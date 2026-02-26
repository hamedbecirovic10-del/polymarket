import os
import sys
import json
import time
import argparse
from datetime import datetime
from simmer_sdk import SimmerClient

# Configuration Defaults (Exactly like your original strategy)
DEFAULT_CONFIG = {
    "asset": "BTC",
    "window": "5m",
    "max_position": 5.0,
    "daily_budget": 10.0,
    "min_momentum_pct": 0.5,
    "entry_threshold": 0.05,
    "volume_confidence": True,
    "signal_source": "binance"
}

def load_config():
    if os.path.exists("config.json"):
        with open("config.json", "r") as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    return DEFAULT_CONFIG

def get_binance_momentum(symbol="BTCUSDT"):
    """Fetch 1m momentum from Binance"""
    import requests
    try:
        # Fetches the last 5 minutes of 1-minute candles
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1m&limit=5"
        res = requests.get(url, timeout=10).json()
        close_prices = [float(k[4]) for k in res]
        current = close_prices[-1]
        prev = close_prices[0]
        momentum = ((current - prev) / prev) * 100
        return momentum
    except Exception as e:
        print(f"Error fetching signal: {e}")
        return 0.0

def run_fast_market_strategy(dry_run=True, quiet=False):
    config = load_config()
    api_key = os.getenv("SIMMER_API_KEY")
    venue = os.getenv("TRADING_VENUE", "polymarket")
    
    if not api_key:
        print("❌ Error: SIMMER_API_KEY environment variable not set")
        return

    # Initialize the client (Handles the eth-account signing locally)
    client = SimmerClient(api_key=api_key, venue=venue, live=(not dry_run))
    
    if not quiet:
        print(f"\n⚡ Simmer Strategy Loop | {datetime.now().strftime('%H:%M:%S')}")
        print(f"Checking {config['asset']} {config['window']} markets...")

    # 1. Get Signal
    momentum = get_binance_momentum()
    if not quiet:
        print(f"Current 5m Momentum: {momentum:+.3f}%")

    # Only trade if momentum is strong enough
    if abs(momentum) < config['min_momentum_pct']:
        if not quiet: print(f"⏸ Momentum too weak (< {config['min_momentum_pct']}%). Skipping.")
        return

    side = "buy_yes" if momentum > 0 else "buy_no"

    # 2. Find Markets via Simmer SDK
    markets = client.get_fast_markets(asset=config['asset'], window=config['window'])
    active_markets = [m for m in markets if m.get('active')]

    if not active_markets:
        if not quiet: print("📭 No active markets found.")
        return

    # 3. Execute Trade
    target_market = active_markets[0]
    market_id = target_market['id']
    
    if not quiet:
        print(f"🚀 Signal detected! {side.upper()} on Market: {target_market['question']}")

    try:
        order = client.create_fast_market_order(
            market_id=market_id,
            side=side,
            amount=config['max_position']
        )
        print(f"✅ Order placed: {order.get('id', 'Unknown ID')}")
    except Exception as e:
        print(f"❌ Execution failed: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Execute real trades")
    parser.add_argument("--quiet", action="store_true", help="Minimize logs")
    args = parser.parse_args()

    if not args.live:
        print("⚠️  RUNNING IN PAPER MODE (Dry Run). Use --live for real trading.")
    else:
        print("💰 REAL TRADING ENABLED. Stay safe.")

    # THE INFINITE LOOP (Checks the market every 60 seconds)
    while True:
        try:
            run_fast_market_strategy(dry_run=(not args.live), quiet=args.quiet)
        except Exception as e:
            print(f"CRITICAL ERROR: {e}")
        
        # Wait 60 seconds before checking the market again
        time.sleep(1)
