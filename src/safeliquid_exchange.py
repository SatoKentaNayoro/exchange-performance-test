import asyncio
import json
import os
import time
from decimal import Decimal

import requests

from sdks.safeliquid_perp_api import PerpApi
from .base_exchange import BaseExchange, APIMode
from .config import ORDER_SIZE_BTC, MARKET_OFFSET, SAFELIQUID_CONFIG
from web3 import Web3


class SafeliquidExchange(BaseExchange):
    """Safeliquid REST API implementation"""

    def __init__(self, sub_account: str, private_key: str, market_id: int):
        super().__init__("Safeliquid", APIMode.REST)

        self.logger.info("Initializing Safeliquid exchange")

        self.sub_account = sub_account
        self.account = Web3().eth.account.from_key(private_key)

        abi_path = os.path.join(os.path.dirname(__file__), "../abis/perp_abi.json")
        with open(abi_path, "r") as f:
            abi = json.load(f)

        self.api = PerpApi(
            rpc="http://192.168.200.11:9939",
            market_id=market_id,
            abi=abi
        )

        latest_order_id = self.fetch_first_order_id_from_api(self.sub_account, market_id)
        self.latest_order_id = latest_order_id
        self.next_nonce = self.api.web3.eth.get_transaction_count(self.account.address)
        self.nonce_lock = asyncio.Lock()

    def fetch_first_order_id_from_api(self, address, market_id):
        """
        xbit testnet API
        :param address: str
        :param market_id: int
        :return: int or None
        """
        url = f"http://192.168.36.15:8088/blockchain/perp/user-orders?address={address}&market_id={market_id}&page_number=1&pageSize=1000"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", {}).get("items", [])
        if items:
            return items[0].get("order_id", 0)
        return 0

    def _get_tick_size(self, asset: str = "BTC") -> float:
        """Get the correct tick size for Safeliquid assets"""
        if asset == "BTC":
            return SAFELIQUID_CONFIG['tick_size']
        return SAFELIQUID_CONFIG['default_tick_size']

    def _round_to_tick_size(self, price: float, asset: str = "BTC") -> float:
        """Round price to the nearest valid tick size"""
        tick_size = self._get_tick_size(asset)
        return round(price / tick_size) * tick_size

    async def test_order_latency(self) -> None:
        """Test Safeliquid order placement and cancellation latency"""
        if not self.api:
            self.logger.warning("No api available for order test")
            return

        # Get current price directly from info API
        if not self.latest_price:
            try:
                self.logger.debug(f"Getting current price for {self.api.token.symbol}")
                # Get the current market price
                price = self.api.amount_from_chain(self.api.perp_markets().oracle_price, self.api.b_market.token_a_decimal)
                self.latest_price = price
                self.logger.debug(f"Got current price for {self.api.token.symbol}: {self.latest_price}")

                if not self.latest_price:
                    self.logger.error(f"Failed to get current price for {self.api.token.symbol}")
                    return

            except Exception as e:
                self.logger.error(f"Error getting current price: {e}")
                return

        raw_price = self.latest_price * Decimal(str(MARKET_OFFSET))
        self.logger.debug(f"Placing order: {ORDER_SIZE_BTC} {self.api.token.symbol} at {raw_price}")

        self.failure_data.place_order_total += 1
        start_time = time.time()

        try:
            async with self.nonce_lock:
                nonce = self.next_nonce
                result = self.api.place_perp_order(
                    account=self.account,
                    subaccount=self.sub_account,
                    is_long=True,
                    size=ORDER_SIZE_BTC,
                    price=raw_price,
                    order_type=0,
                    leverage=10,
                    take_profit=0,
                    stop_loss=0,
                    nonce=nonce
                )
                self.next_nonce += 1
            place_latency = time.time() - start_time

            # Always record total request latency
            self.latency_data.place_order_total.append(place_latency)
            if result:
                # Record success-only latency
                self.latency_data.place_order.append(place_latency)

                self.logger.debug(f"Order placed successfully in {place_latency:.4f}s")

                # Try to cancel order immediately
                self.latest_order_id += 1
                # Track for cleanup
                self.open_orders.append({
                    'id': self.latest_order_id,
                    'asset': self.api.token.symbol,
                    'exchange': 'Safeliquid'
                })

                if self.wait_for_order_on_chain(self.sub_account, self.api.market_id, self.latest_order_id):
                    # Cancel order
                    await self._cancel_order(self.latest_order_id)
                else:
                    self.failure_data.place_order_failures += 1
                    self.logger.error(f"Order placement failed: wait_for_order_on_chain timeout")

            else:
                self.failure_data.place_order_failures += 1
                error_msg = result.get("error", "Unknown error") if result else "No result returned"
                self.logger.error(f"Order placement failed: {error_msg}")

        except Exception as e:
            place_latency = time.time() - start_time
            # Record total request latency even for exceptions
            self.latency_data.place_order_total.append(place_latency)
            self.failure_data.place_order_failures += 1
            self.logger.error(f"Unexpected error during order placement: {e}", exc_info=True)

    async def _cancel_order(self, order_id: int) -> None:
        """Cancel a specific order and log the result"""
        self.failure_data.cancel_order_total += 1
        cancel_start_time = time.time()

        try:
            async with self.nonce_lock:
                nonce = self.next_nonce
                cancel_result = self.api.cancel_order(self.account, self.sub_account, order_id, nonce)
                self.next_nonce += 1
            cancel_latency = time.time() - cancel_start_time

            # Always record total cancel latency
            self.latency_data.cancel_order_total.append(cancel_latency)

            if cancel_result:
                self.logger.debug(f"Order {order_id} cancelled successfully in {cancel_latency:.4f}s")
            else:
                self.failure_data.cancel_order_failures += 1
                self.logger.error(f"Order {order_id} cancellation failed: {cancel_result}")
        except Exception as e:
            cancel_latency = time.time() - cancel_start_time
            self.latency_data.cancel_order_total.append(cancel_latency)
            self.failure_data.cancel_order_failures += 1
            self.logger.error(f"Unexpected error during order cancellation: {e}", exc_info=True)

    async def cleanup_open_orders(self):
        """Cancel all open Safeliquid orders"""
        if not self.open_orders:
            self.logger.info("No open orders to cleanup")
        else:
            self.logger.info(f"Cleaning up {len(self.open_orders)} open orders")
            for order in self.open_orders[:]:
                try:
                    async with self.nonce_lock:
                        nonce = self.next_nonce
                        result = self.api.cancel_order(self.account, self.sub_account, order['id'], nonce)
                        self.next_nonce += 1
                    if result:
                        self.logger.info(f"Successfully cancelled order {order['id']} during cleanup")
                    else:
                        error_msg = result.get("error", "Unknown error") if isinstance(result, dict) else str(result)
                        self.logger.warning(f"Failed to cancel order {order['id']} during cleanup: {error_msg}")
                except Exception as e:
                    self.logger.error(f"Error during cleanup of order {order['id']}: {e}", exc_info=True)

        try:
            on_chain_orders = self.api.user_active_orders(self.sub_account)
            self.logger.info(f"Found {len(on_chain_orders)} on-chain active orders for cleanup")
            for order in on_chain_orders:
                try:
                    async with self.nonce_lock:
                        nonce = self.next_nonce
                        result = self.api.cancel_order(self.account, self.sub_account, order.order_id, nonce)
                        self.next_nonce += 1
                    if result:
                        self.logger.info(f"Successfully cancelled on-chain order {order.order_id} during cleanup")
                    else:
                        error_msg = result.get("error", "Unknown error") if isinstance(result, dict) else str(result)
                        self.logger.warning(f"Failed to cancel on-chain order {order.order_id} during cleanup: {error_msg}")
                except Exception as e:
                    self.logger.error(f"Error during cleanup of on-chain order {order.order_id}: {e}", exc_info=True)
        except Exception as e:
            self.logger.error(f"Error fetching on-chain orders for cleanup: {e}", exc_info=True)
        self.logger.info("Cleanup process finished.")

    def wait_for_order_on_chain(self, sub_account, market_id, expected_order_id, timeout=60, interval=0.2):
        start = time.time()
        while time.time() - start < timeout:
            order_id = self.fetch_first_order_id_from_api(sub_account, market_id)
            if order_id == expected_order_id:
                return True
            time.sleep(interval)
        return False