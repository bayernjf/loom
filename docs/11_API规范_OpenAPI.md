# 11. API 规范（OpenAPI 契约说明）

> **状态**：🟢 已补内容（接口规格说明，非 OpenAPI YAML 文件）
> **来源**：05_契约层_API与状态机.md（effect-callback 完整契约 Q60、白名单消费 Q71）｜02_决策记录 Q60/Q62/Q71｜09 全景 §4/§9.5
> **用途**：已定稿接口的机器可解析规格说明；AI 据此生成 OpenAPI 规范文件、SDK 与接口测试。
> **⚠ 说明**：原文只定义了 effect-callback（完整）与白名单消费（规则完整）；**错误码、限流、分页等通用项原文未定义，标【建议】**。未定稿接口保持【待补：原文未给出】。

---

## 1. 接口总览

| 接口 | 方法/路径 | 来源决策 | 契约状态 |
|---|---|---|---|
| 效果回调 | POST /api/effect-callback | Q60 | 🟢 契约定稿（见 §2.1）；**入站第一片已落地（Q126，2026-09-19）**：Bearer 验签 + effect_records 时序 + matched/orphan 分流 + 运营只读队列；孤儿人工认领（Q60a）/反哺校准随下一片 |
| 白名单消费 | POST /api/product-spaces/{product_space_id}/pwc/consume（业务方参考路径 /api/whitelist/consume 不采用） | Q71 | 🟢 已落地（M5，见 §2.2） |
| 白名单查询 | GET /api/product-spaces/{product_space_id}/pwcs（租户内池查询，M5）；D9.5 系统后台页面级清单另计 | D9.5 | 🟡 池内组合查询已落地（M5）；中台页面级清单【待补】 |
| 使用记录上报 | V1 无独立上报端点：consume 取用即写 usage_record 并回带 usage_record_id（M5） | D9.5 / Q71 | 🟡 V1 随消费内联落地；独立上报接口【待补】 |
| Key 管理 | 入站 POST/GET /api/admin/agent-keys、POST /api/admin/agent-keys/{id}/revoke（Q88）；出站 POST /api/admin/ai-models/{id}/keys（录入/轮换）、GET /api/admin/ai-models/{id}/keys（清单）、POST /api/admin/ai-model-keys/{key_id}/revoke（Q82） | Q60b/Q67/Q82/Q88 | 🟢 治理端点已落地（见 §2.4）；受 Key 保护的 effect-callback 已随 Q126 接入（§2.1）；Q127 孤儿人工认领、Q128 客户回填通道已落地（反哺校准随下一片） |
| DB 浏览 / AI 调试台 / 调用日志 / 配额 | 后台内部；其中 **2 个驾驶舱只读聚合已落地**：GET /api/admin/dashboards/token-cost、GET /api/admin/dashboards/review-workload（Q92） | D9.5 / Q92 | 🟡 驾驶舱两读口已落地（platform_admin，见 05 §1.4）；DB 浏览 / AI 调试台 / 配额【待补】 |
| 中台对接 API + Webhook 回流 | 中台 | D4 | 🔶 V2 项【待补】 |
| 中台 SDK 嵌入 | 中台 | D4 | 🔶 V3 项【待补】 |
| CSV / JSON 导出 | GET /api/exports/fcw.csv（Q100） | D4 | 🟢 CSV 已落地（见 §2.3）；JSON 形态/异步导出挂后续/V2【待补】 |

---

## 2. 已定稿接口规格

### 2.1 效果回流（Q60，契约完整；Q126 入站推送 / Q127 孤儿认领 / Q128 客户回填均已落地）

**用途**：全链唯一反向边的数据入口——外部 Agent 系统推送效果数据（本系统不做抓取、不做定时拉取调度，Q62）。

**鉴权**：API Key（一 Agent 一 Key，可吊销；复用 API Key 管理模块，Q60b/Q67）

**请求体**：
| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| source | string | ✅ | Agent 标识；客户回填时 = "customer-backfill" |
| records[] | array | ✅ | 记录列表 |
| records[].content_id | string | ✅ | 本系统内容 ID（发布后由运营回填 platform_post_id 建立映射） |
| records[].platform_post_id | string | ✅ | 平台帖子链接/ID |
| records[].captured_at | datetime | ✅ | 采集时间 |
| records[].metrics | object | ⬜ | 全部可选字段：plays / likes / comments / shares / read_rate / inquiries / conversions |

**响应**：200 成功；4xx/5xx 见 §3 错误码【建议】

**数据纪律**：缺席字段=未采集记"—"，**绝不当 0 / 不许估算**（硬性）

**幂等/时序**：
- 同 content_id 多次推送按 captured_at **追加**为时间序列
- 同 content_id + captured_at **幂等覆盖**

**孤儿数据处理**：对不上 content_id 的推送进"孤儿数据"队列人工认领（Q60a；认领端点 Q127 已落地，见下「实现补登 Q127」）

**发布链路（业务澄清 Q60c）**：客户确认（仅审批信号）→ **运营用托管账号发布** → **运营回填平台链接/ID** → Agent 抓取 → 本 API 推送。前端客户不填写平台链接。

**实现补登（Q126 入站第一片，2026-09-19，02 C1.70）**：`app/core/effects/` + 表 `effect_records`（迁移 0034）。
- 鉴权＝Q88 `require_agent_key`（Authorization: Bearer；缺失/错误/吊销统一 401），首个受 Agent Key 保护的业务端点，命中盖 last_used_at。
- 成功 200 回执 `{received, matched, orphan, upserted}`；逐字段校验失败回 422（detail 含 `{index, field, message}`）。
- metrics 类型（实现补规格，原文未给类型）：plays/likes/comments/shares/inquiries/conversions 为非负整数、read_rate 为 0..1 数值；bool 拒绝、未知键拒绝、缺席键与显式 null 不落（绝不当 0）。
- captured_at 必须带时区（naive 422），服务端归一 UTC；幂等键 (content_id, captured_at) 重推覆盖、新采集点追加。
- 自动匹配仅按 content_id 命中**非 discarded** 成品（命中回填 matched_content_id/tenant_id，否则 orphan）；platform_post_id 不参与自动绑定。
- 整批 all-or-nothing；批内重复幂等键 422；每批审计 `effect.batch_received`（tenant `_platform`）。
- 运营只读：`GET /api/admin/effects/orphans`、`GET /api/admin/effects?content_id=`（operations | platform_admin query actor 闸，limit/offset 同既有队列）。
- **Q127 孤儿人工认领（2026-09-19，02 C1.71，迁移 0035）**：`POST /api/admin/effects/claims`，body `{record_id, content_id, actor}`（operations 写口硬闸，actor 在体；客户/platform_admin 403）。入口记录须为当前 orphan（未知 404、非 orphan 409），目标成品须存在且非 discarded（未知 404、discarded 409）。新表 `effect_claims`（external_content_id PK→content_id FK、claimed_by/claimed_at）持久映射，`effect_records` 加 claimed_by/claimed_at 两溯源列（不新增第三状态，认领后转 matched）；认领＝upsert 映射＋回填该 external_content_id 下全部 orphan 与历史 claimed 行（响应回带 updated_rows，审计 `effect.claimed` tenant `_platform`）。此后同 ID 的推送（覆盖/新采集点）经认领兜底一律 matched，不回落孤儿；映射目标 discarded 则回落 orphan、映射保留。
- **Q128 客户回填通道（2026-09-19，02 C1.72，零迁移）**：`POST /api/effects/backfill`，**无 Agent Key**，body `{tenant_id, records[], actor}`（客户 actor roles 恒空，同 Q122 客户写口）；source 服务端固定 `customer-backfill`；每条 content_id 必须命中本租户非 discarded 成品，否则该条 422（index/field/message）整批 all-or-nothing——**客户通道绝不产生孤儿**；幂等/时序/metrics 纪律与 Agent 通道一致，received_by=客户 actor.id，审计 `effect.customer_backfilled`（tenant=客户租户），回执 orphan 恒 0。
- **未含（随下一片/V2）**：效果反哺/Q54·Q57 校准算法（口径【待补】）、认领取消/解绑与认领/回填前端 UI、content_id↔platform_post_id 映射自助化、Agent 抓取与发布自动化（Q62 不抓取）。

### 2.2 白名单消费接口（Q71，规则完整）

**用途**：系统后台 API 端消费内容配方（PWC/白名单）

**取用排序**：按评分从高到低取（Q22 PWC 分 / Q54 FCW 分，临时公式够排序）

**去重**：同平台 + 同账号 + 同发布位不重复（Q24）；命中即写 usage_record 并流转状态（待用→已用）

**保底补给**：
- 待用池跌破保底线自动触发一轮相撞补货回目标量
- 触发线 = critical（50）；目标 = target（100）；补货冷却默认 5min（防抖）

**池健康度三档**（line 1451）：target 100 / min 70 / critical 50

**⚠ 参考来源**：业务方 E1 `/api/whitelist/consume`（按权重取 + usage_record + 5 池保底）——采纳骨架但**不采用"上限 200"**，一律以本系统池健康度三档为准。

**实现端点（M5 2026-09-14 落地，2026-09-17 据实现补登）**：`POST /api/product-spaces/{product_space_id}/pwc/consume`（业务方参考路径 `/api/whitelist/consume` 不采用）

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| platform | string | ✅ | 目标平台；同 platform+account+slot 去重（Q24/Q71） |
| account | string | ✅ | 发布账号 |
| slot | string | ✅ | 发布位 |
| goals | string[] | ⬜ | 目的码交集过滤（不传不过滤） |
| actor | object | ✅ | 操作人（id/roles） |

响应 200：`pwc`（组合完整视图，含 score/gate_status/status/combo_atom_ids 等）、`usage_record_id`（取用即写流水）、`platform_state`（platform/state/cooldown_until，per-platform 冷却态）、`pool_ready_count`、`pool_health`（target100/low70/critical50）、`restock_hint`、`restock_run_id`。

错误码：404 product space not found；409 待用池空（PoolEmpty）。

> 自动补货：Q87 restock_auto worker 为进程内轮询（默认关闭 opt-in，platform_admin 可手工 POST /api/admin/restock/run）；补货只产 pending_review 候选，人工 Gate 不改。Q90 瞬态失败指数退避（restock_retry_state 游标）。

### 2.3 GET /api/exports/fcw.csv（中台 CSV 导出 · Q100，已落地）

**用途**：中台手动拉取白名单 final_id 单列（D4 CSV 契约），同步流式生成。

**请求**：query `tenant_id`（必填）、`product_space_id`（可选，缺省导该租户全部）。

**响应 200**：`text/csv; charset=utf-8`，头 `Content-Disposition: attachment; filename="fcw-{tenant_id}.csv"`；正文为 final_id 单列（首行表头）。

**口径**：只导 published（draft 通道 V1 未开；Q32 revoked 过滤随其落地自然生效）；读路径不触发 Q95 租户准入门——未知租户返回仅表头空文件 200，不 404。

**未含**：JSON 形态、异步导出/导出任务记录均挂后续/V2【待补】。

### 2.4 API Key 治理端点（Q88 入站 / Q82 出站，已落地）

**入站一 Agent 一 Key**（`app/core/api_keys/`，platform_admin 红线）：

| 方法/路径 | 说明 |
|---|---|
| POST /api/admin/agent-keys | 签发（201）：请求 {name, actor}，空名 422、越权 403；响应含 `secret` 明文（`loom_`+token_urlsafe(32)，**仅签发返回一次**） |
| GET /api/admin/agent-keys?include_revoked=false | 列表：仅 key_id/name/key_prefix（前 12 字符）/status/created_at/last_used_at，不回明文与哈希 |
| POST /api/admin/agent-keys/{key_id}/revoke | 吊销：append-only 状态位（不物理删除），未知 key 404、越权 403 |

DB 只存 SHA-256 hex 哈希 + 展示前缀（单向，库泄露不暴露可用 Key）；审计 `agent_api_key.issue/revoke`（tenant=`_platform`）；Key 为平台级凭证、不绑租户（单租户绑定口径【原文未给出，待补】，未来由 content_id→FCW.tenant_id 解析）。验签依赖（Bearer 缺失/未知/已吊销统一 401）已备，**已随 Q126 接入受保护业务端点 POST /api/effect-callback（§2.1）**；Q60a 孤儿人工认领已随 Q127 落地、customer-backfill 客户通道已随 Q128 落地（均见 §2.1）；效果反哺校准随段13 下一片/V2。

**出站模型商 Key**（Q82 模型网关，`app/core/model_registry/`）：Fernet 可逆加密入库 + env 主密钥（与入站单向哈希刻意区分——出站需代持调用）；端点 **POST /api/admin/ai-models/{model_id}/keys**（录入/轮换，body=secret/actor，原子把旧 active 行置 revoked 并插新密文行）、**GET /api/admin/ai-models/{model_id}/keys**（清单，仅 key_id/fingerprint/status/时间元数据）、POST /api/admin/ai-model-keys/{key_id}/revoke（吊销，幂等），platform_admin 治理。

---

## 3. 通用规范（原文未定义，均为【建议】）

| 项 | 建议 | 依据 |
|---|---|---|
| 鉴权 | API Key 放 Authorization header；一 Agent 一 Key 可吊销 | Q60b/Q67 |
| 租户隔离 | 所有接口按 tenant_id 隔离；跨租户不可见 | Q33 |
| 错误码 | 统一 `{code, message, request_id}` 结构：400 参数错 / 401 未授权 / 404 不存在 / 409 冲突（幂等覆盖冲突）/ 429 限流 / 500 服务错 / 503 上游模型不可用 | 【建议】 |
| 限流 | 外部推送接口按 Agent 配额（Rate Limit 见 09 D3.11）；补货防抖 5min | Q71 |
| 审计 | 所有 API 调用写 writeAudit（append-only） | D3.11 |
| 版本 | URL 前缀 /api/v1；重大变更走新版本 | 【建议】 |
| 上游降级 | 模型不可用时返回 503 + 客户端重试语义（幂等保证） | 【建议】 |

---

## 4. 未定稿接口的补规格模板（开发第 0 步范围）

> 每个待补接口（白名单查询/使用上报/中台 API 等）按此模板补齐，补完回填 §1 状态表：

```markdown
### <接口名>
- 用途 / 调用方 / 触发时机【内容待补】
- 请求 Schema（字段/类型/必填）【内容待补】
- 响应 Schema 与状态码【内容待补】
- 鉴权与限流【内容待补】
- 幂等与错误处理【内容待补】
- 相关决策（Q 编号）【内容待补】
```

---

## 5. 与既有文档的核对项

- [x] effect-callback 契约与 05/Q60 逐字段一致（source/records/content_id/platform_post_id/captured_at/metrics）
- [x] 白名单消费规则与 Q71/Q24 一致（排序取用/去重/保底/三档健康度）
- [x] 数据更新节奏与 Q62 一致（不做定时拉取，外部推送制）
- [x] 白名单消费实现端点与 M5/Q71 代码一致（路径/请求体/响应/错误码，2026-09-17 补登 §2.2）
- [x] CSV 导出与 Q100 实现一致（§2.3）
- [x] 入站/出站 Key 治理端点与 Q88/Q82 实现一致（§2.4）
- [x] effect-callback 入站第一片与 Q60/Q88/Q126 实现一致（鉴权/幂等键/metrics 缺“—”不当 0/matched·orphan 分流/只读队列，2026-09-19 补登 §2.1）
- [x] effect-callback 续片：Q126 入站推送、Q127 孤儿人工认领、Q128 customer-backfill 客户通道均已落地（见 §2.1，02 C1.70–C1.72）
- [ ] 待补接口回填：中台对接 API+Webhook（V2）、中台 SDK（V3）、效果反哺/Q54·Q57 校准（口径【待补】）、认领/回填前端 UI、DB 浏览/AI 调试台/调用日志/配额、白名单页面级查询与独立使用上报、JSON/异步导出——均【待补】，随对应版本补齐后回填 §1
- [x] 段内业务端点不在本表登记范围：段12 内容成品五端点（POST /api/content/generate、/{id}/approve|reject|revise|regenerate）契约见 05 §1.4 Q116 补登与 13 §1.13（V2 P4 首片，2026-09-17 落地）
