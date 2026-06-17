"""
真实深析实跑：DeepSeek 驱动 TradingAgents-CN 12-Agent 引擎跑一只票，
保存**完整研报 + 多空/风控辩论会议纪要**到 reports/，再套 harness 5 选 1 评级。

    python -m harness.real_run [代码] [交易日]
默认：600519 2026-06-16

会真实消耗 DeepSeek token；只调用一次深析引擎（结果复用）。
输出文件：reports/{代码}_{交易日}_{时间戳}.md（本地，已 gitignore）。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

from .deep_dive import BaseDeepDiveAdapter, DeepDiveAdapter, DeepDiveResult
from .models import Portfolio, StockMetrics
from .orchestrator import Coordinator
from .regime import grade_market


class _Cached(BaseDeepDiveAdapter):
    def __init__(self, result: DeepDiveResult):
        self._r = result

    def analyze(self, code: str, trade_date: str) -> DeepDiveResult:
        return self._r


def _g(state: dict, key: str) -> str:
    v = state.get(key, "")
    return v if isinstance(v, str) else str(v)


def _build_markdown(code, name, trade_date, dd, dec, regime) -> str:
    st = dd.raw_state or {}
    inv = st.get("investment_debate_state", {}) or {}
    risk = st.get("risk_debate_state", {}) or {}
    L = []
    L.append(f"# 个股深析报告 · {code} {name}")
    L.append(f"- 交易日：{trade_date}　生成：{datetime.now().isoformat(timespec='seconds')}")
    L.append(f"- 引擎：TradingAgents-CN（DeepSeek deepseek-chat）｜协调器：harness")
    L.append("\n---\n## 一、阶段1 · 四大分析师采集")
    L.append("### ① 市场/技术分析师\n" + _g(st, "market_report"))
    L.append("\n### ② 基本面分析师\n" + _g(st, "fundamentals_report"))
    L.append("\n### ③ 舆情新闻分析师\n" + _g(st, "news_report"))
    L.append("\n### ④ 市场情绪分析师\n" + _g(st, "sentiment_report"))
    L.append("\n---\n## 二、阶段2 · 多空辩论会议纪要")
    L.append("### ⑤ 多头研究员\n" + _g(inv, "bull_history"))
    L.append("\n### ⑥ 空头研究员\n" + _g(inv, "bear_history"))
    L.append("\n### 辩论全过程\n" + _g(inv, "history"))
    L.append("\n### ⑦ 研究主管裁决 / 标准研报\n" + (_g(inv, "judge_decision") or _g(st, "investment_plan")))
    L.append("\n---\n## 三、阶段3 · 交易测算员\n" + _g(st, "trader_investment_plan"))
    L.append("\n---\n## 四、阶段4 · 三方风控辩论会议纪要")
    L.append("### 激进风控\n" + _g(risk, "risky_history"))
    L.append("\n### 保守风控\n" + _g(risk, "safe_history"))
    L.append("\n### 中性风控\n" + _g(risk, "neutral_history"))
    L.append("\n### 辩论全过程\n" + _g(risk, "history"))
    L.append("\n---\n## 五、⑬ 终审风控主管裁决\n" + _g(st, "final_trade_decision"))
    L.append("\n---\n## 六、Harness 决策卡")
    L.append(f"- {regime.summary()}")
    L.append(f"- **5 选 1 评级：【{dec.buy_rating.value}】**（动作 {dec.verdict.value}）")
    L.append(f"- 仓位 {dec.target_position_pct:.0f}%｜止盈 {dec.take_profit_pct}%｜止损 "
             f"{dec.stop_loss_pct}%｜R:R {dec.risk_reward}｜置信 {dec.confidence:.2f}")
    L.append(f"- 理由：{dec.rationale}")
    L.append("\n> 注：大盘环境为手动占位（宏观分析师 LLM 前端未接）；个股指标仅置安全红线，其余为信息缺口。")
    return "\n".join(L)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    code = sys.argv[1] if len(sys.argv) > 1 else "600519"
    trade_date = sys.argv[2] if len(sys.argv) > 2 else "2026-06-16"
    name = {"600519": "贵州茅台"}.get(code, code)

    print(f"\n{'='*72}\n真实深析：{code} {name}  trade_date={trade_date}  (DeepSeek)\n{'='*72}")
    print("调用 12-Agent 深析引擎中（数分钟）...\n")

    dd = DeepDiveAdapter(provider="deepseek").analyze(code, trade_date)

    regime = grade_market({"index_trend": 52, "breadth": 50, "volume": 50,
                           "stability": 52, "capital_flow": 50, "sentiment": 50})
    metrics = StockMetrics(code=code, name=name, sector="白酒", price=None,
                           is_st=False, is_suspended=False, regulatory_event=False,
                           major_incident=False, delisting_risk=False,
                           unlock_ratio=0, top_holder_pledge_ratio=0)
    dec = Coordinator(adapter=_Cached(dd)).deep_analysis(
        code=code, metrics=metrics, regime=regime, portfolio=Portfolio(cash=1_000_000),
        trade_date=trade_date, now=datetime(2026, 6, 16, 10, 30))

    # 落盘完整文档
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")
    os.makedirs(out_dir, exist_ok=True)
    fname = f"{code}_{trade_date}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    path = os.path.join(out_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(_build_markdown(code, name, trade_date, dd, dec, regime))

    print(f">>> 引擎信号(末段)：...{_g(dd.raw_state or {}, 'final_trade_decision')[-120:]}")
    print(f">>> 5 选 1 评级：【{dec.buy_rating.value}】（{dec.verdict.value}）")
    print(f"\n✅ 完整研报 + 多空/风控会议纪要已保存：\n   {path}")


if __name__ == "__main__":
    main()
