"""
Crypto signal alerts -> Telegram
- Watches your core coins + the top coins by 24h trading volume on Binance
- Reads free public candle data (no Binance API key needed)
- Calculates RSI(14) and EMA(9)/EMA(21) on 1-hour candles
- Sends ONE combined Telegram message per run if any BUY/SELL signal appears
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
CORE_SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]
TOP_N = 10               # also scan the top N USDT pairs by 24h volume (0 = off)
CANDLE = "1h"            # candle size
RSI_BUY, RSI_SELL = 30, 70
CHECK_MINUTES = 60       # how often this script runs (must match your schedule)
# Public market-data host (works in more countries than api.binance.com)
BASE_URL = "https://data-api.binance.vision"
# ---------------------------------------------

# Coins that stay near $1 (nothing to trade) are skipped by the scanner
STABLES = {"USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDP", "USD1", "XUSD",
           "RLUSD", "PYUSD", "BFUSD", "AEUR", "EUR", "EURI", "TRY", "BRL"}

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def send_telegram(text):
    if not TOKEN or not CHAT_ID:
        print("[no telegram set up]\n" + text)
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    r = requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=15)
    if not r.ok:
        print("Telegram error:", r.text)


def get_top_symbols(n):
    """Top n USDT pairs by 24h quote volume, skipping stablecoins and leveraged tokens."""
    r = requests.get(f"{BASE_URL}/api/v3/ticker/24hr", timeout=20)
    r.raise_for_status()
    rows = []
    for t in r.json():
        s = t["symbol"]
        if not s.endswith("USDT"):
            continue
        base = s[:-4]
        if base in STABLES or base.endswith(("UP", "DOWN")):
            continue
        rows.append((float(t["quoteVolume"]), s))
    rows.sort(reverse=True)
    return [s for _, s in rows[:n]]


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
    """Returns a list of (BUY/SELL, text) signals for this coin."""
    candles = get_candles(symbol)
    closed = candles[:-1]                 # drop the still-open candle
    closes = [float(c[4]) for c in closed]
    close_time = closed[-1][6] / 1000     # when the last closed candle ended

    # Only react to a candle that closed since the previous check,
    # so each signal is reported once instead of repeating.
    if time.time() - close_time > CHECK_MINUTES * 60:
        return []

    r = rsi(closes)
    r_prev = rsi(closes[:-1])
    e9, e21 = ema(closes, 9), ema(closes, 21)
    cross_up = e9[-2] <= e21[-2] and e9[-1] > e21[-1]
    cross_down = e9[-2] >= e21[-2] and e9[-1] < e21[-1]
    price = closes[-1]

    buy, sell = [], []
    if r < RSI_BUY <= r_prev:             # RSI just ENTERED the oversold zone
        buy.append(f"RSI {r:.1f} just fell below {RSI_BUY}")
    if cross_up:
        buy.append("EMA9 crossed above EMA21")
    if r > RSI_SELL >= r_prev:            # RSI just ENTERED the overbought zone
        sell.append(f"RSI {r:.1f} just rose above {RSI_SELL}")
    if cross_down:
        sell.append("EMA9 crossed below EMA21")

    print(f"{symbol}: price={price} rsi={r:.1f}")
    signals = []
    if buy:
        signals.append(("BUY", f"{symbol}  price {price}\n   " + "; ".join(buy)))
    if sell:
        signals.append(("SELL", f"{symbol}  price {price}\n   " + "; ".join(sell)))
    return signals


def run_once():
    symbols = list(CORE_SYMBOLS)
    if TOP_N > 0:
        try:
            for s in get_top_symbols(TOP_N):
                if s not in symbols:
                    symbols.append(s)
        except Exception as e:
            print(f"Top-coin scan error (using core list only): {e}")

    print("Checking:", ", ".join(symbols))
    buys, sells = [], []
    for s in symbols:
        try:
            for kind, text in check_symbol(s):
                (buys if kind == "BUY" else sells).append(text)
        except Exception as e:
            print(f"{s} error: {e}")

    if not buys and not sells:
        print("No new signals this run.")
        return

    parts = []
    if buys:
        parts.append("BUY signals:\n" + "\n".join(buys))
    if sells:
        parts.append("SELL signals:\n" + "\n".join(sells))
    parts.append("(Alerts only, not financial advice.)")
    send_telegram("\n\n".join(parts))


if __name__ == "__main__":
    if os.environ.get("LOOP") == "1":
        while True:
            run_once()
            time.sleep(CHECK_MINUTES * 60)
    else:
        run_once()
