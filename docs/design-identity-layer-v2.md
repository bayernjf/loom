# 身份层第二切片 — 决策请求（草案，⬜ 待拍板）

> **状态**：⬜ **待负责人拍板**，本文档零代码零迁移、不作任何裁决。Q178（02 C1.122）落了身份层**第一切片＝内部运营人员 PAT**；本文件把**第二切片必须先定的三个口径**摆开，并给出**用命令实测出来的改造爆炸半径**，供拍板时估代价。拍板后按先例追加 Q 编号再落码。
>
> **为什么现在要问**：Q144 把身份层 P0-① 定为公网自助的唯一前置；docs/20 §6.6 #1 记着"客户侧真实认证、`actor↔tenant` 绑定（Q88 口径待补）、账号密码/会话仍 V2"。这几句里**没有一句能直接落码**——落之前必须先有裁决，而裁决的三个选项代价差一个数量级，所以先测量再问。

## 1. 实测现状（每条附测量方法，可复跑）

| # | 事实 | 出处 |
|---|---|---|
| 1 | 全仓 **205 条路由**（`grep -rhoE "@router\.(get\|post\|put\|patch\|delete)\(" app` 去重计数＝204，另 `@customer_router.get` 1 条）＋ `@app.get("/healthz")` | `backend/app/**/router.py` |
| 2 | **只有 4 处**校验真实凭证：Q88 Agent Key 两处（`core/effects/router.py:39` 依赖 `:71`、`core/a2a/router.py:30`）、Q178 `internal_gate` 一处（`core/api_keys/router.py:59`）、`/api/auth/me` 一处（`core/staff_auth/router.py:123`）。其余全部依赖调用方**自报**身份 | 同左 |
| 3 | **92 个**请求体模型自带 `actor` 字段并绑在路由入参上，**7 个**自带 `tenant_id`（其中 6 个两者都有）；分布最密的模块＝atom 16／content 11／modeling 10／platform_adaptation 9／condition 9／effects 9 | AST 扫描：按类字段命中，再要求该类名出现在路由函数形参注解里 |
| 4 | `append_audit(` 调用点 **122 处**，`actor_id` 多来自上述自报字段。客户写路径**不经** `require_any_role`，故无覆盖：`core/effects/service.py:393-401` 把 `batch.actor.id/roles` 原样写进审计 | `core/audit/__init__.py:10` |
| 5 | Q178 的覆盖只发生在 RBAC 里：`core/rbac/__init__.py:56-57` `actor.id = authn.id; actor.roles = list(authn.roles)`，且**仅当** `settings.staff_auth_enabled`（`core/config.py:112`，默认 False）且所需角色属内部角色集（同文件 `:46`）；客户角色 `whitelist_owner` 被刻意排除在 PAT 可签发范围外（`:22,26-34`） | 同左 |
| 6 | `tenant_id` 的**存在性/暂停**校验收敛在一个函数：`core/tenants/service.py:199 assert_intake_admitted`，全仓**只有 1 个**业务入口调它（`app/product/product_intake/service.py:38`，段1 准入）。其余租户隔离一律是 `WHERE tenant_id = :declared` | grep 实测 |
| 7 | 客户读口无一处鉴权：`GET /api/effects/analytics?tenant_id=`（`core/effects/router.py:329`）、`GET /api/fcw?tenant_id=`（`final/final_whitelist/router.py:161`）等按**声明的** tenant 过滤 | 同左 |
| 8 | **导出的两个任务口既不鉴权也不按租户收**：`GET /api/exports/jobs/{job_id}` 与 `/jobs/{job_id}/download`（`core/exports/router.py:166,179`）只按 `job_id` 直查，`service.get_job`（`core/exports/service.py:443`）无租户条件——而同族的 Q161 导入口有 `get_scoped_job(session, job_id, tenant_id)`（`core/imports/router.py:87`、`service.py:319`）。**这是两处实现不对称**，属既有缺口而非本次新增 | 同左 |
| 9 | 前端：staff 令牌走 httpOnly cookie `loom_staff_token`＋服务端注入 `Authorization: Bearer`（`frontend/lib/staff-auth.ts:7,14-22`、`lib/api.ts:54-56`）；客户侧**无任何对应物**，tenant/actor 直接取宿主 env（`lib/api.ts:44,48`，客户写口连 `roles` 都是硬编码空数组 `:140`；注释自陈"V1 无真实认证…V2 改会话派生"） | 同左 |
| 10 | 改造代价（测试面）：`tests` 下 **53/96** 个文件显式传 `actor_id=`/`roles=`/`tenant_id=`，关键字形态 **143 处**，JSON body 里 `"actor"` 形态 **714 处** | grep 实测 |

## 2. 三个必须先定的口径（每项给选项与代价，**推荐项排第一**）

### 口径 A：`actor ↔ tenant` 的权威来源是什么？

Q88 当年把机器 Key 刻意**不绑租户**，写下"归属由 `content_id → FCW.tenant_id` 解析"并标【原文未给出，待补】。第二切片必须选一条：

- **甲（推荐）：先做"服务端归属"，不动凭证形态。** 保留现有自报字段做**兼容读**，但服务端一律以"该端点作用的对象反查出的 tenant"为准（写口已有此形状：Q128 客户通道服务端固定 `source`、只命中本租户非 discarded 成品否则整批 422），并给 8 号事实那**两个导出口**补上租户归属与鉴权。代价＝**新代码集中在 2 处路由＋1 个反查工具**，零契约变更、零迁移、`92` 个模型不动。
- **乙：给每个客户发一把 API Key 并绑 `tenant_id`**（`agent_api_keys` 加一列或建 `customer_api_keys`）。语义最干净，但**改 Q88 已裁决的"Key 不绑租户"口径**，且迁移＋治理页＋客户侧持有方式全要重定。代价＝1 迁移＋契约变更＋Q88 需重裁。
- **丙：账号密码＋会话**（Q178 乙案的后半）。这是公网自助的正解，但依赖注册/找回/密码策略规格——**docs 里一条都没有**，现在做必然要工程臆造。代价＝新表＋新端点族＋一堆【待补】需业务先给。

### 口径 B：自报身份还能不能进审计？

事实 4 意味着：任何能打到后端的调用方都能把审计里的"谁做的"写成任意字符串。

- **甲（推荐）：受保护写口的审计 actor 一律服务端派生**，与口径 A 甲同步落地；HTTP 层继续接受自报字段但**只用于兼容**，落库前覆盖。零契约变更，可被"传入他人 actor → 审计仍记真实身份"的用例证伪。
- **乙：从 92 个模型里删掉 `actor` 字段**。最彻底，代价＝**REST 契约破坏性变更**＋事实 10 的 714 处 body 与 143 处关键字全部改写，且 `docs/11` 契约文档要整体回填。
- **丙：只做 B 面（写口），读口保持"声明 tenant 即过滤"**，并把"客户读口无鉴权"明文写进 docs/21 与 docs/17 作为已接受风险。

### 口径 C：beta 阶段客户侧到底要不要真登录？

Q144 裁的是**受控 private beta＝平台代运营**，客户今天**不自助登录**（Q166 analytics 等页都由服务端渲染、身份来自部署 env）。

- **甲（推荐）：beta 维持"代运营＋无客户登录"**，身份层第二切片只做 A/B 两口的服务端归属，把"客户门户登录"留给 V2 自助上线包。
- **乙：现在就做客户登录**（等于口径 A 丙），需先向业务方索取注册/会话/密码策略口径。

## 3. 拍板后我建议的落地顺序（仅供确认，不含工时）

1. 口径 A 甲 ＋ B 甲：一个切片，闭掉"写口身份可冒充"和"导出任务口可跨租户读"两处，零迁移、契约不变，可被证伪用例守。
2. docs/11 补记"自报字段的兼容语义"（读得到、不采信），docs/21 补值班口径。
3. 客户门户登录／Key 绑租户／账号会话，各自单立切片，均需新的负责人裁决与业务输入。

## 4. 本文件刻意不做

- 不写代码、不建迁移、不改任何端点签名——**在拿到裁决前，这些都是禁项**（AGENTS「待裁决事项不擅自裁决」）。
- 不改 §6.6 里 #4/#5/#6/#7/#15–#28 各行状态词与【待补】口径（Q194 同一纪律）。
- 不给工时：08 §2.2 三列（工期/人员/起止）原文未给，仍【待补】。
