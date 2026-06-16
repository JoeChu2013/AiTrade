"""
GuardrailEngine —— 把排除规则 / 八纪律 / 七时段 / 买入条件闸 组合成统一关卡。

  screen(metrics, ctx)         选股筛选 ⑧：返回 ScreenResult（红线/硬排除/情境分类）
  buy_gate(...)                买入条件复合闸（doc08）：环境≥B ∧ 排除≤1 ∧ R:R≥2 ∧ 时间 ∧ 持仓<3
  vet_trade(...)               拟议交易综合校验（纪律 + 时段 + 单票/持仓）
  portfolio_stops(portfolio)   止损三档
  take_profit_actions(pf)      止盈分档
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..config_loader import load_config
from ..models import (GateStatus, GuardrailResult, MarketRegime, Portfolio,
                      RegimeGrade, ScreenResult, StockMetrics, Verdict)
from . import exclusion_rules as excl
from . import principles as P
from . import time_rules as T
from . import trading_discipline as D

_GRADE_ORDER = {g: i for i, g in enumerate(["D", "C", "B", "A", "S"])}


class GuardrailEngine:
    # --- 选股筛选 ⑧ -------------------------------------------------------
    def screen(self, metrics: StockMetrics, ctx: dict = None) -> ScreenResult:
        return excl.run_exclusions(metrics, ctx or {})

    # --- 买入条件复合闸（doc08）------------------------------------------
    def buy_gate(self, *, regime: MarketRegime, screen: ScreenResult,
                 risk_reward: Optional[float], portfolio: Portfolio,
                 now: datetime) -> GuardrailResult:
        bc = load_config()["buy_condition"]
        hits = []

        # 环境 ≥ B
        ok_env = _GRADE_ORDER[regime.grade.value] >= _GRADE_ORDER[bc["min_regime_grade"]]
        hits.append(_rh("BG-环境", ok_env and regime.max_new_positions > 0,
                        f"{regime.grade.value}级"
                        + ("" if ok_env else f"<{bc['min_regime_grade']}")))

        # 硬排除 ≤ max_hard_exclusions 且 无红线
        ok_excl = (not screen.has_red_line) and (screen.hard_count <= bc["max_hard_exclusions"])
        hits.append(_rh("BG-排除", ok_excl,
                        f"红线{len(screen.red_line_hits)}/硬排除{screen.hard_count}"))

        # R:R ≥ 阈值
        ok_rr = (risk_reward is not None and risk_reward >= bc["min_risk_reward"])
        hits.append(_rh("BG-风报比", ok_rr,
                        f"R:R {risk_reward}" if risk_reward is not None else "R:R 缺失"))

        # 时间 < 14:30 且在买入窗口
        ok_time = T.can_buy(now) and now.time() < T._parse(load_config()["no_new_after"])
        hits.append(_rh("BG-时间", ok_time, "买入窗口" if ok_time else "非买入窗口/已过14:30"))

        # 持仓 < 3
        ok_hold = portfolio.holding_count < load_config()["position"]["max_holdings"]
        hits.append(_rh("BG-持仓", ok_hold, f"持仓{portfolio.holding_count}"))

        blocked = [h.rule_id for h in hits if not h.passed]
        status = GateStatus.PASS if not blocked else GateStatus.BLOCK
        return GuardrailResult(status=status, hits=hits, blocked_by=blocked)

    # --- 拟议交易综合校验 ------------------------------------------------
    def vet_trade(self, *, verdict: Verdict, target_position_pct: float,
                  take_profit_pct, stop_loss_pct, regime: MarketRegime,
                  portfolio: Portfolio, metrics: Optional[StockMetrics] = None,
                  rationale: str = "", now: Optional[datetime] = None,
                  is_add: bool = False, intraday_pnl_pct: float = 0.0,
                  ledger=None, trade_date: Optional[str] = None) -> GuardrailResult:
        now = now or datetime.now()
        opening_new = verdict == Verdict.BUY and not is_add
        hits = []

        P.no_vague_language(verdict, rationale)   # 原则三/P-01（违规抛错）

        hits += T.check_time_gates(now, opening_new=opening_new)
        hits.append(D.check_regime_capacity(regime, portfolio, opening_new))
        hits.append(D.check_holding_cap(portfolio, opening_new))

        if verdict == Verdict.BUY:
            hits.append(D.check_single_position(target_position_pct, regime))
            hits.append(D.check_no_add_on_loss(intraday_pnl_pct, is_add))
            if metrics is not None:
                hits.append(D.check_chase_filter(metrics))   # D-06
            if ledger is not None and trade_date is not None:
                hits.append(D.check_trade_frequency(ledger, metrics.code if metrics else "", trade_date))
                hits.append(D.check_daily_trade_count(ledger, trade_date, opening_new))
            P.strict_tp_sl(take_profit_pct, stop_loss_pct)   # 原则六（违规抛错）

        blocked = [h.rule_id for h in hits if not h.passed]
        status = GateStatus.PASS if not blocked else GateStatus.BLOCK
        return GuardrailResult(status=status, hits=hits, blocked_by=blocked)

    # --- 止损三档 / 止盈分档 ---------------------------------------------
    def portfolio_stops(self, portfolio: Portfolio) -> GuardrailResult:
        hits = D.check_stop_loss_tiers(portfolio)
        blocked = [h.rule_id for h in hits if not h.passed]
        return GuardrailResult(GateStatus.BLOCK if blocked else GateStatus.PASS, hits, blocked)

    def take_profit_actions(self, portfolio: Portfolio) -> list:
        return [D.check_take_profit(p) for p in portfolio.positions]


def _rh(rid, passed, detail):
    from ..models import RuleHit, RuleKind
    return RuleHit(rid, rid, RuleKind.SITUATIONAL, passed, detail)
