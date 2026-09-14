# 10. 数据模型 Schema（建表级定义）

> **状态**：🟢 已补内容（建表级说明，非 DDL 代码）
> **来源**：04_契约层_数据模型.md（35 实体与字段）｜01_PRD §3 各段规格｜02_决策记录（Q 编号）
> **用途**：把 04 的字段清单落成**建表级说明**（类型建议/约束/索引/关系/租户隔离），AI 据此生成数据库迁移脚本。
> **⚠ 说明**：原文（v3/基准 HTML）**未给出字段类型、索引等物理定义**——本表类型/索引列为【建议】（依据字段语义与 Q 约束推断，落地前需 DBA 复核）；约束列凡来自原文 Q/line 的如实标注，凡属惯例的标注【建议】。**不得把【建议】当原文规格使用。**

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
| 幂等键 | 外部推送/重试场景必须有幂等键：effect-callback 用 `content_id + captured_at` | Q60 / 05 §1.1.1 |

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

## 2. 逐表 Schema（35 实体）

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
| 外键 | `tenant_id` 必填；`intake_id` → product_intake_applications；`category_node_id` → g1_category_tree；`active_pws_id` → pws_snapshots（同刻仅 1 个 active，Q31） | Q33/Q5/Q31 |
| 属性 | `industry_tag`（类目路径映射，运营可改 Q7）/ `sensitive_industry` 布尔 / `business_owner`（产品记录字段，非登录角色，09 D8） | Q7/Q11/09 D8 |
| 生命周期 | `lifecycle_priority`：frozen > stale > cold > modeling > active（迁移触发条件原文未给，待补） | line 1655 |
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

> **实现补登（2026-09-13，M4 后端切片）**：原子域随 Alembic 0004 落地（PG16 up/down/up 实测），共 5 表：`compliance_wordlist`（Q48，见 §2.5）、`atom_batches`（拓展批次：batch_size/source/sensitive_snapshot）、`atom_candidates`（候选主体，唯一约束 `(batch_id, normalized)` 同批去重，草稿/待审核活在候选侧）、`atom_conflicts`（三类冲突 + resolved_at）、`product_atom_instances`（Gate 后正式实例，唯一约束 `(fact_type, normalized)` 落实 line 11189 事实原子全局唯一；NULL fact_type 不参与唯一性）。字段类型/索引以迁移脚本为准。

### 2.3 白名单域（段 5–6）

**condition_packages（PWC）** — 04 §2.10（字段完整）
| 要素 | 说明 | 来源 |
|---|---|---|
| combo | 组合明细子表：`pwc_combo_items(pwc_id, fp_id, atom_id)`（跨字段原子组合） | line 1780 |
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

**content_products（内容成品）** — 04 §3 待补
- 载体：文章/视频（video-studio 四模块）/多语言版本；各语言版独立成品（Q58）
- 状态：ready_for_publish / 客户确认 / 已发布 / 驳回 / 改稿（Q59）
- 字段全定义【待补：原文未给出——属开发第 0 步①】

> **实现补登（2026-09-14，M8 后端切片，迁移 0009_m8_stage11，PG16 up/downgrade-1/up 实测）**：
> - `final_content_whitelists`：final_id PK（uuid1，时间有序）/ task_id 可空（关联批量任务）/ tenant_id / product_space_id / pws_id / pwc_id / pcp_id / csp_package_id / cstp_package_id / cep_package_id / ccr_report_id / law_review_id（后两者可空，Guards 实际要求 ccr 存在）/ platform / slot_id / goal（均索引）/ country String(8) 可空索引 / score Float 可空 / score_detail JSONB（公式/权重/原始分/缩放）/ score_incomplete Bool（server_default false）/ guards JSONB（7 项逐项结果）/ guards_passed Bool / publish_status String(16) server_default 'published' / issued_by / published_at / created_at / updated_at；`UNIQUE(pws_id, pwc_id, platform, slot_id)`（含 country 维度的重复判定在服务层补 country 条件，uq 约束按 04 §2.21 实现补登口径）。
> - `fcw_assembly_tasks`（Q55 任务驱动）：task_id PK / tenant_id / product_space_id / pws_id 索引 / platform / goal / country / requested_count / slot_ids JSONB / status(running|completed) / results JSONB（requested/resolved_slots/issued/failures 逐项原因）/ created_by / created_at / completed_at；V1 为同步执行（建单即跑完），异步 worker 随 M10。
> - 分数口径（Q54，仅排序）：PWC 骨架分与三包 conf 为 0–1 先 ×100 归一，slot fit 本为 0–100；`pwc×100×0.4 + fit×0.3 + mean(三包 conf)×100×0.3`；任一来源缺失 → score=null + incomplete=true，不凑分、不卡发证。
> - 挂账：WF-09 AI Skills（V2）、draft 生命周期端点（V1 直接 published，draft 列保留无创建入口）、段12 content_products、消费侧 API（Q71 取用走 M5 PWC 消费，FCW 消费契约【待补】）。

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

**skill_run_logs（Skill 运行日志）** — 04 §3 待补
- 输入/输出/成本/置信度/失败/人工修改记录；**不可 mutate**（append-only）

**audit_logs（writeAudit）** — 04 §3 待补
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

**agent_registry（Agent 注册表）** — 04 表 #30
- 3 个 Agent：AG-REVIEW-COPILOT（10 轮/8000 token）、AG-PM-AUDIT（6/6000）、AG-SUPPORT（20/4000，上线前脱敏审核）
- 边界：不能批正式对象；必须有 max_turns + max_tokens + emergency_stop（line 2115 / Q66）

**config_center（系统配置中心）** — 02 §C2 全表
- 40+ 配置项：key/value/类型/校验/出处 Q 编号/审计；禁止硬编码（Q9）
- 热更新（14 §2.4 定稿）：配置落库 + 变更广播；**发布=新版本 + 原子切换 + writeAudit**，自带版本历史与回滚；建议表结构 key 唯一 + 版本子表（config_center_versions）【建议】
- 权重和=1（Q2）与 Σ≤1.0（Q40）做成**通用校验器**被多处复用【建议】

**api_keys（API Key）** — 04 §3 待补
- 一 Agent 一 Key，可吊销；唯一入口（真接 LLM 时模型注册页是唯一入口，line 2101）；effect-callback 鉴权

**dict_management（字典管理）** — Q25/Q38/Q43/Q46
- 内容目的字典（contentGoals）/ 降级动作字典（REMOVE_BRAND/REMOVE_CLAIM/REMOVE_HOOK/REWRITE/…，Q38）/ 17 池选项字典 / 通用底座（Q46 权限单列）
- 全部 CRUD + 审计

**memory_layers（Memory 6 层 M1–M6）** — 展示口径，09 §3.13
- 内容：M1 项目规范 / M2 产品知识 / M3 平台知识 / M4 内容策略 / M5 使用表现 / M6 Skill 运行
- 存储：PostgreSQL + pgvector + S3 对象存储 + Redis 缓存（14 定稿，见 §1.3）

**auxiliary_systems（10 辅助系统）** — 展示口径，09 §3.12
- Knowledge Graph / Evidence Center / Evaluation Dataset / Golden Cases / Simulation Sandbox / Rollback Center / Drift Detection / Human Feedback Loop / Multi-model Router / Context Pack Builder
- **MVP 只建 Evaluation Dataset + Golden Cases 两件套**（14 §2.6 定稿，落 eval/ 目录，与 16 测试联动）；Simulation Sandbox 及其余随 V2-V3

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

- [x] 字段名与 04 完全一致，未新增/改名（全部引用 04 章节）
- [x] Q 编号约束已映射（Q2/Q3/Q5/Q7/Q8/Q12/Q13/Q15/Q17/Q18/Q20/Q21/Q24/Q25/Q27/Q28-Q33/Q34-Q38/Q39-Q43/Q44-Q47/Q48-Q51/Q52-Q55/Q56-Q59/Q60-Q65/Q66-Q72）
- [x] 配置化清单数值不硬编码进表定义（全部指向配置中心）
- [x] 存储引擎已定稿并补入 §1.3（2026-09-13，14 选型）
- [ ] 字段全定义仍【待补】的实体（content_products / skill_run_logs / audit_logs / api_keys / memory_layers / 动态信号事件 / 爆款判定记录 / 校准报表 / SLA 待办）——属段 7/12/13 与横切，随对应阶段任务包补（段 1-6 的 ProductSpace / g2_field_candidates 已于 M0 补齐）
