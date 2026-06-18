"""
实时行情（sina 直连，比 eastmoney 稳）。分钟级足够盘中监控用。

    fetch_realtime(["600519","002281"]) -> {code: {name,price,prev_close,open,high,low,pct}}
"""
from __future__ import annotations

from .datafeed import _sina_sym


def fetch_realtime(codes) -> dict:
    import requests
    if not codes:
        return {}
    syms = ",".join(_sina_sym(c) for c in codes)
    url = f"http://hq.sinajs.cn/list={syms}"
    headers = {"Referer": "https://finance.sina.com.cn",
               "User-Agent": "Mozilla/5.0"}
    out = {}
    try:
        r = requests.get(url, headers=headers, timeout=8)
        r.encoding = "gbk"
        for line, code in zip(r.text.strip().splitlines(), codes):
            try:
                payload = line.split('"')[1]
                f = payload.split(",")
                if len(f) < 6 or not f[3]:
                    continue
                price = float(f[3]); prev = float(f[2])
                out[code] = {
                    "name": f[0], "open": float(f[1]), "prev_close": prev,
                    "price": price, "high": float(f[4]), "low": float(f[5]),
                    "pct": round((price / prev - 1) * 100, 2) if prev else 0.0,
                }
            except Exception:
                continue
    except Exception:
        pass
    return out
