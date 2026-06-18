"""
盘中监控循环（纸面）—— 高频确定性监控，不调 LLM。

每个周期：拉实时行情 → 刷新持仓盈亏 → 跑确定性风控（止损三档/单票止损/止盈分档/时段闸）
        → 候选买点告警 → 推送指令。**只产指令、不下单**（半自动：硬止损自动，其余待人工确认）。

    python -m harness.monitor            # 跑几个周期演示
    python -m harness.monitor --loop 30  # 每 30 秒一轮，盘中持续

依赖 harness/state/positions.json（持仓）。候选池来自两层股票池。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from . import store
from .config_loader import load_config
from .guardrails import GuardrailEngine
from .guardrails import time_rules as T
from .models import MarketRegime, Portfolio, Verdict
from .realtime import fetch_realtime


@dataclass
class Instruction:
    action: str            # 建仓/加仓/减仓/清仓/止损/告警
    code: str
    name: str
    detail: str
    auto: bool = False     # True=硬止损可自动；False=需人工确认

    def __str__(self):
        tag = "🤖自动" if self.auto else "🙋待确认"
        return f"[{tag}] {self.action} {self.code} {self.name}：{self.detail}"


@dataclass
class Monitor:
    engine: GuardrailEngine = field(default_factory=GuardrailEngine)
    regime: Optional[MarketRegime] = None
    candidates: list = field(default_factory=list)   # [code]
    push: Callable = print

    def cycle(self, now: Optional[datetime] = None) -> list:
        now = now or datetime.now()
        instr: list = []
        pf = store.load_portfolio()

        # 1) 拉实时行情（持仓 + 候选）
        codes = [p.code for p in pf.positions] + list(self.candidates)
        quotes = fetch_realtime(codes)

        # 2) 刷新持仓现价/峰值 + 当日盈亏
        num = den = 0.0
        for p in pf.positions:
            q = quotes.get(p.code)
            if not q:
                continue
            p.current_price = q["price"]
            p.peak_price = max(p.peak_price or p.current_price, p.current_price)
            num += p.qty * (q["price"] - q["prev_close"])
            den += p.qty * q["prev_close"]
        if den > 0:
            pf.daily_pnl_pct = round(num / den * 100, 2)

        # 3) 组合级止损三档（D-01）——硬触发自动
        stops = self.engine.portfolio_stops(pf)
        for h in stops.hits:
            if not h.passed:
                instr.append(Instruction("止损", "组合", "", h.detail, auto=True))

        # 4) 逐仓：单票止损 + 止盈分档
        sl = load_config()["take_profit"]["default_stop_loss_pct"]
        for p in pf.positions:
            if p.current_price <= 0:
                continue
            if p.pnl_pct <= sl:
                instr.append(Instruction("止损", p.code, p.name,
                             f"浮亏{p.pnl_pct:.1f}%≤{sl}%，清仓", auto=True))
                continue
            tp = self.engine.take_profit_actions(Portfolio(positions=[p]))
            for hh in tp:
                if not hh.passed:
                    instr.append(Instruction("减仓/止盈", p.code, p.name, hh.detail, auto=False))

        # 5) 候选买点告警（仅提示，不自动建仓——建仓需深析+人工）
        in_buy_window = T.can_buy(now)
        slots = load_config()["position"]["max_holdings"] - pf.holding_count
        for code in self.candidates:
            q = quotes.get(code)
            if not q:
                continue
            reasons = []
            if not in_buy_window:
                reasons.append("非买入窗口")
            if slots <= 0:
                reasons.append("持仓已满")
            if self.regime and self.regime.max_new_positions <= 0:
                reasons.append(f"环境{self.regime.grade.value}级不开仓")
            if q["pct"] >= load_config()["chase_filter"]["max_1d_gain_pct"]:
                reasons.append(f"当日+{q['pct']}%追高")
            if not reasons:
                instr.append(Instruction("告警", code, q["name"],
                             f"现价{q['price']} 买点时点成立 → 建议触发深析+人工确认", auto=False))

        # 6) 推送 + 落权益快照
        store.save_portfolio(pf)
        store.append_equity(pf.total_value, now.isoformat(timespec="seconds"))
        ts = now.strftime("%H:%M:%S")
        if instr:
            self.push(f"\n⏱ {ts} 监控（持仓{pf.holding_count} 当日{pf.daily_pnl_pct:+.2f}%）")
            for i in instr:
                self.push("   " + str(i))
        else:
            self.push(f"⏱ {ts} 监控正常，无触发（持仓{pf.holding_count} 当日{pf.daily_pnl_pct:+.2f}%）")
        return instr

    def loop(self, interval: int = 30, max_cycles: int = 0):
        import time
        n = 0
        while T.can_trade(datetime.now()) or max_cycles:
            self.cycle()
            n += 1
            if max_cycles and n >= max_cycles:
                break
            time.sleep(interval)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, default=0, help="循环间隔秒；0=单轮")
    ap.add_argument("--cycles", type=int, default=3, help="演示周期数")
    args = ap.parse_args()

    from .regime import grade_market
    from .datafeed import fetch_regime_factors
    from .pool import StockPool
    print("初始化：抓大盘环境 + 加载持仓/候选...")
    regime = grade_market(fetch_regime_factors())
    print(regime.summary())
    cands = StockPool().all_codes()[:10]
    mon = Monitor(regime=regime, candidates=cands)
    if args.loop:
        mon.loop(interval=args.loop)
    else:
        for _ in range(args.cycles):
            mon.cycle()


if __name__ == "__main__":
    main()
