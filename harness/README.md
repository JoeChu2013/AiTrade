# AI 量化交易团队 · Harness 工程框架

在开源 **TradingAgents-CN** 之上加一层"纪律编排层"，把一个 13 角色的股票分析团队
"一人成军"地跑起来。底层 12-Agent 深析图原样复用，我们只在外面包护栏和协调器。

> 设计决策（经人工裁决，rule #3）：**A1 外包裹 + B1 纪律=确定性代码 + C1 协调器=第13角色**

标记说明：**【新增】= 本框架在开源底座之外扩充的条目**（你在需求里没明确、但工程上需要的）。

---

## 1. 分层架构

```
【新增】L0  协调器 Coordinator ───────────── 第13角色，纯编排+确定性规则，不拍脑袋
            │  （orchestrator.py）
【新增】L0.5 护栏层 Guardrails ───────────── 6原则/12排除/8纪律/止损三档/时间节点/14禁止
            │  （guardrails/，确定性 Python，LLM 不可绕过）
            ▼
       L1  采集 ── 市场/基本面/新闻/情绪 4 分析师      ┐
       L2  研究 ── 多头/空头研究员 + 研究主管          │ 复用开源
       L3  交易 ── 交易员                              │ 12-Agent 图
       L4  风控 ── 激进/中性/保守 3 风控 + 风控主管     ┘ （deep_dive.py 适配）
            │
【新增】贯穿 ── 市场环境定级 + 两层股票池 + 7 套战术工作流
```

**信息怎么流动**：所有 Agent **不直接通信**（禁止行为 P-04）。协调器维护一块"黑板"
（`models.py` 里的 dataclass），上游 Agent 写自己的字段，下游只读上游写好的字段 —— 这正是
开源底座 `AgentState` 的黑板模式，我们沿用它。

## 2. 13 个角色

| # | 角色 | 层 | 来源 |
|---|---|---|---|
| 1 | 市场分析师 | L1 采集 | 开源 `market_analyst` |
| 2 | 基本面分析师 | L1 | 开源 `fundamentals_analyst` |
| 3 | 新闻分析师 | L1 | 开源 `news_analyst` |
| 4 | 情绪分析师 | L1 | 开源 `social_media_analyst` |
| 5 | 多头研究员 | L2 研究 | 开源 `bull_researcher` |
| 6 | 空头研究员 | L2 | 开源 `bear_researcher` |
| 7 | 研究主管 | L2 | 开源 `research_manager` |
| 8 | 交易员 | L3 交易 | 开源 `trader` |
| 9 | 激进风控 | L4 风控 | 开源 `risky_debator` |
| 10 | 中性风控 | L4 | 开源 `neutral_debator` |
| 11 | 保守风控 | L4 | 开源 `safe_debator` |
| 12 | 风控主管 | L4 | 开源 `risk_manager` |
| 13 | **协调器** | **L0** | **【新增】** `orchestrator.Coordinator` |

## 3. 六大核心原则（`guardrails/principles.py`，编码为约束而非口号）

| 原则 | 落地方式 |
|---|---|
| 环境优先 | 先 `grade_market()` 定级 S/A/B/C/D，再选股；D 级直接跳过选股 |
| 排除后推荐 | 先跑 12 排除规则砍掉，幸存者才进入深析与推荐 |
| 禁止模糊语言 | 结论必须是明确 `Verdict` 枚举；理由含"可能/也许/再看看"等词直接抛错 |
| 必须有取舍 | 候选 > 开仓容量时强制砍；超量触发人工裁决 |
| 承认信息缺口 | 缺字段记入 `info_gaps`，挂到决策理由并下调置信度 |
| 严格止盈止损 | 买入缺止盈或止损 = 裸单，直接拒绝 |

## 4. 市场环境定级 S/A/B/C/D（`regime/`）

多因子加权 0-100 分 → 按 `config/harness_config.yaml` 区间映射。**所有因子统一"越高越偏多"**
（波动率请转成 `stability=100-波动率分位` 再传，避免特判）。

| 级 | 分数 | 含义 | 姿态 | 今日开新仓上限 |
|---|---|---|---|---|
| S | 80-100 | 偏好 | 积极进攻 | 3 |
| A | 50-79 | 利好 | 正常操作 | 2 |
| B | 20-49 | 中性偏暖 | 谨慎试探 | 1 |
| C | 10-19 | 中性偏凉 | 防守为主 | 0 |
| D | 0-9 | 强利空 | **强制空仓** | 0 |

> 注：原始需求里相邻档位的百分比区间有重叠/留白（如 A 50-60、B 20-30）。**【新增】**
> 我把它收敛成无缝、无重叠的整数区间，否则同一个分数可能落到两个等级或无处可归。
> 阈值都在 config 里，可随时调。

## 5. 七套战术工作流（`workflows.py`）

同一套 Agent + 护栏，不同调用姿势——目的是"管住自己的手"，不是预测市场。

1. **全链路分析** `full_analysis` — 环境→筛→取舍→深析→风控（最完整）
2. **池中优选** `pool_optimize` — 只筛+预打分排序，不烧 LLM
3. **横向对比** `compare` — 指定少数标的逐一深析后并排比
4. **持仓巡检** `portfolio_review` — 止损三档 + 逐仓复评，不开新仓
5. **市场快照** `market_snapshot` — 只做环境定级
6. **补充批注** `annotate` — 给标的追加人工/数据批注
7. **批量筛选** `batch_screen` — 整池跑排除规则，出黑白名单

## 6. 交易纪律（`guardrails/trading_discipline.py`）

- **止损三档制**：日亏 -3%/-5%、周亏 -5%/-8%、月亏 -8%/-12% → 减仓/暂停/强制空仓
- **仓位规则**：最多持 3 支、单票 ≤40%、日内浮亏不补仓、止盈下限 8%
- **时间节点**（`time_rules.py`）：14:30 后不开新仓、开盘 15 分钟/尾盘 5 分钟禁区、非交易时段不下单

## 7. 12 项排除规则（`guardrails/exclusion_rules.py`）

E-01 ST/*ST｜E-02 停牌｜E-03 流动性不足｜E-04 次新股｜E-05 高位连板｜E-06 禁止追高｜
E-07 估值畸高｜E-08 高股权质押｜E-09 高负债｜E-10 近期违规｜E-11 微市值易操纵｜E-12 换手过热

> 数据缺失策略：**【新增】** 安全红线（ST/停牌）缺失则保守排除；其余缺失只记信息缺口、不武断排除
> （呼应"承认信息缺口"）。具体阈值见代码，可参数化。

## 8. 14 项禁止行为（`guardrails/prohibitions.py`）

每条要么由架构天然保证，要么映射到一条会拦截的规则，要么有运行时硬断言 `require()`。
`ProhibitionError` 是硬失败：宁可崩，不可违规放行。运行 `python -c "from harness.guardrails
import prohibitions as p; print(p.describe())"` 看全表与各自的兜底机制。

## 9. 人工裁决机制（rule #3）

重大分歧时，协调器发出 `HumanDecisionRequest`：**至少 2 个选项 + 每项理由 + 推荐项**。
当前内置触发点：候选数超过开仓容量（取舍分歧）。处理器可插拔：
- `auto_recommend_handler`（默认）：选推荐项并在报告里标注"未经人工确认"——仅供离线跑通。
- `interactive_handler`：命令行让人真正拍板。**生产环境用这个。**

新增触发点（如环境处于等级边界、深析与护栏结论冲突）可在 orchestrator 里挂更多
`HumanDecisionRequest`。

## 10. 怎么跑

```bash
# 1) 离线骨架演示（无需 LLM key，用 StubDeepDiveAdapter）
python -m harness.demo

# 2) 护栏单测（验证纪律确实会"咬人"）
python -m harness.tests.test_guardrails      # 或 pytest harness/tests -q

# 3) 接真实深析引擎：配置 TradingAgents-CN 的 .env 与模型 key 后
#    把 Coordinator(adapter=StubDeepDiveAdapter()) 换成 DeepDiveAdapter()
```

依赖：`pyyaml`（护栏/编排层）。真实深析另需安装 `TradingAgents-CN/requirements`（LangGraph 等）。

## 11. 待办 / 后续扩展点

- [ ] 股票池补到 100 + 50（当前是模板示例）
- [ ] 接真实行情源填充 `StockMetrics`（现为手工/桩数据）
- [ ] 环境因子接真实大盘数据（指数动量、涨跌家数、北向资金…）
- [ ] **【新增】** 决策落库 + 复盘审计（每条 `HarnessDecision` 已带时间戳与护栏明细，可直接持久化）
- [ ] 把更多人工裁决触发点接入（等级边界、信号冲突）
```
