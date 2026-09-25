# Loom · 契约层 · API 与状态机

> **本文档来源**：`../Loom_核心业务主链梳理_v3.md` **Part A / Part C / Part D 结构化提取**（重组视图，非原文直排）。
> **文档定位**：AI 落代码的硬前提之一。系统对外/对内 API 契约 + 全部已定义状态机。**原文未给出的事件/迁移/字段一律标注【待补：原文未给出】，不编造**。
> **配套文档**：实体字段见 04；WF/Skill 协议见 06。

---

## Part 1 · API 契约

### 1.1 已定稿契约（原文给出完整定义）

#### 1.1.1 POST /api/effect-callback（段13 · Q60，**契约完整**；入站 Q126–Q131 已落地[含认领批量/解绑与两端操作 UI]，见本节末实现补登）
- **用途**：效果数据回流（全链唯一反向边的数据入口）。
- **调用方**：外部 Agent 系统（本系统不做抓取、不做定时拉取调度，Q62）。
- **鉴权**：API Key（一 Agent 一 Key，可吊销，复用 API Key 管理模块）。
- **请求体**：
  ```
  {
    source: string,                       // Agent 标识；客户回填时 = "customer-backfill"
    records: [{
      content_id: string,                 // 本系统内容 ID（发布后由运营回填 platform_post_id 建立映射）
      platform_post_id: string,           // 平台帖子链接/ID
      captured_at: datetime,              // 采集时间
      metrics: {                          // 全部可选字段
        plays, likes, comments, shares, read_rate, inquiries, conversions
      }
    }]
  }
  ```
- **数据纪律**：缺席字段=未采集记"—"，**绝不当 0 / 不许估算**。
- **幂等/时序**：同 content_id 多次推送按 captured_at 追加为时间序列；同 content_id+captured_at 幂等覆盖。
- **孤儿数据处理**：对不上 content_id 的推送进"孤儿数据"队列人工认领（Q60a；**认领动作已随 Q127 落地**，见下 Q127 补登）。
- **发布链路（业务澄清 Q60c）**：客户确认（仅审批信号）→ **运营用托管账号发布** → **运营回填平台链接/ID** → Agent 抓取 → 本 API 推送。前端客户不填写平台链接。**Q125（C1.69）已落「运营回填」一环**：`PUT /api/admin/content/{id}/publish-info` + 待发布队列 `GET /api/admin/content/ready-to-publish`，published_at 非空即已发布（不新增 published 态）；Agent 抓取仍随段13 P3/V2；**本 API 推送（effect-callback 入站）已随 Q126 落地第一片**（见下 Q126 补登）。
>
> **Q126 实现补登（2026-09-19，段13 入站第一片，迁移 0034，02 C1.70）**：新建横切包 `app/core/effects/`（models/schemas/service/router）+ 物理表 `effect_records`，复用 Q88 `require_agent_key` Bearer 验签（缺失/错误/吊销统一 401，首个受 Agent Key 保护的业务消费端点）。请求 `{source, records[]}`，record=`content_id/platform_post_id/captured_at/metrics?`；**整批 all-or-nothing**（任一记录非法 422 回 index/field/message，不落部分；source 必填非空白、records≥1、批内重复 (content_id,captured_at) 422）。metrics 七键：六计数（plays/likes/comments/shares/inquiries/conversions）为非负整数、read_rate 为 0..1 数值，bool/未知键拒绝，缺席键与显式 null 不落库（绝不写 0、不估算）。captured_at 须带时区（naive 422）并归一 UTC；同 (content_id,captured_at) 重推幂等覆盖（不新增行）、不同 captured_at 追加时序。按 content_id 精确匹配**非 discarded** 成品：命中 status=matched 并回填 matched_content_id(nullable FK)/tenant_id（由 content.tenant_id 解析，Key 不绑租户），查无或命中 discarded 为 status=orphan；platform_post_id 只留存、不自动绑定。200 回执 `{received,matched,orphan,upserted}`，批级审计 `effect.batch_received`（tenant `_platform`、actor=key_id、roles=[]）。运营只读 `GET /api/admin/effects/orphans`（跨租户孤儿、captured_at 升序）与 `GET /api/admin/effects?content_id=`（成品时序），operations|platform_admin 的 query actor 闸（缺 actor 422、越权 403，limit 1..100 默认 20 / offset 默认 0）。测试 554→591（+37），迁移 0034 经 pg16 往返实测（业务物理表 55→56、FK/索引就位）。**Q127/Q128 后续片已销账**：Q60a 孤儿人工认领动作、customer-backfill 客户专用通道均已落地（见下两段补登）。**Q129–Q131 后续片已销账**：认领取消/解绑与批量认领（Q129）、管理端认领台 UI（Q130）、客户回填 UI（Q131）均已落地（见下三段补登）。**仍随续片/V2 不落**：content_id↔platform_post_id 运营回填映射的自助化、回填批量表格/CSV 导入（V2）、**效果反哺知识与 Q54/Q57 评分阈值的相关性校准算法（口径原文未给【待补】，不臆造公式）**、Agent 抓取与发布自动化（Q62 本系统不抓取）。

> **Q127 实现补登（2026-09-19，段13 入站第二片·Q60a 孤儿人工认领，迁移 0035，02 C1.71）**：新表 `effect_claims`（external_content_id String36 PK / content_id String36 NOT NULL FK `fk_effect_claims_content`→content_products / claimed_by String64 / claimed_at timestamptz default now / updated_at 可空）持久保存「推送方 ID→本系统成品」人工映射；`effect_records` 加 nullable `claimed_by` String64 / `claimed_at` timestamptz 两行级溯源列（**不新增第三状态**，认领后行转 matched、claimed_by 非空即人工认领）。写口 `POST /api/admin/effects/claims`，body `{record_id, content_id, actor}`（管理面写口 actor 在体，服务层 operations 硬闸，客户/platform_admin 403，同 Q125 写口口径）：入口记录须存在且当前 orphan（未知 404、非 orphan 409），目标成品须存在且非 discarded（未知 404、discarded 409）；动作＝upsert 映射（重复认领即改绑）＋批量回填该 external_content_id 下全部 orphan 行与历史 claimed 行（自动 matched 行不动），响应 `{external_content_id, content_id, claimed_by, claimed_at, updated_rows}`，审计 `effect.claimed`（tenant `_platform`、entity_id=external_content_id）。**ingest 认领兜底（不冲回孤儿的关键）**：Agent 通道自动匹配未命中的 ID 再查 effect_claims，映射目标存在且非 discarded 即按映射 matched（幂等覆盖行与新采集点都不再回落 orphan）；目标缺失/discarded 则回落 orphan、映射保留。测试 +8（test_effect_claims_api.py），迁移 0035 经 pg16 往返实测（业务物理表 56→57、down 回 56、再 up 57）。~~不落：取消认领、认领前端页（V2/后续）~~ **已随 Q129（解绑/批量）、Q130（管理端认领台）销账，见下**。
> **Q128 实现补登（2026-09-19，段13 入站第三片·customer-backfill 客户专用通道，零迁移，02 C1.72）**：新端点 `POST /api/effects/backfill`，**无 Agent Key**，body `{tenant_id, records[], actor}`（与 Q122 客户写口同构：actor 在体、客户 roles 恒空、无运营闸；tenant_id 口径同 `GET /api/content?tenant_id=`）。source 服务端固定 `"customer-backfill"`（不接受客户端传入）；**客户通道绝不产生孤儿**——每条 content_id 必须命中本租户非 discarded 成品，否则该条 422（index/field=`content_id`/message），整批 all-or-nothing，且不查认领映射兜底。captured_at 带时区（naive 422）归一 UTC、(content_id,captured_at) 幂等覆盖/新点追加、metrics 七键稀疏纪律与 Agent 通道完全一致（复用同一归一/持久化路径）；received_by=客户 actor.id；审计 `effect.customer_backfilled`（**tenant=客户租户**，区别于 Agent 通道 `_platform`）；回执复用 `{received,matched,orphan,upserted}`，orphan 恒 0。测试 +8（test_effect_customer_backfill_api.py）。Q127+Q128 合计后端 591→607（+16），ruff 净，eval 101/101，前端零改动。~~不落：客户回填 UI~~ **已随 Q131（内容详情页回填岛）销账，见下**；效果反哺校准算法仍口径【待补】。

> **Q129 实现补登（2026-09-20，段13 认领批量/解绑，零迁移，02 C1.73）**：①`POST /api/admin/effects/claims/unclaim`，body `{external_content_id, actor}`（operations 硬闸，客户/platform_admin 403，映射不存在 404 `ClaimMappingNotFound`）：删 effect_claims 映射行，把该 external_content_id 下 **matched_content_id 等于旧映射目标** 的全部行回滚 orphan（清 matched_content_id/tenant_id/claimed_by/claimed_at 四列；按旧目标 content_id 筛而非 claimed_by 非空，认领后经兜底 matched 的新推送行 claimed_by 为空也一并回滚；external_id 自匹配的真自动行不受影响），回 `{external_content_id, reverted_rows}`，审计 `effect.claim_revoked`（tenant `_platform`、entity_type=effect_claim、detail 含旧 content_id/reverted_rows）。②`POST /api/admin/effects/claims/batch`，body `{items:[{record_id,content_id}](≥1), actor}`：逐条复用单条认领（service 抽 `_claim_one` 无角色闸，claim_orphan/batch 各自过 operations 闸），批内 record_id 重复 422（detail `{index,field:"record_id",message}`）、空 items 422，任一记录 404/409 整批 all-or-nothing 回滚，逐条 `effect.claimed` 审计随事务，回 `{claimed, updated_rows}`。测试 607→618（+11：unclaim 5 + batch 6，test_effect_claims_api.py 累计 19 例），ruff 净，eval 101/101，零迁移（迁移头仍 0035、物理表 57）。
> **Q130 实现补登（2026-09-20，段13 管理端操作面，零迁移，02 C1.74）**：新建管理端 `/admin/effects`（sidebar 第 8 项，check-admin 锁恰 8 项）：孤儿数据队列（RSC 取 `GET /api/admin/effects/orphans?limit=100`，孤儿认领岛支持单条认领与勾选批量认领，整批成功或整批拒绝）＋成品效果时序（按 content_id 查 `GET /api/admin/effects?content_id=`，人工认领行可「取消认领」，window.confirm 后调 unclaim 并重查）。读 operations|platform_admin、写 operations（缺 LOOM_ADMIN_ACTOR_ID=unconfigured、缺 operations=missing_role 本地拒发）；RSC force-dynamic、client 岛只走同源 Server Action、成功 router.refresh；指标缺席显 "—" 绝不显 0。文件：app/[locale]/admin/effects/ 五文件（page/actions/orphan-table-island/series-island/effect-fields）＋admin-sidebar＋lib/api.ts effects 段＋messages admin.effects 段；check-admin 扩守卫（五文件/消息键/sidebar 8 项/后端六路由齐备）。
> **Q131 实现补登（2026-09-20，段13 客户回填操作面，零迁移，02 C1.75）**：客户「内容生产与发布」**详情页**对非 discarded 成品挂回填岛（客户 nav 仍恰 8 项，不新增菜单；09 客户数据分析 V2 菜单不动）。V1 单条手工表单：platform_post_id 必填、captured_at 用 datetime-local 经 `new Date(value).toISOString()` 转带 Z 的 UTC（后端 tz-aware、naive 422）、metrics 七键数字输入（留空＝缺席不落；六计数挡非负整数、read_rate 挡 0..1），提交 Q128 的 `POST /api/effects/backfill`（body `{tenant_id, records:[{content_id=当前成品,...}], actor}`，客户 roles 恒空），422 `{index,field,message}` 回显，成功 router.refresh 清空表单、回执显 matched 数。批量表格/CSV 随 V2。文件：(shell)/content/backfill-island.tsx＋content/actions.ts 增 backfillEffectAction＋详情页挂载＋messages content.backfill* 段；check-content 扩守卫（岛 "use client"/禁直连 API/router.refresh/datetime-local+toISOString、actions 含 backfillEffectAction/customerBackfillEffects、后端 backfill 路由串）。前端 tsc 净、八 checker 全过、next build 通过。

> **Q156 实现补登（2026-09-21，段13 客户批量回填服务端化，零迁移、零新依赖，02 C1.100）**：新端点 `POST /api/effects/backfill/upload`，**无 Agent Key**（客户通道，同 Q128），JSON body（不引 multipart/python-multipart）`{tenant_id, content_id, csv, filename?, actor}`，整份挂单一 content_id（与 Q136 九列一致：platform_post_id,captured_at + 六计数 + read_rate，无 content_id 列）。新纯函数 `app/core/effects/csv_io.py`（标准库 csv）：去 BOM、表头按名定位（重复/未知/缺列聚合）、跳纯空行（不计上限）、回执物理行号（首数据行 line=2）、post_id 必填、captured_at fromisoformat（Z→+00:00）且**服务端强制 tz-aware（naive/纯日期逐行 422）**、计数 `^\d+$`、read_rate 0..1、空指标缺席不落 0；**逐行收集全部坏行一次回 422**（CsvValidationError.errors[]{index,line,field,message}）；行数硬上限 env `LOOM_BACKFILL_UPLOAD_MAX_ROWS`（settings `backfill_upload_max_rows` 默认 10000，运维旋钮非 Q9 阈值），0 数据行/超限 422。解析通过复用 Q128 `ingest_customer_backfill`（只命中本租户非 discarded 成品否则整批 422、绝不孤儿、all-or-nothing、审计 effect.customer_backfilled），200 回执 `CustomerBackfillUploadReceipt`（在 Q128 `{received,matched,orphan,upserted}` 上追加 filename 与 rows[]{index,line,platform_post_id,captured_at}）。**甲案接缝待负责人追认**：服务端强制时区（前端岛有浏览器时区可转、纯 API 上传无上下文，不静默假定 UTC）、上限默认 1 万为工程值待运维调、CSV 走 JSON body；Excel（openpyxl）/异步导入任务/前端岛切换新端点仍挂 V2。测试 test_effect_backfill_upload_api.py 7 例（+7）。

> **Q88 实现补登（2026-09-15，鉴权前置半套）**：本行的“API Key（一 Agent 一 Key，可吊销）”半套已落地——`app/core/api_keys/` + 迁移 0019 新表 `agent_api_keys`（SHA-256 单向哈希存储，明文仅签发响应返回一次，吊销=active/revoked 状态位 append-only），platform_admin 治理端点 `POST/GET /api/admin/agent-keys`、`POST /api/admin/agent-keys/{id}/revoke`，Bearer 验签依赖 `require_agent_key`（失败 401）已备。**本端点 POST /api/effect-callback 本身、records 时序落库（content_id+captured_at 幂等、缺席指标记“—”不当 0）、孤儿队列人工认领、Q60a 运营回填映射、customer-backfill 均仍随段13/P3（V2），本切片不提前落**；Key 在 V1 无受保护业务消费端点为显式记录的已知挂账（同 Q82“底座先行”）。详见 02 C1.32。

#### 1.1.2 白名单消费接口（段11/5 · Q71，**契约主体完整**）
- **用途**：系统后台 API 端消费内容配方（PWC/白名单）。
- **取用排序**：按评分从高到低取（Q22 PWC 分 / Q54 FCW 分，临时公式够排序）。
- **去重**：同平台+同账号+同发布位不重复（Q24）；命中即写 usage_record 并流转状态。
- **保底补给**：待用池跌破保底线自动触发一轮相撞补货回目标量；触发线=critical（50）、目标=target（100），补货冷却默认 5min（防抖）。
- **池健康度三档**：target 100 / min 70 / critical 50（line 1451）。
- ⚠ 参考来源：业务方 E1 `/api/whitelist/consume`（按权重取 + usage_record + 5 池保底）——采纳骨架但**不采用"上限 200"**，一律以本系统池健康度三档为准。

### 1.2 已点名但契约未定稿（开发补规格范围）

| API | 来源 | 现状 |
|---|---|---|
| 白名单查询 API | D9.5 系统后台 API 端 | 仅有页面清单，无契约【待补】 |
| 使用记录上报 API | D9.5 / Q71 | 同上【待补】 |
| 效果回流 API | D9.5 / Q60 | Q60 已定稿（见 1.1.1） |
| DB 浏览 / AI 调试台 / 调用日志 / 配额 / Key 管理 | D9.5 | 后台内部接口【待补】 |
| 中台对接 API + Webhook 反馈回流 | D4 | V2 项：中台调 API 拿白名单 + Webhook 回流【待补】 |
| 中台 SDK 嵌入 | D4 | V3 项：中台集成 Loom SDK【待补】 |
| 中台 CSV/JSON 导出 | D4 | V1 项：CSV 已定稿（Q100）=仅 final_id 单列同步 GET，中台手动用；~~JSON 形态仍【待补，挂后续】~~ **已落地：JSON 形态随 Q132（同口径 envelope）、异步导出任务随 Q132、真后台 Streams worker 随 Q137、分页与行数硬上限随 Q142**（见本文件导出端点表）｜2026-09-25 Q198 按实现回填缺口口径，非新决策 |

### 1.3 鉴权与治理（横切）
- **API Key 唯一入口**：真接 LLM 时模型注册页是唯一入口（line 2101）；Q67 合并为一张模型注册表（per-1M）。**Q82 已落地 outbound 半套**：Key 密文落库 + env 主密钥、注册页录入/轮换/吊销，明文永不回显；**入站“一 Agent 一 Key 可吊销”Key 半套已随 Q88（2026-09-15）落地**：独立新表 `agent_api_keys` 存 SHA-256 哈希（非可逆加密，入站只需比对）+ 展示前缀，`/api/admin/agent-keys` 签发/列表/吊销（platform_admin），Bearer 401 验签依赖已备；effect-callback 业务端点本体仍随段13/P3（V2）。
- **单一出口红线（line 11036）**：全系统只有 E1.1 publishFCW 能生成 final_content_whitelist_id；任何其他模块/Skill/Agent 写 final_id = 越权 = 违反协议。**Q203 起这条红线有运行期守卫**：`final_content_whitelist` 的 ORM mapper 在 E1.1 的签发作用域（`app/final/final_whitelist/exit_guard.py`）之外拒绝 INSERT，直插即判红。覆盖边界＝ORM flush；Core `insert()`/裸 SQL 不经 mapper 事件，全仓今日对该表无此类写入（迁移里只有建表、无种子），边界由 `test_fcw_single_exit_guard.py` 钉成实测事实而非断言。
- **E1.1 写口的身份（Q203 收紧）**：`POST /api/fcw/assemble` 与 `POST /api/fcw/assembly-tasks` **只认已验真的内部令牌**（`loom_staff_` PAT，Q178）——`Authorization: Bearer` 缺失/无效/吊销一律 401，令牌角色不含 operations 一律 403；**body 里自报的 `actor` 不再是身份**（被验真令牌覆盖，被推翻的自报值按 Q196 口径降级存证）。与 Q178 全局门控的分工：这两个口在 `LOOM_STAFF_AUTH_ENABLED=false`（默认形态）下**也自行验真**，所以发证保护不是 opt-in；其余内部口仍按 Q178（门控开才强制）。代价：脚本/测试打这两个口须先按 Q178 引导流程签一枚令牌。

### 1.4 M1–M11 已落地 REST 端点（2026-09-13 起后端切片实现登记；实现序 M7→M11→M8，段11 已闭合）

> 以下为已实现端点（FastAPI，前缀见各行）；原文未给契约，属"开发补规格"落地，**不是已定稿契约的替代**——后续契约层定稿以本节实现为对账输入。错误口径统一：不存在 404 / 业务状态不允许 409 / 角色不符 403 / 输入或规则校验失败 422；所有写操作 writeAudit。

**M1 段1 产品录入（前缀 `/api/intakes`）**

| 方法/路径 | 说明 | 依据 |
|---|---|---|
| POST `` | 创建申请单 | 13 §1.1 |
| GET `` | 按租户分页列表（Q98；tenant_id 必填，limit≤100；读路径不触发准入门，未知租户空列表） | Q98 |
| GET `/overview` | 按租户状态聚合（Q99；tenant_id 必填；读路径不触发准入门，未知租户零值；注册序先于 `/{intake_id}`） | Q99 |
| GET `/ops-queue` | 跨租户运营只读队列（Q107；query actor_id 必填+重复 roles，operations\|platform_admin，否则 422/403；可选 status 限 15 态非法 422、limit≤100/offset；created_at DESC；行含 created_at；注册序先于 `/{intake_id}`） | Q107 |
| GET `/{intake_id}` / `/{intake_id}/allowed-events` / `/{intake_id}/product-space` | 查询/可迁事件/生成的 PS | — |
| PATCH `/{intake_id}/profile` | 补资料（审核后不可改 409） | Q74 |
| POST `/{intake_id}/transitions` | 15 态事件迁移（缺字段 422 / 越权 403 / 非法迁移 409） | Q3/Q5 |

**M2 段2 C1 识别（前缀 `/api`）**

| 方法/路径 | 说明 | 依据 |
|---|---|---|
| GET/PUT `/admin/c1/signal-weights` | Q2 权重表（Σ≠1 → 422；operations；越权 403，Q75 补闸；**Q109 起 GET 补 operations query 读闸：缺 actor_id 422、越权 403**） | Q2/**Q109** |
| GET/POST `/admin/c1/industries`，PATCH/DELETE `/admin/c1/industries/{industry}` | Q7 阈值 CRUD（operations；越权 403，Q75 补闸；默认档删 → 409；**Q109 起 GET 同补 operations query 读闸**） | Q7/Q75/**Q109** |
| POST `/intakes/{intake_id}/c1-recognition` | conf 三分支（高置信 auto_confirm；中置信出待办；低置信须带 category_pending_id） | Q1/Q3/Q5 |
| POST `/intakes/{intake_id}/ops-decision` | 运营选定/全否 | Q3 |
| POST `/admin/ops-todos/sweep` | 72h 到期升级（手工触发，**platform_admin**，越权 403；Q75；调度随 M10） | Q4/Q75 |
| POST/GET `/categories`，PUT `/categories/{category_id}/template` | G1 最小切片 + 叶子模板（**dictionary_admin**，越权 403；fid:'-'/未知 fid → 422；Q75；**Q109 起 GET 同补 dictionary_admin query 读闸：缺 actor_id 422、越权 403**） | Q68/Q75/**Q109** |
| POST `/intakes/{intake_id}/c7-runs` | C7 L1–L4 兜底（L4 提案入库候选） | Q6/Q68 |

**M3 段3 字段池规划（前缀 `/api`）**

| 方法/路径 | 说明 | 依据 |
|---|---|---|
| GET `/admin/fp-source-routes`，PUT/DELETE `/admin/fp-source-routes/{route}` | Q8 来源路由 CRUD（operations；越权 403，Q75 补闸；被维度引用 → 409；**Q109 起 GET 同补 operations query 读闸**） | Q8/Q75/**Q109** |
| POST/GET `/product-spaces/{product_space_id}/field-pools`（+ `/current`） | 方案提交（一品一池；违规落 violations 仍 pending_gate）/查当前池 | PT-FP-PLAN |
| POST `/field-pools/{pool_id}/gate` | WF-02 HumanGate（product_reviewer；非合规批 → 409） | Q9/Q11/Q12 |
| POST `/field-pools/{pool_id}/dimensions/{dimension_id}/restore` | 备选档捞回（满 8 挤回最低置信） | Q12 |
| GET `/admin/g2-candidates`，POST `/admin/g2-candidates/{candidate_id}/promote` | 候选列表 / Q13 转正（dictionary_admin；fid 冲突/重复转正 → 409，转正回填池维度） | Q13/Q68 |

**M4 段4 原子拓展（前缀 `/api`）**

| 方法/路径 | 说明 | 依据 |
|---|---|---|
| GET/POST `/admin/compliance-wordlist`，PUT/DELETE `/admin/compliance-wordlist/{entry_id}` | Q48 统一词表 CRUD（operations/internal_compliance；downgrade 缺目标 422；DELETE=软归档；段 5/10 后续同表读取；**Q109 起 GET 同补 operations/internal_compliance query 读闸**——platform_admin 不在内、403） | Q48/Q51/**Q109** |
| POST `/product-spaces/{product_space_id}/atom-batches` | WF-03 候选批次（仅产 candidate；池非 approved → 409；Q14 超限 422 可覆盖；Q15 AI 达标 409、manual 放行；同批去重/维度归属 422；事实原子跨产品撞值 409）；响应内嵌 AtomConflict | Q14/Q15/PT-ATOM-EXP/line 11189 |
| GET `/product-spaces/{product_space_id}/atom-candidates`、`/atoms` | 候选列表（可按 status）/正式原子列表 | — |
| POST `/atom-candidates/{id}/approve`、POST `/atom-candidates/batch-approve` | approveAtomGuard（product_reviewer；违规码数组 409；high/critical 批量 409，Q70） | line 2633/Q70 |
| POST `/atom-candidates/{id}/reject` `/evidence` `/revive` | 驳回（critical 禁用表达记合规审计动作）/ 补证据（解 evidence_required）/ 仅 evidence_timeout 驳回复活（**revive 有意不设角色闸**，前置状态即闸，Q75） | Q18/Q75/line 840 |
| POST `/atom-clusters/{cluster_id}/resolve` | Q19 同义簇人工终裁 keeper，非 keeper 置 merged 为 alias | Q19 |
| POST `/atom-candidates/{id}/risk-override` | 人工复核改判（词表强制定级 409 不可改；AI 判级可改并重建冲突集） | Q17 |
| POST `/atoms/{id}/freeze` `/unfreeze` `/compliance-suspend` `/compliance-resume` `/deprecate` `/archive` `/reject` | atom8 生命周期：freeze/unfreeze/deprecate/archive=operations（解冻不重审、废弃不原地复活）；suspend/resume=internal_compliance；reject=product_reviewer | Q20 |
| POST `/admin/atom-evidence/sweep`（**未开 HTTP**） | Q18 超时扫描已实现为服务函数 `sweep_evidence_timeouts`，定时触发随 M10；当前仅测试/内部调用 | Q18 |

**M5 段5 PWC 条件包（前缀 `/api`）**

| 方法/路径 | 说明 | 依据 |
|---|---|---|
| GET/PUT `/admin/content-goals`，POST `/admin/content-goals/{code}/archive` | Q25 五类 contentGoals 字典（种子 ENGAGEMENT/CONVERSION/EDUCATION/TRUST/RETENTION；dictionary_admin；ratio_min≤ratio_max 否则 422；软归档；**Q118 起 GET 补 dictionary_admin query 读闸：缺 actor_id 422、越权 403**） | Q25/line 1090/**Q118** |
| GET/PUT `/product-spaces/{id}/pwc-pool-config` | Q27 库容配置（operations；默认 100，capacity=null 无上限；target_platforms/high_reuse_n） | Q27/Q24 |
| POST `/product-spaces/{id}/pwc/funnel` | WF-04 漏斗：预筛→Q48 合规检测（ban→blocked；手拼不豁免 Q26）→Q22 评分（AI 子分缺失不凑分）→限量 50；池非 approved 409；结构/跨租户/停用 goal 422；返回 PWC 视图数组 | Q21/Q22/Q23/Q26 |
| GET `/product-spaces/{id}/pwcs` | 条件包列表（score 降序 null 末位，含 combo 原子与合规/评分明细） | — |
| POST `/pwcs/{pwc_id}/gate` | HumanGate（product_reviewer；approve→ready 受库容 409；reject→archived；blocked 不可批 409） | Q21/Q27 |
| POST `/product-spaces/{id}/pwc/consume` | Q71 消费：score 降序取用，同平台+账号+发布位去重，跨平台可复用，goals 交集过滤；响应带 usage_record/platform_state/pool_ready_count/pool_health/restock_hint；无可取 409 | Q24/Q71 |
| POST `/pwcs/{pwc_id}/hot` `/archive` | Q61 爆款手工标/取消（operations；V1 无自动检测）；归档（operations） | Q61/Q24 |
| 冷却 sweep / 自动补货（**补货信号与自动消费均已实现，冷却 sweep 未开 HTTP**） | `sweep_cooldowns`（14 天到期回 available）已实现为服务函数；critical→target 自动补货=Q76-4 跌破 critical 经 5 分钟防抖落 `skill_runs(status=requested)`（consume 响应回带 `restock_run_id`），**Q87 起由 M8 restock worker 进程内自动消费**（见 §2.3 Q87 补登）；冷却 sweep 定时触发随 M10 | Q24/Q71/Q76/Q87 |

**M6 段6 PWS 冻结（前缀 `/api`）**

| 方法/路径 | 说明 | 依据 |
|---|---|---|
| GET `/product-spaces/{id}/pws/readiness` | pwsReadiness 5 项机械求值 + 计数明细（PS 不存在 404） | line 2634 |
| POST `/product-spaces/{id}/pws/evaluate` | 全绿时系统出 pws_ready 待办（whitelist_owner，7 天 due，幂等）；不全绿只回状态不出单（**有意不设角色闸**：系统提请的机械求值，Q75） | Q28/Q75 |
| POST `/product-spaces/{id}/pws/freeze` | BO-07 冻结/重冻（whitelist_owner；非属主 403；不全绿 409 回带 5 项）；首冻 v1.0 免原因，重冻须 reason_code（缺失/未知 422，none 档 409）；返回快照+items、dup_hints、Q30 dispositions | Q29/Q30/Q31/Q33/line 7674 |
| POST `/pws/{pws_id}/revoke` | Q32 急停（whitelist_owner；仅 active frozen 可作废，否则 409）；作废后可重冻新版 | Q32 |
| GET `/product-spaces/{id}/pws`、GET `/pws/{pws_id}` | 版本列表（主版本号倒序，同刻仅 1 active）/ 版本明细含物化 items；superseded/revoked 只读 | Q31 |

**M7 段10 合规清洗（前缀 `/api`）**

| 方法/路径 | 说明 | 依据 |
|---|---|---|
| GET/POST `/admin/cp-law-domains`，PUT/DELETE `/admin/cp-law-domains/{id}` | CP-LAW 敏感领域小表 CRUD（internal_compliance；code 唯一 409；DELETE=软归档；迁移种子 medical/children/weight_loss/whitening/medical_device/finance；**Q118 起 GET 补 internal_compliance query 读闸：缺 actor_id 422、越权 403**） | Q48/Q49/**Q118** |
| POST `/pws/{pws_id}/ccr/run` | WF-08 机械清洗（**internal_compliance 触发**，越权 403，Q75）：仅 active frozen 可跑（否则 409）；同源自 M4 词库按行业+市场取词，Q50 国家>平台>底座裁决（同级 Q36 从严）；ban→`blocked/block_required=true`、downgrade→`downgrade_pending` 只出建议、无命中→`clean`；敏感领域同事务幂等触发法审；报告 append-only | PT-COMPLIANCE/Q48-Q50/Q75 |
| GET `/pws/{pws_id}/ccr`、GET `/pws/{pws_id}/ccr/gate?country=` | 报告历史（新→旧，同秒按 id 兜底）/ 供段11 Guard②⑥ 消费的机械视图（block_required/cleaning_passed/law_review_passed） | Q53 |
| POST `/ccr/{ccr_id}/approve-downgrades` | 降级建议人工 approval（internal_compliance；仅 downgrade_pending 可批，否则 409）；批后 cleaning_passed | PT-COMPLIANCE |
| GET `/pws/{pws_id}/law-reviews`、POST `/law-reviews/{id}/decision` | 法审记录查询/线下律师结论录入（internal_compliance；approved/rejected，已决再判 409；通过放行 Guard⑥、不通过维持否决；同步开关法审待办） | Q49 |
| GET `/compliance/overview?tenant_id=` | 客户合规风控页租户只读聚合（Q101，**无角色闸、无 body、不 writeAudit**）：该租户 active frozen PWS 一行一产品；每市场（country=None=底座）取最新一行 CCR，行结论跨市场从严（blocked>downgrade_pending>approved>clean），block_required OR；附单条 LawReview 视图；无报告/无法审分别 null；未知租户 200 `{"items":[]}`，读路径不触发 Q95 准入门；tenant_id 缺/空 422 | Q101 |
| Q51 生效即扫（**无独立端点**） | 词表 POST/PUT 保存生效即在同事务扫描全部 active frozen 快照（按行业过滤），命中产出 `wordlist_rescan` 待办（whitelist_owner，detail.reason_code=wordlist_hit，开放待办幂等），响应附 `q51_impacted`；重冻新版本仍须 BO-07 人工执行；定时扫未来生效词条随 M10 | Q51/Q29 |

**M11 段7/8 静态底表 + 段9 三包（前缀 `/api`，实现序先于 M8：段11 七 Guard 需要静态 PCP/三包实例）**

| 方法/路径 | 说明 | 依据 |
|---|---|---|
| GET/POST `/admin/publish-slots`，PUT/DELETE `/admin/publish-slots/{slot_id}` | 发布位档案 CRUD（operations；code 唯一 409；四维分 score_source=manual_eval + source_url；DELETE=软归档；**Q118 起 GET 补 operations query 读闸**）；**`gate` V1 恒人工直编 `approved`**（Q118 裁决：无 pending_gate 产生路径/无 Gate 翻转端点，AI 拓展候选审核流随段7 完整版/V2，见 13 §1.9）；**无平台目录种子（line 1098-1221 原文【待补】）** | Q35/**Q118**/line 1098 |
| GET `/admin/publish-slots/{slot_id}/fit-score?goal=` | Q34 派生值（不落库）：Σ 四维分×目的权重；目的未配权重 → fit_score=null/incomplete=true，不凑分 | Q34 |
| GET/PUT `/admin/fit-weights` | 目的权重矩阵（operations；4 维齐 + Σ=1 硬校验 422，不归一化；goal 须活跃 content_goals 否则 404；种子 ENGAGEMENT/CONVERSION；**Q109 起 GET 同补 operations query 读闸**） | Q34/**Q109** |
| GET/POST `/admin/platform-rules`，DELETE `/admin/platform-rules/{rule_id}`，GET `/admin/platform-rules/match` | 4 层 selector + country 横切；层级必填字段 422、effect 仅 blocked/partial；同级同条件异结论保存 → 409 回冲突行，`overwrite=true` 重发归档旧行；match=高优先级层级覆盖、同级从严；native 默认不存 | Q36/line 1383 |
| GET/PUT `/admin/slot-type-defaults` | slotType 默认值（operations；min>max 422；约 40 列走 defaults JSON，明细【待补】；**Q118 起 GET 补 operations query 读闸**） | line 1428/**Q118** |
| GET `/admin/pcp-templates` | Q39 四模板只读（种子 short_video/community/photo_text/ecommerce，17 键 Σ=1.0；实现期初值草稿） | Q39 |
| GET/POST `/product-spaces/{id}/pcp`，PUT `/pcp/{pcp_id}` | PCP 实例（operations；PS 不存在 404；模板派生或显式 weights，17 键 Σ≤1.0 统一校验器 422；同 PS×平台 active 唯一 409；PUT 为 Q42 人工直编通道，清空 template_code + before/after 审计） | Q40/Q42/Q52/PT-PCP-V1.5 |
| GET/POST `/product-spaces/{id}/packages`，PUT/DELETE `/packages/{package_id}` | 段9 CSP/CSTP/CEP 静态实例（operations；payload 键按 04 §2.17 定死，缺/多键 422；产品×平台×目的×包型 active 唯一 409；goal 须活跃；DELETE=软归档；行带 tenant/PS 供段11 Guard④⑤） | Q45/Q52/line 863 |

**M8 段11 FCW 组装（前缀 `/api`，E1.1 publishFCW = final_id 唯一出口，line 11036）**

| 方法/路径 | 说明 | 依据 |
|---|---|---|
| POST `/fcw/assemble` | 手动单条发证（operations；body 指定 PS/pws_id(缺省取 active 版)/platform/slot_id/goal/country）：机械解析六路材料→7 项 Guard，全绿 mint final_id 直接 published；任一 Guard 败 → 409 回带逐项 guards（不生成 final_id，失败尝试仍 writeAudit `fcw.assembly_blocked` 并提交）；材料缺失 409、slot/平台不符 422、goal 未知 404、重复发证 409；**Q203：需 `Authorization: Bearer <loom_staff_…>`，无令牌 401、令牌无 operations 403，body 自报 `actor` 不再算身份** | PT-FCW-ASM/Q52/Q53/Q55 |
| POST `/fcw/assembly-tasks` | Q55 任务驱动批量（operations；product×platform×goal×count，可选 slot_ids 长度须=count 且不重复否则 422）：同步逐条组装，不给 slot_ids 时取该平台 active 发布位前 N；单项失败（Guard/材料/去重）不阻断其余，任务 completed，results 留痕 issued/failures 每条原因；每条发证 writeAudit `fcw.issued`（六路材料+Guard 结果+E1_owner=publishFCW），任务另记 `fcw.assembly_task`；**Q203：需 `Authorization: Bearer <loom_staff_…>`，无令牌 401、令牌无 operations 403，body 自报 `actor` 不再算身份** | Q55 |
| GET `/fcw/assembly-tasks/{task_id}` | 任务结果（不存在 404） | Q55 |
| GET `/product-spaces/{id}/fcw`、GET `/fcw/{final_id}` | 成品列表（新→旧）/单条明细（含 guards 明细、score/score_detail/incomplete） | line 870 |
| GET `/exports/fcw.csv` | M12 中台导出（Q100）：同步流式 CSV，**仅 final_id 单列**（含表头），query tenant_id 必填（空 422）、product_space_id 可选收窄；只导 published、created_at DESC；读路径不触发 Q95 准入门，未知租户 200 仅表头；`Content-Disposition: attachment; filename="fcw-<tenant>.csv"` | Q100/D4 |
| GET `/exports/fcw.json` | M12 中台导出 JSON 形态（Q132）：query/口径同 fcw.csv，响应 attachment JSON `{tenant_id, product_space_id, count, total, limit, offset, has_more, final_ids[]}`，未知租户空 envelope 200；**Q142 起 fcw.csv/fcw.json 均支持 `limit`(1..硬上限)/`offset` query，limit 超 env `LOOM_EXPORT_MAX_ROWS`(默认 10 万) 或 offset<0 返 422，CSV 分页走 `X-Export-Total/Limit/Offset/Has-More/Truncated` 响应头** | Q132·Q142/D4 |
| GET `/fcw/{final_id}/material.json` | 台内白名单卡片 **6 层原料包全量 JSON**（Q155）：按 final_id 反解析六路，产 schema `loom.fcw.material-pack.v1`（issued 头 + product/platform/strategy/structure/expression/compliance 六层 + guards + warnings），attachment `fcw-material-<final_id>.json`；只读、无 RBAC 闸、不触发 Guard、不写审计、未知 404，引用行物理缺失回 `{_ref,available:false}` + warning 不 500；**不属中台 /api/exports 的 final_id-only 面**（Q100/Q132/Q142 分界，6 层包属台内卡片详情/复制口径，09:87）；前端卡片随 D3.5 菜单点工 | Q155/09:87 |
| POST `/exports/jobs` | M12 异步导出任务（Q132，V1 请求内同步执行置 completed）：body {tenant_id, product_space_id?, format=csv\|json, actor}，201 任务视图含 download_url（**Q196 起该 URL 自带 `tenant_id`**）；审计 export.job_created；空 tenant/非法 format/缺 actor 422 | Q132/D4 |
| GET `/exports/jobs/{job_id}` | 导出任务状态查询：~~V2 真异步后供轮询~~ **异步 worker 已随 Q137 落地**（env 门控默认关，关时请求内同步到终态）；**Q196 起 `tenant_id` 必填、任务须属该租户，跨租户与不存在同回 404**（不做存在性探针） | Q132/Q137/Q196·D4 |
| GET `/exports/jobs/{job_id}/download` | 按任务参数重渲染下载（未知 404、failed 409 回带 error、**queued/running 409 not ready**；幂等反映当前 published 集合，不存文件 payload；**Q196 起同状态口 `tenant_id` 必填并按任务行归属收口**；`job_id` 改 `uuid4`，旧 uuid1 含时钟与节点分量可推算、不宜独担授权凭证） | Q132/Q137/Q196·D4 |

> Guard 七项 code：`g1_pws_frozen`（PWS status=frozen）/`g2_compliance_clear`（block_required=false **且** cleaning_passed=true，无报告不放行【实现补】）/`g3_packages_active`（PCP active + CSP/CSTP/CEP active 且 gate=approved）/`g4_product_space_consistent`（六路 PS 一致）/`g5_tenant_consistent`（六路 tenant 一致）/`g6_law_review`（仅法审被触发时要求 approved，Q49）/`g7_pws_active_version`（is_active=true）。Q54 score（pwc×100×0.4 + fit×0.3 + 三包 conf 均值×100×0.3）仅排序，缺失即 null/incomplete=true，永不做门槛。draft publish_status V1 无创建入口；WF-09 AI Skill 随 V2。

**M10 切片 a · 配置中心**（2026-09-14，迁移 0010，路由前缀 `/api/admin/config`）

| 方法/路径 | 说明 | 依据 |
|---|---|---|
| GET `` （`?category=` 可过滤） | 配置项列表（key/category/value/value_type/validation/source_ref/version/时间）；只读，**platform_admin（Q113 补闸，与写口同组）** | 02 §C2 / 07 §2.4 |
| GET `/{key}` / GET `/{key}/history` | 单项（未知键 404）/版本历史（新→旧，种子为 v1）；**platform_admin（Q113 补闸）** | 14 §2.4 |
| PUT `/{key}` | 改值发布（仅 `platform_admin`【实现补：07 §2.3 平台级管理员 Q46/Q64 的英文角色码】；body=value/change_note/actor）：类型+min/max/choices 校验失败 422、未知键 404、越权 403；发布=coerce→value/version+1→写版本行→writeAudit(`config.update`)→事务提交后进程内快照原子切换 | 14 §2.4 |
| POST `/{key}/rollback` | 回滚到历史版本（platform_admin；target_version 不存在 404）：以新版本号重发该值（非覆盖历史），默认 change_note `rollback to vN`，writeAudit(`config.rollback`) | 14 §2.4 |

> 发布语义严格按 14 §2.4：新版本 + 原子切换 + writeAudit；快照切换挂在 SQLAlchemy `after_commit`，事务回滚/校验失败不触缓存（已测试）。V1 单进程模块化单体，仅做进程内热更新；多副本变更广播（Redis pub/sub）【挂账，多副本部署前补】。进程启动加载与业务常量消费已在切片 c 接通（见下）。

**M10 切片 c · 缓存引导 + 常量迁移**（2026-09-14，无新表/无新端点/无迁移）

> 消费侧统一入口 `knob(key)`（`app/core/config_center/knobs.py`）：读进程内 `config_cache`，缓存未引导或键缺失时回落种子表拍板值（`SEED_BY_KEY` 为默认值唯一事实源）。M1–M8 拍板值全部由代码常量迁为零参访问器函数：c1 冷启动 0.6/TopGap 0.1/ops 72h、c7 L3 覆盖 0.6、fieldpool 0.85/0.9/3–8/15–30（请求契约默认值走 `Field(default_factory=...)` 按请求取值）、atom 20·50/0.5/7 天、pwc 50/100·70·50/5min/100/0.6·0.4/0.5·0.5/1.0/0.8/7·3·14、pws 3·1/7 天、ccr 48h、sla 黄 24h、fcw 0.4·0.3·0.3；状态字符串/原因码映射等非标量规则不动。纯函数权重入参缺省为 `None` 并在函数内解析，显式传值仍覆盖（测试/未来分行业配置）。启动引导：lifespan 在调度器启动前以独立会话全量 reload；失败仅告警不阻断启动（knob 回落种子值）。发布后的热更路径不变（切片 a after_commit apply），故运营改值对所有规则访问器即时生效、无需重启。

**M10 切片 b · 通用 SLA 引擎 + 定时调度**（2026-09-14，无新表/迁移 0011 仅加列）

| 方法/路径 | 说明 | 依据 |
|---|---|---|
| POST `/sla/run` | 手工触发全部 sweep 作业（**platform_admin**，body 带 actor，越权 403；Q75）：①待办到期升级（所有 open ops_todo 过 due_at→escalated，按类型写审计）②Q18 证据超时自动驳回 ③Q24 冷却到期回 available ④Q51 未来生效词条到点激活并补扫；每作业独立会话/提交，单作业失败回滚不阻断其余，响应回带每作业 `{changed}` 或 `{error}`；**Q89 起与定时调度抢同一把 Redis leader 锁 `loom:lock:sla-sweep`，锁被占 409、锁后端故障 503**（`LOOM_DISTRIBUTED_LOCK_ENABLED` 默认关） | Q49/Q18/Q24/Q51/Q75/Q89 |
| GET `/sla/todos?status=open\|escalated\|resolved\|all` | 待办 SLA 看板（跨租户、不分页、due_at 升序），派生 `sla_state`：green/yellow/red/resolved（黄色仅法审 created_at+24h，其余类型黄色口径【原文未给出，待补】）。**Q108 起**：query actor_id 必填（缺参 422）+重复 roles，require_sla_view 仅放行 **platform_admin**（operations/internal_compliance/customer 均 403）；status 白名单恰 4 值，非法 422 `unknown todo status: {status}`，默认 open。Q108 前该端点为 M10b 裸端点无鉴权 | Q49/Q70/**Q108** |

> 定时调度：FastAPI lifespan 内 asyncio 循环，默认 300s 一轮（`LOOM_SWEEP_INTERVAL_SECONDS`、`LOOM_SCHEDULER_ENABLED=false` 可关）；多副本部署以 Redis leader 锁保证单实例 tick（**Q89 已落地**：`LOOM_DISTRIBUTED_LOCK_ENABLED` 默认关，开启后非持锁副本跳过该轮、锁后端故障 fail-closed 跳过；看门狗 TTL/3 续约）。法审黄色小时数读配置中心 `sla.yellow_hours`（种子 24，缓存未引导时回退默认）——首个配置中心消费方。Q71 critical→target 自动补货（5 分钟防抖）仍未实现：V1 无 skill7 AI 漏斗可调用，挂 skill7 切片，不构造虚拟候选。**RBAC 收口已于切片 d 完成（Q75）**：`/sla/run` 与 `/admin/ops-todos/sweep` 手工触发归 platform_admin；其余端点级角色映射见切片 d 小节。

> **Q108 补登（2026-09-16，M12 第六片——裸看板端点补闸 + 管理端只读页；无新端点/无新写口/无迁移）**：M10b 落地的 `GET /api/admin/sla/todos` 自切片 d 起仍为**无鉴权裸端点**（Q75 补闸矩阵只收 POST /run），Q108 补 require_sla_view query 依赖——actor_id 必填（缺参 422）+重复 roles，require_any_role 仅 PLATFORM_ADMIN，operations/internal_compliance/customer 全 403；status 由原 open|all 两值扩为白名单 {open,escalated,resolved,all}，非法 422 `unknown todo status: {status}`，默认 open；不分页、due_at ASC 与返回字段集（含 sla_state）不变，sla_state 派生仍走 `core/sla/policies.py`。POST /run 的 body 内闸与 409/503 口径不动。前端新页 `/[locale]/admin/sla-todos` 纯只读 RSC（GET 表单四筛选、9 列、枚举码原样、sla_state 四色 chip、yellowNote 如实声明"黄色仅法审、其他类型黄口径【待补】"），写口 /sla/run 不上页面。测试 421 全绿（+3 集成），eval 不受影响。

**M10 切片 d · RBAC 红线收口**（2026-09-14，无新表/无新端点；Q75 销账）

> 统一入口 `app/core/rbac`：角色常量（operations/product_reviewer/dictionary_admin/internal_compliance/whitelist_owner/platform_admin）+ `require_any_role(actor, *roles)` + 单一 `PermissionDenied`（路由统一映射 403）。闸放服务层；定时调度等系统内部调用不经 HTTP、不经角色闸。

> **Q178 补登（2026-09-24，身份层 P0-① 第一切片·甲案内部运营 PAT，迁移 0040_staff_api_keys，02 C1.122）**：在 Q88 机器 Agent Key 之外新增内部运营**人员**令牌（`loom_staff_` 前缀、新表 `staff_api_keys`、新横切包 `app/core/staff_auth/`，业务物理表 61→62）。**认证与授权分离、端点签名零改动**：认证＝app 级全局依赖 `staff_auth_context`（门控 env `LOOM_STAFF_AUTH_ENABLED` 默认关；开则仅验 `loom_staff_` Bearer 并把人员 Actor 写入请求级 contextvar，无令牌/机器 `loom_` 前缀/客户口/公开口直接放行，坏或吊销 staff 令牌 401）；授权仍统一在 `app/core/rbac`——`require_any_role` 新增 `NotAuthenticated`(401)/`PermissionDenied`(403) 两异常（main 注册全局 handler），门控开且要求内部角色时：contextvar 无人 401、角色不足 403、通过则**就地把传入 actor.id/actor.roles 覆盖为令牌身份**（审计落真实人员，query/body 自报提权失效）；门控关或仅要求 whitelist_owner 的客户口维持 V1 自报。新增端点 `POST/GET /api/admin/staff-keys`、`POST /api/admin/staff-keys/{key_id}/revoke`（platform_admin 红线）、`GET /api/auth/me`（门控关 400／开无令牌 401／有效回显 {staff_id,staff_name,roles}）；Q88/Q109 有意免闸的 agent-keys GET 门控开改挂新依赖 `internal_gate(platform_admin)`（门控关 no-op）。门控开时 actor_id query／body.actor 仍是必填 schema 形状（缺 422），其值被令牌覆盖。**首个 platform_admin 令牌须门控仍关时自报签发（引导），前端 /admin/login 录入后再开门控；关 env 即回滚至 V1 自报**。客户侧真实认证、actor↔tenant 绑定（Q88 待补口径）、账号密码/会话/注册（乙案）仍后置 V2，公网自助仍 NO-GO（Q144）。测试 817→**842 passed**＋9 skip（+25 集成 `tests/integration/test_staff_auth_api.py`，StaticPool 内存 sqlite 共享认证/业务两 session），ruff 净，迁移 0040 经 pg16 容器 up/downgrade-1/up 实测。端点字段明细见 docs/11 §2.4，env/引导顺序/回滚见 docs/17。
> 新增/补闸矩阵：①`POST /api/admin/sla/run`、`POST /api/admin/ops-todos/sweep` → **platform_admin**（Q75 新裁决；sla/run 请求体新增 `actor`）；②`POST /categories`、`PUT /categories/{id}/template` → **dictionary_admin**（Q75；CategoryCreate 请求体新增 `actor`）；③`POST /pws/{id}/ccr/run` → **internal_compliance**（Q75）；④补闸既有裁决：信号权重 PUT、行业阈值 CRUD = operations（Q2/Q7），来源路由 PUT/DELETE = operations（Q8）；⑤`POST /api/admin/restock/run` → **platform_admin**（Q87，手工触发一轮补货，同 Q75 sla/run 口径；Q89 起与定时 worker 抢 `loom:lock:restock-worker`，409/503 同 sla/run；Q90 起手工触发绕过瞬态退避窗口，但瞬态结果仍累加 attempts 并重排窗口）。
> **有意开放、不加闸**（Q75 第 4 条，实现补登）：`POST /pws/{id}/pws/evaluate`（Q28"系统提请"——机械求值 + 幂等出单，非人工决策）、`POST /atom-candidates/{id}/revive`（仅 evidence_timeout 驳回可复活，前置状态即闸）。
> 既有各模块服务内 `RoleNotAllowed`（config_center/whitelist_center/compliance_center 等）保持不动，本次只收口红线，不做全库异常类合并；统一 403 口径不变。

> **Q109 补登（2026-09-16，M12 第七片——管理面读端点鉴权审计 + 同型补闸；无新端点/无新写口/无迁移，前端零改动）**：对全部 `/api/admin` GET 穷举审计后，8 个表行把 GET 与写口同组标注角色、但 Q75 矩阵方法枚举只收写口的裸读口，统一补 query actor 依赖（actor_id 必填缺参 422、重复 roles、require_any_role 不符 403；口径同 Q92/Q108）：①c1/signal-weights ②c1/industries = operations；③/categories（无 /admin 前缀）= dictionary_admin；④fp-source-routes ⑤fit-weights = operations；⑥compliance-wordlist = operations/internal_compliance（platform_admin 不在内）；⑦ai-models = platform_admin；⑧ai-scene-routes = operations|platform_admin。**矩阵未定读角色，保持开放并挂【原文未给出，待补】**：~~config 三读口（``、`/{key}`、`/{key}/history`）、g2-candidates、skill-prompts 三读口（指针/版本历史/单版本）~~ **已于 Q113（2026-09-17，02 C1.57）收口补闸，见下条补登**。**矩阵明确有意开放、测试锁定**：agent-keys 列表（"GET 无 actor 体（同 outbound Key 列表口径）"）与 ai-models/{id}/keys（仅元数据）；fcw.csv Q100 tenant_id 隔离不在列。系统内部（CCR/建模等）读词表/权重/路由均走服务层不经 HTTP，闸不影响内部调用；前端全仓确认无这 8 个端点消费方。444 测试（+23），见 02 C1.53、08 Q109。

> **Q113 补登（2026-09-17，M12 第八片——Q109 挂账三族管理面读口补闸收口；无新端点/无新写口/无迁移，前端零改动）**：负责人"按你的来，狠狠的搞完"授权按推荐方案收口 Q109 挂【待补】的三族 7 个读口，角色全部溯自已落地矩阵表行/写口同组，不新增业务口径：①config 三 GET（``、`/{key}`、`/{key}/history`）= **platform_admin**（写口 PUT/rollback 本表配置中心节明确 platform_admin，配置含 SLA 时限/各域阈值，同 ai-models 先例）；②g2-candidates 列表 = **dictionary_admin**（本表 GET 与 promote 同行同角色 Q13/Q68，与 /categories 同型）；③skill-prompts 三 GET（指针/版本历史/单版本）= **platform_admin**（发布写口本表 = platform_admin，单版本含 template+variables 全文，同 ai-models 平台级敏感口径）。实现同 Q109：3 路由各加本地 query actor 依赖（`require_config_view`/`require_g2_candidates_view`/`require_prompts_view`），处理器末位 `_: Actor = Depends(...)`、函数体零改动，写口 body actor 服务层闸不动；agent-keys 与 ai-models/{id}/keys 仍有意免闸、测试继续锁定。三族前端全仓 grep 零消费。455 测试（445+10），见 02 C1.57、08 Q113。

> **Q118 补登（2026-09-18，Q117 挂账四项收口；纯加固 + 一迁移，前端零改动）**：负责人「一口气开搞」对 Q117 挂账 4 项均按推荐（甲）拍板（02 C1.62）。**(1) Q109 穷举遗漏的 4 个管理面 GET 同型补 query actor 闸**（缺 actor_id 422、角色不符 403、命中 200；写口 body actor 服务层闸不动；角色溯自已落地表行/写口同组，不新增口径；四端点前端零消费）：①`GET /admin/content-goals`=**dictionary_admin**（`require_content_goals_view`）；②`GET /admin/cp-law-domains`=**internal_compliance**（`require_law_domains_view`）；③`GET /admin/publish-slots`、④`GET /admin/slot-type-defaults`=**operations**（platform_adaptation 原 `require_fit_weights_view` 重构为通用 `require_operations_view`，fit-weights/publish-slots/slot-type-defaults 三读口共用）。**(2) publish_slots.gate 口径回填**：V1 仅 Q42 人工直编，`gate` 默认 `approved`（模型列与 SlotUpsert 双默认，集成测试锁定）；无 slot_items 表、无 pending_gate 产生路径、无 Gate 翻转端点（`pa_rules.GATE_PENDING` 为 V2 预留常量零引用）；13 §1.9 的 pending_gate→approved AI 拓展审核流整体随段7 完整版/V2。**(3)** product_spaces 两软引用补 DB 级 FK（迁移 0027，见 docs/10）。**(4)** CI frontend 六 checker→七（check-settings 接入，见 docs/17 与 ci.yml）。另修复审计外发现：Alembic 版本表 version_num 默认 VARCHAR(32) 容纳不下 0021 起 33 字符的 revision id，全新 PG 全链在 0021 截断；env.py 迁移前幂等预置/加宽至 VARCHAR(128)。483 测试（472+11）、ruff 净、eval 101/101、迁移头 0027，见 02 C1.62。

**M10 切片 e · skill7 AI 候选通道（WF-04 试点；WF-02 字段池 Q78、WF-01 冷启动识别 Q79、WF-03 原子批次 Q80、WF-01 C7 Layer4 Q81 为复用切片）**（2026-09-14，迁移 0012 + 0013，Q76/Q78/Q79/Q80/Q81；路由前缀 `/api`）

| 方法/路径 | 说明 | 依据 |
|---|---|---|
| POST `/skill-runs` | AI 产出外部投递（**operations**，越权 403；入站机器对机器 API Key 通道仍【待补】，Q82 真 LLM 走向见切片 f 的进程内系统 Actor 投递）：body=skill_id/wf_id(可省，按注册表推导)/**锚点二选一 product_space_id 或 intake_id（Q79-4，必给且仅给一个）**/input/output/candidates[{target_type,payload}]/confidence/tokens/actor；未注册 Skill 或 Skill 不属该 WF → 422，锚点实体不存在 404（PS/intake）；**投递校验按 WF 步骤声明泛化（Q78/Q79）**：非候选产出步骤带候选 422、target_type 与声明 `candidate_target` 不符 422、payload 不符该 target 既有契约 422、步骤声明 `single_candidate: true` 时必须整结果单候选否则 422、**锚点与 WF 归属不符（c1_recognition/c7_layer4 必须 intake 锚点；pwc_combo/field_plan/atom_batch 必须 PS 锚点）422**；写不可变 `skill_runs(status=succeeded,source=delivery)` + 每候选 `skill_candidates(pending_review)`，两表按锚点回填 product_space_id/intake_id 之一，writeAudit `skill7.run_delivered`（detail.anchor=intake/product_space） | Q76-1/2/5，Q78，Q79-4，06 §4 |
| GET `/skill-runs`（`?product_space_id=&intake_id=&status=`）/ GET `/skill-runs/{run_id}` | 运行日志查询（无更新/删除端点；历史不可 mutate，PT-COMPLIANCE）；不存在 404；视图含 intake_id | 06 §4.3 |
| GET `/skill-candidates`（`?product_space_id=&intake_id=&state=`） | 候选列表；视图含 intake_id | 05 §2.3 |
| POST `/skill-candidates/{id}/decision` | 人工裁决（角色取 WF 定义 skill7 Gate 插槽；WF-02/WF-03/WF-04=**product_reviewer**（Q80-2），**WF-01=operations（Q79-3/Q81-3，WF-01 两道 Gate 同角色）**）：confirmed→适配器按 `target_type` 落库（**`pwc_combo` 经既有 `pwc/funnel`(source=ai)；`field_plan`（Q78）经既有 `fieldpool.submit_plan` 落 pending_gate，PT-FP-PLAN/Q8/Q9/Q10/Q12 全不绕过，再过 WF-02 端点 Gate；`c1_recognition`（Q79）经既有 `modeling.submit_recognition`，Q1 三分支机械逻辑一字不改（direct_approve→auto_confirm submitted / ops_assist→pending_confirm+72h OpsTodo / cold_start→需 category_pending_id 转 category_creating）；`atom_batch`（Q80）经既有 `atom.submit_batch`（通道强制 source=ai），Q14 批次上限/Q15 达标停拓/同批去重/维度归属/line 11189 事实唯一/Q17 双轨/line 840 冲突/PT-ATOM-EXP 空证据降级全不绕过，入库后逐条 approveAtomGuard·Q70·Q18·Q19 Gate 原样保留**；`c7_layer4`（Q81）经既有 `modeling.resolve_c7`，Q6 覆盖率 0.6 地板/L1 缓存/L2 approved 兄弟继承/Q68 fid:'-' 闸全不绕过，实际落 L1/2/3 时 l4_proposals 自然不生效，落 L4 才写 g2_field_candidates(pending_gate) 并继续走段3 Q13 dictionary_admin 转正**）置 applied+applied_refs（c1_recognition 回填 C1Record.record_id，atom_batch 回填 AtomBatch.batch_id，c7_layer4 回填 C7Run.run_id）；modified 必带替换 payload（按该 target 契约校验，422）、human_modified=true 后同样 apply；rejected→archived；非 pending_review 409；不存在 404；适配器业务错误沿用各业务端口径 404/409/422（field_plan：ProductSpaceNotFound 404 / GateNotAllowed 409 / InvalidPlan 422；c1_recognition：IntakeNotFound 404 / RecognitionNotAllowed 409 / ConfigError·InvalidDecision 422；atom_batch：ProductSpaceNotFound·PoolNotFound 404 / PoolNotApproved·TargetReached·FactAtomConflict 409 / InvalidBatch 422；c7_layer4：IntakeNotFound·CategoryNotFound 404 / IllegalFid·InvalidDecision 422）；适配器失败回滚事务，候选留 pending_review 可重裁；writeAudit `skill7.candidate_applied/rejected` | Q76-3，Q78，Q79-1/2/3，Q80-1/2/3，Q81-1/2/3，05 §2.3 |

> 补货（Q71/Q76-4）：`POST .../pwc/consume` 致待用数跌破 critical 时，按 `pwc.restock_cooldown_minutes`（5min）防抖创建 `skill_runs(status=requested,source=restock_auto,created_by=system)`，**只记 run 不产候选**；响应新增 `restock_run_id`（防抖期内为 null）。外部投递迟到产出后正常走 pending_review。
> 注册表：`runtime/workflows/WF-04.yaml`（顺序 Skill + 2 个 Gate 插槽）与 `runtime/skills/{PWC-BUILDER,COMBO-VALIDATE,PWC-SCORING}/skill.yaml`；**WF-02 替换切片（Q78）**`runtime/workflows/WF-02.yaml`（FIELDPOOL-PLAN→DIM-SOURCE→DIM-MERGE，DIM-MERGE 步骤 `produces_candidates: true, candidate_target: field_plan, single_candidate: true`，skill7+fieldpool 双 Gate 插槽）与 `runtime/skills/{FIELDPOOL-PLAN,DIM-SOURCE,DIM-MERGE}/skill.yaml`；**WF-01 替换切片（Q79 C1 识别 + Q81 C7 Layer4）**`runtime/workflows/WF-01.yaml`（PARSE→UNDERSTAND→CAT-RECOG→TYPE-MATCH→MISSING-INFO→RISK-TAG，**两个候选产出步骤**：CAT-RECOG `candidate_target: c1_recognition, single_candidate: true`、TYPE-MATCH `candidate_target: c7_layer4, single_candidate: true`，CAT-RECOG 后与 TYPE-MATCH 后各一个 skill7 Gate 插槽，role 均为 operations；MISSING-INFO 非产出步骤）与六张 `runtime/skills/<skill>/skill.yaml`（均 06 §4.1 的 10 字段；原文称 11 字段但逐项列出 10 项，按 10 项实现不擅补；model_tier V1 为空串、cost_limit 为 null）；**WF-03 替换切片（Q80）**`runtime/workflows/WF-03.yaml`（ATOM-EXPAND→ATOM-CANON→ATOM-AFFINITY→CONFLICT-PRECHECK，**末步 CONFLICT-PRECHECK** 声明 `produces_candidates: true, candidate_target: atom_batch, single_candidate: true`，末步后单个 skill7 Gate 插槽 role=product_reviewer）与四张 `runtime/skills/{ATOM-EXPAND,ATOM-CANON,ATOM-AFFINITY,CONFLICT-PRECHECK}/skill.yaml`；加载器 `app/core/skill7/registry.py`（`producer_step_for/candidate_target_for(wf,skill)` 供投递校验，`review_role(wf)` 供裁决角色），`LOOM_RUNTIME_DIR` 可覆盖路径。**仍挂账**：真 LLM 新字段生成体——Q82 已落地模型底座 + CAT-RECOG 试点、Q83 落地 PWC-BUILDER 第二站、Q84 落地 C7 Layer4 TYPE-MATCH 第三站、Q85 落地 WF-02 DIM-MERGE 字段池方案第四站、Q86 落地 WF-03 CONFLICT-PRECHECK（chat）+ ATOM-AFFINITY（embedding，非产出步骤不挂 Prompt）第五站（均见切片 f 内 Q83–Q86 补登），**五个真 LLM 站点已全部接通，Q67 站点 backlog 闭合**；**Q71 restock_auto 自动触发已由 Q87 M8 worker 闭环（2026-09-15）**；入站一 Agent 一 Key 通道随 Q60 回调切片；编排器并行/DAG 二期；多副本补货防抖/单实例 worker 锁随调度锁挂账 V2。

**M10 切片 f · 模型网关与 CAT-RECOG 真 LLM 试点（Q67/Q82）**（2026-09-14，迁移 0014；路由前缀 `/api`；表见 04 §2.24 / 10 §2.8）

*治理类（模型注册页，红线归 platform_admin；场景路由 operations\|platform_admin）*

| 方法与路径 | 契约 | 来源 |
|---|---|---|
| POST `/admin/ai-models` / GET `/admin/ai-models` | 建模：body=model_code(唯一)/provider/input_price_per_1m/output_price_per_1m(≥0)/currency_code(3 字符可空，币种【原文未给出，待补】)/daily_budget(可空)/fallback_model_id(创建时禁带，422)/actor；**platform_admin**，越权 403；重码 422；201 视图含 has_active_key。列表按 model_code 排序，带 has_active_key。**Q109 起 GET 补 platform_admin query 读闸（缺 actor_id 422/越权 403）** | Q67 / Q82 / **Q109** |
| PATCH `/admin/ai-models/{id}` | 改价/币种/日预算/status(active\|disabled)/fallback_model_id；自引用 fallback 422、目标不存在 422、模型不存在 404；platform_admin | Q82 |
| POST `/admin/ai-models/{id}/keys` | 录入/轮换 outbound Key：body=secret(min 8)/actor；platform_admin，模型 404；原子地把旧 active 行置 revoked 并插新密文行；201 仅回 key_id/fingerprint(末 4 位)/status，**明文/密文均不回显**；writeAudit `ai_model_key.rotate` | Q82-3 |
| GET `/admin/ai-models/{id}/keys` | Key 清单：仅 key_id/fingerprint/status/时间元数据 | Q82-3 |
| POST `/admin/ai-model-keys/{key_id}/revoke` | 吊销（body=actor；platform_admin；幂等，重复吊销不报错）；Key 404；writeAudit `ai_model_key.revoke` | Q82-3 |
| PUT `/admin/ai-scene-routes/{scene}` / GET `/admin/ai-scene-routes` | 场景键 = `skill_id`；body=model_id/actor，模型不存在 422；**operations\|platform_admin** 可改不动代码；writeAudit `ai_scene_route.update`。**Q109 起 GET 同补 operations\|platform_admin query 读闸** | Q67 / Q82 / **Q109** |
| POST `/admin/skill-prompts/{skill_id}/versions` | 发布 Prompt 新版本：template(非空)/change_note/variables/actor，platform_admin；首版 v0.1，之后 v0.N+1；同步移动 skill_prompts 指针，版本行 append-only；writeAudit `skill_prompt.publish` | Q82-4 |
| GET `/admin/skill-prompts` / GET `/admin/skill-prompts/{skill_id}/versions` / GET `.../versions/{version}` | 指针列表 / 版本历史（不含 template 全文）/ 单版本详情（含 template+variables）；单版本不存在 404；**三 GET 均 platform_admin（Q113 补闸，与发布写口同组）** | Q82-4 |
| POST `/admin/agent-keys` | **入站**一 Agent 一 Key 签发（**Q88**；body=name(1..128 非空白)/actor；platform_admin，越权 403、空名 422；201 视图含 key_id/key_prefix/status/created_at 与 **secret（明文仅本次返回，后台不可再读）**；writeAudit `agent_api_key.issue`；Key 不绑租户） | Q60 / Q88 |
| GET `/admin/agent-keys` | Key 列表：?include_revoked=false（默认仅 active）；视图仅 key_id/name/key_prefix/status/created_at/last_used_at，**永不含 secret/hash**；GET 无 actor 体（同 outbound Key 列表口径） | Q88 |
| POST `/admin/agent-keys/{key_id}/revoke` | 吊销（body=actor；platform_admin，越权 403；未知 key_id 404；幂等状态位 active→revoked + revoked_by/revoked_at，历史行 append-only 不物理删除，重复吊销不报错）；writeAudit `agent_api_key.revoke` | Q88 |

*试点触发（段2 CAT-RECOG）*

| 方法与路径 | 契约 | 来源 |
|---|---|---|
| POST `/intakes/{intake_id}/c1-recognition/llm-invoke` | body=actor；**operations**（越权 403）；intake 不存在 404；仅 `ai_recognizing` 状态可调，否则 409；无启用 C1 信号权重 422。进程内同步：场景路由→模型（disabled 且无 active fallback → 409，不静默换商）→日预算硬停（用尽 409）→渲染当前 Prompt 版本（缺 Prompt/变量 422）→驱动（provider=synthetic 走确定性替身；其余 OpenAI 兼容，base_url 只从 `LOOM_LLM_BASE_URL_<PROVIDER>` 注入，缺 active Key 422，上游/协议错误 502）→输出 JSON 校验（非 JSON/信号越权重名/分值越界/候选非启用类目 → 502 ExtractionOutputInvalid）。通过后以系统机器 Actor（`system:llm-gateway`, roles=[]，Q66 不授任何角色）走 skill7 同一投递：`skill_runs(source=llm_auto, model_id, tokens, input_cost, output_cost, currency_code)` + 整结果单候选 `skill_candidates(pending_review, c1_recognition)`，WF 声明校验/intake 锚点/适配器全复用。201 返回 run_id/source/model_id/tokens/candidates[{id,state,target_type}]。后续运营经 `/skill-candidates/{id}/decision` 裁决，confirmed/modified 才由 c1_recognition 适配器跑 Q1 三分支（line 同既有投递） | Q82-1/2 |

> 种子（迁移 0014，固定 uuid5）：`synthetic-deterministic`（provider=synthetic，价 0，无预算）模型 + CAT-RECOG→synthetic 路由 + CAT-RECOG Prompt v0.1（变量 product_profile/signal_keys/category_options）。仓库不含真实供应商凭证；真实 Key 只在部署环境经 `LOOM_MASTER_KEY` + 注册页录入，主密钥不入库不入仓，未设置时本地/测试退化为进程内临时密钥（告警，重启旧密文不可解）。

> **Q83 补登（2026-09-14，迁移 0015 纯种子）**：第二站 PWC-BUILDER 真 LLM——`POST /api/product-spaces/{product_space_id}/pwc/llm-build`（body=actor，**operations**，越权 403；PS 不存在 404；字段池非 approved 409；approved 原子不足跨 2 维度 409；Q71 restock_auto 不被自动消费）。进程内同步同 Q82 口径（disabled 无 fallback 409/预算硬停 409/缺 Key 422/上游坏 502）；输出校验：非 JSON 或 combos 非数组/空/超 Q21 批 50/atom_id 非本 PS approved/组合不足 2 维/goals 非 active → 502 PwcBuildOutputInvalid；模型回带的 logic_score/fit_score/weight 一律不透传（Q22b），同原子集重复组合机械去重。通过后每条组合一条 `skill_candidates(pending_review, pwc_combo, PS 锚点)`（步骤未声明 single_candidate），201 返回 run_id/source/model_id/tokens/candidates[]；product_reviewer 经既有 `/skill-candidates/{id}/decision` 逐候选裁决，confirmed 才由 pwc_combo 适配器跑 M5 漏斗（Q48/Q21/Q22/Q23/Q27/Q71 一项不绕，子分缺 → score_incomplete 人工 Gate）。种子：PWC-BUILDER→synthetic 路由 + Prompt v0.1（变量 approved_atoms/active_goals/capacity/ready_count/target_platforms/batch_limit）。

> **Q84 补登（2026-09-15，迁移 0016 纯种子）**：第三站 C7 Layer4 TYPE-MATCH 真 LLM——`POST /api/intakes/{intake_id}/c7/llm-resolve`（body=`{category_id, required_fids, actor}`，**operations**，越权 403；intake 不存在 404；仅 `ai_recognizing` 状态可调，否则 409；类目不存在 404、类目非 active 409；required_fids 含空串/`-` 按 Q68 在调模型前 422；不与 CAT-RECOG llm-invoke 自动串联）。进程内同步同 Q82 口径（disabled 无 fallback 409/预算硬停 409/缺 Key 422/上游坏 502）；输出校验：非 JSON、回显 category_id 不等于触发类目、required_fids 集合漂移、l4_proposals 非数组/field_name 空/批内重名/带 fid:'-' → 502 C7ResolveOutputInvalid；模型回带的 confidence/score/weight/fid/status/source_route 一律剥离（只透传 field_name 与非空 definition；source_route 枚举原文未给，v0.1 落 NULL），空 l4_proposals 合法。通过后整 C7 解析请求单候选 `skill_candidates(pending_review, c7_layer4, intake 锚点)`（WF 声明 single_candidate），201 返回 run_id/source/model_id/tokens/candidates[]；operations 经既有 `/skill-candidates/{id}/decision` 裁决，confirmed/modified 才由 c7_layer4 适配器跑 modeling.resolve_c7（Q6 四层兜底/Q68/L4 同名全局候选复用一项不绕，落 L1/2/3 提案不生效；L4 g2_field_candidates 仍 status=pending_gate 走 Q13 dictionary_admin 转正）。种子：TYPE-MATCH→synthetic 路由 + Prompt v0.1（变量 category/required_fids/own_template/sibling_summary/coverage_floor/g2_coverage）。

> **Q85 补登（2026-09-15，迁移 0017 纯种子）**：第四站 WF-02 字段池方案 DIM-MERGE 真 LLM——`POST /api/product-spaces/{product_space_id}/field-pools/llm-plan`（body=`{target_atom_min?, target_atom_max?, actor}`，缺省走 Q15 旋钮 15/30，**operations**，越权 403；PS 不存在 404；已有池且 gate≠rejected 409，与 `POST /field-pools` 同口径；min>max 409；调模型前闸不花 token；不自动串链）。场景键=DIM-MERGE（WF-02 唯一声明 field_plan 产出步骤，FIELDPOOL-PLAN/DIM-SOURCE 七路外部采集连接器属 V2）。进程内同步同 Q82 口径（disabled 无 fallback 409/预算硬停 409/缺 Key 422/上游坏 502）；输出校验：非 JSON、target_atom_min/max 未原样回传、dimensions 空或 >dim_max、field_name 空/批内重名、role∉{product_attribute, risk_control}、source_route 不在启用路由表、confidence 缺失/非数值/越界 [0,1]、source_ref 空白（line 14081 证据红线，只许引用 g2:/product_profile:/industry_tag: 有界来源）、fid 给值但非 active G2（含 Q68 '-'）、similarity 越界 → 502 FieldPlanOutputInvalid；模型多带的未知键不透传。**与 Q83/Q84 不同，dimension.confidence 是 PT-FP-PLAN 契约内 AI 字段（Q9 细看/Q12 Top8 依赖），0..1 校验后透传**；similarity/related_fid 可选透传（Q10 仅标记）。<3 维/缺 product_attribute/敏感缺 risk_control 等业务违规不 502，落非合规 pending_gate 池由人工终裁。通过后整方案单候选 `skill_candidates(pending_review, field_plan, PS 锚点)`，201 返回 run_id/source/model_id/tokens/candidates[]；product_reviewer 经 `/skill-candidates/{id}/decision` 裁决后才由 field_plan 适配器跑 fieldpool.submit_plan（PT-FP-PLAN/Q8/Q9/Q10/Q11/Q12/Q15/line 14081 一项不绕，fid 缺省维度建 wf02_dim_source 候选走 Q13 dictionary_admin 转正），非合规方案 WF-02 Gate 不可 approve。种子：DIM-MERGE→synthetic 路由 + Prompt v0.1（变量 product_profile/sensitive_industry/industry_tag/enabled_routes/active_g2_fields/dim_range/target_atom_range）。

> **Q86 补登（2026-09-15，迁移 0018——首个带 schema 变更的 LLM 切片）**：第五站（末站）WF-03 原子批量补池真 LLM，一次触发两次模型调用——`POST /api/product-spaces/{product_space_id}/atom-batches/llm-expand`（body=`{batch_size?, actor}`，缺省 Q14 敏感 20/非敏感 50，**operations**，越权 403）。花 token 前全量预闸：PS 不存在 404 → 字段池不存在 404（与手动批次同口径）→ gate≠approved 409 → 已通过+冻结正式原子数 ≥ target_atom_max 时 409 TargetReached（Q15 停拓仅约束 AI 批次，手动追加端点不变）；不自动串链（restock_auto 挂 M8 worker）。第一次=chat 场景 **CONFLICT-PRECHECK**（WF-03 唯一 `candidate_target: atom_batch, single_candidate: true` 步骤，Prompt 挂此 skill）；第二次=embedding 场景 **ATOM-AFFINITY**（`capability=embedding`，不挂 Prompt、不产候选；网关新 `embed(scene, texts)` 通道，路由模型能力不符 422）；只落 1 条 SkillRun（model_id=chat 模型，两次 input tokens/cost 求和，output 仅 chat 侧，embedding 模型身份记 run.input 的 embedding_scene/embedding_model_id）。输出契约：严格白名单 `{batch_size 必须原样回传, items:[{content, dimension_id, ai_risk, evidence?, fact_type?}]}`；结构脏数据（非 JSON/回显漂移/items 空或超批/空白 content/批内 normalized 重复/dimension_id 非本池 selected/ai_risk·fact_type 枚举越界/evidence 非空白字符串）投递前 502 AtomExpandOutputInvalid，且不留 run/候选；embedding 返回行数不符或维度≠1536 同样 502。**模型自报 affinity/cluster_id/score 一律剥离**，affinity=与同维 approved/frozen 且有向量原子的进程内余弦 max（6 位小数；无基含历史 NULL 向量原子时为 None 不伪造 0，另记 approved_atom_count/approved_embedding_count），cluster_id=批内同维并查集（余弦 ≥ `atom.cluster_line` 默认 **0.9**——借 Q10 同义线，原文未给【待补】，进配置中心；跨维不成簇，仅 ≥2 成员成分发 uuid4），Q16 low_affinity_line=0.5 仍只标不淘汰；KNN 索引/`<=>` 下推按 14 §2.3 千万级后置。**ai_risk 与前四站"模型分全剥"不同——PT-ATOM-EXP/Q17 契约内 AI 字段，枚举校验通过即透传作兜底档，词表命中仍由 submit_batch 强制只升不降**。业务违规（line 11189 全局事实唯一/事实冲突等）不 502，照由 submit_batch 既有 409/422 口径处理、适配器失败回滚留 pending_review。整批单个 atom_batch 候选（1536 维向量以机读键 `_embeddings` 带外随候选 payload，投递校验与适配器双侧 pop，不进 BatchSubmitRequest/run.output），201 返回 run_id/source=llm_auto/model_id/tokens/candidates[]；product_reviewer 经 `/skill-candidates/{id}/decision` 裁决后才由 Q80 适配器 apply_atom_batch→submit_batch（强制 source=ai，Q14/Q15/批内去重/维度必选/line 11189/Q17 双轨/line 840/Q18 缺证降级一项不绕，有证 pending_review/无证 pending_evidence）；approve 时候选 embedding 复制到 product_atom_instances 供后续批次做基（Q86 前历史行 NULL 不 backfill、不入基），逐条 approveAtomGuard/Q70/Q18/Q19/Q20 Gate 原样。预算/失败同 Q82–Q85：日预算按模型全局硬停 409（chat 成功后 embedding 触顶同样 409 不留 run）、不静默切供应商、disabled 仅走已注册 fallback、非合成模型缺 active Key 422、上游坏 502；系统 Actor `system:llm-gateway` roles=[]（Q66）。种子：CONFLICT-PRECHECK→synthetic-deterministic、ATOM-AFFINITY→synthetic-embedding（价 0）两条路由 + CONFLICT-PRECHECK Prompt v0.1（模板变量 6 项 product_profile/sensitive_industry/batch_size/selected_dimensions/approved_atoms/target_range，另有 _batch_size/_selected_dims 两个合成替身机读键不进模板）。

> **Q87 补登（2026-09-15，无迁移纯代码切片——M8 restock_auto worker 闭环）**：Q71/Q76-4 的 `skill_runs(status=requested, source=restock_auto, skill=PWC-BUILDER)` 信号行由进程内第二个 asyncio 循环 `RestockWorker`（与 SweepScheduler 同构，task 名 `loom-restock-worker`）自动消费，**四接缝经负责人拍板追加 Q87（02 C1.31，均选推荐项）**。①形态/队列选型裁决：**V1=进程内轮询**（docs/07 §7.5"待决策"闭合），Redis Streams 与多副本单实例锁后置 V2；`LOOM_RESTOCK_WORKER_ENABLED` **默认 false**（自动花真 token，部署 opt-in；区别于 scheduler 默认 true）、`LOOM_RESTOCK_INTERVAL_SECONDS` 默认 60、`LOOM_RESTOCK_BATCH_SIZE` 默认 20（实现值，env 调，非 Q9 旋钮）；管理端 `POST /api/admin/restock/run`（body=actor，**platform_admin**，越权 403）手工跑一轮，返回 `{claimed, succeeded, failed, deferred, runs}`。②**纯追加认领（append-only 不放松）**：requested 信号行**永不 mutate**；成功追加一条 `succeeded/llm_auto` 子 SkillRun（`input.restock_request_id` 回链信号行，候选 FK 挂子 run，与手动 llm-build 同构，全部 pending_review 过既有 product_reviewer Gate）；终态失败追加一条 `failed/llm_auto` 子 run（error 记异常类型+消息）；认领查询 = requested 行反连接已有 llm_auto 子 run（成功/失败都不重复消费，瞬态不留子 run 故下轮重试）。`GET /skill-runs?status=requested` 会持续显示已消费信号行（日志本色），处理状态靠 join 子 run。③**范围仅 PWC-BUILDER**（当前唯一 requested 写者），created_at 最早优先；worker 走系统内部入口 `invoke_pwc_build_for_restock`（`system:llm-gateway` roles=[]，Q66），**OPERATIONS 角色闸只在 HTTP 的 `/pwc/llm-build` 保留**；不自动串 ATOM-EXPAND（原子跨维 <2 时按终态失败处理）；一次信号一次调用（一批 ≤ Q21 cap 50）。④失败分类（无 HTTP 状态码，映射子 run/audit）：**终态**=PS 消失/池非 approved/PwcBuildNotReady/PwcBuildOutputInvalid 结构脏输出/ModelConfigError（缺路由·Prompt·Key、能力不符）/停用无 fallback ModelUnavailable → failed 子 run + audit `skill7.restock_failed`(terminal=true)；**瞬态**=日预算硬停（新增 `BudgetExhausted(ModelUnavailable)` 子类，HTTP 侧仍映射 409 不变）/上游 GenerationUpstreamError → 不留子 run、audit `skill7.restock_deferred`(terminal=false)、下轮重试；成功 audit `skill7.restock_delivered`。不静默切供应商，fallback 仅走注册表已注册者；V1 不设重试次数/退避（挂账随多副本锁同列 V2）；每信号行独立会话/提交，单条失败不污染整轮。无 Alembic 迁移（failed 状态 Q71 已预留）。

> **Q88 补登（2026-09-15，迁移 0019——入站“一 Agent 一 Key”凭证券半套，Q60b effect-callback 鉴权前置）**：接缝四问经负责人拍板追加 Q88（02 C1.32，均选推荐项甲案）。①**范围=只做 Key 半套**：新表 + platform_admin 治理端点 + Bearer 验签函数/依赖 + 审计；`POST /api/effect-callback`、effect_records 时序（content_id+captured_at 幂等、缺席指标记“—”不当 0）、孤儿队列人工认领、Q60a content_id↔platform_post_id 运营回填、customer-backfill 全部随段13/P3（V2），本切片不提前落；V1 无受 Key 保护业务端点是显式挂账（同 Q82 底座先行），不建占位回调端点。②**SHA-256 单向哈希**：明文 `loom_`+secrets.token_urlsafe(32) 仅签发响应返回一次，DB 存 sha256 hex（unique + 索引）与明文前 12 字符展示前缀；与 outbound Fernet 可逆加密刻意区分（出站须还原明文、入站只需比对，库泄露不暴露可用 Key）；吊销=状态位+revoked_by/revoked_at，不物理删除。③**Key 不绑租户**：平台级凭证 platform_admin 签发，未来回调租户归属由 content_id 解析 FCW.tenant_id（对不上进孤儿队列）；单租户绑定口径原文未给【待补】，不臆造 tenant 列。④**新横切包 `app/core/api_keys/`**（models/service/schemas/router，与 model_registry outbound 域并列不合并），治理路径 `/api/admin/agent-keys`，platform_admin 红线；验签 `verify_key` 对未知/空串/已吊销统一 None（不区分原因，防凭证探测侧信道），命中盖 last_used_at（调用方提交）；FastAPI 依赖 `require_agent_key`（Authorization: Bearer，401 `invalid or revoked agent API key`）留待段13 端点复用；审计 tenant_id=`_platform`，动作 `agent_api_key.issue`/`agent_api_key.revoke`。测试 332 全绿（+17 集成），eval 不新增仍 101/101。

> **Q89 补登（2026-09-15，无迁移纯代码切片——多副本单实例锁，02 C1.33 四接缝均选推荐甲案）**：两个进程内循环（SweepScheduler/RestockWorker）多副本下的单实例执行由新横切包 `app/core/locking/` 保证：Redis `SET key token NX PX 60000` + uuid4 owner token，释放/续约走 Lua 比对 token，看门狗每 TTL/3=20s 续约，进程崩溃 TTL 到期自动放锁；两把循环级命名锁 `loom:lock:sla-sweep`/`loom:lock:restock-worker`，每轮 tick 抢锁成功才跑、抢不到跳过（不做每信号行细粒度认领，Q87 append-only 认领一字不改）。`LOOM_DISTRIBUTED_LOCK_ENABLED` **默认 false**（单副本/本地零依赖）；开启后 Redis 故障 **fail-closed 跳过本轮**并 error 日志，绝不无锁双跑。`POST /api/admin/sla/run`、`POST /api/admin/restock/run` 纳入同一把锁：锁被占 **409**（already running，RBAC 403 判定在前）、Redis 故障 **503**。看门狗发现锁易主/续约失败仅记 error，不打断进行中一轮（fencing token 强制退场留 V2）。测试 345 全绿（+13 集成，内存 FakeRedis），eval 仍 101/101。仍挂账：瞬态重试退避（**Q90 已落地，见下条**）、Redis Streams/细粒度认领、配置缓存广播、fencing token、编排并行/DAG（V2）。
> **Q90 补登（2026-09-15，迁移 0020——restock 瞬态失败指数退避，02 C1.34 四接缝均选推荐甲案）**：Q87 瞬态（BudgetExhausted/GenerationUpstreamError）的无状态自然重试升级为游标退避——新表 `restock_retry_state`（request_id PK/attempts/next_attempt_at 索引/last_reason/updated_at，迁移 0020，PG16 up/downgrade-1/up 实测）专载可变重试状态，**requested 信号行 append-only 纪律一字不动**。定时 tick（honor_backoff=True）认领时跳过 next_attempt_at 未到的信号；间隔=60×2^(attempts−1) 封顶 1800s（env `LOOM_RESTOCK_BACKOFF_BASE_SECONDS`/`_MAX_SECONDS`/`_MAX_ATTEMPTS=10`，运维参数非 Q9 旋钮）。**BudgetExhausted 永不转终态**（UTC 日界预算自愈，转终态会永久漏补），GenerationUpstreamError 连续 10 次（约 17h）转终态：追加 failed/llm_auto 子 run + `restock_failed`(terminal=true, attempts=10) + 删游标，之后被反连接排除。成功或终态即删游标；瞬态每次 attempts+1 并重排窗口（restock_deferred 审计 detail 增 attempts）。`POST /api/admin/restock/run` honor_backoff=False 绕过窗口立即试，瞬态仍计数（平台管理员“立即试一次”语义）。测试 351 全绿（Q87 预算用例更新 +6 退避集成/单测），eval 仍 101/101。仍挂账：Streams/细粒度认领、配置缓存广播、fencing token、编排并行/DAG（V2）。
> **Q92 补登（2026-09-15，无迁移纯只读切片——M12 首片两个驾驶舱，02 C1.36 四接缝均选推荐甲案）**：新横切包 `app/core/dashboards/` 挂两个 GET（前缀 `/api/admin/dashboards`，仅 **platform_admin**；管理面 GET 首次经 query 携带 actor——`actor_id` 必填（缺 422）、`roles` 可重复，FastAPI 依赖判 403；真实认证中间件 V2，V1 actor 请求自报同写端点）：①`GET /token-cost?date_from=&date_to=`（YYYY-MM-DD 可缺省，默认近 30 天 today−29…today，半开 UTC；from>to 或日期非法 422）——succeeded 且 model_id 非空行按天×model_id×currency_code 聚合 runs/tokens/cost（Q86 embedding 运行计入，价 0 计调用数），另附 by_skill；failed 不计费按 skill 单列 failed_by_skill；requested 无 model 排除；**多币种分组不换算**（币种【待补】沿用 Q82）；单价口径归 Q67 不重算。②`GET /review-workload`（同窗参，窗只管产出段）——backlog 为实时快照：pending_review 候选按 target_type 计数+最老等待秒数，ops_todos 按 todo_type 拆 open（未到期）/overdue（open 且 due_at 过）/escalated + 四类 totals；window_output=窗内 reviewed_at 候选按 state、resolved 待办按 todo_type 计数；snapshot_at UTC ISO8601；空库零值。append-only 三表（skill_runs/skill_candidates/ops_todos）只读，不建表/不物化/无调度器/无租户过滤参数（租户实体不存在，Q33 随租户管理切片）。Q70 二期项（智能派单/10% 抽检/6 场景细分）不做。测试 378 全绿（+7 集成），eval 仍 101/101。仍挂账：统一审核工作台、租户+Onboarding、客户前端（18 🟡 门控）、CSV 中台契约、驾驶舱前端页面、真认证中间件（V2）。
> **Q93 补登（2026-09-15，M12 第二片——Q70 一期统一审核工作台，02 C1.37 四接缝均选甲案；迁移 0021 纯配置种子）**：新横切包 `app/core/workbench/`（前缀 `/api/review-workbench`）：①`GET /candidates`——统一队列，query `actor_id`（必填 422）+`roles` 可重复（依赖判 403），可见角色=注册表全部 WF 的 skill7 Gate 角色并集（当前 operations+product_reviewer，platform_admin 不放行）；参 `state`（默认 pending_review｜applied｜archived）、`target_type` 可重复（pwc_combo/field_plan/c1_recognition/atom_batch/c7_layer4）、`wf_id`、`risk_level`（critical/high/medium/low）、`limit` 默认 50 ≤200、`offset`；排序 risk_rank DESC, created_at ASC（同档最老优先）；风险派生：atom_batch=批内 ai_risk 最高档、c1_recognition=industry 命中 c1_industry_thresholds.sensitive 归 critical 否则 low、其余三型 low（risk_reason 回带来源码）；响应 `{total,limit,offset,batch_pass_confidence,candidates:[候选字段+run.confidence+risk_level/risk_rank/risk_reason+wait_seconds+batch_eligible]}`。②`POST /batch-approve` body `{candidate_ids[],reason?,actor}`——只允许 confirmed 原样通过；预检顺序：不存在 404→非 pending 409→逐候选 WF Gate 角色不符 403（混角色批整批拒）→run.confidence 缺失/≤`review.batch_pass_confidence`(0.85，Q70/Q9 新键)/risk_rank≥high 422；全过预检后单事务复用 skill7 decide_candidate 适配器，任一失败整批回滚（错误口径同 `/api/skill-candidates/{id}/decision`），返回 `{approved[],count}`；high/critical（含敏感行业）禁批量，modified/rejected 仍逐条。Q70②候选自动挂 SLA 待办、派单/抽检/6 场景细分不在本切片（后者二期）。测试 384 全绿（+6 集成），eval 仍 101/101。
> **Q94 补登（2026-09-16，M12 第三片——Q70②候选审核 SLA 待办自动挂接，02 C1.38 四接缝均选甲案；迁移 0022 五条纯配置种子）**：skill7 候选生命周期补 SLA 挂接（HTTP 契约不变，无新端点）：**投递** `POST /api/skill-runs`（人工/llm_auto 同路径）每候选同事务落一条 ops_todos：todo_type=`review_{target_type}`（五型五个）、entity_type=skill_candidate、assignee_role=该 WF 注册表 review_role（WF-01 operations／WF-02/03/04 product_reviewer）、detail={wf_id,target_type,run_id,candidate_index}、due_at=投递时刻+`review.sla_hours.<target_type>`（五键种子均 72h，数值【原文未给出，待补】，配置中心热更）；**裁决**（`POST /api/skill-candidates/{id}/decision` 与 `/api/review-workbench/batch-approve` 复用同一路径）即把 open/escalated 待办置 resolved（resolution=applied｜archived，resolved_at 落戳），升级不阻断裁决，查无待办静默（挂接前存量不回填）。**到期**仍由 Q49 sweep 统一置 escalated，五型升级审计动作=`skill7.review_sla_escalated`；黄色预警窗口原文未给→到期前 green（挂账）。驾驶舱 review-workload 的 todos 积压按 todo_type 自动新增五型分组。测试 391 全绿（+7 集成），eval 仍 101/101。

> **Q95 补登（2026-09-16，M12 第四片——租户管理+Onboarding，02 C1.39 四接缝均选甲案；迁移 0023 建 tenants 表+存量回填）**：新横切包 `/api/admin/tenants`（platform_admin 红线）：`POST /api/admin/tenants` 开通（体 `{tenant_id,name?,plan=trial,actor}`，201；默认 trial/trial+月额度 50 万，付费档→active/额度 null；重复 409、未知 plan 422、非管理员 403）；`GET /api/admin/tenants` 列表、`GET /api/admin/tenants/{tenant_id}` 详情（GET 走 query actor：actor_id 必填 422、roles 不符 403；详情额外回派生 `onboarding={intakes,product_spaces,first_modeling_started}`，无引导状态机）；`POST /api/admin/tenants/{id}/change-plan`（续费口径只改 plan 不改 status；付费档额度 null、改回 trial 写 50 万）、`/pause`（trial/active→paused，重复 409）、`/resume`（paused→active，未暂停 409），写端点 actor 在体，全部 append-only 审计 tenant.provisioned/plan_changed/paused/resumed。**段1 准入新增错误口径**：`POST /api/intakes` 写单前校验租户存在且未暂停——未知租户 **404**、暂停租户 **409**（闸在应用层，无硬外键；链内其余端点仍从 intake/PS 锚点派生租户，不新增校验）。价格（Basic $999/Pro $2999/Enterprise $9999）仅 D3.11 展示用，无计费端点；团队账号/Onboarding 页面随 V2/前端门控。测试 401 全绿（+10 集成），eval 仍 101/101。


> **Q98 补登（2026-09-16，M12 客户前端切片 2·产品中心跨栈最小闭环；无迁移，Alembic 头仍 0023）**：段1 新增只读端点 `GET /api/intakes`——query `tenant_id`（必填非空，缺/空 422）、`limit`（默认 20，1..100）、`offset`（默认 0，≥0），响应 `IntakeList{items: IntakeView[], total, limit, offset}`，排序 created_at DESC。**读路径不触发 Q95 准入门**：未知租户与暂停租户均返回 200 空列表（只读不放宽写闸：POST 建单的未知 404/暂停 409 一字不动）；只读不 writeAudit。配套前端：RSC 列表 + Server Action 建 draft + 只读详情（02 C1.42 四接缝全甲），server-only env `LOOM_TENANT_ID`/`LOOM_API_BASE_URL`，产品名走工程临时键 `product_name`（G2 cat='common' fid 基线回填后对齐，挂账）。测试 404 全绿（+3 集成），eval 仍 101/101。

> **Q99 补登（2026-09-16，M12 客户前端切片 3·工作台最小总览；无迁移，Alembic 头仍 0023）**：段1 再增只读端点 `GET /api/intakes/overview`——query `tenant_id`（必填非空，缺/空 422），响应 `IntakeOverview{total:int, by_status:{状态码:计数}}`，单次 group by status 聚合、total 为分组计数之和；读路径同 Q98 **不触发 Q95 准入门**（未知/暂停租户返回 `{total:0,by_status:{}}`，写闸一字不动），只读不 writeAudit；**路由必须注册在 `GET /{intake_id}` 之前**，否则字面量 overview 被路径参数吞成 intake_id。配套前端工作台（02 C1.43 四接缝全甲）：录入单总数 + 15 态分组（`intake.status.*` 消息对齐 docs/13 §1.1，仅渲染计数 > 0）+ 快捷入口；D5 原文五指标（今日生成/发布/互动/趋势/健康度，数据源属段 12/13）渲染禁用态 V2 卡，不显示任何数字（含 0）。测试 407 全绿（+3 集成），eval 仍 101/101。

> **Q100 补登（2026-09-16，M12 中台导出·FCW final_id 单列 CSV；无迁移，Alembic 头仍 0023）**：新横切只读包 `app/core/exports/` 挂 `GET /api/exports/fcw.csv`（02 C1.44 四接缝全甲）：query `tenant_id`（必填非空，缺/空 422）、`product_space_id`（可选，按产品空间收窄）；响应 `text/csv; charset=utf-8` + `Content-Disposition: attachment; filename="fcw-<tenant>.csv"`，正文表头 `final_id` 后每条 published 一行一个 final_id（created_at DESC），**严格单列、不拼 6 层原料包**——docs/09:87 的 6 层包口径属台内详情/复制，不进导出文件；D4 行【待补】就 CSV 部分收口（JSON 形态仍挂后续）。读路径纪律同 Q98/Q99：不触发 Q95 准入门、不 writeAudit，未知租户 200 返回仅表头空文件；只导 published（draft 排除；Q32 revoked 急停 V1 未落地，其态一旦实现由 published 过滤自然排除——前向兼容）。curl 实测：t1 表头+3 条（draft/t2 排除）、product_space_id 收窄、ghost 仅表头 200、空 tenant 422。测试 410 全绿（+3 集成），eval 仍 101/101。

> **Q132 补登（2026-09-20，M12 中台导出 JSON 形态 + 异步导出任务；迁移 0036 新表 export_jobs，02 C1.76）**：① `GET /api/exports/fcw.json` 与 fcw.csv 同 query/同口径（只 final_id、只 published、created_at DESC、未知租户空 envelope 200、不触发 Q95 准入门），body=`{tenant_id,product_space_id,count,final_ids[]}`，不拼 6 层原料包；② `POST /api/exports/jobs` body `{tenant_id,product_space_id?,format:csv|json=csv,actor}`（中台面同 Q100 无 RBAC 闸、actor 留痕），V1 请求内同步执行置 completed（同 Q55 任务同步先例），201 回 ExportJobView（含 download_url），审计 `export.job_created`（tenant=客户租户、actor_id=requested_by、roles=[]、detail format/row_count/product_space_id）；新表 export_jobs（job_id PK/tenant 索引/format/status server_default completed/row_count/file_name/requested_by/error/created_at/completed_at）**不存 payload**；③ `GET /api/exports/jobs/{id}` 状态口（404 未知）、`GET /api/exports/jobs/{id}/download` 下载口（404 未知、failed 409，按 format 重渲染 csv/json、文件名取 job.file_name，幂等反映当前 published 集合，row_count 为创建时留痕）；~~queued/running 真后台 worker 随 V2 Redis Streams、任务列表口 V1 不做~~ ✅ **已由 Q137 落地（02 C1.81，env `LOOM_EXPORT_WORKER_ENABLED` 默认关）**：门控开启时 POST 落 queued 并入 Redis Streams，`ExportWorker` 消费组异步处理（崩溃 PEL 接管/超限死信），新增 `GET /api/exports/jobs` 任务列表口，download 对 queued/running 返 409；门控关闭仍走本片同步 completed 路径。restock requested 信号生产侧 XADD 见 Q138（02 C1.82，仅入流、worker 主认领仍 DB 轮询）。测试 618→633（+15：5 单测 +10 集成），迁移 0036 经 pg16 容器实测物理表 57→58、downgrade-1/up 往返对称，eval 仍 101/101（golden 21）。
> **Q141–Q143 补登（2026-09-20，V2 基建收口三片；02 C1.85–C1.87）**：
> - **Q141 配置缓存版本号门控 + TTL 兜底（非 HTTP，内部一致性）**：ConfigCache 快照携 per-key `ConfigItem.version` 向量；`reload_keys` 对 DB 版本号小于本地持有版本的键跳过（skipped）、显式删除出快照（removed）、接受更新（accepted），杜绝乱序广播把旧快照回灌；写侧 after_commit `apply({k:v},{k:version})` 用 DB 权威版本。订阅器无失效消息超过 env `LOOM_CONFIG_CACHE_TTL_SECONDS`（默认 300s）也回源全量 reload（仅广播门控开启且曾成功装载时触发）。零迁移；后端测试 678→684（+6）。
> - **Q142 中台导出分页 + 行数硬上限（HTTP 契约）**：fcw.csv/fcw.json（含 jobs 下载）统一加 query `limit`（1..硬上限）/`offset`（≥0）；硬上限 env `LOOM_EXPORT_MAX_ROWS`（默认 100000，运维防护旋钮、非 Q9 业务阈值），limit 超限/offset 为负 422，不传 limit 回落硬上限。JSON envelope 追加 `total/limit/offset/has_more`（count 仍为本页行数）；CSV 正文守 Q100 单列、分页走响应头 `X-Export-Total/Limit/Offset/Has-More/Truncated`，truncated＝未显式分页却被截断。同步/异步 worker/下载经同一 `fetch_export_page` 受上限；export_jobs 不加分页列、审计 detail 加 total/limit/truncated。零迁移；测试 684→692（单测 +2、集成 +6）。

> **Q155 实现补登（2026-09-21，台内白名单卡片 6 层原料包全量 JSON，零迁移，02 C1.99）**：销 V2 挂账「6 层原料包全量 JSON」的**后端能力**。面的分界：docs/09:87「每条白名单 = 完整 6 层提示词原料包（产品+平台+策略+结构+表达+合规）」、01 line 14「final_id = 6 层快照相加」；Q100 + Q132 + Q142 三处定论中台 `/api/exports/fcw.csv|json` 严格 final_id 单列、不拼 6 层包，6 层包属**台内 FCW 卡片详情/复制口径**，故端点落 final FCW 域 `app/final/final_whitelist/material.py`（不塞进 exports）。新模块 `build_material_pack(session, fcw)` 按 final_id 反解析六路 id：product=PwsSnapshot 冻结快照（池原子 atoms/PWC combo）、platform=PcpWeightTable 权重 + PublishSlot、strategy/structure/expression=三包 Package（kind=csp/cstp/cep 及定键 payload）、compliance=CcrReport + 关联 LawReview 列表；包体 `{schema:"loom.fcw.material-pack.v1", final_id, issued:{tenant_id,product_space_id,platform,slot_id,goal,country,score,score_incomplete,score_detail,publish_status,issued_by,created_at,published_at}, layers:{...}, guards, warnings:[]}`，引用行物理缺失不 500、回 `{"_ref":id,"available":false}` 并收 warning。端点 `GET /api/fcw/{final_id}/material.json`（JSONResponse + attachment 文件名 fcw-material-<final_id>.json），只读、无 RBAC 闸、不触发 Guard、不写审计、未知 final_id 404，读纪律同既有 `GET /api/fcw/{final_id}`。测试 test_fcw_material_api.py 3 例（六层齐全/含已批准 LawReview/未知 404，+3）。docs/08 beta checklist 曾列本期不做（P2），本轮系负责人新点工提前销项；**前端不做**（D3.5 白名单组装引擎菜单整片未建，同 Q100 先例），6 层包之外的卡片 UI（复制 ID/多选/列表卡片）不扩张。
> - **Q143 restock 花钱路径 PG 行级 fence（内部写口径，非 HTTP）**：新表 restock_claims（迁移 0037，pg16 往返实测，业务物理表 58→59）+ `app/core/restock/fencing.py`。花钱（模型调用）前 `claim_request(session, request_id, fence, owner)` 在独立短事务插入或把 fence 单调升到自己（返回 acquired/held/lost，先提交使易主新 leader 可见）；fence=None（V1 单副本、多副本锁关闭）恒 held、不写表。花钱成功、同一业务事务提交前 `fence_current(...)` 执行条件 UPDATE `... WHERE request_id=:id AND fence=:token`，rowcount=0 即被更大 fence（新 leader）抢占→回滚整轮（succeeded 子 run/候选/审计不落库），worker report 加 skipped_lost；花钱前认领即 lost 则不调模型。只接 restock 花钱成功提交路径——外部模型已花费用不可撤销，fence 只保下游 DB 不重复写；deferred/failed/退避游标幂等不接门。SLA sweep 行级 fence、restock worker 切消费组水平并行（花钱隔离 Q87/Q89）、真 PG/Redis 多副本易主验证留 V2。测试 692→699（fencing 原语 4 + worker 端到端 3；sqlite 单连接替身无法跨会话并发接管，端到端用 monkeypatch 关门、跨连接条件 UPDATE 由顺序事务原语测试覆盖）。

> **Q101 补登（2026-09-16，M12 客户前端切片 4·合规风控只读功能页；无迁移，Alembic 头仍 0023）**：段10 增租户级只读聚合 `GET /api/compliance/overview`（02 C1.45 四接缝全甲）：query `tenant_id`（必填非空，缺/空 422），响应 `ComplianceOverview{items:[{pws_id,product_space_id,intake_id,product_name,version,ccr:null|{worst_status,block_required,latest_at,markets:[{country,status,block_required,created_at,bans,downgrades}]},law_review:null|{status,domain,conclusion,decided_at}}]}`。口径：仅 is_active=true 且 status=frozen 的 PWS 快照，每 PWS 一行；同一 PWS 各市场（country=None=底座通用判定）只取 created_at,ccr_id 双 DESC 后的最新一行 append-only 报告，行 worst 按 blocked>downgrade_pending>approved>clean 从严、block_required 跨市场 OR、latest_at 取最大；superseded/revoked/非 active 快照与历史报告行不进列表；从未清洗 ccr=null（不伪造 clean）、未触发法审 law_review=null（一 PWS 一条 uq_law_review_pws）；产品名仅取 intake.profile.product_name 非空 strip 字符串，否则回退产品空间 ID 前 8 位。读路径纪律同 Q98–Q100：无角色闸但也无任何写口，不触发 Q95 准入门、不 writeAudit，未知租户 200 `{"items":[]}`；清洗触发（POST /pws/{id}/ccr/run）、降级批准、法审裁决、CP-LAW 词库/领域 CRUD 仍全部 internal_compliance 台内执行，客户页不挂任何写操作，亦不派生法审 SLA 超时态。curl/Chrome 实测见 02 C1.45④。测试 414 全绿（+4 集成），eval 仍 101/101。

> **Q107 补登（2026-09-16，M12 管理端第五片·录入单运营队列与跨租户运营操作；无新写口、无迁移，Alembic 头仍 0023）**：段1 增跨租户只读端点 `GET /api/intakes/ops-queue`（02 C1.51 四接缝全甲）——query `actor_id`（必填，缺 422）、重复 `roles`（require_any_role(actor, OPERATIONS, PLATFORM_ADMIN)，不符 403；customer 不可见）、可选 `status`（必须在 15 态 STATE_LABELS 内，否则 422 `unknown intake status: {status}`）、`limit`（默认 20，1..100）/`offset`（≥0）；响应 `OpsIntakeList{items: OpsIntakeView[], total, limit, offset}`，OpsIntakeView 为租户内 IntakeView 加 `created_at: datetime`；无租户过滤、created_at DESC。**路由必须注册在 `GET /{intake_id}` 之前**（同 /overview 教训），service.list_ops_intakes 跨租户 select + count 子查询。**不新增写口**：管理端操作岛的 6 个运营事件（ops_confirm/to_cold_start/reject/b2_approved/b2_parent_fallback/b2_rejected）全部复用 `POST /api/intakes/{id}/transitions`，actor 换成管理员身份，状态机既有 403 RoleRequired/409 IllegalTransition/422 missing_fids 口径一字不动；wf01_*/auto_confirm 与 send_review/review_*/start_modeling/model_*/failed_*（触发方【原文未给出，待补】）不在管理端白名单。配套前端 `/admin/intakes` 列表与 `[intakeId]/` 详情操作岛、platform_admin 默认可看不可执行（缺 operations 角色前端本地 missing_role 零请求）见 02 C1.51、08 Q107、15 Q107。测试 418 全绿（+3 集成），eval 仍 101/101。

> **Q114 补登（2026-09-17，M12 收尾——客户侧 settings 账户面板后端读口；无迁移，Alembic 头仍 0023）**：租户注册表新增**客户侧只读**路由（同包内与 `/api/admin/tenants` 分离的 `customer_router`，前缀 `/api/tenants`）：`GET /api/tenants/{tenant_id}`——**无 actor 闸**（客户读自己租户的元数据；V1 身份仍 env 自报，真实会话派生随 V2），未知租户 404；响应 `CustomerTenantView{tenant_id,name,plan,status,monthly_token_quota}`，**刻意不含 detail/onboarding 等管理面字段**（测试锁定不泄漏）。plan 四档/status 三态码原样不译；`monthly_token_quota=null` 表付费档额度【原文未给出，待补】。消费方：前端 `/[locale]/settings` 只读账户面板（02 C1.58、08 Q114）。

> **Q116 补登（2026-09-17，V2 P4 段12 内容生成首片——文章单语言最小闭环；迁移 0025 建表 + 0026 纯种子，Alembic 头 0024→0026）**：新模块 `app/content/` 挂 `/api/content/*`（02 C1.60、08 Q116）——**段12 的 Gate 是客户审阅（Q59），不走 skill7 运营 Gate（Q66）**：ARTICLE-GEN 为模型网关第 7 场景，**不产 skill7 候选**，成本经 SkillRun 手动落（Q67）+ writeAudit 留痕：

| 方法与路径 | 契约 | 来源 |
|---|---|---|
| POST `/api/content/generate` | **operations**（越权 403）：body=`{final_id, kind?=article, language?=zh-CN, actor}`；按 final_id 只读消费 FCW（PT-ART-GEN-V1.5）并从 FCW 取 tenant/product_space/goal/platform/slot/country；201 返回 `ContentProductView`；final_id 不存在 404；kind=video 或未知 422（P4 仅 article）；**Q119：language 不在「发布位市场 ∩ 产品目标语言」交集 → 422（detail 回带 eligible）、同 final_id+language+kind 成品已存在 → 409**；模型输出非法 502；状态闸（非 generating）409 | Q116/Q119 |
| POST `/api/content/{content_id}/approve` | **客户**通过（Q59）：review→ready_for_publish；**Q200 起 `tenant_id` 必填 query、跨租户与不存在同回 404**；不存在 404；状态不合法 409 | Q116/**Q200** |
| POST `/api/content/{content_id}/reject` | **客户**驳回（Q59）：**原因必填**，空/空白 422；review→rejected，reason 落 `reject_reason` 供段13 回流；**Q200 起 `tenant_id` 必填 query、跨租户与不存在同回 404**；状态不合法 409 | Q116/**Q200** |
| POST `/api/content/{content_id}/revise` | **客户**改稿：review→revising（强制重过 CONTENT-COMPLIANCE 复检：词库扫描 + 语义级检测，Q121）；重生成次数达 `content.regen_limit`（默认 3、运营可配，Q120 接通）422（detail 回带 {count}/{limit}）；**Q200 起 `tenant_id` 必填 query、跨租户与不存在同回 404**；状态不合法 409 | Q116/Q120/**Q200** |
| POST `/api/content/{content_id}/regenerate` | **operations**（越权 403）：revising→generating（`regenerate_count`+1）→review；非 revising 或达上限 422；不存在 404；模型输出非法 502 | Q116 |
| GET `/api/content?tenant_id=` | **客户·无闸**（Q122）：租户内容成品列表，created_at DESC，**列表项不含 body**（`ContentProductListItem`）；未知租户 200 返空（口径同 Q101），缺 tenant_id 422 | Q122 |
| GET `/api/content/{content_id}` | **客户·无闸**（Q122）：成品详情（含 body 与完整 review_hits/质量字段）；**Q200 起 `tenant_id` 必填 query、跨租户与不存在同回 404**；不存在 404 | Q122/**Q200** |
| PATCH `/api/content/{content_id}/body` | **客户·无闸**（Q122，Q56-a 人工编辑）：仅 revising 态可调（非 revising 409），body 空白 422、不存在 404；**Q200 起 `tenant_id` 必填 query、跨租户与不存在同回 404**；换正文后**重跑词库 + 语义复检与 ARTICLE-QC**，经 `manual_resubmit` 回 review；**不调 ARTICLE-GEN、不增 regenerate_count**，审计 `content.body_edited` | Q122/Q56/**Q200** |
| GET `/api/admin/content-languages` | **dictionary_admin**（query actor 闸 Q118：缺 actor_id 422、越权 403）：语言清单，`include_archived=false` 默认仅 active；返回 `[{code,name,markets,status}]` | Q119 |
| PUT `/api/admin/content-languages` | **dictionary_admin**（body actor，越权 403）：upsert 语言 `{code(BCP-47),name,markets[] ,actor}`，markets 空数组=全市场（含 country 空）；code/name 空 422、markets 含空串 422；显式 upsert 复活已归档语言（同 content_goals） | Q119 |
| POST `/api/admin/content-languages/{code}/archive` | **dictionary_admin**：软归档（active→archived）；不存在 404、越权 403 | Q119 |
| GET `/api/content/eligible-languages?final_id=` | **operations**（query actor 闸，缺 422/越权 403）：生成前查可生成语言，返回 `{final_id,country,ps_target_languages,eligible[]}`；final_id 不存在 404 | Q119 |
| PUT `/api/product-spaces/{ps_id}/target-languages` | **operations**（body actor，越权 403）：设产品侧目标语言 `{languages[],actor}`，空列表=清空（未声明/不限，返回 null）；产品空间不存在 404、语言重复 422 | Q119 |
| GET `/api/content/languages` | **客户·无闸**（Q123）：仅返回 active 语言清单 `[{code,name,markets,status}]`（不含归档；管理面含归档清单走 dictionary_admin 的 `/api/admin/content-languages`）；**注册顺序必须先于 `GET /api/content/{content_id}`**，否则被路径参数吞掉 | Q123/Q119 |
| PATCH `/api/intakes/{intake_id}/target-languages` | **客户·无闸**（Q123）：按 intake 维度设产品目标语言 `{languages[],actor}`，空数组=未声明（写 NULL）；**Q200 起 `tenant_id` 必填 query、跨租户与不存在同回 404**；产品空间未生成 404、语言码重复/未知/已归档 422；回显 `ProductSpaceView`（新增 target_languages 字段）；operations 的 PUT 代设入口与 OPERATIONS 闸原样保留 | Q123/Q58/**Q200** |
| POST `/api/content/{content_id}/discard` | **operations 写口**（Q124，越权客户 403）：body=`{reason(1–500 必填),actor}`；仅 review/revising/rejected 可作废（draft/generating/ready_for_publish 409），空白 reason 422、未知 404；落 `discard_reason` + 审计 `content.discarded`，行转终态 discarded 并经 partial unique index 释放同键生成机会（回池） | Q124/Q56-b |
| PUT `/api/admin/content/{content_id}/publish-info` | **operations 写口**（Q125，越权 403）：body=`{url(必填非空白,≤1000),platform_post_id?(≤128),actor}`；仅 ready_for_publish（否则 409）、未知 404、空白 url 422；首次落 `published_at`，可重复回填修正 url（不重置时间），post_id 缺省不动、空串清空；审计 `content.publish_info_set` | Q125/Q60c |
| GET `/api/admin/content/ready-to-publish` | **operations \| platform_admin 读口**（Q125，query actor 闸，缺 422/越权 403）：跨租户全部 ready_for_publish 成品，created_at 升序先到先发，行不含 body；published_at 空=待回填、非空=已回填（显链接可修正） | Q125/Q60c |
| GET `/api/admin/content/needs-attention` | **operations \| platform_admin 读口**（Q124，query actor 闸）：跨租户 review/revising/rejected 成品（可作废候选），created_at 升序，行不含 body；**两个静态 GET 必须注册在参数路由 PUT/POST 之前** | Q124/Q56-b |

> 复检口径（Q59 四项）：①**词库扫描**（复用 Q48 词库 + ccr_rules 三层裁决，ban 命中 `block_required=true` 硬阻断，落 `review_hits.bans/downgrades`）；②**语义级检测**（Q121 已落，模型网关第 9 场景 ARTICLE-SEMANTIC-CHECK，落 `review_hits.semantic`，**纯 advisory** 不阻断）；③施工指令核对、④国家规则核对仍【原文未给出，待补】。状态机见 §2.12，表见 04 §3 / 10 §2.9。
>
> **Q119 多语言补登（2026-09-18，Q58，迁移 0028，02 C1.63）**：语言 = 发布位目标市场（`fcw.country`）∩ 产品录入目标语言（`product_spaces.target_languages`）；语言清单 `content_languages` 配置化（dictionary_admin），`markets=[]` 覆盖全市场（含 country=NULL），受限语言不覆盖 country=NULL。每个语言版为独立成品（`content_products` 唯一约束 `(final_id,language,kind)`），复检与客户审按 content_id 天然独立（Q59 流程不按语言分叉）；ARTICLE-GEN 模板新增 `$language` 变量（硬性规则 4：须用目标语言撰写），SkillRun.input_payload 记 language。表见 04 §3 / 10 §2.9。
>
> **Q120 AI 质量分补登（2026-09-18，Q57 + Q56，迁移 0029/0030，02 C1.64）**：模型网关新增**第 8 场景 `ARTICLE-QC`**（只读打分、不改写，variables `[body,language]`，输出 `{score,issues}`）；generate/regenerate 在 ARTICLE-GEN 写正文、词库复检之后、状态 COMPLETE 之前**内嵌**调用一次（新建 `app/content/quality.py`），**零新 HTTP 端点**。结果落 `content_products.quality_score`(0..1)/`quality_issues`；`ContentProductView` 另回带四字段 `quality_score/quality_issues/quality_threshold/quality_advisory`（threshold 取 `content.ai_quality_threshold` 默认 0.85；advisory 低于阈值=true、分数缺失=null）。**定位纯 advisory（Q57 降级裁决）**：分数不自动发证/驳回、不阻断 approve、不新增状态，段12 Gate 仍是客户审阅 Q59；界面「AI 评估分，仅供参考」标注随 Q122 前端，段13 回流后的相关性校准后置。QC 场景未配置/模型不可用/预算耗尽/上游错误，或输出非法（非 JSON/非对象/score 缺失越界，bool 不算数值）时 score 留空、issues 记 `{"qc_error": ...}`、成品照常进 review（失败写审计 `content.quality_unavailable`、不落 SkillRun；成功落 SkillRun source=llm_auto、wf=WF-10 与审计 `content.quality_scored`）。**Q56 止损**：重生成上限取配置 `content.regen_limit`（默认 3、运营可改），`revise_allowed(status,count,limit)` 超限只能 reject——不自动作废 final_id、不自动回池；a 清洗区人工编辑已由 Q122 落（PATCH body）；b 作废回池记难产原因已由 **Q124（C1.68）落**（discarded 终态 + discard 端点 + 运营台待处置队列）。表见 04 §3 / 10 §2.6、§2.8。
>
> **Q121 语义级复检补登（2026-09-19，Q59 复检第②项，迁移 0031，02 C1.65）**：模型网关新增**第 9 场景 `ARTICLE-SEMANTIC-CHECK`**（只读检测、不改写，variables `[body,language]`，输出 `{findings:[{code,message,excerpt}]}`）；generate/regenerate 在词库扫描之后、ARTICLE-QC 之前**内嵌**调用一次（新建 `app/content/semantic.py`），**零新 HTTP 端点 / 零新列 / 零新表**，结果聚合进既有 `review_hits` 的 `semantic` 段 `{checked, findings, ?error}`。**负责人拍板纯 advisory（甲）**：语义命中不抬 `block_required`、不阻断 approve、不新增状态（词库 ban 的确定性硬阻断原样保留；与 Q57 降级、Q66 AI 不持否决权一致）。检测维度四 code（unsubstantiated_claim/absolute_guarantee/off_material_exaggeration/misleading_ambiguity）为 v0.1 工程口径，待业务方/法审校准。场景未配置/模型不可用/上游错误 → `{checked:false, findings:[], error:<类型>}`、审计 `content.semantic_unavailable`、不落 SkillRun，不阻断生成；坏 JSON/非对象/findings 非数组归一为空+错误码但仍落 SkillRun（output 带 parse_error），成功审计 `content.semantic_checked`（source=llm_auto、wf=WF-10）；findings 逐项容错（非法项跳过、message/excerpt 非字符串丢弃）。施工指令核对、国家规则核对两项仍【待补】；语义发现的界面提示随 Q122，视频载体随 video-studio。表见 04 §3 / 10 §2.9。

> **Q122 客户内容页 + Q56-a 人工编辑补登（2026-09-19，零迁移，头仍 0031，02 C1.66）**：第 3 菜单「内容生产与发布」由 v2 占位转 V1 功能页，能力边界 = **只读 + 审阅 + 人工改稿**；生成 / AI 重新生成维持 operations 闸、客户页不调用（前端访问层不得出现这两个端点，check-content 守卫）。后端：六态机新增事件 `manual_resubmit`（**revising→review**，不新增状态）；新增客户三端点（上表，均无 query/body 角色闸，actor roles 恒空）——租户列表（列表项去 body）、详情、`PATCH body`；人工编辑提交后重跑词库复检 + 语义复检（Q121）+ ARTICLE-QC（Q120）回 review，不调 ARTICLE-GEN、不增 regenerate_count（每轮仍须先 revise，间接受 content.regen_limit 约束）；审计 `content.body_edited`。前端：(shell)/content/ 列表（每语言成品并列）/ 详情（正文、AI 质量卡标「仅供参考」、复检卡 bans/downgrades/语义 code 原样不翻译、checked=false 显暂不可用、驳回原因）/ review 态 DecisionIsland（block_required 时禁通过）/ revising 态 BodyEditIsland；nav content v2→v1；新增第八个 checker check-content 并接入 CI。**接缝按推荐甲拍板（交互提问时负责人未在线，沿用其「按你的来/狠狠搞完」授权），已经负责人 2026-09-19 追认销账，见 02 C1.66【追认销账（2026-09-19）】条**；~~Q56-b（作废 final_id 回池记难产原因）继续挂账~~ ✅ 已由 **Q124（C1.68，2026-09-19）** 落地：第七态 discarded + partial unique index 回池 + 运营台待处置队列，见下。测试 523→528（+5 集成）。
>
> **Q124 难产骨架作废回池补登（2026-09-19，Q56-b，迁移 0032，02 C1.68）**：内容状态机由六态扩为**七态**，新增终态 **discarded（只读）**——与 rejected 严格区分：rejected=客户驳回原因回流段13（可继续 revise/regenerate），discarded=运营判定骨架不要、释放该白名单键生成机会。事件 `discard`（operations 硬闸、reason 必填 1–500 字）仅允许 review/revising/rejected → discarded；generating/draft/ready_for_publish 不可作废；终态上所有动作事件为空。**回池机制**：普通唯一约束 `uq_content_final_language_kind(final_id,language,kind)` 改为 **partial unique index `WHERE status <> 'discarded'`**（模型层 postgresql_where + sqlite_where 双方言），作废后同键可重新生成新成品、旧行只读保留；generate 查重另加 `status != discarded` 双保险。新增跨租户读口 `GET /api/admin/content/needs-attention`（review/revising/rejected，operations | platform_admin）承载运营台作废岛。不做自动作废 / FCW 状态机回退（达上限仍只 422，作废是运营显式动作）。迁移 0032 加 `discard_reason Text` + 换索引，pg16 实测 up/downgrade-1/up 对称（downgrade 还原普通唯一索引，不处理同键冲突，V1 无生产数据）。
>
> **Q125 运营发布回填与待发布队列补登（2026-09-19，Q60c，迁移 0033，02 C1.69）**：**不新增 published 态**，ready_for_publish 仍为终态，`published_at` 非空即已发布信号；迁移 0033 加 `published_url Text` / `platform_post_id String(128)` / `published_at timestamptz` 三 nullable 列。写口 `PUT /api/admin/content/{id}/publish-info`（operations 硬闸，仅 ready 态、url 必填、可重复修正、published_at 仅首次落），读口 `GET /api/admin/content/ready-to-publish`（operations | platform_admin，跨租户全部 ready 行：待回填/已回填两分区，回填后不离队以便核对修正，行不含 body）。前端管理端新建 `/admin/content` 内容运营台（与 Q124 共用一页：上半待发布队列 + 回填岛，下半待处置队列 + 作废岛；Server Action 在角色缺 operations 时 missing_role 零请求）；客户详情页 ready 态 published_url 非空显外链、否则仍显「待平台统一发布」。**明确不落（随段13/P3/V2）**：Agent 抓取、effect-callback 端点与 effect_records 时序、孤儿发布队列、Q60a 客户自助发布、发布自动化。迁移 0033 pg16 实测往返对称。Q124/Q125 合计测试 534→554（+20），八 checker 总数不变（扩 check-admin/check-content 守卫，无新 checker 文件）。

> **Q123 段1 客户目标语言控件补登（2026-09-19，零迁移，头仍 0031/表 55，02 C1.67）**：Q119 的 operations 代设入口（PUT /api/product-spaces/{id}/target-languages，OPERATIONS 闸）保留，另开客户侧两个无闸端点（上表）：GET active 语言清单（注册先于 {content_id}）、PATCH 按 intake 设目标语言（产品空间未生成 404，码去重且必须 active，空数组清 NULL，审计 product_space.target_languages.set 带 channel=customer_intake）；ProductSpaceView 回显 target_languages。前端在录入详情产品空间段挂多选控件（空间未生成不渲染），check-products / check-content 加守卫；operations PUT 对 roles=[] 仍 403 有回归锁定。测试 528→534（+6 集成）。


---
## Part 2 · 状态机定义

> 表格列：当前状态 → 触发事件 → 目标状态 → Guard/条件。**事件与迁移原文未逐条给出者标【待补】**（v3 只给状态清单与部分流转规则，实现时需按 Q 编号逐条补迁移表）。

### 2.1 productIntake15（段1 · 录入申请单，line 1454 + Q5）
| 状态 | 说明 | 已知迁移/触发 | Guard/条件 |
|---|---|---|---|
| 草稿 | 初始 | → AI识别中（提交） | 输入完整（G2 18 通用字段） |
| AI识别中 | 6 Skill 串行处理 | → 待确认 / 待补充参数 / 待确认额度 / 类目创建中 | 见 WF-01（06 文档） |
| 待确认 | 类目确认（由运营执行，Q3） | → 已提交 / 类目创建中 | 运营 72h 未处理升级（Q4） |
| 待补充参数 | 缺参数 | → 已提交 / 驳回 | 【待补】 |
| 待确认额度 | 额度确认 | → 已提交 | 【待补】 |
| 已提交 | 提交审核 | → 审核中 | 【待补】 |
| 审核中 | 后台审核 | → 需补充资料 / 已通过 / 驳回 | 【待补】 |
| 需补充资料 | 缺资料 | → 已提交 | 【待补】 |
| 已通过 | 审核通过 | → 建模中 | 【待补】 |
| 建模中 | 冷启动/建模 | → 已入库 / 入库失败 | 【待补】 |
| 已入库 | 完成 | 终态 | — |
| 入库失败 | 失败 | → 需补充资料 / 驳回 | 【待补】 |
| 驳回 | 终态 | — | — |
| 已归档 | 终态 | — | — |
| **类目创建中**（Q5 新增第 15 态） | 冷启动支线停靠位，关联 B2 新类目候选单 | B2 通过→待补充参数；B2 驳回→运营二选一：挂最近父类目继续 / 打回需补充资料 | 客户端显示中性话术"资料分析中" |

### 2.2 atom8（段4 · 原子实例，line 1454 + Q17-Q20）
| 状态 | 已知迁移/触发 | Guard/条件 |
|---|---|---|
| 草稿 | → 待审核（拓展产出候选） | 仅产 candidate 不直接写实例（PT-ATOM-EXP） |
| 待审核 | → 已通过 / 已驳回 | approveAtomGuard 10 项（01 段4）；high/critical 必走 HumanGate（critical 单条审） |
| 已通过 | → 已冻结 / 已废弃 / 已驳回 | 冻结=运营、废弃复活重走审核（Q20） |
| 已冻结 | 单条原子暂停（≠PWS 冻结，注意区分） | 解冻不重审（Q20） |
| 已废弃 | 终态（可恢复=重走审核） | Q20 |
| 已驳回 | → 已通过（复活重提） | pending_evidence 超时自动驳回可复活（Q18） |
| 合规暂停 | 合规角色触发；恢复须合规角色复核 | Q20 |
| 归档 | 终态 | — |

### 2.3 skill7（横切 · Skill 输出状态机，line 11314）
| 状态 | 迁移 | Guard/条件 |
|---|---|---|
| ai_suggested | → pending_review | Critical Skill 输出必须走候选通道 |
| pending_review | → confirmed / modified / rejected | 人工 Gate |
| confirmed | → applied / archived | 应用到正式对象 |
| modified | → applied / archived | 人工修改后应用 |
| rejected | → archived | 拒绝后归档 |
| applied | 应用态 | — |
| archived | 终态 | — |

> **实现补登（2026-09-14，M10 切片 e，Q76；WF-02 切片 Q78；WF-01 切片 Q79/Q81；WF-03 切片 Q80）**：通道落 `app/core/skill7/`；`ai_suggested` 为生产者侧态，外部投递落库即 `pending_review`，不持久化 ai_suggested 行【实现补】。confirmed/modified → 适配器应用后置 `applied`（不经过独立 confirmed/modified 持久态，二者体现在 human_modified 与审计动作上）；rejected → `archived`。已接入五个 target_type 适配器：`pwc_combo`（WF-04）复用既有 `pwc/funnel`，`field_plan`（WF-02，Q78）复用既有 `fieldpool.submit_plan`，`c1_recognition`（WF-01，Q79）复用既有 `modeling.submit_recognition`，`atom_batch`（WF-03，Q80）复用既有 `atom.submit_batch`（强制 source=ai），`c7_layer4`（WF-01，Q81）复用既有 `modeling.resolve_c7`——AI 候选落库后仍走各自待 Gate/三分支/四层兜底/逐条 approveAtomGuard→下游流程，skill7 不替代任何既有机械逻辑或 Gate（c7_layer4 落 L1/2/3 时提案不生效；L4 候选仍过段3 Q13 dictionary_admin）。投递侧契约校验按 WF 步骤 `producer_step_for(...).candidate_target/single_candidate` 分派（Q78 起不再硬编码 pwc_combo；Q79 单候选约束声明化；Q80 atom_batch 复用同一整批单候选声明；Q81 同一 WF 第二个产出步骤 TYPE-MATCH 复用同一机制）。Q79-4 起 skill_runs/skill_candidates 双锚点（PS 或 intake，后者 product_space_id 改 nullable，迁移 0013；atom_batch 走 PS 锚点，c1_recognition/c7_layer4 走 intake 锚点，无新迁移）。Q81 同时将 resolve_c7 Layer4 盲插改为同名 c7_layer4 全局候选复用（与 wf02_dim_source 同口径，避免 uq(source_layer,field_name) 冲突）【实现补】。Q82 起新增 `source=llm_auto` 运行来源（进程内真 LLM 系统 Actor 投递，角色门只在触发端点与既有投递侧，系统 Actor 不授角色 Q66），SkillRun 增 model_id/input_cost/output_cost/currency_code；候选状态机本身不变。

### 2.4 G1 类目状态机（段2）
| 状态 | 说明 | Guard/条件 |
|---|---|---|
| active | 正常可用 | — |
| draft | 草稿 | — |
| review | 审核中 | — |
| deprecated | 已废弃 | — |
| archived | 已归档 | — |
| merged | 合并（merged_into 永久重定向，否则历史 PS 悬空） | A6 |

### 2.5 PWS 版本状态（段6 · Q28-Q33）
| 状态 | 说明 | Guard/条件 |
|---|---|---|
| 待冻结（pwsReadiness 检查中） | 5 项就绪门全绿出待办推 BO-07 | 就绪后 7 天未冻升级（Q28） |
| frozen | 可消费（下游段 7-11 唯一合法输入） | 必须 BO-07 + 人工 Gate（红线，line 7674） |
| superseded | 旧版只读保留（同刻仅 1 个 active） | Q30/Q31 |
| active | 当前版本（段 11 Guard⑦ 要求） | Q53 |
| revoked | 急停（立即断消费，作废后重冻新版） | Q32 |

> **实现补登（2026-09-14，M6 后端切片）**："待冻结"不落状态——evaluate 仅机械求值 5 门并在全绿时出 pws_ready OpsTodo（7 天 due，幂等；升级复用 M2 sweep）；快照落库即 frozen。"active"不单独成态：frozen + is_active=true 为当前版本，重冻时旧版翻 superseded/is_active=false 并写 supersede+refreeze 双日志，revoked 亦 is_active=false；superseded/revoked 为只读终态，不可再作废/再当活动版（Q32 作废后须重冻新版，仍过 5 门）。重冻触发原因 → Q29 三档（forced/suggested/none），已存在 active 版时原因缺失或未知 422、none 档 409。

### 2.6 PWC 状态流转（段5 · line 1780-1806 + Q24）
| 状态 | 已知触发 | Guard/条件 |
|---|---|---|
| 候选 | 组合生成（漏斗产出） | 预筛→检测→评分→限量（Q21） |
| 待Gate | 进审核 | 人工 Gate |
| 待用 | 审核通过入待用池（库容默认 100） | Q27 |
| 已用 | 同平台+账号+发布位用 1 次 | 跨平台可复用；全平台用尽转已用（Q24） |
| 冷却 | 同平台 7 天消费 ≥3 次 | 14 天回待用（Q24） |
| 爆款 | 一期手工标注；自动判定留段 13（Q61 中位数 5 倍+门槛） | Q24/Q61 |
| 阻断 | 冲突/合规阻断 | Q26 |
| 待入库 | 入库前 | 【待补】 |
| 归档 | 终态 | — |

### 2.7 平台适配四态（段7 · PT-PLATFORM-ADAPTER）
| 状态 | 说明 | Guard/条件 |
|---|---|---|
| allow | 允许 | 只读 frozen PWS；AI 输出一律 pending_review 需 HumanGate |
| downgrade | 降级 | 降级动作只能从 Q38 动作字典选 |
| block | 阻断 | 最严 |
| pending_review | 待审（AI 候选默认态） | 禁止生成 final_id、禁止输出成稿 |

### 2.8 发布位/平台规则 Gate 状态（段7）
| 状态 | 说明 | 来源 |
|---|---|---|
| pending_gate | AI 拓展候选默认态（四维全 0） | line 1098-1221 |
| approved | 过 Gate 启用 | Q35 |

### 2.9 客户审阅动作（段12 · Q59）
| 动作 | 结果 | Guard/条件 |
|---|---|---|
| 通过 | 转"客户已确认"进发布 | — |
| 驳回 | 必选原因，退运营，原因回流段13 | 原因必填 |
| 改稿 | 强制重过 CONTENT-COMPLIANCE 复检（4 项），不过不生效 | 复检=词库扫描+语义级+施工指令+国家规则 |

### 2.10 原子 evidence 状态（段4 · Q18）
| 状态 | 说明 | Guard/条件 |
|---|---|---|
| pending_evidence | AI 自动补一轮 → 运营待办 → 7 天超时自动驳回 | 超时自动驳回可复活 |
| evidence 完备 | 可进审核 | evidence 必填 |

### 2.11 冷启动三分支（段2 · Q1/Q3，流程分支非状态机）
- conf ≥ 行业阈值 → direct_approve
- [0.6, 行业阈值) 或 Top1-Top2 差 <0.1 → ops_assist（运营待办选定，客户无感知；72h 未处理升级；全否转 cold_start）
- conf < 0.6 → cold_start（推 B2 生成候选类目 → 申请单进"类目创建中"）

### 2.12 content_products 内容成品状态机（段12 · Q56/Q59，**实现补登** Q116）
> 原文只给五态语义与 Q56 重生成 ≤3、Q59 客户三动作，未给完整迁移表；下表为 Q116 实现补登的机械口径（`app/content/statemachine.py`）。

| 当前态 | 事件 | 条件 | 目标态 | 副作用 |
|---|---|---|---|---|
| draft | generate | operations 触发，final_id 存在 | generating | 建 content_products 行并对 FCW 只读组装材料 |
| revising | generate | 同批（改稿后重生成，operations） | generating | `regenerate_count`+1 |
| generating | complete | 模型返回 + 词库复检完成 + 语义级复检（Q121，advisory）+ ARTICLE-QC 质检（Q120） | review | body 落库、review_hits（含 semantic 段）落库、quality_score/issues 落库（advisory，不驱动迁移） |
| review | approve | 客户通过 | ready_for_publish | 进发布（运营用托管账号发布 → Q125 回填链接，published_at 非空即已发布；Q60c 回填一环已落） |
| review | reject | **原因必填** | rejected | 原因数据回流段13 |
| review | revise | `regenerate_count` < `content.regen_limit`（默认 3、运营可配，Q120 接通） | revising | 改稿须强制重过复检（Q59） |
| revising | **manual_resubmit** | **Q122/Q56-a 客户人工改正文后提交**（PATCH body；不调 ARTICLE-GEN、不增 regenerate_count） | review | 重跑词库 + 语义复检 + ARTICLE-QC；审计 content.body_edited |
| 任意 | 达重生成上限 | `regenerate_count` ≥ `content.regen_limit`（默认 3） | 仅可 reject | 转人工；运营亦可对 review/revising/rejected 显式作废（Q124，见下） |
| review / revising / rejected | **discard** | **Q124 operations 显式动作**，reason 必填 1–500 字 | **discarded（新终态、只读）** | 落 discard_reason + 审计 content.discarded；partial unique index 释放同键生成机会（回池），旧行保留——**Q187 起「保留」是有条件的**：超过配置中心 `content.discard_retention_days`（默认 180 天）的行由第五个 SLA sweep 作业物理删＋逐行 `content.discard_purged` 审计，**有下游引用（effect_records/effect_claims/import_jobs）的行留档不删**，整块动作受 env `LOOM_DISCARD_PURGE_ENABLED` 门控、默认关；draft/generating/ready_for_publish 不可作废，终态上无可用事件 |

> 枚举码：`draft/generating/review/ready_for_publish/rejected/revising/discarded`（Q124 起七态）原样不翻译进消息表；discarded 为终态，客户页显弱化只读 chip 与作废原因。
>
> **发布信号（Q125）**：ready_for_publish 之后不迁移状态，运营在管理端内容运营台回填 `published_url`/`platform_post_id`，首次回填落 `published_at`（非空=已发布）；待发布 / 待处置（needs-attention）两跨租户队列见上表端点。Agent 抓取与 effect-callback 推送随段13 P3/V2。

---

> **信息保全**：API 与状态机全部条目来自 v3 Part A/C/D 原文（逐项带 line/Q 来源）；原文未定义的事件/迁移/字段已显式标注【待补】，未新增虚构逻辑。PWC 状态"待入库"等原文仅列名的迁移为待补项（属开发第 0 步范围，见 01 §7）。
