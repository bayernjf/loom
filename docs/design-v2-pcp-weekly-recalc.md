# PCP 每周重算触发（段7/8 V2 余量）实现候选设计

> **状态：✅ 3.1 甲＋3.2 甲已落地（2026-10-06 Q294，负责人「按你推荐来」；02 C1.237）**——本文的候选与裁决点保持原样，**落地范围＝§3.1 甲（SweepScheduler 第 6 作业＋默认关 env）＋§3.2 甲（只开 OpsTodo 提醒、不产权重）**；**§3.2 乙/丙与 §4 的 4/5/6 三个待裁点仍未裁**（乙的硬阻塞＝业务方先给「事件→权重」映射规则；丙随 PCP-SCORE 模型网关接通）。落地实现：`core/sla/jobs.py` 作业 `pcp_weekly_recalc_scan`、`platform_adaptation/service.py::scan_weekly_recalc_reminders`、配置中心 `platform.recalc_weekday/_hour/_tz_offset_hours/recalc_todo_due_days`（迁移 0049 纯种子）、env `LOOM_PCP_WEEKLY_SCAN_ENABLED` 默认关；测试 `tests/integration/test_pcp_weekly_recalc_scan.py` 10 例。原文（2026-10-05 起草时点）如下，一字未改。
> 对应待办：handoff「Q278 点名三件未落」之**每周定时触发（`recalc` 无调度器）**；权威需求见 docs/01 段7/8，台账锚点 docs/02 C1.203（Q259）。
> 与已落地的三包重配（[design-p2-package-reuse-reconfig.md](design-p2-package-reuse-reconfig.md)）是两件事：那边是段9 三包 usage 重配（已落 Q262–Q264/Q288）；本文是段8 **PCP 17 字段权重表**的周期性重算。

## 1. 需求与边界（只引原文，不补白）

- docs/01 段8 PT-PCP-V1.5（`line 2057` 痕迹，基准 HTML 已永久丢失，见 AGENTS 行号溯源降级）：「**17 字段权重总和 ≤1.0**；不修改产品原子；**动态信号每周更新触发重算**；平台间不共享权重池」。
- docs/01:175 主链表：「PCP 权重池｜平台间不共享；**动态信号每周触发重算 → 段 9-11 下游重算**」。
- docs/06:75 WF-06 同句：「动态信号每周更新触发重算」。
- 治理红线（docs/02 Q66 等）：**AI 只产候选、人工 Gate 裁决**。PCP 权重变更影响下游段9-11，属高影响面，任何自动路径都只能产 `pending` 候选，不得自动 `approve`/直接写回 `pcp_weight_tables`。

**原文未给、本文不臆造的缺口**：
1. 「动态信号」如何映射成 17 个字段的具体新权重——**算法/公式原文未给**。现有 `pa_rules.py` 只有校验、冲突、fit_score 派生，没有「事件→权重」函数。
2. 「每周」的具体节奏（星期几/时刻/时区）原文未给。
3. 无新动态信号的周是否仍强制重算，原文未给。

## 2. 现状盘点（回源码实测，2026-10-05，head=0048）

### 2.1 已落（静态底表 + 人工/手工触发，Q242/Q259）

- **动态事件 CRUD**：`platform_dynamic_events`（模型 `models.py:180`，迁移 0045 建表）；service `create_event/update_event/archive_event`（`service.py:568+`），写口受内部令牌闸（Q242）。
- **事件的唯一真实消费＝match advisory，不改判定**：`active_events_for()`（`service.py:652-667`）在平台规则 match 时**回带**当前生效事件；docstring 自述「advisory 消费方……**不改变规则判定**」。即事件目前不会自动改任何权重。
- **重算候选 + 人工 Gate 三件套已全**：`pcp_recalc_candidates`（`models.py:210`，partial unique `uq_pcp_recalc_pending`＝同 PCP 同刻仅一条 pending）；端点 `GET/POST /api/admin/pcp-recalc/candidates`、`.../{id}/approve|reject`（`router.py:369-437`）。
  - `create_candidate`（`service.py:686`）强制：Σ≤1.0（Q40）、单项变化 ≤ `platform.recalc_step`（Q42，默认 ±0.05，超限须走人工直编 `PUT /api/pcp/{id}`）、同 PCP 仅一条 pending。
  - `approve_candidate`（`service.py:1057`）才写回 `pcp.weights`、清 `template_code`、before/after 审计。〔Q309 复扫订正：旧作 `service.py:760+`——Q300 在该文件上方新增候选 service 后整体下移〕
  - **`source=ai|manual`，V1 仅接受 manual**（`models.py:216-217`、`schemas.py:120` 明写「PCP-SCORE AI 生成器随 V2」）。
- **调度底座可复用**：`SweepScheduler`（`core/sla/scheduler.py`，300s 一轮，含 Q89 多副本 leader 锁、Q139 协作中止、Q151 PG fence）＋统一 `run_jobs`（`core/sla/runner.py`，每作业独立会话/异常隔离）＋ `JOBS` 注册表（`core/sla/jobs.py`，现 5 作业，登记顺序即执行顺序）＋手工触发 `POST /api/admin/sla/run`（platform_admin，`sla/router.py:50`）。
- **运营待办底座**：`OpsTodo`（`product/modeling/models.py:90`，todo_type/entity/status/assignee_role/due_at，到期 sweep 置 escalated）；PWS 就绪已有「写 OpsTodo 提醒」先例（`whitelist_center/service.py:171`）。
- **fit_score 派生不落库**（Q34，`service.py:244-276`；Q309 复扫订正：旧作 `:203`）；**fit_score 自学习**仍随 V2（`models.py:12`），不在本文范围。

### 2.2 未落（本文要解决的就两处）

1. **周期触发**：没有任何东西按「每周」节奏去看动态事件/产出重算动作；`recalc` 只有 HTTP 手工三口。
2. **权重来源（更本质）**：`proposed_weights` 的 17 个新值，V1 只能由人填；自动产候选需要的「事件→权重」派生或 PCP-SCORE AI 生成器**都不存在**。

> 关键判断：**只加一个周调度器而不解决权重来源，它每周醒来没有任何合法动作可做**（不能凭空编 17 个权重，否则直接违反「禁工程臆造」与「AI 只产候选」）。因此裁决必须同时回答「触发机制」与「触发后产出什么」两层。

## 3. 候选设计（均【工程建议·待裁决】，默认不自动改权重）

### 3.1 周期触发机制

- **甲（推荐）：作为 `SweepScheduler` 的第 6 个登记作业 `pcp_weekly_recalc_scan`**
  - 复用既有 300s tick + leader 锁 + fence + checkpoint + 手工 `/run`；作业内部按「上次扫描水位 + 周节奏」判定本周是否到点（到点才动作，未到点空转返回 0），不新建第二个 asyncio 循环。
  - 门控仿 Q187 `discard_purge`：新增 env（建议 `LOOM_PCP_WEEKLY_SCAN_ENABLED`，**默认 false**，纯加法、可回滚）；周节奏/锚点走配置中心键（如 `platform.recalc_weekday`/`..._hour`，热更），不入 env（Q9 业务旋钮纪律）。
  - 优点：零新调度基建、自动获得多副本单实例与易主安全；缺点：300s 粒度（对「每周」完全够用）。
- **乙：独立 `WeeklyRecalcScheduler` 进程内循环**（仿 Q87 RestockWorker 同构）。隔离更清晰，但要重写一套锁/停启/水位，与甲能力重复，YAGNI。
- **丙：不加任何自动节奏**，维持人工 `POST /api/admin/sla/run`（可带 `only=["pcp_..."]`）+ 运营自排外部 cron。最省，但等于「每周触发」仍无产品内承载，与原文「每周更新触发」长期不符。

### 3.2 触发后产出什么（真正需要业务/负责人定的一层）

- **甲（推荐作为 V2 第一切片）：只产「待重算提醒」，不产权重**
  - 周扫描找出「该平台存在扫描窗口内新生效的 `active` 动态事件、且对应 active PCP 当前无 pending 候选」的 PCP；为每个开/续一条 `OpsTodo`（新 `todo_type`，如 `pcp_weekly_recalc`，assignee_role=operations，detail 带 platform/product_space/pcp_id 与命中事件 id 列表）。
  - **不**生成 `proposed_weights`、**不**建 candidate、**不**碰 `pcp.weights`；运营据提醒去走既有 manual 候选→Gate。确定性、可审计、零臆造，与 PWS 就绪提醒同型。
- **乙：确定性派生候选权重**（自动建 `source` 新增取值如 `scheduled` 的 pending candidate）
  - 前提硬阻塞：**必须先由业务方给出「动态事件类型/severity → 17 字段权重调整」的确定映射规则**（现 `pa_rules.py` 无此函数，原文未给）。规则到位前不可做，否则就是编算法。仍受 Σ≤1.0 与 `recalc_step` 约束、仍须人工 approve。
- **丙：PCP-SCORE AI 生成器产 `source=ai` 候选**（段8 完整 V2 愿景）
  - 接模型网关（参照 WF-06 PCP-SCORE 与 PLATFORM-ADAPTER 第 11 场景种子，0046），AI 读事件+现权重产候选，**只产 pending、人工 Gate**；需 eval/golden 回归与成本预算，是三件里最重的，且与「PLATFORM-ADAPTER 业务接入」「fit_score 自学习」同批依赖。

> 建议落地顺序：**3.1 甲 + 3.2 甲**先闭合「每周有节奏地把该重算的 PCP 摆到运营面前」（确定性、零臆造、纯加法）；3.2 乙/丙待业务给映射规则或模型网关接通后另裁，不得在本切片偷渡权重生成。

## 4. 需要负责人/业务裁决的点（汇总）

1. **触发机制选甲/乙/丙**（工程推荐 3.1 甲：复用 SweepScheduler 第 6 作业 + 默认关 env）。
2. **触发后产出选甲/乙/丙**（工程推荐 V2 第一切片 3.2 甲：只开 OpsTodo 提醒）。
3. **周节奏口径**：星期几/时刻/时区（建议默认「每周一 02:00 Asia/Shanghai」，但这是业务口径，需确认）；无新事件的周是否跳过（建议跳过，只在有新生效事件时提醒）。
4. **若走 3.2 乙**：业务方须提供「事件类型/severity→17 字段权重」映射规则与边界（现原文未给，工程不代拟）。
5. **扫描水位落点**：是否需要新增一张轻量水位表/键记录「每平台上次扫描时刻」（倾向用配置中心/已有审计事件派生，避免新表；若多副本严格去重需要再评估）。
6. 是否纳入 V1 private beta 范围（08 M11 现把每周重算划在 V2）；纳入则属排期项（待裁项④资源）。

## 5. 刻意不做（守边界）

- 不自动 `approve`、不直接写回 `pcp_weight_tables`（人工 Gate 红线）。
- 不在业务规则缺位时自造「事件→权重」算法（禁臆造）。
- 不碰 fit_score 自学习、PLATFORM-ADAPTER 业务接入（另两件 V2 余量，各自独立）。
- 本材料阶段不写 env、不建迁移、不改 `JOBS`；裁决后实现批再同批加门控默认关 + 守卫测试（仿 Q187/Q291 纪律：env 须经 compose 可达、默认值进契约门）。

## 6. 来源索引

- 需求：`docs/01_PRD_产品需求规格.md` 段8（:112-114）、主链表（:175）；`docs/06_契约层_WF与Skill协议.md:75`。
- 现状代码：`backend/app/platform/platform_adaptation/{models.py,service.py,router.py,pa_rules.py,schemas.py}`；`backend/app/core/sla/{scheduler.py,runner.py,jobs.py,router.py}`；`backend/app/product/modeling/models.py`（OpsTodo）。
- 相关台账：docs/02 C1.203（Q259 动态信号三口）、C1.131（Q187 discard_purge 门控 job 先例）、C1.147（Q203 门控纪律）；Q278 三件未落点名（handoff/AGENTS 待办）。
