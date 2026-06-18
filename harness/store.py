"""
状态持久化（JSON，简单可靠；后续可换 sqlite）。
存：持仓 positions、交易流水 ledger、权益快照 equity（供周/月止损）。
文件在 harness/state/（本地，已 gitignore）。
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from .ledger import TradeLedger, Trade
from .models import Portfolio, Position

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
_POS = os.path.join(_DIR, "positions.json")
_LEDGER = os.path.join(_DIR, "ledger.json")
_EQUITY = os.path.join(_DIR, "equity.json")


def _ensure():
    os.makedirs(_DIR, exist_ok=True)


def load_portfolio() -> Portfolio:
    _ensure()
    if not os.path.exists(_POS):
        return Portfolio(cash=0.0)
    d = json.load(open(_POS, encoding="utf-8"))
    positions = [Position(**p) for p in d.get("positions", [])]
    return Portfolio(cash=d.get("cash", 0.0), positions=positions,
                     daily_pnl_pct=d.get("daily_pnl_pct", 0.0),
                     weekly_pnl_pct=d.get("weekly_pnl_pct", 0.0),
                     monthly_pnl_pct=d.get("monthly_pnl_pct", 0.0))


def save_portfolio(pf: Portfolio) -> None:
    _ensure()
    d = {"cash": pf.cash,
         "daily_pnl_pct": pf.daily_pnl_pct,
         "weekly_pnl_pct": pf.weekly_pnl_pct,
         "monthly_pnl_pct": pf.monthly_pnl_pct,
         "positions": [vars(p) for p in pf.positions]}
    json.dump(d, open(_POS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def load_ledger() -> TradeLedger:
    _ensure()
    if not os.path.exists(_LEDGER):
        return TradeLedger()
    rows = json.load(open(_LEDGER, encoding="utf-8"))
    return TradeLedger(trades=[Trade(**t) for t in rows])


def save_ledger(led: TradeLedger) -> None:
    _ensure()
    json.dump([vars(t) for t in led.trades], open(_LEDGER, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


def append_equity(value: float, when: str = None) -> None:
    _ensure()
    hist = []
    if os.path.exists(_EQUITY):
        hist = json.load(open(_EQUITY, encoding="utf-8"))
    hist.append({"ts": when or datetime.now().isoformat(timespec="seconds"),
                 "equity": value})
    json.dump(hist[-500:], open(_EQUITY, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
