# 新增内部角色与可签发性（V2 三件事的公共前置）实现候选设计

> **状态：⬜ 工程候选材料（2026-10-06 起草，Q297，未获裁决）**——本文只摆现状、候选与裁决点，**未写业务代码、未建迁移、未改角色表**；推荐甲中不需裁决的诚实化小改已随 Q297 落地＝写口守卫 UNGATED 补登 PWS 冻结/吊销两口（盲区变判据，零生产行为变化）。
> 定位：这不是一个独立功能，而是**三个 V2 余量共同卡在的一道契约前置**。三处都需要"一个权威角色码 + 它能否签发 staff 令牌 + 守哪些写口"，拆三次裁决会造成两到三次契约变更，故汇总成一份。
> 三件事：① fit_score 人工校准闭环（[design-v2-fit-score-selflearning.md](design-v2-fit-score-selflearning.md) §3.2 乙）；② PLATFORM-ADAPTER 候选表＋HumanGate（[design-v2-platform-adapter-business.md](design-v2-platform-adapter-business.md) §3.2 乙）；③ 待裁项③ 客户侧认证里 `whitelist_owner` 的可签发性（handoff/AGENTS 活跃待裁项③）。

## 1. 现状盘点（回源码实测，2026-10-06，head=0049）

### 1.1 现有六个角色码与"可不可签发 staff 令牌"的分界

`backend/app/core/rbac/__init__.py:18-31` 定义六个常量，分两类：

- **内部员工角色（5 个，可绑 staff PAT）**：`operations`、`product_reviewer`、`dictionary_admin`、`internal_compliance`、`platform_admin`。
  - 同一集合在两处**必须逐字一致**：`rbac.INTERNAL_ROLES`（:26，决定门控开时哪些口要真凭证）与 `staff_auth/service.py:34 INTERNAL_STAFF_ROLES`（决定签发 staff 令牌时允许绑哪些角色，`normalize_roles` 对未知角色直接 ValueError→422）。
- **客户角色（1 个，刻意不可签发）**：`whitelist_owner`（:22）。它在 `rbac` 有常量，但**不在** `INTERNAL_ROLES`、也**不在** `INTERNAL_STAFF_ROLES` ⇒ 门控开时不被当内部口保护，也无法给它签 staff 令牌。

### 1.2 受闸写口的角色分布（`tests/integration/test_write_gate_wiring.py` 实测）

守卫把每个受凭证保护的写口钉到期望角色元组，当前实际只用了四种角色：

- `operations`（OPS）：绝大多数写口——原子冻结/解冻/废弃/归档、三包 CRUD、平台底表、动态信号、PCP 重算三口、发证、FCW 预检/吊销、adapter 预览（Q296）。
- `product_reviewer`（REVIEWER）：原子 approve/reject/batch-approve/risk-override/cluster resolve。
- `internal_compliance`（COMPLIANCE）：原子 compliance-suspend/resume。
- `platform_admin`：layer-spaces items CRUD、staff-keys 签发红线。
- **`dictionary_admin` 当前没有任何写口挂它**（角色存在、可签发，但守卫矩阵里 0 口）——这是一个"已定义未使用"的角色，裁决时可考虑复用而非新增。

### 1.3 三处需求各自要什么

**① fit_score 人工校准（fit-score 乙案）**
- 需求：授权一个内部角色改四维静态分（新写口，方案设计见其 §3.2），与 PCP 侧 `PUT /api/admin/fit-weights`（现 OPS）同族但对象不同（那是目的权重矩阵，这是发布位四维分）。
- 缺口：docs/06 §7 人工 Gate 总览（:181-194）**没有 fit_score 这一行**，权威角色码原文未给。

**② PLATFORM-ADAPTER 候选裁决（adapter 乙案）**
- 需求：候选表 approve/reject 写口要一个审核角色。docs/06 §7 该行为「**平台审核员（展示口径）**」——明确标注是展示口径，**没有权威英文角色码**。
- 现状：`synthetic.py:307` 自述「候选投递/HumanGate 裁决/平台审核员界面随 V2」；Q296 已落的只读预览口用的是 **OPS**（守卫矩阵实测）。

**③ `whitelist_owner` 与 PWS 冻结两口**
- 红线：PWS 冻结盖章必须 **BO-07 `whitelist_owner`**（`whitelist_center/service.py:3` 引 line 7674；`_require_owner` :67-70 对缺角色抛 RoleNotAllowed）。
- 现状硬伤：冻结/吊销两口（`POST /product-spaces/{id}/pws/freeze`、`POST /pws/{id}/revoke`，router :78/:109）**既没有 `require_internal_actor`，也不在写口守卫的 GATED/UNGATED 任一名单**（实测 grep 0 命中）。它们只在 **service 层认 body 自报 actor 的 roles**，而 `whitelist_owner` 又**不可签发 staff 令牌** ⇒ 门控开启后，没有任何"可验真的 whitelist_owner 身份"能合法打这两口（自报在门控开时对内部口失效，但该口根本没接内部凭证闸，形成一处**身份模型悬空**）。Q242 当时因此刻意不给两口加闸（照搬会永久 403），登记归并进待裁项③。

### 1.4 一个必须先于写码对齐的机制事实

新增内部角色不是只加一个常量：要**同时**改 `rbac.INTERNAL_ROLES` 与 `staff_auth INTERNAL_STAFF_ROLES`（两处漂移会出现"能守门但签不出令牌"或反之），并把新写口加进守卫 `GATED` 矩阵（Q276/Q277 起该矩阵反向枚举，漏登记即判红）。客户角色若要"可验真"，走的是**另一套还不存在的客户认证**（待裁项③：账号/会话/客户 Key），**不能**靠把 `whitelist_owner` 塞进 `INTERNAL_STAFF_ROLES` 来糊——那会让客户拿到内部员工令牌，越权面扩大。

## 2. 需要先裁决的本质问题

1. **"平台审核员"要不要落成一个新内部角色码？** 还是复用现有 `operations`（Q296 预览口已用 OPS）或未占用的 `dictionary_admin`？
2. **fit_score 校准权限**归谁：OPS（与现有 fit-weights 写口同族，最省事）还是新设角色？
3. **`whitelist_owner` 走哪条路**：维持"客户角色 + 未来客户认证"（推荐，归待裁项③），还是另有内部承接角色冻结的安排（会改变 BO-07 红线语义，须业务确认）？

## 3. 候选设计（均【工程建议·待裁决】）

### 3.1 对①fit_score 校准：甲＝复用 `operations`（推荐）／乙＝新设 `fit_admin`

- **甲（推荐）**：新校准写口挂 `operations`。理由：同族 `PUT /fit-weights` 已是 OPS；fit_score 是派生值、校准属运营动作；零新角色、零契约面扩张，最快解锁。docs/06 §7 补一行"fit_score 校准｜运营"即可（把展示口径落到已存在的权威码）。
- **乙**：新设 `fit_admin`（或语义更近的名）。仅当业务要求"四维分校准与日常运营分权、需独立审计身份"才值得；代价是 +1 内部角色、两处集合、可签发令牌面扩大。

### 3.2 对②adapter 候选裁决：甲＝复用 `operations`（推荐）／乙＝新设 `platform_reviewer`

- **甲（推荐）**：候选 approve/reject 挂 `operations`，与 Q296 预览口、动态信号、PCP 重算三口保持同一运营族；"平台审核员（展示口径）"在工程侧映射到 `operations`，并在 docs/06 §7 该行注明映射（展示口径≠新角色）。
- **乙**：新设 `platform_reviewer` 内部角色。仅当平台适配审核要与运营分权（类似 product_reviewer 之于原子）才需要；须同步两处角色集合 + 守卫矩阵 + docs/06。
- 无论甲乙，候选裁决**一律 advisory、不改段11 七 Guard 判定**（其 §4 第 2 点红线）；若业务要 `block` 硬阻断发证，那是新增 Guard，另案高影响裁决，不混在本批。

### 3.3 对③whitelist_owner：甲＝维持客户角色、随待裁项③客户认证解决（推荐）／乙＝内部承接（不建议）

- **甲（推荐）**：本批**不**给冻结两口加内部凭证闸、**不**把 whitelist_owner 塞进内部角色；但做一件现在就能做的**诚实化小改**：把冻结/吊销两口补进写口守卫的 `UNGATED` 名单并注释"待裁项③ 客户认证承接"，让"当前无凭证闸"从**矩阵盲区**变成**显式登记的已知缺口**（Q276 反向前例：漏在两套名单外＝以后摘依赖也不会红）。真正的可验真客户身份随待裁项③（客户 Key/账号会话）落地。
- **乙（不建议）**：新设内部角色或让某内部角色代行 BO-07 冻结。会改变"客户对自己白名单负责"的红线语义，须业务明确授权；工程侧不代裁。

## 4. 需要负责人/业务裁决的点（汇总）

1. fit_score 校准角色：**甲复用 operations（推荐）**／乙新设 fit_admin。
2. adapter 候选裁决角色：**甲复用 operations（推荐）**／乙新设 platform_reviewer。
3. 若选乙×2：确认两个新角色码的确切英文码、是否都进 staff 可签发集（建议是，否则守了门签不出令牌）。
4. whitelist_owner：**甲维持客户角色、随③解决，本批只做守卫 UNGATED 显式登记（推荐）**／乙内部承接（须业务改 BO-07 语义）。
5. docs/06 §7 总览补两行权威角色（fit_score 校准、平台适配裁决的工程映射）——属把展示口径落成权威码，随 1/2 裁决一并写。
6. 是否把 `dictionary_admin`（当前 0 写口）纳入本次梳理：保留/启用/暂不动（倾向暂不动，仅登记事实）。

## 5. 刻意不做（守边界）

- 不在本材料阶段改任何角色集合、守卫矩阵、端点；裁决后实现批再改并同批加测试。
- 不把客户角色塞进内部 staff 令牌集（越权）。
- 不让 adapter 裁决变硬 Guard（advisory 红线）。
- 不替业务决定分权与否——复用 vs 新设的本质是"要不要独立审计身份"，属组织/职责裁决。
- 不实现客户认证本体（待裁项③，独立大项）。

## 6. 实现批（裁决后）的改动面预告（供估爆炸半径，非本批执行）

- 若全选甲：**零新角色**；仅新增 fit 校准写口（fit 乙案自带）、adapter 候选表+两口（adapter 乙案自带），两口均挂 OPS 并进守卫 GATED；冻结两口补进 UNGATED 注释；docs/06 §7 补两行映射。契约面零扩张。
- 若任一选乙：同批改 `rbac.INTERNAL_ROLES` + `staff_auth INTERNAL_STAFF_ROLES` 两处、守卫矩阵、staff 令牌签发用例（未知角色 422 / 新角色可签），并补 eval/集成。
- 全部为零迁移（角色是代码常量，非表数据；staff_api_key 已存 roles JSON，新码无需建列）。

## 7. 来源索引

- 角色常量与分界：`backend/app/core/rbac/__init__.py:18-31,45-60`；`backend/app/core/staff_auth/service.py:33-66`。
- 写口角色矩阵：`backend/tests/integration/test_write_gate_wiring.py`（GATED :21-53、UNGATED :72+）。
- PWS 冻结红线与悬空：`backend/app/product/whitelist_center/service.py:3,67-70`、`router.py:78,109`；`pws_rules.py:30`。
- 三处需求原文：`docs/06_契约层_WF与Skill协议.md:181-194`（§7 Gate 总览）；`synthetic.py:307`；本目录两份 V2 设计 §4。
- 相关台账：Q178（身份层甲案，02 C1.122）、Q242（27 写口统一，whitelist 两口归并③）、Q276/Q277（守卫反向枚举）、Q296（fit 甲/adapter 甲只读预览已落，02 C1.239）。
