# Loom · 私域内容生产白名单平台

**AI 驱动的 13 段链内容生产 SaaS 后台**：把"产品信息 → 可发布内容"这件事拆成一条可编排、可审计、可质量拦截的生产链——从产品录入、冷启动建模、字段池与原子管理，到条件包（PWC/PWS）冻结、平台适配、策略/结构/表达三包、合规清洗、`final_id` 组装，最后只读消费给内容生成，再经反馈回流反哺知识进化。

> **当前状态**：设计/文档已定稿（[`docs/`](docs/) 为项目**唯一事实源**）；**代码已进入实现阶段**——V1 主链 段1→6→10→11 闭合，M1–M12 各切片、V2 P4 段12 首片（Q116）、Q118 一致性收口（4 GET 补闸 / gate V1 口径回填 / 迁移 0027 两 FK / CI 七 checker）与 Q119 段12 多语言（content_languages 语言清单 / 市场∩产品目标语言交集 / 每语言独立成品，迁移 0028）、Q120 段12 AI 质量分 Q57（第 8 场景 ARTICLE-QC 内嵌、纯 advisory 不阻断、阈值与重生成上限配置化，迁移 0029/0030）、Q121 复检第②项语义级检测（第 9 场景 ARTICLE-SEMANTIC-CHECK 内嵌、纯 advisory 落 review_hits.semantic，迁移 0031 纯种子）、Q122 客户「内容生产与发布」功能页 + Q56-a 客户人工改稿（无闸列表/详情/PATCH body、新事件 manual_resubmit revising→review、前端内容页与第八 checker check-content，零迁移）、Q123 段1 客户目标语言录入控件（客户 PATCH /api/intakes/{id}/target-languages + 无闸 GET /api/content/languages，零迁移）、Q124 难产骨架作废回池 Q56-b（第七态 discarded 终态 + discard 端点 reason 必填 + needs-attention 队列、partial unique index 释放同键生成机会，迁移 0032）、Q125 运营发布回填 Q60c（publish-info PUT + ready-to-publish 队列、published_url/platform_post_id/published_at 三列、不新增 published 态，迁移 0033；管理端 /admin/content 内容运营台）、Q126 段13 反馈回流入站第一片 effect-callback（`POST /api/effect-callback` 复用 Q88 Agent Key 为首个受保护业务端点 + `effect_records` 时序表 matched/orphan 分流 + 运营只读孤儿队列/成品时序，metrics 缺席不落不补 0、(content_id,captured_at) 幂等，迁移 0034 新建 effect_records 表）、Q127 Q60a 孤儿人工认领（`POST /api/admin/effects/claims` operations 写口 + `effect_claims` 持久映射 + effect_records 两溯源列，认领后同 ID 推送不回落孤儿，迁移 0035）、Q128 customer-backfill 客户专用通道（`POST /api/effects/backfill` 无 Agent Key、body actor、租户隔离、未命中整批 422 绝不产生孤儿，零迁移）、Q129 孤儿批量认领 + 取消认领/解绑（claims/batch 整批 all-or-nothing、claims/unclaim 删映射并回滚旧目标行、审计 effect.claim_revoked，零迁移）、Q130 管理端效果回流运营台（/admin/effects 为 sidebar 第 8 项：孤儿队列单条/批量认领 + 成品时序查询/解绑）、Q131 客户内容详情页效果回填岛（消费 Q128 客户通道、非 discarded 成品、V1 单条手工，零迁移）、Q132 中台导出 JSON 形态 + 异步导出任务（GET fcw.json 与 CSV 同口径 envelope、POST /api/exports/jobs V1 同步落 completed + 状态/下载口、export_jobs 不存 payload 下载重渲染，迁移 0036）、Q133 fencing token（`leader_lease` 抢锁后 `INCR loom:fence` 取跨易主单调令牌、看门狗易主/续约故障置 lost、INCR 失败 fail-closed）、Q134 Redis Streams 消费组细粒度认领原语（新包 `app/core/queue`，XADD/XREADGROUP/XCLAIM/ACK/死信，只落原语不接 worker、不落 env）、Q135 配置缓存多副本失效广播（Redis pub/sub + ConfigBroadcastSubscriber 收消息全量 reload，env `LOOM_CONFIG_CACHE_BROADCAST_ENABLED` 默认关、发布 best-effort）、Q136 客户批量 CSV 回填（内容详情页批量岛：纯前端 CSV 解析+行级校验+预览、整批走 Q128 records[] 客户通道、前端软上限 500 行，甲案无后端端点/迁移/依赖）、**Q137 中台导出真后台 worker**（queued/running 异步态 + Redis Streams 消费组 `ExportWorker` 水平并行〔只读幂等作业可安全并行〕+ `GET /api/exports/jobs` 任务列表口 + 崩溃 PEL 接管/超限死信，env `LOOM_EXPORT_WORKER_ENABLED` 默认关、`LOOM_EXPORT_STREAM_BLOCK_SECONDS`=5.0，零迁移）、**Q138 restock requested 信号 XADD 生产接线**（`restock/notify.py` after_commit best-effort 入流、DB requested 行为唯一事实源/DB 轮询兜底；因 restock 自动花真 token 须 leader 单实例防双花，worker 主认领**不切**消费组、水平并行留 V2 重评花钱隔离，env `LOOM_RESTOCK_STREAM_ENABLED` 默认关，零迁移）、**Q139 两循环 leader_lease 协作中止**（SLA sweep/restock 两 `_tick` 与两个手工 /run 由 leader_lock 换 leader_lease，作业/信号间 checkpoint=`raise_if_lost`，锁一轮中途易主抛 LockLost 协作中止、手工口返 409，复用 Q89 门控，零迁移）、**Q140 配置缓存单 key 增量失效 + 广播断线退避**（`reload_keys` 按 key 合并/DB 删除同步出快照、订阅 `*` 全量·具体 key 增量分流，断线指数退避 1s→封顶 30s，复用 Q135 门控，零迁移）、**Q141 配置缓存版本号门控+TTL 防陈旧**（per-key ConfigItem.version 向量拒旧快照回灌、订阅器超 300s 无失效消息回源全量，零迁移）、**Q142 中台导出分页+行数硬上限**（limit/offset、env LOOM_EXPORT_MAX_ROWS 默认 10 万，JSON envelope 加 total/has_more、CSV 走 X-Export-* 头，零迁移）、**Q143 下游 PG 行级 fence 接 restock 花钱路径**（restock_claims 表 + claim/fence_current 两段式拒旧 leader 迟到写，迁移 0037）已落地，Q133–Q142 零迁移/Q143 一迁移、env 默认关、不改 V1 单副本默认行为；迁移头 0037（物理表 59）、后端 699 测试（678→699：Q141 +6/Q142 +8/Q143 +7，全 FakeRedis/FakeStreams 内存替身）、eval 101/101、前端 8 个 checker（Q137–Q143 前端零改动，token 仍 86）。private beta 上线准备五片已落地：Q144 上线形态裁决（受控 private beta、公网自助 NO-GO、身份层压 V2 第一项）、Q145 最小部署制品（前后端 Dockerfile/entrypoint 迁移先行/compose backend 不发布端口 frontend 唯一入口 3000）、Q146 最小备份监控（每日 pg_dump+7 天保留/日志轮转/watchdog 探活+webhook）、Q147 staging 彩排（overlay 6 服务 healthy、真实 Chrome SSR 零 console 错误）、Q148 真实 LLM 接线（agnes OpenAI 兼容网关/agnes-2.5-flash/USD/日预算 50 USD/8 chat 场景真模型/Fernet Key，ATOM-AFFINITY 仍 synthetic）、Q149 beta 阈值确认（SLA 72h/黄 24h/红 48h、QC 0.85、cluster_line 0.9、G2 12 字段基线）+ docs/19 主数据录入模板；**Q150 loom 作为 Zeus 联邦第二封臣 A2A 第一阶段 plan 模式任务层**（新包 `app/core/a2a/`：三公开 Agent Card 发现端点 + `POST /api/a2a/tasks` 复用 Q88 Agent Key Bearer、JSON-RPC tasks/send·sendSubscribe(SSE)·get·cancel、进程内存任务存储、审计 tenant=`_platform`；plan 模式不触链/不花 token/不越 Gate，零迁移）、**Q151 SLA sweep 写路径 PG 行级 fence**（sweep_tick_claims 表 + sla/fencing.py 两段式 claim_tick/fence_current + run_jobs commit_guard，Q143 restock fence 的 SLA 同型收口，迁移 0038）、**Q152 导出 worker 单进程多 consumer 并发度/批量配置**（build_export_workers 工厂，env LOOM_EXPORT_WORKER_CONCURRENCY 默认 1/LOOM_EXPORT_STREAM_COUNT 默认 20 保 V1 行为，零迁移）已落地；其后 **Q153 docs/10 第二轮 DBA 全量列复核**（upgrade head 到 0038 后 information_schema 对 ORM 逐列比对，60 表/637 列/212 索引/PK60·FK32·UQ20、列漂移 0，纯文档实测）、**Q154 真 Redis/真 PG 多副本锁易主原语级集成验证**（新增 test_real_infra.py 8 例、函数级 skipif 默认 skip 不进 CI，真容器带 env 8/8 过 52.6s，抓到 request_id varchar(36) 被 sqlite 替身掩盖的 StringDataRightTruncation、统一 32 字符 uuid.hex）、**Q155 台内白名单卡片 6 层原料包全量 JSON**（`GET /api/fcw/{final_id}/material.json` 反解析产品/平台/策略/结构/表达/合规六层，台内卡片口径非中台 final_id-only 面，前端随 D3.5 菜单，零迁移）、**Q156 客户批量回填服务端化**（`POST /api/effects/backfill/upload` 无 Agent Key、JSON body 携 CSV、标准库服务端解析+逐行回执+强制 tz-aware、行数硬上限 env LOOM_BACKFILL_UPLOAD_MAX_ROWS 默认 10000，零迁移/零新依赖；Excel/异步/前端岛切换随 V2）、**Q157 真多副本多 worker 持续负载端到端部署演练**（alembic PG 咨询锁串行迁移 + infra/docker-compose.ha.yml 两副本 + ha-rehearsal.sh 16/16：导出两 consumer 分片 12/12、SLA/restock 抢锁 200/409、配置广播 reload；并修复 redis-py XREAD BLOCK 超时被误判后端故障致 worker 空转的缺陷，零迁移）已落地；**Q158 异机备份恢复端到端演练**（infra/restore-rehearsal.sh 两独立 pg16 容器源/异机 55440/55441、Q146 同款 custom pg_dump 离源入异机、pg_restore 后逐表零差异 12/12、应用 ORM 只读通、恢复库迁移幂等，零迁移/零生产代码、本地手动不进 CI）已落地；迁移头仍 0038_sweep_tick_claims（物理表 60，Q153–Q157 零迁移）、后端 761 测试＋8 real-infra 默认 skip（747→750 Q155 +3、→757 Q156 +7、→761 Q157 +4；带 LOOM_TEST_REAL_PG_DSN/LOOM_TEST_REAL_REDIS_URL 两 env 时 real-infra 8 例另计全过）、eval 101/101、前端八 checker（Q153–Q157 前端零改动，token 仍 86）。效果反哺校准算法（口径【待补】）、restock 消费组水平并行（花钱隔离，Q157 只验单 leader 不双花未改造）、A2A 第二阶段（任务持久化/真 LLM 链路/Zeus 真机联调）、台内白名单卡片前端 UI（D3.5 运营只读首片已随 Q177 落管理端 /admin/fcw 跨租户列表＋行内六层卡片、sidebar 第 11 项；组装工作台/审核台/冻结管理/客户视图等余项随 D3.5 菜单；6 层包后端 JSON 已随 Q155 落地）、批量回填的 Excel/异步导入任务/前端岛切换（服务端 CSV 上传+逐行回执已随 Q156 落地）、真多副本多 worker 持续负载生产级演练（Q154 原语级 + Q157 部署演练 + Q158 异机恢复演练已落，持续高压压测/RPO·RTO 量化达标随 V2）另 **Q166–Q177（2026-09-22～23，02 C1.110–121）**：客户效果 analytics 只读页、Agent Key 治理页、导出 job 管理页、全链 golden-path e2e、运营 SOP（docs/21）、第三轮 DBA 复核（61 表/654 列）、真 agnes 全链演练、持续高压负载演练（9/9）、批量导入岛异步轮询、RPO·RTO 量化达标（1.919s/70.111s）已落地；**Q177** D3.5 白名单卡片运营只读首片（管理端 /admin/fcw 跨租户列表＋六层卡片，sidebar 第 11 项，零迁移，三接缝甲案已经 2026-09-24 追认）；**Q176** ATOM-AFFINITY KNN 索引经 grounding 判定零 DB 层 KNN 查询消费方、裸建为死索引，列三档待负责人拍板、本轮不落地；**Q178** 身份层 P0-① 甲案第一切片内部运营人员令牌 PAT（新包 `app/core/staff_auth/`、staff_api_keys 表迁移 0040 物理表 61→62、`loom_staff_` 前缀与机器 `loom_` 分表分域、认证 staff_auth_context 全局依赖＋授权 rbac 唯一收口相分离、门控 `LOOM_STAFF_AUTH_ENABLED` 默认关、防 query/body 自报提权、管理端 /admin/login＋/admin/staff-keys 为 sidebar 第 12 项、后端 817→842〔+25 集成〕、HTTP 端点签名零改动；客户侧真实认证与 actor↔tenant 绑定仍 V2，02 C1.122；其三接缝已经 Q179 追认）；**Q179 第四轮 DBA 全量列复核**（upgrade head 到 0040 后 information_schema 对 ORM 逐列比对，62 表/666 列/219 索引/PK62·FK32·UQ21、列漂移 0，纯文档实测，02 C1.123）、**Q180 D3.5 客户白名单卡片视图**（客户集合口 `GET /api/fcw?tenant_id=` 无闸强制单租户、前端 content 子页 /content/cards 客户 nav 不增项、六层原料沿用 Q155，+3 集成，02 C1.124）、**Q181 零依赖指标级监控**（新包 `app/core/metrics` Counter/Gauge/Histogram＋ASGI MetricsMiddleware 按路由模板低基数＋`GET /metrics` 不鉴权同 healthz；prometheus 走 compose `monitoring` profile 默认不启，+10 测试，02 C1.125）、**Q182 WAL 归档＋基础备份＋对象存储 PITR**（postgres 开归档＋db-basebackup 周期 pg_basebackup＋wal-archiver 推 MinIO，`infra/wal/pitr-rehearsal.sh` 端到端 before=1/after=0，RPO 日级→分钟级并具备时点恢复；跨 region 冗余仍 V2，02 C1.126）已落地，三片零迁移、Alembic 头仍 0040/物理表 62，后端 855 passed＋9 skip、eval 101/101、前端 sidebar 12/token 86。随 V2；private beta 验收唯一剩余阻塞＝业务方按 docs/19 回填首批主数据（禁工程臆造）。当前进度、待办与接手须知见 [handoff.md](handoff.md)。

## 13 段链一图流（CHAIN_13）

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

## 为什么是"链"而不是"工具"

- **白名单是相撞产物**：在（产品 + 目的 + 平台/发布位 + 账号/风险）上下文下，各层原子相撞出的可用条件包；不是手写的词表。
- **质量是结构性的**：每段都有人工 Gate / Guard / 评审位，AI 只产候选、不静默生效；`frozen` 快照隔离了"决策"与"消费"两段。
- **可审计可回写**：Q1–Q183 决策日志、writeAudit、唯一出口、反馈回流闭环（唯一反向边回到段 3/4/8）。

## 文档入口

| 文档 | 用途 |
|---|---|
| [docs/README_文档地图与治理.md](docs/README_文档地图与治理.md) | **文档地图（场景导航）+ 治理规则**——先读这个 |
| [handoff.md](handoff.md) | **交接文档**：当前状态、待办、活跃工作（续工时先读） |
| [docs/01_PRD_产品需求规格.md](docs/01_PRD_产品需求规格.md) | 权威规格：13 段链各段功能/实体/规则/硬闸 |
| [docs/02_决策记录_ADR_Q1-Q72.md](docs/02_决策记录_ADR_Q1-Q72.md) | 决策日志 Q1–Q183 + 配置化清单 |
| [docs/04-06_契约层](docs/04_契约层_数据模型.md) | 数据模型 / API 与状态机 / WF 与 Skill 协议（AI 落代码用） |
| [docs/08_迭代计划与任务包.md](docs/08_迭代计划与任务包.md) | 路线图（Q73 合并后）+ M0–M12 任务包 + V2/V3 路线 |

完整 18 份文档一句话清单见 [handoff.md → 项目文档](handoff.md#项目文档)（单一事实源）。

## 路线图速览（2026-09-13 Q73 合并后：A7 为骨 + D9 厚度）

- **V1（0–3 月 / 5–10 客户）**：主链段 1→6→10→**11**（到 `final_id` 发证闭环，**不含段 12**）；段 7/8 仅 FCW 必需的静态底表基础版；横切 skill7/writeAudit/RBAC/配置中心/SLA + 审核工作台 + 租户/Onboarding + 前端 8 菜单基础版 + CSV + 质量两件套 + 2 驾驶舱（Token 成本、人工审核）。
- **V2（3–6 月 / 30–50）**：段 7/8 完整（动态信号/fit_score/PLATFORM-ADAPTER）、段 9 三包、段 12 内容生成、段 13 回流/KUP；知识库/Memory/Router/自助门户等 D9 厚度。
- **V3（6–12 月 / 100–200）**：平台化（辅助系统剩余 8 个、BI、Webhook、SDK、移动端、国际化、白牌）。

> 第 0 步规格仲裁（M0）与技术选型 6 项均已于 2026-09-13 完成；任务包明细见 08 §2（V1=M1–M8+M10/M10-Q/M11/M12），裁决记录见 02 C1.17/Q73。

## 治理铁律（摘要）

1. **唯一事实源** = `docs/` 全部文档；原 `v3.md` 已于 2026-09-13 归档删除（231 段核验零丢失）。
2. 任何变更先改本库对应文档 → 新决策追加 Q 编号 → 若涉及展示层再同步渲染。
3. 两套口径（13 段链 vs 03-A~E 展示）并存不混用，冲突以 01 PRD 为准。
4. 文档中 `line NNNN` 行号引用原指向基准文件 `Docs/Loom_后台_V6.0-需求说明（不是原型).html`；该文件经 2026-09-17 确认永久丢失（Q115），行号引用已降级为历史痕迹，不再作为可重新核对的基准。

## License / 约定

- 提交规范见 [git-commit-message.md](git-commit-message.md)；AI 工作规范见 [AGENTS.md](AGENTS.md)。
