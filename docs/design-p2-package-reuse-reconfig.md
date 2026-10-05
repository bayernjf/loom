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

- 字段（models.py 实测）：`package_id` PK / `tenant_id` / `product_space_id` / `platform` / `goal` / `kind`（csp|cstp|cep）/ `payload` JSON（引用 layerSpaces 原子名）/ `conf` / `status`（active|archived）/ `usage_count` / `created_by/at` / `updated_at`；**「同三元组仅一个 active」由 service 层先查后插保证**（`decision/layer_strategy/service.py:113-124`→`PackageExists`→409）。
  > **Q278 勘误（2026-10-04）**：本行原写作「唯一约束 `uq_package_active_triple`」——**该标识符全仓不存在**，`alembic/versions/0008_m11_stage78.py:127-143` 建表时只给 kind/tenant_id/product_space_id/platform/goal 五个**普通**索引，**无任何唯一约束**；并发双建同三元组 active 包无 DB 守卫，是否补 partial unique index 属迁移决策，已登记待裁（docs/23 §8.3 勘误注、02 C1.221）。
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

## 6. 待裁项⑦ 的评审材料（Q284 交付；**只出材料，未建迁移、未动库、未改代码**）

负责人若裁「补」，本节就是可直接评审的两块：盘点语句与迁移草案。裁「不补」则本节留档即可。

**① 先盘点（只读，不改任何行）**

```sql
-- 同三元组存在多个 active 包＝草案里会被索引拒绝的那批行
SELECT tenant_id, product_space_id, platform, goal, kind,
       count(*) AS n,
       array_agg(package_id ORDER BY created_at) AS ids,
       array_agg(usage_count ORDER BY created_at) AS usages
FROM packages
WHERE status = 'active'
GROUP BY tenant_id, product_space_id, platform, goal, kind
HAVING count(*) > 1
ORDER BY n DESC;
```

判据与 service 层查重**逐字同键**（`app/decision/layer_strategy/service.py:113-119`：`product_space_id`·`platform`·`goal`·`kind`＋`status='active'`）。
`tenant_id` 只出现在投影里、**不进键**——PS 本身已定租户，把租户塞进键会造出一个比现语义更宽的约束，那不是「补守卫」而是换语义。

**② 迁移草案（若裁「补」＝新文件 `0048_packages_active_triple_unique.py`）**

```python
def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX uq_packages_active_triple ON packages "
        "(product_space_id, platform, goal, kind) WHERE status = 'active'"
    )

def downgrade() -> None:
    op.drop_index("uq_packages_active_triple", table_name="packages")
```

- **索引名刻意不叫 `uq_package_active_triple`**：那个名字是 Q272 起被误当作既有事实引用了 5 处的**幻影标识符**（Q278 已纠偏）。补上真约束时若复用旧名，等于让「文档早就写了」掩盖「代码从来没有」，后续读史的人会再次上当。
- PG 与 SQLite 都支持带 `WHERE` 的部分唯一索引，但**光在迁移里建会撞自己的门**：Q207 的 Migration gate 在真 PG16 上比 ORM⇄DB 漂移，所以索引必须同时声明进 `packages.__table_args__`，且要 `postgresql_where` ＋ `sqlite_where` **双写**——先例就是本仓已有的两条部分唯一索引：`uq_pcp_recalc_pending`（`app/platform/platform_adaptation/models.py:221-226`）与 Q124 释放同键的那条（`app/content/models.py:50-56`）。「迁移建了、模型没写」＝漂移门判红，这条不是可选项。
- 建成后并发形态会变：两个请求同时插同三元组 active 包，**后到的会拿到 DB 的约束冲突**而不是现在的 409——`router.py:90` 目前把 `PackageExists` 译成 409，走 DB 冲突路径则需一并接 `IntegrityError` 并仍回 **409**（否则外部自动化看到 500，属破坏性变更）。这条要在裁「补」的实现批里一起处理。

**③ 盘点若查出重复，归档口径三案（要负责人／业务定，工程不代选）**

| 案 | 做法 | 代价 |
|---|---|---|
| 甲（工程侧推荐） | 每组保留 `usage_count` 最大的一条 active，其余置 `archived`（**不删行**） | 需要一条一次性数据修补脚本＋审计留痕；「哪条代表历史发证」按计数判，可能与真实使用序有偏差 |
| 乙 | 全部置 `archived`，由业务重配 | 现网若已有依赖这些包的成品，取包路径会立刻 `MaterialMissing` |
| 丙 | 盘点为 0 行重复 ⇒ 直接建索引，无需归档 | **最可能情形**（三表现为零行）；但它是「当下没数据」而非「语义已保证」，索引价值在写入口变多之后才显现 |

**④ 我需要的东西**：一句「补／不补」。裁「补」后我按上面顺序交实现批（盘点脚本先跑真库→归档口径按你选的案→0048 迁移＋`IntegrityError`→409 接线＋门），全程不碰业务真值。

