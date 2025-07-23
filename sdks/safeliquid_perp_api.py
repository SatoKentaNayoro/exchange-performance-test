from dataclasses import dataclass
from typing import List, Optional
from decimal import Decimal
from web3 import Web3
from decimal import Decimal

PERP_CONTRACT_ADDRESS = "0x000000000000000000000000000000000000044E"

@dataclass
class PerpPosition:
    market_id: int
    is_long: bool
    base_asset_amount: int
    entry_price: int
    leverage: int
    last_funding_rate: int
    isolated_margin: int
    version: int
    unrealized_pnl: int
    realized_pnl: int
    funding_payment: int
    owner: str
    take_profit: int
    stop_loss: int

@dataclass
class PerpOrder:
    order_id: int
    owner: str
    market_id: int
    is_long: bool
    size: int
    price: int
    order_type: int
    create_time: int
    leverage: int
    isolated: bool
    margin: int
    slippage: Optional[int]
    status: int
    size_filled: int
    size_remain: int
    margin_remain: int
    margin_used: int
    take_profit: Optional[int] = None
    stop_loss: Optional[int] = None

@dataclass
class ActiveOrder:
    owner: str
    market_id: int
    order_side: int
    order_type: int
    order_id: int
    price: int
    created_at: int

@dataclass
class Token:
    address: str
    decimals: int
    symbol: str

@dataclass
class PerpMarket:
    id: int
    name: str
    token_a: str
    token_a_address: str
    token_a_decimal: int
    token_b_market_id: int
    network: str
    height: int
    cumulative_funding_rate: int
    last_cacl_funding_rate_time: int
    oracle_price: int
    max_deviation_bps: int
    liquid_spread_bps: int
    fallback_if_dlob_price_invalid: bool
    maintenance_margin_ratio: int

class PerpApi:
    def __init__(self, rpc: str, market_id: int, abi: list):
        self.web3 = Web3(Web3.HTTPProvider(rpc))
        self.market_id = market_id
        self.abi = abi
        self.contract = self.web3.eth.contract(address=PERP_CONTRACT_ADDRESS, abi=abi)
        self.market = self.perp_markets()
        self.b_market = self.perp_b_markets()
        self.token = Token(address=self.market.token_a_address, decimals=self.market.token_a_decimal, symbol=self.market.token_a)

    def place_perp_order(self, account, subaccount: str, is_long: bool, size: float, price: float, order_type: int, leverage: int, take_profit: float, stop_loss: float):
        txn = self.contract.functions.placePerpOrder(
            subaccount,
            self.market_id,
            is_long,
            self.amount_to_chain(size),
            self.amount_to_chain(price, self.b_market.token_a_decimal),
            order_type,
            leverage,
            self.amount_to_chain(take_profit, self.b_market.token_a_decimal),
            self.amount_to_chain(stop_loss, self.b_market.token_a_decimal)
        ).build_transaction({
            'from': account.address,
            'nonce': self.web3.eth.get_transaction_count(account.address),
        })
        gas = self.web3.eth.estimate_gas(txn)
        txn['gas'] = gas * 2
        signed = account.sign_transaction(txn)
        tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
        return tx_hash

    def cancel_order(self, account, subaccount: str, order_id: int):
        txn = self.contract.functions.cancelOrder(
            subaccount,
            self.market_id,
            order_id
        ).build_transaction({
            'from': account.address,
            'nonce': self.web3.eth.get_transaction_count(account.address),
        })
        gas = self.web3.eth.estimate_gas(txn)
        txn['gas'] = gas * 2
        signed = account.sign_transaction(txn)
        tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
        return tx_hash

    def close_position(self, account, subaccount: str, price: float, slippage: int):
        txn = self.contract.functions.closePosition(
            subaccount,
            self.market_id,
            self.amount_to_chain(price, self.b_market.token_a_decimal),
            slippage
        ).build_transaction({
            'from': account.address,
            'nonce': self.web3.eth.get_transaction_count(account.address),
        })
        gas = self.web3.eth.estimate_gas(txn)
        txn['gas'] = gas * 2
        signed = account.sign_transaction(txn)
        tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
        return tx_hash

    def set_profit_and_loss_point(self, account, subaccount: str, take_profit: float, stop_loss: float):
        txn = self.contract.functions.setProfitAndLossPoint(
            subaccount,
            self.market_id,
            self.amount_to_chain(take_profit, self.b_market.token_a_decimal),
            self.amount_to_chain(stop_loss, self.b_market.token_a_decimal)
        ).build_transaction({
            'from': account.address,
            'nonce': self.web3.eth.get_transaction_count(account.address),
        })
        gas = self.web3.eth.estimate_gas(txn)
        txn['gas'] = gas * 2
        signed = account.sign_transaction(txn)
        tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
        return tx_hash

    def deposit(self, account, subaccount: str, amount: int):
        txn = self.contract.functions.deposit(
            subaccount,
            self.market_id,
            amount
        ).build_transaction({
            'from': account.address,
            'nonce': self.web3.eth.get_transaction_count(account.address),
        })
        gas = self.web3.eth.estimate_gas(txn)
        txn['gas'] = gas * 2
        signed = account.sign_transaction(txn)
        tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
        return tx_hash

    def calc_value(self, price: str, amount: str, leverage: int) -> int:
        receive = Decimal(amount) * Decimal(price) * Decimal(leverage) * Decimal(10 ** self.token.decimals)
        return int(receive.to_integral_value(rounding='ROUND_DOWN'))

    def withdraw(self, account, subaccount: str, amount: int):
        txn = self.contract.functions.withdraw(
            subaccount,
            self.market_id,
            amount
        ).build_transaction({
            'from': account.address,
            'nonce': self.web3.eth.get_transaction_count(account.address),
        })
        gas = self.web3.eth.estimate_gas(txn)
        txn['gas'] = gas * 2
        signed = account.sign_transaction(txn)
        tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
        return tx_hash

    def user_active_orders(self, user: str) -> List[ActiveOrder]:
        result = self.contract.functions.userActiveOrders(user).call()
        return [ActiveOrder(*item) for item in result]

    def user_perp_positions(self, user: str) -> PerpPosition:
        result = self.contract.functions.userPerpPositions(user, self.market_id).call()
        print(result)
        return PerpPosition(*result)

    def order_info(self, user: str, order_id: int) -> PerpOrder:
        result = self.contract.functions.orderInfo(user, order_id).call()
        return PerpOrder(*result)

    def perp_markets(self) -> PerpMarket:
        result = self.contract.functions.perpMarkets(self.market_id).call()
        return PerpMarket(*result)

    def perp_b_markets(self) -> PerpMarket:
        result = self.contract.functions.perpMarkets(self.market.token_b_market_id).call()
        return PerpMarket(*result)

    def active_pos_for_market(self) -> List[PerpPosition]:
        result = self.contract.functions.activePosForMarket(self.market_id).call()
        return [PerpPosition(*item) for item in result]

    def amount_to_chain(self, value, decimals=None):
        """
        :param value: float or str
        :param decimals: int, optional
        :return: int
        """
        if decimals is None:
            decimals = self.token.decimals
        if float(value) == 0:
            return 0
        return int(Decimal(value) * Decimal(10 ** decimals))

    def amount_from_chain(self, value, decimals=None):
        """
        :param value: int
        :param decimals: int, optional
        :return: Decimal
        """
        if decimals is None:
            decimals = self.token.decimals
        if int(value) == 0:
            return Decimal(0)
        return Decimal(value) / Decimal(10 ** decimals)