from flask import Flask
import requests
from datetime import datetime, timezone

app = Flask(__name__)

TOKEN = "8649683072:AAFDTkpO55rO9UGszDIa7cmq3VD9YxerLCE"
CHAT_ID = "8832877679"
SYMBOLS = ["BTC_USDT", "ETH_USDT"]

def send_tg(text):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10
        )
        return r.text
    except Exception as e:
        return str(e)

def get_klines(symbol, interval, limit=60):
    url = "https://api.gateio.ws/api/v4/futures/usdt/candlesticks"
    r = requests.get(url, params={"contract": symbol, "interval": interval, "limit": limit}, timeout=10)
    data = r.json()
    klines = []
    for item in data:
        klines.append({
            "t": int(item["t"]),
            "o": float(item["o"]), "h": float(item["h"]),
            "l": float(item["l"]), "c": float(item["c"]),
            "v": float(item["v"])
        })
    klines.sort(key=lambda x: x["t"])
    return klines

def ema(closes, period):
    if len(closes) < period:
        return [None] * len(closes)
    result = [None] * len(closes)
    result[period-1] = sum(closes[:period]) / period
    mult = 2 / (period + 1)
    for i in range(period, len(closes)):
        result[i] = (closes[i] - result[i-1]) * mult + result[i-1]
    return result

def get_trend(k4h):
    closes = [k["c"] for k in k4h]
    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    if e20[-1] is None or e50[-1] is None:
        return "range"
    close = closes[-1]
    if close > e50[-1] and e20[-1] > e50[-1]:
        return "bullish"
    if close < e50[-1] and e20[-1] < e50[-1]:
        return "bearish"
    return "range"

@app.route("/")
def home():
    return "交易机器人运行中。访问 /scan 触发扫描"

@app.route("/scan")
def scan():
    msg = []
    for symbol in SYMBOLS:
        k1h = get_klines(symbol, "1h", 60)
        k4h = get_klines(symbol, "4h", 60)
        trend = get_trend(k4h)
        close = k1h[-1]["c"]
        msg.append(f"{symbol}: 4h={trend}, 现价={close}")
    
    result = "\n".join(msg)
    tg_result = send_tg(f"<b>扫描结果</b>\n{result}")
    return f"扫描完成\n{result}\n\nTelegram返回：{tg_result}"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
