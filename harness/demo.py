"""
离线演示：用 StubDeepDiveAdapter 跑通 6 阶段 + 漏斗，无需 LLM key。
    python -m harness.demo
真实运行把 StubDeepDiveAdapter() 换 DeepDiveAdapter()（需 .env 与模型 key）。
"""
from __future__ import annotations

from datetime import datetime

from .deep_dive import StubDeepDiveAdapter
from .models import Portfolio, Position, StockMetrics
from .orchestrator import Coordinator


def _m(code, name, sector, **kw):
    base = dict(price=100, net_profit_declining_quarters=0, gross_margin=45,
                pe_ttm=25, industry_pe_mean=30, yoy_net_profit=12,
                close=100, ma60=90, macd_dead_cross=False,
                is_st=False, regulatory_event=False, unlock_ratio=0,
                top_holder_pledge_ratio=0, major_incident=False,
                is_suspended=False, delisting_risk=False,
                avg_amount_20d=2e9, avg_turnover_20d=2.0, trend_dir=1,
                gain_1d=1.0, gain_3d=3.0, consecutive_limit_ups=0,
                negative_news_score=10)
    base.update(kw)
    return StockMetrics(code=code, name=name, sector=sector, **base)


def candidates():
    return [
        _m("600519", "贵州茅台", "白酒"),                      # 干净，可买
        _m("300750", "宁德时代", "电池", gain_3d=25),           # 追高 D-06/E-08
        _m("600100", "某ST股", "电子", is_st=True),             # 红线 E-04
        _m("000001", "弱基本面", "银行", gross_margin=15,
           negative_news_score=90),                            # 两条硬排除→只可观察
    ]


def run_case(title, factors, now, policy=False):
    print("\n" + "=" * 72 + f"\n{title}\n" + "=" * 72)
    coord = Coordinator(adapter=StubDeepDiveAdapter({
        "600519": ("买入", 0.82), "300750": ("买入", 0.7),
        "000001": ("买入", 0.6),
    }))
    pf = Portfolio(cash=1_000_000,
                   positions=[Position("601318", "中国平安", 50, 1000, 46, sector="保险")],
                   daily_pnl_pct=-1.0, weekly_pnl_pct=-2.0, monthly_pnl_pct=-3.0)
    rep = coord.full_analysis(regime_factors=factors, candidates=candidates(),
                              portfolio=pf, trade_date="2026-06-16", now=now,
                              policy_headwind=policy,
                              force_codes={"600100", "000001"})  # 越池以演示排除
    print(rep.summary())


def main():
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    good = {"index_trend": 70, "breadth": 60, "volume": 55,
            "stability": 50, "capital_flow": 65, "sentiment": 60}
    panic = {"index_trend": 5, "breadth": 8, "volume": 10,
             "stability": 10, "capital_flow": 5, "sentiment": 6}

    run_case("案例1：A级 + 上午10:30（正常，5选1评级）", good, datetime(2026, 6, 16, 10, 30))
    run_case("案例2：A级 + 下午14:45（T-01→条件满足才可买）", good, datetime(2026, 6, 16, 14, 45))
    run_case("案例3：D级（强制空仓，跳过选股）", panic, datetime(2026, 6, 16, 10, 30))
    run_case("案例4：A级但政策利空一票压D", good, datetime(2026, 6, 16, 10, 30), policy=True)


if __name__ == "__main__":
    main()
