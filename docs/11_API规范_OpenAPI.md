# 11. API 规范（OpenAPI 契约说明）

> **状态**：🟢 已补内容（接口规格说明，非 OpenAPI YAML 文件）
> **来源**：05_契约层_API与状态机.md（effect-callback 完整契约 Q60、白名单消费 Q71）｜02_决策记录 Q60/Q62/Q71｜09 全景 §4/§9.5
> **用途**：已定稿接口的机器可解析规格说明；AI 据此生成 OpenAPI 规范文件、SDK 与接口测试。
> **⚠ 说明**：原文只定义了 effect-callback（完整）与白名单消费（规则完整）；**错误码、限流、分页等通用项原文未定义，标【建议】**。未定稿接口保持【待补：原文未给出】。

---

## 1. 接口总览

| 接口 | 方法/路径 | 来源决策 | 契约状态 |
|---|---|---|---|
| 效果回调 | POST /api/effect-callback | Q60 | 🟢 契约定稿（见 §2.1）；**入站与操作面已落地（Q126–Q131，2026-09-19/20）**：Bearer 验签 + effect_records 时序 + matched/orphan 分流 + 运营只读队列 + 单条/批量认领/解绑（Q127/Q129）+ 客户专用回填通道（Q128）+ 管理端认领台与客户回填岛（Q130/Q131）+ 服务端 CSV 批量上传逐行回执（Q156）；反哺校准算法口径【待补】随 V2 |
| 白名单消费 | POST /api/product-spaces/{product_space_id}/pwc/consume（业务方参考路径 /api/whitelist/consume 不采用） | Q71 | 🟢 已落地（M5，见 §2.2） |
| 白名单查询 | GET /api/product-spaces/{product_space_id}/pwcs（租户内池查询，M5）；D9.5 系统后台页面级清单另计 | D9.5 | 🟡 池内组合查询已落地（M5）；中台页面级清单【待补】 |
| 使用记录上报 | V1 无独立上报端点：consume 取用即写 usage_record 并回带 usage_record_id（M5） | D9.5 / Q71 | 🟡 V1 随消费内联落地；独立上报接口【待补】 |
| Key 管理 | 入站 POST/GET /api/admin/agent-keys、POST /api/admin/agent-keys/{id}/revoke（Q88）；出站 POST /api/admin/ai-models/{id}/keys（录入/轮换）、GET /api/admin/ai-models/{id}/keys（清单）、POST /api/admin/ai-model-keys/{key_id}/revoke（Q82） | Q60b/Q67/Q82/Q88 | 🟢 治理端点已落地（见 §2.4）；受 Key 保护的 effect-callback 已随 Q126 接入（§2.1）；Q127 孤儿人工认领、Q128 客户回填通道已落地（反哺校准随下一片） |
| DB 浏览 / AI 调试台 / 调用日志 / 配额 | 后台内部；其中 **2 个驾驶舱只读聚合已落地**：GET /api/admin/dashboards/token-cost、GET /api/admin/dashboards/review-workload（Q92） | D9.5 / Q92 | 🟡 驾驶舱两读口已落地（platform_admin，见 05 §1.4）；DB 浏览 / AI 调试台 / 配额【待补】 |
| 中台对接 API + Webhook 回流 | 中台 | D4 | 🔶 V2 项【待补】 |
| 中台 SDK 嵌入 | 中台 | D4 | 🔶 V3 项【待补】 |
| CSV / JSON 导出 + 异步导出任务 | GET /api/exports/fcw.csv（Q100）、fcw.json（Q132）、POST /api/exports/jobs + 状态/下载口（Q132） | D4 | 🟢 CSV/JSON 同步导出 + 导出任务记录已落地（见 §2.3/§2.4）；queued/running 真后台 worker（Streams 消费组）+ 任务列表口已随 Q137 落地（env 默认关，门控关走同步）；limit/offset 分页与行数硬上限已随 Q142 落地（env `LOOM_EXPORT_MAX_ROWS` 默认 10 万，超限 422） |
| 台内白名单 6 层原料包 JSON | GET /api/fcw/{final_id}/material.json（Q155） | 09:87 / 01 line14 | 🟢 后端全量 JSON 已落地（见 §2.5，台内卡片口径、非中台 final_id-only 面）；台内卡片前端随 D3.5 点工 |

---

## 2. 已定稿接口规格

### 2.1 效果回流（Q60，契约完整；Q126 入站推送 / Q127 孤儿认领 / Q128 客户回填 / Q129 批量认领·解绑 / Q130 管理端认领台 / Q131 客户回填 UI 均已落地）

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

**孤儿数据处理**：对不上 content_id 的推送进"孤儿数据"队列人工认领（Q60a；单条认领 Q127、批量认领/解绑 Q129、管理端认领台 Q130 均已落地，见下实现补登）

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
- **Q129 批量认领与取消认领/解绑（2026-09-20，02 C1.73，零迁移）**：`POST /api/admin/effects/claims/batch`，body `{items:[{record_id,content_id}](≥1), actor}`，逐条复用单条认领校验，批内 record_id 重复/空 items 422（detail `{index,field,message}`），任一记录 404/409 整批 all-or-nothing 回滚，回 `{claimed, updated_rows}`，逐条 `effect.claimed` 审计随事务。`POST /api/admin/effects/claims/unclaim`，body `{external_content_id, actor}`（operations 硬闸，映射不存在 404 `ClaimMappingNotFound`）：删映射并把该 external_content_id 下 **matched_content_id 等于旧映射目标** 的全部行回滚 orphan（清四列；按旧目标 content_id 筛而非 claimed_by，兜底新 matched 行也回滚；external_id 自匹配的真自动行不动），回 `{external_content_id, reverted_rows}`，审计 `effect.claim_revoked`。
- **Q130 管理端效果回流运营台（2026-09-20，02 C1.74，零迁移）**：`/admin/effects`（管理端 sidebar 第 8 项）。孤儿队列区：RSC `GET /api/admin/effects/orphans?limit=100` 首屏，岛支持单条认领与勾选批量认领（整批成功或整批拒绝）；成品时序区：`GET /api/admin/effects?content_id=` 查询，人工认领行可「取消认领」（confirm 后调 unclaim 并重查）。读 operations|platform_admin、写 operations（缺身份 unconfigured/缺 operations missing_role 本地拒发）；指标缺席显 "—" 绝不显 0。check-admin 扩守卫（sidebar 恰 8 项、effects 五文件、admin.effects.* 键、后端六路由齐备）。
- **Q131 客户效果回填 UI（2026-09-20，02 C1.75，零迁移）**：客户内容详情页对非 discarded 成品挂回填岛（客户 nav 不增项，仍恰 8 项）；V1 单条手工表单（platform_post_id 必填、captured_at datetime-local 客户端转带 Z 的 UTC ISO、metrics 七键留空即缺席、六计数非负整数/read_rate 0..1 前端先挡），提交 Q128 `POST /api/effects/backfill`，422 `{index,field,message}` 回显，成功 router.refresh；批量表格/CSV 随 V2。check-content 扩守卫。

- **Q156 服务端 CSV 批量上传（2026-09-21，02 C1.100，零迁移/零新依赖，甲案接缝待追认）**：`POST /api/effects/backfill/upload`，**无 Agent Key**（客户通道，同 Q128），JSON body `{tenant_id, content_id, csv, filename?, actor}`（不引 multipart，CSV 为文本字段；整份挂单一 content_id，九列同 Q136：platform_post_id,captured_at,plays,likes,comments,shares,inquiries,conversions,read_rate）。服务端标准库 csv 解析：去 BOM、表头按名定位（重复/未知/缺列聚合报错）、跳纯空行、回执物理行号（首数据行 line=2）、captured_at **强制带时区**（naive/纯日期逐行 422，守 Q128 tz-aware 铁律）、计数 `^\d+$`、read_rate 0..1、空指标缺席不落 0；**逐行收集全部坏行一次回 422**（detail `{message:"CSV validation failed", errors:[{index,line,field,message}]}`）；行数硬上限 env `LOOM_BACKFILL_UPLOAD_MAX_ROWS` 默认 10000（0 数据行/超限 422）。通过后复用 Q128 客户通道（只命中本租户非 discarded 成品否则整批 422、绝不孤儿、all-or-nothing、审计 effect.customer_backfilled），200 回执在 `{received,matched,orphan,upserted}` 上追加 `filename` 与 `rows[]{index,line,platform_post_id,captured_at}`。仍挂 V2：Excel（openpyxl）解析、异步导入任务、Q131 前端岛切换到本端点。
- **未含（随下一片/V2）**：效果反哺/Q54·Q57 校准算法（口径【待补】）、回填批量表格/CSV 导入（V2）、content_id↔platform_post_id 映射自助化、Agent 抓取与发布自动化（Q62 不抓取）。~~认领取消/解绑与认领/回填前端 UI~~（已随 Q129–Q131 落地）。

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

**未含（已销账）**：~~JSON 形态、异步导出/导出任务记录均挂后续/V2【待补】~~ ✅ 已随 Q132（2026-09-20，02 C1.76）落地，见 §2.4；仅真后台 worker 仍随 V2。

### 2.4 中台 JSON 导出与异步导出任务（Q132，已落地）

**JSON 同步口 `GET /api/exports/fcw.json`**：query 同 §2.3（tenant_id 必填、product_space_id 可选），口径完全一致（只导 published、created_at DESC、未知租户 200 空 envelope、不触发 Q95 准入门）；响应 `application/json` + `Content-Disposition: attachment; filename="fcw-<tenant>.json"`，body 与 CSV 同构只含 final_id，不拼 6 层原料包：

```json
{ "tenant_id": "t1", "product_space_id": null, "count": 2, "total": 123456, "limit": 100000, "offset": 0, "has_more": true, "final_ids": ["...", "..."] }
```

**分页与行数硬上限（Q142，2026-09-20，02 C1.86，已落地）**：fcw.csv 与 fcw.json 两口（含 jobs 下载渲染）统一支持 query `limit`（1..硬上限）/`offset`（≥0）。硬上限取 env `LOOM_EXPORT_MAX_ROWS`（settings `export_max_rows`，默认 100000；运维防护旋钮、非 Q9 业务阈值、零迁移），`limit` 超限或 `offset` 为负返 422，不传 `limit` 时回落到硬上限（全量导出受截断保护）。分页元数据：
- JSON：envelope 在 Q132 字段上**追加** `total`（匹配过滤条件的总数，不受分页影响）/`limit`/`offset`/`has_more`，`count` 仍为本页行数（向后兼容只加字段）；
- CSV：正文守 Q100 严格单列不变，分页信息走响应头 `X-Export-Total` / `X-Export-Limit` / `X-Export-Offset` / `X-Export-Has-More` / `X-Export-Truncated`；`truncated=true` 表示未显式分页（offset=0）却仍有更多行、即被硬上限截断。
同步 job、Q137 异步 worker、下载口全部经同一 `fetch_export_page` 受上限约束；export_jobs 不新增分页列，`export.job_created/job_completed` 审计 detail 追加 total/limit/truncated。

**异步导出任务（V1 同步执行落表）**：
- `POST /api/exports/jobs`：body `{tenant_id（必填）, product_space_id?（可选）, format: "csv"|"json"=csv, actor}`（中台面同 Q100 无 RBAC 闸，actor 仅留痕）；门控关（默认，`LOOM_EXPORT_WORKER_ENABLED=false`）在请求内同步导出并置 `completed`（同 Q55 FcwAssemblyTask 同步先例）、201 返回任务视图；门控开（Q137）置 queued/running 经 Redis Streams 消费组 ExportWorker 异步处理（只读幂等作业可水平并行、崩溃 PEL 接管、超限进死信）。
- `GET /api/exports/jobs/{job_id}`：任务状态视图（未知 404；queued/running 供中台轮询，Q137 起支持）。
- `GET /api/exports/jobs?tenant_id=&limit=`：任务列表口（Q137，envelope `{tenant_id,count,jobs[]}`，limit 默认 50、1..200）。
- `GET /api/exports/jobs/{job_id}/download`：按任务参数**重新查询渲染**下载（不存文件 payload，幂等反映当前 published 集合；未知 404、status=failed 409 detail=error、queued/running 409 not ready，Q137），媒体类型与文件名按 job.format/file_name，渲染同样受 Q142 分页/硬上限约束。
- 任务视图 ExportJobView：`{job_id, tenant_id, product_space_id, format, status, row_count, file_name, requested_by, error, created_at, completed_at, download_url}`；row_count 为创建时留痕，不随后续数据变化。
- 审计 `export.job_created`（tenant=客户租户、actor_id=requested_by、actor_roles=[]、entity_type=export_job、entity_id=job_id、detail {format,row_count,product_space_id}）；同步 CSV/JSON 两口沿用 Q100 不写审计。
- 新表 export_jobs（迁移 0036，业务物理表 57→58，pg16 up/downgrade-1/up 实测）；错误：tenant_id 空 422、format 非 csv|json 422、缺 actor 422、未知 job 404、failed 任务下载 409。
- **未含（V2）**：失败重试策略细化。（queued/running 后台 worker 与任务列表口已随 Q137、分页与行数硬上限已随 Q142、多 ExportWorker 副本并发度/批量配置已随 Q152〔env `LOOM_EXPORT_WORKER_CONCURRENCY` 默认 1/`LOOM_EXPORT_STREAM_COUNT` 默认 20〕落地；中台导出契约仍为 final_id-only，**6 层原料包全量 JSON 不属本面、已随 Q155 落台内卡片口径见 §2.5**。）

### 2.5 台内白名单 6 层原料包 JSON（Q155，已落地）

**用途**：docs/09:87「每条白名单 = 完整 6 层提示词原料包（产品+平台+策略+结构+表达+合规）」、01 line 14「final_id = 6 层快照相加」的台内 FCW 卡片详情/复制口径；与中台 §2.3/§2.4 的 final_id-only 导出**分属两个面**（Q100/Q132/Q142 定论），故端点落 final FCW 域而非 `/api/exports`。

- `GET /api/fcw/{final_id}/material.json`：只读、无 RBAC 闸、不触发 Guard、不写审计、未知 final_id 404（读纪律同 `GET /api/fcw/{final_id}`）；响应 `application/json` + `Content-Disposition: attachment; filename="fcw-material-{final_id}.json"`。
- 包体 schema `loom.fcw.material-pack.v1`：`{schema, final_id, issued:{tenant_id,product_space_id,platform,slot_id,goal,country,score,score_incomplete,score_detail,publish_status,issued_by,created_at,published_at}, layers:{product,platform,strategy,structure,expression,compliance}, guards, warnings:[]}`。product=PwsSnapshot 冻结快照（池原子/PWC combo）、platform=PcpWeightTable 权重 + PublishSlot、strategy/structure/expression=三包 Package（csp/cstp/cep 定键 payload）、compliance=CcrReport + 关联 LawReview 列表。
- 引用行物理缺失不 500，该层引用回 `{"_ref":<id>,"available":false}` 并在 `warnings` 收一条。
- **边界**：本片只销后端 JSON 能力，台内卡片前端（D3.5 白名单组装引擎菜单）整片未建、随菜单点工，复制 ID/多选/列表卡片不扩张；零迁移。

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
- [x] effect-callback 续片：Q126 入站推送、Q127 孤儿人工认领、Q128 customer-backfill 客户通道、Q129 批量认领/解绑、Q130 管理端认领台、Q131 客户回填 UI 均已落地（见 §2.1，02 C1.70–C1.75）
- [ ] 待补接口回填：中台对接 API+Webhook（V2）、中台 SDK（V3）、效果反哺/Q54·Q57 校准（口径【待补】）、~~认领/回填前端 UI~~（已随 Q130/Q131 落地）、回填批量表格/CSV（V2）、DB 浏览/AI 调试台/调用日志/配额、白名单页面级查询与独立使用上报、~~JSON/异步导出~~（✅ 已随 Q132 落地，见 §2.4）——其余均【待补】，随对应版本补齐后回填 §1
- [x] 段内业务端点不在本表登记范围：段12 内容成品五端点（POST /api/content/generate、/{id}/approve|reject|revise|regenerate）契约见 05 §1.4 Q116 补登与 13 §1.13（V2 P4 首片，2026-09-17 落地）
