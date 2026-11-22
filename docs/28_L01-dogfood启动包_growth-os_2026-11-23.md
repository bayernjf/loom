# 28 — L-01 dogfood 启动包：growth-os 真实入料与证据模板（2026-11-23）

> 性质：L-01 的执行启动包与证据台账，不是排期承诺；证据随跑随记，本文件持续追加。
> 口径：本机单人自用；文本为主产出；现有功能全部保留，只做追加式迭代。
> 关联：`docs/27`（差距与待办）、`handoff.md`（活跃待办）、BayJF `docs/tier0` 按序执行清单。

## 0. 已拍板决策与未选候选项（可追踪）

| 决策点 | 已选（简单、覆盖功能实现） | 未选候选项（保留追踪） |
|---|---|---|
| dogfood 产品 | **growth-os** | BayJF（内容形态最简单，备选）、Agent Ops（多语言/模板厚度，备选）、commerce-os（字段池/平台规则最代表性，备选） |
| 主产出形态 | **文本为主**，L-13 视频转写/成片复检保持 P2 | 视频为主（L-13 升 P1，范围显著变大，暂缓） |
| Q59③④ 实现口径 | **工程甲案**：按 docs/01 §C1.12 + docs/02 Q59 原文 + 段7规则集起草规格（docs/29），先落码、随迭代完善 | ① owner 提供权威规则文本（更准，但有外部依赖）；② 继续挂账（L-02 不算完整验收，不选） |
| L-03 worker 固化 | **两者都做**：先 launchd 常驻 sidecar（本机可用），再修容器镜像重建 | 仅 launchd（免去镜像维护）；仅容器（需等镜像重建成功，当前不可用） |
| 未来 Zeus Z-01 身份 | 决策+组织执行 runtime，全保留（到 Zeus 阶段再落） | 缩回纯决策平台（违反追加式纪律，不选） |

## 1. growth-os 真实入料（从仓库现况提炼，不虚构）

来源：`/Users/jiangfeng/000mycodes/growth-os/README.md`（G1 里程碑、read-only loop、offline-first 等）。

| 字段 | 值 | 依据 |
|---|---|---|
| 产品名 | growth-os | README 标题 |
| 一句话定位 | Operations personal agent for growth：市场研究、需求发现、潜客挖掘、CRM、外联 | README |
| 品类 | 开发者工具 / AI 运营工作台（L3 业务系统，Tier0） | README |
| 核心卖点（拟作为真实内容素材） | ① signal engine 采集→去重→打分→聚类，全 read-only；② 人工复核 insights（pending_review）；③ 版本化、加水印的 ResearchReport；④ offline-first 确定性回放，无外网凭据也能跑；⑤ 线上 fail-closed（缺 key 即 422） | README G1 loop |
| 目标市场/国家 | 本地自用起点：中国大陆（zh-CN）；市场∩语言取最小集 | 本机自用口径 |
| 目标平台 | Web（growth-os 自身无购物/票务，commerce-os 兄弟产品边界） | README not-in-scope |
| 内容目标（拟） | 一篇 growth-os 介绍/使用说明类成稿，语言 zh-CN | L-01 完成判据 |

> 注意：以上「卖点」从 growth-os README 原文提炼，属于真实产品事实；Loom 侧只做录入与生产，不改动 growth-os 任何文件。

## 2. 13 段逐段输入 / 产出 / 证据模板

证据目录：`outputs/dogfood-growth-os/`（JSON/文本逐步落盘；不手改数据库）。

| 段 | 段名 | 输入（真实） | 预期产出 | 证据文件 | 状态 |
|---|---|---|---|---|---|
| — | 入料 | growth-os 产品事实（§1） | `intake_id` | `00-intake.json` | ✅ 已跑（`13d17c77-…`） |
| C1 | 冷启动识别 | intake | 候选画像 `pending_review` → 人工 approve | `01-c1-candidates.json` | ✅ 已跑（launchd worker 自动识别） |
| 1 | 产品录入 | 产品/品类/卖点/平台 | product_space 记录 | `02-space.json` | ✅ 已跑（`532cdf15-…`） |
| 2 | 冷启动建模 | profile 快照 | 产品画像/受众/场景 | `02-space.json`（profile 内嵌） | ✅ 已跑 |
| 3 | 字段池规划+Gate | 画像 | FIELDPOOL-PLAN 产物 + Gate | `04-fieldpool.json` | ✅ 已跑（段级部分：DIM-SOURCE 七路未接为已知缺口，L-07） |
| 4 | 字段下原子+Gate | 字段池 | 原子 + 置信度 | `05-atoms.json` | ✅ 已跑 |
| 5 | PWC | 原子 | 产品世界模型 | `06-pwc.json` | ✅ 已跑 |
| 6 | PWS 冻结 | PWC | 冻结层快照 | `07-pws.json` | ✅ 已跑 |
| 7 | 平台适配 | PWS | PLATFORM-ADAPTER 四态 + fit_score 建议 | `08-platform-adapter.json` | ✅ 已跑（fit_score 真自学习为 L-06，不阻塞） |
| 8 | PCP | 适配结果 | 平台内容包 | `09-pcp.json` | ✅ 已跑（Q41 AI 候选为 L-05） |
| 9 | CSP/CSTP/CEP | PCP | 三包 + 配比 | `10-packages-csp/cstp/cep.json` | ✅ 已跑（Q44 软提示为 L-04） |
| 10 | 合规清洗 | 三包 | CCR 清洗结果 | `11-ccr.json` | ✅ 已跑 |
| 11 | final_id 组装 | 六层 | `final_id` + 发证 | `12-final-id.json` | ✅ 已跑（`0f392a3a-…`） |
| 12 | 内容生成+复检 | final_id | 一篇 zh-CN 文本成稿 + review_hits | `13-content.json`＋`15-review-q59-34.json` | ✅ 已跑（synthetic 成稿；Q59③④ v0.1 复检命中 structure_not_applied） |
| 13 | 反馈回流 | 成稿/发布位 | 回流记录/知识进化 | `14-feedback.json` | ✅ 已跑（KUP/热点/校准为 L-08） |

## 3. 失败点记录区（随跑随记）

| 时间 | 段 | 现象 | 根因 | 处置 |
|---|---|---|---|---|
| 2026-11-23 | 入料/全链 | 前端 3000 不代理 `/api`，宿主 8000 是 Atlas API | Loom 前端 Next 自己处理 `/api`，后端容器未发布端口 | 新增 `infra/docker-compose.dogfood.yml`，backend 回环映射 `127.0.0.1:8001:8000`（基础 compose 发布契约不变） |
| 2026-11-23 | 段 12 | ARTICLE-GEN 180s 超时 | 容器配了 `MODEL_HUB_URL/TOKEN` → 走 model-hub 真模型，上游 3 次尝试全失败（`GenerationUpstreamError`） | 按启动包 synthetic-first 口径：`infra/.env` 的 `MODEL_HUB_*` 置空（原值注释保留），回退 synthetic；真模型路径待单独修 |
| 2026-11-23 | 复检 | ③④ 未落地 | 原文未给实现口径 | 按工程甲案落 `content/compliance.py`（docs/29），真实成稿复检并落证据 |

## 4. 环境事实（2026-11-23 实测）

- `infra-backend-1` 容器 Up 7 天（镜像早于 2026-11-22 的 C1 worker 提交，容器内无 C1 代码）。
- `infra-postgres-1`/`infra-redis-1`/minio 均健康；Postgres 只绑宿主回环 127.0.0.1:5432。
- API 经 `infra-frontend-1` 的 3000 端口代理；`GET /api/health` → `{"status":"ok"}`。
- staff 门控开（`LOOM_STAFF_AUTH_ENABLED=true`），库内 active staff key 9 枚；dogfood 另签专用令牌（bootstrap --force）。
- model-hub 宿主可达 `http://127.0.0.1:8791`（容器内 DNS 为 `model-hub:8791`，host sidecar 用前者）。
- LLM 默认 synthetic（`LOOM_LLM_BASE_URL_OPENAI` 空）；真模型经 model-hub，dogfood 首选 synthetic 跑通机制，真模型调用单独记录。

## 5. 完成判据（对照 docs/27 L-01）

- [x] growth-os 真实入料 → C1 → 段 1/2/4/5/6 → 段 10 → 段 11 `final_id` → 段 12 成稿/复检 → 段 13 回流，全链无手改数据库（15 份证据）。
- [x] 至少一篇真实成稿通过复检：content `cd099720-…` 复跑 Q59③④ v0.1（`15-review-q59-34.json`），block_required=false、命中 `structure_not_applied`（可定位到 CSTP struct 规则）。
- [x] `outputs/dogfood-growth-os/` 证据齐全（0–14＋99 索引＋15 复检），失败点逐条记录于 §3。

## 6. 实跑结果（2026-11-23 回填）

| 项 | 结果 |
|---|---|
| 全链 | 13 段全通，API 驱动、无手改数据库；C1 由 launchd worker 自动识别（验证 L-03a） |
| 关键 id | intake `13d17c77-7975-4291-aa63-7086516b6427`／product_space `532cdf15-0f34-41df-8c28-fe01d692b4ef`／field pool `c109d222-9bc5-4dd5-8266-ef7483990573`／final_id `0f392a3a-e6a1-11f1-ab6a-fa6984d93c8f`／content `cd099720-e6a1-11f1-9230-9ed4b69628fb` |
| 成稿 | synthetic zh-CN 占位正文（`review_hits` ①②③④ 全部产出；quality_score=0.92） |
| Q59③④ | ③ 命中 `structure_not_applied`（2 段 < 钩子-论点-收尾 3 段）；④ country=null → generic 无命中；`semantic` checked=true、findings=[] |
| 已知限制 | 真模型路径未通（model-hub 上游 3 次失败）；③④ 规则集为工程口径待校准；合成正文不代表真实文案质量 |
