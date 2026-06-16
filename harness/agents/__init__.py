"""确定性/混合角色模块（戴'Agent'帽子，按 B1 多为确定性代码）。"""
from .macro_analyst import MacroAnalyst
from .sizing import size_trade
from .final_risk_gate import adjudicate

__all__ = ["MacroAnalyst", "size_trade", "adjudicate"]
