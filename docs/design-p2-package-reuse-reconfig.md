# 三包复用计数与重配触发（P2 续片）实现候选设计

> **状态**：✅ **已裁决并落地**（2026-10-03 起草；负责人 2026-10-03「按照推荐来」→ 4 裁点全按推荐：载体甲 / 人工更新即清零 / PCP 钩子不区分微调 / 两源同批落 → 02 C1.208 Q264 落地，见 §3 各表推荐列）。
> **用途**：docs/08 §2.3 P2「段9 D0 三包」剩余项收口——Q45「使用满 20 次（配置项）或 PCP 权重表更新 → 触发重配走 Gate」。需求原文仅一句话，本文把它展开为**可落码的实现候选**，逐项标注原文依据／工程推断／事实缺口，供负责人 Gate 裁决后再点工落地。
> **纪律**：① 所有结论可溯源（Q 编号／文档行号，见文末来源索引）；② 原文空缺一律标【原文未给出，待补】，**禁臆造**；③ 工程推断一律标【工程建议·待裁决】，不冒充原文；④ 本文仅为候选，**不构成规格**。

---

## 1. 需求与边界

- **需求原文（唯一来源）**：02 L161 Q45——「按（产品 × 平台 × 目的）三元组配一份并缓存复用，同组合多条内容共用（内容差异靠 PWC 骨架不同保证，拍法一致即账号人设稳定）；**使用满 20 次（配置项）或 PCP 权重表更新 → 触发重配走 Gate**。」
- **配置登记**：02 §C2 L1376「三包配方复用次数阈值 | 20 次 | Q45」；配置键 `package.reuse_threshold`（config_center seeds.py L76，默认 20，min 1）。
- **版本边界**：docs/10 L217「WF-07 AI 选包、20 次重配、usage_count 递增均 V2（列先行不计数）」→ 本片即该 V2 项的**计数与触发侧**；**AI 选包侧不可做**（docs/12 #21 PT-CONTENT-GOAL-PLAN 仍 ⬜ 占位未定稿，禁臆造）。
- **「重配走 Gate」的载体原文未给**：候选表形态、人工批准接口、重配后旧包处置、Gate 角色——均【原文未给出，待补】。本设计只给候选，**不擅自定义**。
- **红线**：packages 行**不得**绕过运营配置路径被系统改写 payload（Q45 V1 口径＝运营手工配置实例，docs/08 M11；`final_id` 唯一出口哲学 E1.1 同源——AI 只产候选、人工 Gate 裁决）。任何候选不得让「重配」变成无 Gate 的自动改写。

## 2. 现状盘点

### 2.1 已落能力（计数侧）

| 能力 | 形态 | 依据 |
|---|---|---|
| 三包唯一实例 | `packages` 表，`(product_space_id, platform, goal, kind)` 每元组仅一条 active（重复 409） | Q45 / docs/04 L254 / layer_strategy.service.create_package |
| usage_count 列 | `packages.usage_count`（迁移 0008，server_default 0），当前仅读不写 | docs/10 L217「列先行不计数」 |
| 阈值配置键 | `package.reuse_threshold`（seeds.py L76，默认 20） | 02 §C2 L1376 / config_center |
| E1.1 唯一发证口 | `assemble_one`（final/whitelist_center service），FCW 行引用 `csp_package_id/cstp_package_id/cep_package_id` | docs/05 §1.3 / service.py L452–454 |
| **Q263 已落码**（本次） | `assemble_one` 发证成功后三包 `usage_count` 各 +1；跨阈值写 `package.reuse_threshold_reached` 审计；5 集成测试全绿，46 FCW 回归测试无破 | 本批提交 / test_fcw_package_usage.py |

### 2.2 现有物理结构（`packages`，迁移 0005/0008）

- 字段（models.py 实测）：`package_id` PK / `tenant_id` / `product_space_id` / `platform` / `goal` / `kind`（csp|cstp|cep）/ `payload` JSON（引用 layerSpaces 原子名）/ `conf` / `status`（active|archived）/ `usage_count` / `created_by/at` / `updated_at`；唯一约束 `uq_package_active_triple`。
- **现状缺口（Q45 剩余语义对应）**：
  - 「使用满 20 次 → 触发重配」→ Q263 已落**计数＋跨阈值审计信号** ✅；「触发后发生什么」→ **无**（重配载体缺失）；
  - 「PCP 权重表更新 → 触发重配」→ **无**（PCP 更新写口在哪、如何关联到包，未实现）；
  - 「重配走 Gate」→ **无**（候选表／批准形态／旧包处置均无）。

## 3. 候选设计（甲／乙／丙，均【工程建议·待裁决】）

> 按 Q45 两个触发源（满 20 次／PCP 更新）给「重配载体」候选。**推荐项排第一**。所有实现形态均标【工程建议·待裁决】，不构成规格。AI 选包（新 payload 自动生成）不在本片——PT 未定稿，任何候选的「新包内容」均指**运营手工配置**（复用 Q45 V1 人工通道）。

### 3.1 重配载体

| 候选 | 形态 | 改动面 | 依赖 | 冲突／风险 |
|---|---|---|---|---|
| **甲（推荐）** | **触发信号 → 运营待重配清单**：跨阈值审计（Q263 已落）＋ PCP 更新时也写同款审计；运营侧新只读口 `GET /admin/packages/reuse-pending`（按 `package.reuse_threshold_reached` 审计聚合：包三元组＋当前 usage_count＋阈值）；人工在既有 `PUT /packages/{id}` 更新 payload/conf 后**主动清零** `usage_count`（写 `package.reuse_reset` 审计）重启计数 | 只读口＋`usage_count` 清零语义（随更新接口加参数或独立 POST） | 无新表；复用既有审计与人工通道 | 语义清晰、零新表；「清零」时机是工程接缝【待裁决：人工更新即清零 vs 显式按钮】；无 Gate 化候选流转，若负责人要 Gate 化选乙 |
| **乙** | **Gate 化候选表**：新建 `package_reconfig_candidates`（参照 pcp_recalc_candidates 先例，Q259）：`candidate_id`／`package_id`／`trigger`（threshold|pcp_update）／`trigger_meta`（usage_count、threshold、pcp 更新前后快照）／`state`（pending|approved|rejected）／`proposed_payload`（**运营人工填**，AI 不可产）／`reviewer_id`／`decided_at`；批准 → 新包行 active、旧包 archived、usage_count 重置；审计齐 | 新表＋迁移＋POST 候选／PUT 决定口＋发证读包逻辑不变 | 复刻 Q41/Q259 PCP 重算候选模式，项目内已有同构先例 | 改动面最大；「候选 payload 由谁填、Gate 角色是否 = operations」【待裁决】；与 Q263 审计信号可并存（审计只作信号源） |
| **丙** | **只留信号不做载体**：Q263 审计即终态，不新增任何口；重配完全靠运营日常翻包 | 无 | 现状 | 与 Q45「触发重配走 Gate」措辞落差最大；仅当裁决「P2 不落载体」时兜底 |

### 3.2 PCP 更新触发源（与 3.1 任一候选配套）

| 候选 | 形态 | 改动面 | 依赖 | 冲突／风险 |
|---|---|---|---|---|
| **甲（推荐）** | **PCP 权重表更新写口挂钩**：段8 PCP 更新（`PUT /product-spaces/{id}/pcp` 或等价写口）成功提交后，对**该 PS×platform 下全部 active 三包**各写一条 `package.reuse_threshold_reached`（trigger=`pcp_update`，detail 带 pcp_id）——复用 Q263 审计通道，不动包数据 | PCP 写口一处钩子＋测试 | Q263 审计通道 | 「PCP 更新即触发全部包重配」是 Q45 原文语义【原文明确】；是否区分 pcp 模板切换 vs 微调【工程建议：微调 ±0.05 走人工通道的 Q42 语义下，仍触发重配信号，但可加 trigger 细分待裁决】 |
| **乙** | PCP 更新时只写普通审计（不挂 reuse 语义） | 无 | — | 与 Q45「PCP 权重表更新 → 触发重配」不对应，不推荐 |
| **丙** | 不实现 PCP 触发源 | 无 | — | 漏掉 Q45 一半触发源；仅当 P2 排期砍此项时兜底 |

## 4. 需要负责人裁决的点（汇总）

> **✅ 2026-10-03 已全部裁决（负责人「按照推荐来」，02 C1.208 Q264）**：

1. **重配载体取甲**（§3.1）：触发信号 → 运营待重配清单（`GET /api/admin/packages/reuse-pending` 只读口）＋ 人工 `PUT /api/packages/{id}` 更新 payload/conf 后清零 `usage_count`（写 `package.reuse_reset` 审计）重启计数。乙/丙归档备查。
2. **usage_count 清零时机＝人工更新即清零**：不设独立「重置计数」按钮；改包 payload 即视为重配完成（`package.reuse_reset` 留痕）。
3. **PCP 更新触发源取甲、不区分模板切换/微调**：`update_pcp` 成功后对该 PS×platform 全部 active 三包各写 `package.reuse_threshold_reached`（trigger=pcp_update、detail 带 pcp_id/kind/platform/goal/usage_count/threshold），复用 Q263 审计通道；微调/切换细分待主数据落地后校准。
4. **两触发源同批落**：满 20 次（Q263 已有）与 PCP 更新（本批）同批交付，不拆两轮。

**工程接缝（实现补，随 Q264）**：`list_reuse_pending` 以 `usage_count >= threshold` 为入清单判据（active 包实时值，非审计历史聚合）——人工清零后自然移出清单；阈值键缺失时 knob() 抛配置异常，不静默。

## 5. 来源索引

- Q45 原文：docs/02 L161；配置登记 docs/02 §C2 L1376。
- usage_count 列：docs/10 L217（V2 列先行）；迁移 backend/alembic/versions/0008_m11_stage78.py L139。
- 阈值键：backend/app/core/config_center/seeds.py L76。
- 发证引用三包：backend/app/final/final_whitelist/service.py（assemble_one，csp/cstp/cep_package_id）；docs/05 §1.3。
- PCP 更新先例：Q41/Q42（docs/02）；pcp_recalc_candidates 先例 Q259。
- 本片已落码（Q263）：service.py 递增＋审计块；tests/integration/test_fcw_package_usage.py。
