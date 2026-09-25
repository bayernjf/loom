# 21 运营 SOP — 全链操作手册（private beta · 平台代运营）

> **定位**：受控 private beta 期间由**平台运营团队代客户操作**的逐段操作手册。每步注明"谁（角色）→ 点哪个页面/调哪个端点 → 裁决什么"。
> **依据**：角色名取自后端 `app/core/rbac/__init__.py` 常量；步骤与顺序经 `backend/tests/e2e/test_fullchain_golden_path.py` 全链实测（2026-09-22）；主数据字段以 [19](./19_private_beta主数据录入模板.md) 为准。本文不新增业务事实。
> **铁律**：AI 只产候选；每个 Gate 必须人工裁决；`final_id` 只能由 E1.1 publishFCW（`POST /api/fcw/assemble`）写入；LLM 触发全部为运营显式操作，链上不会自动串发（Q83/Q84）。

---

## 0. 角色与工作台

| 角色（actor.roles） | 职责 | 主要入口 |
|---|---|---|
| `customer` | 段1 提交资料、段12 审阅成品/改稿、段13 回填效果 | 客户台：products / content / compliance / workbench / analytics / settings（social-accounts、templates 为 V2 占位） |
| `operations` | 段1 推进、段2 触发识别、段3–5 编排与 Gate 送裁、段11 组装、段12 触发生成与发布回填 | 管理台：/admin/intakes、review-workload、review-queue、content、effects、exports、fcw 等 12 页（见 §0.1 登录） |
| `product_reviewer` | 字段池 / 原子 / PWC 三道 Gate 的人工裁决 | /admin/review-workload、/admin/review-queue |
| `whitelist_owner` | PWS 冻结 | API（V1 无独立页面） |
| `internal_compliance` | 段10 合规清洗 CCR | /admin/content（及 API） |
| `platform_admin` | 租户、Agent Key、运营人员令牌、AI 模型与场景路由、字典管理、导出任务 | /admin/tenants、/admin/agent-keys、/admin/staff-keys、/admin/token-cost、/admin/exports |
| `dictionary_admin` | 内容语言清单等字典维护 | API（语言清单管理） |

> **身份（Q178，2026-09-24 起）**：内部运营管理端已有可选的个人访问令牌（staff PAT）认证层，门控 `LOOM_STAFF_AUTH_ENABLED` **默认关**——门控关时 Actor 仍为请求体内 `{"id","roles"}` 自报（private beta 由平台内控保证）；门控开后管理口必须持 staff 令牌、自报 actor 被令牌身份覆盖（防提权）。开通与登录操作见 **§0.1**。客户侧真实认证仍为 V2（Q196 口径 C 甲＝private beta 维持平台代运营、不做客户登录）。**Q196 起审计身份由服务端定**：写审计的唯一口按「已验真凭证 > 请求自报」取值，带 staff PAT 或 Agent Key 打的口，审计记的是凭证持有人，body/query 里自报的 id/roles 只作备查证据（`detail.declared_actor`），来源看 `detail._actor_via`∈{`staff_token`,`agent_key`,`declared`}；无凭证的客户口仍记自报并标 `declared`——**读到 `declared` 就等于「身份未经证实」**。中台导出任务状态口与下载口（见 §1 段 11 末「异步导出经 `/api/exports/jobs`」与 §3 的 404/422 行）现须带 `tenant_id` 且只能读本租户任务。

### 0.1 运营登录与身份（Q178 staff PAT，门控默认关）

人员令牌（前缀 `loom_staff_`，表 staff_api_keys）与机器 Agent Key（前缀 `loom_`，/admin/agent-keys，段13 用）**分表分前缀、不可互换**；人员令牌无租户、审计恒记 `_platform`，可签发角色限五种内部角色（operations / platform_admin / product_reviewer / dictionary_admin / internal_compliance，不含客户角色 whitelist_owner）。

**首次开通（鸡生蛋引导，platform_admin 操作）**：
1. 门控仍关时，用自报 platform_admin 调 `POST /api/admin/staff-keys` `{staff_id, staff_name, roles}` 签发**首个**人员令牌——secret 仅签发响应返回一次，立即离线保存。
2. 浏览器打开 `/admin/login`，录入该令牌（存 httpOnly cookie，前端后续请求自动注入 `Authorization: Bearer`）；`GET /api/auth/me` 可验当前身份。
3. 运维置 `LOOM_STAFF_AUTH_ENABLED=true` 重启服务即生效；此后管理口无令牌 **401**、角色不足 **403**，query/body 自报的 actor_id/roles 一律被令牌身份覆盖。
4. **回滚**：关掉该 env 重启即恢复 V1 自报行为（纯加法、无迁移回滚）。

**日常管理**（/admin/staff-keys，sidebar 第 12 项；/admin/login 不进 sidebar）：platform_admin 签发/列表/吊销（revoke 为 platform_admin 红线），一人可发多令牌便于轮换；吊销即 401 不可恢复。机器 Agent Key 的签发仍在 /admin/agent-keys（见段 13 步骤 1）。

---

## 1. 标准操作流程（一个产品从录入到发证）

### 段 1 — 产品录入（客户 + operations）

1. **客户**在 products 页提交资料（`POST /api/intakes`），profile 须含全部 12 个 common 字段：f_name、f_brand、f_intro、f_selling_points、f_seo、f_main_image、f_packaging_image、f_target_market、f_language、f_channel、f_audience、f_content_usage。
2. **客户**执行 `submit`（`POST /api/intakes/{id}/transitions`）。
3. 目标语言由客户在产品页维护（Q123，`PATCH /api/intakes/{id}/target-languages`）；未声明则段12 不做产品侧语言收窄。
4. **operations** 依次推进事件：`wf01_confirm → ops_confirm → send_review → review_approve → start_modeling → model_stored`。
5. 到 `stored` 后 `GET /api/intakes/{id}/product-space` 取得 `product_space_id`，进入建模段。

> 段 1 为 15 态状态机；事件只能按合法迁移触发，跳态会被拒。

### 段 2 — 冷启动建模（operations 触发，AI 产候选）

- `POST /api/intakes/{id}/c1-recognition/llm-invoke`：跑 CAT-RECOG，返回候选与 token 计数；候选进入待审，由段1 的 wf01 Gate 人工裁决。
- C7 四层解析对应 `…/c7/llm-resolve`。
- 没有可用场景路由时返回配置错误（见 §3）；private beta 默认全部走 synthetic 或已接线的 agnes 模型。

### 段 3 — 字段池规划 + Gate

1. **operations**：`POST /api/product-spaces/{ps}/field-pools`，提交维度（role、source_route、confidence、source_ref）。
2. **product_reviewer**：`POST /api/field-pools/{id}/gate` `{decision:"approve"}`（驳回则重做）。
3. `GET …/field-pools/current` 取批准后的 `dimension_id` 列表。

### 段 4 — 字段下原子 + 逐条裁决

1. **operations**：`POST /api/product-spaces/{ps}/atom-batches`，每项 `{content, dimension_id, ai_risk, evidence}`。
2. **product_reviewer** 对每条候选 `POST /api/atom-candidates/{id}/approve`（另有 reject 等裁决）。
3. `GET /api/product-spaces/{ps}/atoms` 取 `atom_id` 列表。

### 段 5 — PWC 条件包 + Gate

1. **operations**：`POST /api/product-spaces/{ps}/pwc/funnel`，组合 `{atom_ids, logic_score, fit_score, goals}`。
2. **product_reviewer**：`POST /api/pwcs/{id}/gate` 批准。

### 段 7/8/9 — 发布位、PCP、三包（主数据，须先按 docs/19 回填）

1. 发布位：**operations** `POST /api/admin/publish-slots`（platform、code、slot_type、四维人工分 traffic/safe/conv/load）。
2. PCP：`POST /api/product-spaces/{ps}/pcp`（platform + template_code）。
3. 三包：`POST /api/product-spaces/{ps}/packages` 逐条建 csp / cstp / cep，`{kind, platform, goal, payload, conf}`。

### 段 6 — PWS 冻结

- **whitelist_owner**：`POST /api/product-spaces/{ps}/pws/freeze`。冻结即 5 门 readiness 校验，任一不过返回未就绪原因；冻结后如需变更走重冻/版本/revoke 流程。

### 段 10 — 合规清洗

- **internal_compliance**：`POST /api/pws/{pws_id}/ccr/run`；报告 `status=clean` 方可组装。命中 block_required 时按报告处理（清洗或法审，法审 SLA 48h）。

### 段 11 — FCW 组装发证（V1 主链终点）

- **operations**：`POST /api/fcw/assemble` `{product_space_id, platform, slot_id, goal, actor}`。
- 七 Guard 全量不短路；通过则签发 `final_id`，`publish_status=published`、`guards_passed=true`；不通过返回 **409** 与 `detail.guards` 逐门结果。
- 中台导出：CSV `GET /api/fcw/{final_id}.fcw.csv`、JSON envelope `….fcw.json`（含 limit/offset，行数上限 env `LOOM_EXPORT_MAX_ROWS` 默认 10 万）；台内原料 `GET /api/fcw/{final_id}/material.json`。
- 异步导出经 `/api/exports/jobs`（worker 门控默认关，关时同步落 completed；管理页 /admin/exports）。
- **白名单卡片查看（Q177/Q180）**：运营在管理台 /admin/fcw 跨租户分页查看全部成品卡片、行内展开六层原料（只读，operations|platform_admin）；客户在自己台的 content → cards（`/content/cards`，客户 nav 不增项）只看本租户卡片，后端 `GET /api/fcw?tenant_id=` 强制单租户隔离。

---

## 2. 段 12 / 段 13（beta 已接线，按需使用）

### 段 12 — 内容生成与客户审阅

1. **operations**：`POST /api/content/generate` `{final_id, kind:"article", language, actor}`。
   - language 必须在可生成清单内：`GET /api/content/eligible-languages?final_id=`（发布位市场 ∩ 产品目标语言，Q119）。
   - 默认 `zh-CN`。
2. **客户**在 content 页裁决：`approve`（→ `ready_for_publish`）/ `reject`（reason 必填）/ `revise`（客户可在改稿岛编辑后 manual_resubmit）/ `regenerate`（上限 3 次）。
3. AI 质量分（ARTICLE-QC）与语义检测（ARTICLE-SEMANTIC-CHECK）为纯 advisory，不阻断。
4. **operations** 托管发布后回填：`PUT /api/admin/content/{id}/publish-info`（url 必填）；不新增 published 态，三列非空即已发布。队列：`GET /api/admin/content/ready-to-publish`。
5. 难产骨架：**operations** `POST /api/content/{id}/discard`（reason 必填，终态，释放唯一占位回池）；队列在 needs-attention。

### 段 13 — 效果回流

1. **platform_admin** 在 /admin/agent-keys 签发 Agent Key（secret 仅显示一次）。
2. 外部系统带 `Authorization: Bearer <secret>` 调 `POST /api/effect-callback`，records 按 `content_id` 精确匹配非 discarded 成品；整批 all-or-nothing，回执 `{received, matched, orphan}`。
3. 孤儿（无匹配）：**operations** 在 /admin/effects 单条或批量认领（external_content_id→content_id 映射），可改绑/解绑。
4. 客户回填（无 Agent Key）：`POST /api/effects/backfill`（只命中本租户、绝不产生孤儿）；批量走 `/upload`（CSV）、`/upload-excel`（xlsx，上限 env `LOOM_BACKFILL_UPLOAD_MAX_ROWS` 默认 1 万）、异步任务 `/api/effects/backfill/jobs`（worker 门控默认关）。
5. metrics 字段缺席记 NULL，**绝不补 0**；captured_at 必须带时区；(content_id, captured_at) 幂等。

---

## 3. 常见 4xx / 5xx 含义与处置

| 码 | 典型含义 | 处置 |
|---|---|---|
| 401 | Agent Key 缺失/无效/停用（effect-callback、A2A tasks）；或门控开后管理口 staff 令牌缺失/损坏/吊销（Q178） | 机器口核对 `loom_` secret 与 Key 状态；人员口在 /admin/login 重新录入有效的 `loom_staff_` 令牌 |
| 403（PermissionDenied） | actor.roles 不含该口所需角色 | 换正确角色账号；勿在业务流程中提权 |
| 404 | 资源不存在（intake/ps/pws/fcw/content）；**导出任务口跨租户也回 404**（Q196，与不存在同码，不做存在性探针） | 核对 ID 与 `tenant_id` 是否同一租户；FCW 未签发前段12 各口必 404 |
| 409 状态机冲突 | 事件在当前态非法 / 重复发证 / FCW 已签发 / 材料缺失 / 下载口对 queued·running 作业 | 查当前状态再决定下一步；assemble 的 409 看 `detail.guards` |
| 409 锁冲突 | 单 leader 锁被占（SLA/restock 手工 /run） | 单实例稍后重试；LockLost→409 表示锁已易主，本轮中止 |
| 422 | 请求体校验失败：submit 缺 common fids、语言不在 eligible、PWC/评分参数非法、导出行数超上限、时区缺失、Excel/CSV 坏行、**导出任务状态口/下载口缺 `tenant_id`**（Q196 起必填） | 按 detail 字段（如 missing_fids、eligible、逐行错误）修正后整批重提 |
| 503 | 锁后端故障 / 异步 worker 入流失败（fail-closed） | 排查 Redis/基础设施后重试 |
| ModelConfigError（500/配置错） | 场景无路由 / 模型或 Key 未配置 | platform_admin 在模型管理补模型、Key 与场景路由 |

---

## 4. 日常运维节奏

- **SLA sweep**：调度器自动巡检（受单 leader 锁/PG 行级 fence 保护）；手工触发 `POST /api/admin/sla/run`；阈值 SLA 72h、黄 24h、红 48h（Q149）。
- **难产/孤儿/待发布三队列**：每日在 /admin/content 与 /admin/effects 过 needs-attention、orphans、ready-to-publish。
- **审计**：每个写操作与每次 LLM 调用均落审计；异常排查先查审计与 `/admin/token-cost`。
- **指标（Q181）**：`GET /metrics` 暴露 Prometheus 文本（Counter/Gauge/Histogram + 每请求计时，path 按路由模板低基数），不鉴权（同 /healthz），供抓取；可选 prometheus 容器在 compose `monitoring` profile 后、默认不启动（`docker compose --profile monitoring up`）。
- **备份与恢复**：逻辑备份＝db-backup sidecar 每日 `pg_dump` + 7 天保留（`infra/backup/backup.sh`），异机逻辑恢复演练 `infra/restore-rehearsal.sh`（Q158，12/12）；**WAL 归档 + 基础备份 + 对象存储 PITR（Q182）**＝postgres 持续归档 WAL（archive_timeout=300s）、db-basebackup 周期基础备份、wal-archiver 推 MinIO，RPO 分钟级、可回滚到指定时点，演练脚本 `infra/wal/pitr-rehearsal.sh`（before=1/after=0 实测，本地手动不进 CI）；跨 region 对象存储冗余仍为 V2。
- **演练**：全链验证跑 `infra/fullchain-rehearsal.sh`（synthetic 不花钱；真 LLM 演练需授权 + 当日预算内）；高可用/负载演练 `infra/ha-rehearsal.sh`、`infra/load-rehearsal.sh`（本地手动不进 CI）。

> 校准类口径（效果反哺算法、Q54 评分等）原文【待补】，运营不得自行编公式，按业务/数据科学口径下达后执行。

## 5. 告警与值班处置（Q185 消费面 ＋ Q188 业务信号）

**先记住三条前提，否则会误判"没告警＝没事"：**

1. **默认部署一条告警都不会发。** 规则与 Prometheus 都在 opt-in overlay 里，须
   `docker compose -f docker-compose.yml -f docker-compose.monitoring.yml --profile monitoring up -d` 起监控栈；
   没起栈就没有任何告警面，`/metrics` 仍可自己抓。
2. **同一个故障只通知一次。** 投递是 watchdog 轮询 `Prometheus /api/v1/alerts` 转发进 `LOOM_ALERT_WEBHOOK`
   （**刻意不开 Alertmanager 容器**，Q185 实测其 0.34.1 两条 URL 通路都不可用），语义为
   「只转发 `state=firing`、按 `alertname|instance|activeAt` 去重」。**收到一次后长期静默不等于已恢复**，
   要确认恢复得回看 Prometheus；同理**没有 grouping / silencing / inhibition**，维护窗口期会照常打到群裡。
3. **业务队列两族指标只在 worker 开着时存在。** `LOOM_EXPORT_WORKER_ENABLED` / `LOOM_IMPORT_WORKER_ENABLED` /
   `LOOM_FCW_WORKER_ENABLED` 默认全关（V1 单副本同步形态），此时 `loom_stream_pending` / `loom_stream_length`
   **无序列**、两条队列规则**永不触发**——这是事实，不是漏报。

**规则 → 第一步查哪里 → 要不要停线**（`infra/monitoring/alert_rules.yml`；序列定义在
`backend/app/core/metrics/business.py`）：

| 规则 | 它在说什么 | 第一步查哪里 | 停线？ |
|---|---|---|---|
| `LoomBackendUnreachable` (critical) | Prometheus 抓 `backend:8000/metrics` 连续 1 分钟失败 | 容器是否活着／健康检查；`GET /healthz` | **是**，先当服务不可用处理 |
| `LoomHigh5xxRatio` (critical) | 近 5 分钟 5xx 占比 >5% | 后端日志栈顶异常类型；审计表看是否集中在某写口 | 视占比，>20% 按故障处理 |
| `LoomHighP99Latency` (warning) | 后端 P99 >1s 持续 5 分钟 | 慢在哪个路由模板（`http_request_duration_seconds_bucket` 的 `path` 标签） | 否，先观察 |
| `LoomJobFailed` (warning) | 有异步作业进入 `failed` 终态（kind=export\|import\|fcw） | 导出 `GET /api/exports/jobs` 与管理端 /admin/exports；导入 `GET /api/effects/backfill/jobs`；FCW `GET /api/fcw/assembly-tasks/{id}`；审计 `export.job_failed` / `import.job_failed` / `fcw.assembly_task_failed` | 否，**但必须有人认领**——failed 不会自动重试 |
| `LoomStreamDeadLettered` (critical) | 消息重复投递仍失败、已进死信流 | 读 Redis 死信流 `loom:stream:exports:dead` / `loom:stream:imports:dead` / `loom:fcw-assembly:dead`（字段 `_dead_reason`、`_dead_origin_id`）；**管理端无死信页**，目前只能 `XRANGE` | 否，但死因要归类：`max-deliveries-exceeded`＝下游真故障，`job-not-found`＝入流早于提交可见 |
| `LoomQueueBacklog` (warning) | 某消费组「已投递未 ACK」>100 持续 10 分钟 | 是不是只有 1 个 consumer 在跑（Q152 可调 `LOOM_EXPORT_WORKER_CONCURRENCY`）；或 worker 卡在真 LLM/DB 慢调用 | 否 |
| `LoomStreamNearTrimLimit` (critical) | 流长度 >5000，逼近近似 `MAXLEN≈10000`——**再涨就开始丢未消费消息** | 生产侧是否远快于消费（入流闸门/门控）；必要时临时加 consumer 数或扩 MAXLEN | **是**，这是数据丢失前最后一站 |
| `LoomLockLost` (warning) | 看门狗判 leader 租约易主（锁过期被抢／续约期 Redis 故障 fail-closed） | 是否多副本同开 `LOOM_DISTRIBUTED_LOCK_ENABLED` 且机器时钟漂移；Q143/Q151 的 PG 行级 fence 已挡旧 leader 迟到写，故先看是否伴随 `LoomQueueBacklog`／sweep 停摆 | 否，fence 已兜底，但要查 TTL/时钟 |
| `LoomLlmUpstreamSlow` (warning) | 某 scene 成功调用 P99 >30s 持续 10 分钟（按 `provider` 分开，synthetic 不污染） | 供应商侧状态；`LOOM_LLM_HTTP_TIMEOUT_SECONDS`（Q172 配置化，默认 60s）是否偏小——注意超时打满会同时顶到 30s P99 规则 | 否，链会变慢但不断 |
| `LoomLlmBudgetBlocked` (warning) | 某 scene 调用被**日预算硬停**在花钱之前拒绝 | 配置中心该模型 `daily_budget` 与当日 `SkillRun` 花费；**这是停摆不是降级**——AI 候选不再产出 | 视业务，需要就调预算并留审计 |

**每条规则被证明到哪一层（别把 39/39 读成「七条都端到端验过」**：

| 规则 | 已证明 | 未证明 |
|---|---|---|
| `LoomBackendUnreachable` | **端到端**：真停 backend → firing → watchdog 恰一次转发（阶段 4） | — |
| `LoomJobFailed` | **端到端**：真停 redis 走入流 fail-closed → 75s firing、105s 转发 1 次（阶段 5）＋exposition 0→1 单测 | — |
| `LoomLlmBudgetBlocked` | 9 场景零序列已预置（单测）；真 HTTP 409 会计数（集成测试断言 counter +1） | 真栈上「求值→转发」那一段无独立证据（与上两条共用机制，但共用不等于验过） |
| `LoomStreamDeadLettered` | 零序列随 worker tick 预置（单测，且后端故障时预置仍先生效） | 真栈未证：造一条死信需 ≥6 分钟投递接管轮（`max_deliveries=5`、`min_idle=60s` 皆非 env 可调），**刻意未做** |
| `LoomQueueBacklog` / `LoomStreamNearTrimLimit` | 取样链与 Gauge 语义（真 Redis 实测 XPENDING 与 XLEN 正交） | 真栈无积压量级可造；阈值本身待校准 |
| `LoomLlmUpstreamSlow` | 桶与 outcome 标签、真往返计时 | 分位数需窗口内 ≥2 次调用，**单次慢调用不触发**（固有性质非缺陷）；真供应商 P99 未测 |

要补哪条的证据时，别靠放宽阈值让它变绿——那是把「没证明」换成「证明了一个不存在的东西」。

**数值来源纪律**：`100`（未 ACK）/ `5000`（流长）/ `30s`（上游 P99）与 `content.discard_retention_days=180 天`
**原文均未给出**，是工程默认值（甲案已经负责人 2026-09-25 追认＝02 C1.134）；**追认结的是设计选择，不结数值校准**——
真队列压出来之前这些阈值没被证明合理，误报/漏报请记回 docs/20 而不是各自改本地值。

**看板可达性（Q192 起，已实测）**：监控 overlay 给 Grafana 发布的是**宿主回环端口**
`127.0.0.1:3001`（**不是** 3000——base compose 里 3000 已经是 frontend）。

- 在**跑着栈的那台宿主机**上开浏览器：`http://127.0.0.1:3001`，用户名 `admin`、口令即
  `LOOM_GRAFANA_ADMIN_PASSWORD`（该变量无默认值，不设则监控栈根本起不来）。
- 两张看板文件式置备、`uid` 固定：`loom-http`（HTTP 基本盘）与 `loom-operations`（Q188 业务信号）。
  机器可核的路径是 `GET /api/dashboards/uid/loom-operations`（演练里断言 200）。
- **只绑回环是刻意的**：Grafana 唯一的门就是那个管理员口令，绑 `0.0.0.0` 等于把它裸露在网卡上。
  代价是**远程看盘需要自己起隧道**（例如 `ssh -L 3001:127.0.0.1:3001 <host>`），
  该做法本仓未实测，不在此充当标准步骤。
- 不想开 Grafana 时的替代：Prometheus 仍发布 `9090`，其 `/graph` 表达式页可直接查这 10 条规则用到的
  全部序列；`GET /metrics` 是原始文本。
- **可达性由演练守着**：`infra/alerting-rehearsal.sh` 阶段 3 有两条宿主侧断言——从宿主机 `curl`
  `127.0.0.1:3001/api/health` 必须 200，且 `docker port grafana` 必须显示只绑 `127.0.0.1`。
  2026-09-25 全量演练 **39/39 PASS**（含阶段 5「业务告警实触发」：停 redis 让导出作业真失败，断言 `LoomJobFailed` 曾 firing 且带 `kind=export`、watchdog 恰转发一次——七条业务规则唯有此处被端到端证明过）。发布口形状另有契约测试硬守
  （`test_grafana_is_loopback_only`：绑错网卡、撞 3000、多开口子都判红）。

> 起监控栈需要 `LOOM_GRAFANA_ADMIN_PASSWORD`（**无默认值、缺失即 compose 报错**）——这是 Q185 有意为之，
> 拒绝内置弱口令；该变量只在监控 overlay 里必填，不开监控栈的默认部署不受影响。
