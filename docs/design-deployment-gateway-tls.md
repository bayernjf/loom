# 部署候选：网关与 TLS 归属（待裁项① → 候选三案）

> 状态：⬜ **待负责人裁决**（工程侧只产候选，不代裁）
> 产出批次：Q274（2026-10-04，02 C1.218）
> 目的：把 AGENTS/handoff 待裁项①「网关与 TLS 归属」从一句话待裁变成可一键裁决的三案，裁决后 private beta 前提「后端在网关后」即有仓内落地路径。

## 1. 来由与现状（事实，均可溯源）

- **仓内零产物**：全仓 deployable 文件（`infra/`＋`backend/`＋`frontend/` 的 yml/py/ts/conf/Dockerfile，排除叙述性 docs）对 `nginx|traefik|caddy|certbot|letsencrypt|acme|ssl_certificate|tls` **零命中**（docs/20 §12.3#1，Q217 起反复实测，L711 更新）；compose 里 backend **只 `expose 8000` 无宿主端口**、frontend 是**唯一发布口 `3000:3000`**、后端**明文 HTTP**。
- **数据面已收口**：三条数据端口（postgres 5432／redis 6379／minio 9000-9001）全绑 `127.0.0.1`（Q200，02 C1.144）。
- **既定部署形态**：Q144 裁决受控 private beta＝后端内网/网关后、平台代运营、公网自助 NO-GO；Q145 最小部署制品明确「**TLS 由部署环境在 frontend 口外终结**」（`.dockerignore` 句）；frontend 为唯一对外入口。
- **对外入站路径面（网关放行须覆盖的完整清单）**：
  | 路径 | 说明 | 出处 |
  |---|---|---|
  | `/api/*` | 全部业务 API（含 A2A 任务口 `POST /api/a2a/tasks`） | docs/22 §2 |
  | `POST /mcp` | **顶层路径、不在 `/api` 之下**——按 `/api/*` 前缀放行的规则会漏掉这一条 | docs/22 §2.9 / docs/17 Q232 |
  | `/.well-known/agent-card.json`、`/.well-known/agent.json` | A2A 公开只读发现端点 | docs/22 §2 |
  | `/healthz`、`/metrics` | 探活与指标暴露（均默认不鉴权） | docs/17 Q181 |
  | `/`、`/_next/*` 等前端静态面 | frontend SSR 全部路径 | Q145 |
- **Q238 已就位机制**：`LOOM_PUBLIC_BASE_URL` 是 `Settings` 真字段（默认空⇒A2A 卡片 `url` 为相对路径）；**设对外公网域名即输出绝对地址——取值正取决于本裁决**（docs/22 §2.1）。
- **判定影响**：docs/20 §7.4/#1：③ 可上线（受控 private beta）未达标的主因之一＝「后端在网关后」仓内无产物。本裁决落地后该主因即消（剩余 ② 主数据回填与跑链人手仍为外部卡点）。

## 2. 待裁点拆解

| # | 待裁问题 | 选项含义 |
|---|---|---|
| a | 网关/反代**是否入仓** | 仓内制品（可复现、可进演练）vs 仓外边缘（Cloudflare/负载均衡，仓内只补放行文档） |
| b | **TLS 终结位置** | frontend 口外（边缘/负载均衡，符合 Q145 现状句）vs 仓内反代层（统一终结后转发明文到 backend） |
| c | 公网域名与 **`LOOM_PUBLIC_BASE_URL`** 取值 | 例：`https://loom.bayjf.com`（沿用 loom-landing 同域惯例）或新域名——裁决后 Q238 机制才有值 |
| d | 五套全栈演练（ha/load/alerting/restore/pitr）是否**纳入网关面** | 演练命令加 `-f docker-compose.gateway.yml`（若入仓）与否 |

## 3. 候选三案

### 甲案：仓内 Caddy 反代（推荐项：自动 HTTPS、单 YAML、零证书管理负担）

- **形态**：`infra/docker-compose.gateway.yml` 新增 `gateway` 服务（Caddy 镜像），frontend/backend 不再直连宿主，对外唯一入口＝gateway 的 `:443/:80`。
- **路径放行**：`/api/*`、`POST /mcp`、`/.well-known/*`、`/healthz`、`/metrics` 反代到 backend `:8000`；其余全部反代到 frontend `:3000`（SSR）。
- **TLS**：Caddy 自动申请/续期（ACME）；`LOOM_PUBLIC_BASE_URL` 取裁决域名（如 `https://loom.bayjf.com`）→ A2A 卡片输出绝对地址。
- **改动范围**：新增 1 个 compose overlay + 1 份 Caddyfile + 演练脚本加该 overlay 的 smoke（起栈→https 探活→`/api/healthz`→`POST /mcp` 放行验证）；**零应用代码改动**（backend/frontend 均不知情）。
- **依赖面**：需 80/443 可用；ACME 需公网域名解析到部署机。
- **风险/取舍**：仓内多一个容器（轻微）；Caddy 在仓库新引入（此前零命中——但这是部署层新增，非改既有行为）。
- **对 ③ 判定**：落地即满足「后端在网关后」仓内有产物；private beta 前提成立。

### 乙案：仓外边缘网关（Cloudflare/负载均衡），仓内只补放行文档 + 示例

- **形态**：TLS 在边缘终结（如 Cloudflare SSL），回源到 frontend `:3000`（HTTP）；仓内**不新增服务**，只补一份「部署放行口径」文档（docs/17 §新增或并入 docs/22）+ 示例 nginx 片段（供自建边缘参考）。
- **路径放行**：同上清单，边缘规则按 `/api/*`＋`POST /mcp`＋`/.well-known/*`＋`/healthz`＋`/metrics` 分流。
- **TLS**：边缘托管证书；`LOOM_PUBLIC_BASE_URL` 取边缘域名。
- **改动范围**：纯文档（1 份放行口径 + 示例片段）；零容器、零应用代码。
- **依赖面**：边缘平台（用户已有 Cloudflare 账号与 bayjf.com 域，loom-landing 先例）；「后端在网关后」由边缘侧实现，仓内无运行制品可验证。
- **风险/取舍**：仓内依旧无网关制品 ⇒ ③ 的「仓内有产物」表述不成立，但「网关后」事实成立（取决于评审口径认不认仓外）；五套演练不覆盖网关面。
- **对 ③ 判定**：若评审接受仓外边缘=「在网关后」，同样消主因；否则仍需甲/丙。

### 丙案：仓内 nginx + 手动证书（certbot 定时续期）

- **形态**：同甲案布局但反代用 nginx，TLS 证书由 certbot（或托管证书挂载）管理，compose 挂证书卷。
- **改动范围**：overlay + nginx conf + certbot 续期 cron/脚本；零应用代码。
- **依赖面**：证书签发/续期运维面大于甲（ACME 自动 vs 手动/定时）。
- **风险/取舍**：比甲多证书运维；比乙多仓内可验证性。
- **对 ③ 判定**：同甲，落地即满足。

## 4. 裁决建议（工程侧推荐）

- **推荐甲案**：理由＝① 仓内可复现、可进演练（与"仓内零产物"的评审缺口直接对治）；② Caddy 自动 HTTPS 免证书运维（单人/小微团队最省）；③ 零应用代码改动、可随时回滚（down -f ... 即回 Q145 现状）；④ 与 Q145「TLS 在 frontend 口外终结」句兼容（TLS 终结在 gateway 层，gateway 即 frontend 口的"外"）。
- **域名**：沿用 `loom.bayjf.com`（与 loom-landing 同域惯例，用户已在 Cloudflare 配置该域）⇒ `LOOM_PUBLIC_BASE_URL=https://loom.bayjf.com`。
- 若用户偏好零新增容器：乙案 + 评审接受"仓外即网关后"亦可，代价是仓内无运行制品可验证。

## 5. 待负责人 Gate 的点（裁决即登记 02 Q275）

1. 选案：甲 / 乙 / 丙（或组合）。
2. 域名：`loom.bayjf.com` 或指定其他（裁决后我改 `LOOM_PUBLIC_BASE_URL` 一处即可生效，机制已在 Q238 就位）。
3. 五套演练是否纳入网关 overlay（甲/丙时默认纳入，乙时跳过）。

## 6. 落地后动作（工程侧待命，不预执行）

- 甲/丙：写 overlay＋Caddyfile/nginx conf＋放行契约测试（断言 `/mcp` 与 `/.well-known/*` 在放行清单、gateway 为唯一发布口）＋演练脚本扩展。
- 乙：补 docs/17（或 docs/22）「部署放行口径」一节＋示例片段。
- 统一：docs/17/docs/22/handoff/AGENTS 同步；02 登记 Q275；docs/20 §7.4/#1 加收口注记。
