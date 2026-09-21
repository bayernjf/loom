# A2A 封臣接入（Zeus 联邦）— 设计草案

> 状态：**✅ 第一阶段已实施（Q150，2026-09-21；02 C1.94）**。负责人裁决四项全按本草案；`backend/app/core/a2a/` + 12 项单测。第二阶段（真 LLM / 链路执行 / 任务持久化 / 真机联调）须另点工。
> 背景：Zeus 是统一门面产品（多 Agent 协作平台），已定「封臣协议 = A2A 超集」（zeus 仓库 `docs/design-vassal-protocol.md`）；pr-helper 已作为第一个封臣完成 Agent Card + fealty 发布与任务层（4/6 验收项）。loom 为第二个封臣候选，目的：**验证协议可复制性**。

## 提议的封臣契约（x-zeus-fealty）

| 字段 | 提议值 | 理由 |
| --- | --- | --- |
| swornTo | zeus | 星型拓扑，任务只来自 Zeus |
| domain | content-production | 能力域，Zeus 据此路由 |
| dataRealms | enterprise | 私域内容生产平台，服务企业租户 |
| dataPolicy | read-task-scope | 只读任务范围内数据 |
| reportBack | true | 战报回流（summary/evidence/cost） |
| escalationPolicy | auto | 与 loom 既有「AI 只产候选、人工 Gate 裁决」天然同构——不可逆动作升级驾驶员 |
| sla.ackSeconds | 10 | 长链路任务受理时限（比 pr-helper 的 5s 宽） |

## 提议的 skills（第一阶段，均为 plan 模式）

- `generate-content`（段 12 内容生成，人工 Gate 前的候选产出）
- `compliance-check`（段 11 合规清洗，advisory 结果）
- `effect-backfill`（段 13 效果回流，走 Q128 客户通道语义）

**skills 名单与能力边界须负责人裁决**，以上仅为对照 13 段链的初始提案。

## 实施要点（裁决后）

1. FastAPI 新增只读 GET 端点 `/api/a2a/agent-card`（+ well-known 路径），返回 Agent Card + fealty；卡片单一事实源放 `app/core/`（独立模块，不碰业务链）。
2. 任务端点 `POST /api/a2a/tasks`（JSON-RPC：send / sendSubscribe / get / cancel），第一阶段只做 plan 模式（返回行动方案 artifact + 战报），**不触链、不花 token、不改任何 Gate 语义**。
3. 认证：复用 Q88 Agent Key 语义（Bearer，但 Zeus 专用 Key，与 effect-callback 的下游 Key 分离）——是否复用同一张表待裁决。
4. 审计：A2A 调用落审计事件（复用既有审计设施口径）。

## 明确不做（与既有裁决一致）

- 不做发布自动化（Q62：发布由运营回填，Zeus 任务也不可越权发布）。
- 不绕过任何人工 Gate（封臣 escalationPolicy=auto 与 Gate 并存，Gate 优先）。
- plan 模式不调用真 LLM、不花钱。

## 待负责人裁决清单

1. 是否接入（及排期：建议 private beta 主数据回填之后、不阻塞 #6）。
2. skills 名单与能力边界。
3. Agent Key 是否复用 Q88 体系。
4. 卡片端点是否需要租户维度（当前提议：单卡片、租户在任务参数里）。
