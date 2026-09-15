# Loom · 契约层 · Workflow 与 Skill 协议

> **本文档来源**：`../Loom_核心业务主链梳理_v3.md` **Part A / Part D 结构化提取**（重组视图）。
> **文档定位**：AI 落代码的硬前提之一。13 段链 → Workflow → Skill → PT 协议 → Agent 的完整编排视图。
> **⚠ 关键缺口**：40 个 PT 协议中 34 个为占位（红旗 B17）——本文档列出原文已给约束的 7 个协议全文，其余标注【占位：原文未给出】，**不编造协议内容**。
> **配套文档**：实体字段见 04；状态机与 API 见 05；红旗裁决见 03。

---

## 1. Workflow 总表（WF-01 ~ WF-12）

| WF | 归属段 | Skill 数 | 主要 Skill | 来源 |
|---|---|---|---|---|
| WF-01 | 段1+段2（段2并入） | 6 | PARSE → UNDERSTAND → CAT-RECOG → TYPE-MATCH → MISSING-INFO → RISK-TAG | A1 / A3 段1 |
| WF-02 | 段3 | 3 | FIELDPOOL-PLAN → DIM-SOURCE（7 路）→ DIM-MERGE | A1 / A3 段3 |
| WF-03 | 段4 | 4 | ATOM-EXPAND（批次20/50）→ ATOM-CANON → ATOM-AFFINITY → CONFLICT-PRECHECK | A1 / A3 段4 |
| WF-04 | 段5 | 3 | PWC-BUILDER → COMBO-VALIDATE → PWC-SCORING | A1 / A3 段5 |
| WF-05 | 段6 | 1 | PWS 冻结（Skill 名原文未列【待补】） | A1 / A3 段6 |
| WF-06 | 段7+段8（段8由 WF-06 覆盖） | 注册 6 条 / 官方注 5（⚠不一致，红旗 A15） | PLATFORM-PARSE → COMPAT-RULE → DYNAMIC-SIGNAL → PLATFORM-ADAPTER → PCP-BUILD → PCP-SCORE | A1 / A3 段7 |
| WF-07 | 段9 | 4 | CONTENT-GOAL-PLAN → STRUCT-MATCH → TONE-STYLE → CONTENT-GOAL-TAG | A1 / A3 段9 |
| WF-08 | 段10 | 3 | COMPLIANCE → CLAIM-DOWNGRADE → LAW-REVIEW | A1 / A3 段10 |
| WF-09 | 段11 | 2 | FCW-ASSEMBLY + FCW-SCORE | A1 / A3 段11 |
| WF-10 | 段12 | 4 | ARTICLE-GEN / VIDEO-SCRIPT / MULTILANG-GEN / CONTENT-COMPLIANCE 复检 | A1 / A3 段12 |
| WF-11 | 段13 | 3 | KUP-PROPOSE / WEIGHT-UPDATE / 【第 3 个待补】 | A1 / A3 段13 |
| WF-12 | 段13 | 2 | PROMPT-EVAL + DRIFT-DETECT | A1 / A3 段13 |

> 段-WF 映射接缝（红旗 B16 → Q72）：以 §A1 CHAIN_13 表为准，**不新增 WF**：段 8→WF-06 覆盖、段 2→WF-01、段 13→WF-11+WF-12。
> ⚠ 原型未启用的 Skill：PLATFORM-ADAPTER（段7）、KUP-PROPOSE（段13）、PROMPT-EVAL、DRIFT-DETECT（WF-12）——state=pending_review、runs_7d=0，**实现即首次落地**。

### 1.1 WF-04 PWC-SCORING 输出契约（2026-09-13 M0 补，Q22/Q22a/Q22b）

> 段5 的 PWC-SCORING 在原文中仅有 Skill 名（line 918"品类乘数"一句），本契约为 M0 补规格，非原文提取。

- 前置：仅对通过 COMBO-VALIDATE 且未被合规 block 的组合执行；手拼 PWC（Q26）同样执行。
- 输入：组合的逻辑合理性 AI 分、场景情绪搭配 AI 分（0–1，COMBO-VALIDATE 产出）；待用池中各组合的原子集合（算重合占比）。
- 输出：写入 `conditionPackages.score`（0–1）及分项留痕 `score_detail{logic, fit, diversity, category_multiplier, w_logic, w_fit}`；品类乘数取 Q7 行业表列，第一期恒 1.0。
- 计算：`score = (合理性 × 0.6 + 多样性 × 0.4) × 品类乘数`；合理性 = logic×w1 + fit×w2（w1/w2 默认 0.5）；多样性 = 1 − max(原子重合占比)，空池 1.0；重合口径同 Q23。
- 失败策略：任一 AI 分项缺失/超时 → 该分项记"—"、组合转 `pending_review` 进人工 Gate，禁止默认值凑分。
- 约束：score 仅排序与 Gate 展示，不做自动通过门槛；权重/开关/小数位配置化（02 §C2）。

---

## 2. 已定稿 PT 协议（原文给出完整 constraints/guards，共 7 个）

> 注：红旗 B17 原文称"仅 6 个旗舰协议有完整 constraints/guards"，而 01 文档 §3 实际列出 7 个带约束协议——此处按 01 文档列出 7 个，差异为原文计数口径，不擅自改。

### 2.1 PT-FP-PLAN-V2.0（段3 · 字段池规划，line 2001）
- 必须含 ≥1 个 product_attribute 角色维度
- 必须含 ≥1 个 risk_control 候选（合规预筛）
- 维度数 3-8
- 不直接生成原子
- 输出必经 WF-02 HumanGate
- confidence<0.85 触发 HumanGate 必审（Q9 后改为"细看线"，第一期全部走 Gate）

### 2.2 PT-ATOM-EXP-V1.3（段4 · 原子拓展，line 2013）
- 仅产 candidate，不直接写 ProductAtomInstance
- 同批次去重
- 同维度互斥优先禁同义词簇
- risk=high/critical 必走 HumanGate（critical 单条审，不入批量 Gate）
- evidence 必填（空则降级 pending_evidence）
- 产品事实原子（容量/成分/浓度/疣类型/品牌）严禁跨产品复用，引用数恒=1

### 2.3 PT-PLATFORM-ADAPTER-V1.0（段7 · 平台适配，line 2043）
- 只读 frozen PWS
- 禁止消费 pending PWC/PWS
- 禁止输出成稿（正文/脚本/标题）
- **禁止生成 final_id**
- 必须返回 allow / downgrade / block / pending_review 四态
- AI 输出一律 pending_review 需 HumanGate
- 无 frozen PWS 时返回缺失、不造假数据

### 2.4 PT-PCP-V1.5（段8 · 平台条件包，line 2057）
- 17 字段权重总和 ≤1.0
- 不修改产品原子
- 动态信号每周更新触发重算
- 平台间不共享权重池

### 2.5 PT-COMPLIANCE-V2.0（段10 · 合规清洗，line 2029）
- 绝不放过医疗绝对化
- block_required=true 阻断后续 WF（WF-09 必须中止）
- 降级只出建议、最终人工 approval
- 分市场独立判
- 历史 SkillRunLog 不可 mutate（即便回滚）

### 2.6 PT-FCW-ASM-V1.0（段11 · FCW 组装，line 2071）
- 五项 Guard（任一失败→guards_passed=false，final_id 不生成）：
  ①PWS state=frozen ②compliance.block_required=false ③所有 Package state=active ④6 路输入 product_space_id 一致 ⑤tenant_id 一致
- Q52 补充：Guard④⑤ 校验"配置实例"归属（实例落库带 product_space_id/tenant_id），底座字典共享不受影响
- Q53 扩展为 7 项 Guard：+⑥law_review 已通过（Q49）+⑦PWS 为当前 active 版本

### 2.7 PT-ART-GEN-V1.5（段12 · 内容生成，line 2085）
- 只读消费 FCW，不重新决策上游、不重新打分、不加入 FCW 之外的原子
- compliance 已在 FCW 内完成不重判
- 生成后必走 SK-LIB-CONTENT-COMPLIANCE 复检

---

## 3. 占位 PT 协议（34 个，原文仅列名）

- 原文：40 个 PT 协议中 34 个为占位（「详情待补充」），仅 6 个（注：本文档 §2 按 01 文档列为 7 个）旗舰协议有完整 constraints/guards（红旗 B17）。
- **占位协议名单原文未逐条列出**【待补：从基准 HTML 的 PT 注册表导出名单】。
- **补齐优先级**（Q70-72 定；Q73 合并后重划）：先补 **V1** 主链（段 1→6→10→11，18 个 P0 协议，见 12 §2）用到的协议；段 12 生成类与段 7/8 AI Skill 随 V2 补，余随阶段补。

---

## 4. Skill 注册表与编排（展示口径 D3.10 + 权威口径 A4）

### 4.1 Skill 注册表（D3.10，50+ Skill）
| 注册表字段（原文 11 字段表述） | 说明 |
|---|---|
| skill_id / layer | 标识与层级 |
| input-output_schema | 输入输出 Schema |
| 依赖知识 | 依赖的知识库/记忆 |
| 模型档位 | 模型档位选择 |
| 阈值 / 失败策略 / 审核规则 / 成本上限 / 版本 | 治理字段 |

### 4.2 Skill Orchestrator（编排器，D3.10）
- 触发判断 / 串并行编排 / 人工闸门 / 失败处理 / 成本控制 / 结果路由
- **选型定稿（14 §2.2，2026-09-13）**：一期**自研注册表驱动编排器最小集**——只做注册表驱动 + 顺序/并行 + 人工 Gate 插槽；WF/Skill/PT 均为 YAML 数据驱动（落位 15 `runtime/`），编排协议与框架解耦；复杂 DAG 能力二期评估，失控时可迁 LangGraph。
- **实现状态（2026-09-14，M10 切片 e，Q76；WF-02 替换切片 Q78）**：注册表加载器 + WF-04 YAML（顺序 Skill + skill7/PWC 双 Gate 插槽）+ 三个 WF-04 Skill 定义已落；SkillRunLog（`skill_runs`，append-only）与通用候选（`skill_candidates`）通道可用，投递/裁决 API 见 05 §1.4 切片 e。顺序演绎经"投递→候选→适配器"接通；并行执行与复杂串排二期。
- **实现状态（2026-09-14，WF-02 字段池占位替换切片 1/3，Q78）**：`runtime/workflows/WF-02.yaml`（FIELDPOOL-PLAN→DIM-SOURCE→DIM-MERGE 顺序 Skill + skill7/fieldpool 双 Gate 插槽，failure_policy 记 Q9 mark_needs_detail / Q10 flag_only）与 `runtime/skills/{FIELDPOOL-PLAN,DIM-SOURCE,DIM-MERGE}/skill.yaml` 已登记；接缝经负责人拍板记 Q78——DIM-MERGE 为候选产出者，**整方案单候选** `target_type=field_plan`（payload 为去 actor 的 PlanSubmitRequest 形态；Q79 起单候选约束改由步骤 `single_candidate: true` 声明驱动），投递校验按 WF 步骤 `candidate_target` 泛化（非产出步骤拒收、target 不符拒收、field_plan 限 1 条），confirmed/modified 经适配器复用 `fieldpool.submit_plan` 落 pending_gate 再过既有 WF-02 HumanGate（Q8 启用路由/PT-FP-PLAN/Q9/Q10/Q12/G2 候选一项不绕）；rejected→archived 不落池；适配器 GateNotAllowed 等失败回滚候选留 pending_review。FIELDPOOL-PLAN、DIM-SOURCE 不带 candidate_target。配套 eval 回归见 15 §2.5 `eval/`（DIM-MERGE 12+3 案）。
- **实现状态（2026-09-14，WF-01 冷启动识别占位替换切片 2/3，Q79；范围仅 C1 识别，C7 Layer4 留挂账→Q81 销账）**：`runtime/workflows/WF-01.yaml`（PARSE→UNDERSTAND→CAT-RECOG→TYPE-MATCH→MISSING-INFO→RISK-TAG 顺序 Skill；CAT-RECOG 后单个 skill7 Gate 插槽 role=**operations**；failure_policy 记 Q1 low→cold_start / mid→ops_assist）与六张 Skill YAML 已登记。接缝经负责人拍板记 Q79：**(1) 范围**=CAT-RECOG 为候选产出者，识别整结果单候选 `target_type=c1_recognition`（payload=去 actor 的 C1RecognitionRequest：signals/candidates/industry?/category_pending_id?），C7 Layer4 新字段提案通道随后续切片；**(2) Q1 接缝**=平台铁律 AI 只产候选，统一过一次人工 confirm（skill7 Gate="AI 产出准入"裁决），准入后 Q1 三分支机械逻辑一字不改——direct_approve 照常 auto_confirm 无第二道确认、ops_assist 照出 72h OpsTodo、cold_start 照要 category_pending_id；**(3) Gate 角色**=operations（与 ops-decision/ops_assist 处理人一致，Q3/Q4）；**(4) 锚点**=段2 先于 ProductSpace，skill_runs/skill_candidates 加 nullable `intake_id`，skill_candidates.product_space_id 改 nullable（迁移 0013），投递 PS/intake 锚点二选一且按 WF 归属校验。通道侧：单候选约束泛化为步骤声明 `single_candidate`（WF-02 DIM-MERGE 同步改声明），适配器 `c1_recognition` 复用既有 `modeling.submit_recognition`（异常口径 IntakeNotFound 404 / RecognitionNotAllowed 409 / ConfigError·InvalidDecision 422，失败回滚候选留 pending_review）。配套 eval：CAT-RECOG 打 c1 纯函数 weighted_conf/decide_branch，回归矩阵 11 案 + Golden 3 案。
- **实现状态（2026-09-14，WF-03 字段下原子占位替换切片 3/3，Q80）**：`runtime/workflows/WF-03.yaml`（ATOM-EXPAND→ATOM-CANON→ATOM-AFFINITY→CONFLICT-PRECHECK 顺序四步；CONFLICT-PRECHECK 后单个 skill7 Gate 插槽 role=**product_reviewer**，即本文 line 172 原子审核=产品审核员；failure_policy 记 Q15 target_reached→stop_expand / 空证据→pending_evidence）与四张 Skill YAML 已登记。接缝经负责人拍板记 Q80：**(1) 粒度**=整批一条候选 `target_type=atom_batch`、步骤声明 `single_candidate: true`，payload=去 actor 的 BatchSubmitRequest 形态（items[{content,dimension_id,ai_risk,affinity?,evidence?,fact_type?,cluster_id?}] + 可选 batch_size），通道只接 AI 拓展批次，confirmed/modified 经适配器复用既有 `atom.submit_batch`（强制 source=ai，Q14/Q15/同批去重/维度属本池/line 11189/Q17/line 840/PT-ATOM-EXP 空证据一项不绕），入库后每条 AtomCandidate 的 approveAtomGuard/Q70/Q18/Q19/Q20 原样保留——skill7 Gate 仅 AI 产出准入，不替代逐条 Gate；rejected→archived 批次不入库；**(2) Gate 角色**=product_reviewer（投递仍归 operations）；**(3) 产出步骤**=末步 CONFLICT-PRECHECK（投递即四步 AI 处理全部完成后的最终成型批次），ATOM-EXPAND/ATOM-CANON/ATOM-AFFINITY 登记普通步骤不带 candidate_target；**(4) 锚点**=product_space_id（复用 Q79-4 PS 分支，无新迁移）。通道侧：投递/裁决 payload 按 BatchSubmitRequest 契约预校验（剥离 source/actor），适配器 `atom_batch` 异常口径 ProductSpaceNotFound·PoolNotFound 404 / PoolNotApproved·TargetReached·FactAtomConflict 409 / InvalidBatch 422，失败回滚候选留 pending_review（Q15 达标 409 时批次未入库、候选留待重决）。配套 eval：四 Skill 全覆盖（default_batch_size/target_reached/normalize_text/is_low_affinity/pick_cluster_keeper/grade_risk/conflicts_for 七 target），回归矩阵 24 案 + Golden 7 案，覆盖 Q14/Q15/Q16/Q17/Q19 与 line 840；真 LLM 拓展生成本体挂 Q67。
- **实现状态（2026-09-14，WF-01 C7 Layer4 新字段提案占位切片，Q81，Q79-1 挂账销账）**：`runtime/workflows/WF-01.yaml` 增第二个候选产出步骤 TYPE-MATCH（`candidate_target: c7_layer4, single_candidate: true`）与第二道 skill7 Gate 插槽（CAT-RECOG 后、TYPE-MATCH 后各一，role 均=**operations**；MISSING-INFO 仍非产出步骤，其缺字段清单驱动 pending_params），TYPE-MATCH/skill.yaml 输出改为整 C7 解析请求、review_rule 记两道 Gate 分工。接缝经负责人拍板记 Q81：**(1) 产出步骤**=TYPE-MATCH（其 skill.yaml 本自陈 failure_policy=fallback_to_c7），同一 WF 多产出者由 registry 按"WF+步骤"校验，投递逐步骤独立；**(2) 候选形态**=整 C7 解析请求单候选（payload=去 actor 的 C7ResolveRequest：category_id/required_fids/l4_proposals[]），confirmed/modified 经适配器复用既有 `modeling.resolve_c7`，L1 缓存/L2 approved 兄弟/Q6 覆盖率 0.6 地板/L4 候选与 Q68 fid:'-' 闸一项不绕——实际落 L1/2/3 时 l4_proposals 自然不生效（与 Q15 target_reached 同口径），落 L4 才写 g2_field_candidates(pending_gate)；**(3) Gate 角色**=operations（与 Q79-3 同档），与段3 Q13 dictionary_admin 深度审核/转正**不合并**：准入裁"AI 产出能否进解析"、转正裁"候选字段能否进 G2 字典"，两道人工 Gate 先后独立（Q66 AI 无角色）；**(4) eval 范围**=只打 c7 确定性纯函数（coverage/pick_sibling/layer3_coverage_floor），Q68 拒绝与错误分支留后端集成测试，L4 真 LLM 新字段生成体原挂 Q67、已随 Q84 接通（见下）。通道侧：锚点复用 Q79-4 intake 分支（无新迁移），适配器异常口径 IntakeNotFound·CategoryNotFound 404 / IllegalFid·InvalidDecision 422、applied_refs=[C7Run.run_id]，失败回滚候选留 pending_review；resolve_c7 Layer4 同步改同名 c7_layer4 全局候选复用（与 wf02_dim_source 同口径）。配套 eval：TYPE-MATCH 回归矩阵 14 案 + Golden 3 案（Q6/line 708/Q68 refs，全合成数据）。
- **实现状态（2026-09-15，Q67/Q84 C7 Layer4 TYPE-MATCH 真 LLM 第三站）**：接缝四项经负责人拍板记 Q84（02 C1.28）：①仅显式业务端点 operations 触发（`POST /api/intakes/{id}/c7/llm-resolve`，body=`{category_id, required_fids, actor}`），不与 CAT-RECOG llm-invoke 自动串联（链式/DAG 二期）；②WF-01 TYPE-MATCH 步骤已声明 `single_candidate: true`，整 C7 解析请求单候选（payload=去 actor 的 C7ResolveRequest）原样复用 Q81 适配器 resolve_c7；模型回显 category_id/required_fids 必须与触发输入一致（集合不漂移，顺序按触发侧），空 l4_proposals 合法（裁决后自然落 L3）；③Prompt 机读变量白名单有界（目标类目/必填 fid/L1 approved 模板/L2 approved 兄弟计数/L3 G2 active 清单+现状覆盖率+0.6 floor），前置闸=intake 存在 + 状态 ai_recognizing + 类目存在且 active + required_fids 过 c7.validate_fids（Q68，调模型前 422），synthetic 替身只按覆盖率缺口造结构提案**不打置信分**，真模型回带的 confidence/score/fid/status/source_route 编排层一律丢弃（只透传 field_name/非空 definition，G2FieldCandidate.confidence 落 NULL；source_route 枚举原文未给，v0.1 不接模型值），Q13 dictionary_admin 转正 Gate 不绕；④预算/失败语义沿用 Q82/Q83（409 硬停/缺 Key 422/坏输出 502/disabled 无 fallback 409），系统 Actor `system:llm-gateway` roles=[]、source=llm_auto、成本四列照记。迁移 0016 为纯种子（TYPE-MATCH→synthetic 路由 + Prompt v0.1），无 schema 变更，PG16 up/downgrade-1/up 实测；eval 不新增（synthetic 构造器是夹具不是业务函数）。
- **实现状态（2026-09-15，Q67/Q85 WF-02 DIM-MERGE 字段池方案真 LLM 第四站）**：接缝四项经负责人拍板记 Q85（02 C1.29）：①场景键=**DIM-MERGE**（WF-02 唯一声明 field_plan 产出步骤；FIELDPOOL-PLAN/DIM-SOURCE 七路外部采集连接器属 V2，一次调用覆盖框架+采集+合并整结果），仅显式业务端点 operations 触发（`POST /api/product-spaces/{id}/field-pools/llm-plan`，body=`{target_atom_min?, target_atom_max?, actor}`，缺省 Q15 旋钮 15/30；链式/DAG 二期）；②DIM-MERGE 步骤已声明 `single_candidate: true`，整方案单候选（payload=去 actor 的 PlanSubmitRequest）原样复用 Q78 适配器 apply_field_plan→submit_plan，target_atom_min/max 必须原样回传（漂移 502）；<3 维/缺 product_attribute/敏感缺 risk_control 属业务违规照常落非合规 pending_gate 池，Gate 不可 approve；③Prompt 机读变量白名单有界（profile_snapshot 资料行/敏感标+行业标签/启用来源路由/active G2 清单/dim 3-8/目标原子 15-30），前置闸=PS 404 + 池态（无池或 rejected，否则 409，与 submit_plan 同口径）+ min≤max；结构白名单：role/启用 route/active fid（Q68 '-' 与幻觉 fid 502）/批内去重/非空且 ≤dim_max；**证据红线 line 14081 在生成边界强制执行**（source_ref 空白即 502，只许引用有界输入 g2:/product_profile:/industry_tag:，禁止编造）；**confidence 口径与 Q83/Q84 不同——它是 PT-FP-PLAN 契约内 AI 字段（Q9 细看/Q12 Top8 依赖），0..1 校验后透传，缺失/越界 502**，synthetic 固定 0.9 不模拟分布，similarity/related_fid 可选透传（Q10 仅标记），未知键剥离；④预算/失败语义沿用前三站（409 硬停/缺 Key 422/坏输出 502/disabled 无 fallback 409），系统 Actor roles=[]、source=llm_auto、成本四列照记。迁移 0017 为纯种子（DIM-MERGE→synthetic 路由 + Prompt v0.1），无 schema 变更，PG16 up/downgrade-1/up 实测；eval 不新增（synthetic 构造器是夹具不是业务函数）。
- **实现状态（2026-09-15，Q67/Q86 WF-03 原子批量补池真 LLM 第五站/末站：chat + embedding 双调用）**：接缝四项经负责人拍板记 Q86（02 C1.30）：①触发=`POST /api/product-spaces/{id}/atom-batches/llm-expand`（operations，batch_size 缺省 Q14 敏感 20/非敏感 50），花 token 前预闸 PS/字段池 404、gate≠approved 409、Q15 已通过+冻结原子数 ≥ target_atom_max → 409 TargetReached（仅约束 AI 批次），不自动串链；②**一次触发两次调用、一个 atom_batch 候选**：CONFLICT-PRECHECK（WF-03 唯一 `candidate_target: atom_batch, single_candidate: true` 步骤，Prompt 挂此 skill）chat 产整批候选，ATOM-AFFINITY 为同 WF 的 embedding 步骤——**首个 capability=embedding 场景：不挂 Prompt、不产候选**，网关 `embed(scene, texts)` 路由能力不符 422；只落 1 条 SkillRun（skill_id=CONFLICT-PRECHECK，model_id=chat 模型，两次 input tokens/cost 求和、output 仅 chat，embedding 模型身份记 run.input 可审计）；候选原样复用 Q80 apply_atom_batch→submit_batch（强制 source=ai，Q14/Q15/批内去重/line 11189/Q17/line 840/Q18 一项不绕），1536 维向量以机读 `_embeddings` 键随候选 payload 带外传递（投递校验与适配器双侧 pop），approve 复制向量到 product_atom_instances；③Q16 相似度本体 V1：PG `vector(1536)`（迁移 0018 建 pgvector 扩展，SQLite 端 float32 LargeBinary TypeDecorator），进程内纯 Python 余弦 max 取同维 approved/frozen 有向量原子（无基 None，Q16 低亲和 0.5 只标不淘汰），批内同维并查集成簇线 `atom.cluster_line=0.9`（借 Q10 同义线，原文未给【待补】，进配置中心），KNN 索引/`<=>` 千万级切换按 14 §2.3 后置；④输出白名单 `{batch_size 回传, items:[{content, dimension_id, ai_risk, evidence?, fact_type?}]}`，模型自报 affinity/cluster_id/score 一律剥离本地重算，**ai_risk 属 PT-ATOM-EXP/Q17 契约内 AI 字段枚举校验后透传**（词表只升不降仍在 submit_batch），结构脏数据/embedding 行数·维度不符投递前 502 不留痕，业务违规不 502；预算/失败沿用 Q82–Q85（409/422/502/disabled 已注册 fallback），系统 Actor `system:llm-gateway` roles=[]。**Q86 后五个真 LLM 站点全部接通，Q67 站点 backlog 闭合**；restock_auto 仍挂 M8 worker。eval 不新增（synthetic chat/embedding 构造器均为夹具）。
- **实现状态（2026-09-14，Q67/Q83 PWC-BUILDER 真 LLM 第二站）**：接缝四项经负责人拍板记 Q83（02 C1.27）：①仅显式业务端点 operations 触发（`POST /api/product-spaces/{id}/pwc/llm-build`），Q71 restock_auto 补货请求不自动消费（自动触发随 M8 worker）；②WF-04 PWC-BUILDER 步骤不声明 `single_candidate`，一次调用产整批、每条组合各投一条 `target_type=pwc_combo` 候选（payload=`{"combos":[{atom_ids,goals}]}`），输出超 Q21 批 50 拒、同原子集重复由编排层机械去重（保序），适配器逐候选原样跑 M5 漏斗；③Prompt 机读变量白名单有界（approved 原子/库容/ready 数/active goals/目标平台），前置闸=字段池 approved + approved 原子跨 ≥2 维（不足不调模型），synthetic 替身只按维度确定性配对**不造分**，真模型回带的 logic/fit/weight 编排层一律丢弃，Q22b 子分缺失 → score incomplete → 人工 Gate；④预算/失败语义沿用 Q82（409 硬停/缺 Key 422/坏输出 502/disabled 无 fallback 409），系统 Actor `system:llm-gateway` roles=[]、source=llm_auto、成本四列照记。迁移 0015 为纯种子（PWC-BUILDER→synthetic 路由 + Prompt v0.1），无 schema 变更，PG16 up/downgrade-1/up 实测；eval 不新增（synthetic 构造器是夹具不是业务函数）。
- **实现状态（2026-09-14，Q67/Q82 模型网关与 CAT-RECOG 真 LLM 试点）**：接缝四项经负责人拍板记 Q82（02 C1.26）：①范围=模型底座+CAT-RECOG 单站试点，其余四站点后续切片复用；②进程内同步调用、系统机器 Actor（roles=[]，Q66）复用 skill7 投递通道，人工 Gate 不改；③outbound Key DB 加密 + env 主密钥，入站一 Agent 一 Key 随 Q60；④Prompt 模板 DB 版本化（v0.1 起步、append-only、platform_admin + writeAudit，仓库只携迁移种子）。与本协议的关系：上表"模型档位"字段 V1 **留空不启用**——模型选择不由 skill.yaml 档位决定，而由 `ai_scene_routes` 按 **场景路由键 = skill_id** 解析（如 CAT-RECOG 场景）；日预算按模型全局硬停、不静默切供应商，fallback V1 仅注册态+人工（disabled 才走）；Prompt 不走 15 §1 规划的 `prompt/*.md` 文件，落 §4.4 的 DB 版本化路径（见该节补登）。skill 调用日志成本侧补 model_id/input_cost/output_cost/currency_code 四列（迁移 0014），append-only 语义不变。

### 4.3 Skill 调用日志（M6，D3.10 + 段10）
- 每次输入/输出/成本/置信度/失败/人工修改记录
- **历史 SkillRunLog 不可 mutate**（即便回滚，PT-COMPLIANCE-V2.0）

### 4.4 Prompt 模板库（D3.10 + A4 治理）
- 每个 Skill 的 Prompt 模板 · 版本管理 · A/B 测试
- **Prompt 治理（A4）**：只读 + 编辑必走 ChangeProposal + AI 不可自动 mutate；保存自动版本 +0.1、history 追加
- Prompt 修改属 RBAC 红线操作（必须对应角色 + 人工 Gate）
- **实现状态（2026-09-14，Q82）**：Prompt 模板库已按 DB 版本化落地（`skill_prompts`/`skill_prompt_versions` 两表，迁移 0014）：v0.1 起步、再发布自动 v0.N+1，版本行 append-only 不改写，发布角色 platform_admin 且写 writeAudit，仓库只携 CAT-RECOG/PWC-BUILDER/TYPE-MATCH/DIM-MERGE/CONFLICT-PRECHECK v0.1 迁移种子（Q83 起两站、Q84 起三站、Q85 起四站、Q86 起五站；ATOM-AFFINITY 为 embedding 能力场景不挂 Prompt，无版本行）；A/B 测试 V1 不做（原文 A/B 能力后置）。运行时不用 15 §1 规划的 `runtime/skills/<id>/prompt/*.md` 文件（该规划由 Q82 修订）。

### 4.5 Multi-model Router（D3.10，V2）
- 轻模型/强模型/视觉模型/规则引擎自动路由
- Q67：场景→默认模型路由配置页（类目识别/原子拓展/内容生成/合规复检等各场景默认模型，运营可改不动代码）
- **实现状态（2026-09-14，Q82）**：场景路由 V1 已最小落地（`ai_scene_routes`，场景键=skill_id，operations|platform_admin 可改 + writeAudit），Q82–Q86 五个站点已全部真调（CAT-RECOG/PWC-BUILDER/TYPE-MATCH/DIM-MERGE 为 chat，Q86 起 CONFLICT-PRECHECK chat + ATOM-AFFINITY embedding 双能力，路由按 ai_models.capability 解析，能力不符 422）；自动按轻/强/视觉路由仍属 V2（本节标题维持 V2，不静默升级）。V1 不做自动故障转移：模型 disabled 才走已注册 fallback，日预算耗尽全局硬停 409，不静默切换供应商。

---

## 5. Agent 注册表（权威口径 A4 + Q66）

| Agent | 职责 | 边界（max_turns / max_tokens） | 来源 |
|---|---|---|---|
| AG-REVIEW-COPILOT | 审核辅助（建议不批准） | 10 轮 / 8000 token | line 2115 |
| AG-PM-AUDIT | 审计辅助 | 6 / 6000 | line 2115 |
| AG-SUPPORT | 支持（上线前需脱敏审核） | 20 / 4000 | line 2115 |

**Agent 三条边界（line 2115）**：Agent 不能批正式对象；必须有 max_turns + max_tokens + emergency_stop。
**Q66（红旗 A11 裁决）**：第一期 AI agent 一律不授予任何 owner/审批角色；internal_compliance / internal_finance 角色只配真人；USR-CO-AI-* 账号降级为"辅助建议"定位；涉资金与合规窗口必须人类持有。

---

## 6. 展示口径 Skill 清单（03-A~E 体系，仅展示参考，规格以权威口径为准）

| 层 | Skill 数 | Skill 名单 | 来源 |
|---|---|---|---|
| 平台层 | 11 | Platform Source Parse / Atom Decomposition / Canonicalizer / Conflict Precheck / Static Rule Extraction / Compatibility Builder / Dynamic Signal Collector / Account Stage Eval / Slot Retrieval / Condition Package Builder / Scoring | D3.2 |
| 策略层 | 5 | Content Goal Planning / Audience Stage Match / Angle Selection / Expression Strength / CTA Strategy | D3.3 |
| 结构层 | 5 | Structure Template Match / Hook-Opening-Middle / CTA Position / Structure Compatibility / Scoring | D3.4 |
| 表达层 | 4 | Tone Style Match / Language Localization / Explicit-Implicit Expression / Softening Expression | D3.4 |
| 合规层 | 4 | Compliance Screening / Forbidden Expression Detection / Claim Downgrade / Cleaning Rewrite | D3.4 |
| 反馈层 | 5 | Usage Memory Skill / Performance Collector / Weight Learning / Cooldown Decision / Knowledge Update Proposal | D6 |
| AI 演化建议 | 6 | 缺失检测 / 冗余检测 / 平衡度评估 / 亲和度学习 / 演化建议 / 趋势推荐 | D3.6 |

---

## 7. 人工 Gate 点位总览（横切，全链审核）

| Gate 类型 | 所在段/WF | 审核角色 | 批量/单条 | 来源 |
|---|---|---|---|---|
| 录入审核 | 段1 | 运营 | 【待补】 | A3 段1 |
| 字段池规划 Gate | 段3 / WF-02 | 产品审核员（展示口径） | 0.85 细看线 | PT-FP-PLAN / Q9 |
| 原子审核（approveAtomGuard） | 段4 / WF-03 | 产品审核员（展示口径） | high/critical 单条，其余可批量（Q70） | line 2633 / Q70 |
| PWS 冻结 | 段6 / WF-05 | BO-07 | 单条（红线） | line 7674 |
| 平台适配候选 | 段7 / WF-06 | 平台审核员（展示口径） | AI 输出一律 pending_review | PT-PLATFORM-ADAPTER |
| PCP 权重重算 | 段8 | 运营 | 候选+对照单 | Q41 |
| 三包（D0） | 段9 / WF-07 | 内容审核员（展示口径） | 0.85 细看线（复用 Q9） | Q47 |
| 法审（law_review） | 段10/11 | internal_compliance 角色 | 单条 | Q49 |
| FCW 组装 | 段11 / WF-09 | 无人审（全自动发证，Q55） | 7 项 Guard 机械核验 | Q55 |
| 内容复检 | 段12 / WF-10 | 客户审阅 + 运营 | 复检 4 项 | Q59 |
| KUP 审批 | 段13 | 运营（单产品）/ 平台管理员（共享层） | 证据三关 | Q63/Q64 |
| 通用审核台（Q70） | 全链 | 各角色 | 置信 >0.85 批量通过，低于线逐条 | Q70 |

---

> **信息保全**：本文档所有 WF/Skill/PT/Agent/Gate 条目来自 v3 Part A（A1/A3/A4）与 Part D（D3/D6）原文；34 个占位协议名单原文未列出，已标注【待补】，未编造协议内容。展示口径 Skill 与权威口径 Skill 的对应映射原文未给出【待补】。
