"""
AI 量化交易团队 Harness —— 在开源 TradingAgents-CN 之上的纪律编排层。

设计决策：A1（外包裹复用开源）+ B1（纪律=确定性代码）+ C1（协调器=第13角色）。
完整设计见 harness/docs/01-09。
"""
from .config_loader import load_config
from .deep_dive import DeepDiveAdapter, StubDeepDiveAdapter
from .execution import Executor
from .guardrails import GuardrailEngine, ProhibitionError
from .ledger import TradeLedger
from .models import (BuyRating, HarnessDecision, MarketRegime, Portfolio,
                     Position, RegimeGrade, RuleKind, ScreenResult,
                     StockMetrics, Verdict)
from .orchestrator import (Coordinator, OrchestrationReport,
                           auto_recommend_handler, interactive_handler)
from .pool import StockPool
from .regime import grade_market

__all__ = [
    "load_config", "Coordinator", "OrchestrationReport",
    "GuardrailEngine", "ProhibitionError", "TradeLedger", "Executor",
    "DeepDiveAdapter", "StubDeepDiveAdapter", "StockPool", "grade_market",
    "MarketRegime", "RegimeGrade", "StockMetrics", "ScreenResult", "RuleKind",
    "Portfolio", "Position", "HarnessDecision", "Verdict", "BuyRating",
    "auto_recommend_handler", "interactive_handler",
]
