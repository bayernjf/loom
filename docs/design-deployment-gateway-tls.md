# 部署候选：网关与 TLS 归属（待裁项① → 候选三案）

> 状态：✅ **已裁决并落地**——负责人 2026-10-04 选**甲**（02 C1.222／Q279），仓内反代产物＋入站面契约门已上线；
> §1 末两个非业务暴露面亦各自收口（文档面由 Q279 网关 404 拦截、prometheus 宿主口由 **Q289** 绑回环）。
> 本文其余部分保留为裁决前的候选材料（逐片记录不回改）。
> 产出批次：Q274（2026-10-04，02 C1.218）
> 运行手册：docs/17 §1.1–1.2（启动与实测读数）、§7.8（`infra/gateway-rehearsal.sh` 演练）；门：`tests/unit/test_gateway_surface_contract.py`。
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
  | `/docs`、`/redoc`、`/openapi.json` | FastAPI 自带交互式文档/OpenAPI 模式，**应用默认开启**（`backend/app/main.py:149` 实例化未传 `docs_url/redoc_url/openapi_url`，2026-10-04 复核实证）；生产建议网关**默认拦截**或应用侧 env 门控关闭，**不在放行之列** | main.py:149（实证；Q309 复扫订正为 `:147`，旧作 `:145`） |
- **两个待清理的非业务暴露面（2026-10-04 复核新发现，三案共同前置，工程侧不代裁）**：
  1. **FastAPI 交互式文档面**：`backend/app/main.py:149` 的 `FastAPI(...)` 未禁用文档，故 `/docs`（Swagger UI）、`/redoc`、`/openapi.json` 在任何部署形态下默认开放且无鉴权——网关上线时若不显式拦截，等于把完整 API 目录公开到公网。 **✅ 随 Q279 甲案落地收口**：`infra/caddy/Caddyfile` 对六条面（`/docs`·`/docs/*`·`/redoc`·`/openapi.json`·`/healthz`·`/metrics`）返回 404，应用侧不改；形状由 `tests/unit/test_gateway_surface_contract.py` 逐路径钉住（判 body 不判状态码）。
  2. **monitoring overlay 的 prometheus 宿主口**：`infra/docker-compose.monitoring.yml:23` 为 `ports: ["9090:9090"]`（发布到所有网卡）；同 overlay 的 Grafana 已按 **Q192 负责人决策**绑 `127.0.0.1:3001` 且有契约测试 `test_grafana_is_loopback_only` 硬守，而 prometheus（无认证、含 `/api/v1/query` 查询面）**无回环绑定、无契约**；alerting 演练探针一律 `docker exec` 走容器网格内（docs/17 §7.6），宿主 9090 无已知消费者。监控 profile 默认不启，不阻塞 beta，但与 Q192 同纪律的处置（绑回环）建议一并裁决。 **✅ Q289 已裁决并落地（2026-10-05「按你建议来」）**：现同一位置在 `:25`＝`ports: ["127.0.0.1:9090:9090"]`（本批新增两行注释使锚点下移），网格内消费不受影响，hardening 门断言 prometheus＋grafana 两口绑回环。
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
4. 两个非业务暴露面的处置（建议随网关案一并裁决，见 §1 末）：① `/docs`·`/redoc`·`/openapi.json`——网关默认拦截，还是应用侧加 env 门控在生产关闭（工程侧倾向前者零应用改动，或两者都做纵深防御）；② prometheus `9090` 是否按 Q192 Grafana 同纪律绑回环（一行配置＋一条契约测试，工程侧可即落）。

**裁决结果（四点全部有主，工程侧未代裁）**：

| 点 | 裁决 | 落地 |
|---|---|---|
| 1 选案 | **甲**（负责人 2026-10-04「好的，你搞吧」） | Q279＝`infra/caddy/Caddyfile`＋`infra/docker-compose.gateway.yml`（第 5 个 overlay），02 C1.222 |
| 2 域名 | 沿用 `loom.bayjf.com`（建议随甲案采纳） | `LOOM_GATEWAY_DOMAIN` 默认值⇄`LOOM_PUBLIC_BASE_URL` 同域不变式由 Q287 三条门守着（docs/17 §1.1） |
| 3 演练纳入 | 纳入 | Q282＝第八套 `infra/gateway-rehearsal.sh`（四段 23 断言，docs/17 §7.8） |
| 4 两个暴露面 | ① 网关默认拦截（甲案自带）／② 绑回环（负责人 2026-10-05「按你建议来」） | ① 随 Q279 落地；② **Q289**＝`127.0.0.1:9090:9090`＋契约门，02 C1.232 |

**真实 ACME 签发仍未证**——本机只以 `localhost`＋Caddy 内部 CA 验过路由／拦截／308 跳转；须部署机执行 `-f docker-compose.gateway.yml up -d`＋设 `LOOM_PUBLIC_BASE_URL`（docs/17 §1.2 首启实测）。

## 6. 落地后动作（工程侧待命，不预执行）

- 甲/丙：写 overlay＋Caddyfile/nginx conf＋放行契约测试（断言 `/mcp` 与 `/.well-known/*` 在放行清单、gateway 为唯一发布口）＋演练脚本扩展。
- 乙：补 docs/17（或 docs/22）「部署放行口径」一节＋示例片段。
- 统一：docs/17/docs/22/handoff/AGENTS 同步；02 登记 Q275；docs/20 §7.4/#1 加收口注记。
