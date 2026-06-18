"""
Harness 共享数据模型。

这些 dataclass 是"黑板"上流转的结构化对象——协调器在各层之间传递的就是它们，
而不是让 13 个 Agent 互相喊话（P-06 禁止跨 Agent 通信）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------
class RegimeGrade(str, Enum):
    """市场环境定级 —— 原则一「环境优先」。"""
    S = "S"
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class Verdict(str, Enum):
    """执行动作（持仓/下单层面）。明确值，禁止模糊。"""
    BUY = "买入"
    HOLD = "持有"
    SELL = "卖出"
    REDUCE = "减仓"
    CLEAR = "清仓"
    REJECT = "排除"
    NO_ACTION = "不操作"


class BuyRating(str, Enum):
    """个股分析最终 5 选 1 评级（阶段5 输出）。P-01 禁止二选一/模糊。
    仅 BUY 可直接转 Verdict.BUY；其余不立即开仓。"""
    BUY = "可适仓买入"            # 1
    CONDITIONAL = "条件满足才可买"  # 2
    NON_PRIORITY = "可买但不优先"   # 3
    WATCH = "只可观察不可买"        # 4
    NO_BUY = "明确不买"            # 5


class GateStatus(str, Enum):
    PASS = "通过"
    BLOCK = "拦截"
    NEEDS_HUMAN = "待人工裁决"


class RuleKind(str, Enum):
    """排除/检查规则的性质（doc04 v2）。"""
    RED_LINE = "红线"        # 单条即剔除 → 明确不买
    HARD = "硬排除"          # 计入计数分级（≥2 → 只可观察）
    SITUATIONAL = "情境闸"   # 不剔除标的，仅压评级/挡当下买入


# ---------------------------------------------------------------------------
# 市场环境
# ---------------------------------------------------------------------------
@dataclass
class MarketRegime:
    grade: RegimeGrade
    score: float
    label: str
    stance: str
    max_new_positions: int
    exposure_min: float = 0.0
    exposure_max: float = 0.0
    max_single_position_pct: float = 0.0
    direction: int = 0               # 大盘方向：+1 多 / -1 空 / 0 中性（供 E-06）
    factors: dict = field(default_factory=dict)
    force_flat: bool = False
    policy_override: bool = False     # 政策利空一票压 D

    def summary(self) -> str:
        return (f"大盘环境 {self.grade.value} 级（{self.label}，{self.score:.0f}分）"
                f"｜姿态：{self.stance}｜总仓位 {self.exposure_min:.0f}-{self.exposure_max:.0f}%"
                f"｜单票≤{self.max_single_position_pct:.0f}%｜今日可开新仓 {self.max_new_positions}")


# ---------------------------------------------------------------------------
# 个股指标快照（字段对应 E-01~E-13；缺失用 None → 信息缺口）
# ---------------------------------------------------------------------------
@dataclass
class StockMetrics:
    code: str
    name: str = ""
    sector: str = ""                              # 行业板块（E-12）
    price: Optional[float] = None

    # E-01 基本面恶化
    net_profit_declining_quarters: Optional[int] = None  # 净利连续同比下降季数
    gross_margin: Optional[float] = None                 # 毛利率 %
    # E-02 估值过高
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    industry_pe_mean: Optional[float] = None
    yoy_net_profit: Optional[float] = None               # 净利同比增长 %（≤0 视无增长）
    # E-03 技术面破位
    close: Optional[float] = None
    ma60: Optional[float] = None
    macd_dead_cross: Optional[bool] = None
    # E-04 重大利空（红线）
    is_st: Optional[bool] = None
    regulatory_event: Optional[bool] = None              # 立案/问询/处罚
    unlock_ratio: Optional[float] = None                 # 解禁市值/流通 %
    top_holder_pledge_ratio: Optional[float] = None      # 第一大股东质押 %
    major_incident: Optional[bool] = None                # 突发重大安全事故
    is_suspended: Optional[bool] = None
    delisting_risk: Optional[bool] = None
    # E-05 流动性
    avg_amount_20d: Optional[float] = None               # 近20日日均成交额（元）
    avg_turnover_20d: Optional[float] = None             # 近20日日均换手 %
    # E-06 违背方向
    trend_dir: Optional[int] = None                      # 个股趋势：+1/-1/0
    # E-08 追涨形态
    gain_1d: Optional[float] = None                      # 当日涨幅 %
    gain_3d: Optional[float] = None                      # 近3日累计涨幅 %
    consecutive_limit_ups: Optional[int] = None
    # E-10 除权除息
    pre_record_gain_pct: Optional[float] = None          # 登记日前抢权窗口累计涨幅 %
    days_since_ex: Optional[int] = None                  # 距除权除息日的交易日数（0=当天）
    in_pre_record_window: Optional[bool] = None          # 是否处抢权窗口
    # E-13 负面舆情
    negative_news_score: Optional[float] = None          # 0-100

    raw: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 排除/检查结果
# ---------------------------------------------------------------------------
@dataclass
class RuleHit:
    rule_id: str
    rule_name: str
    kind: RuleKind
    passed: bool
    detail: str = ""

    def __str__(self) -> str:
        mark = "✅" if self.passed else "⛔"
        return f"{mark} [{self.rule_id}/{self.kind.value}] {self.rule_name}: {self.detail}"


@dataclass
class ScreenResult:
    """选股筛选 Agent ⑧ 的产出（doc04 v2 分类口径）。"""
    hits: list = field(default_factory=list)          # list[RuleHit]
    red_line_hits: list = field(default_factory=list) # list[str] rule_ids（单条即剔）
    hard_hits: list = field(default_factory=list)     # list[str]（计入分级）
    situational_hits: list = field(default_factory=list)  # list[str]（仅压评级）
    info_gaps: list = field(default_factory=list)

    @property
    def has_red_line(self) -> bool:
        return bool(self.red_line_hits)

    @property
    def hard_count(self) -> int:
        return len(self.hard_hits)

    @property
    def excluded(self) -> bool:
        """红线 或 硬排除≥2 → 不可买（剔除/只可观察）。"""
        return self.has_red_line or self.hard_count >= 2

    def failures(self) -> list:
        return [h for h in self.hits if not h.passed]


@dataclass
class GuardrailResult:
    """交易级综合校验（vet_trade / 止损）结果。"""
    status: GateStatus
    hits: list = field(default_factory=list)
    blocked_by: list = field(default_factory=list)
    info_gaps: list = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == GateStatus.PASS

    def failures(self) -> list:
        return [h for h in self.hits if not h.passed]


# ---------------------------------------------------------------------------
# 持仓 / 组合
# ---------------------------------------------------------------------------
@dataclass
class Position:
    code: str
    name: str
    cost: float
    qty: int
    current_price: float
    sector: str = ""
    open_date: Optional[str] = None
    peak_price: Optional[float] = None      # 持有期最高价（D-05 移动止盈）

    @property
    def market_value(self) -> float:
        return self.current_price * self.qty

    @property
    def pnl_pct(self) -> float:
        if not self.cost:
            return 0.0
        return (self.current_price - self.cost) / self.cost * 100.0


@dataclass
class Portfolio:
    cash: float = 0.0
    positions: list = field(default_factory=list)  # list[Position]
    daily_pnl_pct: float = 0.0
    weekly_pnl_pct: float = 0.0
    monthly_pnl_pct: float = 0.0

    @property
    def holding_count(self) -> int:
        return len(self.positions)

    @property
    def total_value(self) -> float:
        return self.cash + sum(p.market_value for p in self.positions)

    @property
    def exposure_pct(self) -> float:
        tv = self.total_value
        if tv <= 0:
            return 0.0
        return sum(p.market_value for p in self.positions) / tv * 100.0

    def sector_count(self, sector: str) -> int:
        return sum(1 for p in self.positions if p.sector == sector)


# ---------------------------------------------------------------------------
# 最终决策卡
# ---------------------------------------------------------------------------
@dataclass
class HarnessDecision:
    code: str
    name: str
    verdict: Verdict
    confidence: float
    buy_rating: Optional[BuyRating] = None
    target_position_pct: float = 0.0
    entry_price: Optional[float] = None
    risk_reward: Optional[float] = None
    take_profit_pct: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    rationale: str = ""
    screen: Optional[ScreenResult] = None
    guardrail: Optional[GuardrailResult] = None
    deep_dive_signal: Optional[str] = None
    provenance: dict = field(default_factory=dict)   # 数据来源留痕（P-13）
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


# ---------------------------------------------------------------------------
# 人工裁决请求（rule #3）
# ---------------------------------------------------------------------------
@dataclass
class DecisionOption:
    label: str
    reason: str


@dataclass
class HumanDecisionRequest:
    topic: str
    context: str
    options: list
    recommended: Optional[str] = None

    def render(self) -> str:
        lines = [f"⚖️  需人工裁决：{self.topic}", f"背景：{self.context}", "选项："]
        for i, opt in enumerate(self.options, 1):
            tag = "（推荐）" if opt.label == self.recommended else ""
            lines.append(f"  {i}. {opt.label}{tag} —— {opt.reason}")
        return "\n".join(lines)
