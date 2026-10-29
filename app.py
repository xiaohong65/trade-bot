from flask import Flask
import requests
from datetime import datetime, timezone
import copy

app = Flask(__name__)

# -------------------- 配置 --------------------
ACCOUNT_USDT = 1000
RISK_PCT = 10
SYMBOLS = ["BTC_USDT", "ETH_USDT"]

TOKEN = "8649683072:AAFDTkpO55rO9UGszDIa7cmq3VD9YxerLCE"
CHAT_ID = "8832877679"

def send_tg(text):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=15
        )
        return r.json().get("ok", False)
    except Exception as e:
        return str(e)

def get_klines(symbol, interval, limit=100):
    url = "https://api.gateio.ws/api/v4/futures/usdt/candlesticks"
    r = requests.get(url, params={"contract": symbol, "interval": interval, "limit": limit}, timeout=10)
    data = r.json()
    result = []
    for item in data:
        result.append({
            "t": int(item["t"]),
            "o": float(item["o"]), "h": float(item["h"]),
            "l": float(item["l"]), "c": float(item["c"]),
            "v": float(item["v"])
        })
    result.sort(key=lambda x: x["t"])
    return result

def ema(values, period):
    result = [None] * len(values)
    if len(values) < period: return result
    mult = 2 / (period + 1)
    result[period-1] = sum(values[:period]) / period
    for i in range(period, len(values)):
        result[i] = (values[i] - result[i-1]) * mult + result[i-1]
    return result

def rsi(closes, period=14):
    result = [None] * len(closes)
    if len(closes) < period + 1: return result
    gains, losses = [], []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i-1]
        gains.append(max(ch, 0))
        losses.append(max(-ch, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    result[period] = 100 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period-1) + gains[i]) / period
        avg_loss = (avg_loss * (period-1) + losses[i]) / period
        result[i+1] = 100 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
    return result

def atr(highs, lows, closes, period=14):
    result = [None] * len(closes)
    if len(closes) < period + 1: return result
    trs = [0.0]
    for i in range(1, len(closes)):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        trs.append(tr)
    atr_val = sum(trs[1:period+1]) / period
    result[period] = atr_val
    for i in range(period+1, len(closes)):
        atr_val = (atr_val * (period-1) + trs[i]) / period
        result[i] = atr_val
    return result

def sma(values, period):
    result = [None] * len(values)
    for i in range(period-1, len(values)):
        result[i] = sum(values[i-period+1:i+1]) / period
    return result

def add_indicators(klines):
    closes = [k["c"] for k in klines]
    highs = [k["h"] for k in klines]
    lows = [k["l"] for k in klines]
    vols = [k["v"] for k in klines]
    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    r = rsi(closes)
    a = atr(highs, lows, closes)
    vma = sma(vols, 20)
    out = []
    for i, k in enumerate(klines):
        nk = copy.deepcopy(k)
        nk.update({"ema20": e20[i], "ema50": e50[i], "rsi": r[i], "atr": a[i], "vol_ma20": vma[i]})
        out.append(nk)
    return out

def get_4h_trend(k4h):
    latest = k4h[-1]
    e20, e50, close = latest.get("ema20"), latest.get("ema50"), latest["c"]
    if e20 is None or e50 is None: return "range"
    if close > e50 and e20 > e50: return "bullish"
    if close < e50 and e20 < e50: return "bearish"
    return "range"

def is_reversal(k, direction):
    body = abs(k["c"] - k["o"])
    full = k["h"] - k["l"]
    if full == 0: return False
    ratio = body / full
    if direction == "long":
        lower = min(k["o"], k["c"]) - k["l"]
        return (k["c"] > k["o"] and ratio > 0.5) or (lower > body * 1.5 and k["c"] > k["o"])
    else:
        upper = k["h"] - max(k["o"], k["c"])
        return (k["c"] < k["o"] and ratio > 0.5) or (upper > body * 1.5 and k["c"] < k["o"])

def check_conditions(k1h, direction):
    triggered = []
    latest = k1h[-1]
    e20, e50 = latest.get("ema20"), latest.get("ema50")
    if e20 and e50:
        close = latest["c"]
        in_zone = (abs(close - e20)/e20 < 0.006 or abs(close - e50)/e50 < 0.008 or
                   min(e20, e50) <= close <= max(e20, e50))
        if in_zone and is_reversal(latest, direction):
            triggered.append("①回踩EMA反转")
    if len(k1h) >= 15:
        window = k1h[-16:-1]
        if direction == "long":
            ph = max(k["h"] for k in window)
            if any(k["h"] > ph * 1.001 for k in k1h[-6:-1]) and abs(latest["c"] - ph)/ph < 0.008 and latest["c"] > latest["o"]:
                triggered.append("②突破回踩")
        else:
            pl = min(k["l"] for k in window)
            if any(k["l"] < pl * 0.999 for k in k1h[-6:-1]) and abs(latest["c"] - pl)/pl < 0.008 and latest["c"] < latest["o"]:
                triggered.append("②突破回踩")
    rsis = [k.get("rsi") for k in k1h[-10:]]
    closes = [k["c"] for k in k1h[-10:]]
    if not any(r is None for r in rsis):
        if direction == "long":
            if (any(r < 32 for r in rsis[-5:-1]) and rsis[-1] > rsis[-2] and rsis[-1] > 30) or \
               (closes[-1] < min(closes[-6:-1]) and rsis[-1] > min(rsis[-6:-1])):
                triggered.append("③RSI拐头/背离")
        else:
            if (any(r > 68 for r in rsis[-5:-1]) and rsis[-1] < rsis[-2] and rsis[-1] < 70) or \
               (closes[-1] > max(closes[-6:-1]) and rsis[-1] < max(rsis[-6:-1])):
                triggered.append("③RSI拐头/背离")
    if latest.get("vol_ma20") and latest["v"] > latest["vol_ma20"] * 1.5:
        triggered.append("④放量")
    return triggered

def calc_plan(k1h, direction):
    latest = k1h[-1]
    atr_val = latest.get("atr") or 0
    entry = latest["c"]
    window = k1h[-13:-1]
    if direction == "long":
        swing = min(k["l"] for k in window)
        stop = swing - atr_val * 0.5
        if stop >= entry: stop = entry - atr_val
        t1 = entry + abs(entry - stop)
        t2 = entry + abs(entry - stop) * 2
        t3 = entry + abs(entry - stop) * 3
    else:
        swing = max(k["h"] for k in window)
        stop = swing + atr_val * 0.5
        if stop <= entry: stop = entry + atr_val
        t1 = entry - abs(entry - stop)
        t2 = entry - abs(entry - stop) * 2
        t3 = entry - abs(entry - stop) * 3
    r = abs(entry - stop)
    return round(entry, 2), round(stop, 2), round(r, 2), round(t1, 2), round(t2, 2), round(t3, 2)

def calc_position(entry, stop):
    risk_amount = ACCOUNT_USDT * (RISK_PCT / 100)
    r_dist = abs(entry - stop)
    if r_dist == 0: return 0, 1
    pos = risk_amount / (r_dist / entry)
    lev = min(20, max(1, round(pos / ACCOUNT_USDT, 1)))
    return round(pos, 1), lev

@app.route("/")
def home():
    return "完整版交易机器人运行中。访问 /scan 触发扫描"

@app.route("/scan")
def scan():
    results = []
    any_signal = False

    for symbol in SYMBOLS:
        k1h = add_indicators(get_klines(symbol, "1h", 100))
        k4h = add_indicators(get_klines(symbol, "4h", 80))
        trend = get_4h_trend(k4h)

        if trend == "range":
            results.append(f"{symbol}: 震荡，跳过")
            continue

        direction = "long" if trend == "bullish" else "short"
        triggered = check_conditions(k1h, direction)

        if len(triggered) < 2:
            results.append(f"{symbol}: {trend}，条件不足({len(triggered)}条)")
            continue

        # 有信号
        entry, stop, r, t1, t2, t3 = calc_plan(k1h, direction)
        pos, lev = calc_position(entry, stop)
        strength = "A" if len(triggered) >= 3 else "B"
        dir_cn = "做多" if direction == "long" else "做空"
        invalid = f"收盘跌破 {stop}" if direction == "long" else f"收盘涨破 {stop}"

        alert = (
            f"<b>{symbol} | {dir_cn} | 1h</b>\n"
            f"→ 触发：{', '.join(triggered)}\n"
            f"→ 进场：{entry}\n"
            f"→ 止损：{stop}  （R={r}）\n"
            f"→ 目标：1R {t1} | 2R {t2} | 3R {t3}\n"
            f"→ 建议仓位：约 {pos} USDT（风险{RISK_PCT}%） 杠杆参考 {lev}x\n"
            f"→ 信号强度：{strength}\n"
            f"→ 简评：4h{trend}，规则触发\n"
            f"→ 失效：{invalid}"
        )
        send_tg(alert)
        results.append(f"{symbol}: 已推送 {dir_cn} 信号")
        any_signal = True

   # 无论有没有信号都推送
    if any_signal:
        for a in alerts:
            send_tg(a)
        final_msg = "扫描完成\n" + "\n".join(results)
    else:
        status = "扫描完成（无信号）\n" + "\n".join(results)
        send_tg(f"<b>定时状态</b>\n{status}")
        final_msg = status

    return final_msg
