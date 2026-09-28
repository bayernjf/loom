# 22. 外部系统接入手册（Agent Key ／ A2A ／ MCP）

> **定位**：给"要调用 Loom 的机器"看的单一入口。三份文档分工——
> [docs/11 §2.7](11_API规范_OpenAPI.md) 登记 API Key **治理端点契约**（签发/列出/吊销的响应模型与角色闸）；
> [docs/design-a2a-vassal.md](design-a2a-vassal.md) 是 A2A 的**设计草案与裁决**（为什么做、明确不做）；
> **本文件是可执行接入步骤**（拿 Key → 探能力 → 调工具 → 读回执）。三者冲突时以代码与本文件的 file:line 实测为准。
>
> **事实纪律**：下文每个字段、状态码、常量都标了代码位置（2026-09-28 读码核对）。§5 的样例是**当天真进程实测输出**（一次性 pg16＋真 redis＋真 uvicorn，非测试替身）；规范里没取到的口径明标【原文未取到，待补】，不冒充"已符合规范全文"。

---

## 0. 机器可达的三条入口

| 面 | 入口 | 凭证 | 门控 | 会动链吗 | 代码 |
|---|---|---|---|---|---|
| A2A（Q150） | `POST /api/a2a/tasks` | Q88 Agent Key `loom_…` Bearer | **无门控，一直在线** | 否（plan only） | `app/core/a2a/router.py:71` |
| A2A 发现 | `GET /api/a2a/agent-card`、`GET /.well-known/agent-card.json`、`GET /.well-known/agent.json` | 公开无凭证 | 无 | — | `app/core/a2a/router.py:56,61,66` |
| MCP（Q232） | `POST /mcp` | 同上（同一套 Q88 Key） | `LOOM_MCP_ENABLED` **默认关** | 否（plan only） | `app/core/mcp/router.py:35`、`app/core/config.py:126` |
| 效果回流（Q126） | `POST /api/effect-callback` | 同上 | 无 | 是（写 `effect_records`） | `app/core/effects/router.py:68`；契约见 docs/11 §2.1 |

三条要点：

1. **凭证只有两种，不能互换**：机器用 `loom_` 前缀（`app/core/api_keys/service.py:22`），内部人员用 `loom_staff_`（Q178）。全仓 `require_agent_key` 的调用方**恰好三处**（`app/core/a2a/router.py:30`、`app/core/mcp/router.py:32`、`app/core/effects/router.py:45`，2026-09-28 grep 实测）——没有第四处，也没有任何机器凭证能碰发证两口（`final_id` 两口只认 staff 令牌，docs/11 §2.8／Q203）。
2. **plan 面不发证、不花 token、不越 Gate**：A2A 卡片的自述与 MCP 的 `instructions` 都是代码常量（`app/core/a2a/card.py:37-43`、`app/core/mcp/server.py:102`），实测 `cost.llmTokens = 0`（§5）。
3. **鉴权先于门控**：MCP 关闭时，无凭证回 **401** 而不是 404——外部连"这个面存不存在"都问不出来（`app/core/mcp/router.py:39` 的依赖在函数体之前求值，§5 真进程实测）。

---

## 1. Agent Key：唯一的入站机器凭证（Q88）

### 1.1 形态

- 明文 `loom_` + `secrets.token_urlsafe(32)`，**全长 48**；库里只存 sha256 与 12 字符展示前缀，**明文仅签发响应里出现一次**（`app/core/api_keys/service.py:30-33`、`app/core/api_keys/models.py:21-34`）。
- 状态只有 `active` / `revoked`（`app/core/api_keys/models.py:34`）。

### 1.2 签发 / 列出 / 吊销

| 动作 | 端点 | 角色要求 | 代码 |
|---|---|---|---|
| 签发 | `POST /api/admin/agent-keys` → **201** | body `actor` 须含 `platform_admin` | `app/core/api_keys/router.py:35` |
| 列出 | `GET /api/admin/agent-keys?include_revoked=false` | Q109 门控关有意免闸；Q178 门控开需 staff 令牌 | `app/core/api_keys/router.py:55` |
| 吊销 | `POST /api/admin/agent-keys/{key_id}/revoke` | `platform_admin` | `app/core/api_keys/router.py:67` |

请求体形状（`app/core/api_keys/schemas.py:8-10`）：`{"name": "<用途名>", "actor": {"id": "<人员 id>", "roles": ["platform_admin"]}}`。
`name` 空或全空白 → 422（`app/core/api_keys/service.py:54` 的 `ValueError` 在 `app/core/api_keys/router.py:49` 转 422）；角色不足 → 403（`router.py:47`，同文件）。
审计：`agent_api_key.issue` / `.revoke`，tenant 恒 `_platform`（`app/core/api_keys/service.py:64-72`、`93-102`）。

> **令端口径分岔提醒**（与 docs/19 §0.1 同一条）：`LOOM_STAFF_AUTH_ENABLED` 开起来之后，签发这一步也要 staff 令牌；未开门控时按上表自报 `actor` 即可。

### 1.3 验签语义

`require_agent_key(session, Authorization)`（`app/core/api_keys/service.py:124-135`）：非 `Bearer …` 格式、未知、已吊销、空串**一律同一个 401** `invalid or revoked agent API key`，不区分原因以防凭证探测侧信道（`app/core/api_keys/service.py:106-121`）。命中时顺带写 `last_used_at`，并把该 Key 的身份登记为**已验真凭证**——审计以此为准，不认 body/query 里自报的 actor（Q196 口径，`app/core/identity.py`）。

### 1.4 接入方要做的事

把明文 Key 放 `Authorization: Bearer <key>`，**不要**放 query 或 body。轮换＝签新 Key → 切流 → 吊旧 Key（没有"更新"端点）。

---

## 2. A2A（Q150）：对上游编排系统（Zeus）的任务面

### 2.1 发现：三个公开 GET

`/api/a2a/agent-card`、`/.well-known/agent-card.json`、`/.well-known/agent.json` 返回**同一张卡片**，带 `Cache-Control: public, max-age=300`（`app/core/a2a/router.py:52-53`）。卡片单一事实源＝`app/core/a2a/card.py:46`。

关键字段（实测 §5）：`name=loom`、`version=0.1.0`、`capabilities={streaming:true, pushNotifications:false, stateTransitionHistory:true}`、`defaultInputModes/OutputModes=["application/json"]`、`preferredTransport="JSONRPC"`、`authentication={schemes:["bearer"]}`、`skills[]`（三件，见 2.3）、`x-zeus-fealty`（**上游归属声明**：`swornTo=zeus`、`dataPolicy=read-task-scope`、`sla.ackSeconds=10`；键名与取值是 Q150 定下的对外契约，**不改名**）。

⚠️ **`url` 字段是相对路径 `/api/a2a/tasks`**：`build_agent_card()` 只在 `settings.public_base_url` 存在时拼绝对地址（`card.py:47-48,55`），而 `public_base_url` **不是 `Settings` 的字段**（2026-09-28 grep `app/core/config.py` 零命中），所以当前出厂卡片 `url` 恒为相对值。**接入方须自行以部署域名补全**；这属可改进项，登记在 §6。

### 2.2 任务端点

`POST /api/a2a/tasks`（`app/core/a2a/router.py:71`）：Q88 Bearer 保护；`tasks/sendSubscribe` 走 SSE，其余走同步 JSON。

### 2.3 四个方法与状态机

| method | 参数 | 返回 | 代码 |
|---|---|---|---|
| `tasks/send` | `params.message`（须 `role=user` 且 `parts` 为 list） | 终态 task | `rpc.py:157-165` |
| `tasks/sendSubscribe` | 同上 | SSE：`submitted`→`working`→`artifact-update`→`completed`(final)→末帧 task | `router.py:78`、`rpc.py:98-146` |
| `tasks/get` | `params.id` | task（剥内部键）或 `-32001` | `rpc.py:167-172` |
| `tasks/cancel` | `params.id` | task；已终态 → `-32002` | `rpc.py:174-182` |

状态取值：`submitted` / `working` / `completed` / `input-required` / `failed` / `canceled`（终态三件 `rpc.py:12`）。任务存**进程内存**，TTL 30 分钟、上限 500 条（`rpc.py:24-25,30-35`）——**多副本部署下 `tasks/get` 不保证命中**，这是第一阶段刻意边界（第二阶段＝持久化，随 V2，见 §6）。

`x-zeus-runId`：放在 `message.metadata` 里，会原样回显在事件与 task.metadata（`rpc.py:68,78,95`）。

### 2.4 三个 plan skill 与必填参数

`app/core/a2a/skills.py:5-30`，缺任一必填 ⇒ 任务进 `input-required`（终态、`message` 列出缺哪些，`skills.py:46-51`）；未知 skill ⇒ `failed`（`skills.py:40-45`）。

| skill id | 必填 | 段落 |
|---|---|---|
| `generate-content` | `tenant_id`, `product_id` | 段 12 |
| `compliance-check` | `tenant_id`, `content_id` | 段 11 |
| `effect-backfill` | `tenant_id`, `content_id` | 段 13 |

产物 `artifacts[0]`＝两件 parts（data 件含 `mode/skill/params`，text 件是编号步骤列表）＋ `x-zeus-report`（`summary`/`evidence`/`cost`/`followUps`，`rpc.py:108-121`）。

### 2.5 错误码（`rpc.py:14-22`）

`-32700` 解析错 ／ `-32600` 非法请求 ／ `-32601` 方法不存在 ／ `-32602` 参数非法（含 `message` 形状不对、`parts` 里没 `skill`）／ `-32603` 内部错 ／ `-32001` 任务不存在 ／ `-32002` 任务不可取消。

### 2.6 审计

每次产出 task 的调用记一条 `a2a.task`（tenant `_platform`、actor＝Key 的 `key_id`、detail 含 `skill`/`state`/`run_id`），`input-required` 也留痕——`app/core/a2a/router.py:33-49`；SSE 路径在流结束后于 `_subscribe_stream` 末尾落同一条审计（`app/core/a2a/router.py:90-101`）。

---

## 3. MCP（Q232）：把同样三件 plan 能力以 MCP 工具暴露

### 3.1 启用

`LOOM_MCP_ENABLED=true` 才开（`app/core/config.py:126` 默认 `False`）。**刻意不写进 `backend/.env.example`**，与本仓运维旋钮同一惯例（Q161/Q178 同型）。回滚＝关掉该 env 重启，面即消失（404）。

### 3.2 方法与必带字段

单一入口 `POST /mcp`，JSON-RPC 2.0。对端规范版本＝ **`2026-07-28`**（`app/core/mcp/server.py:23`），该修订的事实按官方页逐条取（本仓实现依赖这几条，均已在 §3.6 标注符合度）：

- **移除协议级 sessions 与 `Mcp-Session-Id` 头** ⇒ 本面无状态，不需要 sticky routing；
- **移除 `initialize`／`notifications/initialized` 握手**，服务端 **MUST** 实现 `server/discover` ⇒ 调 `initialize` 得 `-32601` 并在 message 里指明改用 `server/discover`；
- 每个请求在 `_meta` 带 `protocolVersion`（`params._meta` 或顶层 `_meta` 都接受，`server.py:163`）；版本不认识 ⇒ **`-32022`**；
- **所有 result 必带 `resultType`**（`complete` / `input_required`）；
- `tools/list` 结果必带 `ttlMs`（=300000，与 A2A 卡片 300s 同值）与 `cacheScope`（=`private`，面在鉴权之后）与 `nextCursor`（=`null`，工具表静态）（`server.py:85-87,106-113`）；
- `tools/call` 结果＝`{resultType, content:[{type:"text",…}], isError}`，成功时另带 `structuredContent`（`server.py:124-153`）。

支持的方法：`server/discover`、`tools/list`、`tools/call`、`ping`；其余（含 `resources/list`、`prompts/list`）一律 `-32601`。

### 3.3 三个工具 ↔ skill 映射

`server.py:33-79`。工具名是 skill id 的下划线化，内部 `skill` 键不外泄（`server.py:82`）。

| MCP 工具 | A2A skill | 必填 arguments |
|---|---|---|
| `loom_plan_generate_content` | `generate-content` | `tenant_id`, `product_id` |
| `loom_plan_compliance_check` | `compliance-check` | `tenant_id`, `content_id` |
| `loom_plan_effect_backfill` | `effect-backfill` | `tenant_id`, `content_id` |

**治理红线（有测试钉住）**：MCP 面上永远只有 plan 三件；出现 `fcw`／`assemble`／`issue`／`approve`／`gate`／`publish` 任一字样的工具即判红（`tests/unit/test_mcp_server.py::test_tools_expose_no_issuance_or_chain_writes`）。

### 3.4 参数与重试语义

- 缺必填 ⇒ `resultType: "input_required"` ＋ `inputRequests[]`（每项 `name`/`reason`/`required`），**这不是错误**（`isError:false`）；补全 `arguments` 后重发同一 `tools/call` 即可（无状态，无需 session）。
- `arguments` 传了非对象（数组/字符串/数字）⇒ `-32602`。**注意别写 `params.get("arguments") or {}`**：`[]`／`0`／`""` 都是假值会被当"没传"放过，代码里已按 `is None` 判（`server.py:181-186`，2026-09-28 实测红→修→绿）。
- 未知工具名 ⇒ 工具级错误（`resultType:"complete"`, `isError:true`, 文本列出可用工具），不是协议错误。

### 3.5 审计

每一次**通过鉴权**的请求记一条 `mcp.request`（tenant `_platform`、actor＝`key_id`、detail＝`{agent_key, method, tool, result_type, error_code}`），错误与 `input_required` 同样留痕（`app/core/mcp/router.py:52-72`）。门控关闭时的请求**不写审计**（函数体未执行）。

### 3.6 与 `2026-07-28` 规范的符合度自评

| 项 | 状态 |
|---|---|
| 无 session／无握手／`server/discover` 在位 | ✅ 按已读到的规范事实实现 |
| `resultType`、`ttlMs`、`cacheScope`、`-32022`、`input_required` | ✅ 已实现并有单测钉字段 |
| `server/discover` 的**完整响应 schema** | 🟡【原文未取到，待补】——`discover_result()`（`server.py:94-103`）的字段集是本仓自定，官方页当时未给出完整结构，**不得对外宣称"完全符合规范"** |
| 工具 id 的**字符约束正则** | 🟡【原文未取到，待补】——只读到"须遵循严格的大小写与字符约束"一句，本仓取最保守的 `[a-z0-9_]` 子集 |
| Streamable HTTP 之外的传输 | ⬜ 不做（旧 HTTP+SSE 传输已被该修订废弃；本面只有一条 `POST /mcp`） |
| prompts / resources / sampling | ⬜ 不做（无对应能力，§6） |

---

## 4. 效果回流：唯一会写业务数据的机器入口

`POST /api/effect-callback`（Q126）是**受 Agent Key 保护的业务端点**，契约不在本文重复：见 [docs/11 §2.1](11_API规范_OpenAPI.md)（幂等键 `(content_id, captured_at)`、metrics 缺席记 NULL 不补 0、matched/orphan 分流、整批 all-or-nothing）。客户侧自助回填走 `POST /api/effects/backfill`（Q128，**无 Agent Key**、body 内 `tenant_id`＋`actor`，`app/core/effects/router.py:95`）。

接入方选型口径：**机器对机器**（有 Key）→ `/api/effect-callback`；**客户在自己后台点**→ `/api/effects/backfill`（含 Q156 CSV／Q160 xlsx／Q161 异步任务三口）。

---

## 5. 端到端联调（2026-09-28 真进程实测输出）

**环境**：一次性容器 `pgvector/pgvector:pg16`（宿主 55455）＋ `redis:7-alpine`（宿主 6399）→ `alembic upgrade head` 到 `0042_g1_category_seed` → `LOOM_MCP_ENABLED=true` 起真 uvicorn（127.0.0.1:8123）。以下每条都是**当时终端上的实际输出**，不是设想；样例里的路径不含真实域名，接入方替换成自己的 base URL。

```bash
B=http://<loom-host>                       # 实测用的是 http://127.0.0.1:8123

# 1) 探能力（公开）
curl -s $B/api/a2a/agent-card
# → HTTP 200，Cache-Control: public, max-age=300
#   name=loom  url=/api/a2a/tasks（相对，见 §2.1 ⚠️）  skills=[generate-content, compliance-check, effect-backfill]

# 2) 签一把机器 Key（明文只出现一次，务必当场存好）
curl -s -X POST $B/api/admin/agent-keys -H 'content-type: application/json' \
  -d '{"name":"zeus-integration","actor":{"id":"ops-1","roles":["platform_admin"]}}'
# → HTTP 201，secret 长度实测 48、前缀 loom_…

# 3) A2A 任务
curl -s -X POST $B/api/a2a/tasks -H "authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tasks/send","params":{"message":{"role":"user","parts":[
        {"kind":"data","data":{"skill":"compliance-check","tenant_id":"t1","content_id":"c1"}}]}}}'
# → HTTP 200  status.state=completed  artifacts[0].parts=2
#   x-zeus-report.cost={"llmTokens":0,"wallSeconds":0.0}     ← plan 不花 token 的实测证据

# 4) A2A SSE（tasks/sendSubscribe）
curl -s -N -X POST $B/api/a2a/tasks -H "authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":9,"method":"tasks/sendSubscribe","params":{"message":{"role":"user","parts":[
        {"kind":"data","data":{"skill":"generate-content","tenant_id":"t1","product_id":"p1"}}]}}}'
# → content-type: text/event-stream／cache-control: no-store／x-accel-buffering: no
#   实测 5 帧：submitted → working → artifact-update → status-update(completed, final) → 末帧 task

# 5) MCP
curl -s -X POST $B/mcp -H "authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
# → HTTP 200  tools=[loom_plan_generate_content, loom_plan_compliance_check, loom_plan_effect_backfill]
#   ttlMs=300000  cacheScope=private

curl -s -X POST $B/mcp -H "authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"loom_plan_compliance_check","arguments":{"tenant_id":"t1"}}}'
# → resultType=input_required  inputRequests=[{"name":"content_id","reason":"required parameter missing","required":true}]

curl -s -X POST $B/mcp -H "authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":3,"method":"server/discover","params":{}}'
# → protocolVersion=2026-07-28

# 6) 三类被拒（都是实测）
#   无 Key / 错 Key / 已吊销 Key          → HTTP 401（A2A 与 MCP 同）
#   method=initialize                     → -32601 "…handshake was removed in 2026-07-28; call server/discover instead"
#   _meta.protocolVersion="1999-01-01"    → -32022
#   tasks/get 未知 id                      → -32001
#   LOOM_MCP_ENABLED 关时带合法 Key 调 /mcp → HTTP 404 {"error":{"code":-32601,"message":"MCP endpoint disabled"}}
#   同一关闭状态下不带 Key 调 /mcp          → HTTP 401（凭证先于门控）
```

**落库核对**（同一库）：`select action, tenant_id, actor_id, detail->>'tool', detail->>'method' from audit_logs where action in ('a2a.task','mcp.request');` → 实测 **1 条 `a2a.task` ＋ 6 条 `mcp.request`**，`tenant_id` 均 `_platform`，`actor_id` 均为该 Key 的 `key_id`，且 `initialize`/`-32022` 这类**错误调用也在留痕里**。

---

## 6. 明确不做／待补／等外部输入

| 项 | 状态 |
|---|---|
| A2A 任务持久化跨实例、真 LLM 与链路执行、Zeus↔Loom 真机联调 | ⬜ 第二阶段，随 V2，须点工（02 C1.94；docs/design-a2a-vassal.md「明确不做」条） |
| MCP 的 `prompts`／`resources`／sampling／客户端侧工具 | ⬜ 不做：Loom 只暴露 plan 工具，`server/discover` 里声明的能力集就是 `server.py:101` |
| Agent 侧 OAuth／per-key 作用域／速率限制 | ⬜ 未实现（Q88 只有 active/revoked 两态），`_PREFIX_SHOWN` 仅用于展示 |
| 卡片 `url` 为相对路径 | 🟡 见 §2.1：要么加 `Settings.public_base_url` 字段（env `LOOM_PUBLIC_BASE_URL`，属新旋钮，需点工），要么接入方自行补全。**当前文档按"接入方补全"口径** |
| `server/discover` 完整 schema、工具 id 字符约束正则 | 🟡【原文未取到，待补】，见 §3.6 |
| MCP 面在真实多副本下的行为 | ⬜ 只验过单进程真 uvicorn（§5）；无 session ⇒ 理论可水平扩，未做 HA 演练（七套 harness 里不含本面） |
| 网关与 TLS 归属、首批主数据、V2 客户侧认证、docs/08 排期三列、覆盖率阈值是否成门 | ⬜ **等负责人／业务方，不得代裁**（AGENTS.md 待裁决五项，2026-09-27 复扫口径） |
