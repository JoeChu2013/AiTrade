"""
深析适配器 —— 决策 A1 的"外包裹"接缝。

把开源 TradingAgents-CN 的 12-Agent 单股深析图当作子程序调用：
    TradingAgentsGraph(...).propagate(code, date) -> (final_state, decision)

DeepDiveAdapter   真适配器（需要安装 tradingagents 及 LLM key）
StubDeepDiveAdapter  离线桩（无依赖，用于跑通编排骨架 / 单测 / 演示）

协调器只依赖抽象方法 analyze()，因此底层引擎可替换、可升级，不影响 harness。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .config_loader import load_config


@dataclass
class DeepDiveResult:
    code: str
    signal: str                       # 引擎给出的原始信号文本/决策
    confidence: float = 0.5
    reports: dict = field(default_factory=dict)  # 各分析师/研究/风控的报告
    raw_state: Optional[dict] = None


class BaseDeepDiveAdapter:
    def analyze(self, code: str, trade_date: str) -> DeepDiveResult:
        raise NotImplementedError


class DeepDiveAdapter(BaseDeepDiveAdapter):
    """真适配器。lazy import，避免无 LLM 环境时 import 失败。"""

    # DeepSeek 默认（可被 config 覆盖）
    DEEPSEEK_DEFAULTS = {
        "llm_provider": "deepseek",
        "deep_think_llm": "deepseek-chat",
        "quick_think_llm": "deepseek-chat",
        "backend_url": "https://api.deepseek.com",
        "online_tools": True,
    }

    def __init__(self, config: dict = None, provider: str = "deepseek",
                 env_path: str = None):
        self._cfg = config
        self._provider = provider
        self._env_path = env_path
        self._graph = None

    def _load_env(self):
        """无依赖加载 .env 到 os.environ（python-dotenv 未装也能用）。"""
        import os
        path = self._env_path
        if path is None:
            here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            path = os.path.join(here, "TradingAgents-CN", ".env")
        if not os.path.exists(path):
            return
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

    def _ensure_graph(self):
        if self._graph is not None:
            return
        self._load_env()
        # 仅在真正深析时才加载重依赖
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        from tradingagents.default_config import DEFAULT_CONFIG

        hcfg = load_config()["deep_dive"]
        cfg = dict(DEFAULT_CONFIG)
        if self._provider == "deepseek":
            cfg.update(self.DEEPSEEK_DEFAULTS)
        if self._cfg:
            cfg.update(self._cfg)
        cfg["max_debate_rounds"] = hcfg["max_debate_rounds"]
        cfg["max_risk_discuss_rounds"] = hcfg["max_risk_discuss_rounds"]
        self._graph = TradingAgentsGraph(
            selected_analysts=hcfg["selected_analysts"],
            config=cfg,
        )

    def analyze(self, code: str, trade_date: str) -> DeepDiveResult:
        self._ensure_graph()
        g = self._graph
        # 绕开 propagate() 中 values/updates 模式混淆的 bug：直接 invoke 编译图。
        init_state = g.propagator.create_initial_state(code, trade_date)
        args = g.propagator.get_graph_args(use_progress_callback=False)
        final_state = g.graph.invoke(init_state, config=args.get("config"))
        decision = final_state.get("final_trade_decision", "")
        reports = {
            "market": final_state.get("market_report", ""),
            "sentiment": final_state.get("sentiment_report", ""),
            "news": final_state.get("news_report", ""),
            "fundamentals": final_state.get("fundamentals_report", ""),
            "investment_plan": final_state.get("investment_plan", ""),
            "trader_plan": final_state.get("trader_investment_plan", ""),
            "final_trade_decision": final_state.get("final_trade_decision", ""),
        }
        return DeepDiveResult(code=code, signal=str(decision),
                              reports=reports, raw_state=dict(final_state))


class StubDeepDiveAdapter(BaseDeepDiveAdapter):
    """离线桩：根据传入的信号表返回固定结果，让编排骨架可独立运行。"""

    def __init__(self, signals: dict = None):
        # signals: {code: (signal_text, confidence)}
        self.signals = signals or {}

    def analyze(self, code: str, trade_date: str) -> DeepDiveResult:
        sig, conf = self.signals.get(code, ("买入", 0.6))
        return DeepDiveResult(
            code=code, signal=sig, confidence=conf,
            reports={"note": "StubDeepDiveAdapter：离线桩，未调用真实 LLM 引擎"},
        )
