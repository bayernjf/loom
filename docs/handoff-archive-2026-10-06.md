# handoff 进度归档 — 2026-10-06

> 依 `handoff.md` 归档惯例：主文件只保留项目当前状态 ＋ 活跃待办 ＋ **最近 5 条**进度；超出 5 条的进度条目**逐条原文**滚入本档（可作历史检索，一字未改）。
> **权威逐片台账仍是 [docs/02](02_决策记录_ADR_Q1-Q72.md)（C1 日志）／[docs/08](08_迭代计划与任务包.md) §2.2 ／[docs/16](16_测试策略.md)。**

## Q288/Q289 banner 原文（于 2026-10-06 按「最近 5 条」上限滚出）

> **其前（2026-10-05）：Q288/Q289 待裁项⑦ 裁「补」丙案落地 ＋ prometheus 9090 绑回环（**代码＋迁移＋测试＋配置＋文档**，迁移 **0047→0048**；后端 **1141→1146 passed＋10 skipped**〔Q288 ＋4 集成／Q289 ＋1 加固契约〕；真 PG16 往返实测；02 C1.231/C1.232）**——负责人「按你建议来」。
> - **Q288（⑦ 裁「补」丙案）**：迁移 `0048_packages_active_triple_unique` 在 `packages` 上建**部分唯一索引** `uq_packages_active_triple`（product_space_id·platform·goal·kind，`WHERE status='active'`，双 where 双写）＋模型 `__table_args__` 成对＋router create/update 两路 `IntegrityError`→**409**。索引名刻意不复用幻影 `uq_package_active_triple`（Q278 勘误）。
> - **真库实测（本机 `infra-postgres-1`）**：升级前 `packages` **3 行 active**（同一 PS×`x_platform`×`ENGAGEMENT` 的 csp/cstp/cep 三件套），重复三元组盘点 **0** ⇒ 建索引成功（有重复会当场失败）；重复插同 active 三元组被 DB 拒、archived 孪生放行（证 partial）；`0047→0048→0047→0048` 往返（`pg_indexes` **1→0→1**），head＝**0048**。
> - **Q289**：`monitoring` overlay 的 prometheus 由 `9090:9090` 改绑 **`127.0.0.1:9090:9090`**（无认证无契约的抓取口不开宿主网卡，与 Q192 Grafana 同纪律）；既有测试改名并改判据、hardening 门新增「prometheus＋grafana 两口都必须回环」。
> - **陈述精确化（与 Q280 同型）**：design-p2 §6「现网 `packages` 零行」指**生产环境**（无部署确为零行），本机**开发库**实测 3 行——两句话指的不是同一个库，已在设计文档就地注记。
> - **【复判不变】**：① 功能覆盖达标／②「核心完全可用」未达标（卡点＝业务方回调首批主数据＋有人跑段1→6→10 在 Gate 裁决）／③ 可上线未达标（现网部署＋真实 ACME 未证，另有待裁项③）——本批是守卫加固，不改任一层判定。**⑦ 自本批退出活跃待裁项（余 ②③④⑤）**。

## Q287 banner 原文（于 2026-10-06 按「最近 5 条」上限滚出）

> **其前（2026-10-05）：Q287 两个对外旋钮钉成同域不变量（**脚本＋测试＋文档；零生产代码零迁移**；后端 **1140→1141 passed＋10 skipped**（总收集 **1151**；＋1＝同域规则门）、ruff 净、前端零改动；02 C1.230）**——负责人「那你搞」＝工程侧最后一件不需裁决的事。**缺陷形态**＝`LOOM_GATEWAY_DOMAIN`（Caddy 站点地址）与 `LOOM_PUBLIC_BASE_URL`（A2A 卡片 base）互不约束：只设其一或把后者写成别域 ⇒ 应用不报错、CI 六道门与契约测试全绿，**外部 Agent 拿到一张指向别处的卡片**——Q280「旋钮没接到制品」一族里最后没钉死的一型。
> - **演练预检（部署前唯一能拦住人的地方）**：`gateway-rehearsal.sh` 开头 fail-fast＝env 已设且其主机 ≠ 站点地址 ⇒ **exit 2** 并打印冲突双方。实测别域注入回 **exit 2**、同域/未设放行；**第一次量 exit 被管道里的 `head` 掩蔽成 0**，去掉管道重测才拿到 2——老教训再中一次。
> - **阶段 4 从 4 条增到 6 条**：同域注入（`https://<站点地址>`）⇒ 两张卡片 `url` 同域绝对；**反向对照**＝故意注入 `https://mismatch.test` ⇒ 卡片真的跟着指向别域，**实证应用对此不设防**（这正是预检存在的理由）；收尾恢复同域。复跑＝**23/23 PASS、FAIL=0**，拆除后本项目残留容器 0。
> - **静态门 ＋1**：同域规则必须同现于运维读的 docs/17 与演练预检（规则丢任何一边即红）。**自摆乌龙一次**：断言初版按字面找「必须同域」，而 docs/17 正文写的是「必须与 `LOOM_GATEWAY_DOMAIN` 同域」⇒ 假红，改按语义断言。docs/17 §1.1 顺手更正「两件事」→「**三件事（前两件必须同域）**」（原文列三条自称两件）；§7.8／BENCHMARK 计数同步 23。
> - **刻意没做**＝应用内启动校验（backend 读两个 env 自查属运行时行为变更，未获裁决不动）。**三层判定不变**：① 达标／② 未达标（业务方按 docs/19 §0.2 回填主数据＋录入一个真产品＋有人跑段1→6→10 在 Gate 裁决）／③ 未达标（现网未部署＋真实 ACME 未签发）。

## Q290 banner 原文（于 2026-10-06 按「最近 5 条」上限滚出）

> **其前（2026-10-05）：Q290 主数据自检器在本机开发库实测 **exit 0**（已找到可发证组合），但数据带 `t-e2e` 前缀 ⇒ ② 判定不变（**纯实测＋纯文档登记**，零代码零迁移零测试变化；后端基线仍 **1146 passed＋10 skipped**；02 C1.233）**
> - **实测**：`python backend/scripts/check_master_data.py` ⇒ `publish_slots(active)=1／pcp_weight_tables(active)=1／packages(active)=3／content_goals=5／敏感领域=6／G1 类目=6`，并打出 **✅ 已可发证：(product_space=bd1e64ac-…, tenant=t-e2e-c174c8ee7f9f, platform=x_platform, goal=ENGAGEMENT)**，**exit 0**——Q245 以来「自检器恒 exit 1、三表零行」的状态已不再成立（旧读数按不回改保留，由本条纠偏）。
> - **为什么 ② 判定仍未翻**：该组合的 `tenant_id` 前缀是 **`t-e2e`**（端到端造数痕迹），`platform=x_platform`／`slot_type=short_video` 亦非业务命名 ⇒ 按「禁工程臆造」红线与 docs/19「判定首批完成＝真实业务数据出一张 `final_id`」，**工程侧不得据此自推、不得据此跑链宣称跑通**。
> - **① 的性质变了但没消失**：从「等三表填齐」变成「等**真值替换或确认**」——要么业务方给五个空（产品／平台／发布位类型／内容目的／**Gate 裁决人**），要么负责人明确「`t-e2e` 这组算真值」（本会话不代裁）。**跑链裁决的第二个人仍是硬卡点**。
> - **本机口令事实（只记形状不记值）**：用 compose 容器里那个 32 位口令从宿主连会 `InvalidPasswordError`；可用的是 `LOOM_DATABASE_DSN=postgresql+asyncpg://loom:loom@localhost:5432/loom`（与 `alembic/env.py` 缺省同值），口令不入库不入文档。
> - **【复判不变】**：① 达标／② 未达标（卡点＝真业务值替换 `t-e2e` 造数＋跑链第二人）／③ 未达标（现网部署＋真 ACME 未证，另有待裁项③）。

## Q291 banner 原文（于 2026-10-06 按「最近 5 条」上限滚出）

> **最新（2026-10-05）：Q291 四个拓扑无关布尔开关经 base compose 转发（Q280「旋钮没接到制品」一族的系统性收口；**配置＋测试＋文档**，零生产代码零迁移；后端 **1146→1147 passed＋10 skipped**〔＋1 可达性契约门〕；02 C1.234）**——工程侧自查可独立推进项，负责人「你自己可以搞吗」。
> - **缺陷（反向枚举实测，非推理）**：把 `config.py` 全部字段对照 base compose 与 5 overlay 一次性盘点，查出四个**与拓扑无关、文档已承诺部署期可拧**的布尔开关谁都不转发、容器内又无 `.env` ⇒ 运维在 `.env` 设了也进不了容器。最要命 `LOOM_STAFF_AUTH_ENABLED`：docs/17 §1 启用引导第③步与 Q203 验收都要求「置 true 重启」，但官方 compose 形态下 env 永不到 backend（`staff_auth/deps.py:121` 凭证分支永不进），身份门控实际开不了。
> - **交付**：`infra/docker-compose.yml` backend.environment 补 `LOOM_SCHEDULER_ENABLED`（默认 true）＋`LOOM_STAFF_AUTH_ENABLED`／`LOOM_DISCARD_PURGE_ENABLED`／`LOOM_MCP_ENABLED`（默认 false）四行 `${VAR:-字面默认}`（布尔 env 不用空串默认，空串会让 pydantic bool 启动校验失败）；默认值一字不变、纯加法可回滚。
> - **守卫（反向枚举，不止补一个）**：`test_gateway_surface_contract.py` 新增 `test_topology_free_bool_switches_actually_reach_the_backend_container`——四开关必须转发且插值默认与 `config.py` 逐字一致；拓扑绑定族（restock/export/import/fcw 四 worker＋distributed_lock＋config_cache_broadcast 共 6 开关）**刻意不进 base**，谁挪进来即红（只由 ha overlay 在多副本/演练时打开）。两次种植（staff_auth 改空串／export worker 塞 base）各判红后还原；沙盒内 2 个 backup_monitoring socket.bind 失败经沙盒外复跑 22 passed 证实为环境假红。
> - **刻意没做（守裁决边界）**：不改默认值、不加应用内启动校验（Q287 已注明属运行时行为变更须裁决）、不扩 worker 族转发面、不入 `backend/.env.example`（Q135/Q178/Q232 先例）。docs/17 §1＋docs/22 §3.1 已补接线事实，Q285 banner 按「最近 5 条」上限滚入 10-04 档案。
> - **【复判不变】**：① 功能覆盖达标／② 未达标（卡点＝真业务值替换 `t-e2e` 造数＋跑链第二人）／③ 未达标（本批让 staff 门控在官方 compose 下**真能开**、补了 #7 验收链一处被文档掩盖的硬缝，但现网部署＋真 ACME 仍未证，另有待裁项③ 客户侧认证）。

## Q292 banner 原文（于 2026-10-06 按「最近 5 条」上限滚出）

> **其前（2026-10-05）：Q292 PCP「每周重算触发」实现候选设计（**纯文档交材料**，零代码零迁移零测试变化；基线不变 **1147 passed＋10 skipped**；02 C1.235）**——承接 Q278 点名三件未落之一，只做 Q274/Q284 同型候选材料，不写码不裁决。
> - **grounding 改变问题形状**：真缺口不是「周调度器」而是「每周触发后**新权重从哪来**」。重算候选＋人工 Gate 三件套已全（`pcp_recalc_candidates` partial unique、create/approve/reject、Σ≤1.0＋`recalc_step`），但 `proposed_weights` 的 17 个新值 V1 只能人填——`source=ai|manual`、V1 仅 manual、PCP-SCORE 生成器随 V2（`models.py:215-216`）；`pa_rules.py` 无「事件→权重」派生函数；动态事件唯一消费是 match advisory 回带、不改判定（`service.py:652`）；原文（docs/01 line 2057 痕迹）只说「每周触发重算」未给映射算法。⇒ 只加周循环而无权重来源＝每周醒来无合法动作，自造映射即违反禁臆造。
> - **交付**：新档 `docs/design-v2-pcp-weekly-recalc.md`，两层候选——3.1 触发机制（甲＝复用 `SweepScheduler` 第 6 登记作业＋默认关 env〔推荐，白拿 Q89/Q139/Q151 多副本安全〕／乙独立循环／丙外部 cron）× 3.2 触发后产出（甲＝只开 OpsTodo「待重算提醒」不产权重〔推荐的 V2 第一切片，与 PWS 就绪提醒同型、零臆造〕／乙确定性派生候选，硬阻塞＝业务方先给事件→权重映射规则／丙 PCP-SCORE AI 候选，接模型网关＋eval/golden）；§4 列 6 待裁点。任何路径都不自动 approve（人工 Gate 红线）。
> - **同批登记 Q291 CI**：run `37324727725`（dev `22e6c60`）六道门全 **success**，本机 1147＋10 skip 与 CI 一致。锚点按 Q283 教训逐行对内容（`approve_candidate` 实为 `service.py:760`，非初稿 773）。
> - **【复判不变】**：① 达标／② 未达标（真业务值替换 `t-e2e`＋跑链第二人）／③ 未达标（现网部署＋真 ACME 未证，另有待裁项③）——本批把一件 V2 余量从「无调度器」精确化为「权重来源缺失」并交可裁决材料，不改任一层判定。
>

## Q293 banner 原文（于 2026-10-06 按「最近 5 条」上限滚出）

> **其前（2026-10-06）：Q293 Q278「三件未落」之另两件实现候选设计——fit_score 自学习 ＋ PLATFORM-ADAPTER 业务接入（**纯文档交材料**，零代码零迁移零测试变化；基线不变 **1147 passed＋10 skipped**；02 C1.236）**——负责人「那你搞」；Q292 已交三件之第一件，本批把**剩下两件**按 Q274/Q284/Q292 同型补齐，不写码不裁决。**至此 Q278 三件未落全部有可裁决材料。**
> - **【fit_score 自学习】**（新档 `docs/design-v2-fit-score-selflearning.md`）：grounding 先纠前提——红旗 B1.1 原文挂的「四维如何聚合成 fit_score」该半**已由 Q34 落地**（`pa_rules.py:89-96`），**未答的另一半才是「学习」**。四维 `traffic/safe/conv/load` 与 `goal_fit_weights` **全部纯人工**；平台适配 8 张表**无候选表**；docs/06 §7 Gate 总览十二行**无 fit_score 行**；`GET /fit-score` 只回标量**不可解释**（看不见就没法校准）。**硬阻塞＝唯一候选数据源段13 `effect_records.metrics` 七键**（`plays/likes/comments/shares/inquiries/conversions`＋`read_rate`，稀疏、缺席不补 0、不许估算）**与四维对不上**：`safe`（安全）/`load`（承载）**零候选源**（合规在系统内是机械判定 Q48/Q49，不是效果数据能给的量）、另两维映射原文未给；且段13 属 V2（Q73 V1 不含段12/13）、生产零行。⇒ **结论比 PCP 那件更硬：不是「怎么做学习」，而是「被学的量本身没有数据源」。** 候选：**甲＝可解释化**（回带 breakdown，不动算法不落库）／**乙＝人工校准闭环**（复用既有 PUT 两口、只补四维 before/after 审计，并立**口径诚实条款：不得表述为「自学习」**）／**丙＝真自学习**须业务先给四份规则、到位后仿 Q259 候选＋Gate。§4 列 6 待裁点。
> - **【PLATFORM-ADAPTER 业务接入】**（新档 `docs/design-v2-platform-adapter-business.md`）：**规格不缺、缺业务接线**——PT-PLATFORM-ADAPTER-V1.0 七条约束**已定稿 ✅**（docs/12:19 标 ✅）、Q246/0046 已落引擎三件套（`ai_scene_routes`→synthetic＋Prompt v0.1＋`build_platform_adapter()` 四态构造器），`synthetic.py:307` 自述「业务接线随 V2」。反向枚举四处缺口＝**无调用方**（全仓仅 **5** 个 `llm-*` 端点（llm-invoke/llm-plan/llm-expand/llm-build/llm-resolve），平台适配自身 **25** 端点无一涉及 adapter ⇒ Prompt 三变量至今无人组料）／**无结果载体**／**无 HumanGate 面**／**无 eval/golden**（9 案例无此项 ⇒ 红旗 S2「只有协议没有运行证据」零回归证据，**无 golden 不许切真模型**）。**最有利事实＝三料源全在且都有现成生产消费方**（`PwsSnapshot`＋`match_rules()`＋`active_events_for()`）⇒ 组料零臆造，真缺口只在触发方式/载体/Gate 面/护栏四处。三段候选：**甲＝只读预览口**（仿 Q249 FCW 预检，零落库不改判定）／**乙＝候选表＋Gate 闭环**（仿 Q259 `pcp_recalc_candidates`，`approve` **只解除 pending 留痕、不自动放行到 `final_id`**）／**丙＝接真模型**（硬前置先补 golden）。§4 列 7 待裁点。
> - **三处自查订正（照 Q283 教训逐行对内容，不留初稿误判）**：① **Q38 降级动作字典口径「已定稿 ✅」——初稿曾误判为「原文未给」**（docs/02 C1.6 已给六个初始动作，原话红线「不许 AI 自由发挥」），但**全仓零命中＝载体零落地**（`content_goals` 属 Q25 已落，Q38 与 Q25/Q43/Q46 同入 docs/10:368 字典管理区但尚无实现）⇒ 乙若要落人工审核降级动作须先落 Q38 载体（**已定稿口径的欠实现，非新裁决**）；② **docs 口径漂移待订正**：docs/02:141 六项 vs docs/10:369 举例（`REMOVE_HOOK`/`REWRITE`）**后四项对不上**，以 docs/02 为准、**工程侧不擅自改 Q 记录**；③ 照 Q288 同型**陈述精确化**：docs/13:123「截至 Q116 代码未实现适配判定端点、`platform_dynamic/` 为空包」**已被 Q246/Q259 超越**（旧读数按不回改保留、由本条点名纠偏）。另实测**形状缺口**：Prompt v0.1 要求五键 `{missing,decision,reason,refs,gate}`，synthetic 无 PWS 分支**只返两键** `{missing,reason}` ⇒ 消费方取 `decision` 会 KeyError，接线须归一并登记进 docs/05。
> - **【复判不变】**：① 功能覆盖达标／② 未达标（卡点＝真业务值替换 `t-e2e` 造数＋跑链裁决第二人）／③ 未达标（现网部署＋真 ACME 未证，另有待裁项③ 客户侧认证）——两件的硬阻塞被定位到**业务规则供给**（映射规则、审核角色码、Q38 字典口径漂移）而非工程实现，不改任一层判定。
>

## Q294 banner 原文（于 2026-10-06 按「最近 5 条」上限滚出）

> **其前（2026-10-06）：Q294 PCP 每周重算提醒落地＝Q292 候选的 3.1 甲＋3.2 甲（Q278「三件未落」第一件由材料变代码；**代码＋迁移＋测试＋配置＋文档**，迁移 **0048→0049**〔纯种子〕；后端 **1147→1157 passed＋10 skipped**（总收集 **1167**；＋10＝新集成测试档）、ruff 净、eval 仍 101/101、前端零改动；真 PG16 up／down／up 往返＋功能往返实测、DBA 脚本 **NO DRIFT**〔68 表／734 列一字不变〕；02 C1.237）**——负责人「按你推荐来」＝落地 Q292 自己给出的「V2 第一切片」推荐顺序，**不产权重、不替业务方裁映射规则**。
> - **缺陷形状（承接 Q292 grounding）**：docs/01 段8 PT-PCP-V1.5 要求「动态信号每周更新触发重算」，但真缺口不是「周调度器」而是「**触发后新权重从哪来**」——`pa_rules.py` 无「事件→权重」派生函数、原文未给算法。故本批只把「每周」落到**产品内节奏**：每周把「窗口内新生效动态事件、且对应 active PCP 尚无 pending 候选」摆成运营待办，权重仍由人走既有 manual 候选 → 人工 Gate。
> - **交付**：① `config.py` 新 env `LOOM_PCP_WEEKLY_SCAN_ENABLED` **默认 false**（同 Q187 门控纪律，关时空转返回 0、V1 sweep 行为一字不变）；② `core/sla/jobs.py` `JOBS` 追加第 6 作业 `pcp_weekly_recalc_scan`（复用 300s tick＋Q89 leader 锁＋Q139 协作中止＋Q151 commit_guard＋既有手工 `/api/admin/sla/run`，**不新建第二个 asyncio 循环**）；③ `platform_adaptation/service.py` 新 `scan_weekly_recalc_reminders()`＋`weekly_recalc_anchor()`；④ `config_center/seeds.py` 四个**热更旋钮** `platform.recalc_weekday`(0)／`_hour`(2)／`_tz_offset_hours`(8)／`recalc_todo_due_days`(7)（周节奏属业务口径，按 Q9 纪律走配置中心不占 env）；⑤ 迁移 **0049_pcp_weekly_recalc_seed**（纯种子、幂等，同 0041 先例）；⑥ compose 转发新 env＋Q291 反向枚举门加第五开关。
> - **语义（逐条可判）**：锚点＝本地 `(weekday, hour)` 周时刻，**固定 UTC 偏移口径**（中国自 1991 年无夏令时，固定偏移与 Asia/Shanghai 恒等；镜像 `python:3.12-slim` 无系统 tz 数据库，刻意不引 tzdata 依赖），钟点未到退回上一周期 ⇒ 同周期任意 tick 同一锚点；窗口＝**(上一锚点, 本锚点]** 内新生效的 active 事件；命中平台每个 active PCP：**已有 pending 候选则跳过**（提醒不得与在途 Gate 叠加），**开/续**一条 `pcp_weekly_recalc` OpsTodo（assignee=operations，detail 带 platform/ps/pcp_id/event_ids/anchor/cycle_start/next_step）；本周期已提醒过（含 resolved）不重复；**无新事件的周直接跳过**。审计 `signal.pcp_weekly_recalc_todo`（actor 空＝系统作业）。
> - **红线与种植**：**不建候选、不写回 `pcp.weights`**（测试逐字节钉住）。三次种植均判红后还原：门控默认翻 true、去掉 pending 候选检查、compose 删新开关行。真 PG16（一次性 pg16 容器宿主 55451）实测：4 键落库 version 1、`downgrade -1` 只删本批 4 键（未伤 `platform.recalc_step`）、head=0049、DBA 脚本 NO DRIFT；同容器**功能往返**（显式事务后回滚）＝开 1 条提醒＋同周期续期不重复＋回滚后两表 0 行。
> - **刻意没做**：不自动 approve、不写回权重表；不自造「事件→权重」映射（3.2 乙硬阻塞＝业务方先给规则，原样保留）；不碰 fit_score 自学习与 PLATFORM-ADAPTER 业务接入（Q293 同批另两件，各自待裁）；不入 `.env.example`；前端零改动（提醒经既有待办 SLA 看板可见）。
> - **【复判不变】**：① 功能覆盖达标／②「核心完全可用」未达标（卡点＝真业务值替换 `t-e2e` 造数＋跑链第二人）／③ 可上线未达标（现网部署＋真 ACME 未证，另有待裁项③）——本批不改任一层判定。

## Q295 banner 原文（于 2026-10-06 按「最近 5 条」上限滚出）

> **其前（2026-10-06）：Q295 beta 首批真证重发落成 ＋ ②「核心完全可用」翻正（owner Gate 三步＝Q32 作废重冻 v2.0 → 段10 CCR 重扫 clean → E1.1 真发证口出活证 `537a2f28`；**纯运行时数据操作＋纯文档**，零代码零迁移零测试变化；后端基线不变 **1157 passed＋10 skipped**、头仍 0049；02 C1.238）**——负责人「按你推荐的来」一次性给齐三刀。
> - **三刀登记**：① **t-e2e 组合确认为 beta 首批真值**（ps=bd1e64ac-…／tenant=t-e2e-c174c8ee7f9f／x_platform／short_video／ENGAGEMENT）＋**Gate 裁决人＝负责人本人**——Q290「真值确认＋跑链第二人」两卡点解除；② Q278 三件裁决＝PCP 3.1甲×3.2甲（Q294 已落地，追认）／fit_score 采**甲（可解释化）**／PLATFORM-ADAPTER 采**甲（只读预览口）**（后两件落码另点工）；③ 授权按 docs/02 C1.6 订正 docs/10 Q38 举例。**whitelist_owner 可签发性、docs/05 三写口角色、MCP discover 四处出入仍未裁**。
> - **盘点与活体预检**：段3 pool approved／3 原子 approved／组合 30e9948e approved·ready（0.82）／PWS v1.0 frozen／CCR clean，但唯一 final_id `43d5b9e6` 的快照 **revoked**（e2e 发证 4 分钟后测回滚流）⇒ **库内无活证**；Q249 只读预检口同材料重评**七 Guard 全 PASS**、76.6 与原证逐位一致（干净 worktree `d65bd3b` 起 uvicorn :8001，避开并行 WIP）。
> - **owner Gate 三步（每步 AskUserQuestion 明示批准）**：零变化重冻被 Q29 判 409「no new version」⇒ 经批准改走 **Q32 作废后重冻**（v1.0 revoke → 首冻 **v2.0 `5277a9ad`** all_green）→ CCR 重扫 **clean** → `POST /api/fcw/assemble`（operations 令牌）⇒ **活证 `final_id=537a2f28-c0e5-11f1-8218-9bc72af50592`**（七 Guard 现场全过、76.6、published；快照 v1 frozen/active；审计 fcw.issued by owner-gate-20261006；Q263 三包 usage_count 各 +1 首次实战验证）。
> - **② 翻正依据**：docs/19「首批完成唯一标准＝真实部署库出一张 `final_id`、六路材料指向真实业务数据」满足——真值经负责人确认＋六路材料（PWS v2.0／PCP `be069bc0`／三包 `2b7acfd7`·`3ae7764a`·`2269ab13`／CCR `4cbafa0a`）全落库＋人工 Gate。**刻意没做**＝不重造产品内容（重录新链需臆造素材）、不自动 Gate、Q294 批独立落账不混装。
> - **【复判更新】**：① 功能覆盖达标／② **「核心完全可用」＝✅ 达标（本批翻正）**／③ 可上线未达标（现网部署＋真 ACME 未证，另有待裁项③）。
>
