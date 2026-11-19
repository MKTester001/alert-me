"""
Crypto signal alerts -> Telegram
- Reads free public candle data from Binance (no API key needed)
- Calculates RSI(14) and EMA(9)/EMA(21) on 1-hour candles
- Sends a Telegram message when a BUY or SELL signal appears
NOTIFICATIONS ONLY. It never trades. Signals are NOT guaranteed to be profitable.

Setup:
  pip install requests
  Set environment variables TELEGRAM_TOKEN and TELEGRAM_CHAT_ID
Run once:        python crypto_alerts.py
Run in a loop:   LOOP=1 python crypto_alerts.py
"""
import os
import time
import requests

# ---------- settings you can change ----------
SYMBOLS = ["SOLUSDT", "XRPUSDT", "DOGEUSDT", "SHIBUSDT"]
CANDLE = "1h"            # candle size
RSI_BUY, RSI_SELL = 30, 70
CHECK_MINUTES = 15       # how often this script runs (must match your schedule)
# Public market-data host (works in more countries than api.binance.com)
BASE_URL = "https://data-api.binance.vision"
# ---------------------------------------------

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def send_telegram(text):
    if not TOKEN or not CHAT_ID:
        print("[no telegram set up]", text)
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    r = requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=15)
    if not r.ok:
        print("Telegram error:", r.text)


def get_candles(symbol):
    r = requests.get(
        f"{BASE_URL}/api/v3/klines",
        params={"symbol": symbol, "interval": CANDLE, "limit": 100},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def ema(values, period):
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(values, period=14):
    gains, losses = [], []
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    if avg_l == 0:
        return 100.0
    return 100 - 100 / (1 + avg_g / avg_l)


def check_symbol(symbol):
    candles = get_candles(symbol)
    closed = candles[:-1]                 # drop the still-open candle
    closes = [float(c[4]) for c in closed]
    close_time = closed[-1][6] / 1000     # when the last closed candle ended

    # Only react to a candle that closed since the previous check,
    # so you get one alert instead of repeats.
    if time.time() - close_time > CHECK_MINUTES * 60:
        return

    r = rsi(closes)
    e9, e21 = ema(closes, 9), ema(closes, 21)
    cross_up = e9[-2] <= e21[-2] and e9[-1] > e21[-1]
    cross_down = e9[-2] >= e21[-2] and e9[-1] < e21[-1]
    price = closes[-1]

    reasons_buy, reasons_sell = [], []
    if r < RSI_BUY:
        reasons_buy.append(f"RSI {r:.1f} (oversold)")
    if cross_up:
        reasons_buy.append("EMA9 crossed above EMA21")
    if r > RSI_SELL:
        reasons_sell.append(f"RSI {r:.1f} (overbought)")
    if cross_down:
        reasons_sell.append("EMA9 crossed below EMA21")

    if reasons_buy:
        send_telegram(f"BUY signal {symbol}\nPrice: {price}\n" + "\n".join(reasons_buy))
    if reasons_sell:
        send_telegram(f"SELL signal {symbol}\nPrice: {price}\n" + "\n".join(reasons_sell))
    print(f"{symbol}: price={price} rsi={r:.1f}")


def run_once():
    for s in SYMBOLS:
        try:
            check_symbol(s)
        except Exception as e:
            print(f"{s} error: {e}")


if __name__ == "__main__":
    if os.environ.get("LOOP") == "1":
        while True:
            run_once()
            time.sleep(CHECK_MINUTES * 60)
    else:
        run_once()
