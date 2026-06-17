"""
L0 协调器 Coordinator —— 第 13 角色（C1）。编排 + 确定性规则，不拍脑袋。

核心方法：
  deep_analysis(...)   WF1 个股全链路 6 阶段 → HarnessDecision(含 5 选 1 BuyRating)
  full_analysis(...)   漏斗：环境门 → 池筛+粗排 → 取舍 → 逐只 deep_analysis → 持仓风控

Agent 间不直接通信（P-06）：协调器读写"黑板"(models)。重大分歧走人工裁决(rule #3)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from .agents import MacroAnalyst, adjudicate, size_trade
from .config_loader import load_config
from .deep_dive import BaseDeepDiveAdapter, StubDeepDiveAdapter
from .guardrails import GuardrailEngine
from .guardrails import time_rules as T
from .guardrails.trading_discipline import single_position_cap
from .models import (BuyRating, DecisionOption, HarnessDecision,
                     HumanDecisionRequest, MarketRegime, Portfolio, RegimeGrade,
                     ScreenResult, StockMetrics, Verdict)
from .pool import StockPool

DecisionHandler = Callable[[HumanDecisionRequest], str]


def auto_recommend_handler(req: HumanDecisionRequest) -> str:
    return req.recommended or req.options[0].label


def interactive_handler(req: HumanDecisionRequest) -> str:
    print("\n" + req.render())
    labels = [o.label for o in req.options]
    while True:
        ans = input(f"请选择 {labels}（回车=推荐项）：").strip()
        if not ans and req.recommended:
            return req.recommended
        if ans in labels:
            return ans
        for i, lb in enumerate(labels, 1):
            if ans == str(i):
                return lb
        print("无效输入，请重试。")


# 关键信息缺口（缺失即不可确认安全/可交易性 → 禁买）
CRITICAL_FIELDS = {"E-04"}  # 红线项缺失已在 screen 内保守处理


@dataclass
class OrchestrationReport:
    trade_date: str
    regime: Optional[MarketRegime] = None
    capacity: int = 0
    screened_out: list = field(default_factory=list)
    decisions: list = field(default_factory=list)
    human_decisions: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"==== 编排报告 {self.trade_date} ===="]
        if self.regime:
            lines.append(self.regime.summary())
        lines.append(f"今日开仓容量：{self.capacity}")
        if self.screened_out:
            lines.append("粗筛淘汰：" + ", ".join(f"{c}({'/'.join(r)})" for c, r in self.screened_out))
        for d in self.decisions:
            rt = d.buy_rating.value if d.buy_rating else d.verdict.value
            lines.append(f"  · {d.code} {d.name}: 【{rt}】 仓位{d.target_position_pct:.0f}%"
                         f" R:R{d.risk_reward} 置信{d.confidence:.2f} | {d.rationale}")
        for topic, chosen in self.human_decisions:
            lines.append(f"  ⚖️ 人工裁决「{topic}」→ {chosen}")
        for n in self.notes:
            lines.append(f"  · {n}")
        return "\n".join(lines)


class Coordinator:
    def __init__(self, adapter: Optional[BaseDeepDiveAdapter] = None,
                 engine: Optional[GuardrailEngine] = None,
                 pool: Optional[StockPool] = None,
                 ledger=None,
                 decision_handler: DecisionHandler = auto_recommend_handler):
        self.adapter = adapter or StubDeepDiveAdapter()
        self.engine = engine or GuardrailEngine()
        self.pool = pool or StockPool()
        self.ledger = ledger
        self.macro = MacroAnalyst()
        self.decide = decision_handler

    # ======================================================================
    # WF1 · 个股全链路 6 阶段
    # ======================================================================
    def deep_analysis(self, *, code: str, metrics: StockMetrics,
                      regime: MarketRegime, portfolio: Portfolio,
                      trade_date: str, now: Optional[datetime] = None,
                      squeezed_out: bool = False) -> HarnessDecision:
        now = now or datetime.now()
        name = metrics.name or self.pool.info(code).get("name", "")

        # 阶段0：环境（D 级直接明确不买）
        if regime.grade == RegimeGrade.D and regime.force_flat:
            return self._decision(code, name, BuyRating.NO_BUY, 0.0,
                                  rationale=f"大盘D级{regime.score:.0f}分，强制空仓，明确不买。")

        # 阶段1-2：采集 + 多空辩论 + 研报（委托深析引擎）
        dd = self.adapter.analyze(code, trade_date)
        signal = self._signal_to_verdict(dd.signal)
        conviction = dd.confidence

        # 阶段3：交易测算（R:R + 买点 + 仓位）
        plan = size_trade(regime, metrics, conviction)
        rr = plan["risk_reward"]

        # 阶段4：三层风控
        opening_new = True
        after_no_new = now.time() >= T._parse(load_config()["no_new_after"])
        ctx = {
            "market_direction": regime.direction,
            "risk_reward": rr,
            "after_no_new": after_no_new or (not T.can_buy(now)),
            "portfolio": portfolio,
            "target_position_pct": plan["target_position_pct"],
            "single_cap_pct": single_position_cap(regime),
            "regime_grade": regime.grade.value,
        }
        screen = self.engine.screen(metrics, ctx)
        gate = self.engine.buy_gate(regime=regime, screen=screen, risk_reward=rr,
                                    portfolio=portfolio, now=now)
        approved, reasons = adjudicate(screen, gate, regime)

        # 阶段5：5 选 1 评级 + 决策卡
        in_buy_window = T.can_buy(now) and not after_no_new
        sector_full = portfolio.sector_count(metrics.sector) >= load_config()["position"]["max_sector_holdings"] if metrics.sector else False
        opening_allowed = (regime.max_new_positions > 0
                           and portfolio.holding_count < load_config()["position"]["max_holdings"]
                           and not sector_full)
        critical_gap = any(g in CRITICAL_FIELDS for g in screen.info_gaps)

        rating = self._compute_rating(screen, regime, rr, signal,
                                      in_buy_window, opening_allowed,
                                      critical_gap, squeezed_out)

        _sig = (dd.signal or "").strip().replace("\n", " ")
        _sig = _sig[:50] + ("…" if len(_sig) > 50 else "")
        rationale = (f"引擎动作={signal.value}（{_sig}）；R:R {rr}；硬排除{screen.hard_count}条"
                     f"{('/红线'+ '·'.join(screen.red_line_hits)) if screen.has_red_line else ''}；"
                     f"环境{regime.grade.value}级{regime.score:.0f}分；置信{conviction:.2f}。")
        if not approved:
            rationale += f" 终审否决：{reasons}。"
        if screen.info_gaps:
            rationale += f" 信息缺口{screen.info_gaps}。"

        verdict = Verdict.BUY if rating == BuyRating.BUY else Verdict.NO_ACTION

        dec = self._decision(
            code, name, rating, conviction, verdict=verdict,
            target_position_pct=plan["target_position_pct"] if rating == BuyRating.BUY else 0.0,
            entry_price=plan["entry_price"], risk_reward=rr,
            take_profit_pct=plan["take_profit_pct"], stop_loss_pct=plan["stop_loss_pct"],
            rationale=rationale, screen=screen, deep_dive_signal=dd.signal,
            provenance={"engine": type(self.adapter).__name__, "reports": list(dd.reports.keys())},
        )
        return dec

    # ======================================================================
    # 漏斗：环境门 → 池筛+粗排 → 取舍 → 逐只深析
    # ======================================================================
    def full_analysis(self, *, regime_factors: dict, candidates: list,
                      portfolio: Portfolio, trade_date: str,
                      now: Optional[datetime] = None, policy_headwind: bool = False,
                      force_codes: Optional[set] = None) -> OrchestrationReport:
        now = now or datetime.now()
        force_codes = force_codes or set()
        report = OrchestrationReport(trade_date=trade_date)

        regime = self.macro.assess(regime_factors, policy_headwind=policy_headwind)
        report.regime = regime

        if regime.grade == RegimeGrade.D and regime.force_flat:
            report.capacity = 0
            report.notes.append("大盘D级，强制空仓，跳过选股（仅持仓风控）。")
            self._portfolio_risk(report, portfolio)
            return report

        slots = max(0, load_config()["position"]["max_holdings"] - portfolio.holding_count)
        capacity = min(regime.max_new_positions, slots)
        report.capacity = capacity

        # 粗排：池筛 + 标的内在排除（红线 / 硬排除≥2）
        survivors = []
        for m in candidates:
            if not self.pool.is_analyzable(m.code, force=m.code in force_codes):
                report.screened_out.append((m.code, ["POOL"]))
                continue
            sc = self.engine.screen(m, {})   # 仅内在项
            if sc.has_red_line:
                report.screened_out.append((m.code, sc.red_line_hits))
                continue
            if sc.hard_count >= 2:
                report.screened_out.append((m.code, sc.hard_hits))
                continue
            survivors.append((m, self._prescore(m)))
        survivors.sort(key=lambda x: x[1], reverse=True)

        if capacity == 0:
            report.notes.append("开仓容量0，仅持仓巡检。")
            self._portfolio_risk(report, portfolio)
            return report

        shortlist = [m for m, _ in survivors[:capacity]]
        squeezed = {m.code for m, _ in survivors[capacity:]}
        if len(survivors) > capacity:
            shortlist = self._tradeoff_gate(survivors, capacity, report)

        for m in shortlist:
            dec = self.deep_analysis(code=m.code, metrics=m, regime=regime,
                                     portfolio=portfolio, trade_date=trade_date, now=now)
            report.decisions.append(dec)
        # 被挤出的标记为"可买但不优先"
        for m, _ in survivors[capacity:]:
            report.decisions.append(self.deep_analysis(
                code=m.code, metrics=m, regime=regime, portfolio=portfolio,
                trade_date=trade_date, now=now, squeezed_out=True))

        self._portfolio_risk(report, portfolio)
        return report

    # ======================================================================
    # 内部
    # ======================================================================
    @staticmethod
    def _compute_rating(screen: ScreenResult, regime: MarketRegime, rr,
                        signal: Verdict, in_buy_window: bool, opening_allowed: bool,
                        critical_gap: bool, squeezed_out: bool) -> BuyRating:
        # 5 明确不买
        if (screen.has_red_line or regime.grade == RegimeGrade.D
                or (rr is not None and rr < 1) or signal == Verdict.SELL):
            return BuyRating.NO_BUY
        # 4 只可观察
        if (screen.hard_count >= 2 or regime.grade == RegimeGrade.C
                or critical_gap or signal == Verdict.HOLD):
            return BuyRating.WATCH
        if rr is None or rr < 1.5:
            return BuyRating.WATCH
        # 3 可买但不优先
        if squeezed_out or rr < 2.0:
            return BuyRating.NON_PRIORITY
        # 2 条件满足才可买（时点/额度未满足）
        if not in_buy_window or not opening_allowed:
            return BuyRating.CONDITIONAL
        # 1 可适仓买入
        return BuyRating.BUY

    def _prescore(self, m: StockMetrics) -> float:
        score = 50.0
        if self.pool.membership(m.code)["in_watchlist"]:
            score += 8
        if m.avg_amount_20d:
            score += min(15, m.avg_amount_20d / 1e8)
        if m.pe_ttm is not None and 0 < m.pe_ttm < 40:
            score += 8
        if m.gain_1d is not None:
            score -= abs(m.gain_1d)
        return score

    def _tradeoff_gate(self, survivors, capacity, report) -> list:
        top = [m for m, _ in survivors[:capacity]]
        cut = [m.code for m, _ in survivors[capacity:]]
        req = HumanDecisionRequest(
            topic="候选数超过开仓容量，如何取舍",
            context=f"合格{len(survivors)}只，仅能开{capacity}仓。入围{[m.code for m in top]}；挤出{cut}。",
            options=[
                DecisionOption(f"按预打分取前{capacity}名", "客观可复现；可能漏题材。"),
                DecisionOption("人工指定名单", "纳入难量化判断；牺牲一致性，自负其责。"),
            ],
            recommended=f"按预打分取前{capacity}名",
        )
        chosen = self.decide(req)
        report.human_decisions.append((req.topic, chosen))
        return top

    def _portfolio_risk(self, report, portfolio: Portfolio):
        for h in self.engine.portfolio_stops(portfolio).hits:
            if not h.passed:
                report.notes.append(f"⛔ 止损 {h}")
        for h in self.engine.take_profit_actions(portfolio):
            if not h.passed:
                report.notes.append(f"💰 止盈 {h}")

    @staticmethod
    def _signal_to_verdict(signal: str) -> Verdict:
        """从深析结论中解析动作。
        注意：研报正文常同时含"买入/卖出"字样（如"何时可重新买入"），
        故只截取结论段（最后一个决策标记之后）判定，且卖出优先，避免把 SELL 误读成 BUY。"""
        s = signal or ""
        markers = ["最终建议", "最终结论", "最终决策", "操作建议", "投资建议", "综合建议", "建议："]
        pos = max((s.rfind(m) for m in markers), default=-1)
        seg = s[pos:pos + 120] if pos >= 0 else s
        low = seg.lower()
        sell = any(k in seg for k in ["卖出", "清仓", "减仓", "做空", "减持"]) or \
            any(k in low for k in ["sell", "short", "reduce"])
        buy = any(k in seg for k in ["买入", "做多", "加仓", "增持", "建仓"]) or \
            any(k in low for k in ["buy", "long"])
        if sell and not buy:
            return Verdict.SELL
        if buy and not sell:
            return Verdict.BUY
        if sell and buy:                       # 结论段两者都现，取最后出现者
            return Verdict.SELL if max(seg.rfind(k) for k in ["卖出", "清仓", "减仓"]) > \
                max(seg.rfind(k) for k in ["买入", "做多", "加仓"]) else Verdict.BUY
        return Verdict.HOLD

    @staticmethod
    def _decision(code, name, rating, conviction, *, verdict=Verdict.NO_ACTION,
                  target_position_pct=0.0, entry_price=None, risk_reward=None,
                  take_profit_pct=None, stop_loss_pct=None, rationale="",
                  screen=None, deep_dive_signal=None, provenance=None) -> HarnessDecision:
        return HarnessDecision(
            code=code, name=name, verdict=verdict, confidence=conviction,
            buy_rating=rating, target_position_pct=target_position_pct,
            entry_price=entry_price, risk_reward=risk_reward,
            take_profit_pct=take_profit_pct, stop_loss_pct=stop_loss_pct,
            rationale=rationale, screen=screen, deep_dive_signal=deep_dive_signal,
            provenance=provenance or {},
        )
