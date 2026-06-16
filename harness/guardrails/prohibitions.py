"""
14 项禁止行为 —— 把纪律"焊死"在系统里。

每条禁止行为要么由架构保证（如 P-04 Agent 不直接通信，靠黑板模式天然成立），
要么映射到一条会拦截的规则，要么提供运行时断言 require()。
ProhibitionError 是硬失败：宁可崩，不可违规放行。
"""
from __future__ import annotations

from dataclasses import dataclass


class ProhibitionError(RuntimeError):
    """触碰禁止行为时抛出。绝不 catch 后静默继续。"""


@dataclass
class Prohibition:
    pid: str
    name: str
    enforced_by: str  # 由哪条机制兜底


# 14 条永久禁止行为（你的改写版，见 docs/09-prohibitions.md）。
# 任一触发 → 本次分析作废重算（run_with_enforcement）。
# name 后括号为我方补全的语义解释（如有偏差请纠正）。
PROHIBITIONS = [
    Prohibition("P-01", "禁止二选一结论（结论须单一明确，不得'A或B'两可）", "no_vague_language + 单一 Verdict 强校验"),
    Prohibition("P-02", "禁止跳过低级风控（一级风控⑫不可跳过）", "orchestrator 强制⑫巡检/止损先于终审；require"),
    Prohibition("P-03", "禁止主观臆测填充（缺数据不得用猜测补）", "acknowledge_info_gaps + require_data_support"),
    Prohibition("P-04", "未完成禁止跳过（阶段未完成不得进入下一阶段）", "阶段闸：每阶段产出非空才放行 require"),
    Prohibition("P-05", "禁止尾盘换票（14:30后/尾盘不得卖旧买新换股）", "time_rules T-01（只卖不买）+ 卖买配对换票检测"),
    Prohibition("P-06", "禁止跨 Agent 通信（仅黑板读写）", "架构保证：只读上游字段、只写自身字段"),
    Prohibition("P-07", "禁止省略环境注入（个股分析必须注入 regime）", "阶段0强制；require(regime 在状态中)"),
    Prohibition("P-08", "禁止仅抛原始数据（须给加工结论+依据）", "各 report 须含结论段+数值依据，结构校验"),
    Prohibition("P-09", "禁止单向论证（必须多空双向）", "强制阶段2；require(bull_history 且 bear_history 非空)"),
    Prohibition("P-10", "禁止'两个都行'（必须决断取舍）", "must_tradeoff + no_vague('都行/均可'入黑名单)"),
    Prohibition("P-11", "禁止忽略仓位上限（单票/总仓位/持仓数）", "check_single_position + check_holding_cap + exposure 封顶"),
    Prohibition("P-12", "禁止止损延期（触发即执行，不得延后）", "check_stop_loss_tiers 强制；执行员不得挂起止损"),
    Prohibition("P-13", "禁止未校准数据源（数据须来自已验证源）", "数据源白名单 + provenance + 校准检查"),
    Prohibition("P-14", "禁止修改风控参数", "仅协调器可 reload()；运行时 config 哈希校验"),
]

_BY_ID = {p.pid: p for p in PROHIBITIONS}


def require(condition: bool, pid: str, detail: str = "") -> None:
    """运行时硬断言。condition 为假 = 触犯禁止行为 pid，立即抛错。"""
    if not condition:
        p = _BY_ID.get(pid)
        name = p.name if p else pid
        raise ProhibitionError(f"触犯禁止行为 [{pid}] {name}：{detail}")


def describe() -> str:
    return "\n".join(f"[{p.pid}] {p.name}  ← {p.enforced_by}" for p in PROHIBITIONS)


class ProhibitionEscalation(RuntimeError):
    """重算次数耗尽仍违规 → 升级人工裁决（不静默放行）。"""


def run_with_enforcement(run_fn, *, max_retries: int = 2, on_invalidated=None):
    """
    「作废重算」执行器：跑一次分析；若触犯禁止行为则作废、重算。
    run_fn(attempt:int) -> result。重算前可借 on_invalidated 注入纠正上下文。
    超过 max_retries 仍违规 → 抛 ProhibitionEscalation 交人工。
    """
    attempt = 0
    last_err = None
    while attempt <= max_retries:
        try:
            return run_fn(attempt)
        except ProhibitionError as e:
            last_err = e
            attempt += 1
            if on_invalidated:
                on_invalidated(e, attempt)
    raise ProhibitionEscalation(
        f"连续 {attempt} 次触犯禁止行为，已作废并升级人工裁决：{last_err}")
