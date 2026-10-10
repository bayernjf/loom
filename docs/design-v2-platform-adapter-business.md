# PLATFORM-ADAPTER 业务接入（段7 V2 余量）实现候选设计

> **状态：⬜ 工程候选材料（2026-10-06 起草，未获裁决）**——本文只摆现状、候选与裁决点，**未写代码、未建迁移、未跑盘点**。
> 对应待办：handoff「Q278 点名三件未落」之 **PLATFORM-ADAPTER 业务接入**；权威需求见 docs/01 段7（PT-PLATFORM-ADAPTER-V1.0）、台账锚点 docs/02 C1.204（Q260）。
> 与 [design-v2-pcp-weekly-recalc.md](design-v2-pcp-weekly-recalc.md)（段8 PCP 每周重算）、[design-v2-fit-score-selflearning.md](design-v2-fit-score-selflearning.md)（段7 fit_score 学习）是**三件独立余量**，本文只做第一件。

## 1. 需求与边界（只引原文，不补白）

- docs/01:103（段7 主链，WF-06）：「PLATFORM-PARSE → COMPAT-RULE → DYNAMIC-SIGNAL 动态信号采集 → **PLATFORM-ADAPTER（state=pending_review, runs_7d=0，即该核心 Skill 在原型中尚未启用）** → PCP-BUILD → PCP-SCORE」。
- docs/06:63-70（§2.3 **PT-PLATFORM-ADAPTER-V1.0 已定稿 ✅**，line 2043 痕迹）七条硬约束：
  1. 只读 frozen PWS
  2. 禁止消费 pending PWC/PWS
  3. 禁止输出成稿（正文/脚本/标题）
  4. **禁止生成 final_id**
  5. 必须返回 `allow` / `downgrade` / `block` / `pending_review` **四态**
  6. **AI 输出一律 pending_review 需 HumanGate**
  7. 无 frozen PWS 时返回缺失、**不造假数据**
- docs/06:187（§7 人工 Gate 点位总览）：「**平台适配候选｜段7 / WF-06｜平台审核员（展示口径）｜AI 输出一律 pending_review｜PT-PLATFORM-ADAPTER**」。
- 红旗 S2（docs/03:18）：「**关键 Skill 在原型中未启用**：SK-LIB-PLATFORM-ADAPTER（段7 核心）state=pending_review、runs_7d=0——主链的平台适配与知识进化两个枢纽**只有协议、没有运行证据**」。
- 治理红线（docs/02 Q66 等）：AI 只产候选、人工 Gate 裁决。

> **规格不缺**：PT-PLATFORM-ADAPTER-V1.0 七条约束已定稿 ✅（docs/06 §2.3、docs/12 标 ✅）。本文的缺口**不是"协议怎么写"，而是"谁在什么时候调它、结果落到哪、谁裁决"**——即业务接线。

## 2. 现状盘点（回源码实测，2026-10-06，head=0048）

### 2.1 已落（Q246／迁移 0046：引擎侧预备件齐了）

- **场景注册**：`SCENE_PLATFORM_ADAPTER = "PLATFORM-ADAPTER"`（`core/model_registry/seeds.py:264`），`ai_scene_routes` 路由到 **synthetic**（迁移 0046 纯种子，无 schema 变更）。
- **Prompt v0.1 已入库**：`PLATFORM_ADAPTER_PROMPT_TEMPLATE`（`seeds.py:268-286`），正文即 docs/06 七条约束的运行时化，并声明**三个变量**：`PLATFORM_ADAPTER_PROMPT_VARIABLES = ["pws", "platform_rules", "dynamic_events"]`（`seeds.py:288`）。
- **synthetic 构造器**：`build_platform_adapter()`（`synthetic.py:296-334`）——四态机械映射已实现：
  - 无 frozen PWS → `{"missing": True, "reason": "no_frozen_pws"}`
  - 命中 `effect=blocked` → `block`；`effect=partial` → `downgrade`
  - 有 active 动态信号 → `pending_review`
  - 其余 → `allow`；返回体 `gate` 恒 `pending_review`
- **构造器自述缺口（最权威的一句）**：`synthetic.py:307`——「**业务接线（候选投递/HumanGate 裁决/平台审核员界面）随 V2 后续片**」。
- docs/08:116（Q260 落地行）逐字同义：「**候选投递/HumanGate/平台审核员界面随 V2**」。

### 2.2 未落（反向枚举实测，非推理）

1. **无调用方**。全仓 `llm-*` 触发端点只有 **5** 个（**Q293 逐行点清，初稿误写 4——漏了 CAT-RECOG 的 `llm-invoke`**）：`llm-invoke`（`core/model_registry/router.py:297`，C1 识别，Q82）、`llm-plan`（`product/fieldpool/router.py:157`）、`llm-expand`（`product/atom/router.py:145`）、`llm-build`（`product/condition/router.py:152`）、`llm-resolve`（`core/model_registry/router.py:339`）——**无一为 PLATFORM-ADAPTER**。平台适配自身 **25** 个端点（`platform/platform_adaptation/router.py` 逐行点清，**初稿误写 24**）**无一涉及 adapter**。⇒ Prompt 的三个变量 `$pws`/`$platform_rules`/`$dynamic_events` **至今无人组料**。
2. **无结果载体**。平台适配 8 张表（`models.py` 全量 `__tablename__` 枚举：`publish_slots` / `goal_fit_weights` / `platform_rules` / `slot_type_defaults` / `pcp_templates` / `pcp_weight_tables` / `platform_dynamic_events` / `pcp_recalc_candidates`）**无任何 adapter 候选或决策表**。四态算出来后无处可放。
3. **无 HumanGate 面**。docs/06 §7 登记的「平台适配候选」审核点无端点、无队列、无界面；Q242 收口的 27 个受闸写口里也没有它。
4. **无 eval/golden 护栏**。`eval/datasets/skills/` 与 `eval/golden_cases/skills/` 各 9 个案例（ATOM-AFFINITY / ATOM-CANON / ATOM-EXPAND / CAT-RECOG / COMBO-VALIDATE / CONFLICT-PRECHECK / DIM-MERGE / PWC-SCORING / TYPE-MATCH），**无 PLATFORM-ADAPTER**。⇒ 红旗 S2 的「runs_7d=0」至今**没有任何回归证据**，且切真模型前无 golden 就无法防漂移。
5. **四态无消费方**。即便落了库，`allow/downgrade/block/pending_review` 该被谁读、与段11 FCW 七 Guard 是何关系，原文未给。
   - **状态机已有设计规格**（docs/13:121-128 §1.8 两行迁移表）：`（输入）| 适配判定 | 只读 frozen PWS；无 PWS 返回缺失不造假 | allow/downgrade/block/pending_review | AI 输出一律 pending_review 需 HumanGate`；`pending_review | 人工审核 | **降级动作只能从 Q38 动作字典选** | allow/downgrade/block | 禁生成 final_id、禁输出成稿`。
   - ⚠ **陈述精确化（照 Q288 对 design-p2 §6 的同型处理）**：docs/13:123 那句「**截至 Q116** 代码未实现适配判定与人工审核端点……`platform_dynamic/` 为空包」**已被 Q246（0046 场景＋Prompt v0.1＋synthetic 四态构造器）与 Q259（0045 七端点＋match advisory）超越**，该读数按不回改保留、由本条点名纠偏。**仍未实现的是本文 2.2 的 1–4 项**（调用方/载体/Gate 面/eval 护栏），不是"四态判定本身"。

### 2.3 降级动作字典：口径已定稿 ✅，但**载体零落地**（Q293 实测，初稿曾误判为「原文未给」）

- **口径已定稿，不是待裁项**：docs/02 C1.6 **Q38 ✅**（用户原话口径）——「降级建议必须从预设动作字典里选（字典可配置），**不许 AI 自由发挥**。字典初始项：**REMOVE_BRAND / REMOVE_CLAIM / REMOVE_LINK / SOFT_CTA / SHORTEN / SUBST_WORD**（联动段10 CP-DOWN 映射）。AI 输出 = 动作组合 ＋ 中文理由；段12 按结构化指令执行。」docs/13:128 与 docs/12:148 均指向同一字典。
- **但全仓零代码落地**：反向枚举 `REMOVE_BRAND` / `SOFT_CTA` / `SUBST_WORD` / `downgrade_action` / `action_dict` 于 `backend/` **零命中**；平台适配 8 张表无字典表（`content_goals` 属 Q25、已落 `product/condition/models.py:36`；Q38 与 Q25/Q43/Q46 同入 docs/10:375「字典管理 dict_management」后台区，docs/10:375 标注「全部 CRUD ＋ 审计」**尚无实现**）。〔**Q309 注：本行的「尚无实现」前提已过期**——Q38 载体随 **Q306** 落（`downgrade_actions`，迁移 0051）、Q43 载体随 **Q308** 落（`pool_options`，迁移 0052），docs/10 §dict_management 现状行两者均 ✅；本文其余「PLATFORM-ADAPTER 真模型业务接入」待裁事实不受影响。旧行号 `docs/10:368`／`:369` 系本节上方新增迁移登记行所致；旧行号 `:372-374` 系其后又插行所致，现行 `:375`〕
- ⇒ **乙方案若要落 docs/13:128 的「人工审核时从 Q38 动作字典选降级动作」，必须先落 Q38 字典载体**（CRUD ＋ 审计），否则审核人无处可选。**这不是新裁决，是已定稿口径的欠实现**。
- ⚠ **docs 内部口径漂移（须登记，工程侧不擅自改 Q 记录）**：docs/02:141 六项为 `REMOVE_BRAND / REMOVE_CLAIM / REMOVE_LINK / SOFT_CTA / SHORTEN / SUBST_WORD`；docs/10:375 现举例为 `REMOVE_BRAND / REMOVE_CLAIM / REMOVE_LINK / SOFT_CTA / SHORTEN / SUBST_WORD`（**Q295 已按 docs/02 C1.6 订正销账**——2026-10-06 负责人授权，原举例 `REMOVE_HOOK`/`REWRITE` 系口径漂移，以 docs/02 为准，docs/10:375 即订正后现状行）。旧行号 `docs/10:372-374` 系插行所致，现行 `:375`。

### 2.4 组料三源全部已存在（本文最有利的一条事实，零臆造）

Prompt v0.1 要的三个变量，在仓内**都已有生产消费方的现成函数**，不需要新业务口径：

| 变量 | 现成来源 | 现状 |
|---|---|---|
| `$pws` | `PwsSnapshot`（`product/whitelist_center/models.py`），段6 冻结件 | 已被段11 消费（`final_whitelist` 走 `ensure_fcw_consumable`）；PT 约束「只读 frozen」天然满足 |
| `$platform_rules` | `service.match_rules()`（`platform/platform_adaptation/service.py`） | 已有端点 `GET /api/admin/platform-rules/match`（`router.py:308`，Q309 复扫订正：旧作 `:286`），Q36 四层选择器＋country 横切已实现 |
| `$dynamic_events` | `service.active_events_for()`（`service.py:725`） | **已被 Q259 match advisory 消费**（`router.py:319`），生效期过滤（`effective_start ≤ now ≤ effective_end`）已实现 |

⇒ **"谁调"这一层的输入齐备**。真缺口只在「触发方式 / 结果载体 / Gate 面 / 护栏」四处。

### 2.5 一处必须先对齐的形状差异（Q293 实测发现）

Prompt v0.1 要求的返回契约（`seeds.py:281`）是五键：`{"missing", "decision", "reason", "refs", "gate"}`。
但 synthetic 构造器在**无 frozen PWS 分支只返两键**：`{"missing": True, "reason": "no_frozen_pws"}`（`synthetic.py:311`）——**没有 `decision`、没有 `refs`、没有 `gate`**。

⇒ 任何消费方都必须同时容忍「五键」与「两键」两种形状，否则 `missing=true` 时取 `decision` 会 KeyError。这属**已落代码与已定稿协议之间的形状缺口**，需在接线时一并处理（是补构造器、还是在消费方归一，属实现细节，但**契约须显式登记到 docs/05**）。

## 3. 候选设计（均【工程建议·待裁决】，默认不自动放行）

### 3.1 甲（推荐第一切片）：只读预览口——四态直接回带，零落库

- 新增 `POST /api/admin/platform-adapter/preview`：body 给 `pws_snapshot_id` ＋ `platform` ＋ `slot_type`/`slot_id`/`country`（复用 `match_rules` 现有入参形状），service 组三料 → 调 `gateway`（V1 路由仍 synthetic）→ 四态**直接回带**，**不落库、不改任何判定、不写 Gate 审计**。
- 权限：`require_internal_actor(OPERATIONS)`（Q242 同族纪律）。
- **形态先例**：与 Q249 裁决 b 的 FCW 预检只读口 `POST /api/fcw/assemble/preview`（同材料、同七 Guard 求值、不签发、不写审计、不查重）**完全同型**，可直接抄其零副作用契约测试。
- 顺带闭合 2.4 的形状缺口：预览口是第一个真实消费方，**归一 `missing` 分支的返回形状**并登记 docs/05。
- 价值：把"引擎侧预备件"变成"可被人调用并看见输出"，是乙的前置，**零业务口径、纯加法可回滚**。

### 3.2 乙（推荐与甲同批或紧接）：候选表 ＋ HumanGate 闭环——这才是闭红旗 S2 的形态

- 新表 `platform_adapter_candidates`，**完全仿 Q259 的 `pcp_recalc_candidates`**：
  - `source`（`synthetic|ai|manual`，V1 仅 `synthetic`）、`pws_snapshot_id`、`platform`/`slot_type`/`slot_id`/`country`（可空）、`decision`（四态）、`reason`、`refs` JSONB、`status`（`pending|approved|rejected`）、`missing` 布尔；
  - **partial unique** 防重：同 (pws_snapshot_id, platform, slot_type, slot_id) 仅一条 pending（照 `uq_pcp_recalc_pending` 写法）；
  - `reject` reason 必填（照 Q259）。
- 三件套端点：`GET /api/admin/platform-adapter/candidates`、`POST .../{id}/approve|reject`，写口全 `require_internal_actor(OPERATIONS)`，逐条写审计（`platform_adapter.approved/rejected`）。
- **`approve` 语义必须守红线**：PT 约束 6「AI 输出一律 pending_review 需 HumanGate」⇒ **`approve` 只解除 pending 并留痕，不得自动放行到 `final_id`、不得改写平台规则或发布位约束**。四态是**建议**，唯一出口仍是段11 `publishFCW`。
- **若 `approve` 要落到具体降级动作**（docs/13:128 的目标态 allow/downgrade/block），**须同批或前置落 Q38 降级动作字典载体**（见 2.3：口径已定稿 ✅、代码零落地），审核人才有可选动作；且动作必须**从字典选、禁 AI 自由文本**（Q38 原话红线）。**本文默认乙只落"解除 pending ＋ 留痕"，降级动作选字典单列为 §4 第 4 点待裁。**
- 审核角色：docs/06 §7 写的是「**平台审核员（展示口径）**」——⚠ 权威口径的角色码原文未给，Q178 现限五角色。**是否新增角色码属契约变更**，与待裁项③ 的 `whitelist_owner` 同型（见 §4 第 3 点）。

### 3.3 丙（最重，须在乙之后）：接真模型

- 把 `ai_scene_routes` 的 PLATFORM-ADAPTER 由 synthetic 切真模型（Q148 已接 agnes 网关、8 chat 场景真模型、Fernet 加密、USD 成本看板），Prompt v0.1 → v1.0。
- **前置硬条件**：先补 `eval/datasets/skills/PLATFORM-ADAPTER.yaml` ＋ `eval/golden_cases/skills/PLATFORM-ADAPTER.yaml`（CI 门禁跑 `python eval/runner.py`，101 案回归），**无 golden 不许切真模型**——否则就是无护栏接真钱模型。
- 需成本预算与 token 上限（对齐 Q148 日预算 50 USD/天 口径）。
- **丙不改变红线**：真模型输出一律 `pending_review`（PT 约束 6），与 synthetic 同规。

> **建议落地顺序**：甲（预览）→ 乙（候选＋Gate，闭红旗 S2）→ 丙（真模型）。三段各自可独立停，**不得跳甲直接接真模型**（无载体则真模型输出无处可放，等于花钱产出孤儿）。

## 4. 需要负责人/业务裁决的点（汇总）

1. **切片边界**：只做甲／甲+乙（**推荐**）／直上丙（工程侧不建议）。
2. **`block`/`downgrade` 能否影响段11 FCW 七 Guard**？本文全部候选**一律 advisory、不改判定**（守 PT 约束 4「禁止生成 final_id」＋ 红线）。若业务要求 `block` 硬阻断发证，那是**新增 Guard**，属高影响面裁决，工程侧不代裁。
3. **审核角色口径**：docs/06 §7 的「平台审核员」是**展示口径**，权威角色码原文未给。是否新增角色码？Q178 限五角色，**可签发性须先定**——与待裁项③ 的 `whitelist_owner` 是**同一类前置问题**（建议一并裁，避免两次改契约）。
4. **`approve` 是否要落到具体降级动作**？⚠ **初稿曾把此项误判为「降级动作原文未给」，Q293 核对后订正**：口径**已定稿 ✅**（Q38 六动作，禁 AI 自由文本，见 2.3）。真问题是两个：
   - **a 是否在乙批同带 Q38 字典载体**（`approve` 时让人从字典选动作）？还是乙只解除 pending、字典另点工？——工程侧倾向**另点工**，避免一批里混两张表两套审计。
   - **b docs 口径漂移须先订正**（docs/02:141 与 docs/10:375 现均六码一致——**Q295 已按 docs/02 C1.6 订正销账**，原 `REMOVE_HOOK`/`REWRITE` 举例系漂移，见 2.3）。**当时是文档事实冲突、工程侧不擅自改 Q 记录；Q295 负责人已授权订正，本项已销**。旧行号 `docs/10:372-374` 现行 `:375`。
5. **触发方式**：operations 显式手工触发（仿 Q83 `llm-build`「restock_auto 不自动消费」纪律，**推荐**）／段7 链内自动调用。前者可控可测，后者会与「AI 只产候选」的节奏混在一起。
6. **谁在什么时机产生第一批候选**：甲乙都只提供能力，不产生候选。首批触发口径（每个新 frozen PWS 自动产一条？运营手工触发？）属业务节奏，**原文未给**。
7. **是否纳入 V1 private beta**：docs/08:50 现明确 V1「无 PLATFORM-ADAPTER AI Skill」；纳入则改 08 范围行，属排期项（连带待裁项④ 资源）。

## 5. 刻意不做（守边界）

- **不自动放行、不自动 block**（PT 约束 6＋人工 Gate 红线）；`approve` 只解除 pending、留痕。
- **不让四态改写 FCW Guard 结果**、不生成 `final_id`（PT 约束 4）。
- **不切真模型**（丙独立批，且以补 golden 为硬前置）。
- **不外推降级动作**：Q38 字典口径已定稿 ✅，但**在 docs 口径漂移订正前不落字典代码**（见 §4 第 4 点 b）；且不套用 PT-COMPLIANCE 的「降级只出建议」口径到本 Skill。
- **不把「四态判定已实现」与「业务已接入」混为一谈**：引擎侧有构造器 ≠ 有人调用（红旗 S2 的口径就是"有协议、无运行证据"，接线前不得声称 S2 已闭）。
- **不新增角色码**（契约变更，须裁决；见 §4 第 3 点）。
- 本材料阶段不写 env、不建迁移、不改端点；裁决后实现批再同批加守卫测试（仿 Q187/Q291 纪律）。

## 6. 来源索引

| 事实 | 位置 |
|---|---|
| 段7 链与「state=pending_review, runs_7d=0」原文 | docs/01:103 |
| PT-PLATFORM-ADAPTER-V1.0 七条约束（定稿 ✅） | docs/06:63-70（§2.3，line 2043 痕迹）、docs/03:19（M0 复核） |
| 「平台适配候选」Gate 登记（展示口径角色） | docs/06:187（§7 人工 Gate 点位总览） |
| 红旗 S2 原文 | docs/03:18 |
| V1 不含 PLATFORM-ADAPTER AI Skill | docs/08:50、docs/08:51（V2 段7/8 完整） |
| 「候选投递/HumanGate/平台审核员界面随 V2」 | docs/08:142（Q260）、docs/04:232（Q259 遗留片） |
| 「业务接线随 V2 后续片」自述 | `backend/app/core/model_registry/synthetic.py:307` |
| **Q38 降级动作字典口径定稿 ✅（六动作）** | docs/02 C1.6 Q38（:141）、docs/10:375、docs/12:148 |
| **Q38 字典零代码落地**（反向枚举零命中） | `backend/` 全量 grep `REMOVE_BRAND`/`SOFT_CTA`/`action_dict` |
| **docs 口径漂移**（原四项动作名对不上） | docs/02:141 vs docs/10:375（**Q295 已按 docs/02 C1.6 订正销账**；原 `REMOVE_HOOK`/`REWRITE` 举例系漂移） |
| 段7 四态状态机两行迁移表 | docs/13:125-128（§1.8） |
| docs/13:123 旧读数已被 Q246/Q259 超越（陈述精确化） | docs/13:123 vs 02 C1.203/C1.204 |
| 场景注册与 Prompt v0.1、三个变量 | `backend/app/core/model_registry/seeds.py:264-288` |
| synthetic 四态机械映射 | `backend/app/core/model_registry/synthetic.py:296-334` |
| **五键 vs 两键形状缺口** | `seeds.py:281` vs `synthetic.py:311` |
| 迁移 0046（纯种子、无 schema 变更） | `backend/alembic/versions/0046_platform_adapter_seed.py`、docs/17 §迁移头 |
| `match_rules` 四层选择器 | `backend/app/platform/platform_adaptation/service.py`、`router.py:308` |
| `active_events_for` 生效期过滤 | `backend/app/platform/platform_adaptation/service.py:725` |
| match advisory 回带（Q259） | `backend/app/platform/platform_adaptation/router.py:319` |
| 平台适配 8 张表 / **25** 端点全量枚举 | `backend/app/platform/platform_adaptation/models.py`、`router.py`（`@router.*` 逐行点清＝25，**初稿误写 24**） |
| **5** 个 `llm-*` 端点（无 adapter） | `core/model_registry/router.py:297,339`、`product/fieldpool/router.py:157`、`product/atom/router.py:145`、`product/condition/router.py:152`（**初稿只列 4 个、漏 `llm-invoke`**） |
| eval 9 案例无 PLATFORM-ADAPTER | `eval/datasets/skills/`、`eval/golden_cases/skills/`（目录全量枚举） |
| Q242 写口收口纪律 | docs/23 §10.4、docs/02 C1.186 |
| Q83 手工触发先例（不自动消费） | docs/02 C1.94 段、`product/condition/router.py:152-158` |
| FCW 预检只读口先例（Q249 裁决 b） | docs/02 C1.193、3.1 乙 |
