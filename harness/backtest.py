"""
回测（backtrader）—— 验证 harness 的【确定性纪律层】是否赚钱、回撤多大。

回测对象：环境过滤 + 不追高/不破位 + 单票仓位上限 + 持仓≤3 + 止损-5% + 止盈分档(+10%减半)
          + 移动止盈(回撤6%)。
⚠️ 边界：入场方向用 **MACD 金叉**作确定性代理信号（LLM 深析无法逐日历史回放）。
   故本回测检验的是"纪律+技术入场"，不是 13-Agent 研判本身。

    python -m harness.backtest                      # 默认股池/区间
    python -m harness.backtest --start 2024-01-01 --end 2026-06-16
"""
from __future__ import annotations

import sys

import backtrader as bt

from .datafeed import _sina_sym

DEFAULT_UNIVERSE = ["600519", "002281", "600584", "603993", "002709",
                    "000333", "600036", "300750"]
INDEX = "sh000001"


def _load_df(symbol_or_index, start, end, is_index=False):
    import akshare as ak
    import pandas as pd
    s = start.replace("-", "")
    e = end.replace("-", "")
    if is_index:
        d = ak.stock_zh_index_daily(symbol=symbol_or_index)
        d = d.rename(columns=str.lower)
        d["date"] = pd.to_datetime(d["date"])
        d = d[(d["date"] >= start) & (d["date"] <= end)]
    else:
        d = ak.stock_zh_a_daily(symbol=_sina_sym(symbol_or_index),
                                start_date=s, end_date=e, adjust="qfq")
        d["date"] = pd.to_datetime(d["date"])
    d = d.set_index("date").sort_index()
    for c in ["open", "high", "low", "close", "volume"]:
        if c not in d.columns:
            d[c] = 0.0
    return d[["open", "high", "low", "close", "volume"]].astype(float)


def _regime_by_date(idx_df):
    """从指数日线算每日简化环境：仅趋势(close vs MA20/MA60 + 动量)。"""
    import pandas as pd
    c = idx_df["close"]
    ma20 = c.rolling(20).mean()
    ma60 = c.rolling(60).mean()
    ret20 = c / c.shift(20) - 1
    out = {}
    for dt in c.index:
        cc, m20, m60, r = c[dt], ma20[dt], ma60[dt], ret20[dt]
        if pd.isna(m60):
            out[dt.date()] = {"allow_new": False, "single_cap": 0.0, "grade": "?"}
            continue
        score = 20 * (cc > m20) + 20 * (cc > m60) + 20 * (m20 > m60) + \
            40 * max(0, min(1, ((r if r == r else 0) + 0.05) / 0.10))
        if score >= 80:
            g = ("S", 0.40, 3)
        elif score >= 50:
            g = ("A", 0.30, 2)
        elif score >= 20:
            g = ("B", 0.20, 1)
        else:
            g = ("C", 0.0, 0)
        out[dt.date()] = {"allow_new": g[2] > 0, "single_cap": g[1],
                          "grade": g[0], "max_new": g[2]}
    return out


class EquityCurve(bt.Analyzer):
    """逐日记录账户权益，用于画收益曲线/单位净值/算波动率。"""
    def start(self):
        self.data = []

    def next(self):
        self.data.append((self.strategy.datas[0].datetime.date(0),
                          float(self.strategy.broker.getvalue())))

    def get_analysis(self):
        return self.data


class DisciplineStrategy(bt.Strategy):
    params = dict(regime_by_date={}, max_holdings=3, stop_loss=-0.05,
                  tp1=0.10, trailing=0.06, chase_3d=0.20, chase_1d=0.09)

    def __init__(self):
        self.ma20 = {d: bt.ind.SMA(d.close, period=20) for d in self.datas}
        self.ma60 = {d: bt.ind.SMA(d.close, period=60) for d in self.datas}
        self.cross = {}
        for d in self.datas:
            macd = bt.ind.MACD(d.close)
            self.cross[d] = bt.ind.CrossOver(macd.macd, macd.signal)
        self.entry = {}
        self.peak = {}
        self.tp_done = {}
        self.trade_log = []   # 买卖标识：{date,code,side,price,size}

    def notify_order(self, order):
        if order.status == order.Completed:
            self.trade_log.append({
                "date": self.datas[0].datetime.date(0).isoformat(),
                "code": order.data._name,
                "side": "buy" if order.isbuy() else "sell",
                "price": float(order.executed.price),
                "size": int(order.executed.size),
            })

    def next(self):
        dt = self.datas[0].datetime.date(0)
        reg = self.p.regime_by_date.get(dt, {"allow_new": False, "single_cap": 0.0})
        holdings = sum(1 for d in self.datas if self.getposition(d).size > 0)

        for d in self.datas:
            pos = self.getposition(d)
            px = d.close[0]
            if len(d) < 61:
                continue
            if pos.size > 0:
                ent = self.entry.get(d, px)
                self.peak[d] = max(self.peak.get(d, px), px)
                pnl = px / ent - 1
                if pnl <= self.p.stop_loss:
                    self.close(data=d); continue
                if not self.tp_done.get(d) and pnl >= self.p.tp1:
                    self.sell(data=d, size=pos.size // 2)
                    self.tp_done[d] = True
                elif self.tp_done.get(d) and (self.peak[d] - px) / self.peak[d] >= self.p.trailing:
                    self.close(data=d)
            else:
                if holdings >= self.p.max_holdings or not reg["allow_new"]:
                    continue
                gc = self.cross[d][0] > 0
                up = px > self.ma20[d][0] and px > self.ma60[d][0]
                g3 = (px / d.close[-3] - 1) if len(d) > 3 else 0
                g1 = (px / d.close[-1] - 1)
                chase = g3 >= self.p.chase_3d or g1 >= self.p.chase_1d
                if gc and up and not chase:
                    cash = self.broker.getvalue() * reg["single_cap"]
                    size = int(cash / px / 100) * 100
                    if size > 0:
                        self.buy(data=d, size=size)
                        self.entry[d] = px
                        self.peak[d] = px
                        self.tp_done[d] = False
                        holdings += 1


def run(universe=None, start="2024-01-01", end="2026-06-16", cash=1_000_000,
        stop_loss=-0.05, tp1=0.10, trailing=0.06, cap_mult=1.0, max_holdings=3,
        label="基线", _cache={}):
    universe = universe or DEFAULT_UNIVERSE
    # 数据缓存（同区间多次调参回测复用，省抓取）
    key = (tuple(universe), start, end)
    if key not in _cache:
        idx = _load_df(INDEX, start, end, is_index=True)
        dfs = {}
        for code in universe:
            try:
                df = _load_df(code, start, end)
                if len(df) >= 80:
                    dfs[code] = df
            except Exception as e:
                print(f"  跳过 {code}: {e}")
        _cache[key] = (idx, dfs)
    idx, dfs = _cache[key]
    regime = _regime_by_date(idx)
    if cap_mult != 1.0:
        for v in regime.values():
            v["single_cap"] = min(0.5, v["single_cap"] * cap_mult)

    cer = bt.Cerebro(stdstats=False)
    for code, df in dfs.items():
        cer.adddata(bt.feeds.PandasData(dataname=df), name=code)
    cer.broker.setcash(cash)
    cer.broker.setcommission(commission=0.0005)
    cer.addstrategy(DisciplineStrategy, regime_by_date=regime, stop_loss=stop_loss,
                    tp1=tp1, trailing=trailing, max_holdings=max_holdings)
    cer.addanalyzer(bt.analyzers.DrawDown, _name="dd")
    cer.addanalyzer(bt.analyzers.TradeAnalyzer, _name="ta")
    cer.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", riskfreerate=0.0,
                    timeframe=bt.TimeFrame.Days)
    cer.addanalyzer(bt.analyzers.Returns, _name="ret")
    cer.addanalyzer(EquityCurve, _name="eq")
    res = cer.run()[0]
    final = cer.broker.getvalue()
    bench = (idx["close"].iloc[-1] / idx["close"].iloc[0] - 1) * 100

    # 权益曲线 / 单位净值 / 波动率
    eq = res.analyzers.eq.get_analysis()
    import numpy as np
    vals = [v for _, v in eq]
    rets = np.diff(vals) / np.array(vals[:-1]) if len(vals) > 1 else np.array([0.0])
    vol = float(np.std(rets) * np.sqrt(252) * 100) if len(rets) else 0.0
    equity = [{"date": d.isoformat(), "value": v, "nav": v / cash} for d, v in eq]
    # 指数基准归一曲线（对齐到同一净值起点）
    idx_norm = (idx["close"] / idx["close"].iloc[0]).tolist()
    idx_dates = [d.date().isoformat() for d in idx["close"].index]
    ta = res.analyzers.ta.get_analysis()
    total = ta.get("total", {}).get("closed", 0)
    won = ta.get("won", {}).get("total", 0)
    lost = ta.get("lost", {}).get("total", 0)
    avg_win = ta.get("won", {}).get("pnl", {}).get("average", 0)
    avg_loss = ta.get("lost", {}).get("pnl", {}).get("average", 0)
    pf = (won * avg_win) / abs(lost * avg_loss) if lost and avg_loss else float("inf")
    sharpe = res.analyzers.sharpe.get_analysis().get("sharperatio")
    return {
        "label": label, "ret": (final / cash - 1) * 100, "bench": bench,
        "ann": res.analyzers.ret.get_analysis().get("rnorm100", 0),
        "dd": res.analyzers.dd.get_analysis()["max"]["drawdown"],
        "sharpe": sharpe or 0.0, "vol": vol, "trades": total,
        "win": (won / total * 100 if total else 0), "pf": pf,
        "loaded": len(dfs), "final": final, "nav": final / cash,
        "equity": equity, "trades_log": res.trade_log,
        "bench_curve": {"dates": idx_dates, "norm": idx_norm},
    }


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default="2026-06-16")
    ap.add_argument("--cash", type=float, default=1_000_000)
    ap.add_argument("--codes", default="", help="逗号分隔，默认 5 只深析样本")
    a = ap.parse_args()
    uni = a.codes.split(",") if a.codes else ["600519", "002281", "600584", "603993", "002709"]
    print(f"回测股池：{uni}  区间 {a.start}~{a.end}\n加载数据中...")

    configs = [
        dict(label="基线(防守)", stop_loss=-0.05, tp1=0.10, trailing=0.06, cap_mult=1.0),
        dict(label="调参A(让赢家跑)", stop_loss=-0.08, tp1=0.20, trailing=0.12, cap_mult=1.0),
        dict(label="调参B(加仓位+让赢家跑)", stop_loss=-0.08, tp1=0.20, trailing=0.12, cap_mult=1.4),
    ]
    rows = [run(universe=uni, start=a.start, end=a.end, cash=a.cash, **c) for c in configs]
    bench = rows[0]["bench"]
    print("\n" + "=" * 78)
    print(f"5只回测对比（{rows[0]['loaded']}只可用 | 基准上证持有 {bench:+.1f}%）")
    print("=" * 78)
    print(f"{'配置':<22}{'总收益':>9}{'年化':>8}{'回撤':>8}{'夏普':>7}{'交易':>6}{'胜率':>7}{'盈亏比':>8}")
    for r in rows:
        print(f"{r['label']:<22}{r['ret']:>+8.1f}%{r['ann']:>+7.1f}%{r['dd']:>7.1f}%"
              f"{r['sharpe']:>7.2f}{r['trades']:>6}{r['win']:>6.1f}%{r['pf']:>8.2f}")


if __name__ == "__main__":
    main()
