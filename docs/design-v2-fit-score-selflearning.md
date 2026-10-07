# fit_score 自学习（段7/8 V2 余量）实现候选设计

> **状态：⬜ 工程候选材料（2026-10-06 起草，未获裁决）**——本文只摆现状、候选与裁决点，**未写代码、未建迁移、未跑盘点**。
> 对应待办：handoff「Q278 点名三件未落」之 **fit_score 学习**（Q259 遗留片之一）；权威需求见 docs/01 段7/8，台账锚点 docs/02 C1.203（C1.204）。
> 与 [design-v2-pcp-weekly-recalc.md](design-v2-pcp-weekly-recalc.md) 是两件事：那边是**段8 PCP 17 字段权重表**的每周重算（权重来源已交材料）；本文是**段7 发布位四维静态分 → fit_score** 这条派生链的学习闭环。

## 1. 需求与边界（只引原文，不补白）

- docs/01:106（发布位档案，`line 1098-1221` 痕迹，基准 HTML 已永久丢失，见 AGENTS 行号溯源降级）：「每位含 slotType、推荐档、格式约束（chars/dur）、**四维静态分 traffic/safe/conv/load（0-100）**、risk、gate。AI 拓展候选四维全 0 + pending_gate。**⚠ 四维如何聚合为单一 fit_score，全文无公式（红旗 §B1.1）**。」
- docs/08:50 V1 范围（Q73 合并后权威）：段 7/8「仅做 FCW 6 路输入所必需的静态底表基础版（发布位/平台规则/17 权重池录入与静态值，**无动态信号、无 fit_score 学习、无 PLATFORM-ADAPTER AI Skill**）」。
- docs/04:230：「Q41/Q42 每周动态信号重算 + AI 对照单 + 单项 ±0.05、**fit_score 学习闭环**、PLATFORM-ADAPTER AI Skill 均 V2」。
- docs/04:232（Q259 遗留片登记）：「weekly 调度节奏（Q41 实现形态现场定）、PLATFORM-ADAPTER AI Skill、**fit_score 学习闭环**、PCP-SCORE AI 生成器（V1 候选仅 manual）」。
- docs/08:116（Q260 落地行）：「**fit_score 学习需回流数据**」。
- 治理红线（docs/02 Q66 等）：**AI 只产候选、人工 Gate 裁决**；拟合分影响段11 FCW 评分（Q54），属高影响面，不得自动写回。

**红旗 B1.1 的精确状态（Q293 核对）**：原文挂的问题是「**四维如何聚合为单一 fit_score**」，这一半已由 **Q34** 裁决并落地（`fit_score = Σ(四维分 × 目的权重)`，目的权重矩阵 Σ=1 强校验，`pa_rules.py:89-96`/`71-86`）。**未答的另一半是「四维分本身从哪来、会不会随时间变」**——这才是本文要处理的「学习」。

## 2. 现状盘点（回源码实测，2026-10-06，head=0048）

### 2.1 已落（静态值 + 派生 + 单一真实消费方）

- **四维定义与派生**：`FIT_DIMS = ("traffic", "safe", "conv", "load")`（`pa_rules.py:31`）；`compute_fit_score(slot, weights)`（`pa_rules.py:89-96`）＝Σ(维度分 × 权重)，docstring 明写「**派生值，不落库（10 §2.4 建议）**」。
- **目的权重矩阵**：`goal_fit_weights` 表（`models.py:80`，Q34 挂 Q25 contentGoals，Σ=1 强校验、不归一化）；端点 `GET/PUT /api/admin/fit-weights`（`router.py:202/213`），**纯人工录入**。
  - Q34 已给真实样例（docs/02:133）＝四维中文名与权重矩阵配置化口径：**种草 = 流量 0.4／安全 0.2／转化 0.2／承载 0.2；转化 = 转化 0.4／安全 0.3／流量 0.2／承载 0.1**。⇒ `safe`＝**安全**（合规向）、`load`＝**承载**（承接向），两个维度的业务含义据此明确（见 2.3 为什么它们无回流数据源）。
- **四维分载体**：`publish_slots.traffic/safe/conv/load`（0-100），经 Q35 后台 CRUD 录入（`router.py:129-187`），**同样纯人工**。
- **只读出口**：`GET /api/admin/publish-slots/{slot_id}/fit-score`（`router.py:212`）→ `service.fit_score()`（`service.py:244-276`）。目的未配矩阵时返回 `fit_score=None` + `incomplete=true`，**不凑分**（对齐 Q22b 精神）。
- **唯一真实消费方＝段11 FCW 评分**：`final/final_whitelist/service.py:288-294` 取 `GoalFitWeight` 与 `PublishSlot`，算 `slot_fit` 传入 `fcw_rules.score_fcw(slot_fit_score=...)`，属 Q54 四项评分之一（0.4/0.3/0.3 量纲统一 ×100，**仅排序、永不做门槛**）。
- **代码自述边界**：`pa_rules.py:8` 原文写着「动态信号 / **fit_score 学习** / 每周重算均不在 V1（08 M11）」。

### 2.2 未落（本文要解决的）

1. **四维分零学习来源**：traffic/safe/conv/load 四个值没有任何采集、派生或校准路径——人工填进去就一直是那个值。
2. **目的权重矩阵零学习来源**：`goal_fit_weights` 同样纯人工，无候选、无 Gate、无变更审计以外的回路。
3. **无学习闭环载体**：平台适配 8 张表（`publish_slots` / `goal_fit_weights` / `platform_rules` / `slot_type_defaults` / `pcp_templates` / `pcp_weight_tables` / `platform_dynamic_events` / `pcp_recalc_candidates`，`models.py` 全量枚举）**无任何 fit_score 候选表**；docs/06 §7 人工 Gate 点位总览 12 行里**没有「fit_score 学习」这一行**（对比：同表有「PCP 权重重算 段8 运营 候选+对照单 Q41」）。
4. **算出来的分对人不可解释**：`GET /fit-score` 只回一个标量，人看不出「traffic 贡献 0.31、safe 贡献 0.12…」——**看不见就没法校准**，这是学习闭环的前置缺口（与「没有回路」同等重要）。

### 2.3 硬阻塞：唯一候选学习数据源与四维对不上（本批 grounding 最硬的发现）

docs/08:116 明写「fit_score 学习**需回流数据**」。全仓唯一的回流数据载体是段13 `effect_records`：

- 表：`core/effects/models.py:50`，迁移 0034 建表（Q126），`status` 只有 `matched|orphan` 两态（Q127 人工认领不新增第三状态）。
- 指标形态：`metrics` 为 **JSONB 七键稀疏子集**（`models.py:83-84`），**缺席键不落、绝不写 0、不许估算**（数据纪律硬性）。
- **七键全集**（`models.py:27-37`）：六个非负整数计数 `plays` / `likes` / `comments` / `shares` / `inquiries` / `conversions` ＋ 一个比率 `read_rate`（0..1）。

与四维逐项对照：

| 四维 | 七键中是否有候选源 | 事实 |
|---|---|---|
| `traffic`（流量） | `plays` 看似对应 | **该对应关系原文未给出**，属工程猜测 |
| `conv`（转化） | `conversions` / `inquiries` 看似对应 | **同上，原文未给出**；且两者取一还是如何合并亦未给 |
| `safe`（安全/合规） | **零候选源** | 七键无任何键能表达合规判定；合规在系统内是**机械判定**（Q48 词库三关卡、Q49 敏感领域法审），不是效果数据能给的量 |
| `load`（承接/负载） | **零候选源** | 七键无任何键能表达承接能力 |

**三条叠加的阻断**：
1. **映射规则原文未给**——自造「七键 → 四维」映射＝直接违反「禁工程臆造」。
2. **四维中两维无数据源**——即使给映射，`safe` 与 `load` 仍无从计算；强行用代理指标（如以 `likes` 代 `load`）是二次臆造。
3. **数据侧还不存在**——`effect_records` 属**段13＝V2**（Q73：V1 主链段 1→6→10→11，**不含段 12/13**），现网未部署（待裁项③），生产零行；本机开发库亦为 `t-e2e` 造数（Q290）。**没有真行就没有任何可回归的读数。**

> **关键判断（与 PCP 每周重算同型，但结论更硬）**：那件是「触发后权重从哪来」待定；这件是「**被学的那个量本身没有数据源**」。因此本文的推荐切片**不碰学习算法**，只做两件零臆造的纯加法——**把分摊开给人看**（甲）＋**给一条人工校准回路**（乙）。真学习（丙）必须等业务方先补规则。

## 3. 候选设计（均【工程建议·待裁决】，默认不改任何既有值）

### 3.1 甲（推荐第一切片）：fit_score 可解释化——回带四维分项与贡献值

- `GET /api/admin/publish-slots/{slot_id}/fit-score` 返回体**加法扩展**：在既有 `fit_score` / `incomplete` 之外回带 `breakdown`＝`[{dim, score, weight, contribution}]` 四行（Σ 与标量一致，可自校验）。
- **不动**：`pa_rules.compute_fit_score()` 的算法一字不改（只加一个等价的分项展开函数，二者共用同一份权重）；`incomplete` 语义不动；不落库。
- 价值：这是 3.2/3.3 的**共同前置**——没有可解释性，任何校准与学习都缺「人凭什么改」的落点。**零业务口径、零臆造、纯加法可回滚**。
- 形态先例：与 Q249 裁决 b 的 FCW 预检只读口（`POST /api/fcw/assemble/preview`，同材料同 Guard 求值不签发）同型。

### 3.2 乙（推荐与甲同批）：人工校准闭环（**口径上不叫「自学习」**）

- 运营在回带分项后手工调整 `publish_slots` 四维分（`PUT /api/admin/publish-slots/{id}` 已有，**只需补 before/after 审计与分项对比回带**，不改端点形状）或 `goal_fit_weights`（`PUT /api/admin/fit-weights` 已有）。
- 硬约束（照 Q259/Q264 纪律）：
  - 权限沿用 `require_internal_actor(OPERATIONS)`（Q242 已把这族 27 个写口收口，平台适配 7 端点同族）；
  - **每次校准写审计**（`slot.update` 扩 detail 带四维 before/after），沿用 Q35 既有 `slot.create/update/archive` 审计族；
  - **是否设单次幅度上限待裁**（PCP 侧有 `platform.recalc_step=0.05` 先例，四维 0-100 侧现无）；
  - **不自动触发**任何下游重算（FCW 评分是发证时现算的派生值，无缓存需失效）。
- **口径诚实条款**：本切片是「人工校准」，**不得在任何文档/UI 表述为「自学习」**——否则等于用工程手段假装业务规则已定（与 Q290 「`t-e2e` 数据不得据此自推」同一纪律）。

### 3.3 丙（真自学习，须先补业务规则，不可自推）

- 前提硬阻塞——业务方须给出**四份规则**：
  1. 「七键 → 四维」映射（含 `safe`/`load` 无源时如何处置：留人工？置缺权重？还是取消这两维？——**三选一都改变 fit_score 口径，属业务裁决**）；
  2. 各维归一化区间与算法（计数类如何压到 0-100；`read_rate` 是比率、其余是计数，量纲不一致的合成规则）；
  3. 最小样本量门槛与冷启动策略（新发布位无数据时怎么办）；
  4. 观察窗与回溯口径（按 `captured_at` 取窗？多期如何加权？）。
- 规则到位后的形态建议（**仅在规则给出后才可实现**）：产 `pending` 候选 → 人工 Gate → 写回，与 `pcp_recalc_candidates`（Q259）**完全同型**，可复用其 partial unique 与三件套端点形状。
- 依赖：需先有真回流数据（段13 落地 + 客户/Agent 真实回填），与待裁项②/③ 同族。

## 4. 需要负责人/业务裁决的点（汇总）

1. **切片边界**：只做甲（可解释化）／甲+乙（可解释化＋人工校准，推荐）／直上丙（工程侧不建议，规则缺位）。
2. **校准权限归属**：operations（与 Q259 动态信号同族，推荐）／新增角色码。⚠ 注意：docs/06 §7 人工 Gate 总览**没有 fit_score 这一行**，权威口径角色码原文未给；Q178 现限五角色，新增角色码属**契约变更**，与待裁项③ 的 `whitelist_owner` 是**同型前置问题**（可签发性须先定）。
3. **四维分是否允许跨发布位继承**：Q36 已有 `slot_type` 级规则，但那是**规则表**不是**四维分**；四维分现仅 slot 级。新增继承＝新语义，原文未给。
4. **是否设校准幅度上限**：PCP 侧有 `recalc_step=0.05` 配置化先例；四维侧无。若设，需业务给数值（工程不代拟）。
5. **是否纳入 V1 private beta**：docs/08:50 现明确 V1「无 fit_score 学习」；纳入则改 08 范围行，属排期项（连带待裁项④ 资源）。
6. **段13 回流数据何时有真行**：丙的硬前提；与待裁项②（主数据/跑链第二人）、③（客户侧认证）同族，**不在工程侧可控范围**。

## 5. 刻意不做（守边界）

- **不自造「七键 → 四维」映射**，不用 `likes` 之类代理指标去填 `safe`/`load`（禁臆造）。
- **不让 fit_score 落库**：现口径是派生值（10 §2.4），改口径属裁决（且会引入失效缓存问题）。
- **不把人工校准包装成「自学习」**（口径诚实，见 3.2）。
- **不动 Q54 评分权重**（0.4/0.3/0.3 及其「仅排序、永不做门槛」性质）。
- **不碰 fit_score 自学习的 AI 化**（与 PCP-SCORE AI 生成器同属重批，需 eval/golden + 成本预算）。
- 本材料阶段不写 env、不建迁移、不改端点签名；裁决后实现批再同批加守卫测试（仿 Q187/Q291 纪律）。

## 6. 来源索引

| 事实 | 位置 |
|---|---|
| 四维静态分 0-100 + 红旗 B1.1 原文 | docs/01:106（`line 1098-1221` 痕迹，基准 HTML 已丢失） |
| V1 无 fit_score 学习的范围口径 | docs/08:50（Q73 合并后权威）、docs/08:51（V2 段7/8 完整） |
| fit_score 学习闭环属 V2 / Q259 遗留片 | docs/04:230、docs/04:232 |
| 「fit_score 学习需回流数据」 | docs/08:116（Q260 落地行） |
| Q34 公式与 Σ=1 强校验 | `backend/app/platform/platform_adaptation/pa_rules.py:31,71-96` |
| Q34 权重样例（四维中文名：流量/安全/转化/承载） | docs/02 C1.6 Q34（:133）、docs/02:1369（配置化清单行） |
| fit_score 派生 service（不凑分） | `backend/app/platform/platform_adaptation/service.py:244-276` |
| 只读出口 | `backend/app/platform/platform_adaptation/router.py:212-221` |
| 唯一真实消费方（FCW 评分） | `backend/app/final/final_whitelist/service.py:288-294` |
| 代码自述「fit_score 学习不在 V1」 | `backend/app/platform/platform_adaptation/pa_rules.py:8` |
| 平台适配 8 张表全量枚举 | `backend/app/platform/platform_adaptation/models.py`（`__tablename__` 全量 grep） |
| 回流七键全集与稀疏纪律 | `backend/app/core/effects/models.py:11,27-37,83-84` |
| 段13 属 V2 | docs/08:51（Q73：V1 不含段 12/13） |
| 人工 Gate 总览无 fit_score 行 | docs/06:181-194（§7 十二行表） |
| FCW 预检只读口先例 | docs/02 C1.193（Q249 裁决 b，3.1 乙） |
