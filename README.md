# Loom · 私域内容生产白名单平台

**AI 驱动的 13 段链内容生产 SaaS 后台**：把"产品信息 → 可发布内容"这件事拆成一条可编排、可审计、可质量拦截的生产链——从产品录入、冷启动建模、字段池与原子管理，到条件包（PWC/PWS）冻结、平台适配、策略/结构/表达三包、合规清洗、`final_id` 组装，最后只读消费给内容生成，再经反馈回流反哺知识进化。

> **本文件只讲三件事：产品是什么／怎么把它起来／代码怎么摆。** 进度与逐批历史不在这里——当前状态与基线看 [handoff.md](handoff.md) 顶部权威行，逐条决策台账看 [docs/02](docs/02_决策记录_ADR_Q1-Q72.md)，按 PRD 逐条验收看 [docs/25](docs/25_PRD逐条验收台账.md)，段级功能比对看 [docs/24](docs/24_功能点比对_ContentOS产品基准.md)。README 原先承载的逐批状态段已于 2026-10-13（Q356）整段逐字移入 [docs/handoff-archive-2026-10-08.md](docs/handoff-archive-2026-10-08.md) 的「三十三、」节，一字未改。

---

## 一、产品

### 1. 13 段链一图流（CHAIN_13）

```
G1类目树 + G2通用字段池（跨类目共享字典）
  │
[1]产品录入(14态状态机) → [2]冷启动建模(C1五信号识别)
  → [3]字段池规划+Gate → [4]字段下原子+逐条Gate(approveAtomGuard 10项)
  → [5]PWC条件包组合(同PS跨字段相撞) → [6]PWS冻结(pwsReadiness 5项) ══下游只能消费 frozen PWS══
  → [7]平台静/动态适配(allow/downgrade/block/pending_review) → [8]PCP平台条件包(17字段权重 Σ≤1.0)
  → [9]CSP/CSTP/CEP三包(layerSpaces通用底座) → [10]合规清洗(block_required 一票否决)
  → [11]final_id组装(Guard全过才生成) ══readonly══ [12]内容生成+合规复检 → 客户审阅发布
  → [13]反馈回流+知识进化(KUP提案→人工Gate→回写G2/原子weight/类目模板)
```

**final 定义**：`final_id` = 6 层快照相加 —— 产品 PWS（私域原子）+ 平台 PCP + 策略 CSP + 结构 CSTP + 表达 CEP + 合规 CCR（5 类通用原子），唯一出口 `E1.1 publishFCW`。

**三端（PORTS）**：用户前端（客户录入/内容中心）/ 管理后端（13 模块）/ 系统后台 API（内容生成系统只读消费白名单）。读者永不接触系统，只作为效果数据来源。

### 2. 为什么是"链"而不是"工具"

- **白名单是相撞产物**：在（产品 + 目的 + 平台/发布位 + 账号/风险）上下文下，各层原子相撞出的可用条件包；不是手写的词表。
- **质量是结构性的**：每段都有人工 Gate / Guard / 评审位，AI 只产候选、不静默生效；`frozen` 快照隔离了"决策"与"消费"两段。
- **可审计可回写**：逐条决策日志（docs/02 C1 台账，编号只增不内嵌于此以免过期）、writeAudit、唯一出口、反馈回流闭环（唯一反向边回到段 3/4/8）。

### 3. 三条产品边界（决定它今天能给谁用）

- **首发形态＝受控 private beta**（Q144）：后端在网关后、平台代运营；公网自助注册已裁 **NO-GO**。
- **客户侧没有登录页**：客户内容口（列表/详情/裁决/正文编辑/语言目录）自 2026-10-30 起强制客户访问令牌（`loom_client_` Bearer，运营经 `/api/admin/client-keys` 签发、绑定租户；部署侧经前端 env `LOOM_CLIENT_TOKEN` 注入），query `tenant_id` 只作与令牌绑定的一致性交叉校验、声明不再产生权限；运营写口一律 `loom_staff_` 个人令牌硬闸。浏览器侧仍没有客户登录页，会话式登录与 `actor↔tenant` 自助绑定＝V2 第一项（见 docs/17 §1.3「这个清单解决不了的三条」）。
- **花钱与生效都要过人**：AI 产出只落候选、人工 Gate 裁决后才生效，`final_id` 只有一个出口；自动补足（restock）、真视频提交、Prompt 修改这类会花真 token／真钱的动作一律 **env 门控默认关＋逐单人工批准**（Q87／Q354）。

### 4. 路线图速览（2026-09-13 Q73 合并后：A7 为骨 + D9 厚度）

- **V1（0–3 月 / 5–10 客户）**：主链段 1→6→10→**11**（到 `final_id` 发证闭环，**不含段 12**）；段 7/8 仅 FCW 必需的静态底表基础版；横切 skill7/writeAudit/RBAC/配置中心/SLA + 审核工作台 + 租户/Onboarding + 前端 8 菜单基础版 + CSV + 质量两件套 + 2 驾驶舱（Token 成本、人工审核）。
- **V2（3–6 月 / 30–50）**：段 7/8 完整（动态信号/fit_score/PLATFORM-ADAPTER）、段 9 三包、段 12 内容生成、段 13 回流/KUP；知识库/Memory/Router/自助门户等 D9 厚度。
- **V3（6–12 月 / 100–200）**：平台化（辅助系统剩余 8 个、BI、Webhook、SDK、移动端、国际化、白牌）。

> 第 0 步规格仲裁（M0）与技术选型 6 项均已于 2026-09-13 完成；任务包明细见 08 §2（V1=M1–M8+M10/M10-Q/M11/M12），裁决记录见 02 C1.17/Q73。

---

## 二、启动方法

### 1. 只跑门禁（本机，不需要任何服务容器）

后端测试跑 sqlite，PG／Redis 都不需要；命令与 CI 逐字一致（`.github/workflows/ci.yml`）：

```bash
# 后端（Python 3.12）：安装与两道门都在 backend/ 下跑（与 CI 的 working-directory 一致）
cd backend
python -m venv .venv
.venv/bin/pip install -r requirements-dev.lock
.venv/bin/pip install -e . --no-deps
.venv/bin/ruff check .
.venv/bin/python -m pytest -q
cd ..

# 模型质量回归（仓库根执行；独立 runner，不进 pytest）
python eval/runner.py

# 前端（Node 20）：类型 + 八道契约门
cd frontend
npm ci
npm run typecheck
node scripts/check-tokens.mjs
node scripts/check-nav.mjs
node scripts/check-content.mjs
node scripts/check-products.mjs
node scripts/check-workbench.mjs
node scripts/check-compliance.mjs
node scripts/check-admin.mjs
node scripts/check-settings.mjs
cd ..
```

> 覆盖率**只测量、不设门**（Q321 裁决；docs/16 §4 的阈值仍是【建议】，CI 用 `--cov=app` 产读数但不接 `--cov-fail-under`）。真 PG16 迁移门与真 Redis 门是 CI 里另四道 job，本机跑需要 `pgvector/pgvector:pg16` 镜像（官方 `postgres:16` 没有 vector 扩展）。

### 2. 本机自己起一套后端＋前端（不经 compose）

```bash
# 数据面：compose 的 postgres 没有口令默认值（Q203），本机也要先给
# infra/.env 由 .gitignore 的 `.env` 规则忽略、不入库；最小集就是一个 POSTGRES_PASSWORD
# （开发值 loom 与 backend/.env.example 的 DSN 对齐；已有该文件的请追加而不是覆盖）
docker compose --env-file infra/.env -f infra/docker-compose.yml up -d postgres redis

# 后端（仓库根）：.env 只放 Settings 字段（Q239 载体契约）
cp backend/.env.example backend/.env
cd backend
.venv/bin/alembic upgrade head
.venv/bin/python -m uvicorn app.main:app --port 8000

# 前端（另开一个终端，从仓库根起）
cd frontend
cp .env.example .env.local
npm run dev
```

> `backend/.env.example` 的 DSN 默认就指向 `localhost:5432` 的 `loom/loom`，与上面这条 compose 链对齐。`LOOM_MASTER_KEY` 是出站供应商 Key 的加密主密钥——容器形态下空值会让 entrypoint 直接 `exit 1`（本机跑 uvicorn 不强制，但要调真模型就得给）。

- `.env` 载体纪律（Q239）：`backend/.env` **只能放 `Settings` 字段**——pydantic-settings 是 `extra="forbid"`，放一个它不认识的名字（如 `LOOM_LLM_BASE_URL_AGNES`）会让进程直接起不来。直读 `os.environ` 的变量走可 source 的 `backend/.env.shell`（`set -a; source backend/.env.shell; set +a`）；本仓没有 `load_dotenv`。
- 出站供应商 Key **不进任何 env 或文件**：它经 Fernet 加密存 `ai_model_keys`，主密钥是 `LOOM_MASTER_KEY`（Q82／Q148）。
- model-hub 知识库消费（M3-W3-5 试点）：ARTICLE-GEN 生成前经 `backend/app/core/knowledge.py` 检索 hub 知识库，命中作为「业务文档参考」段（带出处）追加进生成原料。env 直读 `os.environ`、走 `.env.shell` 载体：`LOOM_KNOWLEDGE_URL`（hub 基址，如 `http://localhost:8791`）与 `LOOM_KNOWLEDGE_TOKEN`（hub project token `mh_…`）**任一缺失即功能整体停用**（fail-closed，不报错不影响生成）；`LOOM_KNOWLEDGE_TIMEOUT_SECONDS` 可选超时旋钮（默认 15s）。运行期超时／HTTP 错误／无命中一律 fail-soft 跳过注入；检索与重排的限流/计费在 hub 侧（30 ingest/h、120 query/h，见 model-hub `docs/knowledge-api.md`）。

### 3. 起真栈部署（docker compose，private beta 官方形态）

```bash
cd infra
# 第 0 步·先写 infra/.env —— 三个不给就起不来（仓内刻意不留弱默认，Q203）：
#   POSTGRES_PASSWORD=…      缺 ⇒ postgres 容器启动即失败
#   MINIO_ROOT_PASSWORD=…    缺 ⇒ minio 容器启动即失败
#   LOOM_MASTER_KEY=…        缺 ⇒ backend entrypoint 打印 FATAL 并 exit 1
# 另两个不设不会崩、但会静默出错：LOOM_GATEWAY_DOMAIN=<域名> 与 LOOM_PUBLIC_BASE_URL=https://<域名>
# —— 二者必须同域，异域时网关演练预检 exit 2（Q287）

docker compose --env-file .env -f docker-compose.yml -f docker-compose.gateway.yml up -d
```

- **迁移自动跑**：backend entrypoint 先 `alembic upgrade head` 再起 uvicorn，失败即退出。起来后宿主只有网关的 80/443，`backend`／`frontend` 都不发布宿主端口。
- **验网关**（不可跳）：`curl -sI https://<域名>/` 期望 200 · `https://<域名>/docs` 期望 404（网关拦） · `http://<域名>/api/atoms` 期望 308。证书必须是 Let's Encrypt 真签——本机只以 `localhost`＋内部 CA 验过路由／拦截／跳转，**真 ACME 至今未证**。
- **引导内部身份**（鸡生蛋，顺序不可反，Q178）：① 门控保持关 → 用自报 `platform_admin` 调 `POST /api/admin/staff-keys` 签首个人员令牌（明文只返回一次）② 浏览器 `/admin/login` 粘贴该令牌（经 `/api/auth/me` 自检写 httpOnly cookie）③ `.env` 设 `LOOM_STAFF_AUTH_ENABLED=true` 并重启 backend。此后内部写口只认真令牌，`?actor_id=&roles=` 自报提权失效。
- **备份是内置的**：`db-backup` 每日 `pg_dump`＋7 天保留，`db-basebackup`＋`wal-archiver` 把基础备份与 WAL 推 MinIO（具备时点恢复 PITR）。监控按需叠 `-f docker-compose.monitoring.yml --profile monitoring`（要另给 `LOOM_GRAFANA_ADMIN_PASSWORD`，无默认值、缺失即报错）。

> 完整投产清单（第 0–4 步＋部署前打勾单＋这份清单解决不了的三条）＝**docs/17 §1.3**；本节只是摘要，冲突以 docs/17 为准。
> 只想在浏览器里点页面：不带 gateway overlay 起 base 即可（`docker compose up -d`），此时 `frontend` 发布 `3000`、postgres／redis／minio 全部只绑 `127.0.0.1`（Q200 #33）、后端在 compose 内网 `backend:8000`。

### 4. 五份 overlay 与八套演练

| 制品 | 什么时候用 |
|---|---|
| `docker-compose.gateway.yml` | 生产形态：Caddy 作唯一对外应用口（80/443），把 frontend 的宿主 3000 收回内网 |
| `docker-compose.monitoring.yml` | 需要 Prometheus＋Grafana＋告警转发时（`--profile monitoring`） |
| `docker-compose.ha.yml` | 多副本／抢锁／Streams worker／配置广播演练（backend 两副本） |
| `docker-compose.staging.yml` | 验收环境：`!reset` 清空 infra 宿主端口、minio 挪出默认 profile |
| `docker-compose.alerting-rehearsal.yml` | 告警链路演练专用叠加层 |
| `infra/*-rehearsal.sh`（8 套） | ha／load／restore／rpo-rto／wal-pitr／alerting／fullchain／gateway——**本地手动、不进 CI**，实测结论只登记在 docs/17 §7（本文件不复制数字） |

---

## 三、架构概览

### 1. 技术栈（选型总表＝docs/14 §1 七项；语言与框架同日 2026-09-13 确认，见 docs/15 §1／§5）

| 方向 | 采用 |
|---|---|
| 应用形态 | **模块化单体**：13 模块同仓 package，接口按服务边界设计（未来可拆） |
| 语言与框架 | 后端 Python 3.12 + FastAPI + SQLAlchemy 2/Alembic；前端 React + Next.js + TypeScript（Node 只在构建/SSR） |
| 编排 | **自研 Skill 注册表驱动编排器**，WF／Skill 定义为 YAML（数据驱动，无独立编排服务；协议与框架解耦，预留 LangGraph 迁移） |
| 数据层 | PostgreSQL 16 + pgvector ／ Redis 7（缓存 + Streams 队列）／ S3 兼容对象存储（MinIO） |
| 配置热更新 | 配置中心落库 + 变更广播：发布＝新版本 + 原子切换 + writeAudit，自带版本回滚 |
| 合规规则引擎 | 进程内独立模块（词库三关卡同源），不单独成服务 |
| 网关与 TLS | **反代入仓**：Caddy 2.10.2 单容器作唯一对外口，TLS 在 gateway 层终结 |
| 辅助系统（MVP 取舍） | 只建 Evaluation Dataset + Golden Cases；Simulation Sandbox 后置，其余随 V2–V3 |

> 三条硬约束贯穿所有选型：数值一律后台可配（Q9，禁硬编码）、审计 append-only、AI 不静默生效（候选必过 HumanGate）。

### 2. 仓库结构（docs/15 §1）

```
loom/
├── docs/                 # 唯一事实源：规格／决策／契约／运维（只读消费，不落代码）
├── backend/              # FastAPI 模块化单体
│   ├── app/
│   │   ├── product/      #   段1–6：录入·建模·字段池·原子·条件包·白名单中心
│   │   ├── platform/     #   段7–8：平台适配·动态信号·PCP
│   │   ├── decision/     #   段9–10：三包策略·合规中心
│   │   ├── final/        #   段11：final 白名单组装与发证
│   │   ├── content/      #   段12：内容生成·多语言·复检·video-studio
│   │   ├── core/         #   横切能力：rbac／audit／config_center／sla／skill7／model_registry
│   │   │                 #             queue／locking／orchestration／effects／exports／imports
│   │   │                 #             metrics／staff_auth／api_keys／a2a／mcp／dashboards／workbench…
│   │   └── main.py       #   装配：Settings／db／lifespan（调度器与 worker 按门控启停）／include_router
│   ├── alembic/          # 迁移，与 docs/10 Schema 一一对应（env.py 必须 import 全部 models 模块）
│   ├── scripts/          # 工程脚本：schema 漂移检查／主数据自检／回填骨架／覆盖率读数
│   └── tests/            # unit / integration / contract / e2e（docs/16 分层）
├── runtime/              # 编排可执行物：workflows/WF-*.yaml · skills/*/skill.yaml · agents/ · protocols/
├── eval/                 # Evaluation Dataset + Golden Cases（独立 runner，不进 pytest）
├── frontend/             # Next.js App Router：app/[locale]/(shell)＝客户侧，app/[locale]/admin＝管理端
│   ├── lib/api.ts        #   唯一后端访问层（server-only env，浏览器经 RSC/Server Action 间接访问，无需 CORS）
│   └── scripts/check-*.mjs  # 八道契约门（含"后端防漂移"守卫：文案键/枚举码/调用形态反查）
├── middleplatform/       # 中台对接：API / Webhook / Python SDK / CSV-JSON 导出
└── infra/                # docker-compose（base + 5 overlay）· Dockerfile · caddy · 备份与演练脚本
```

> 「每个包负责什么／入口在哪／表叫什么」＝按代码反向生成的清单，在 **docs/15 §3.1**；模块↔13 段映射＝**docs/07 §1**；表与列的权威定义＝**docs/04／docs/10**。本文件刻意不复制包数、表数、测试数——那些是活数字，去 handoff／docs/23 看现测。

### 3. 一条请求穿过什么（安全与治理骨架）

1. **认证**：机器面 Q88 Agent Key（`loom_` 前缀，保护 effect-callback／A2A／MCP）；人员面 Q178 内部 PAT（`loom_staff_` 前缀，门控 `LOOM_STAFF_AUTH_ENABLED` 默认关）。两域分表分前缀、不可互换。
2. **授权**：认证与授权分离，角色判定收在 `rbac`（`require_any_role`／`require_internal_actor`）。写口分两类——路由级凭证闸 `require_internal_actor(<角色>)`，其清单由 `tests/integration/test_write_gate_wiring.py` **反向枚举路由**求得并钉死（新受闸口漏登记即判红）；只读管理口走 query actor 角色闸。
3. **审计**：所有写动作经 `append_audit` 落 append-only 台账，操作人取**已验真凭证 > 请求自报**（`detail._actor_via` 三值可分辨，Q196）。
4. **业务闸**：候选只能进 `pending_review`，人工裁决才生效；`frozen` PWS 是下游唯一输入；`final_id` 只有 `E1.1 publishFCW` 一个出口；合规 `block_required` 一票否决。
5. **花钱**：模型调用一律经模型网关（场景路由 → 日预算硬停 → Prompt 渲染 → 驱动 → per-1M 成本记账），默认驱动是确定性 synthetic 替身；异步消耗（restock／真视频／导出／导入／FCW 重组装）全部 env 门控默认关，多副本形态下再靠 leader 锁与 fencing token、PG 行级 fence 防双花／拒旧 leader 迟到写（Q87／Q89／Q133／Q143／Q151／Q354）。

### 4. 运行拓扑（base compose ＋ gateway）

| 服务 | 角色 | 宿主口 |
|---|---|---|
| `caddy`（gateway overlay） | 唯一对外应用口；TLS 终结，放行 `/api/*`·顶层 `POST /mcp`·`/.well-known/*`，404 拦 `/docs`·`/redoc`·`/openapi.json`·`/healthz`·`/metrics` | 80/443 |
| `frontend` | Next.js standalone，管理台＋客户界面（服务端取数） | 3000（叠 gateway 时被收回内网） |
| `backend` | FastAPI 单进程模块化单体（调度器与各 worker 按 env 门控启停） | 不发布，仅 `expose: 8000` |
| `postgres` | `pgvector/pgvector:pg16`，WAL 归档已开 | `127.0.0.1:5432` |
| `redis` | 缓存／Streams 队列／分布式锁 | `127.0.0.1:6379` |
| `minio` | S3 兼容对象存储（原片留档＋WAL 与基础备份归档） | `127.0.0.1:9000`·`9001` |
| `db-backup`／`db-basebackup`／`wal-archiver` | 每日 pg_dump＋7 天保留／周期基础备份／WAL 推对象存储 | 无 |
| `watchdog` | 探活＋可选 webhook 告警投递（含转发 Prometheus firing） | 无 |

数据面一律只绑宿主回环（Q200 #33）；启用监控时 Grafana／Prometheus 也绑 `127.0.0.1`（Q192／Q289）。多副本形态＝叠 `docker-compose.ha.yml`（backend 两副本，打开分布式锁／Streams worker／配置失效广播三族 env），迁移由 `alembic` 的 PG 咨询锁串行化。

### 5. 质量与可观测（为什么这套东西敢反复改）

- **后端**：`ruff check` ＋ 分层 pytest（sqlite、无服务容器）＋ **独立 Eval／Golden 回归**（防"Skill 从未运行"那一类红旗 S2）。
- **迁移**：CI 的 Migration gate 在**真 PG16**上跑 `upgrade head` → `scripts/dba_schema_check.py` 逐列比对 ORM⇄DB → `downgrade -1` → re-upgrade，漂移或不可逆即判红。
- **前端**：`tsc --noEmit` ＋ 八道契约门；`check-admin`／`check-nav`／`check-tokens` 把"页面消费了后端哪条口、枚举码有没有被翻译进文案、令牌色值有没有漂"钉成判据。
- **可达性**：`tests/unit/test_admin_surface_read_contract.py` 反过来从前端调用清单反解出每条管理端读口，证明默认身份真读得动——"能力在、没人能驱动"这一类不靠人肉发现。
- **运行面**：零依赖自写进程内指标（`GET /metrics`）＋文件式 Prometheus 规则与 Grafana 看板＋watchdog 转发（不引 Alertmanager：Q185 实测其在栈里等于哑弹）；入站放行面与"旋钮有没有接到部署制品"由 `tests/unit/test_gateway_surface_contract.py` 钉住。
- **文档↔代码**：docs/05 契约、docs/10 Schema、docs/23 审计与功能点、docs/25 逐条验收互为对账面对象；改代码要同批改文档，逐片记录不回改（只在活文档加〔QNNN 订正〕注记）。

---

## 文档入口

| 文档 | 用途 |
|---|---|
| [docs/README_文档地图与治理.md](docs/README_文档地图与治理.md) | **文档地图（场景导航）+ 治理规则**——先读这个 |
| [handoff.md](handoff.md) | **交接文档**：当前状态、待办、活跃工作（续工时先读） |
| [docs/01_PRD_产品需求规格.md](docs/01_PRD_产品需求规格.md) | 权威规格：13 段链各段功能/实体/规则/硬闸 |
| [docs/02_决策记录_ADR_Q1-Q72.md](docs/02_决策记录_ADR_Q1-Q72.md) | 决策日志：Q1–Q72 ＋ 其后逐条续编（**权威逐片台账**，最新编号看该文文末的续编名单，不在此内嵌数字） |
| [docs/04-06_契约层](docs/04_契约层_数据模型.md) | 数据模型 / API 与状态机 / WF 与 Skill 协议（AI 落代码用） |
| [docs/08_迭代计划与任务包.md](docs/08_迭代计划与任务包.md) | 路线图（Q73 合并后）+ M0–M12 任务包 + V2/V3 路线 |
| [docs/22_外部系统接入手册_AgentKey_A2A_MCP.md](docs/22_外部系统接入手册_AgentKey_A2A_MCP.md) | **要给 Loom 接外部系统／Agent**：Agent Key 签发与验签、A2A 任务面、MCP 工具面 |
| [docs/26_新用户E2E验证清单.md](docs/26_新用户E2E验证清单.md) | **做浏览器 E2E 功能验证**：新用户视角逐项验证核心功能（13 段链/人工 Gate/final_id 唯一出口），含入口 URL、操作路径、预期判据 |

完整文档清单与一句话描述见 [handoff.md 的「项目文档」节](handoff.md#项目文档完整清单单一事实源)（单一事实源，含 docs/19 四份衍生件与归档件，故不在这里报份数）。

## 约定（改这个仓库前必读）

- **唯一事实源＝`docs/`**：任何变更先改对应文档、再落代码，新决策在 docs/02 追加 Q 编号；涉及展示层再同步渲染（docs/09）。两套口径（13 段链 vs 03-A~E 展示）并存不混用，冲突以 01 PRD 为准。其余治理规则见 [AGENTS.md](AGENTS.md) 与 docs/README 的治理节。
- **提交规范**见 [git-commit-message.md](git-commit-message.md)；**AI 工作规范**见 [AGENTS.md](AGENTS.md)。
