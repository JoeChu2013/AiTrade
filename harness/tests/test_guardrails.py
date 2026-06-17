"""
护栏单测（统一编码版）：验证 E-01~E-13 / D-01~D-08 / 七时段 / 买入闸 / 5选1 确实"咬人"。
    python -m harness.tests.test_guardrails   或   pytest harness/tests -q
"""
from __future__ import annotations

from datetime import datetime

from harness.guardrails import GuardrailEngine
from harness.guardrails.principles import PrincipleViolation
from harness.ledger import TradeLedger
from harness.models import (BuyRating, Portfolio, Position, RegimeGrade,
                            StockMetrics, Verdict)
from harness.orchestrator import Coordinator
from harness.deep_dive import StubDeepDiveAdapter
from harness.regime import grade_market

ENG = GuardrailEngine()


def _regime(grade="A"):
    v = {"S": 90, "A": 65, "B": 35, "C": 15, "D": 3}[grade]
    return grade_market({k: v for k in
                         ["index_trend", "breadth", "volume", "stability",
                          "capital_flow", "sentiment"]})


def _clean_metrics(code="600519"):
    return StockMetrics(
        code=code, name="ok", sector="白酒", price=100,
        net_profit_declining_quarters=0, gross_margin=50,
        pe_ttm=25, industry_pe_mean=30, yoy_net_profit=15,
        close=100, ma60=90, macd_dead_cross=False,
        is_st=False, regulatory_event=False, unlock_ratio=0,
        top_holder_pledge_ratio=0, major_incident=False,
        is_suspended=False, delisting_risk=False,
        avg_amount_20d=2e9, avg_turnover_20d=2.0,
        trend_dir=1, gain_1d=1.0, gain_3d=3.0, consecutive_limit_ups=0,
        negative_news_score=10,
    )


# --- 排除规则 -------------------------------------------------------------
def test_e04_red_line_st():
    m = _clean_metrics(); m.is_st = True
    sc = ENG.screen(m, {})
    assert sc.has_red_line and "E-04" in sc.red_line_hits


def test_e04_red_line_high_pledge():
    m = _clean_metrics(); m.top_holder_pledge_ratio = 80
    sc = ENG.screen(m, {})
    assert "E-04" in sc.red_line_hits


def test_e01_fundamental_hard():
    m = _clean_metrics(); m.gross_margin = 15
    sc = ENG.screen(m, {})
    assert "E-01" in sc.hard_hits


def test_e03_technical_break_hard():
    m = _clean_metrics(); m.close = 80; m.ma60 = 90; m.macd_dead_cross = True
    sc = ENG.screen(m, {})
    assert "E-03" in sc.hard_hits


def test_two_hard_means_excluded():
    m = _clean_metrics(); m.gross_margin = 15; m.negative_news_score = 90
    sc = ENG.screen(m, {})
    assert sc.hard_count >= 2 and sc.excluded


def test_clean_passes():
    sc = ENG.screen(_clean_metrics(), {})
    assert not sc.has_red_line and sc.hard_count == 0, [str(h) for h in sc.failures()]


def test_e13_negative_news_hard():
    m = _clean_metrics(); m.negative_news_score = 90
    sc = ENG.screen(m, {})
    assert "E-13" in sc.hard_hits


# --- 纪律 / vet -----------------------------------------------------------
def test_d_grade_blocks_buy_gate():
    g = _regime("D")
    assert g.grade == RegimeGrade.D
    res = ENG.vet_trade(verdict=Verdict.BUY, target_position_pct=20,
                        take_profit_pct=10, stop_loss_pct=-5, regime=g,
                        portfolio=Portfolio(), metrics=_clean_metrics(),
                        rationale="环境D测试 0", now=datetime(2026, 6, 16, 10, 30))
    assert not res.passed and "ENV-CAP" in res.blocked_by


def test_after_1430_not_buy_window():
    res = ENG.vet_trade(verdict=Verdict.BUY, target_position_pct=20,
                        take_profit_pct=10, stop_loss_pct=-5, regime=_regime("A"),
                        portfolio=Portfolio(), metrics=_clean_metrics(),
                        rationale="时间测试 0", now=datetime(2026, 6, 16, 14, 45))
    assert not res.passed and "T-01" in res.blocked_by


def test_single_position_cap_env():
    res = ENG.vet_trade(verdict=Verdict.BUY, target_position_pct=35,  # A级上限30
                        take_profit_pct=10, stop_loss_pct=-5, regime=_regime("A"),
                        portfolio=Portfolio(), metrics=_clean_metrics(),
                        rationale="单票测试 0", now=datetime(2026, 6, 16, 10, 30))
    assert "D-03" in res.blocked_by


def test_holding_cap():
    pf = Portfolio(positions=[Position(str(i), str(i), 10, 100, 10) for i in range(3)])
    res = ENG.vet_trade(verdict=Verdict.BUY, target_position_pct=20,
                        take_profit_pct=10, stop_loss_pct=-5, regime=_regime("A"),
                        portfolio=pf, metrics=_clean_metrics(),
                        rationale="持仓测试 0", now=datetime(2026, 6, 16, 10, 30))
    assert "D-02" in res.blocked_by


def test_chase_filter_d06():
    m = _clean_metrics(); m.gain_3d = 25
    res = ENG.vet_trade(verdict=Verdict.BUY, target_position_pct=20,
                        take_profit_pct=10, stop_loss_pct=-5, regime=_regime("A"),
                        portfolio=Portfolio(), metrics=m,
                        rationale="追高测试 0", now=datetime(2026, 6, 16, 10, 30))
    assert "D-06" in res.blocked_by


def test_naked_order_rejected():
    try:
        ENG.vet_trade(verdict=Verdict.BUY, target_position_pct=20,
                      take_profit_pct=None, stop_loss_pct=None, regime=_regime("A"),
                      portfolio=Portfolio(), metrics=_clean_metrics(),
                      rationale="裸单测试 0", now=datetime(2026, 6, 16, 10, 30))
        assert False, "裸单应拒绝"
    except PrincipleViolation:
        pass


def test_vague_language_rejected():
    try:
        ENG.vet_trade(verdict=Verdict.BUY, target_position_pct=20,
                      take_profit_pct=10, stop_loss_pct=-5, regime=_regime("A"),
                      portfolio=Portfolio(), metrics=_clean_metrics(),
                      rationale="可能会涨，再看看", now=datetime(2026, 6, 16, 10, 30))
        assert False, "模糊语言应拒绝"
    except PrincipleViolation:
        pass


def test_stop_loss_tier():
    res = ENG.portfolio_stops(Portfolio(daily_pnl_pct=-6.0))
    assert not res.passed and "D-01" in res.blocked_by


# --- 买入闸 + ledger ------------------------------------------------------
def test_buy_gate_pass():
    res = ENG.buy_gate(regime=_regime("A"), screen=ENG.screen(_clean_metrics(), {}),
                       risk_reward=2.0, portfolio=Portfolio(),
                       now=datetime(2026, 6, 16, 10, 30))
    assert res.passed, res.blocked_by


def test_buy_gate_rr_block():
    res = ENG.buy_gate(regime=_regime("A"), screen=ENG.screen(_clean_metrics(), {}),
                       risk_reward=1.2, portfolio=Portfolio(),
                       now=datetime(2026, 6, 16, 10, 30))
    assert "BG-风报比" in res.blocked_by


def test_daily_trade_count():
    led = TradeLedger()
    for i in range(3):
        led.record("2026-06-16", f"00000{i}", "buy")
    res = ENG.vet_trade(verdict=Verdict.BUY, target_position_pct=20,
                        take_profit_pct=10, stop_loss_pct=-5, regime=_regime("A"),
                        portfolio=Portfolio(), metrics=_clean_metrics(),
                        rationale="次数测试 0", now=datetime(2026, 6, 16, 10, 30),
                        ledger=led, trade_date="2026-06-16")
    assert "D-08" in res.blocked_by


# --- 5 选 1 评级（端到端）------------------------------------------------
def _coord():
    return Coordinator(adapter=StubDeepDiveAdapter({"600519": ("买入", 0.8)}))


def test_rating_buy_when_all_good():
    dec = _coord().deep_analysis(code="600519", metrics=_clean_metrics(),
                                 regime=_regime("A"), portfolio=Portfolio(),
                                 trade_date="2026-06-16", now=datetime(2026, 6, 16, 10, 30))
    assert dec.buy_rating == BuyRating.BUY, dec.rationale


def test_rating_no_buy_on_red_line():
    m = _clean_metrics(); m.is_st = True
    dec = _coord().deep_analysis(code="600519", metrics=m, regime=_regime("A"),
                                 portfolio=Portfolio(), trade_date="2026-06-16",
                                 now=datetime(2026, 6, 16, 10, 30))
    assert dec.buy_rating == BuyRating.NO_BUY


def test_rating_conditional_after_1430():
    dec = _coord().deep_analysis(code="600519", metrics=_clean_metrics(),
                                 regime=_regime("A"), portfolio=Portfolio(),
                                 trade_date="2026-06-16", now=datetime(2026, 6, 16, 14, 45))
    assert dec.buy_rating == BuyRating.CONDITIONAL, dec.rationale


def test_rating_watch_two_hard():
    m = _clean_metrics(); m.gross_margin = 15; m.negative_news_score = 90
    dec = _coord().deep_analysis(code="600519", metrics=m, regime=_regime("A"),
                                 portfolio=Portfolio(), trade_date="2026-06-16",
                                 now=datetime(2026, 6, 16, 10, 30))
    assert dec.buy_rating == BuyRating.WATCH, dec.rationale


def test_signal_parser_sell_essay_not_misread_as_buy():
    # 真实研报结论常含大量"买入"字样但结论是卖出，必须解析为卖出
    essay = ("任何反弹都是卖出的机会而非买入的机会；何时可重新买入需等批价企稳。"
             "### 最终结论\n最终建议：卖出（股票代码：600519）。")
    assert Coordinator._signal_to_verdict(essay) == Verdict.SELL


def test_signal_parser_buy_conclusion():
    essay = "风险点：若跌破支撑应卖出。### 最终建议：买入，目标价上看。"
    assert Coordinator._signal_to_verdict(essay) == Verdict.BUY


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ✅ {fn.__name__}")
    print(f"\n{len(fns)} 项全部通过")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    _run_all()
