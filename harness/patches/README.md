# 上游补丁（应用到 TradingAgents-CN 克隆）

这些补丁修改开源 TradingAgents-CN 的少量代码以配合 harness。
TradingAgents-CN 不纳入本仓库，故补丁单独存放、可复现应用。

## risk_manager_conservatism.patch —— 终审风控保守度旋钮
把终审风控主管（`agents/managers/risk_manager.py`）的**单向厌损**改为**可调的对称风险偏好**，
由环境变量 `RISK_CONSERVATISM` 控制：
- `high`：保守（原始偏空，保护本金优先）
- `balanced`：均衡（**默认**，对称权衡上行/下行，不在不确定时默认看空）
- `low`：进取（风险可控前提下重视上行机会，敢于给买入）

并把"避免做错而亏损"改为对称："既不要错买亏损，也不要错空踏空"。

### 应用
```bash
cd TradingAgents-CN
git apply ../harness/patches/risk_manager_conservatism.patch
```
然后在 `TradingAgents-CN/.env` 设 `RISK_CONSERVATISM=balanced`（或 high/low）。

### 实测（002709 天赐材料，同数据同日）
| 口径 | 终审 | harness 评级 |
|---|---|---|
| high | 卖出 | 明确不买 |
| balanced | 卖出（对称论证） | 明确不买 |
| low | 买入 | 可适仓买入 |

证明：原"逢分析必看空"主要源自上游 prompt 的结构性保守，而非独立客观判断。
