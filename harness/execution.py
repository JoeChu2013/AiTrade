"""
⑪ 分时交易执行员（确定性）—— 严格遵守时段，执行开/减/清仓，禁情绪化。

纸面执行（paper）实现：校验时段闸 → 记 TradeLedger。
硬止损卖出为安全例外：不受时段买入窗口限制，但仍需在可交易时段；
非交易时段触发的止损顺延至最近可交易时段（这里仅标记 deferred）。
"""
from __future__ import annotations

from datetime import datetime

from .guardrails import time_rules as T
from .models import Verdict


class Executor:
    def __init__(self, ledger=None):
        self.ledger = ledger

    def execute(self, *, code: str, verdict: Verdict, now: datetime,
                trade_date: str, is_stop_loss: bool = False) -> dict:
        seg = T.current_segment(now)
        in_session = bool(seg and seg["trade"])

        # 开新仓：必须在买入窗口且 14:30 前
        if verdict == Verdict.BUY:
            if not T.can_buy(now):
                return {"status": "rejected", "reason": "非买入窗口/已过14:30", "code": code}
            self._log(trade_date, code, "buy")
            return {"status": "filled", "side": "buy", "code": code}

        # 卖/减/清
        if verdict in (Verdict.SELL, Verdict.REDUCE, Verdict.CLEAR):
            if not in_session:
                # 止损顺延
                return {"status": "deferred", "reason": "非交易时段，顺延至最近可交易时段",
                        "code": code, "is_stop_loss": is_stop_loss}
            self._log(trade_date, code, "sell")
            return {"status": "filled", "side": "sell", "code": code,
                    "is_stop_loss": is_stop_loss}

        return {"status": "noop", "code": code, "verdict": verdict.value}

    def _log(self, trade_date, code, side):
        if self.ledger is not None:
            self.ledger.record(trade_date, code, side)
