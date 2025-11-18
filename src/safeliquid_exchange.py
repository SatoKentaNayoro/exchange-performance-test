import json
import os
import time
from decimal import Decimal

import requests
import asyncio
from collections import deque

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

        abi_path = os.path.join(os.path.dirname(__file__), "../abis/PerpMarketAbi.json")
        with open(abi_path, "r") as f:
            abi = json.load(f)

        self.api = PerpApi(
            rpc="http://192.168.200.11:9923",
            market_id=market_id,
            abi=abi
        )

        latest_order_id = self.fetch_first_order_id_from_api(self.sub_account, market_id)
        self.logger.info(f"latest_order_id: {latest_order_id}")
        self.latest_order_id = latest_order_id
        self.nonce_queue = deque()
        self.nonce_lock = asyncio.Lock()
        current_nonce = self.api.web3.eth.get_transaction_count(self.account.address)
        for i in range(1000):
            self.nonce_queue.append(current_nonce + i)

    def fetch_first_order_id_from_api(self, address, market_id):
        """
        xbit testnet API
        :param address: str
        :param market_id: int
        :return: int or None
        """
        url = f"https://testnet.xbit.finance/perp/blockchain/perp/user-orders?address={address}&market_id={market_id}&page_number=1&pageSize=1000"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", {}).get("items", [])
        if items:
            return items[0].get("order_id", 0)
        return 0

    def get_next_nonce(self):
        return self.nonce_queue.popleft()

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
                price = self.api.amount_from_chain(self.api.perp_markets().oracle_price,
                                                   self.api.b_market.token_a_decimal)
                self.latest_price = price
                self.logger.debug(f"Got current price for {self.api.token.symbol}: {self.latest_price}")

                if not self.latest_price:
                    self.logger.error(f"Failed to get current price for {self.api.token.symbol}")
                    return

            except Exception as e:
                self.logger.error(f"Error getting current price: {e}")
                return

        # Place order 5% below market to avoid execution
        # raw_price = self.latest_price * Decimal(str(1 - self.api.amount_from_chain(self.api.market.max_deviation_bps, 4)))
        raw_price = self.latest_price * Decimal(str(MARKET_OFFSET))
        self.logger.debug(f"Placing order: {ORDER_SIZE_BTC} {self.api.token.symbol} at {raw_price}")

        self.failure_data.place_order_total += 1
        start_time = time.time()

        try:
            # Place order
            # nonce = self.get_next_nonce()
            # self.logger.info(f"Placing order with nonce {nonce}")
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
                nonce=None
            )
            place_latency = time.time() - start_time

            # Always record total request latency
            self.latency_data.place_order_total.append(place_latency)
            if result:
                # Record success-only latency
                self.latency_data.place_order.append(place_latency)

                self.logger.debug(f"Order placed successfully in {place_latency:.4f}s")

                # Try to cancel order immediately
                self.latest_order_id += 1
                latest_order_id = self.latest_order_id
                # Track for cleanup
                self.open_orders.append({
                    'id': latest_order_id,
                    'asset': self.api.token.symbol,
                    'exchange': 'Safeliquid'
                })

                # self.logger.info(f"Before wait, latest_order_id: {latest_order_id}")
                # await self.api.wait_for_order_on_chain(self.sub_account, latest_order_id)
                # Cancel order
                self.logger.info(f"Cancelling order: {latest_order_id}")
                self._cancel_order(latest_order_id)
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

    def _cancel_order(self, order_id: int) -> None:
        """Cancel a specific order and log the result"""
        self.failure_data.cancel_order_total += 1
        cancel_start_time = time.time()

        try:
            # nonce = self.get_next_nonce()
            # self.logger.info(f"Cancelling order with nonce: {nonce}")
            cancel_result = self.api.cancel_order(self.account, self.sub_account, order_id, None)
            cancel_latency = time.time() - cancel_start_time

            # Always record total cancel latency
            self.latency_data.cancel_order_total.append(cancel_latency)

            if cancel_result:
                # Record success-only cancel latency
                self.latency_data.cancel_order.append(cancel_latency)
                self.open_orders = [o for o in self.open_orders if o['id'] != order_id]
                self.logger.debug(f"Order {order_id} cancelled successfully in {cancel_latency:.4f}s")
            else:
                self.failure_data.cancel_order_failures += 1
                error_msg = cancel_result.get("error", "Unknown error") if cancel_result else "No result returned"
                self.logger.error(f"Order cancellation failed for {order_id}: {error_msg}")

        except Exception as e:
            cancel_latency = time.time() - cancel_start_time
            self.latency_data.cancel_order_total.append(cancel_latency)
            self.failure_data.cancel_order_failures += 1
            self.logger.error(f"Error cancelling order {order_id}: {e}", exc_info=True)

    async def cleanup_open_orders(self):
        """Cancel all open Safeliquid orders"""
        if not self.open_orders:
            self.logger.info("No open orders to cleanup")
            return

        self.logger.info(f"Cleaning up {len(self.open_orders)} open orders")

        for order in self.open_orders[:]:
            try:
                # nonce = self.get_next_nonce()
                result = self.api.cancel_order(self.account, self.sub_account, order['id'], None)
                if result:
                    self.open_orders.remove(order)
                    self.logger.info(f"Successfully cancelled order {order['id']} during cleanup")
                else:
                    error_msg = result.get("error", "Unknown error") if result else "No result returned"
                    self.logger.warning(f"Failed to cancel order {order['id']} during cleanup: {error_msg}")
            except Exception as e:
                self.logger.error(f"Error during cleanup of order {order['id']}: {e}", exc_info=True)

        if self.open_orders:
            self.logger.warning(f"Failed to cleanup {len(self.open_orders)} orders")
        else:
            self.logger.info("All orders cleaned up successfully")
