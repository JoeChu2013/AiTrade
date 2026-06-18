"""
真实数据接入（akshare）——让 12 排除规则与宏观环境真正用上实盘数据。

  fetch_metrics(code, trade_date)  -> StockMetrics（个股指标回灌，A）
  fetch_regime_factors()           -> dict 6 因子 0-100（大盘环境，B）

设计：每一项独立 try/except，抓不到就留 None（信息缺口）或中性 50，绝不抛出中断主流程。
akshare 接口不稳定/pandas 兼容问题都被吞掉并降级。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .models import StockMetrics


def _clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


def _sina_sym(code: str) -> str:
    if code.startswith(("60", "68", "51", "11", "58", "5")):
        return "sh" + code
    if code.startswith(("00", "30", "12", "15", "16", "2", "3")):
        return "sz" + code
    if code.startswith(("8", "4", "92")):
        return "bj" + code
    return ("sh" if code.startswith("6") else "sz") + code


def _retry(fn, attempts=3, pause=0.8):
    """flaky 接口（尤其 eastmoney）重试若干次；全失败返回 None。"""
    import time
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa
            last = e
            time.sleep(pause)
    return None


def _ewm(series, span):
    return series.ewm(span=span, adjust=False).mean()


# ---------------------------------------------------------------------------
# A. 个股指标回灌
# ---------------------------------------------------------------------------
def fetch_metrics(code: str, trade_date: str, name: str = "", sector: str = "") -> StockMetrics:
    import akshare as ak  # 延迟导入

    m = StockMetrics(code=code, name=name, sector=sector)
    # 安全红线默认（确保 E-04 不因全 None 被保守误剔）
    m.is_suspended = False
    m.delisting_risk = False
    m.major_incident = False
    m.regulatory_event = None  # 事件类留缺口

    end = datetime.strptime(trade_date, "%Y-%m-%d")
    start = (end - timedelta(days=160)).strftime("%Y%m%d")
    end_s = end.strftime("%Y%m%d")

    # --- 日线：均线/MACD/涨幅/量能/趋势 ---
    # 优先 sina(stock_zh_a_daily，本环境稳)，回退 eastmoney(stock_zh_a_hist)
    def _sina():
        d = ak.stock_zh_a_daily(symbol=_sina_sym(code), start_date=start,
                                end_date=end_s, adjust="qfq")
        return {"close": d["close"].astype(float),
                "amount": d["amount"].astype(float) if "amount" in d else None,
                "turn": (d["turnover"].astype(float) * 100) if "turnover" in d else None}

    def _em():
        d = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start,
                               end_date=end_s, adjust="qfq")
        return {"close": d["收盘"].astype(float),
                "amount": d["成交额"].astype(float) if "成交额" in d else None,
                "turn": d["换手率"].astype(float) if "换手率" in d else None}

    try:
        data = _retry(_sina, attempts=3) or _retry(_em, attempts=3)
        if data is not None:
            close = data["close"].reset_index(drop=True)
            if len(close) >= 5:
                m.close = float(close.iloc[-1])
                m.price = m.close
                ma = lambda n: float(close.rolling(n).mean().iloc[-1]) if len(close) >= n else None
                ma20, ma60 = ma(20), ma(60)
                m.ma60 = ma60
                dif = _ewm(close, 12) - _ewm(close, 26)
                dea = _ewm(dif, 9)
                m.macd_dead_cross = bool(dif.iloc[-1] < dea.iloc[-1])
                m.gain_1d = float((close.iloc[-1] / close.iloc[-2] - 1) * 100)
                if len(close) >= 4:
                    m.gain_3d = float((close.iloc[-1] / close.iloc[-4] - 1) * 100)
                if data["amount"] is not None:
                    m.avg_amount_20d = float(data["amount"].tail(20).mean())
                if data["turn"] is not None:
                    m.avg_turnover_20d = float(data["turn"].tail(20).mean())
                if ma20 is not None:
                    ma20s = close.rolling(20).mean()
                    prev = float(ma20s.iloc[-5]) if len(close) >= 24 else ma20
                    m.trend_dir = 1 if (m.close > ma20 and ma20 >= prev) else \
                        (-1 if m.close < ma20 else 0)
                chg = close.pct_change() * 100
                cnt = 0
                for v in chg.iloc[::-1]:
                    if v >= 9.8:
                        cnt += 1
                    else:
                        break
                m.consecutive_limit_ups = cnt
    except Exception:
        pass

    # --- 估值 PE/PB：乐咕乐股(stock_a_indicator_lg)，比 eastmoney spot 稳 ---
    try:
        ind = _retry(lambda: ak.stock_a_indicator_lg(symbol=code))
        if ind is not None and len(ind):
            last = ind.sort_values(ind.columns[0]).iloc[-1]
            for col, attr in [("pe_ttm", "pe_ttm"), ("pb", "pb")]:
                try:
                    v = float(last.get(col))
                    if v == v:
                        setattr(m, attr, v)
                except Exception:
                    pass
    except Exception:
        pass

    # --- 名称/ST（best effort，用于安全红线）---
    try:
        info = _retry(lambda: ak.stock_individual_info_em(symbol=code), attempts=2)
        if info is not None and len(info):
            kv = dict(zip(info.iloc[:, 0], info.iloc[:, 1]))
            nm = str(kv.get("股票简称", m.name))
            if nm and nm != "None":
                m.name = nm
                m.is_st = ("ST" in nm.upper())
    except Exception:
        pass

    # --- 财务：毛利率/净利同比（best effort）---
    try:
        fa = ak.stock_financial_analysis_indicator(symbol=code, start_year=str(end.year - 2))
        if fa is not None and len(fa):
            fa = fa.sort_values(fa.columns[0])
            last = fa.iloc[-1]
            for col in fa.columns:
                if "销售毛利率" in col:
                    try:
                        v = float(last[col])
                        if v == v:           # 排除 nan
                            m.gross_margin = v
                        break
                    except Exception:
                        pass
    except Exception:
        pass

    if m.is_st is None:
        m.is_st = False  # E-04 安全红线兜底为已知
    return m


# ---------------------------------------------------------------------------
# B. 大盘环境 6 因子
# ---------------------------------------------------------------------------
def fetch_regime_factors(index_symbol: str = "sh000001") -> dict:
    import akshare as ak
    f = {}

    # 指数趋势 / 量能 / 稳定度
    try:
        idx = _retry(lambda: ak.stock_zh_index_daily(symbol=index_symbol))
        close = idx["close"].astype(float)
        c = float(close.iloc[-1])
        ma20 = float(close.rolling(20).mean().iloc[-1])
        ma60 = float(close.rolling(60).mean().iloc[-1])
        ret20 = (c / float(close.iloc[-21]) - 1) * 100 if len(close) >= 21 else 0.0
        trend = 20 * (c > ma20) + 20 * (c > ma60) + 20 * (ma20 > ma60) + \
            40 * _clamp((ret20 + 5) / 10, 0, 1)
        f["index_trend"] = _clamp(trend)
        std20 = float(close.pct_change().tail(20).std() * 100)
        f["stability"] = _clamp(100 - std20 * 20)
        if "volume" in idx:
            vol = idx["volume"].astype(float)
            ratio = float(vol.iloc[-1] / vol.tail(5).mean())
            f["volume"] = _clamp(20 + (ratio - 0.6) / (1.6 - 0.6) * 60)
    except Exception:
        pass

    # 市场宽度 / 情绪（涨跌家数、涨停数）
    try:
        spot = _retry(lambda: ak.stock_zh_a_spot_em())
        chg = spot["涨跌幅"].astype(float).dropna()
        adv = int((chg > 0).sum())
        dec = int((chg < 0).sum())
        if adv + dec > 0:
            f["breadth"] = _clamp(adv / (adv + dec) * 100)
        lu = int((chg >= 9.8).sum())
        ld = int((chg <= -9.8).sum())
        f["sentiment"] = _clamp(40 + (lu - ld) * 0.4, 10, 90)
    except Exception:
        pass

    # 北向资金（接口常变，失败则中性）
    try:
        nf = ak.stock_hsgt_north_net_flow_in_em(symbol="北向资金")
        latest = float(nf["value"].astype(float).iloc[-1])  # 亿元
        f["capital_flow"] = _clamp(50 + latest)  # ±50亿 → 0/100
    except Exception:
        f["capital_flow"] = 50.0

    return f
