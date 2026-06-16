"""
市场环境定级 S/A/B/C/D（doc03）—— 原则一。

6 因子加权得 0-100 综合分 → 区间映射等级 → 附带固定仓位区间。
所有因子统一"越高越偏多"（波动率请先转 stability=100-波动率分位）。
新增：共振加成、政策利空一票压 D、大盘方向(direction，供 E-06)。
确定性映射：同输入恒同输出，可审计。
"""
from __future__ import annotations

from dataclasses import dataclass

from ..config_loader import load_config
from ..models import MarketRegime, RegimeGrade


@dataclass
class RegimeGrader:
    weights: dict = None

    def __post_init__(self):
        self.weights = self.weights or dict(load_config()["regime"]["weights"])

    def grade(self, factors: dict, policy_headwind: bool = False) -> MarketRegime:
        """
        factors: {因子名: 0-100 子分}。缺失按 50 填充并记缺口。
        policy_headwind=True：系统性政策利空 → 一票压 D（doc03 异常处理）。
        """
        rcfg = load_config()["regime"]
        missing = [k for k in self.weights if factors.get(k) is None]
        filled = {k: (factors.get(k) if factors.get(k) is not None else 50.0)
                  for k in self.weights}

        score = sum(filled[k] * w for k, w in self.weights.items())

        # 共振加成
        thr = rcfg["resonance_threshold"]
        if (filled.get("index_trend", 0) >= thr and filled.get("capital_flow", 0) >= thr
                and filled.get("sentiment", 0) >= thr):
            score += rcfg["resonance_bonus"]
        score = max(0.0, min(100.0, score))

        grade_key = self._score_to_grade(score, rcfg["grades"])

        # 政策一票压 D
        policy_override = bool(policy_headwind)
        if policy_override:
            grade_key = "D"

        g = rcfg["grades"][grade_key]
        force_flat = (grade_key == "D" and rcfg.get("d_grade_force_flat", True))

        detail = dict(filled)
        if missing:
            detail["_info_gaps"] = missing
        if policy_override:
            detail["_policy_override"] = True

        # 大盘方向：综合分≥50 偏多(+1)，<35 偏空(-1)，其间中性(0)
        direction = 1 if score >= 50 else (-1 if score < 35 else 0)
        if grade_key == "D":
            direction = -1

        return MarketRegime(
            grade=RegimeGrade(grade_key), score=score,
            label=g["label"], stance=g["stance"],
            max_new_positions=g["max_new_positions"],
            exposure_min=g.get("exposure_min", 0.0),
            exposure_max=g.get("exposure_max", 0.0),
            max_single_position_pct=g.get("max_single_position_pct", 0.0),
            direction=direction, factors=detail,
            force_flat=force_flat, policy_override=policy_override,
        )

    @staticmethod
    def _score_to_grade(score: float, grades: dict) -> str:
        for key, g in grades.items():
            if g["score_min"] <= score <= g["score_max"]:
                return key
        return "D" if score < grades["D"]["score_max"] else "S"


def grade_market(factors: dict, policy_headwind: bool = False, weights: dict = None) -> MarketRegime:
    return RegimeGrader(weights=weights).grade(factors, policy_headwind=policy_headwind)
