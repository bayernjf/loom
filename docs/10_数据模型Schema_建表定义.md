# 10. 数据模型 Schema（建表级定义）

> **状态**：🟢 已补内容（建表级说明，非 DDL 代码）
> **来源**：04_契约层_数据模型.md（35 实体与字段）｜01_PRD §3 各段规格｜02_决策记录（Q 编号）
> **用途**：把 04 的字段清单落成**建表级说明**（类型建议/约束/索引/关系/租户隔离），AI 据此生成数据库迁移脚本。
> **⚠ 说明**：原文（v3/基准 HTML）**未给出字段类型、索引等物理定义**——本表类型/索引列为【建议】（依据字段语义与 Q 约束推断，落地前需 DBA 复核）；约束列凡来自原文 Q/line 的如实标注，凡属惯例的标注【建议】。**不得把【建议】当原文规格使用。**
>
> **DBA 首轮全量复核：已完成（2026-09-20，结论见 §4 末）**——以一次性 PG16（pgvector/pgvector:pg16）容器 `alembic upgrade head`（head=0036_export_jobs）后的 information_schema / pg_indexes / pg_constraint 实测为权威，逐表核对 58 张业务表的列/类型/长度/nullable/默认值/索引/唯一约束/外键，并以 ORM `Base.metadata` 在 SQLite `create_all` 比对模型⇄迁移表列漂移，**零漂移**；复核中仅订正本文两处旧稿笔误（content_products.status String24→String32、tenants.detail JSON→JSONB）。**该轮复核之后 Q143 新增迁移 0037_restock_claims（业务物理表 58→59，五列/pkey）、Q151 新增迁移 0038_sweep_tick_claims（59→60，五列/pkey），两表均已经 pg16 容器 upgrade/downgrade-1/upgrade 往返实测（建表要素见 §2.8）。**DBA 第二轮全量列复核：已完成（2026-09-21，结论见 §4 末）**——一次性 PG16 容器 upgrade head=0038 后导出 information_schema / pg_indexes / pg_constraint 实测 60 张业务表、**637 列**（首轮 627＋两新表各 5 列）、**212 索引**（首轮 210＋两新表各 1 主键索引）、**FK 32＋UQ 20＝52**（与首轮持平——两新表各仅 1 主键、无 FK/UQ），ORM metadata 逐表逐列比对**零漂移、零单边表**，两新表五列/pkey 与 §2.8 登记完全一致。****该轮复核之后 Q161 新增迁移 0039_import_jobs（业务物理表 60→61，17 列、仅主键＋tenant_id/content_id 两业务索引，无 FK/UQ），已经 pg16 容器（55432 避 atlas-pg）upgrade head / downgrade-1 / upgrade 往返实测（建表要素见 §2.8）；该表在第二轮全量列复核之后落地，未计入 60 表/637 列/212 索引结论，**已纳入 2026-09-22 第三轮全量列复核（61 表/654 列/215 业务索引/PK61·FK32·UQ20，零漂移，见 §4）**。**该轮复核之后 Q178 新增迁移 0040_staff_api_keys（业务物理表 61→62，12 列、主键＋三业务索引含唯一约束 uq_staff_api_key_hash、无 FK），已经 pg16 容器（55442）往返实测；该表在第三轮复核之后落地，已纳入 2026-09-24 第四轮全量列复核（62 表/666 列/219 业务索引/PK62·FK32·UQ21，零漂移，见 §4）。**

---

## 1. 总则

### 1.1 建表约定
| 约定项 | 说明 | 来源/依据 |
|---|---|---|
| 命名 | 表名 snake_case 复数；字段 snake_case；主键 `id`（除 FCW 用 final_id 等业务主键外）；审计字段统一 `created_at / updated_at / created_by / updated_by` | 【建议】 |
| 租户隔离 | 所有业务表带 `tenant_id`（客户/租户）；知识层共享表（类目树/G2/通用底座）除外——**共享表不设 tenant_id 或置 NULL 表示平台级**（Q33：跨客户不查重、互不感知；Q24：共享只在知识层） | Q33/Q24 |
| 审计 | 所有人工操作 + AI 调用写 writeAudit（append-only，不可篡改）；配置中心每次修改写审计 | D3.11 / C2 |
| 软删除 | 不物理删除：状态字段（archived/deprecated/superseded）承载生命周期；"已废弃恢复视同新原子重走审核"（Q20） | Q20 / 各状态机 |
| 不可变对象 | PWS 快照、SkillRunLog、审计：**只追加不可 mutate**（PT-COMPLIANCE-V2.0；即便回滚） | 06 §2.5 |
| 幂等键 | 外部推送/重试场景必须有幂等键：effect-callback 用 `content_id + captured_at`（**Q126 已实现**，captured_at 归一 UTC，重推覆盖/新点追加） | Q60 / 05 §1.1.1 / 02 C1.70 |

### 1.2 枚举字典
| 枚举域 | 取值 | 来源 |
|---|---|---|
| 状态词 | pending/approved/frozen/superseded/revoked/archived/deprecated/blocked/…（各表局部状态见 13 状态机迁移表） | 05 |
| PWC 状态 | 待用/已用/爆款/冷却/待Gate/待入库/候选/阻断/归档 | line 1780-1806 |
| 三端 | user_frontend / admin_backend / system_api | line 2431 |
| 角色 | 普通客户/运营/产品审核员/平台审核员/内容审核员/系统管理员/Skill 管理员/法审 + 权威扩展（BO-07/字典管理员/平台级管理员/internal_compliance/internal_finance） | 09 D8 / 07 §2.3 |
| 内容目的 | contentGoals 5 类标准枚举（ENGAGEMENT/CONVERSION/EDUCATION/TRUST/RETENTION） | Q25 / line 1090 |

### 1.3 存储拓扑（14 选型定稿 2026-09-13：PG + pgvector + Redis + 对象存储）
| 存储 | 引擎 | 承载 |
|---|---|---|
| 关系库 | PostgreSQL 16 | 本文档全部业务表/共享知识表/配置中心/审计；事务与强一致（PWS 冻结、block_required、final_id 组装） |
| 向量 | pgvector 扩展（同 PG 实例起步） | 知识检索 embedding（M2-M4、Memory 层）；切换条件：向量规模 > 千万级或需高级混合检索时迁独立向量库（14 §2.3） |
| 缓存/队列 | Redis 7 | C7 Layer1 模板缓存、结果缓存（D7.2 策略 7）；Redis Streams 承载相撞/生成/批量审核异步任务 |
| 对象存储 | S3 兼容 | 主图/包装图等素材、内容成品（文章/视频/多语言）、Memory 对象层；跨区冗余 |
| 不入库 | — | 密钥/连接串只走环境变量；缓存中的派生值（如 fit_score 视图）不写死回业务表 |

---

## 2. 逐表 Schema（35 设计实体；截至 2026-09-24 物理表 62 张，迁移 0001–0041（**0041 为 Q187 纯配置种子、无 schema 变更，表数不变**）；0027 纯加外键不新增表，0028 新增 content_languages 1 表，0029 加两质量列、0030/0031 纯场景种子、0032 加列并把 content_products 唯一约束换为 partial unique index、0033 加三发布回填列，均不新增表；0034 新增 effect_records 1 表（段13 效果回流时序，Q126）；**0035 新增 effect_claims 1 表并给 effect_records 加两认领溯源列（Q127 孤儿人工认领，Q128 客户回填零迁移）；**0036 新增 export_jobs 1 表（Q132 中台导出任务记录）；**0037 新增 restock_claims 1 表（Q143 下游 PG 行级 fence 接 restock 花钱路径）；0038 新增 sweep_tick_claims 1 表（Q151 SLA sweep 写路径行级 fence，每把循环锁一行 lock_name/fence/claimed_by/claimed_at/updated_at）——0037/0038 均在首轮 DBA 全量复核之后，已经 pg16 往返实测，并已纳入 2026-09-21 第二轮全量列复核（60 表/637 列/212 索引/FK32＋UQ20，零漂移，见 §4 末）**；**0039 新增 import_jobs 1 表（Q161 客户效果回填异步导入任务，17 列、主键＋tenant_id/content_id 两索引，payload Text 落 CSV 原文/xlsx base64 可重放；在第二轮列复核之后落地，已经 pg16 往返实测，见 §2.8）**）

> 字段明细以 04 为唯一来源（本文不重复罗列全部字段，只补建表级要素）；【类型】为建议列。

### 2.1 产品与录入域（段 1–2）

**product_intake_applications（录入申请单）** — 字段见 04 §2.1
| 建表要素 | 说明 | 来源 |
|---|---|---|
| 主键 | `intake_id`（业务容器名 intakes） | 04 §2.1 |
| 状态 | `status`：productIntake15 15 态（见 13 §1.1） | Q5 |
| 资料 | `profile` JSONB：18 通用字段提交值，按 G2 fid 键控；提交后不可变（Q74）；完整度按 g2_fields active 且 cat='common' 行动态校验（D7.1 闸门1） | Q74 |
| 租户 | `tenant_id` 必填 | 1.1 |
| 索引 | (tenant_id, status)；冷启动支线 (tenant_id, category_pending_id) | 【建议】 |
| 关联 | → product_spaces（通过后生成 PS）；→ g2_fields（18 通用录入字段引用） | 01 段1 |
| 关键约束 | 类目确认动作由运营执行（Q3）；72h 未处理升级（Q4） | Q3/Q4 |

**product_spaces（PS，一品一空间）** — 字段见 04 §2.2（2026-09-13 M0 补齐）
| 建表要素 | 说明 | 来源 |
|---|---|---|
| 主键 | `product_space_id` | A6 |
| 外键 | `tenant_id` 必填；`intake_id` → product_intake_applications（**实现为真 FK**，迁移 0001）；`category_node_id` → g1_category_tree（设计名，物理表为 `g1_categories`）；`active_pws_id` → pws_snapshots（同刻仅 1 个 active，Q31）。**Q118（2026-09-18，迁移 0027）已补 DB 级真 FK**：`category_node_id`→`g1_categories.category_id`、`active_pws_id`→`pws_snapshots.pws_id`（均 nullable，约束名 `fk_product_spaces_category_node_id`/`fk_product_spaces_active_pws_id`；两列 V1 代码零写入，迁移先幂等置空孤儿再建约束；PG16 up/downgrade-1/up 实测） | Q33/Q5/Q31 |
| 属性 | `industry_tag`（类目路径映射，运营可改 Q7）/ `sensitive_industry` 布尔 / `business_owner`（产品记录字段，非登录角色，09 D8） | Q7/Q11/09 D8 |
| 目标语言（Q119） | `target_languages` JSONB nullable（BCP-47 数组；NULL/空=未声明，段12 语言交集不做产品侧收窄）；管理端 operations 写入口 `PUT target-languages` 已落，段1 录入表单控件挂账 | Q58/Q119 |
| 生命周期 | `lifecycle`（**列名以迁移 0001/模型为准**，原文与本文旧稿写作 `lifecycle_priority`）：frozen > stale > cold > modeling > active，default=`modeling`（迁移触发条件原文未给，待补） | line 1655 |
| 关联 | 私有资产：field_pools / product_atom_instances / condition_packages / pws_snapshots（禁止跨产品/跨租户复用，Q24） | line 14813/Q24 |
| 索引 | (tenant_id, lifecycle)；active_pws_id 唯一过滤索引【建议】 | 【建议】 |
| 资料快照 | `profile_snapshot` JSONB：18 通用字段值不可变快照，建模中生成时从 intake.profile 整体复制（Q74） | Q74 |

**c1_records（C1 识别记录）** — 字段见 04 §2.3
| 建表要素 | 说明 | 来源 |
|---|---|---|
| signals | 信号配置表 5 行（name/brief/卖点/主图/包装图），**第一期仅启用文本三行（0.50/0.33/0.17），图像后置**；启用行权重 Σ=1 强校验（不合格拒绝保存，不归一化，Q2 已转正） | Q2 |
| 判定 | `conf` 单指标（废弃 hit_rate）；三分支 direct_approve/ops_assist/cold_start | Q1/Q3 |
| 阈值 | 行业阈值表 c1_thresholds 独立 CRUD 表（medical 0.90/electronics 0.80/general 0.85），不可删默认档 + 审计 | Q7 |
| 矛盾 | Top1-Top2 差 <0.1 → 信号矛盾 → ops_assist | Q3 |

**g1_category_tree（G1 类目树）** — 字段见 04 §2.4
| 建表要素 | 说明 | 来源 |
|---|---|---|
| 状态 | active/draft/review/deprecated/archived/merged（merged 带 merged_into 永久重定向） | 01 段2 |
| 模板 | 每叶子挂 template，`field_list` 引用 G2 fid；**禁 fid:'-'**（黑户禁止落库，须回填） | Q68 |
| 共享 | 跨产品/跨租户共享（平台级，无 tenant_id）；历史 PS 引用要 merged_into 防悬空 | A6 / Q69 |
| 索引 | 类目路径（父节点链）复合索引（C7 识别从类目路径映射输出，Q7） | Q7 |

**g2_fields（G2 通用字段池）** — 字段见 04 §2.5
| 建表要素 | 说明 | 来源 |
|---|---|---|
| fid | 字段身份证号，**唯一且不可为空**（`fid:'-'` 禁止落库） | Q68 |
| syn[] / usage / status | 同义词数组、使用计数、状态（含 deprecated 悬空处理） | 04 §2.5 |
| cat | 'common' 18 个通用录入字段（cat:'common'） | line 682-698 |
| 共享 | 平台级共享表（无 tenant_id） | 1.1 |

> **实现补登（2026-09-13，M1/M2 后端切片）**：本段物理表已随 Alembic 0001/0002 落地并在 PG16 实测 up/down/up——`product_intake_applications`/`product_spaces`/`g2_fields`/`audit_logs`（0001）；`c1_signal_weights`/`c1_industry_thresholds`/`c1_records`/`ops_todos`/`g1_categories`/`g1_category_templates`/`c7_runs`/`g2_field_candidates`（0002，含文本三权重与 medical/electronics/general 三阈值种子）。设计名 g1_category_tree 实现为 g1_categories + g1_category_templates 两表；c1_thresholds 实现为 c1_industry_thresholds；ops_todos 为 M2 临时表，M10 通用 SLA 引擎（Q49）落地后归并。字段类型/索引以迁移脚本为准，本文 DBA 复核结论不因此变更。

### 2.2 字段池与原子域（段 3–4）

**g2_field_candidates（字段候选）** — 04 §2.6（2026-09-13 M0 补齐）
- 主键 `candidate_id`；字段：`field_name`/定义、`source_layer`（C7 Layer4/WF-02 等）、`source_route`（Q8 路由 6 路）、`confidence`、`dup`（联动 g2_fields.syn）、`related_fid`（≥0.9 疑似重复指向，Q10）、`status`（pending_gate/approved/rejected【枚举建议】）
- 约束：候选→转正不直接写 g2_fields，走人工 Gate + 字典管理员权限（Q13）；<0.85 必审（Q9）；须带来源标注（line 14133/14081）
- 待补：全局/租户可见性原文未给；完整状态枚举待补

**field_pools（字段池）** — 04 §2.7
| 要素 | 说明 | 来源 |
|---|---|---|
| gate | approved / pending_gate | 04 |
| 目标原子数 | 默认 15-30（达标停拓，可改） | Q15 |
| 维度数 | 3-8；>8 留 Top8 余者入备选档；<3 转人工 | Q12 |
| 角色维度 | ≥1 个 product_attribute；敏感行业 ≥1 个 risk_control | PT-FP-PLAN / Q11 |
| 维度来源 | 6 路默认（用户输入/通用灵感库/产品专属灵感库/类目模板/G2 高频字段/合规风险面），运营可配 | Q8 |

**product_atom_instances（原子实例）** — 04 §2.8
| 要素 | 说明 | 来源 |
|---|---|---|
| 状态 | atom8（草稿→待审核→已通过→已冻结→已废弃→已驳回→合规暂停→归档） | line 1454 |
| evidence | 必填；空 → pending_evidence（7 天超时自动驳回可复活） | Q18 |
| risk | critical/high/…；词表强制 + AI 兜底，只升不降 | Q17 |
| 事实原子 | 产品事实原子（容量/成分/浓度/疣类型/品牌）引用数恒=1，严禁跨产品复用 | line 11189 |
| Guard | approveAtomGuard 10 项（属 PS/属 FieldPool/gate/status/无冲突/approved_id 空/evidence/high 单条/审计） | line 2633 |
| 索引 | (product_space_id, field_pool_id, status)【建议】 | — |

**atom_conflicts（原子冲突）** — 04 §2.9
- 类型：disabled_expression（critical→驳回+审计）/ high_risk_single_review（high→单条 Gate）/ evidence_required（high→补证据或驳回）
- 状态：blocked / pending_gate

> **实现补登（2026-09-13，M3 后端切片）**：field_pools 域随 Alembic 0003 落地（PG16 up/down/up 实测），共 3 表：`fp_source_routes`（Q8 路由，6 路种子）、`field_pools`（一品一池唯一约束，gate 三态含实现补规格 rejected、compliant/violations、target_atom 15-30）、`fp_dimensions`（selected/backup 两档，source_ref 非空，fid/candidate_id 二选一挂接，needs_detail/dup 标记）。product_atom_instances/atom_conflicts 尚未实现，随 M4。

> **实现补登（2026-09-13，M4 后端切片）**：原子域随 Alembic 0004 落地（PG16 up/down/up 实测），共 5 表：`compliance_wordlist`（Q48，见 §2.5）、`atom_batches`（拓展批次：batch_size/source/sensitive_snapshot）、`atom_candidates`（候选主体，唯一约束 `(batch_id, normalized)` 同批去重，草稿/待审核活在候选侧）、`atom_conflicts`（三类冲突 + resolved_at）、`product_atom_instances`（Gate 后正式实例，唯一约束 `(fact_type, normalized)` 落实 line 11189 事实原子全局唯一；NULL fact_type 不参与唯一性）。字段类型/索引以迁移脚本为准。Q86 起（迁移 0018）`atom_candidates`/`product_atom_instances` 各加 nullable `embedding` 列（PG vector(1536)/SQLite float32 LargeBinary），AI 批候选向量随投递落候选行、approve 复制到正式实例，历史 NULL 行不补。

### 2.3 白名单域（段 5–6）

**condition_packages（PWC）** — 04 §2.10（字段完整）
| 要素 | 说明 | 来源 |
|---|---|---|
| combo | 组合明细子表：`pwc_combo_items(pwc_id, atom_id)`（跨字段原子组合；**唯一约束 `(pwc_id, atom_id)`**，另带 dimension_id/fid；原文写作 `(pwc_id, fp_id, atom_id)`，实现无 `fp_id`——以迁移 0005 与本文件 §2.3 实现补登为准） | line 1780 |
| 状态 | 待用/已用/爆款/冷却/待Gate/待入库/候选/阻断/归档 | line 1780-1806 |
| 复用边界 | **严禁跨产品/跨客户复用**（product_space_id + tenant_id 双重隔离） | Q24 |
| 库容 | 待用池默认 100（可配无上限） | Q27 |
| 索引 | (product_space_id, gate_status, score desc)——消费端按评分取 | Q71 |
| goals | contentGoals 枚举引用 | Q25 |

> **实现补登（2026-09-14，M5 后端切片）**：段5 随 Alembic 0005 落地（PG16 up/down/up 实测），共 6 表：`content_goals`（Q25，5 码种子）、`pwc_pool_configs`（一品一配置，capacity 可空=无上限）、`condition_packages`（双状态 gate_status/status、score+score_detail/score_incomplete、dup_of 自 FK/is_backup、high_reuse/is_hot）、`pwc_combo_items`（唯一 `(pwc_id, atom_id)`）、`pwc_usage_records`（取用流水，唯一 `(pwc_id, platform, account, slot)`，带 tenant 隔离）、`pwc_platform_states`（每组合每平台 available/cooldown + cooldown_until；"冷却"态落此表而非组合全局状态）。字段类型/索引以迁移脚本为准；"待入库"原文【待补】未实现。

**pws_snapshots（PWS 快照）** — 04 §2.11
| 要素 | 说明 | 来源 |
|---|---|---|
| 版本 | `version` v1.0 起大版本递增；同刻仅 1 个 active | Q31 |
| 状态 | frozen（可消费）/ superseded（只读）/ revoked（急停） | Q30/Q32 |
| 就绪门 | pwsReadiness 5 项（approved FieldPool / ≥3 原子 / ≥1 active PWC / 0 blocked conflict / pending_gate=0） | line 2634 |
| 不可变 | 快照内容只追加不可 mutate；历史版本全保留 | Q31 / 1.1 |
| 关联 | 快照内容明细子表：pws_items（原子/PWC 引用快照） | 【建议】 |
| 红线 | 冻结操作 owner=BO-07 + 人工 Gate + 审计 | line 7674 |

**pws_freeze_logs（冻结/重冻/作废日志）**
- 事件：freeze / refreeze（强制-建议-免三档，Q29）/ revoke / supersede；每次记录触发原因 + 操作人 + Q 依据【建议】
- 换版四行处置落库：旧版 superseded / 草稿作废 / 未发布待复查 / 已发布不追溯（Q30）

> **实现补登（2026-09-14，M6 后端切片）**：段6 随 Alembic 0006 落地（PG16 up/down/up 实测），共 3 表：`pws_snapshots`（version 唯一 `(product_space_id, version)`、status+is_active 双维、fingerprint sha256、snapshot/readiness JSON 在 PG 为 JSONB、revoked_* 急停字段）、`pws_snapshot_items`（建议名 pws_items 的物理实现，kind=atom/pwc + seq 有序 + payload 物化，唯一 `(pws_id, kind, ref_id)`）、`pws_freeze_logs`（事件含 supersede 双写）。Q30 草稿/未发布/已发布内容实体随 M8/段12，M6 dispositions 结构先行占位。字段类型/索引以迁移脚本为准。

### 2.4 平台适配域（段 7–8）

**publish_slots（发布位）** — 04 §2.12
| 要素 | 说明 | 来源 |
|---|---|---|
| 规模 | 14 平台 100+ 发布位；slotType 13 类 | line 1098-1221 |
| 格式 | chars/dur 约束（如 X-01 280 字符、TT-01 15-180s） | line 1098-1221 |
| 四维分 | traffic/safe/conv/load（0-100）；AI 候选四维全 0 + pending_gate | line 1098-1221 |
| fit_score | 四维加权聚合（权重按内容目的配置，Q34）——**派生列/视图**，不存死值【建议】 | Q34 |
| 档案维护 | 后台 CRUD；客观字段附来源链接；四维分明示"人工评估" | Q35 |

**platform_rules（平台规则）** — 04 §2.13
| 要素 | 说明 | 来源 |
|---|---|---|
| selector | 4 层优先级（低→高）：slotType > platform > platform+slotType > slotId；country 横切 modifier | line 1383 |
| effect | 仅 blocked / partial（native 默认不存） | line 1383 |
| 规模 | <300 条覆盖 ~10 万理论格子（结构性约束，非配置） | line 1382 |
| 冲突 | 保存时静态查重：同层级同条件不同结论 → 提示（Q36） | Q36 |
| 跨层 | R-X01~X05 内部矛盾检测 | line 1383 |

**slot_rule_by_type（slotType 默认值）** — 04 §2.14
- 13 类，约 40 列（含单账号日发布限量：主 2-3/互动 3-5/短视频 1-3）；优先级最低可被逐位覆盖

**strategy_fields_17（PCP 权重池）** — 04 §2.15（17 字段名完整）
| 要素 | 说明 | 来源 |
|---|---|---|
| 权重 | 17 个 *_pool 权重字段；**Σ≤1.0 统一校验器**（保存/重算入库前强制，拒绝不合格） | Q40 |
| 模板 | 4 套平台类型模板（短视频/社区讨论/图文种草/电商）派生初值 | Q39 |
| 隔离 | 平台间不共享权重池（platform_id 归属） | PT-PCP-V1.5 |
| 重算 | 动态信号每周触发；AI 候选+对照单进 HumanGate；单项 ±0.05 | Q41/Q42 |

> **实现补登（2026-09-14，M11 后端切片，迁移 0008，PG16 up/down/up 实测，共 6 表）**：
> - `publish_slots`：slot_id(String36) PK / platform / code UNIQUE / name / slot_type / chars_max / dur_min/max / traffic/safe/conv/load Float server_default 0 / score_source(16) server_default manual_eval / risk(16) 可空 / gate(16) server_default approved / source_url(512) / status(16) active|archived / 审计列；**无种子**（14 平台目录原文 line 1098-1221 基准 HTML 不在仓库，【原文未给出，待补】，不虚构）。
> - `goal_fit_weights`：goal String32 PK（逻辑引用 content_goals.code，无 DB FK）/ weights JSONB / updated_by/at；种子 2 行 ENGAGEMENT、CONVERSION（04 §2.15 实现补登，其余 3 目的【待补】）。
> - `platform_rules`：rule_id PK / selector_level(24) / platform/slot_type/slot_id/country 均可空（空=通配）/ effect(16)=blocked|partial / note / status(16) / 审计列；同层级同条件不同结论的查重由服务层保存时执行（409 + overwrite 归档旧行），非 DB 约束；跨层 R-X01~X05 未建表【后续任务包】。
> - `slot_type_defaults`：slot_type PK / daily_limit_min/max / defaults JSONB / 审计列；约 40 列明细【原文未给出，待补】，无种子。
> - `pcp_templates`：template_id PK / code UNIQUE / name / weights JSONB / status；种子 4 行（pcpt-short_video/community/photo_text/ecommerce，17 键 Σ=1.0，Q39 实现期初值草稿）。
> - `pcp_weight_tables`：pcp_id PK / tenant_id/product_space_id/platform 索引 / template_code(32) 可空（人工直编后清空）/ weights JSONB / status / 审计列；UNIQUE(product_space_id, platform) 名为 uq_pcp_ps_platform，落实 PT-PCP-V1.5 平台不共享（M11 仅提供 create/update，无归档端点，一对 PS×平台生命周期内仅一行）。
> - 种子单一事实源在 `app/platform/platform_adaptation/seeds.py`，迁移与测试共用。字段类型/索引以迁移脚本为准。

### 2.5 策略与合规域（段 9–10）

**layer_spaces（通用底座 4 层）** — 04 §2.16
- strategy 6 维 / structure 6 维 / expression 6 维 / compliance 4 维；维度名见 04
- 共享表（无 tenant_id）；改动收权平台级管理员 + 影响面提示 + 审计（Q46）
- 结构同构：字段 → 原子（每层候选/正式/冻结池）【建议建模为通用 layer_space_items】

**packages（CSP/CSTP/CEP）** — 04 §2.17
- 字段：CSP(goal/stage/angle/intensity/cta/emotion)、CSTP(struct 段式)、CEP(tone/perspective/explicit/soften)；各带 conf 与 gate
- 复用：按（产品×平台×目的）三元组配一份；满 20 次或 PCP 更新触发重配（Q45）
- 索引：(product_id, platform_id, goal) 唯一【建议】

> **实现补登（2026-09-14，M11 后端切片，迁移 0008，PG16 up/down/up 实测）**：物理表 `packages` 落于段9 包 `app/decision/layer_strategy/`：package_id String36 PK / kind(8)=csp|cstp|cep 索引 / tenant_id/product_space_id/platform/goal 索引 / payload JSONB（键按 04 §2.17 定死，服务层校验缺/多键 422）/ conf Float 可空 / gate(16) server_default approved / status(16) active|archived / usage_count Int server_default 0 / 审计列。三元组+包型的"仅一条 active"由服务层保证（非 DB 唯一约束，软归档后可重建）。WF-07 AI 选包、20 次重配、usage_count 递增均 V2（列先行不计数）。

**countries（国家事实库）** — 04 §2.18
- 承载 R-030（EU/GDPR 禁留邮箱手机）/ R-031（CN/NMPA）/ R-032（US/FDA OTC 禁 cure/treat）
- 优先序：国家 > 平台 > 底座默认（**不可配置**，Q50）

**compliance_wordlist（合规词库，Q48 合并后单表）** — 04 §2.19（字段完整）
- 字段：词/等级(critical|high)/处置(禁用|降级)/降级映射目标/适用国家/适用行业/生效期
- 三关卡同源：段 4 定原子风险 / 段 5 相撞合规 / 段 10 清洗——**同一张表**
- 生效即自动全量扫描（active 快照/draft FCW/未发布成品），联动 Q29/Q30（Q51）

> **实现补登（2026-09-13，M4 后端切片；2026-09-14 M7 补齐段10 消费）**：已随 Alembic 0004 落地物理表 `compliance_wordlist`（PG16 up/down/up 实测），active/archived 软删，行业+生效期过滤，段4 已消费（原子风险定级），段5 已在 M5 消费（漏斗合规检测，ban→blocked）；M7 迁移 0007 增 `layer`（country/platform/base，server_default=base）承载 Q50 三层优先序，段10 按行业+市场取词裁决（同级 Q36 从严）；Q51 生效即扫已随 M7 落（保存生效事务内扫 active frozen 快照→`wordlist_rescan` 待办；draft FCW/未发布成品扫描随 M8/段12；未来生效词条定时扫描随 M10）。
>
> **实现补登（2026-09-14，M10 切片 b，迁移 0011_m10_sla_engine，PG16 up/downgrade-1/up 实测）**：`compliance_wordlist` 增 `activated_at`（timestamptz 可空）承载 Q51 未来生效词条到点补扫——创建/编辑时已在生效窗口内立即置位（且 Q48 `effective_from`/`effective_until` 经 API 契约开放录入，窗口倒置 422），未来生效为 NULL；升级 SQL 将存量 active 行回填 now()。SLA 调度作业到点选取 `status=active AND activated_at IS NULL AND effective_from<=now`，置位并复用 `rescan_for_entry` 补扫。**SLA 引擎无新表**：通用升级直接作用于 `ops_todos`（open 且 due_at 到期→escalated，审计动作按类型：ops_assist=`c1.todo_escalated`、pws_ready=`pws.ready_todo_escalated`、law_review=`law_review.escalated`、wordlist_rescan=`wordlist.rescan_todo_escalated`、余者 `sla.todo_escalated`）；看板态 green/yellow/red/resolved 为派生值（yellow 仅法审：created_at+sla.yellow_hours，配置中心种子 24h；其余类型黄色口径原文未给，到期前恒 green），不落库。

**cp_law_sensitive_domains（CP-LAW 敏感领域清单）** — 04 §2.20
- 领域：医疗健康/儿童/减肥/美白/医疗器械/金融（领域非词）；触发自动法审（Q49）

> **实现补登（2026-09-14，M7 后端切片，迁移 0007，PG16 up/down/up 实测）**：
> - `cp_law_sensitive_domains`：domain_id PK / code 唯一 / name / status(active|archived) / 审计列；迁移种子 6 码（medical/children/weight_loss/whitening/medical_device/finance）；internal_compliance CRUD + writeAudit。
> - `law_reviews`：law_review_id PK / tenant_id / product_space_id / pws_id（UNIQUE，一冻结版一条）/ domain / status(pending|approved|rejected) / conclusion Text / decided_by/at / created_at；法审待办复用横切 `ops_todos`（todo_type=law_review，assignee_role=internal_compliance，48h due）。
> - `ccr_reports`：ccr_id PK（uuid1，时间有序便于同秒取最新）/ tenant_id / product_space_id / pws_id（索引）/ country（可空，索引）/ status(clean|downgrade_pending|approved|blocked) / block_required Bool / hits JSONB / wordlist_context JSONB / run_by / decided_by/at / created_at；append-only，段11 按 (pws_id, country) 最新行消费 Guard②⑥。

### 2.6 组装与成品域（段 11–12）

**final_content_whitelists（FCW）** — 04 §2.21（字段完整）
| 要素 | 说明 | 来源 |
|---|---|---|
| 主键 | `final_id`（final_content_whitelist_id，业务主键） | line 870 |
| 6 层输入 | pws_id / pcp / csp / cstp / cep / ccr（快照引用） | line 870 |
| 归属 | product_space_id + tenant_id（Guard④⑤ 校验配置实例归属） | Q52 |
| 状态 | publish_status：draft / published | line 870 |
| 唯一出口 | E1_owner=publishFCW；**任何其他模块写 final_id = 越权** | line 11036 |
| Guard | 7 项（PWS frozen / block_required=false / 包 active / 6 路 PS 一致 / tenant 一致 / law_review 通过 / PWS active 版本） | Q52/Q53 |
| score | FCW-SCORE（0.4/0.3/0.3）——仅排序不做门槛 | Q54 |

**content_products（内容成品）** — 04 §3（**Q116 实现补登**，迁移 0025）
- 载体：文章/视频（video-studio 四模块）/多语言版本；各语言版独立成品（Q58）。**P4 首片只落文章单语言**（kind=article、language=zh-CN），video/多语言缓做。
- 状态：draft → generating → review → ready_for_publish / rejected / revising（Q56/Q59，Q116 实现补登；原文只给五态语义）
- 字段全定义：Q116 实现补登（见下方补登）——原文未给字段，**已由 04 §3 补登 + 迁移 0025 落库**

> **实现补登（2026-09-14，M8 后端切片，迁移 0009_m8_stage11，PG16 up/downgrade-1/up 实测）**：
> - `final_content_whitelists`：final_id PK（uuid1，时间有序）/ task_id 可空（关联批量任务）/ tenant_id / product_space_id / pws_id / pwc_id / pcp_id / csp_package_id / cstp_package_id / cep_package_id / ccr_report_id / law_review_id（后两者可空，Guards 实际要求 ccr 存在）/ platform / slot_id / goal（均索引）/ country String(8) 可空索引 / score Float 可空 / score_detail JSONB（公式/权重/原始分/缩放）/ score_incomplete Bool（server_default false）/ guards JSONB（7 项逐项结果）/ guards_passed Bool / publish_status String(16) server_default 'published' / issued_by / published_at / created_at / updated_at；`UNIQUE(pws_id, pwc_id, platform, slot_id)`（含 country 维度的重复判定在服务层补 country 条件，uq 约束按 04 §2.21 实现补登口径）。
> - `fcw_assembly_tasks`（Q55 任务驱动）：task_id PK / tenant_id / product_space_id / pws_id 索引 / platform / goal / country / requested_count / slot_ids JSONB / status(running|completed) / results JSONB（requested/resolved_slots/issued/failures 逐项原因）/ created_by / created_at / completed_at；V1 为同步执行（建单即跑完），异步 worker 随 M10。
> - 分数口径（Q54，仅排序）：PWC 骨架分与三包 conf 为 0–1 先 ×100 归一，slot fit 本为 0–100；`pwc×100×0.4 + fit×0.3 + mean(三包 conf)×100×0.3`；任一来源缺失 → score=null + incomplete=true，不凑分、不卡发证。
> - 挂账：WF-09 AI Skills（V2）、draft 生命周期端点（V1 直接 published，draft 列保留无创建入口）、消费侧 API（Q71 取用走 M5 PWC 消费，FCW 消费契约【待补】）；~~段12 content_products~~ **✅ Q116 已落地（迁移 0025，见下条补登）**。

> **实现补登（2026-09-17，V2 P4 段12 首片，迁移 0025_content_products + 0026_article_gen_seed；物理表落 `app/content/models.py`，见 02 C1.60 / 05 §1.4 Q116 补登 / 13 §1.13）**：
> - `content_products`：content_id String36 PK（uuid1）/ tenant_id 索引 / product_space_id 索引 / final_id 索引（**只读软关联**，按 final_id 取 FCW 组装材料，不建 DB FK）/ goal / platform / slot_id 可空 / country 可空 / kind String16（article|video；P4 只产 article）/ language String16 server_default zh-CN / body Text 可空 / review_hits JSONB（词库复检命中）/ quality_score Float 可空（Q120 ARTICLE-QC 0..1，advisory）/ quality_issues JSONB 可空（问题明细；QC 故障记 qc_error）/ status String32 索引（迁移 0025 建表即为 String(32)，本文旧稿误记 String24，2026-09-20 DBA 复核订正；Q124 起七态：draft/generating/review/ready_for_publish/rejected/revising/discarded）/ reject_reason Text 可空（Q59 驳回原因回流段13）/ regenerate_count Int server_default 0（Q56 上限默认 3、可由 `content.regen_limit` 配置并经 Q120 接入 revise 闸，`MAX_REGENERATE=3` 为兜底常量）/ **discard_reason Text 可空（Q124 运营作废的难产原因，仅 discarded 态非空）/ published_url Text 可空、platform_post_id String(128) 可空、published_at timestamptz 可空（Q125 运营发布回填三列，published_at 非空即已发布信号，不新增 published 态）** / created_by / created_at / updated_at。status 七态（Q124 起）：draft/generating/review/ready_for_publish/rejected/revising/**discarded（终态只读）**；唯一索引 `uq_content_final_language_kind(final_id,language,kind)` 自 Q124 起为 **partial unique index `WHERE status <> 'discarded'`**（作废后同键可重新生成=回池，旧行保留；模型层 postgresql_where + sqlite_where 双方言）。
> - 生成走**模型网关第 7 场景 ARTICLE-GEN**（0026 纯种子：场景路由 + Prompt v0.1），**不产 skill7 候选、不走运营 Gate**（段12 的 Gate=客户审阅 Q59）；成本经 SkillRun 手动落（Q67）+ writeAudit 留痕。
> - 复检 V1 仅词库扫描（复用 Q48 词库 + `ccr_rules` 三层裁决）；语义级/施工指令/国家规则 3 项【原文未给出，待补】。
> - 挂账：客户前端内容页、视频生成、AI 质量分、复检余 3 项（P4 后续切片）；~~多语言~~ **✅ Q119 已落地（见下条补登）**。
>
> **实现补登（2026-09-18，V2 P4 段12 多语言 Q58，迁移 0028_content_languages；见 02 C1.63 / 05 §1.4 Q119 补登）**：
> - 新表 `content_languages`（语言清单，配置化）：`code` String16 PK（BCP-47，如 zh-CN）/ `name` String64 / `markets` JSONB（适用国家码，对齐 FCW.country；**空数组=全市场，含 country=NULL**）/ `status` String16（active|archived，server_default active）/ created_at / updated_by / updated_at。迁移种子**仅 zh-CN**（简体中文、markets=[]、active，保证单语言向后兼容；其余语言 dictionary_admin 配置，不预置）；dictionary_admin CRUD（content-languages 端点），显式 upsert 复活口径同 content_goals。
> - `product_spaces` 加 `target_languages` JSONB nullable（产品侧目标语言；NULL/空=未声明不收窄；operations `PUT .../target-languages` 写入，段1 录入表单控件挂账）。
> - `content_products` 加唯一约束 `uq_content_final_language_kind (final_id, language, kind)`：一条 final_id 每语言每载体仅一个独立成品（独立复检 / 独立客户审）；generate 语言不在交集→422（回带 eligible）、同 final+lang+kind 已存在→409。
> - 语言交集纯函数 `app/content/languages.py`：active 语言中 markets 覆盖 `fcw.country` 者，再被 `PS.target_languages`（非空时）收窄；空 markets 全覆盖、受限语言不覆盖 country=NULL。PG16（pgvector/pgvector:pg16）一次性容器实测 up / downgrade-1（表列约束全清、head 回 0027）/ 再 up（恢复 zh-CN 种子与约束）往返对称。

> **实现补登（2026-09-18，V2 P4 段12 AI 质量分 Q57 + 重生成上限 Q56，迁移 0029_content_quality + 0030_article_qc_seed；见 02 C1.64 / 05 §1.4 Q120 补登）**：
> - `content_products` 加两 nullable 列：`quality_score` Float（ARTICLE-QC 0..1 分）、`quality_issues` JSONB（问题明细；QC 故障/坏输出记 `[{"qc_error": ...}]`）。纯 advisory：不自动发证/驳回、不阻断 approve、不新增状态（六态机不动，Gate 仍为客户审阅 Q59）；视图另回带 `quality_threshold`（取 `content.ai_quality_threshold` 默认 0.85）与 `quality_advisory`（低于阈值 true、无分 null）。
> - 迁移 0030 纯种子：新增模型网关第 8 场景 `ARTICLE-QC`→synthetic 路由 + SkillPrompt/PromptVersion v0.1（只读打分、输出 {score,issues}，variables [body,language]），不建表；0029 仅加两列。
> - `statemachine.revise_allowed` 增 `limit` 形参，service 读 `content.regen_limit`（默认 3）作为改稿重生成上限，超限 revise 返回 422（detail 回带 {count}/{limit}）只能 reject；Q56 的 a/b 转人工路径保留为人工动作。QC 由新建 `app/content/quality.py` 在正文生成、词库复检之后内嵌调用，零新 HTTP 端点。PG16（pgvector/pgvector:pg16）一次性容器实测：全新库 up（两列 + QC 种子就位）/ downgrade 0030→0029（种子全清、列保留）/ 0029→0028（两列全删）/ 再 up 恢复，往返对称；物理表总数仍 55。

### 2.7 反馈与知识域（段 13）

**cat_feedback（类目效果回流）** — 04 §2.22（字段完整）
| 要素 | 说明 | 来源 |
|---|---|---|
| 指标 | content_count / avg_ctr / avg_read / avg_conv / hot | line 746 |
| field_impact | 子表：field_impact_items(fid, fill 填充率, lift 增益, impact) | line 746 |
| 纪律 | 缺席字段="—"，绝不当 0 / 不许估算 | Q60 |
| 幂等 | (content_id, captured_at) 幂等覆盖；同 content_id 追加时间序列 | Q60 |
| 孤儿 | 对不上 content_id → 孤儿数据队列人工认领 | Q60a |

**kup_proposals（KUP 提案）** — 04 §2.23（字段完整）
| 要素 | 说明 | 来源 |
|---|---|---|
| 字段 | type(add/promote/demote) / target / reason / evidence / conf / status | line 1006 |
| 证据三关 | 样本≥30 条 + 增益差≥0.5% + 连续 2 周期方向一致（配置页） | Q63 |
| 审批 | 单产品=运营；共享知识层=平台管理员（"PM"废除） | Q64 |
| 回滚 | 每次回写留回滚点；预期未兑现可一键回滚 | Q63 |

**knowledge_update_logs（知识回写日志）**
- 回写目标：G2 字段 / 原子 weight / 类目模板（唯一反向边）【建议】

### 2.8 治理与平台域（横切）

**skill_run_logs（Skill 运行日志）** — 04 §3 待补（切片 e 已补字段实现，Q76）
- 输入/输出/成本/置信度/失败/人工修改记录；**不可 mutate**（append-only）
- **实现补登（2026-09-14，M10 切片 e，迁移 0012_m10_skill7）**：物理表名 `skill_runs`，落于 `app/core/skill7/models.py`。run_id String36 PK（uuid1 时间有序）/ skill_id String64 索引 / wf_id String16 可空 / tenant_id·product_space_id 可空索引（横切平台级运行留空）/ status String16 索引（`succeeded`=外部投递终结态、`requested`=系统触发尚无产出（Q71 补货，Q76-4）；`failed` 预留）/ source String16（`delivery`=operations 外部投递、`restock_auto`=system 消费触发）/ `input`/`output` JSONB（SQLite 变体 JSON）/ input_tokens·output_tokens Int 可空（成本金额待 Q67 模型注册表，未建列）/ confidence Float 可空 / error Text 可空 / created_by（投递=actor.id，补货=`system`）/ created_at 索引。无任何 update/delete 代码路径。
- 同迁移建 **`skill_candidates`**（skill7 通用候选，Q76-3；15 §3 通用管道；04 原无此实体，字段为本次实现补）：candidate_id String36 PK（uuid1）/ run_id 索引 + candidate_index Int，uq(run_id,candidate_index) / skill_id 索引 / wf_id / tenant_id 可空索引 / product_space_id 索引 / target_type String32（试点仅 `pwc_combo`）/ payload JSONB（confirmed 原样应用、modified 整体替换并置 human_modified=true）/ state String16 索引（pending_review/applied/archived；投递即 pending_review，ai_suggested 不持久化【实现补】）/ applied_refs JSONB（适配器落库结果 id 列表）/ human_modified Bool server_default false / review_note / reviewed_by / reviewed_at / created_at。每次投递/裁决/补货 writeAudit（skill7.run_delivered / candidate_applied / candidate_rejected / restock_requested）。PG16 up/downgrade-1/up 实测。
- **实现补登（2026-09-14，WF-01 切片 Q79-4，迁移 0013_skill7_intake_anchor）**：段2 先于 ProductSpace，两表各加 `intake_id` String36 可空索引，`skill_candidates.product_space_id` 改可空；投递锚点按 WF 归属二选一（c1_recognition=intake；pwc_combo/field_plan=PS），同一行只回填其一。target_type 扩为 `pwc_combo`/`field_plan`/`c1_recognition`。PG16 up/downgrade-1/up 实测（0013 downgrade 将 product_space_id 复原 NOT NULL）。
- **实现补登（2026-09-14，Q82 模型网关试点，迁移 0014_model_gateway）**：source 枚举增 `llm_auto`（进程内真 LLM 系统 Actor 投递）；`skill_runs` 加 `model_id` String36 可空索引 / `input_cost`·`output_cost` Numeric(12,6) 可空 / `currency_code` String3 可空（per-1M 价 × tokens/1e6，ROUND_HALF_UP 6 位；币种【原文未给出，待补】）。PG16 up/downgrade-1/up 实测。
- **实现补登（2026-09-14，Q83 PWC-BUILDER 第二站，迁移 0015_pwc_builder_seed，纯数据无 schema 变更）**：仅 3 行种子——`ai_scene_routes` PWC-BUILDER→synthetic、`skill_prompts` PWC-BUILDER v0.1 指针、`skill_prompt_versions` v0.1 模板（变量 approved_atoms/active_goals/capacity/ready_count/target_platforms/batch_limit）。downgrade 按三表 DELETE。PG16 up/downgrade-1/up 实测。
- **实现补登（2026-09-15，Q84 C7 Layer4 TYPE-MATCH 第三站，迁移 0016_type_match_seed，纯数据无 schema 变更）**：仅 3 行种子——`ai_scene_routes` TYPE-MATCH→synthetic、`skill_prompts` TYPE-MATCH v0.1 指针、`skill_prompt_versions` v0.1 模板（变量 category/required_fids/own_template/sibling_summary/coverage_floor/g2_coverage）。downgrade 按三表 DELETE。PG16 up/downgrade-1/up 实测。
- **实现补登（2026-09-15，Q85 WF-02 DIM-MERGE 字段池方案第四站，迁移 0017_dim_merge_seed，纯数据无 schema 变更）**：仅 3 行种子——`ai_scene_routes` DIM-MERGE→synthetic、`skill_prompts` DIM-MERGE v0.1 指针、`skill_prompt_versions` v0.1 模板（变量 product_profile/sensitive_industry/industry_tag/enabled_routes/active_g2_fields/dim_range/target_atom_range）。downgrade 按三表 DELETE。PG16 up/downgrade-1/up 实测。
- **实现补登（2026-09-15，Q86 WF-03 原子补池第五站，迁移 0018_atom_affinity_embedding——首个带 schema 变更的 LLM 切片，PG16 用 pgvector/pgvector:pg16 一次性容器 up/downgrade-1/up 实测）**：①PG 端 `CREATE EXTENSION IF NOT EXISTS vector`（downgrade `DROP EXTENSION`），SQLite 测试端不经迁移建扩展；②`ai_models` 加 `capability` String16 NOT NULL server_default `chat`（chat|embedding；downgrade 丢列）；③`atom_candidates.embedding` 与 `product_atom_instances.embedding` 两列 nullable——PG 类型 `vector(1536)`、SQLite LargeBinary（float32 小端，可移植 TypeDecorator 双方言承载；1536 为通行 embedding 维实现取值，真模型接入时维度演进只改 TypeDecorator 单点）；历史行 NULL 不 backfill，approve 时从候选复制向量到正式实例；不建 KNN 索引（V1 进程内余弦，`<=>`/千万级切换按 14 §2.3 后置）；④种子：配置项 `atom.cluster_line`（0.9，借 Q10 同义线原文未给【待补】；**用 `postgresql.insert(...).on_conflict_do_nothing()`**——0010 按 CONFIG_SEEDS 快照播种，全新库该行已由 0010 插入，0018 不得重复 INSERT 撞唯一约束，旧库从 0017 升级时正常补行）+ 第二个合成模型 `synthetic-embedding`（capability=embedding，价 0/无预算/active）+ CONFLICT-PRECHECK→synthetic-deterministic 与 ATOM-AFFINITY→synthetic-embedding 两条路由 + CONFLICT-PRECHECK Prompt v0.1（无 ATOM-AFFINITY Prompt，embedding 场景不挂模板）；downgrade 删上述全部种子行再丢列/扩展。**Q87（2026-09-15，restock_auto M8 worker）无 Alembic 迁移**：纯代码切片——`skill_runs.status=failed` 为 Q71 预留枚举，子 run 回链走既有 `input` JSON 的 `restock_request_id`，无新表/新列/新种子，Alembic 头仍为 0018。

**audit_logs（writeAudit）** — 04 §3 待补（**已实现**：迁移 0001 建表，物理落 `app/core/models.py`）
- 所有人工操作 + AI 调用全记录，append-only 不可篡改

**approval_tasks（审核任务/待办）** — 04 §2.25
| 要素 | 说明 | 来源 |
|---|---|---|
| 类型 | 类目确认/法审/权重表审批/原子证据等（全链几十处 Gate） | Q70 |
| SLA | 各类型时限配置（法审 48h / 类目确认 72h / 原子证据 7 天 / 未冻结 7 天） | Q49/Q18/Q28 |
| 升级 | 通用 SLA 引擎：24h 黄 / 48h 升级上级 | Q49 |
| 批量 | 置信 >0.85 批量通过，低于线逐条 | Q70 |

**model_registry（统一模型注册表）** — 04 §2.24（字段完整）
- 字段：模型/供应商/输入价/输出价/日预算/状态/fallback；**统一 per-1M 口径**（Q67 消除千倍差）
- 场景路由表：场景→默认模型（类目识别/原子拓展/内容生成/合规复检等），运营可改不动代码
- **实现补登（2026-09-14，Q67/Q82，迁移 0014_model_gateway，物理表落 `app/core/model_registry/models.py`，PG16 up/downgrade-1/up 实测）**：拆五表——
  - `ai_models`：model_id String36 PK（uuid1；种子行用 uuid5 固定值）/ model_code String64 unique / provider String32 / input·output_price_per_1m Numeric(12,4) server_default 0 / currency_code String3 可空【原文未给出，待补】/ daily_budget Numeric(12,4) 可空（NULL=不限）/ status String16 server_default active / fallback_model_id 自引用 FK 可空 / created_by·updated_by / created_at·updated_at(onupdate)。
  - `ai_model_keys`（outbound）：key_id PK / model_id FK 索引 / ciphertext LargeBinary（Fernet，env 主密钥派生）/ fingerprint String8（明文末 4 位）/ status active·revoked / created_by·created_at / revoked_by·revoked_at；一模型至多一 active 行，轮换事务内旧行置 revoked + 插新行，历史保留；任何读路径不回显明文/密文。
  - `ai_scene_routes`：scene String64 PK（= skill_id）/ model_id FK / updated_by·updated_at。
  - `skill_prompts`：skill_id PK / current_version String16 / updated_by·updated_at（当前版本指针）。
  - `skill_prompt_versions`：version_id PK / skill_id 索引 / version String16 / template Text / change_note Text 可空 / variables JSONB / created_by·created_at；uq(skill_id,version)；append-only，首版 v0.1。
  - 迁移种子（固定 uuid5）：`synthetic-deterministic`（provider=synthetic，价 0/无预算/active）+ CAT-RECOG→synthetic 路由 + CAT-RECOG Prompt v0.1（变量 product_profile/signal_keys/category_options）。Q83 起（迁移 0015 纯种子，无 schema 变更）再加 PWC-BUILDER→synthetic 路由与 PWC-BUILDER Prompt v0.1（变量 approved_atoms/active_goals/capacity/ready_count/target_platforms/batch_limit）。Q84 起（迁移 0016 纯种子，无 schema 变更）再加 TYPE-MATCH→synthetic 路由与 TYPE-MATCH Prompt v0.1（变量 category/required_fids/own_template/sibling_summary/coverage_floor/g2_coverage）。Q85 起（迁移 0017 纯种子，无 schema 变更）再加 DIM-MERGE→synthetic 路由与 DIM-MERGE Prompt v0.1（变量 product_profile/sensitive_industry/industry_tag/enabled_routes/active_g2_fields/dim_range/target_atom_range）。Q86 起（迁移 0018 带 schema：pgvector 扩展/ai_models.capability/两表 vector(1536) embedding 列/atom.cluster_line 配置，详见上 skill_run_logs 节 0018 补登）再加第二个合成模型 synthetic-embedding（capability=embedding）、CONFLICT-PRECHECK→synthetic-deterministic 与 ATOM-AFFINITY→synthetic-embedding 两条路由、CONFLICT-PRECHECK Prompt v0.1（模板变量 6 项 product_profile/sensitive_industry/batch_size/selected_dimensions/approved_atoms/target_range；ATOM-AFFINITY 为 embedding 能力场景不挂 Prompt）。

**agent_registry（Agent 注册表）** — 04 表 #30
- 3 个 Agent：AG-REVIEW-COPILOT（10 轮/8000 token）、AG-PM-AUDIT（6/6000）、AG-SUPPORT（20/4000，上线前脱敏审核）
- 边界：不能批正式对象；必须有 max_turns + max_tokens + emergency_stop（line 2115 / Q66）

**config_center（系统配置中心）** — 02 §C2 全表
- 40+ 配置项：key/value/类型/校验/出处 Q 编号/审计；禁止硬编码（Q9）
- 热更新（14 §2.4 定稿）：配置落库 + 变更广播；**发布=新版本 + 原子切换 + writeAudit**，自带版本历史与回滚；建议表结构 key 唯一 + 版本子表（config_center_versions）【建议】
- 权重和=1（Q2）与 Σ≤1.0（Q40）做成**通用校验器**被多处复用【建议】

> **实现补登（2026-09-14，M10 切片 a，迁移 0010_m10_config_center，PG16 up/downgrade-1/up 实测）**：物理表 `config_items` + `config_item_versions` 落于 `app/core/config_center/`。**config_items**：key String128 PK / category String64 索引 / value JSONB（SQLite 变体 JSON）/ value_type String16（int/float/bool/string/json）/ validation JSONB 可空（`{min,max,choices}` 通用边界/枚举校验；bool 不触发数值边界）/ source_ref String64（Q 编号或 line 出处）/ version Int（server_default 1）/ updated_by / created_at / updated_at（Python 端 default+onupdate 落值，避免提交后过期属性惰性 IO）。**config_item_versions**：version_id String36 PK（uuid1；种子行用 uuid5(`loom-config-seed:{key}`) 确定性值）/ key 索引 / version / value JSONB / change_note / changed_by / created_at；唯一约束 `uq_config_version_key_version(key,version)`；回滚=以**新** version 重发历史值（append-only，历史行永不改写）。迁移种子 **54 项**覆盖 C2 全部纯标量旋钮（c1/fieldpool/atom/pwc/pws/sla/fcw/content/feedback/platform/agent 各类，含后置阶段的 Q56/Q57/Q61/Q63/Q65 与 line2119 agent 限额——"配置页面先行"）；**已有专用 CRUD 表的 C2 项不入种子**（行业阈值、信号权重、词库、CP-LAW、contentGoals、发布位、PCP 模板、模型注册表等），避免双事实源。类型规则（`config_rules.coerce`）：bool 必须是 JSON 真布尔（拒 1/"true"）、int 拒浮点与字符串、float 接受 int、string 非空。每次发布/回滚 append_audit（entity_type=`config_item`，action=`config.update`/`config.rollback`，detail 带 version/value/note）。热更新：进程内单例快照 `config_cache`，仅在会话 `after_commit` 后原子 apply，失败发布不动缓存；多副本 Redis 广播【挂账】。**启动引导与消费（切片 c 已接通，2026-09-14）**：lifespan 启动时独立会话全量 reload（失败告警不阻断，回落种子默认）；M1–M8 拍板值经 `knob(key)` 统一访问器读缓存/回落种子，无 schema 变更。**未含**：权重和=1/Σ≤1.0 复用校验器（权重仍在各自 CRUD 表内校验）、配置页前端。

**api_keys（API Key）** — 04 §3 待补
- 一 Agent 一 Key，可吊销；唯一入口（真接 LLM 时模型注册页是唯一入口，line 2101）；effect-callback 鉴权
- **outbound 供应商密钥半套已实现（Q82，物理表 ai_model_keys 见上 model_registry；Fernet 可逆加密，因出站须还原明文）**
- **入站一 Agent 一 Key 半套已实现（Q88，2026-09-15，迁移 0019_agent_api_keys，down_revision=0018_atom_affinity_embedding；物理表落 `app/core/api_keys/models.py`，PG16 一次性容器 up/downgrade-1/up 实测）**：物理表名 `agent_api_keys`——key_id String36 PK（uuid1 默认）/ name String128 NOT NULL（Agent 标识/运营备注）/ key_hash String64 NOT NULL（明文的 SHA-256 hex；唯一约束 `uq_agent_api_key_hash` + 索引 `ix_agent_api_keys_key_hash`）/ key_prefix String24 NOT NULL（明文前 12 字符展示码，非凭证）/ status String16 NOT NULL server_default `active`（active|revoked）/ created_by String64 可空 / created_at timestamptz NOT NULL server_default now() / revoked_by String64 可空 / revoked_at timestamptz 可空 / last_used_at timestamptz 可空；**无 tenant_id**（平台级凭证，单租户绑定原文未给【待补】）。明文 = `loom_`+secrets.token_urlsafe(32)，仅签发响应返回一次，任何读路径不回显；吊销=状态位 append-only（不物理删除）。与 ai_model_keys 刻意分表分域：入站只需哈希比对（库泄露不暴露可用 Key），出站须 Fernet 还原。downgrade  drop index + drop table。**未含（随段13/P3 V2）**：effect-callback 端点、effect_records 时序表、孤儿队列表、Q60a content_id↔platform_post_id 映射与运营回填——本迁移只落凭证底座。
- **restock 瞬态退避游标已实现（Q90，2026-09-15，迁移 0020_restock_retry_state，down_revision=0019_agent_api_keys；物理表落 `app/core/restock/models.py`，PG16 一次性容器 up/downgrade-1/up 实测）**：物理表名 `restock_retry_state`——request_id String36 PK（=requested/restock_auto 信号行 run_id）/ attempts Integer NOT NULL（默认 0，每次瞬态 +1）/ next_attempt_at timestamptz NOT NULL + 索引 `ix_restock_retry_state_next_attempt_at`（定时轮按 now 过滤）/ last_reason String64 NOT NULL（异常类名 BudgetExhausted|GenerationUpstreamError）/ updated_at timestamptz NOT NULL server_default now()。**执行态侧表而非业务事实日志**：skill_runs requested 行永不 mutate（Q87），重试态只 upsert 本表；信号成功或转终态删除游标行，审计轨迹（restock_deferred/restock_failed）在 audit_logs 不受影响。downgrade drop index + drop table。

**dict_management（字典管理）** — Q25/Q38/Q43/Q46
- 内容目的字典（contentGoals）/ 降级动作字典（REMOVE_BRAND/REMOVE_CLAIM/REMOVE_HOOK/REWRITE/…，Q38）/ 17 池选项字典 / 通用底座（Q46 权限单列）
- 全部 CRUD + 审计

**memory_layers（Memory 6 层 M1–M6）** — 展示口径，09 §3.13
- 内容：M1 项目规范 / M2 产品知识 / M3 平台知识 / M4 内容策略 / M5 使用表现 / M6 Skill 运行
- 存储：PostgreSQL + pgvector + S3 对象存储 + Redis 缓存（14 定稿，见 §1.3）

**auxiliary_systems（10 辅助系统）** — 展示口径，09 §3.12
- Knowledge Graph / Evidence Center / Evaluation Dataset / Golden Cases / Simulation Sandbox / Rollback Center / Drift Detection / Human Feedback Loop / Multi-model Router / Context Pack Builder
- **MVP 只建 Evaluation Dataset + Golden Cases 两件套**（14 §2.6 定稿，落 eval/ 目录，与 16 测试联动）；Simulation Sandbox 及其余随 V2-V3

> **迁移 0021–0026 汇总补登（2026-09-17 一次性登记，销 handoff「迁移登记落后」缺口；各切片细节见 02 C1.37–C1.60、08 各完成情况）**：
> - **0021_review_batch_pass_confidence**（纯配置种子，Q93）：新增 `review.batch_pass_confidence=0.85`（category=review）。
> - **0022_review_sla_hours**（纯配置种子，Q94）：新增 `review.sla_hours.{pwc_combo,field_plan,c1_recognition,atom_batch,c7_layer4}` 五键，V1 统一 72h（Q114 后 source_ref=Q70②/Q114）。
> - **0023_tenant_registry**（建表 + 存量回填，Q95）：新表 **`tenants`** —— tenant_id String(64) PK / name String(128) 可空 / plan String(16) default trial（trial|basic|pro|enterprise）/ status String(16) default trial 索引（trial|active|paused）/ monthly_token_quota Int 可空（试用 500000，付费档 null＝额度【待补】）/ detail JSONB（PG 端 JSONB、SQLite 变体 JSON，`sa.JSON().with_variant(postgresql.JSONB(),'postgresql')`；回填标记等机读元数据，0023 回填行 `{"backfilled": true}`）/ created_by / created_at / plan_changed_by·plan_changed_at / paused_by·paused_at。回填口径=product_intake_applications ∪ product_spaces 的 DISTINCT tenant_id，置 basic/active + detail.backfilled + created_by=system-migration-0023。**准入为应用层闸**（未知 404/暂停 409），不加硬外键。物理表落 `app/core/tenants/models.py`。
> - **0024_g2_common_fields**（纯种子，Q115）：`g2_fields` 落 12 个 cat='common' 字段（fid 英文 slug + field_name 中文 canonical + status=active，ON CONFLICT DO NOTHING 幂等）；余 6 个 common 字段【原文未给出，待补】不落。**G2 fid 为工程定稿标识符，业务事实以 field_name 中文名为准**（Q115，详见 04 §2.2/§2.5、12 §1.2）。
> - **0025_content_products**（建表，Q116）+ **0026_article_gen_seed**（纯种子，Q116）：见 §2.6 补登。
> - **0027_product_space_fks**（纯约束，Q118，不新增表）：`product_spaces.category_node_id`→`g1_categories.category_id`、`active_pws_id`→`pws_snapshots.pws_id` 补 DB 级真 FK（均 nullable，先幂等置空孤儿再建约束，downgrade drop）；同名 ORM 列同步改 ForeignKey。PG16 一次性容器全链 up / downgrade-1 / up + 孤儿拒绝 + NULL 合法实测通过（02 C1.62）。
> - **0028_content_languages**（建表+加列+约束，Q119，新增 1 表）：建 `content_languages`（含 zh-CN 全市场种子）、`product_spaces` 加 `target_languages` JSONB nullable、`content_products` 加唯一约束 `uq_content_final_language_kind(final_id,language,kind)`；downgrade 对称（drop 约束/列/表）。PG16 一次性容器全新库 up / downgrade-1 / 再 up 实测往返对称（02 C1.63）。
> - **0029_content_quality**（加列，Q120，不新增表）：`content_products` 加 nullable `quality_score` Float、`quality_issues` JSONB；downgrade 对称 drop 两列。
> - **0030_article_qc_seed**（纯种子，Q120，不新增表）：bulk_insert 第 8 场景 ARTICLE-QC→synthetic 路由及 SkillPrompt/SkillPromptVersion v0.1 三件套；downgrade 三 DELETE。PG16 一次性容器全新库 up / 逐档 downgrade / 再 up 实测往返对称（02 C1.64）。
> - **0031_article_semantic_seed**（纯种子，Q121，不新增表）：bulk_insert 第 9 场景 ARTICLE-SEMANTIC-CHECK→synthetic 路由及 SkillPrompt/SkillPromptVersion v0.1 三件套（复检第②项语义级检测，只读不改写，输出 {findings}）；downgrade 三 DELETE。PG16 一次性容器全新库 up（三件套就位）/ downgrade -1 回 0030（语义三件套全清、ARTICLE-QC 三件套保留）/ 再 up 恢复实测往返对称（02 C1.65）。
> - **0032_content_discard**（加列+换索引，Q124，不新增表）：`content_products` 加 nullable `discard_reason` Text；drop 普通唯一约束 uq_content_final_language_kind 并建同名 **partial unique index `WHERE status <> 'discarded'`**（第七态 discarded 终态、作废后同键可重新生成=回池）；downgrade drop 列并重建普通唯一索引（不处理已存在同键冲突，V1 无生产数据）。PG16 一次性容器全新库 up / discarded+live 同键共存而第三条 live 同键 duplicate key 拒写 / downgrade -1 回 0031（列消失、索引还原普通）/ 再 up 恢复实测往返对称（02 C1.68）。
> - **0033_content_publish**（加列，Q125，不新增表）：`content_products` 加 nullable `published_url` Text、`platform_post_id` String(128)、`published_at` timestamptz（published_at 非空即已发布，不新增 published 态）；downgrade drop 三列。PG16 一次性容器全新库 up / downgrade -1 回 0032（三列消失、discard_reason 保留）/ 再 up 恢复实测往返对称（02 C1.69）。
> - **0034_effect_records**（**新表**，Q126 段13 反馈回流入站第一片，`app/core/effects/`）：`effect_records`——record_id String36 PK(uuid1) / source String64 NOT NULL（Agent 标识，customer-backfill 为特例）/ external_content_id String36 NOT NULL（推送方自报 content_id 原值，幂等键组成）/ matched_content_id String36 可空（FK `fk_effect_records_content`→content_products.content_id）/ tenant_id String36 可空（matched 时由 content.tenant_id 回填；Q88 Key 不绑租户，孤儿留空）/ platform_post_id Text NOT NULL（留存核对、不参与自动匹配）/ captured_at timestamptz NOT NULL（须带时区、归一 UTC）/ metrics JSONB 可空（七键稀疏：plays/likes/comments/shares/inquiries/conversions 非负整数 + read_rate 0..1，缺席键与显式 null 不落、绝不写 0）/ status String16 NOT NULL server_default orphan（matched|orphan；查无或命中 discarded 即 orphan）/ received_by String64 可空(=agent key_id) / created_at now NOT NULL / updated_at 可空。索引：唯一 `uq_effect_content_captured(external_content_id,captured_at)`（同 content+采集点幂等覆盖、新点追加时序）、`ix_effect_records_status`、复合 `ix_effect_records_matched_series(matched_content_id,captured_at)`（前缀覆盖成品时序读）、`ix_effect_records_tenant_id`；downgrade drop 四索引 + drop 表。PG16 一次性容器全新库 up（12 列 / metrics=jsonb / captured_at=timestamptz / 4 业务索引+主键 / FK 就位，业务物理表 55→56）/ downgrade -1 回 0033（表、四索引、FK 全清，回 55）/ 再 up 恢复（56）实测往返对称（02 C1.70）。
> - **0035_effect_claims**（**新表+加列**，Q127 段13 Q60a 孤儿人工认领，`app/core/effects/`）：新建 `effect_claims`——external_content_id String36 PK（推送方自报 ID，与 effect_records.external_content_id 同值域）/ content_id String36 NOT NULL（FK `fk_effect_claims_content`→content_products.content_id；非 discarded 由服务层保证）/ claimed_by String64 NOT NULL / claimed_at timestamptz NOT NULL server_default now() / updated_at timestamptz 可空；一个推送 ID 一行持久映射，重复认领=upsert 改绑。同时 `effect_records` 加 nullable `claimed_by` String64、`claimed_at` timestamptz 两行级溯源列（**不新增第三状态**：认领后 status 置 matched、matched_content_id/tenant_id 回填，claimed_by 非空即人工认领）；无新索引（PK 即映射查键，行级回填走既有 ix_effect_records_status 与 external_content_id 扫描，V1 数据量小）。downgrade drop 两列 + drop effect_claims。PG16 一次性容器全新库 up（effect_claims 5 列/PK/FK 就位、两列 timestamptz/varchar 可空，业务物理表 56→57）/ downgrade -1 回 0034（表与两列全清，回 56）/ 再 up 恢复（57）实测往返对称（02 C1.71）。Q128 customer-backfill 客户通道（`POST /api/effects/backfill`）复用 effect_records、**零迁移**。
> - **0036_export_jobs**（**新表**，Q132 中台导出 JSON 形态 + 异步导出任务，`app/core/exports/`）：`export_jobs`——job_id String36 PK(uuid1) / tenant_id String36 NOT NULL（ix_export_jobs_tenant_id）/ product_space_id String36 可空 / format String8 NOT NULL（csv|json）/ status String16 NOT NULL server_default completed（V1 同步仅 completed/failed，queued/running 随 V2）/ row_count Integer NOT NULL server_default 0（创建时留痕，不随后续变化）/ file_name String128 NOT NULL / requested_by String64 NOT NULL / error Text 可空 / created_at timestamptz now NOT NULL / completed_at timestamptz 可空。**不存文件 payload**——下载口按任务参数重新查询渲染（幂等反映当前 published 集合）；索引仅主键 + tenant_id。downgrade drop 索引 + drop 表。PG16 一次性容器（5433 避 atlas-pg）up（11 列/pkey/ix 就位，业务物理表 57→58）/ downgrade -1 回 0035（表与索引全清，回 57）/ 再 up 恢复（58）实测往返对称（02 C1.76）。
> - **0037_restock_claims**（**新表**，Q143 下游 PG 行级 fence 接 restock 花钱路径，`app/core/restock/fencing.py`）：`restock_claims`——request_id String36 PK（对应 restock requested 信号行 id，每个补货信号至多一行）/ fence Integer NOT NULL（当前获准花钱的最大 Q133 fencing 令牌，单调只升）/ claimed_by String64 可空（持锁 leader 的 owner_token 溯源）/ claimed_at timestamptz NOT NULL server_default now / updated_at timestamptz NOT NULL server_default now。无业务外键、无额外索引（仅主键，request_id 即查询键）。语义＝花钱前 claim_request 在独立短事务插入或把 fence 单调升到自己（acquired/held/lost，先提交让易主新 leader 可见）；成功结果在同一业务事务提交前 fence_current 执行 `UPDATE restock_claims SET updated_at=now WHERE request_id=:id AND fence=:token`，rowcount=0 即被更大 fence 抢占、回滚整轮（succeeded 子 run/候选不落库）；fence=None（多副本锁关闭，V1 默认）不写表、不开门。downgrade drop 表。PG16 一次性容器（55432 避 atlas-pg）upgrade head（5 列/pkey 就位，业务物理表 58→59，总 public 表 60＝59 业务+alembic_version）/ downgrade -1 回 0036（to_regclass 为空、表全清，回 58）/ 再 upgrade 重建（59）实测往返对称（02 C1.87）。
> - **0038_sweep_tick_claims**（**新表**，Q151 SLA sweep 写路径 PG 行级 fence，`app/core/sla/fencing.py`）：`sweep_tick_claims`——lock_name String64 PK（循环锁名，如 loom:lock:sla-sweep，每把锁至多一行 upsert，区别于 restock_claims 的 per-request 行）/ fence Integer NOT NULL（当前获准写 SLA 作业结果的 Q133 fencing 令牌，单调只升）/ claimed_by String64 可空（持锁 leader 的 owner_token 溯源）/ claimed_at timestamptz NOT NULL server_default now / updated_at timestamptz NOT NULL server_default now。无业务外键、无额外索引（仅主键，lock_name 即查询键）。语义＝tick 开始 claim_tick 在独立短事务插入或把 fence 单调升到自己（TICK_ACQUIRED/HELD/LOST，先提交让易主新 leader 可见）；每个作业在同一业务事务提交前 fence_current 执行 `UPDATE sweep_tick_claims SET updated_at=now WHERE lock_name=:name AND fence=:token`，rowcount=0 即锁在作业执行期间易主、回滚该作业并抛 LockLost 中止本轮后续作业；fence=None（多副本锁关闭，V1 默认）全程 no-op 不写表。downgrade drop 表。PG16 一次性容器（55432 避 atlas-pg）upgrade head（5 列/pkey 就位，业务物理表 59→60，总 public 表 61＝60 业务+alembic_version）/ downgrade -1 回 0037（表全清，回 59）/ 再 upgrade 重建（60）实测往返对称（02 C1.95）。
> - **0039_import_jobs**（**新表**，Q161 客户效果回填异步导入任务，`app/core/imports/`）：`import_jobs`——job_id String36 PK / tenant_id String36 NOT NULL（ix_import_jobs_tenant_id）/ content_id String36 NOT NULL（ix_import_jobs_content_id）/ format String8 NOT NULL（csv|xlsx）/ payload **Text NOT NULL**（落 CSV 原文或 xlsx base64，导入是写、必须可由后台 worker 重放——刻意镜像而又相反于 0036 export_jobs 的不存 payload、下载按参数重渲染）/ filename String128 可空 / status String16 NOT NULL server_default `completed`（queued|running|completed|failed；server_default 镜像 export_jobs 惯例，门控关请求内同步跑到终态）/ received·matched·orphan·upserted·row_count 五计数 Integer NOT NULL server_default 0 / requested_by String64 NOT NULL / error Text 可空（任务级失败因）/ errors Text 可空（确定性校验失败时逐行坏行 JSON 截断）/ created_at timestamptz now NOT NULL / completed_at timestamptz 可空。索引仅主键＋tenant_id/content_id 两普通索引，无 FK/UQ。downgrade drop 两索引 + drop 表。PG16 一次性容器（55432 避 atlas-pg）upgrade head（17 列/3 索引就位，业务物理表 60→61，总 public 表 62＝61 业务+alembic_version）/ downgrade -1 回 0038（to_regclass 为空、两索引与表全清，回 60）/ 再 upgrade 重建（61、17 列）实测往返对称（02 C1.105，2026-09-22 补测）。
> - **0040_staff_api_keys**（**新表**，Q178 身份层 P0-① 甲案内部运营 PAT，`app/core/staff_auth/models.py`）：`staff_api_keys`——key_id String36 PK / staff_id String64 NOT NULL（非唯一索引 `ix_staff_api_keys_staff_id`，一人多 token 轮换）/ staff_name String128 NOT NULL / roles **JSONB**（PG 端 JSONB、SQLite 变体 JSON，存五内部角色数组）/ key_hash String64 NOT NULL（明文的 SHA-256 hex；唯一约束 `uq_staff_api_key_hash` + 索引 `ix_staff_api_keys_key_hash`）/ key_prefix String24 NOT NULL（明文展示前缀，非凭证）/ status String16 NOT NULL server_default `active`（active|revoked）/ created_by·revoked_by String64 可空 / created_at timestamptz now NOT NULL / revoked_at·last_used_at timestamptz 可空。明文 = `loom_staff_`+secrets.token_urlsafe(30)，仅签发响应返回一次、任何读路径不回显；与 Q88 机器 `agent_api_keys`（`loom_` 前缀、迁移 0019）**分表分前缀、不可互换**；**无 tenant_id**（平台级内部人员凭证，审计 tenant 恒 `_platform`；客户侧 actor↔tenant 绑定仍 V2）。可签发角色限 {operations, platform_admin, product_reviewer, dictionary_admin, internal_compliance}（不含 whitelist_owner）。downgrade drop 两索引 + drop 表。PG16 一次性容器（宿主 55442 避 atlas-pg）upgrade head（jsonb roles/unique+两索引/PK/默认值就位，业务物理表 61→62，总 public 表 63＝62 业务+alembic_version）/ downgrade -1 回 0039（表与索引全清，回 61）/ 再 up 重建（62）实测往返对称（02 C1.122）。**该表在 Q171 第三轮复核（61 表/654 列/215 索引）之后落地，已纳入 2026-09-24 第四轮全量列复核（62 表/666 列/219 业务索引/PK62·FK32·UQ21，零漂移，见 §4）。**
> - **0041_discard_retention_seed**（**纯配置种子迁移，无 schema 变更**，Q187/C4 甲案 discarded 成品保留期清理）：只向 `config_items` + `config_item_versions` 各插 **1 行**——键 `content.discard_retention_days`（category `content`／value_type `int`／值 **180**／validation `{min:1}`／`source_ref` 取 `CONFIG_SEEDS` 现值（0041 在**执行时**从 `seeds.py` 取元组，不是硬编码）／version 1；Q187 播种时为「Q187/C4 甲案（原文未给出，待追认）」，Q190 追认后 `seeds.py` 已改标「…2026-09-25 负责人追认」，**故已跑过 0041 的存量库仍是旧文案，全新库跑出的才是新文案**（本仓无种子回写机制，不为此补迁移），`version_id` 取 `uuid5(NAMESPACE_URL, "loom-config-seed:<key>")`，`ON CONFLICT DO NOTHING` 幂等，同 0021/0022 先例）。**不新建表、不加列、不动索引**，故业务物理表仍 **62**、总列数仍 **666**、业务索引仍 **219**、约束仍 PK62/FK32/UQ21——**第四轮（Q179）全量列复核结论不受影响**；`config_items` 的**行数**由 61 增至 62（行级数据变化不计入本文件表/列/索引口径）。downgrade 按 key 删两表对应行。清理作业本体见 02 C1.131 与 docs/17 §1（门控 `LOOM_DISCARD_PURGE_ENABLED` 默认关）。**已经 pgvector/pg16 一次性容器（宿主 55449 避本机 atlas-pg）全链 0001→0041 实测往返（2026-09-25）**：`upgrade head` 后 head=0041、业务物理表 **62**、总列数 **666**（与第四轮 Q179 逐字一致，证明确无 schema 变更）、`config_items` **62 行**（61→62）、种子行 `value=180 / value_type=int / source_ref="Q187/C4 甲案（原文未给出，待追认）" / version=1` 就位（**该文案是本次往返实测当时 `CONFIG_SEEDS` 的值，保留为测量记录**；Q190 追认后新播种改标已追认）；`downgrade -1` 回 0040、表仍 62、该键在 `config_items`+`config_item_versions` 两表行数归 **0**（删得干净）；再 `upgrade head` 还原（往返对称）。**须记录的迁移编排事实**：0010_config_center 是 `from app.core.config_center.seeds import CONFIG_SEEDS` **在迁移执行时运行时导入并全量播种**（change_note `C2 seed`），故**全新库**上该键已由 0010 插入、0041 的 `ON CONFLICT DO NOTHING` 为空转（实测往返中该行 change_note 即为 `C2 seed` 而非 0041 写的 `Q187 seed`，即为证据）；**0041 的真实作用对象是早已跑过 0010、当前停在 0040 的存量库**——与 0021/0022 纯配置种子迁移完全同型，两条路径终态收敛。
> - **当前 head = 0041_discard_retention_seed**（单链线性，down_revision=0040_staff_api_keys 逐级相扣；0001 为 root）。**0021–0041 各切片的迁移实测记录以 02 对应 C1 条目为准**（0027/0028/0029/0030/0031/0037/0038/0039/0040 已实测 PG16 全链 up/down/up；0021–0026 条目不逐条复记，勿据此推断已验证；0041 纯种子未单独往返，见上条）。

---

## 3. 关系图与约束

| 关系 | 说明 | 来源 |
|---|---|---|
| 产品域私有链 | intake → PS → field_pool → atom → PWC → PWS（产品私域，租户隔离） | 01 数据流 |
| 共享知识层 | G1 类目树 / G2 字段池 / layerSpaces / 合规词库（平台级，跨租户共享） | Q24 |
| final_id 组装 | PWS + PCP + CSP + CSTP + CEP + CCR → FCW（6 路快照） | line 870 |
| 唯一反向边 | catFeedback → KUP → 回写 G2/原子 weight/类目模板 | 01 段13 |
| 外键纪律 | 引用共享知识用 fid/原子 id（禁 fid:'-'）；引用快照用版本号+id | Q68 |

**索引与唯一约束建议**（【建议】，待 DBA 复核）：
- 全部业务表：(tenant_id, status)；消费热路径按评分排序取（PWC/FCW）
- PWC：(product_space_id, gate_status, score desc)；FCW：final_id 唯一、E1_owner 校验
- 词库：词+等级+适用国家+行业 复合唯一；KUP：(type, target) 去重
- 幂等：effect-callback (content_id, captured_at)；配置中心 key 唯一

---

## 4. 与既有文档的核对项

- [x] 字段名与 04 完全一致，未新增/改名（全部引用 04 章节）；**实现补登中的列名/类型以迁移脚本与 ORM 模型为准**（如 product_spaces.lifecycle）
- [x] Q 编号约束已映射（Q2/Q3/Q5/Q7/Q8/Q12/Q13/Q15/Q17/Q18/Q20/Q21/Q24/Q25/Q27/Q28-Q33/Q34-Q38/Q39-Q43/Q44-Q47/Q48-Q51/Q52-Q55/Q56-Q59/Q60-Q65/Q66-Q72；**Q73–Q116 的新增表/列/种子见各节实现补登**）
- [x] 配置化清单数值不硬编码进表定义（全部指向配置中心）
- [x] 存储引擎已定稿并补入 §1.3（2026-09-13，14 选型）
- [x] 迁移登记完整性（2026-09-17 补登、2026-09-18/19 续登、2026-09-22 续 0039、2026-09-24 续 0040、2026-09-25 续 0041）：迁移 **0001–0041** 均在本文登记（0001–0020 分散于各节，**0021–0041 见 §2.8 汇总补登**）；**当前 head = 0041_discard_retention_seed（纯配置种子、无 schema 变更，业务物理表仍 62、列仍 666，经 pg16 宿主 55449 全链 up/downgrade-1/up 往返实测）**；物理表 62 张（0027 纯加两外键不新增表，0028 新增 content_languages 1 表，0029/0032/0033 纯加列、0032 另换 partial 索引、0030/0031 纯场景种子均不新增表，0034 新增 effect_records 1 表，0035 新增 effect_claims 1 表并加两认领列、Q128 零迁移，**0036 新增 export_jobs 1 表（Q132 中台导出任务记录）、0037 新增 restock_claims 1 表（Q143 restock 花钱路径 PG fence）、0038 新增 sweep_tick_claims 1 表（Q151 SLA sweep 写路径 PG fence）；0037/0038 已经 pg16 往返实测并纳入第二轮全量列复核（2026-09-21，见下条）**、**0039 新增 import_jobs 1 表（Q161 客户效果回填异步导入任务，17 列/主键+两业务索引）；0037/0038 已经 pg16 往返实测并纳入第二轮全量列复核（2026-09-21，见下条），0039 已经 pg16 往返实测并纳入第三轮全量列复核（2026-09-22，见上）；**0040 新增 staff_api_keys 1 表（Q178 内部运营 PAT，12 列/主键＋三业务索引含一唯一约束），已经 pg16 往返实测并纳入第四轮全量列复核（2026-09-24，见下条）**）。
- [x] **DBA 首轮全量建表要素复核（2026-09-20，E 项，head=0036/业务物理表 58）**：方法＝一次性 PG16 容器 upgrade head 后导出 information_schema.columns（627 列）/ pg_indexes（210 行）/ pg_constraint（FK+UQ 52 条）+ numeric 精度/vector 维度，与本文各「实现补登」段逐项核对，另以 ORM metadata 在 SQLite create_all 比对，**58 表表名/列名模型⇄迁移零漂移、零单边表**。结论：①各迁移新增表数对账闭合（0001=4、0002=8、0003=3、0004=5、0005=6、0006=3、0007=3、0008=7、0009=2、0010=2、0012=2、0014=5、0019/0020/0023/0025/0028/0034/0035/0036 各 1，合计 58；0011/0013/0021/0022/0024/0026/0027/0029–0033 不新增表）；②新三表 effect_records（0034 建表 12 列、0035 加认领两列后现 14 列，4 业务索引+FK fk_effect_records_content）、effect_claims（5 列、仅 PK、FK fk_effect_claims_content）、export_jobs（11 列、仅 PK+ix_tenant、status 默认 completed、row_count 默认 0）与登记一致；③content_products 24 列、partial unique index `uq_content_final_language_kind ... WHERE status<>'discarded'` 就位；④numeric 精度 ai_models 单价/日预算 (12,4)、skill_runs 成本 (12,6)，vector(1536) 两列（atom_candidates/product_atom_instances.embedding）+ pgvector 0.8.6 就位；⑤FK/唯一约束名（fk_product_spaces_category_node_id/active_pws_id、uq_fcw_same_issue、uq_pcp_ps_platform、uq_pwc_combo_atom、uq_effect_content_captured 等）全部与登记一致；⑥仅订正两处旧稿笔误（见正文：content_products.status String24→String32、tenants.detail JSON→JSONB）。**未逐一标注 nullable/默认值的列以迁移脚本与 ORM 模型为权威**；§3 索引【建议】项中未落地的复合索引仍按性能实测后置，本次不判为缺陷。
- [x] **DBA 第二轮全量列复核（2026-09-21，head=0038_sweep_tick_claims/业务物理表 60，Q153）**：方法同首轮——一次性 PG16（pgvector/pgvector:pg16，容器 55432 避本机 atlas-pg）`alembic upgrade head` 到 0038 后导出 information_schema.columns / pg_indexes / pg_constraint，并以 ORM `Base.metadata`（import app.main 注册全量模型）逐表逐列比对。结论：①业务表 db=60 / orm=60，无单边表（only-in-db、only-in-orm 均空）；②总列数 **637**（首轮 head=0036 为 627，0037/0038 各 5 列，627+5+5=637 对账闭合）、索引 **212**（首轮 210＋两新表各 1 主键索引＝212）、约束 **PK 60 / FK 32 / UQ 20**（FK+UQ=52 与首轮持平——两新表各仅 1 主键、无 FK/UQ）；③**60 表表名/列名模型⇄迁移零漂移（mismatched tables=0）**；④两新表实测五列/pkey 与 §2.8 登记逐字一致——`restock_claims`(request_id varchar(36) NOT NULL PK / fence integer NOT NULL / claimed_by varchar(64) NULL / claimed_at timestamptz NOT NULL default now() / updated_at timestamptz NOT NULL default now())、`sweep_tick_claims`(lock_name varchar(64) NOT NULL PK / fence integer NOT NULL / claimed_by varchar(64) NULL / claimed_at、updated_at 同上)，pkey 分别为 request_id、lock_name。首轮订正的两处旧稿笔误（content_products.status String32、tenants.detail JSONB）维持不变。**未逐一标注 nullable/默认值的列仍以迁移脚本与 ORM 模型为权威**；本轮仅复核列/索引/约束集合与两新表建表要素，跨连接并发条件 UPDATE 的真实 PG 行为见 Q154 真容器集成验证。
- [x] **DBA 第三轮全量列复核（2026-09-22，head=0039_import_jobs/业务物理表 61，Q171）**：方法同前两轮——一次性 PG16（pgvector/pgvector:pg16，容器宿主端口 55442 避本机 atlas-pg）`alembic upgrade head` 到 0039 后导出 information_schema.columns / pg_indexes / pg_constraint，并以 ORM `Base.metadata`（import app.main 注册全量模型）逐表逐列比对。结论：①业务表 db=61 / orm=61，无单边表（only-in-db、only-in-orm 均空）；②总列数 **654**（第二轮 637＋import_jobs 17 列＝654 对账闭合）、业务索引 **215**（第二轮 212＋import_jobs 主键及 tenant_id/content_id 两业务索引＝215；另 alembic_version_pkey 1 条不计入业务口径）、约束 **PK 61 / FK 32 / UQ 20**（FK/UQ 与第二轮持平——import_jobs 无 FK/UQ）；③**61 表表名/列名模型⇄迁移零漂移（column drift=0）**；④import_jobs 实测 17 列/3 索引与 §2.8 登记逐字一致。**未逐一标注 nullable/默认值的列仍以迁移脚本与 ORM 模型为权威**。
- [x] **DBA 第四轮全量列复核（2026-09-24，head=0040_staff_api_keys/业务物理表 62，Q179）**：方法同前三轮——一次性 PG16（pgvector/pgvector:pg16，容器 loom-dba4 宿主端口 55448 避本机 atlas-pg）`alembic upgrade head` 到 0040 后导出 information_schema.columns / pg_indexes / pg_constraint，并以 ORM `Base.metadata`（import app.main 注册全量模型，Base 在 app/core/db.py）逐表逐列比对。结论：①业务表 db=62 / orm=62，无单边表（only-in-db、only-in-orm 均空）；②总列数 **666**（第三轮 654＋staff_api_keys 12 列＝666 对账闭合）、业务索引 **219**（第三轮 215＋staff_api_keys 四索引：主键 staff_api_keys_pkey、ix_staff_api_keys_staff_id、ix_staff_api_keys_key_hash、唯一 uq_staff_api_key_hash＝219；alembic_version_pkey 不计入业务口径）、约束 **PK 62 / FK 32 / UQ 21**（UQ 较第三轮 +1＝uq_staff_api_key_hash，FK 持平——staff_api_keys 无 FK）；③**62 表表名/列名模型⇄迁移零漂移（column drift=0）**；④staff_api_keys 实测 12 列（key_id/staff_id/staff_name/roles/key_hash/key_prefix/status/created_by/created_at/revoked_by/revoked_at/last_used_at）/4 索引与 §2.8 登记逐字一致。**未逐一标注 nullable/默认值的列仍以迁移脚本与 ORM 模型为权威**。
- [x] **第五轮取消：改为 CI 每次 push 自动跑（Q207，2026-09-26，02 C1.151）**：比对逻辑固化进 `backend/scripts/dba_schema_check.py`，在真 `pgvector/pgvector:pg16` 上跑（`upgrade head` → 漂移检查 → `downgrade -1` → `upgrade head`），实测当前**62 表／666 列／PK 62／FK 32／唯一约束或唯一索引 24／普通索引 133，零漂移**。今后不再需要人工"第 N 轮"。同时修掉 `alembic/env.py` 少注册 10 个模型模块的隐患（`target_metadata` 44→62 张表）。**不覆盖**列长度精度、索引存储方法、默认值、CHECK 约束。**计数口径与前四轮不同，不要把两行数字对着看**：本门的「唯一约束或唯一索引 24」＝`pg_constraint.contype='u'` 的行＋`pg_index.indisunique` 中**不由约束自动创建**的唯一索引；「普通索引 133」同样排除约束自动创建者，而前四轮的「业务索引 219」是 `pg_indexes` 全量减 `alembic_version_pkey`。两边其实相等：24＋133＝157，再加 62 条主键自动索引＝**219**（0041 纯配置种子、无索引变更）——差别只在**主键索引计不计入**（定义以脚本 `UQ_SQL`/`IDX_SQL` 及其上方注释为准）。
- [ ] 字段全定义仍【待补】的实体（memory_layers / 动态信号事件 / 爆款判定记录 / 校准报表 / SLA 待办）——属段 7/13 与横切，随对应阶段任务包补（段 1-6 的 ProductSpace / g2_field_candidates 已于 M0 补齐；~~content_products~~ Q116 已补、~~skill_run_logs~~ Q76 已补、~~audit_logs~~ 迁移 0001 已建、~~api_keys~~ Q88 已补）
- [ ] 文档列为建表、代码尚未建表的**设计稿实体**（layer_spaces/layer_space_items §2.5、countries §2.5、agent_registry §2.8、cat_feedback·field_impact_items·kup_proposals·knowledge_update_logs §2.7）——属段 9/13 与展示口径，实现随 V2/V3；**读作设计稿，勿当已建表**
- [ ] 索引【建议】项未落地者（condition_packages 复合索引、product_atom_instances 复合索引等）——实现为单列索引，是否补复合索引随性能实测定
