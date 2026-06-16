"""
L0.5 护栏层 —— 决策 B1：纪律用确定性代码实现，LLM 不可绕过。

组成：
  principles        六大核心原则（编码为可执行约束）
  exclusion_rules   12 项排除规则引擎
  trading_discipline 8 项交易纪律 + 止损三档制
  time_rules        交易时段闸断
  prohibitions      14 项禁止行为登记表 + 运行时断言

GuardrailEngine 把它们组合成"一道闸"：任何要落地的动作都必须先过闸。
"""
from .engine import GuardrailEngine
from .prohibitions import ProhibitionError, PROHIBITIONS

__all__ = ["GuardrailEngine", "ProhibitionError", "PROHIBITIONS"]
