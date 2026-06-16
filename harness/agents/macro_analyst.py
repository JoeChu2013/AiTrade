"""
① 市场宏观分析师（混合）。

LLM 前端职责：把定性研判转成 6 因子 0-100 分 + 政策利空标记；
确定性后端：交 regime grader 出 S/A/B/C/D。
本类是后端封装 + 接口；离线/无 LLM 时直接接收因子分。
"""
from __future__ import annotations

from ..models import MarketRegime
from ..regime import grade_market


class MacroAnalyst:
    def assess(self, factors: dict, policy_headwind: bool = False) -> MarketRegime:
        """factors: {index_trend,breadth,volume,stability,capital_flow,sentiment} 0-100。"""
        return grade_market(factors, policy_headwind=policy_headwind)
