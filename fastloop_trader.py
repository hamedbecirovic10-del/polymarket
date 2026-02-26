import os
import sys
import json
import websocket
import argparse
from datetime import datetime
from simmer_sdk import SimmerClient

# Your original strategy settings
DEFAULT_CONFIG = {
    "asset": "BTC",
    "window": "5m",
    "max_position": 5.0,
    "min_momentum_pct": 0.5,
}

def load_config():
    if os.path.exists("config.json"):
        with open("config.json", "r") as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    return DEFAULT_CONFIG

class FastLoopBot:
    def __init__(self, live=False, quiet=False):
        self.live = live
        self.quiet = quiet
        self.config = load_config()
        self.client = SimmerClient(
            api_key=os.getenv("SIMMER_API_KEY"),
            venue=os.getenv("TRADING_VENUE", "polymarket"),
            live=live
        )
        # Store last 5 prices to calculate 5m momentum
        self.price_history = [] 

    def on_message(self, ws, message):
        data = json.loads(message)
        candle = data['k']
        current_price = float(candle['c'])
        is_candle_closed = candle['x']

        # We update our history and check strategy every time a candle closes (every 1m)
        # For true 100ms response, you can remove 'is_candle_closed' and check every tick
        if is_candle_closed:
            self.price_history.append(current_price)
            if len(self.price_history) > 5:
                self.price_history.pop(0)

            if len(self.price_history) == 5:
                self.check_strategy(current_price)

    def check_strategy(self, current_price):
        prev_price = self.price_history[0]
        momentum = ((current_price - prev_price) / prev_price) * 100
        
        if not self.quiet:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Price: ${current_price:,.2f} | Momentum: {momentum:+.3f}%")

        if abs(momentum) >= self.config['min_momentum_pct']:
            self.execute_trade(momentum)

    def execute_trade(self, momentum):
        side = "buy_yes" if momentum > 0 else "buy_no"
        try:
            markets = self.client.get_fast_markets(asset=self.config['asset'], window=self.config['window'])
            active = [m for m in markets if m.get('active')]
            if active:
                target = active[0]
                order = self.client.create_fast_market_order(
                    market_id=target['id'],
                    side=side,
                    amount=self.config['max_position']
                )
                print(f"🚀 TRADE EXECUTED: {side.upper()} | Order ID: {order.get('id')}")
        except Exception as e:
            print(f"❌ Trade Error: {e}")

    def on_error(self, ws, error):
        print(f"WebSocket Error: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        print("### WebSocket Closed - Restarting... ###")
        self.run() # Auto-restart on disconnect

    def run(self):
        symbol = self.config['asset'].lower() + "usdt"
        socket = f"wss://stream.binance.com:9443/ws/{symbol}@kline_1m"
        
        ws = websocket.WebSocketApp(socket,
                                  on_message=self.on_message,
                                  on_error=self.on_error,
                                  on_close=self.on_close)
        ws.run_forever()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    bot = FastLoopBot(live=args.live, quiet=args.quiet)
    print(f"📡 Real-time WebSocket Bot Started ({'LIVE' if args.live else 'PAPER'} mode)")
    bot.run()
