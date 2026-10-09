# design：Q242 `whitelist_owner` 可签发性裁决材料

- 状态：**⬜ 待负责人拍板**（三案候选）；本材料只给现状、候选与推荐，不代裁
- 背景：Q242（02 C1.168 排除项①）把 PWS 冻结/吊销一族（`product/whitelist_center` 两个写口）并入待裁项③（客户侧真实认证，V2 第一项）；Q321（02 C1.264）已裁「客户侧认证后置 V2、beta 维持代运营＋无客户登录」。本材料回答 Q242 遗留的前置问题——**`whitelist_owner` 是否可签发为 staff 令牌、V1 期该族写口由谁操作**（02 C1.168「是前置问题，不是加不加闸的问题」；02 C1.139 追认「唯一仍敞开」）。
- 相关先例：Q297 汇总档 [design-v2-internal-roles-rbac.md](./design-v2-internal-roles-rbac.md) 已登记「`whitelist_owner` 推荐甲＝维持客户角色随③」与「PWS 冻结两口身份模型悬空」——本材料聚焦该两口的 **V1 处置**，供与③一并拍板。

## 1. 现状（代码事实，已核验）

| 项 | 事实 | 锚点 |
|---|---|---|
| 角色常量 | `ROLE_PWS_OWNER = "whitelist_owner"` | `product/whitelist_center/pws_rules.py:30` |
| 写口角色检查 | PWS 冻结写口 service 层自判 `whitelist_owner not in actor.roles → RoleNotAllowed` | `product/whitelist_center/service.py:69-70` |
| 冻结待办指派 | 待办 assignee_role = `whitelist_owner`（BO-07 红线，Q28） | `service.py:176`、docs/02 C1.33 |
| staff 令牌可签发角色 | `INTERNAL_STAFF_ROLES`＝{operations, platform_admin, product_reviewer, dictionary_admin, internal_compliance}，**不含 whitelist_owner** | `staff_auth/service.py:34`（Q178 限五角色，02 C1.122） |
| 全仓排除声明 | `rbac.INTERNAL_ROLES` 同样刻意排除该角色 | 02 C1.168 排除项① |
| 结论 | 若该族照搬 `require_internal_actor(WHITELIST_OWNER)` ⇒ 永久 403（无任何令牌可满足） | 02 C1.168 |
| 对照（已落） | FCW `final_id` revoke（`/api/admin/fcw/{final_id}/revoke`）＝**OPERATIONS** 闸，与 PWS 层两口不同层 | 02 C1.194（Q250 e 项） |

## 2. 三案候选

### 甲：扩六角色可签发（INTERNAL_STAFF_ROLES 加 `whitelist_owner`）
- 改动面：`staff_auth/service.py` 角色清单＋`rbac.INTERNAL_ROLES`＋normalize_roles；该族两口可加 `require_internal_actor(WHITELIST_OWNER)` 闸。
- 影响：**打破「whitelist_owner 是客户角色」的语义边界**（Q178 把它划在客户侧，Q321 又裁客户登录 V2 才有）——V1 以内部令牌形态签发一个名义上的客户角色，内外部身份混淆；签发面扩大。
- 收益：该族写口立即受闸、角色名保持原文（Q28/BO-07 红线不变）。

### 乙：该族两口改判内部角色（推荐 operations）
- 改动面：`pws_rules.py` 角色常量或 service 自判改 `OPERATIONS`＋router 两口加 `require_internal_actor(OPERATIONS)`；不动签发面、不动 rbac 清单。
- 影响：**偏离 Q242 原文「该族要求 whitelist_owner」的角色语义**——需负责人明示改判（与 Q250 FCW revoke 同口径，V1 内自洽：代运营期冻结/吊销由运营执行）；`whitelist_owner` 保留为 V2 客户侧真实角色（随③绑定客户身份）。
- 收益：V1 立即可受闸、与 Q250 一致、零新角色、不破坏内部角色清单语义。

### 丙：维持 V1 自报、随 V2 客户侧认证一并解决
- 改动面：零。
- 影响：该族两口延续 service 自判自报（Q203 后「写口须内部凭证」标准下的**已知例外**，Q297 已在守卫 UNGATED 显式登记）；与 Q242 归并意图一致，但 V1 敞口延续到 V2。
- 收益：零改动；代价是 V1 无闸。

## 3. 推荐

**乙（改判 operations）**：理由——
1. 与已落地的 FCW `final_id` revoke（Q250，OPERATIONS）同口径，V1 代运营期的冻结/吊销动作归运营执行，身份模型不悬空；
2. 不扩签发面、不引入新角色，规避甲案的内外部身份混淆；
3. `whitelist_owner` 语义保留给 V2 客户侧真实认证（Q321 已裁后置），届时如需客户自助冻结再改回该角色。

## 4. 裁决点

1. 案型：甲／乙／丙；
2. 若乙：角色取 `operations` 还是 `product_reviewer`（推荐 operations，与 Q250 一致）；
3. 是否同步把该族两口从守卫 `UNGATED` 移入 `GATED`（乙案必须，甲/丙案随案型定）。
