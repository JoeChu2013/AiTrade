"""
七大交易时段闸（doc08）。总则：14:30 后不开新仓、尾盘只卖不买。

提供：
  current_segment(now)        -> 当前时段 dict
  can_trade(now) / can_buy(now)
  check_time_gates(now, opening_new) -> list[RuleHit]
"""
from __future__ import annotations

from datetime import datetime, time
from typing import Optional

from ..config_loader import load_config
from ..models import RuleHit, RuleKind

_K = RuleKind.SITUATIONAL


def _parse(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))


def current_segment(now: datetime) -> Optional[dict]:
    t = now.time()
    for seg in load_config()["time_segments"]:
        if _parse(seg["start"]) <= t < _parse(seg["end"]):
            return seg
    return None


def can_trade(now: datetime) -> bool:
    seg = current_segment(now)
    return bool(seg and seg["trade"])


def can_buy(now: datetime) -> bool:
    seg = current_segment(now)
    return bool(seg and seg["buy"])


def check_time_gates(now: datetime, opening_new: bool) -> list:
    seg = current_segment(now)
    hits = []
    if seg is None:
        hits.append(RuleHit("T-04", "交易时段", _K, False,
                            f"{now.time().strftime('%H:%M')} 非交易时段，禁下单"))
        return hits

    hits.append(RuleHit("T-04", "交易时段", _K, seg["trade"],
                        f"[{seg['id']}] {seg['note']}"))
    if not seg["trade"]:
        return hits

    if opening_new:
        # T-01：买入窗口 + 14:30 前
        cutoff = _parse(load_config()["no_new_after"])
        if now.time() >= cutoff:
            hits.append(RuleHit("T-01", "午后禁开新仓", _K, False,
                                f"{cutoff.strftime('%H:%M')} 后不开新仓"))
        elif not seg["buy"]:
            hits.append(RuleHit("T-01", "买入窗口", _K, False,
                                f"[{seg['id']}] 非买入窗口（{seg['note']}）"))
        else:
            hits.append(RuleHit("T-01", "买入窗口", _K, True, f"[{seg['id']}] 可开新仓"))
    return hits
