"""
⑩ 交易测算员（混合）—— 阶段3：R:R + 买点 + 仓位精算。

止盈止损来自规则（D-05/原则六，不接受 LLM 自由设定）；R:R 由二者算出；
仓位按环境单票上限封顶、按置信度微调。
"""
from __future__ import annotations

from ..guardrails.trading_discipline import default_tp_sl, single_position_cap
from ..models import MarketRegime, StockMetrics


def size_trade(regime: MarketRegime, metrics: StockMetrics, conviction: float = 0.7) -> dict:
    tp_pct, sl_pct = default_tp_sl()                 # 如 +10% / -5%
    entry = metrics.price if metrics.price is not None else metrics.close
    risk_reward = round(tp_pct / abs(sl_pct), 2) if sl_pct else None
    cap = single_position_cap(regime)                # min(环境档, 30%)
    # 仓位按置信度在 60%~100% 区间缩放，但不超单票上限
    target = round(min(cap, cap * (0.6 + 0.4 * max(0.0, min(1.0, conviction)))), 1)
    return {
        "entry_price": entry,
        "take_profit_pct": tp_pct,
        "stop_loss_pct": sl_pct,
        "risk_reward": risk_reward,
        "target_position_pct": target,
    }
