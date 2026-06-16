"""
④ 三层风控 + 终审主管（阶段4）——决策 Fork-A=A1（三道确定性风控层 + 终裁）。

  L1 排除精排（ScreenResult：红线 / 硬排除计数）
  L2 纪律风控（buy_gate / vet_trade 结果）
  L3 环境风控（regime：D 禁 / C 减 / 政策压级）
  终裁：任一层不过 → 否决（一票否决）。
"""
from __future__ import annotations

from ..models import GuardrailResult, MarketRegime, RegimeGrade, ScreenResult


def adjudicate(screen: ScreenResult, gate: GuardrailResult,
               regime: MarketRegime) -> tuple:
    """返回 (approved: bool, reasons: list[str])。"""
    reasons = []
    # L1 排除
    if screen.has_red_line:
        reasons.append(f"L1红线{screen.red_line_hits}")
    if screen.hard_count >= 2:
        reasons.append(f"L1硬排除{screen.hard_count}条")
    # L3 环境
    if regime.force_flat or regime.grade == RegimeGrade.D:
        reasons.append("L3环境D级强制空仓")
    elif regime.grade == RegimeGrade.C:
        reasons.append("L3环境C级仅减仓不新增")
    # L2 纪律
    if gate is not None and not gate.passed:
        reasons.append(f"L2纪律未过{gate.blocked_by}")
    return (len(reasons) == 0, reasons)
