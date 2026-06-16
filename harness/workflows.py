"""
七套标准战术工作流（doc05）—— 同一套角色/护栏，不同调用姿势。
目的：用固定流程约束交易行为，克服贪婪/侥幸/情绪化。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .models import Portfolio, Verdict
from .orchestrator import Coordinator, OrchestrationReport
from .regime import grade_market


# WF1 全链路深析（对指定标的逐只深析）---------------------------------------
def full_deep_analysis(coord: Coordinator, *, codes_metrics: dict, regime,
                       portfolio: Portfolio, trade_date: str,
                       now: Optional[datetime] = None) -> list:
    """codes_metrics: {code: StockMetrics}。返回 [HarnessDecision]。"""
    out = []
    for code, m in codes_metrics.items():
        out.append(coord.deep_analysis(code=code, metrics=m, regime=regime,
                                       portfolio=portfolio, trade_date=trade_date, now=now))
    return out


# WF1 组合版（漏斗）---------------------------------------------------------
def full_analysis(coord: Coordinator, **kwargs) -> OrchestrationReport:
    return coord.full_analysis(**kwargs)


# WF2 池内优选 --------------------------------------------------------------
def pool_optimize(coord: Coordinator, candidates: list) -> list:
    out = []
    for m in candidates:
        if not coord.pool.is_analyzable(m.code):
            continue
        sc = coord.engine.screen(m, {})
        if sc.has_red_line or sc.hard_count >= 2:
            continue
        out.append((m, coord._prescore(m)))
    out.sort(key=lambda x: x[1], reverse=True)
    return [m for m, _ in out]


# WF3 横向对比 --------------------------------------------------------------
def compare(coord: Coordinator, codes: list, trade_date: str) -> list:
    rows = [(c, dd.signal, dd.confidence)
            for c, dd in ((c, coord.adapter.analyze(c, trade_date)) for c in codes)]
    rows.sort(key=lambda r: r[2], reverse=True)
    return rows


# WF4 持仓巡检 --------------------------------------------------------------
def portfolio_review(coord: Coordinator, portfolio: Portfolio) -> dict:
    stops = coord.engine.portfolio_stops(portfolio)
    tps = coord.engine.take_profit_actions(portfolio)
    per_pos = []
    for p in portfolio.positions:
        action = Verdict.HOLD
        if p.pnl_pct <= -5.0:
            action = Verdict.SELL
        per_pos.append({"code": p.code, "pnl_pct": round(p.pnl_pct, 1), "action": action.value})
    return {"stops": [str(h) for h in stops.hits if not h.passed],
            "take_profit": [str(h) for h in tps if not h.passed],
            "positions": per_pos}


# WF5 市场快照 --------------------------------------------------------------
def market_snapshot(regime_factors: dict, policy_headwind: bool = False):
    return grade_market(regime_factors, policy_headwind=policy_headwind)


# WF6 补充批注 --------------------------------------------------------------
def annotate(coord: Coordinator, code: str, note: str, metrics=None) -> dict:
    out = {"code": code, "info": coord.pool.info(code), "annotation": note,
           "ts": datetime.now().isoformat(timespec="seconds")}
    if metrics is not None:   # 触发重评
        sc = coord.engine.screen(metrics, {})
        out["re_screen"] = {"red_line": sc.red_line_hits, "hard": sc.hard_hits}
    return out


# WF7 批量筛选 --------------------------------------------------------------
def batch_screen(coord: Coordinator, candidates: list) -> dict:
    white, black = [], []
    for m in candidates:
        sc = coord.engine.screen(m, {})
        if sc.has_red_line or sc.hard_count >= 2:
            black.append({"code": m.code, "red_line": sc.red_line_hits, "hard": sc.hard_hits})
        else:
            white.append({"code": m.code, "info_gaps": sc.info_gaps})
    return {"whitelist": white, "blacklist": black}


WORKFLOWS = {
    "full_deep_analysis": "全链路深析", "pool_optimize": "池内优选",
    "compare": "横向对比", "portfolio_review": "持仓巡检",
    "market_snapshot": "市场快照", "annotate": "补充批注", "batch_screen": "批量筛选",
}
