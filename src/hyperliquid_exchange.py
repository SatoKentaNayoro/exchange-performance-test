import time
import eth_account
from eth_account.signers.local import LocalAccount
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from .base_exchange import BaseExchange, APIMode
from .config import HYPERLIQUID_CONFIG, ORDER_SIZE_BTC, MARKET_OFFSET


class HyperliquidExchange(BaseExchange):
    """Hyperliquid REST API implementation"""
    
    def __init__(self, wallet_address: str, private_key: str, asset: str | None = None):
        super().__init__("Hyperliquid", APIMode.REST)
        
        self.logger.info("Initializing Hyperliquid exchange")
        
        self.wallet_address = wallet_address
        self.private_key = private_key
        self.asset = asset or HYPERLIQUID_CONFIG['asset']
        self.info = Info(constants.TESTNET_API_URL, skip_ws=True)
        
        # Create LocalAccount for signing
        self.account: LocalAccount = eth_account.Account.from_key(private_key)
        self.exchange = Exchange(self.account, constants.TESTNET_API_URL, account_address=wallet_address)

    def _get_tick_size(self, asset: str = "BTC") -> float:
        """Get the correct tick size for Hyperliquid assets"""
        if asset == "BTC":
            return HYPERLIQUID_CONFIG['tick_size']
        return HYPERLIQUID_CONFIG['default_tick_size']

    def _round_to_tick_size(self, price: float, asset: str = "BTC") -> float:
        """Round price to the nearest valid tick size"""
        tick_size = self._get_tick_size(asset)
        return round(price / tick_size) * tick_size

    async def test_order_latency(self) -> None:
        """Test Hyperliquid order placement and cancellation latency"""
        if not self.exchange:
            self.logger.warning("No exchange available for order test")
            return
            
        # Get current price directly from info API
        if not self.latest_price:
            try:
                self.logger.debug(f"Getting current price for {self.asset}")
                # Get the current market price
                meta = self.info.meta()
                universe = meta.get('universe', [])
                
                for token_info in universe:
                    if token_info.get('name') == self.asset:
                        # Get the mark price (current market price)
                        all_mids = self.info.all_mids()
                        if self.asset in all_mids:
                            self.latest_price = float(all_mids[self.asset])
                            self.logger.debug(f"Got current price for {self.asset}: {self.latest_price}")
                            break
                
                if not self.latest_price:
                    self.logger.error(f"Failed to get current price for {self.asset}")
                    return
                    
            except Exception as e:
                self.logger.error(f"Error getting current price: {e}")
                return
        
        # Place order 5% below market to avoid execution
        raw_price = self.latest_price * MARKET_OFFSET
        price = self._round_to_tick_size(raw_price, self.asset)
        
        self.logger.debug(f"Placing order: {ORDER_SIZE_BTC} {self.asset} at {price}")
        
        self.failure_data.place_order_total += 1
        start_time = time.time()
        
        try:
            # Place order
            result = self.exchange.order(
                name=self.asset,
                is_buy=True,
                sz=ORDER_SIZE_BTC,
                limit_px=price,
                order_type={"limit": {"tif": "Gtc"}},
                reduce_only=False
            )
            place_latency = time.time() - start_time
            
            # Always record total request latency
            self.latency_data.place_order_total.append(place_latency)
            
            if result and result.get("status") == "ok":
                # Record success-only latency
                self.latency_data.place_order.append(place_latency)
                
                self.logger.debug(f"Order placed successfully in {place_latency:.4f}s")
                
                # Try to cancel order immediately
                statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                if statuses and "resting" in statuses[0]:
                    order_id = statuses[0]["resting"]["oid"]
                    
                    # Track for cleanup
                    self.open_orders.append({
                        'id': order_id,
                        'asset': self.asset,
                        'exchange': 'hyperliquid'
                    })
                    
                    # Cancel order
                    await self._cancel_order(order_id)
                else:
                    self.failure_data.place_order_failures += 1
                    self.logger.warning("Order status not resting, cannot cancel")
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
    
    async def _cancel_order(self, order_id: str) -> None:
        """Cancel a specific order and log the result"""
        self.failure_data.cancel_order_total += 1
        cancel_start_time = time.time()
        
        try:
            cancel_result = self.exchange.cancel(self.asset, int(order_id))
            cancel_latency = time.time() - cancel_start_time
            
            # Always record total cancel latency
            self.latency_data.cancel_order_total.append(cancel_latency)
            
            if cancel_result and cancel_result.get("status") == "ok":
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
        """Cancel all open Hyperliquid orders"""
        if not self.open_orders:
            self.logger.info("No open orders to cleanup")
            return
        
        self.logger.info(f"Cleaning up {len(self.open_orders)} open orders")
        
        for order in self.open_orders[:]:
            try:
                result = self.exchange.cancel(order['asset'], int(order['id']))
                if result and result.get("status") == "ok":
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
