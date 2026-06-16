"""
六大核心原则 —— 编码为可执行约束，而非口号。

  1. 环境优先 (environment_first)：先判断市场环境再选股
  2. 排除后推荐 (exclude_then_recommend)：先用规则排除，剩下的才进入推荐
  3. 禁止模糊语言 (no_vague_language)：结论必须是明确 Verdict
  4. 必须有取舍 (must_tradeoff)：候选超过可开仓位时，强制砍掉
  5. 承认信息缺口 (acknowledge_info_gaps)：缺数据要显式标注，不许假装知道
  6. 严格止盈止损 (strict_tp_sl)：每个买入必须带止盈/止损
"""
from __future__ import annotations

import re

from ..models import Verdict

# 模糊词黑名单（原则三）。结论文本里出现这些，视为违规。
_VAGUE_TERMS = [
    "可能", "也许", "大概", "应该会", "或许", "说不定", "不好说",
    "再看看", "观望一下", "看情况", "视情况而定", "难说", "有望",
    # P-10 禁止"两个都行"/二选一
    "两个都行", "都可以", "都行", "均可", "二选一", "皆可",
]

import re as _re


class PrincipleViolation(ValueError):
    """原则被违反时抛出，属于硬错误（绝不静默放过）。"""


def no_vague_language(verdict: Verdict, rationale: str) -> None:
    """原则三：结论必须明确。verdict 必须是枚举，理由里不许有模糊词。"""
    if not isinstance(verdict, Verdict):
        raise PrincipleViolation(f"结论必须是明确 Verdict，收到：{verdict!r}")
    hit = [w for w in _VAGUE_TERMS if w in (rationale or "")]
    if hit:
        raise PrincipleViolation(f"原则三违规：结论含模糊词 {hit}，请给明确判断。")


def must_tradeoff(candidate_count: int, capacity: int) -> int:
    """原则四：必须有取舍。返回最终允许的数量（不贪心）。"""
    return max(0, min(candidate_count, capacity))


def strict_tp_sl(take_profit_pct, stop_loss_pct) -> None:
    """原则六：买入必须带止盈止损，否则裸单，拒绝。"""
    if take_profit_pct is None or stop_loss_pct is None:
        raise PrincipleViolation("原则六违规：买入决策缺止盈或止损，禁止裸单。")
    if stop_loss_pct >= 0:
        raise PrincipleViolation("原则六违规：止损必须为负（亏损阈值）。")
    if take_profit_pct <= 0:
        raise PrincipleViolation("原则六违规：止盈必须为正。")


def require_data_support(rationale: str, min_numeric: int = 1, min_len: int = 10) -> None:
    """P-03/P-08：结论须有数据支撑——至少 min_numeric 个数值证据且非空。"""
    text = (rationale or "").strip()
    if len(text) < min_len:
        raise PrincipleViolation("P-08 违规：仅抛原始/空结论，缺加工依据。")
    nums = _re.findall(r"-?\d+\.?\d*%?", text)
    if len(nums) < min_numeric:
        raise PrincipleViolation(f"P-03 违规：结论缺数值支撑（需≥{min_numeric} 个）。")


def acknowledge_info_gaps(missing_fields: list) -> str:
    """原则五：把信息缺口显式化为一句话，挂在决策理由上。"""
    if not missing_fields:
        return ""
    return f"【信息缺口】缺失字段 {sorted(set(missing_fields))}，结论置信度已下调。"


# 给协调器读取的元数据（用于 README / 自检）
PRINCIPLES = [
    ("环境优先", "先判断市场环境(S/A/B/C/D)再选股"),
    ("排除后推荐", "先用 12 排除规则砍，剩下的才推荐"),
    ("禁止模糊语言", "结论必须是明确 Verdict，无模糊词"),
    ("必须有取舍", "候选超容量时强制砍，不贪心"),
    ("承认信息缺口", "缺数据显式标注并下调置信度"),
    ("严格止盈止损", "每个买入必须带止盈/止损阈值"),
]
