"""
八项铁律交易纪律 D-01~D-08（doc07）—— 确定性执行（B1）。

  D-01 三档分级止损
  D-02 持仓数量上限
  D-03 单一仓位上限（按环境 min 30%）
  D-04 浮亏不加仓
  D-05 止盈分档兑现
  D-06 不追突发暴涨/连续拉升
  D-07 不频繁短线反复交易
  D-08 单日交易次数上限
（环境开仓闸改名 ENV-CAP，属原则一，不占 D 编号）
"""
from __future__ import annotations

from ..config_loader import load_config
from ..models import MarketRegime, Portfolio, RegimeGrade, RuleHit, RuleKind, StockMetrics

_K = RuleKind.HARD   # 纪律统一记为硬约束


def _hit(rid, name, passed, detail):
    return RuleHit(rid, name, _K, passed, detail)


# --- D-01 三档止损 ---------------------------------------------------------
def check_stop_loss_tiers(portfolio: Portfolio) -> list:
    cfg = load_config()["stop_loss_tiers"]
    out = []
    for tier, pnl, c in [("日", portfolio.daily_pnl_pct, cfg["daily"]),
                         ("周", portfolio.weekly_pnl_pct, cfg["weekly"]),
                         ("月", portfolio.monthly_pnl_pct, cfg["monthly"])]:
        if pnl <= c["hard_pct"]:
            out.append(_hit("D-01", f"止损-{tier}线(硬)", False,
                            f"{tier}亏{pnl:.1f}%≤{c['hard_pct']}% → {c['hard_action']}"))
        elif pnl <= c["enter_pct"]:
            out.append(_hit("D-01", f"止损-{tier}线", False,
                            f"{tier}亏{pnl:.1f}%≤{c['enter_pct']}% → {c['action']}"))
        else:
            out.append(_hit("D-01", f"止损-{tier}线", True, f"{tier}盈亏{pnl:.1f}%安全"))
    return out


# --- D-02 持仓数量 ---------------------------------------------------------
def check_holding_cap(portfolio: Portfolio, opening_new: bool) -> RuleHit:
    cap = load_config()["position"]["max_holdings"]
    n = portfolio.holding_count
    if opening_new and n >= cap:
        return _hit("D-02", "最大持仓数", False, f"已持{n}≥{cap}，禁开新仓")
    return _hit("D-02", "最大持仓数", True, f"已持{n}/{cap}")


# --- D-03 单票上限（按环境 min 30%）---------------------------------------
def single_position_cap(regime: MarketRegime) -> float:
    """Fork-B=B1：min(环境分级档, 30% 绝对兜底)。"""
    abs_cap = load_config()["position"]["single_position_abs_cap_pct"]
    return min(regime.max_single_position_pct, abs_cap)


def check_single_position(target_pct: float, regime: MarketRegime) -> RuleHit:
    cap = single_position_cap(regime)
    if target_pct > cap:
        return _hit("D-03", "单票仓位上限", False, f"目标{target_pct:.0f}%>上限{cap:.0f}%")
    return _hit("D-03", "单票仓位上限", True, f"目标{target_pct:.0f}%≤{cap:.0f}%")


# --- D-04 浮亏不加仓 -------------------------------------------------------
def check_no_add_on_loss(intraday_pnl_pct: float, is_add: bool) -> RuleHit:
    if not load_config()["position"]["no_add_on_intraday_loss"]:
        return _hit("D-04", "浮亏不加仓", True, "规则关闭")
    if is_add and intraday_pnl_pct < 0:
        return _hit("D-04", "浮亏不加仓", False, f"日内浮亏{intraday_pnl_pct:.1f}%，禁补仓")
    return _hit("D-04", "浮亏不加仓", True, "非浮亏补仓")


# --- D-05 止盈分档 ---------------------------------------------------------
def check_take_profit(position) -> RuleHit:
    """对单个持仓判定止盈动作。需 position.peak_price 才能算移动止盈。"""
    tp = load_config()["take_profit"]
    pnl = position.pnl_pct
    if pnl >= tp["tier1_pct"]:
        # 移动止盈判定
        if position.peak_price:
            drawdown = (position.peak_price - position.current_price) / position.peak_price * 100
            if drawdown >= tp["trailing_drawdown_pct"]:
                return _hit("D-05", "止盈-移动", False,
                            f"自高点回撤{drawdown:.1f}%≥{tp['trailing_drawdown_pct']}% → 了结剩余")
        return _hit("D-05", "止盈-第一档", False,
                    f"盈利{pnl:.1f}%≥{tp['tier1_pct']}% → 减半锁利")
    return _hit("D-05", "止盈", True, f"盈利{pnl:.1f}%未达第一止盈位")


def default_tp_sl() -> tuple:
    tp = load_config()["take_profit"]
    return tp["tier1_pct"], tp["default_stop_loss_pct"]


# --- D-06 不追暴涨 ---------------------------------------------------------
def check_chase_filter(m: StockMetrics) -> RuleHit:
    cf = load_config()["chase_filter"]
    why = []
    if m.gain_3d is not None and m.gain_3d >= cf["max_3d_gain_pct"]:
        why.append(f"3日+{m.gain_3d:.0f}%")
    if m.gain_1d is not None and m.gain_1d >= cf["max_1d_gain_pct"]:
        why.append(f"单日+{m.gain_1d:.0f}%")
    if m.consecutive_limit_ups is not None and m.consecutive_limit_ups > cf["max_consecutive_limit_ups"]:
        why.append(f"{m.consecutive_limit_ups}连板")
    if why:
        return _hit("D-06", "不追暴涨", False, "；".join(why) + "，禁开新仓")
    return _hit("D-06", "不追暴涨", True, "无暴涨形态")


# --- D-07 不频繁反复 / D-08 单日次数（需 TradeLedger）---------------------
def check_trade_frequency(ledger, code: str, now_date: str) -> RuleHit:
    if ledger is None:
        return _hit("D-07", "不频繁反复", True, "无流水(跳过)")
    f = load_config()["frequency"]
    cool = ledger.days_since_last_sell(code, now_date)
    if cool is not None and cool < f["same_stock_cooldown_days"]:
        return _hit("D-07", "不频繁反复", False,
                    f"{code}卖出仅{cool}日<冷却{f['same_stock_cooldown_days']}日")
    rt = ledger.roundtrips_20d(code, now_date)
    if rt >= f["max_roundtrips_20d"]:
        return _hit("D-07", "不频繁反复", False, f"{code}20日往返{rt}≥{f['max_roundtrips_20d']}")
    return _hit("D-07", "不频繁反复", True, "频率合规")


def check_daily_trade_count(ledger, now_date: str, opening_new: bool) -> RuleHit:
    if ledger is None:
        return _hit("D-08", "单日次数", True, "无流水(跳过)")
    f = load_config()["frequency"]
    if opening_new and ledger.new_trades_today(now_date) >= f["max_new_trades_per_day"]:
        return _hit("D-08", "单日次数", False, f"今日开仓已达{f['max_new_trades_per_day']}笔")
    if ledger.total_trades_today(now_date) >= f["max_total_trades_per_day"]:
        return _hit("D-08", "单日次数", False, f"今日交易已达{f['max_total_trades_per_day']}笔")
    return _hit("D-08", "单日次数", True, "次数未超")


# --- ENV-CAP 环境开仓闸（原则一，非 D 编号）-------------------------------
def check_regime_capacity(regime: MarketRegime, portfolio: Portfolio, opening_new: bool) -> RuleHit:
    rid = "ENV-CAP"
    if regime.force_flat or regime.grade == RegimeGrade.D:
        if opening_new:
            return RuleHit(rid, "环境闸-D级空仓", RuleKind.SITUATIONAL, False, "D级强制空仓，禁开新仓")
        return RuleHit(rid, "环境闸-D级空仓", RuleKind.SITUATIONAL, True, "D级仅允许减/清")
    if opening_new and regime.max_new_positions <= 0:
        return RuleHit(rid, "环境闸-开仓额度", RuleKind.SITUATIONAL, False,
                       f"{regime.grade.value}级今日开仓额度0")
    return RuleHit(rid, "环境闸-开仓额度", RuleKind.SITUATIONAL, True,
                   f"{regime.grade.value}级额度{regime.max_new_positions}")
