#!/usr/bin/env python3
import asyncio
import os
import threading
import time

from dotenv import load_dotenv

from src.hyperliquid_exchange import HyperliquidExchange
load_dotenv()

address = os.environ.get("HYPERLIQUID_API_WALLET_ADDRESS")
private_key = os.environ.get("HYPERLIQUID_PRIVATE_KEY")

success_count = 0
fail_count = 0
lock = threading.Lock()

def worker(thread_id, results):
    global success_count, fail_count
    start = time.time()
    try:
        exchange = HyperliquidExchange(address, private_key)
        asyncio.run(exchange.test_order_latency())
        with lock:
            success_count += 1
        print(f"thread {thread_id} success")
    except Exception as e:
        with lock:
            fail_count += 1
        print(f"thread {thread_id} failed: {e}")
    end = time.time()
    results[thread_id] = end - start

if __name__ == "__main__":
    threads = []
    results = [0] * 10

    t0 = time.time()
    for i in range(10):
        t = threading.Thread(target=worker, args=(i, results))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()
    t1 = time.time()

    print(f"each thread costs: {results}")
    print(f"total: {t1 - t0:.4f} s")
    print(f"success: {success_count}, failed: {fail_count}")