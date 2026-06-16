"""
12+1 项检查/排除规则引擎（doc04 v2）—— 选股筛选 Agent ⑧。

分类（RuleKind）：
  RED_LINE     单条即剔除 → 明确不买（E-04）
  HARD         计入计数分级（≥2 → 只可观察）（E-01/02/03/05/13）
  SITUATIONAL  不剔除标的，仅压评级/挡当下买入（E-06~E-12）

每条 check 返回 (是否命中坏条件, 描述)；数据缺失返回 None。
注意：E-06/07/08/09/11/12 依赖运行时上下文（regime/portfolio/now/R:R），
这里只评估"标的内在"项；情境闸的运行时部分在 engine/orchestrator 评估，
本模块对它们仅做"有数据即判"的占位（拿不到上下文则记缺口）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from ..config_loader import load_config
from ..models import RuleHit, RuleKind, ScreenResult, StockMetrics


@dataclass
class Rule:
    rule_id: str
    name: str
    kind: RuleKind
    check: Callable[[StockMetrics, dict], Optional[tuple]]
    fail_safe_exclude: bool = False   # 数据缺失时是否保守判命中


def _cfg():
    return load_config()["exclusion"]


# --- E-01 基本面恶化 -------------------------------------------------------
def _e01(m, c):
    if m.net_profit_declining_quarters is None and m.gross_margin is None:
        return None
    bad = False
    why = []
    if m.net_profit_declining_quarters is not None and \
            m.net_profit_declining_quarters >= c["e01_decline_quarters"]:
        bad = True
        why.append(f"净利连降{m.net_profit_declining_quarters}季")
    if m.gross_margin is not None and m.gross_margin < c["e01_min_gross_margin"]:
        bad = True
        why.append(f"毛利率{m.gross_margin:.0f}%<{c['e01_min_gross_margin']:.0f}%")
    return (bad, "；".join(why) if why else "基本面正常")


# --- E-02 估值过高 ---------------------------------------------------------
def _e02(m, c):
    if m.pe_ttm is None or m.industry_pe_mean is None:
        return None
    no_growth = (m.yoy_net_profit is not None and m.yoy_net_profit <= 0)
    bad = (m.pe_ttm > m.industry_pe_mean * c["e02_pe_industry_mult"]) and no_growth
    return (bad, f"PE {m.pe_ttm:.0f} >行业均值×{c['e02_pe_industry_mult']}且无增长"
            if bad else "估值合理")


# --- E-03 技术面破位 -------------------------------------------------------
def _e03(m, c):
    if m.close is None or m.ma60 is None or m.macd_dead_cross is None:
        return None
    bad = (m.close < m.ma60) and m.macd_dead_cross
    return (bad, "跌破MA60且MACD死叉" if bad else "技术面未破位")


# --- E-04 重大利空（红线）--------------------------------------------------
def _e04(m, c):
    flags = {
        "立案/问询": m.regulatory_event,
        "ST/*ST": m.is_st,
        "退市风险": m.delisting_risk,
        "停牌": m.is_suspended,
        "重大安全事故": m.major_incident,
    }
    known = [v for v in flags.values() if v is not None]
    hit = [k for k, v in flags.items() if v]
    if m.unlock_ratio is not None:
        known.append(True)
        if m.unlock_ratio > c["e04_unlock_ratio"]:
            hit.append(f"巨额解禁{m.unlock_ratio:.0f}%")
    if m.top_holder_pledge_ratio is not None:
        known.append(True)
        if m.top_holder_pledge_ratio > c["e04_top_pledge"]:
            hit.append(f"高质押{m.top_holder_pledge_ratio:.0f}%")
    if not known:
        return None
    return (bool(hit), "；".join(hit) if hit else "无重大利空")


# --- E-05 流动性不足 -------------------------------------------------------
def _e05(m, c):
    if m.avg_amount_20d is None and m.avg_turnover_20d is None:
        return None
    bad = False
    why = []
    if m.avg_amount_20d is not None and m.avg_amount_20d < c["e05_min_amount"]:
        bad = True
        why.append(f"日均额{m.avg_amount_20d/1e8:.2f}亿<0.5亿")
    if m.avg_turnover_20d is not None and m.avg_turnover_20d < c["e05_min_turnover"]:
        bad = True
        why.append(f"换手{m.avg_turnover_20d:.2f}%<{c['e05_min_turnover']}%")
    return (bad, "；".join(why) if why else "流动性达标")


# --- E-06 违背市场方向（情境，需 regime.direction）------------------------
def _e06(m, c, ctx):
    mkt = ctx.get("market_direction")
    if m.trend_dir is None or mkt is None:
        return None
    bad = (mkt != 0 and m.trend_dir != 0 and m.trend_dir != mkt)
    return (bad, "个股趋势与大盘相反" if bad else "与大盘方向一致")


# --- E-07 风报比倒挂（情境，需 R:R）--------------------------------------
def _e07(m, c, ctx):
    rr = ctx.get("risk_reward")
    if rr is None:
        return None
    minrr = load_config()["buy_condition"]["min_risk_reward"]
    bad = rr < minrr
    return (bad, f"R:R {rr:.1f} <{minrr}" if bad else f"R:R {rr:.1f} 达标")


# --- E-08 交易时机不当（情境，需 now + 追涨形态）-------------------------
def _e08(m, c, ctx):
    parts = []
    # 追涨形态（标的内在）
    cf = load_config()["chase_filter"]
    if m.gain_3d is not None and m.gain_3d >= cf["max_3d_gain_pct"]:
        parts.append(f"3日+{m.gain_3d:.0f}%")
    if m.gain_1d is not None and m.gain_1d >= cf["max_1d_gain_pct"]:
        parts.append(f"单日+{m.gain_1d:.0f}%")
    if m.consecutive_limit_ups is not None and \
            m.consecutive_limit_ups > cf["max_consecutive_limit_ups"]:
        parts.append(f"{m.consecutive_limit_ups}连板")
    # 时点（运行时）
    if ctx.get("after_no_new"):
        parts.append("14:30后/尾盘")
    if not parts and m.gain_3d is None and m.gain_1d is None and "after_no_new" not in ctx:
        return None
    return (bool(parts), "；".join(parts) if parts else "时机合适")


# --- E-09 资金管理违规（情境，需 portfolio）------------------------------
def _e09(m, c, ctx):
    pf = ctx.get("portfolio")
    if pf is None:
        return None
    why = []
    if pf.holding_count >= load_config()["position"]["max_holdings"]:
        why.append(f"持仓{pf.holding_count}已满")
    tgt = ctx.get("target_position_pct")
    cap = ctx.get("single_cap_pct")
    if tgt is not None and cap is not None and tgt > cap:
        why.append(f"单票{tgt:.0f}%>上限{cap:.0f}%")
    return (bool(why), "；".join(why) if why else "资金管理合规")


# --- E-10 除权除息干扰（情境）--------------------------------------------
def _e10(m, c, ctx):
    if m.in_pre_record_window is None and m.days_since_ex is None and \
            m.pre_record_gain_pct is None:
        return None
    why = []
    if m.in_pre_record_window and m.pre_record_gain_pct is not None and \
            m.pre_record_gain_pct > c["e10_pre_record_gain"]:
        why.append(f"抢权过热+{m.pre_record_gain_pct:.0f}%")
    if m.days_since_ex is not None and 0 <= m.days_since_ex <= c["e10_ex_cooldown_days"]:
        why.append(f"除权后第{m.days_since_ex}日冷却期")
    return (bool(why), "；".join(why) if why else "无除权除息干扰")


# --- E-11 系统风险警戒（情境，需 regime）---------------------------------
def _e11(m, c, ctx):
    grade = ctx.get("regime_grade")
    if grade is None:
        return None
    bad = grade in ("D", "C")
    return (bad, f"大盘{grade}级（D禁/C减）" if bad else f"大盘{grade}级正常")


# --- E-12 逻辑一致性 同板块≤2（情境，需 portfolio）----------------------
def _e12(m, c, ctx):
    pf = ctx.get("portfolio")
    if pf is None or not m.sector:
        return None
    cap = load_config()["position"]["max_sector_holdings"]
    cnt = pf.sector_count(m.sector)
    bad = cnt >= cap
    return (bad, f"板块[{m.sector}]已持{cnt}≥{cap}" if bad else f"板块[{m.sector}]持{cnt}")


# --- E-13 负面舆情过热（硬排除）-----------------------------------------
def _e13(m, c):
    if m.negative_news_score is None:
        return None
    bad = m.negative_news_score > c["e13_negative_news"]
    return (bad, f"负面舆情{m.negative_news_score:.0f}>{c['e13_negative_news']:.0f}"
            if bad else "舆情正常")


# 标的内在规则（只看 metrics）
_INTRINSIC = [
    Rule("E-01", "基本面恶化", RuleKind.HARD, _e01),
    Rule("E-02", "估值过高", RuleKind.HARD, _e02),
    Rule("E-03", "技术面破位", RuleKind.HARD, _e03),
    Rule("E-04", "重大利空", RuleKind.RED_LINE, _e04, fail_safe_exclude=True),
    Rule("E-05", "流动性不足", RuleKind.HARD, _e05),
    Rule("E-13", "负面舆情过热", RuleKind.HARD, _e13),
]
# 情境/纪律/环境规则（需 ctx）
_CONTEXTUAL = [
    Rule("E-06", "违背市场方向", RuleKind.SITUATIONAL, _e06),
    Rule("E-07", "风报比倒挂", RuleKind.SITUATIONAL, _e07),
    Rule("E-08", "交易时机不当", RuleKind.SITUATIONAL, _e08),
    Rule("E-09", "资金管理违规", RuleKind.SITUATIONAL, _e09),
    Rule("E-10", "除权除息干扰", RuleKind.SITUATIONAL, _e10),
    Rule("E-11", "系统风险警戒", RuleKind.SITUATIONAL, _e11),
    Rule("E-12", "逻辑一致性(同板块≤2)", RuleKind.SITUATIONAL, _e12),
]


def run_exclusions(metrics: StockMetrics, ctx: dict = None) -> ScreenResult:
    """跑全部规则，返回分类后的 ScreenResult。ctx 提供情境上下文。"""
    ctx = ctx or {}
    c = _cfg()
    res = ScreenResult()

    def _record(rule, result):
        if result is None:
            res.info_gaps.append(rule.rule_id)
            if rule.fail_safe_exclude:
                res.hits.append(RuleHit(rule.rule_id, rule.name, rule.kind,
                                        passed=False, detail="数据缺失·安全红线保守判命中"))
                res.red_line_hits.append(rule.rule_id)
            else:
                res.hits.append(RuleHit(rule.rule_id, rule.name, rule.kind,
                                        passed=True, detail="数据缺失·记缺口"))
            return
        bad, detail = result
        res.hits.append(RuleHit(rule.rule_id, rule.name, rule.kind,
                                passed=not bad, detail=detail))
        if bad:
            if rule.kind == RuleKind.RED_LINE:
                res.red_line_hits.append(rule.rule_id)
            elif rule.kind == RuleKind.HARD:
                res.hard_hits.append(rule.rule_id)
            else:
                res.situational_hits.append(rule.rule_id)

    for rule in _INTRINSIC:
        _record(rule, rule.check(metrics, c))
    for rule in _CONTEXTUAL:
        _record(rule, rule.check(metrics, c, ctx))

    return res
