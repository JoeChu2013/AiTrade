"""
TradeLedger —— 交易流水/计数状态，支撑 D-07（频率）与 D-08（单日次数）。

最小实现：内存记录每笔交易 (date, code, side)。生产可换持久化后端。
日期用 'YYYY-MM-DD' 字符串；交易日差按自然日近似（够用；精确交易日历可后接）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


def _d(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


@dataclass
class Trade:
    date: str
    code: str
    side: str   # "buy" / "sell"


@dataclass
class TradeLedger:
    trades: list = field(default_factory=list)  # list[Trade]

    def record(self, date_str: str, code: str, side: str) -> None:
        self.trades.append(Trade(date_str, code, side))

    # --- D-08 ---
    def new_trades_today(self, date_str: str) -> int:
        return sum(1 for t in self.trades if t.date == date_str and t.side == "buy")

    def total_trades_today(self, date_str: str) -> int:
        return sum(1 for t in self.trades if t.date == date_str)

    # --- D-07 ---
    def days_since_last_sell(self, code: str, now_date: str):
        sells = [t.date for t in self.trades if t.code == code and t.side == "sell"]
        if not sells:
            return None
        last = max(_d(s) for s in sells)
        return (_d(now_date) - last).days

    def roundtrips_20d(self, code: str, now_date: str) -> int:
        """近20自然日内 buy→sell 完整往返次数（近似）。"""
        recent = [t for t in self.trades if t.code == code
                  and (_d(now_date) - _d(t.date)).days <= 20]
        buys = sum(1 for t in recent if t.side == "buy")
        sells = sum(1 for t in recent if t.side == "sell")
        return min(buys, sells)
