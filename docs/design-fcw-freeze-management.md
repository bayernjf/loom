# FCW 冻结管理（D3.5 第 6 项）实现候选设计

> **状态**：⬜ **待裁决**（2026-10-02 起草，工程侧按路径 1 输出候选设计；不构成规格、不落码）。
> **用途**：docs/09 §D3.5 第 6 项「final_content_whitelist 冻结管理【V2】」——需求原文仅一句话，本文把该句展开为**可落码的实现候选**，逐项标注原文依据／工程推断／事实缺口，供负责人裁决后再点工落地。
> **纪律**：① 所有结论可溯源（Q 编号／文档行号，见文末来源索引）；② 原文空缺一律标【原文未给出，待补】，**禁臆造**；③ 工程推断一律标【工程建议·待裁决】，不冒充原文；④ 本文仅为候选，**不构成规格**。

---

## 1. 需求与边界

- **需求原文（唯一来源）**：docs/09 L90——「final_content_whitelist 冻结管理【V2】每个组装结果有唯一 ID·版本快照·不可变·回滚·复用」。**语义细节（版本粒度、冻结触发、回滚/复用形态）原文未展开，属【原文未给出，待补】。**
- **版本标注**：docs/09 明标【V2】；**Q249 裁决 d**（02 C1.193）＝「FCW 冻结管理（第 6 项）写侧归 V2 另点工（守 docs/09【V2】标注），本批只落 3.5 甲的只读审核队列，不与 Q242 的 PWS 冻结/吊销同批」。本文不擅自升降版本；候选乙涉及提前入 V1 须负责人另行裁决。
- **与 Q242 的边界（同族治理、不同对象）**：Q242 归 V2 的是 `product/whitelist_center` 的 **PWS 冻结/吊销**写口（对象＝产品层快照，角色 `whitelist_owner`）；第 6 项是 **FCW 层冻结**（对象＝组装结果 `final_content_whitelists` 行，下游＝段12 内容生成只读消费）。两对象、同族哲学（Q31/Q32），**Q249 已裁决不打包**。
- **「唯一出口」红线（不可绕）**：全系统只有 E1.1 publishFCW 能生成 `final_content_whitelist_id`（docs/05 §1.3，line 11036）；Q203 起有运行期守卫 `exit_guard.py`（只挂 `before_insert`）。本设计任何候选**不得**新增第二写口、不得让冻结/回滚/复用绕过 E1.1。
- **下游消费契约（必须纳入回滚/作废设计）**：PT-ART-GEN-V1.5（docs/06 §2.7）＝段12 内容生成**只读消费 FCW**，不重新决策上游、不重新打分；Q32 哲学＝版本作废后**下游消费入口状态判断、立即断消费**。

## 2. 现状盘点

### 2.1 已落能力（发证面）

| 能力 | 形态 | 依据 |
|---|---|---|
| 手动单条发证 | `POST /api/fcw/assemble`（E1.1，仅已验真 staff 令牌） | docs/05 §1.3 / §2.8（L179） |
| 任务驱动批量发证 | `POST /api/fcw/assembly-tasks`＋`GET .../{task_id}` | Q55 / docs/05 L180–181 |
| 成品只读列表/明细 | `GET /product-spaces/{id}/fcw`、`GET /fcw/{final_id}`（含 guards/score 明细） | docs/05 L182 |
| 中台导出 | `GET /exports/fcw.csv`（仅 final_id 单列）、`/exports/fcw.json` | Q100/Q132 |
| 台内 6 层原料包 JSON | `GET /fcw/{final_id}/material.json`（schema `loom.fcw.material-pack.v1`） | Q155 |
| 管理端只读卡片台 | `/admin/fcw` 跨租户分页列表＋行内六层原料包折叠 | Q177 |
| 预检只读口（不签发） | `POST /api/fcw/assemble/preview`（同装配同七 Guard 同评分、不 INSERT 不审计不查重） | Q249 裁决 b / 3.1 乙 |
| 组装工作台＋只读审核队列 | `/admin/fcw/assemble`、`/admin/fcw/review`（审 `pwc_combo` 候选，发证前） | Q249 落地五片 |

### 2.2 现有物理结构（`final_content_whitelists`，迁移 0009）

- 字段（models.py 实测）：`final_id` PK（uuid1，唯一出口 mint）/ `task_id` / `tenant_id` / `product_space_id` / `pws_id` / `pwc_id` / `pcp_id` / `csp_package_id` / `cstp_package_id` / `cep_package_id` / `ccr_report_id` / `law_review_id` / `platform` / `slot_id` / `goal` / `country` / `score` / `score_detail` / `score_incomplete` / `guards` / `guards_passed` / `publish_status`（draft|published，server_default published）/ `issued_by` / `created_at` / `published_at` / `updated_at`。
- 唯一约束 `uq_fcw_same_issue(pws_id, pwc_id, platform, slot_id)`：同冻结版×同骨架×同平台×同发布位不重复发证。
- **现状缺口（第 6 项语义对应）**：
  - 「唯一 ID」→ 已有（`final_id`）✅；
  - 「版本快照」→ **无 version/frozen/status 列**，任何版本化语义需迁移；
  - 「不可变」→ `exit_guard` 仅挡 `before_insert`；**`UPDATE`/`DELETE` 目前无守卫**（`updated_at` 列存在，业务上当前无写路径，但无强制）；
  - 「回滚」→ **无**（无状态、无断消费钩子）；
  - 「复用」→ **无独立实现**；与 docs/09 L87 第 4 项已落「单条复制 ID／多选批量复制（运营/客户）」存在重叠，**须先划清增量**（design-d3.5 §3.5 丙案已注明）。

### 2.3 PWS 冻结哲学（同族蓝本，可复用语义）

- **Q31**：大版本递增（v1.0→v2.0）；历史版本全保留；同一产品空间同时刻仅 1 个 active 版本，余者 superseded。
- **Q32**：快照作废（撤销发行）＝版本状态 `revoked`＋审计＋**下游消费入口状态判断、立即断消费**；专用急停，不用"产品整体暂停"兜底。
- **物理实现（pws_snapshots，迁移 0006）**：`version(16)` / `status(16)=frozen|superseded|revoked` / `is_active` 布尔（**active 非独立状态行**＝frozen 且 is_active=true 表达"当前版本"）/ `fingerprint` / `snapshot`+`readiness` JSON / `refreeze_tier`+`reason_code` / `superseded_by` / `created_by/at` / `revoked_by/at/reason`；唯一约束 `(product_space_id, version)`；成分行 `pws_snapshot_items`（不可变物化）；事件流水 `pws_freeze_logs`（freeze/refreeze/supersede/revoke＋actor_id）。

## 3. 候选设计（甲／乙／丙，均【工程建议·待裁决】）

> 四语义（版本快照／不可变／回滚／复用）分别给候选，每项标注改动面、依赖、冲突。**推荐项排第一**。所有实现形态均标【工程建议·待裁决】，不构成规格。

### 3.1 版本快照载体

| 候选 | 形态 | 改动面 | 依赖 | 冲突／风险 |
|---|---|---|---|---|
| **甲（推荐）** | **新建 `fcw_snapshots` 表**，参照 `pws_snapshots`：`final_id` 外链或快照主键＋`version(16)`／`status(16)=frozen|superseded|revoked`／`is_active` 布尔／`snapshot` JSON（6 路输入＋评分＋guards 明细）／`superseded_by`／`revoked_by/at/reason`；唯一约束 `(final_id, version)` 或 `(product_space_id, platform, slot_id, version)`【待裁决：版本粒度见 §3.5】；事件流水 `fcw_freeze_logs`（freeze/refreeze/supersede/revoke＋actor_id＋reason） | 迁移新建 2 表（`fcw_snapshots`＋`fcw_freeze_logs`）＋只读口 | 发证点 `assemble_one` 落首版快照（frozen＋is_active=true）；`fcw_assembly_tasks` 无关 | 与 PWS 同构，语义清晰、历史全保留；须确认**快照内容**（6 路输入引用 vs 全量 JSON 物化）——参照 PWS 双表（快照头＋成分行），FCW 6 路输入均为 id 引用，可只存引用＋score/guards 明细【工程建议】 |
| **乙** | **现有表加列**：`final_content_whitelists` 加 `version`＋`freeze_status`＋`is_active` | 迁移 1 表加列 | 现状表已有一行一组装结果 | 同键不重复发证（`uq_fcw_same_issue`）下**同键版本如何递增**语义不清；`UPDATE` 现有行破坏「不可变」直觉；不推荐 |
| **丙** | 只读查看，不落版本载体 | 无迁移 | docs/09 L90 的「版本快照」退化为行级只读（现有 GET 已够） | 与第 4 项已落能力重叠，增量不清晰；仅当裁决「版本化不做」时兜底 |

### 3.2 不可变强制

| 候选 | 形态 | 改动面 | 依赖 | 冲突／风险 |
|---|---|---|---|---|
| **甲（推荐）** | `exit_guard` 扩 `before_update`/`before_delete`：已发证成品行（`publish_status=published` 或已入快照）禁止 UPDATE/DELETE；`draft` 行（V1 无创建入口）除外 | 守卫扩展＋测试 | 现有 `exit_guard.py`（models.py 导入即装） | 须确认**是否有合法更新路径**（当前无）；Q249 裁决 a 已定「FCW 成品不可变由 V2 版本快照管」——与「快照表承载版本、原行永不 mutate」同向【工程建议】 |
| **乙** | 不加守卫，仅靠快照表承载不可变语义 | 无 | 现状 | `UPDATE final_content_whitelists` 仍可发生（无强制），与「不可变」措辞有落差 |
| **丙** | DB 级规则（trigger/约束） | 迁移 | — | 与 ORM 守卫双保险但双份维护；超出本仓既有治理风格（先例＝exit_guard 运行期守卫） |

### 3.3 回滚／作废

| 候选 | 形态 | 改动面 | 依赖 | 冲突／风险 |
|---|---|---|---|---|
| **甲（推荐）** | **参照 Q32**：写口 `POST /api/admin/fcw/{final_id}/revoke`（operations|platform_admin，role 口径同 Q242 族【待裁决】）→ 快照状态 `revoked`＋审计（reason 必填）＋**段12 内容生成入口加状态检查**（`content_products` 生成前校验所引 FCW 快照非 revoked，否则 409/422） | 后端写口＋入口钩子＋审计；迁移（快照表状态列） | Q32 哲学；PT-ART-GEN-V1.5 消费路径 | 「回滚」两义须先裁：**A＝作废当前＋重冻新版**（PWS Q32 语义）还是 **B＝恢复历史版本**（把 is_active 指回旧版）？原文「回滚」未展开【原文未给出，待补】——**甲默认 A**，B 需负责人确认 |
| **乙** | 只落状态与审计，不接下游断消费 | 后端写口＋审计；零迁移（若状态落内存/不落表则不可靠） | — | 只作废不断消费＝**伪造 Q32 语义**；不推荐 |
| **丙** | 回滚＝物理删除/隐藏行 | — | — | 违反「历史全保留」（Q31）与审计纪律；禁止 |

### 3.4 复用

| 候选 | 形态 | 改动面 | 依赖 | 冲突／风险 |
|---|---|---|---|---|
| **甲（推荐）** | **复制 ID＝再发证**：把某 `final_id` 的 6 路输入作为新组装请求参数，走 **E1.1 `POST /api/fcw/assemble`**（新 final_id、重新跑七 Guard）；前端「复用」按钮＝预填表单 | 前端页（复用预填）；零后端 | 现有 `assemble` 口；Q249 组装工作台表单 | 与第 4 项「单条复制 ID（运营/客户）」**划界**：第 4 项复制的是**候选池条目**，本项复制的是**已签发成品**；若负责人认为二者同义，则本项**无增量、不做** |
| **乙** | 复用＝同 final_id 多平台/多 slot 引用（不动上游） | 新语义 | — | 违反 `uq_fcw_same_issue` 与"组装结果=完整 6 层包"口径【工程建议不推荐】 |
| **丙** | 只读「引用此版本」链接，无写操作 | 前端 | — | 与第 4 项重叠；增量不清晰 |

### 3.5 版本粒度（前置裁决项，决定 3.1 甲唯一约束）

- 原文「每个组装结果有唯一 ID·版本快照」**未指明**：版本是挂在 **final_id**（一个成品一个版本，版本号恒 v1）还是挂在 **（product_space×platform×slot）键**（同键重冻出新版）？
- PWS 类比：PWS 版本挂在产品空间（同空间同时刻 1 active）。FCW 若参照，则版本应挂 **（product_space_id, platform, slot_id）** 键，重冻/换版产生新版本、旧版 superseded/revoked【工程建议】；但 FCW 现状 `uq_fcw_same_issue` 已挡同键重复发证——**若版本按键递增，则该唯一约束须放松为含 version**，属**契约变更，须负责人裁决**。
- 折中【工程建议·待裁决】：V2 首版只做 **final_id 级版本快照**（每个成品一个不可变快照行，版本恒 v1、状态 frozen，作废即 revoked），同键重冻语义留 V2 后续——改动最小、不触碰 `uq_fcw_same_issue`、满足「唯一 ID·版本快照·不可变·回滚」四词中的三词。

## 4. 需负责人裁决（候选，随点工裁决）

| # | 裁决项 | 影响 |
|---|---|---|
| a | **版本粒度**：final_id 级（每成品一快照，改动最小）vs 键级（同键重冻出新版，须放松 `uq_fcw_same_issue` 为含 version） | 决定 3.1 甲表结构与唯一约束 |
| b | **回滚语义**：A＝作废当前＋重冻新版（PWS Q32 语义，推荐）vs B＝恢复历史版本（is_active 指回旧版） | 决定 3.3 甲写口行为 |
| c | **复用划界**：第 6 项复用＝已签发成品再发证（走 E1.1）vs 与第 4 项候选池复制同义（本项无增量） | 决定 3.4 甲是否成立 |
| d | **不可变强制**：`exit_guard` 扩 `before_update`/`before_delete` 是否采纳 | 决定 3.2 甲 |
| e | **角色口径**：冻结/回滚写口的 RBAC（参考 Q242 族 `require_internal_actor`，或复用 operations|platform_admin） | 决定写口闸 |
| f | **提前入 V1 与否**：docs/09 标【V2】、Q249 裁 d 已守 V2；若要提前须另行裁决（同 Q166/Q167 超额前置先例） | 决定开工窗口 |

## 5. 事实缺口清单（禁臆造，一律标【原文未给出，待补】）

| # | 缺口 | 出处 |
|---|---|---|
| 1 | 「版本快照／回滚／复用」的具体语义（粒度、触发、形态） | docs/09 L90 仅一句话 |
| 2 | 冻结的**触发方**（系统自动 vs 人工 Gate）与**角色** | docs/09 L90；无对应 PT/角色规定 |
| 3 | 回滚后**下游已生成内容**的处置（Q30 换版四行中「已发布不追溯」是否适用于 FCW 回滚） | docs/09 L90；Q30 四行针对 PWS 层 |
| 4 | 复用与第 4 项「候选池复制 ID」是否同义 | docs/09 L87 vs L90 |
| 5 | 排期三列（工期/人员/计划起止） | docs/08 §2.2 L82 明令留【待补】 |

## 6. 落地建议顺序（候选，非承诺；工期一律【待补】）

| 序 | 项 | 前置 | 说明 |
|---|---|---|---|
| F1 | 裁决 §4 a–f | 负责人 | 一次性拍 6 项，最小包＝a 选 final_id 级、b 选 A、c 选再发证、d 采纳、e 复用 Q242 族、f 守 V2 或明示提前 |
| F2 | 3.1 甲＋3.2 甲 | F1 | 迁移新建 `fcw_snapshots`＋`fcw_freeze_logs`、`assemble_one` 落首版快照、`exit_guard` 扩 update/delete 守卫＋测试 |
| F3 | 3.3 甲（revoke 写口＋下游断消费钩子） | F2 | 写口＋段12 入口状态检查＋审计 |
| F4 | 3.4 甲（复用预填） | F3 | 纯前端 |
| F5 | 文档收口（02 追加 Q、handoff、08/09/11 契约回填） | F2–F4 | 随落码同步 |

---

## 附 · 来源索引（可逐条核对）

| 引用 | 出处 |
|---|---|
| 第 6 项需求原文（唯一 ID·版本快照·不可变·回滚·复用） | docs/09_全景体系_展示口径.md L90 |
| 版本标注【V2】＋第 4 项复制能力 | docs/09 L87（第 4 项）/ L90 |
| Q249 裁决 d（写侧归 V2、不与 Q242 打包）＋裁决 a（FCW 不可变由 V2 版本快照管） | docs/design-d3.5-whitelist-assembly-remaining.md Q249 追记（L143/L146）；02 C1.193 |
| PWS 冻结哲学（Q31/Q32） | docs/02_决策记录_ADR_Q1-Q72.md L123（Q31）/ L125（Q32） |
| PWS 快照物理实现（pws_snapshots/items/freeze_logs） | docs/04_契约层_数据模型.md L184 实现补登（迁移 0006） |
| FCW 物理表实现（迁移 0009） | docs/04 §2.21 实现补登（L296） |
| FCW 模型实测（无 version/frozen/status 列） | backend/app/final/final_whitelist/models.py（L26–L75） |
| exit_guard 只挡 before_insert | backend/app/final/final_whitelist/exit_guard.py |
| 七项 Guard（PT-FCW-ASM-V1.0） | docs/06_契约层_WF与Skill协议.md §2.6（L85–L89） |
| 段12 只读消费契约（PT-ART-GEN-V1.5） | docs/06 §2.7（L93–L97） |
| E1.1 唯一出口红线与已落发证/只读口 | docs/05_契约层_API与状态机.md §1.3（L69–L72）＋§2.8（L175–L185） |
| 排期三列【待补】 | docs/08_迭代计划与任务包.md §2.2（L78–L82） |
| D3.5 余项"不可一口气推进"与业务方输入项 | docs/20_MVP评审_2026-09-22.md §6.6 #10（L245/L250） |

---
*本文档为候选设计（工程侧路径 1 输出），未经裁决不构成规格；裁决后在 docs/02 追加 Q 编号并按先例落码。*
