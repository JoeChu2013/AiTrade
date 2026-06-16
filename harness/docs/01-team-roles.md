# 详细设计 01 · 团队分工（13 角色）

> 基线决策：A1 外包裹 + B1 纪律=确定性代码 + C1 协调器编排。
> 本文档的结构性选择：**Fork1=A（风控 2 岗）、Fork2=A（运营岗确定性）、Fork3=A（#1 宏观，个股技术留在深析内）**。
> 标记：**【新增】= 开源底座之外扩充**；**实现方式**分 `LLM` / `确定性` / `混合`。

## 0. 组织结构与信息流

```
                         ┌─────────────────────────────────────────┐
                         │  L0 协调器 Coordinator（第13角色之外的编排器）│
                         │   按 7 套战术工作流调度，维护"黑板"          │
                         └─────────────────────────────────────────┘
环境优先 ─►  ① 市场宏观分析师 ──► regime grader ──► S/A/B/C/D（决定仓位基调）
                         │  D 级 → 直接空仓，后续全部跳过
                         ▼
选股 ─►  ⑨ 股票池管理 ──(候选池)──► ⑧ 选股筛选(12排除) ──(白名单)──►
                         ▼
逐只深析（复用开源 12-Agent 图）：
        ② 基本面  ③ 新闻  ④ 情绪  (＋深析内置个股技术分析师)  ── 并行采集
                         ▼
        ⑤ 多头研究员  ⇄ 强制辩论 ⇄  ⑥ 空头研究员
                         ▼
        ⑦ 研究主管 ── 汇总生成标准化研报
                         ▼
交易 ─►  ⑩ 交易测算员（仓位/入场价/盈亏比） ──► ⑪ 分时交易执行员（时间闸+下单）
                         ▼
风控 ─►  ⑫ 一级风控（持仓实时巡检/止损三档） ──► ⑬ 终审风控主管（一票否决）
```

**通信规则**：所有角色不直接对话（禁止行为 P-04）。每个角色只读上游写好的黑板字段、只写自己的字段；协调器负责喂数据与推进。

---

## 1. 信息采集层（4 大分析师，并行）

### ① 市场宏观分析师　【新增（顶层角色）】
- **实现方式**：混合（LLM 定性研判 → 确定性 regime grader 定级）
- **职责**：判断大盘整体环境（指数趋势、市场宽度、量能、稳定度、资金流、情绪），分级市场冷热，决定全局仓位基调。
- **输入**：大盘指数行情、涨跌家数、北向/主力资金、波动率、政策面摘要。
- **输出（黑板）**：`MarketRegime{grade, score, stance, max_new_positions, factors}`。
- **代码**：`harness/regime/market_regime.py`（grader 已建）｜LLM 前端：**待建** `harness/agents/macro_analyst.py`（产出 6 因子 0-100 分喂 grader）。
- **纪律绑定**：原则一（环境优先）；D 级触发 P-09 强制空仓。
- **个股技术面**：不在本角色；由深析子程序内置技术分析师承担（Fork3-A）。

### ② 基本面分析师
- **实现方式**：LLM
- **职责**：拆解财报、营收、利润、估值、行业地位，做企业价值判断。
- **输入**：财务三表、估值指标、行业数据。
- **输出（黑板）**：`fundamentals_report`。
- **代码**：复用开源 `tradingagents/agents/analysts/fundamentals_analyst.py`（深析子程序内）。

### ③ 舆情新闻分析师
- **实现方式**：LLM
- **职责**：抓取公告、行业资讯、政策、利空利好。
- **输出（黑板）**：`news_report`。
- **代码**：复用开源 `news_analyst.py`。

### ④ 市场情绪分析师
- **实现方式**：LLM
- **职责**：板块热度、资金流向、散户/机构情绪、涨跌家数。
- **输出（黑板）**：`sentiment_report`。
- **代码**：复用开源 `social_media_analyst.py`。

> ②③④ 与深析内置技术分析师并行同步输出基础数据，构成"个股四账本"。

---

## 2. 研究层（多空辩论 + 主管）

### ⑤ 多头研究员
- **实现方式**：LLM｜**职责**：只站多方，罗列全部上涨逻辑、催化因素、上涨空间。
- **输出**：`investment_debate_state.bull_history`。｜**代码**：开源 `bull_researcher.py`。

### ⑥ 空头研究员
- **实现方式**：LLM｜**职责**：只站空方，挖风险、利空、暴雷点、下跌诱因。
- **输出**：`investment_debate_state.bear_history`。｜**代码**：开源 `bear_researcher.py`。
- **机制**：⑤⑥ 强制对辩（`max_debate_rounds`），杜绝单边乐观/悲观。

### ⑦ 研究主管
- **实现方式**：LLM（deep model）｜**职责**：汇总 4 分析师 + 多空双方，生成**标准化个股完整研报**。
- **输入**：上述全部黑板字段。｜**输出**：`investment_plan`（标准研报）。
- **代码**：开源 `research_manager.py`。
- **纪律绑定**：原则三（研报结论须明确）、原则五（缺口须标注）。

---

## 3. 选股与股票池（运营岗，确定性 — Fork2-A）

### ⑧ 选股筛选 Agent　【新增（独立成岗）】
- **实现方式**：确定性
- **职责**：依托 12 条淘汰规则自动过滤不合格标的，输出白/黑名单。
- **输入**：`StockMetrics` 快照。｜**输出**：`GuardrailResult`（含 `blocked_by` 规则号、`info_gaps`）。
- **代码**：`harness/guardrails/exclusion_rules.py`（已建，E-01~E-12）。
- **纪律绑定**：原则二（排除后推荐）；安全红线缺数据保守排除，其余记缺口。

### ⑨ 股票池管理 Agent　【新增（独立成岗）】
- **实现方式**：确定性
- **职责**：维护两层固定池（100 主板 + 50 自选），自动更新、剔除退市/暴雷个股。
- **输入**：池配置 + 退市/风险事件源。｜**输出**：可分析候选集合。
- **代码**：`harness/pool/stock_pool.py`（已建）｜**待建**：退市/暴雷自动剔除钩子 `prune_delisted()` / `prune_blowup()`。
- **纪律绑定**：`analyze_only_from_pool`（日常只在池内选，提效）。

---

## 4. 交易层

### ⑩ 交易测算员
- **实现方式**：混合（开源 trader 给方向 + 确定性测算仓位/价位/盈亏比）
- **职责**：据研报 + 市场等级，计算合理仓位、入场价位、盈亏比。
- **输入**：`investment_plan`、`MarketRegime`、`Portfolio`。
- **输出（黑板）**：`trader_investment_plan` + `HarnessDecision{target_position_pct, take_profit_pct, stop_loss_pct}`。
- **代码**：开源 `trader.py`（方向）｜`harness/orchestrator._suggest_position_pct`（雏形）｜**待建** `harness/agents/sizing.py`（盈亏比≥设定阈值才放行、按环境分级给仓位、入场价区间）。
- **纪律绑定**：原则六（必带止盈止损）、纪律 D-03 单票上限、D-07 环境额度。

### ⑪ 分时交易执行员　【新增】
- **实现方式**：确定性
- **职责**：严格遵守时间规则，执行开仓/减仓/清仓；禁止情绪化操作。
- **输入**：交易测算员的指令 + 当前时刻。｜**输出**：执行回执 / 被时间闸拒绝的记录。
- **代码**：`harness/guardrails/time_rules.py`（时间闸已建）｜**待建** `harness/execution.py`（指令路由 + 下单接口 + 回执；先做 paper-trading 桩）。
- **纪律绑定**：T-01 14:30 后不开新仓、T-02 开盘缓冲、T-03 尾盘禁挂、T-04 非交易时段；P-08 浮亏不补仓。

---

## 5. 风控层（2 岗 — Fork1-A）

### ⑫ 一级风控 Agent
- **实现方式**：确定性
- **职责**：持仓实时巡检，监控单日/单周/月度亏损阈值，触发减仓/暂停/空仓。
- **输入**：`Portfolio`（日/周/月滚动盈亏）。｜**输出**：止损触发清单（`GuardrailResult`）。
- **代码**：`harness/guardrails/trading_discipline.check_stop_loss_tiers` + `workflows.portfolio_review`（已建）。
- **纪律绑定**：纪律 D-01 止损三档制。

### ⑬ 终审风控主管
- **实现方式**：LLM（deep model）+ 确定性否决闸
- **职责**：最终把关；市场环境恶劣或风险超标时**直接否决全部交易**（一票否决）。
- **输入**：`MarketRegime`、一级风控清单、全部 `HarnessDecision`。
- **输出（黑板）**：`final_trade_decision`（放行/否决 + 理由）。
- **代码**：开源 `risk_manager.py`（研判）｜**待建** `harness/agents/final_risk_gate.py`（确定性否决：D 级 / 触发硬止损线 / 超持仓 → 强制全否，LLM 仅在闸内做细化，不能推翻硬否决）。
- **纪律绑定**：P-02 风控不可短路、P-09 D 级空仓；与协调器人工裁决门联动。

---

## 6. 实现状态总表

| # | 角色 | 实现 | 代码位置 | 状态 |
|---|---|---|---|---|
| ① | 市场宏观分析师 | 混合 | regime grader + 待建 LLM 前端 | grader✅ / LLM 待建 |
| ② | 基本面分析师 | LLM | 开源 fundamentals_analyst | ✅(深析内) |
| ③ | 舆情新闻分析师 | LLM | 开源 news_analyst | ✅ |
| ④ | 市场情绪分析师 | LLM | 开源 social_media_analyst | ✅ |
| ⑤ | 多头研究员 | LLM | 开源 bull_researcher | ✅ |
| ⑥ | 空头研究员 | LLM | 开源 bear_researcher | ✅ |
| ⑦ | 研究主管 | LLM | 开源 research_manager | ✅ |
| ⑧ | 选股筛选 | 确定性 | guardrails/exclusion_rules | ✅ |
| ⑨ | 股票池管理 | 确定性 | pool/stock_pool（+剔除钩子） | 部分 |
| ⑩ | 交易测算员 | 混合 | 开源 trader + 待建 sizing | 部分 |
| ⑪ | 分时交易执行员 | 确定性 | time_rules + 待建 execution | 部分 |
| ⑫ | 一级风控 | 确定性 | trading_discipline + portfolio_review | ✅ |
| ⑬ | 终审风控主管 | LLM+闸 | 开源 risk_manager + 待建否决闸 | 部分 |

**本轮新增待建清单**：`agents/macro_analyst.py`、`pool` 退市/暴雷剔除钩子、`agents/sizing.py`、`execution.py`、`agents/final_risk_gate.py`。
