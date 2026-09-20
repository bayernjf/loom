# AGENTS.md — Loom

供 AI coding agents（Claude Code / Codex / Cursor / Copilot 等）在本仓库工作时自动读取。

## 项目概览

Loom：私域内容生产白名单平台（SaaS 后台）。核心是一条 **13 段链（CHAIN_13）** 内容生产链——产品录入 → 冷启动建模 → 字段池规划 → 字段下原子 → PWC 条件包 → PWS 冻结 → 平台适配 → PCP → 策略/结构/表达三包 → 合规清洗 → `final_id` 组装 → 内容生成 → 反馈回流。AI 只产候选、人工 Gate 裁决、`final_id` 唯一出口（E1.1 publishFCW）、反馈回流闭环反哺知识。

**当前阶段**：设计/文档已定稿；代码已进入实现阶段——V1 主链 段1→6→10→11 闭合，V1 任务包 M0–M12 各切片、V2 P4 段12 首片（Q116）、Q118 一致性收口（4 个漏网 GET 补闸 / publish_slots.gate V1 人工直编口径 / 迁移 0027 两 FK / CI 七 checker）与 Q119 段12 多语言 Q58（content_languages 语言清单配置化 / 发布位市场∩产品目标语言交集 / 每语言独立成品唯一约束，迁移 0028）、Q120 段12 AI 质量分 Q57 + 重生成上限 Q56（模型网关第 8 场景 ARTICLE-QC 内嵌生成、纯 advisory 不阻断发证、阈值 content.ai_quality_threshold 与上限 content.regen_limit 配置化，迁移 0029/0030）、Q121 复检第②项语义级检测（模型网关第 9 场景 ARTICLE-SEMANTIC-CHECK 内嵌、纯 advisory 不抬 block_required/不阻断 approve、落 review_hits.semantic，迁移 0031 纯种子）、Q122 客户「内容生产与发布」功能页 + Q56-a 客户人工改稿（无闸列表/详情/PATCH body 三端点、manual_resubmit revising→review、前端内容列表/详情/审阅/改稿岛与第八 checker check-content，零迁移；三接缝交互超时按推荐甲落地待负责人追认，02 C1.66）、Q123 段1 客户目标语言录入控件（客户 PATCH /api/intakes/{id}/target-languages + 无闸 GET /api/content/languages、ProductSpaceView 回显，零迁移，02 C1.67）、Q124 难产骨架作废回池 Q56-b（第七态 discarded 终态、discard 端点 reason 必填、needs-attention 队列、partial unique index WHERE status<>'discarded' 回池，迁移 0032，02 C1.68）、Q125 运营发布回填 Q60c（publish-info PUT + ready-to-publish 队列、发布三列、不新增 published 态，迁移 0033，管理端 /admin/content 内容运营台，02 C1.69）、Q126 段13 反馈回流入站第一片 effect-callback（`POST /api/effect-callback` 复用 Q88 Agent Key Bearer 为**首个受 Agent Key 保护的业务端点**、新建 `app/core/effects` 与 `effect_records` 时序表按 status=matched/orphan 分流、仅精确匹配非 discarded 成品、metrics 缺席记 NULL 绝不补 0、(content_id,captured_at) 幂等覆盖/异点追加、运营只读孤儿队列与成品时序两口带 query actor 闸、整批 all-or-nothing + effect.batch_received 审计，迁移 0034 新建表，02 C1.70）、Q127 Q60a 孤儿人工认领（`POST /api/admin/effects/claims` operations 写口硬闸、`effect_claims` 持久映射 external_content_id→content_id + effect_records 加 claimed_by/claimed_at 两溯源列不新增第三状态、认领后同 ID 推送经映射兜底不回落孤儿、支持改绑重指、effect.claimed 审计，迁移 0035，02 C1.71）、Q128 customer-backfill 客户专用通道（`POST /api/effects/backfill` **无 Agent Key**、body {tenant_id,records,actor} 同 Q122 客户写口、source 服务端固定、只命中本租户非 discarded 成品否则整批 422、**绝不产生孤儿**、effect.customer_backfilled 审计 tenant=客户租户，零迁移，02 C1.72）、Q129 孤儿批量认领 + 取消认领/解绑（claims/batch 整批 all-or-nothing、claims/unclaim 删映射并把旧映射目标行回滚 orphan、effect.claim_revoked 审计，零迁移，02 C1.73）、Q130 管理端效果回流运营台（新建 /admin/effects 为 sidebar 第 8 项：孤儿队列单条/批量认领岛 + 成品时序查询/解绑岛，check-admin 锁恰 8 项，02 C1.74）、Q131 客户内容详情页效果回填岛（消费 Q128 通道、非 discarded 成品挂载、V1 单条手工、批量/CSV 随 V2、客户 nav 不增项，check-content 扩守卫，02 C1.75）已落地，五接缝甲案**已经负责人 2026-09-20 追认**（02 C1.73–C1.75 追认销账）；**Q132** 中台导出 JSON 形态 + 异步导出任务（GET fcw.json envelope 与 CSV 同口径、POST /api/exports/jobs V1 同步落 completed + 状态口/下载口、export_jobs 不存 payload 下载按参数重渲染、审计 export.job_created，02 C1.76）；**Q133/Q134/Q135** 多副本 V2 基建三件（Q133 fencing token：`leader_lease` 取 `INCR loom:fence` 跨易主单调令牌、看门狗易主/续约故障置 lost、INCR 失败 fail-closed，02 C1.77；Q134 Redis Streams 消费组细粒度认领原语新包 `app/core/queue`〔XADD/XREADGROUP `>`/XCLAIM 崩溃接管/ACK/死信〕，只落原语不接 worker、不落 env，02 C1.78；Q135 配置缓存多副本 pub/sub 失效广播 + ConfigBroadcastSubscriber 收消息全量 reload、env `LOOM_CONFIG_CACHE_BROADCAST_ENABLED` 默认关、发布 best-effort，02 C1.79；三件零迁移）；**Q136** 客户效果批量 CSV 回填（内容详情页非 discarded 成品在单条岛下新增批量岛 backfill-batch-island.tsx：纯前端 CSV 解析〔固定 9 列表头/双引号转义〕+行级校验同单条+预览前 10 行+文件/粘贴双入口、前端软上限 500 行、captured_at 转 UTC、空指标缺席，整批走 Q128 records[] 客户通道 all-or-nothing，甲案不建后端端点/无迁移/无新依赖，check-content 扩守卫，02 C1.80）；迁移头 0036_export_jobs（物理表 58，Q128–Q131、Q133–Q136 零迁移；0032/0033/0034/0035/0036 经 pg16 容器往返实测）、后端 656 测试（Q136 纯前端不变）、eval 101/101、前端 8 个 checker（CI 八 checker 全接线，Q122 起含 check-content，Q130 扩 check-admin 至 sidebar 8 项、Q131/Q136 扩 check-content，无新 checker 文件；token 仍 86，Q132/Q133–Q135 前端零改动）。效果反哺校准算法（口径【待补】）、批量导入的服务端上传端点/Excel/异步任务/逐行回执随 V2，须点工。当前基线、待办与逐片记录一律以 [handoff.md](handoff.md)「当前状态/待办」与 `docs/02` C1 日志为准，本文件不复述数字。

## 文档体系与治理规则（必须先读）

- **入口**：先读 [handoff.md](handoff.md)（当前状态/待办），再读 [docs/README_文档地图与治理.md](docs/README_文档地图与治理.md)（场景导航 + 治理规则）。
- **handoff 归档惯例（2026-09-18）**：`handoff.md` 只保留项目当前状态 + 活跃待办 + 最近 5 条进度；更早的进度条目与已销账待办详细过程整块原文归档至 `docs/handoff-archive-YYYY-MM-DD.md`（可作历史检索，逐条一字未改），权威逐条台账仍是 docs/02（C1 日志）/ 08 / 16。
- **唯一事实源** = `docs/` 全部文档；原 `v3.md` 已删除，一切规格以 docs 为准。
- **修改流程**：内容变更先改 docs 对应文档 → 新决策追加 Q 编号（02 文档 C1 日志）→ 涉及展示层再同步渲染（09）。
- **两套口径**：13 段链（权威，01 PRD）与 03-A~E 展示口径（09 全景）并存不混用，冲突以 01 为准；路线图口径合并属裁决事项，不得擅自合并。
- **行号溯源（Q115 收口）**：`line NNNN` 引用指向基准文件 `Docs/Loom_后台_V6.0-需求说明（不是原型).html`；该文件经负责人 2026-09-17 确认**已永久丢失、无法找回**，故行号引用**降级为历史痕迹**，不再作为可核对基准，改动时无需（也无法）同步核对。

## 事实纪律

- 每个数字/状态/结论必须来自 docs 文档原文（可溯到 Q 编号或 line 行号）；**禁止编造业务事实**。
- 文档空缺处一律标【原文未给出，待补】，不得猜测填充。
- 状态词口径：✅ 权威 / 🟡 待补 / ⬜ 待拍板——沿用现有标注，不静默升级状态。

## 待裁决事项（不擅自裁决）

**截至 2026-09-18 无待裁决事项**：

- ~~两套路线图口径合并~~ 已于 2026-09-13 裁决（Q73，08 §1.3：A7 为骨 + D9 厚度，段 12 后置 V2，V1=段 1→6→10→11）。
- ~~2026-09-17 Q117 审计挂账的 4 项实现差异~~ 已于 2026-09-18 由负责人「一口气开搞」均按推荐（甲）拍板并落地，记 **Q118（02 C1.62）**：① 4 个漏网管理面 GET 补 query actor 闸；② `publish_slots.gate` 回填 V1 仅 Q42 人工直编口径；③ `product_spaces` 两软引用补 DB 级 FK（迁移 0027）；④ CI 接入第 7 个 checker check-settings；审计外另修 Alembic 版本表列长缺陷。详见 [handoff.md](handoff.md) 待办 6（已销账）与 02 C1.62。

> M0（S 级红旗 4 条 + 业务方素材采纳）已于 2026-09-13 完成，见 02 中 Q2/Q22/Q22a/Q22b/Q60 转正注记与 C1.16 素材确认；04 §3 另有 4 个实现时挂账子项，非待裁决事项。
> 技术选型 6 项已于 2026-09-13 拍板定稿（14 为正式实现依据）；15/17 等下游文档已同步刷新。
> 今后新出现的挂起事项仍必须由用户/负责人拍板，禁止静默替换或使用默认值，并在 02 追加 Q 记录。

## 常用入口

| 任务 | 读 |
|---|---|
| 了解全貌 | README.md → handoff.md → docs/README 文档地图 |
| 落数据模型/API/状态机代码 | docs/04 · 05 · 06（契约层） |
| 写测试 | docs/16（分层测试策略） |
| 排迭代 | docs/08（V1/V2/V3 任务包，V1=M1–M8+M10/M10-Q/M11/M12，验收标准引用 Guard/Q 编号） |
| 查技术选型 | docs/14（✅ 2026-09-13 已拍板定稿，可作实现依据；15/17 已同步） |

## 不要做的事

- 不要改动 docs 中标注"待拍板/待补"的文档状态，除非对应裁决已发生并在 02 追加 Q 记录。
- 不要拿摘要/二手口径替代 docs 原文。
- 不要删除或移动 docs 文档（唯一事实源，先改文档再谈其他）。
- 不要提交 `.env`、密钥或任何凭证；仓库**已 git init**（分支 `dev`/`main`，origin 为 GitHub），提交规范见 [git-commit-message.md](git-commit-message.md)。
