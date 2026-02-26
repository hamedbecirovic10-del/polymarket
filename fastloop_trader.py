#!/usr/bin/env python3
"""
Simmer FastLoop Trading Skill

Trades Polymarket BTC 5-minute fast markets using CEX price momentum.
Default signal: Binance BTCUSDT candles. Agents can customize signal source.
"""

import os
import sys
import json
import math
import argparse
import time
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote

# Force line-buffered stdout for non-TTY environments
sys.stdout.reconfigure(line_buffering=True)

# Optional: Trade Journal integration
try:
    from tradejournal import log_trade
    JOURNAL_AVAILABLE = True
except ImportError:
    JOURNAL_AVAILABLE = False
    def log_trade(*args, **kwargs): pass

# =============================================================================
# Configuration
# =============================================================================

CONFIG_SCHEMA = {
    "entry_threshold": {"default": 0.05, "env": "SIMMER_SPRINT_ENTRY", "type": float},
    "min_momentum_pct": {"default": 0.5, "env": "SIMMER_SPRINT_MOMENTUM", "type": float},
    "max_position": {"default": 5.0, "env": "SIMMER_SPRINT_MAX_POSITION", "type": float},
    "signal_source": {"default": "binance", "env": "SIMMER_SPRINT_SIGNAL", "type": str},
    "lookback_minutes": {"default": 5, "env": "SIMMER_SPRINT_LOOKBACK", "type": int},
    "min_time_remaining": {"default": 0, "env": "SIMMER_SPRINT_MIN_TIME", "type": int},
    "asset": {"default": "BTC", "env": "SIMMER_SPRINT_ASSET", "type": str},
    "window": {"default": "5m", "env": "SIMMER_SPRINT_WINDOW", "type": str},
    "volume_confidence": {"default": True, "env": "SIMMER_SPRINT_VOL_CONF", "type": bool},
    "daily_budget": {"default": 10.0, "env": "SIMMER_SPRINT_DAILY_BUDGET", "type": float},
}

TRADE_SOURCE = "sdk:fastloop"
ASSET_SYMBOLS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}
ASSET_PATTERNS = {"BTC": ["bitcoin up or down"], "ETH": ["ethereum up or down"], "SOL": ["solana up or down"]}

def _load_config(schema, skill_file, config_filename="config.json"):
    from pathlib import Path
    config_path = Path(skill_file).parent / config_filename
    file_cfg = {}
    if config_path.exists():
        try:
            with open(config_path) as f: file_cfg = json.load(f)
        except: pass
    result = {}
    for key, spec in schema.items():
        if key in file_cfg: result[key] = file_cfg[key]
        elif spec.get("env") and os.environ.get(spec["env"]):
            val = os.environ.get(spec["env"])
            type_fn = spec.get("type", str)
            result[key] = val.lower() in ("true", "1", "yes") if type_fn == bool else type_fn(val)
        else: result[key] = spec.get("default")
    return result

cfg = _load_config(CONFIG_SCHEMA, __file__)

# =============================================================================
# API Helpers & Discovery
# =============================================================================

_client = None
def get_client(live=True):
    global _client
    if _client is None:
        from simmer_sdk import SimmerClient
        api_key = os.environ.get("SIMMER_API_KEY")
        venue = os.environ.get("TRADING_VENUE", "polymarket")
        _client = SimmerClient(api_key=api_key, venue=venue, live=live)
    return _client

def _api_request(url, method="GET", data=None, headers=None):
    try:
        req = Request(url, data=json.dumps(data).encode() if data else None, headers=headers or {}, method=method)
        with urlopen(req, timeout=15) as resp: return json.loads(resp.read().decode())
    except Exception as e: return {"error": str(e)}

def get_binance_momentum(symbol="BTCUSDT", lookback=5):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1m&limit={lookback}"
    res = _api_request(url)
    if not res or "error" in res: return None
    p_then, p_now = float(res[0][1]), float(res[-1][4])
    vols = [float(c[5]) for c in res]
    return {
        "momentum_pct": ((p_now - p_then) / p_then) * 100,
        "direction": "up" if p_now > p_then else "down",
        "price_now": p_now, "price_then": p_then,
        "volume_ratio": vols[-1] / (sum(vols)/len(vols))
    }

def discover_markets(asset="BTC", window="5m"):
    url = "https://gamma-api.polymarket.com/markets?limit=20&closed=false&tag=crypto"
    res = _api_request(url)
    if not res or "error" in res: return []
    return [m for m in res if any(p in m.get("question","").lower() for p in ASSET_PATTERNS[asset]) and f"-{window}-" in m.get("slug","")]

# =============================================================================
# Strategy Execution
# =============================================================================

def run_fast_market_strategy(dry_run=True, quiet=False):
    if not quiet: print(f"\n⚡ Checking Markets... {datetime.now().strftime('%H:%M:%S')}")
    
    momentum = get_binance_momentum(ASSET_SYMBOLS[cfg["asset"]], cfg["lookback_minutes"])
    if not momentum or abs(momentum["momentum_pct"]) < cfg["min_momentum_pct"]:
        if not quiet: print("⏸ Signal too weak.")
        return

    markets = discover_markets(cfg["asset"], cfg["window"])
    if not markets: return

    target = markets[0]
    side = "yes" if momentum["direction"] == "up" else "no"
    
    if not quiet: print(f"🚀 Signal: {side.upper()} on {target['question']}")
    
    try:
        client = get_client(live=not dry_run)
        res = client.import_market(f"https://polymarket.com/event/{target['slug']}")
        mid = res.get("market_id")
        if mid:
            trade = client.trade(market_id=mid, side=f"buy_{side}", amount=cfg["max_position"])
            print(f"✅ Trade placed: {trade.trade_id}")
    except Exception as e: print(f"❌ Error: {e}")

# =============================================================================
# 24/7 Continuous Loop
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()

    print(f"🤖 Starting Original 800-line Strategy ({'LIVE' if args.live else 'PAPER'})")
    while True:
        try:
            run_fast_market_strategy(dry_run=(not args.live))
        except Exception as e:
            print(f"Loop Error: {e}")
        
        # Poll every 30 seconds (no WebSocket needed)
        time.sleep(30)
