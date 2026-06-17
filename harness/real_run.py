"""
真实深析实跑：用 DeepSeek 驱动 TradingAgents-CN 引擎跑一只票，
再套上 harness 的 6 阶段 + 5 选 1 评级。

    python -m harness.real_run [代码] [交易日]
默认：600519 2026-06-16

注意：会真实消耗 DeepSeek token；只调用一次深析引擎（结果缓存复用，避免重复扣费）。
"""
from __future__ import annotations

import sys
from datetime import datetime

from .deep_dive import BaseDeepDiveAdapter, DeepDiveAdapter, DeepDiveResult
from .models import Portfolio, StockMetrics
from .orchestrator import Coordinator
from .regime import grade_market


class _Cached(BaseDeepDiveAdapter):
    """把已得到的真实结果缓存，供协调器复用，避免二次调用 LLM。"""
    def __init__(self, result: DeepDiveResult):
        self._r = result

    def analyze(self, code: str, trade_date: str) -> DeepDiveResult:
        return self._r


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    code = sys.argv[1] if len(sys.argv) > 1 else "600519"
    trade_date = sys.argv[2] if len(sys.argv) > 2 else "2026-06-16"
    name = {"600519": "贵州茅台"}.get(code, code)

    print(f"\n{'='*72}\n真实深析：{code} {name}  trade_date={trade_date}  (DeepSeek)\n{'='*72}")
    print("调用 12-Agent 深析引擎中（多分析师+多空辩论+风控，约数分钟）...\n")

    adapter = DeepDiveAdapter(provider="deepseek")
    dd = adapter.analyze(code, trade_date)   # 唯一一次真实 LLM 调用

    print(f"\n>>> 引擎信号：{dd.signal}\n")
    for k, v in dd.reports.items():
        if v:
            print(f"\n----- {k} -----\n{str(v)[:1800]}")

    # 套上 harness：6 阶段 + 5 选 1（环境暂用手动中性偏暖 B；指标仅安全红线置 False，其余记缺口）
    regime = grade_market({"index_trend": 55, "breadth": 50, "volume": 50,
                           "stability": 55, "capital_flow": 50, "sentiment": 50})
    metrics = StockMetrics(code=code, name=name, sector="白酒", price=None,
                           is_st=False, is_suspended=False, regulatory_event=False,
                           major_incident=False, delisting_risk=False,
                           unlock_ratio=0, top_holder_pledge_ratio=0)
    coord = Coordinator(adapter=_Cached(dd))
    dec = coord.deep_analysis(code=code, metrics=metrics, regime=regime,
                              portfolio=Portfolio(cash=1_000_000),
                              trade_date=trade_date, now=datetime(2026, 6, 16, 10, 30))

    print(f"\n{'='*72}\nHarness 决策卡\n{'='*72}")
    print(regime.summary())
    print(f"5 选 1 评级：【{dec.buy_rating.value}】")
    print(f"理由：{dec.rationale}")
    print(f"仓位 {dec.target_position_pct:.0f}%  止盈 {dec.take_profit_pct}%  "
          f"止损 {dec.stop_loss_pct}%  R:R {dec.risk_reward}  置信 {dec.confidence:.2f}")
    print("（注：大盘环境为手动设定占位——宏观分析师 LLM 前端尚未接；个股指标仅置安全红线，其余为信息缺口）")


if __name__ == "__main__":
    main()
