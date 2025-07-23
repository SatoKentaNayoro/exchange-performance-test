#!/usr/bin/env python3
import os
import json

from dotenv import load_dotenv
from web3 import Web3

from sdks.safeliquid_perp_api import PerpApi, Token, PerpPosition, PerpOrder, ActiveOrder, PerpMarket

load_dotenv()

def mock_token():
    return Token(address="0x86bde473a14bc71e5c145bb9ee723ef7c3ccce6f", decimals=18, symbol="ETH")

def mock_abi():
    abi_path = os.path.join(os.path.dirname(__file__), "abis/perp_abi.json")
    with open(abi_path, "r") as f:
        abi = json.load(f)
    return abi

api = PerpApi(
    rpc="https://ultra-test-node-rpc.bool.network",
    market_id=1,
    token=mock_token(),
    abi=mock_abi()
)

private_key = os.environ.get("SAFELIQUID_PRIVATE_KEY")
if not private_key:
    raise ValueError("SAFELIQUID_PRIVATE_KEY")
account = Web3().eth.account.from_key(private_key)
sub_account = "0x3db0AD243A3aF4cE5e5a9bcf0B5eA25E15F984DE"

def test_place_perp_order():
    price = api.amount_from_chain(api.market.oracle_price, api.b_market.token_a_decimal) - 100
    print(price)
    tx = api.place_perp_order(account, sub_account, True, 0.1, price, 0, 10, 0, 0)
    print("tx hash:", "0x" + tx.hex())

def test_cancel_order():
    tx = api.cancel_order(account, sub_account, 5)
    print("tx hash:", "0x" + tx.hex())

def test_close_position():
    price = api.amount_from_chain(api.market.oracle_price, api.b_market.token_a_decimal)
    tx = api.close_position(account, sub_account, price, 10)
    print("tx hash:", "0x" + tx.hex())

def test_set_profit_and_loss_point():
    price = api.amount_from_chain(api.market.oracle_price, api.b_market.token_a_decimal)
    tx = api.set_profit_and_loss_point(account, sub_account, price + 100, price - 100)
    print("tx hash:", "0x" + tx.hex())

def test_deposit():
    tx = api.deposit(account, "0x3db0AD243A3aF4cE5e5a9bcf0B5eA25E15F984DE", 1000000000000000000)
    print("tx hash:", "0x" + tx.hex())

def test_calc_value():
    api.token.decimals = 18
    val = api.calc_value("2", "3", 4)
    assert isinstance(val, int)
    assert val > 0

def test_withdraw():
    print(account.address)
    tx = api.withdraw(account, "0x3db0AD243A3aF4cE5e5a9bcf0B5eA25E15F984DE", 100000000000000000)
    print("tx hash:", "0x" + tx.hex())

def test_user_active_orders():
    orders = api.user_active_orders(account.address)
    print(orders)
    assert isinstance(orders, list)
    assert isinstance(orders[0], ActiveOrder)

def test_user_perp_positions():
    pos = api.user_perp_positions(Web3.to_checksum_address("0x3db0AD243A3aF4cE5e5a9bcf0B5eA25E15F984DE")) # subaccount address
    print(pos)
    assert isinstance(pos, PerpPosition)

def test_order_info():
    order = api.order_info(Web3.to_checksum_address("0x11a5c5b461d9b8a70f75950e3937f7d58c0b49ab"), 83490)
    print(order)
    assert isinstance(order, PerpOrder)

def test_perp_market():
    market = api.perp_markets()
    print(market)
    assert isinstance(market, PerpMarket)

def test_active_pos_for_market():
    positions = api.active_pos_for_market()
    print(positions)
    assert isinstance(positions, list)
    assert isinstance(positions[0], PerpPosition)

if __name__ == "__main__":
    # test_perp_market()
    # test_active_pos_for_market()
    # test_order_info()
    # test_user_perp_positions()
    # test_user_active_orders()
    # test_withdraw()
    # test_calc_value()
    # test_deposit()
    # test_place_perp_order()
    # test_cancel_order()
    # test_set_profit_and_loss_point()
    test_close_position()