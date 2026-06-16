# 详细设计 02 · 六大核心原则

> 基线：B1 —— 原则一律编码为**确定性约束**，LLM 不可绕过（`harness/guardrails/principles.py` 已有雏形）。
> 标记：**【已建】** 现有代码已覆盖｜**【强化】** 需在现有基础上加严（本轮新增细则）｜**【新增参数】** 待加入 `harness_config.yaml`。
> 本文档默认强度选择：**Fork-A=A1（数值证据）、Fork-B=B1（置信度门槛）、Fork-C=C1（关键字段缺失禁买）**。

---

## 原则一　环境优先 environment_first
**定义**：永远先判定大盘环境，再研究个股。大盘差，再好的个股也限仓，不逆势重仓。

**落地机制（确定性）**
1. 流水线第一步必为 `grade_market()` → `MarketRegime`，先于任何选股/深析。【已建】
2. D 级 `force_flat=True` → 跳过全部选股，仅留持仓风控。【已建，P-09】
3. **总仓位 + 单票天花板按环境分级**，即使个股逻辑再强也不得突破：【强化】

   | 环境 | 总仓位区间 | 单票仓位上限 | 今日开新仓上限 |
   |---|---|---|---|
   | S | 80-100% | 40% | 3 |
   | A | 50-60% | 30% | 2 |
   | B | 20-30% | 20% | 1 |
   | C | 10-20%（仅管存量） | 10% | 0 |
   | D | 0-5%（强制空仓） | 0% | 0 |

   完整语义见 [03-market-regime-grading.md](03-market-regime-grading.md)。区间/单票已进 config 与 `MarketRegime`；
   现状：`orchestrator._suggest_position_pct` 仅系数缩放，**未按 `exposure_max`/单票上限硬封顶**，需在 `vet_trade` 加环境版校验。

**绑定**：`regime/`、`orchestrator.full_analysis` 步骤1/2、纪律 D-07。
**【新增参数】** `regime.grades.*.max_single_position_pct`（覆盖全局 40% 上限）。

---

## 原则二　先排除，后推荐 exclude_then_recommend
**定义**：不先找好股，先用规则剔除高风险标的，剩余范围再优选，从源头降踩雷。

**落地机制（确定性）**
1. 严格固定顺序：**池筛 → 12 排除 → 预打分优选 → 深析**。排除在优选与深析之前（也省 LLM 成本）。【已建】
2. 任一排除命中即出局，不进入后续；理由（规则号）留痕。【已建】
3. **优选只在白名单内进行**：`_prescore` 仅对幸存者打分，不对被排除标的"复活"。【已建】

**绑定**：`guardrails/exclusion_rules`（⑧ 选股筛选）、`orchestrator` 步骤3。
**边界**：白名单为空 → 直接空仓（衔接原则四）。

---

## 原则三　禁止模糊化结论 no_vague_language
**定义**：不得出现"可能/大概/有望"等模糊词；必须给明确判断 + 数据支撑 + 对应依据。

**落地机制（确定性）**
1. 结论必须是明确 `Verdict` 枚举（非自由文本）。【已建】
2. 理由文本含模糊词黑名单 → 抛 `PrincipleViolation`。【已建】
3. **数据支撑校验**（Fork-A=A1）：理由中必须含 ≥ N 个数值型证据（数字/百分比/指标值），否则视为"无依据的空结论"判违规。【强化】
4. **依据非空校验**：`rationale` 去除空白后长度 ≥ 阈值，且至少引用一个来源字段（如 `市盈率`/`营收`/`资金流`）。【强化】

**绑定**：`principles.no_vague_language`（扩展为 `require_explicit_conclusion`），在 ⑦ 研究主管出研报、⑩ 测算员、⑬ 终审 三处调用。
**【新增参数】** `principles.min_numeric_evidence: 1`、`principles.min_rationale_len: 10`。

---

## 原则四　必须做取舍 must_tradeoff
**定义**：不铺满几十只，严格限持仓数；有机会才出手，无合适标的直接空仓等待。

**落地机制（确定性）**
1. `capacity = min(环境开仓额度, 最大持仓数 - 当前持仓)`。【已建】
2. 候选 > capacity → 触发人工裁决（≥2 选项+理由）。【已建，rule #3】
3. **capacity 是上限不是配额**（Fork-B=B1）：只有深析置信度 ≥ `min_conviction_to_buy` 才出手；全部达不到 → **空仓等待**，绝不为填满额度而买次优标的。【强化】

   现状：`_deep_dive_and_finalize` 只要信号=买入就放行，**未设置信度门槛**，需加 `min_conviction` 闸。

**绑定**：`orchestrator` 步骤4/5、`principles.must_tradeoff`。
**【新增参数】** `position.min_conviction_to_buy: 0.6`。

---

## 原则五　主动承认信息缺口 acknowledge_info_gaps
**定义**：数据不全/资讯缺失/行业不透明时，必须标注信息短板，不强行编造逻辑支撑交易。

**落地机制（确定性）**
1. 排除引擎对缺失字段记入 `info_gaps`，并显式挂到决策理由。【已建】
2. **置信度按缺口扣减**：`confidence -= penalty * 缺口数`，下限封底。【强化，当前仅口头"下调"，未真正扣分】
3. **关键字段缺失 → 禁止买入**（Fork-C=C1）：若 `critical_fields` 中任一缺失，BUY 自动降级为 `NO_ACTION`，理由标注"关键信息缺口"。非关键缺失只扣置信度。【强化】

   建议关键字段集：`is_st, is_suspended, price, amount, market_cap`（影响安全/可交易性的硬信息）。

**绑定**：`principles.acknowledge_info_gaps`（扩展返回 penalty 与 is_critical）、`orchestrator` 终审前。
**【新增参数】** `principles.gap_confidence_penalty: 0.05`、`principles.critical_fields: [...]`。

---

## 原则六　刚性止盈止损 strict_tp_sl
**定义**：盈亏标准量化固定，不主观扛单、不随意更改点位，完全靠规则执行。

**落地机制（确定性）**
1. 买入必须带 tp 且 sl，符号正确，否则裸单拒绝。【已建】
2. **tp/sl 由规则/config 计算，不接受 LLM 自由设定**：默认取 `default_tp_sl()`（止盈≥8%、止损-5%），可按环境/波动分档但仍是确定性公式。【强化：明确"来源=规则"】
3. **点位锁定不可篡改**：`HarnessDecision` 一旦生成，tp/sl 视为只读；⑪ 执行员与后续步骤不得修改（"不扛单、不挪点位"）。【强化：加 `locked` 标志 + 修改即抛错】
4. 触发止损由 ⑫ 一级风控的止损三档强制执行，不依赖人工判断。【已建，D-01】

**绑定**：`principles.strict_tp_sl`、`guardrails/trading_discipline`、⑪ 执行员、⑫ 一级风控。
**【新增参数】**（可选）`position.tp_sl_by_regime`（按环境分档的止盈止损表）。

---

## 汇总 · 本轮需落地的强化点与新参数

| 原则 | 强化点 | 新增参数 |
|---|---|---|
| 一 | 单票仓位按环境硬封顶 | `regime.grades.*.max_single_position_pct` |
| 三 | 数值证据 + 依据非空校验 | `min_numeric_evidence`, `min_rationale_len` |
| 四 | 出手置信度门槛（capacity 为上限非配额） | `position.min_conviction_to_buy` |
| 五 | 置信度按缺口扣分 + 关键字段缺失禁买 | `gap_confidence_penalty`, `critical_fields` |
| 六 | tp/sl 来源=规则 + 点位锁定不可改 | （可选）`position.tp_sl_by_regime` |

> 原则二已完全落地，无需强化。以上强化点待"六大原则定稿"后随统一编码一并实现。
