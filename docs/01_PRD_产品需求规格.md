# Loom · 产品需求规格（PRD）

> **本文档来源**：`../Loom_核心业务主链梳理_v3.md` **Part A（A1–A7，即"稳定规格层"）全量切分**，忠实保留原文，未增删业务事实。
> **文档定位**：产品需求规格（权威规格层）。以 **13 段链（CHAIN_13）** 为唯一权威口径；与 03-A~E 展示口径（见 09 全景文档）并存不混用，冲突以本文档为准。
> **基准文件**：`Docs/Loom_后台_V6.0-需求说明（不是原型).html`（约 2.7 万行交互原型，业务语义内嵌于 `DATA` / `STATE` / `CHAIN_13` / Workflow·Skill·Prompt 注册表等 JS 结构，正文标注行号可回溯）。
> **参考标记规则**：凡因 HTML 不明确而参考了 `Docs/业务方-核心业务/` 的内容，一律以 **【业务方参考：文件名】** 显式标记；未标记处均与业务方文档无关（全文实际参考业务方处共 3 处，汇总见 03 文档 §B2）。
> **配套文档**：决策记录（Q1–Q72）见 02；技术红旗见 03；契约层（数据模型/API/状态机/Skill 协议）见 04–06；路线图与任务包见 08。

---

## 1. 主链总览：13 段链（CHAIN_13，line 2410；导航映射 CHAIN_NAV，line 2426）

**业务定义（line 1762）**：白名单 = 在（产品 + 目的 + 平台/发布位 + 账号/风险）上下文下，各层原子相撞出的可用条件包。
**final 定义（line 2745）**：final_id = 6 层快照相加 —— 产品 PWS（私域原子）+ 平台 PCP + 策略 CSP + 结构 CSTP + 表达 CEP + 合规 CCR（5 类通用原子），**唯一出口 E1.1 publishFCW**。

| 段 | 名称 | 层 | 后台模块 | Workflow |
|---|---|---|---|---|
| 1 | 产品录入 | product | product-intake | WF-01（6 Skill） |
| 2 | 冷启动建模（C1 识别） | product | product-modeling | 并入 WF-01 |
| 3 | 字段池规划（AI Plan + Gate） | product | product-dimension | WF-02（3） |
| 4 | 字段下原子（AI 候选 + Gate） | product | product-atom | WF-03（4） |
| 5 | PWC 候选组合（同 PS 跨字段相撞） | product | product-condition | WF-04（3） |
| 6 | PWS 冻结（owner=BO-07） | product | whitelist-center | WF-05（1） |
| 7 | 平台静/动态适配（C7 Compat） | platform | platform-adaptation | WF-06（注册 6 条，官方注 5，⚠不一致） |
| 8 | 平台条件包 PCP | platform | platform-dynamic | 无独立 WF（由 WF-06 覆盖） |
| 9 | 策略/结构/表达包（D0 四包之三） | decision | layer-strategy | WF-07（4） |
| 10 | 合规清洗（D5 Cleaning → CCR） | decision | compliance-center | WF-08（3） |
| 11 | final_id 组装（E1 publishFCW） | final | final-whitelist | WF-09（2） |
| 12 | 内容生成（E4 只读消费） | content | content-manage | WF-10（4） |
| 13 | 反馈回流 + KUP 知识进化 | feedback | feedback-loop | WF-11（3）+ WF-12（2） |

**三端（PORTS, line 2431）**：用户前端（客户录入/内容中心）/ 管理后端（13 模块）/ 系统后台 API（内容生成系统消费白名单）。读者永远不接触系统，只作为效果数据来源存在，无任何读者侧实体。

## 2. 数据流与硬闸

```
G1类目树 + G2通用字段池（跨类目共享字典）
  │
[1]录入(14态状态机) → [2]C1五信号识别(阈值分档) → [3]FieldPool规划+Gate
  → [4]原子拓展+逐条Gate(approveAtomGuard 10项) → [5]PWC跨字段相撞+校验+评分
  → [6]PWS冻结(pwsReadiness 5项) ══下游只能消费 frozen PWS══
  → [7]平台适配(allow/downgrade/block/pending_review) → [8]PCP 17字段权重池(Σ≤1.0)
  → [9]CSP/CSTP/CEP(通用layerSpaces) → [10]CCR(block_required一票否决)
  → [11]FCW组装(5项Guard全过才生成final_id) ══readonly══ [12]内容生成+合规复检
  → 客户审阅发布 → [13]catFeedback效果回流 → KUP提案 → 人工Gate → 回写G2/原子weight/类目模板
                                                    （唯一反向边，回到段3/4/8）
```

## 3. 各段规格（功能 / 输入输出 / 实体 / 规则）

### 段 1 · 产品录入（WF-01, B1 Gate）
- 6 Skill 串行：PARSE 解析 → UNDERSTAND 理解 → CAT-RECOG 类目识别 → TYPE-MATCH 类型/模板匹配 → MISSING-INFO 缺失检测 → RISK-TAG 风险标签（line 900-905）。
- 输入：产品名/品牌/简介/卖点/SEO/主图/包装图/目标市场/语言/渠道/受众/内容用途（G2 中 `cat:'common'` 的 18 个通用字段，line 682-698）。
- 实体：`ProductIntakeApplication`（intakes）→ 通过后生成 `ProductSpace`（PS，一品一空间）。
- **状态机 productIntake14（line 1454，14 态）**：草稿→AI识别中→待确认→待补充参数→待确认额度→已提交→审核中→需补充资料→已通过→建模中→已入库→入库失败→驳回→已归档。
  **📌 定稿修订（§C1 Q5）**：新增第 15 态"类目创建中"（冷启动支线停靠位），升级为 productIntake15；"待确认"的类目确认动作改由运营执行（Q3）。
- 产品生命周期判定优先级（line 1655）：`frozen > stale > cold > modeling > active`。

### 段 2 · 冷启动建模（C1 识别）
- **五信号加权**（c1Records.signals）：name≈0.33 / brief≈0.22 / 卖点≈0.12 / 主图≈0.13 / 包装图≈0.06-0.10，conf=Σ。
- **行业置信阈值（STATE.c1_thresholds, line 1834，可配）**：medical 0.90 / electronics 0.80 / general 0.85。
- 三分支：conf≥行业阈值→`direct_approve`；中置信（信号矛盾）→`customer_assist`（await_customer）；低置信→`cold_start`（推 B2 生成候选类目）。
- ⚠ 冷启动另有两处阈值：`hit_rate<0.6`（line 635）与试用客户 `<0.4`（line 646）——conf 与 hit_rate 是否同一指标、0.6 还是 0.4，文档内不一致（红旗 §B1.7）。
- **📌 定稿修订（详见 §C1.1，临时结论）**：①统一用 conf 单指标，hit_rate 废弃；三分支 = conf≥行业阈值 / [0.6,阈值) 或 Top1-Top2 差<0.1 / <0.6（Q1/Q3）。②信号权重做成配置表，小数、和必须=1 否则拒绝保存；第一期只启用文本三信号，图像后置（Q2）。③中置信由**运营**选（ops_assist），客户无感知；运营 72h 未处理升级，全否转 cold_start（Q3/Q4）。④冷启动期间申请单进新增状态"类目创建中"（Q5）。⑤行业阈值表做成后台 CRUD，含不可删默认档 + 审计（Q7）。
- G1 类目状态机：`active/draft/review/deprecated/archived/merged`（merged 带 merged_into 永久重定向）；每叶子挂 template（field_list 引用 G2 fid）。
- **C7 模板四层兜底（c7Runs, line 708）**：Layer1 缓存命中（0 token）→ Layer2 相邻兄弟继承（~480）→ Layer3 从 G2 挑选（~1480，禁止发明新字段）→ Layer4 大模型全新生成（~5100，新字段进 G2 候选，必须深度审核）。

### 段 3 · 字段池规划（WF-02）
- Skill：FIELDPOOL-PLAN → DIM-SOURCE（7 路并行维度来源分析）→ DIM-MERGE（去重合并校验）。
- **PT-FP-PLAN-V2.0 约束（line 2001）**：必须含 ≥1 个 product_attribute 角色维度；必须含 ≥1 个 risk_control 候选（合规预筛）；**维度数 3-8**；不直接生成原子；输出必经 WF-02 HumanGate；**confidence<0.85 触发 HumanGate 必审**。
- 实体：`FieldPool`（带 gate: approved/pending_gate）、`g2Fields`（通用字段池，43+ 字段，usage 计数、同义词 syn[]）、`g2FieldCandidates`（带 dup 同义词去重）。
- 维度依据红线（line 14133/14081）：禁止凭空拆维度，每维度必须有依据（用户输入/灵感库/维度生成规则）且标明来源；灵感库（product-inspiration，MVP）= 通用 + 产品专属两层，是拆维度的法定来源之一。
- **📌 定稿修订（详见 §C1.2，临时结论）**：①维度来源做成运营可配置路由表，默认 6 路（用户输入/通用灵感库/产品专属灵感库/类目模板/G2 高频字段/合规风险面），上线后运营增删（Q8）。②0.85 细看线配置化；全局魔法数字一律配置化，清单见 §C2（Q9）。③同义合并：相似度 ≥0.9 标疑似重复、人工终裁（Q10）。④risk_control 仅敏感行业强制（Q11）。⑤维度 >8 留 Top8 余者入备选档，<3 转人工（Q12）。⑥新字段转正需字典管理员权限（Q13）。

### 段 4 · 字段下原子（WF-03）
- Skill：ATOM-EXPAND（批次 20/50）→ ATOM-CANON 归一化 → ATOM-AFFINITY 亲和度 → CONFLICT-PRECHECK 冲突预检。
- **PT-ATOM-EXP-V1.3 约束（line 2013）**：仅产 candidate 不直接写 ProductAtomInstance；同批次去重；同维度互斥优先禁同义词簇；risk=high/critical 必走 HumanGate（critical 单条审，不入批量 Gate）；evidence 必填（空则降级 pending_evidence）；**产品事实原子（容量/成分/浓度/疣类型/品牌）严禁跨产品复用，引用数恒=1**（line 11189：通用人类表达原子可作模板被多产品引用后各自派生独立实例）。
- **状态机 atom8（line 1454）**：草稿→待审核→已通过→已冻结→已废弃→已驳回→合规暂停→归档。
- **approveAtomGuard 10 项（line 2633）**：属当前 PS / 属选中 FieldPool / FieldPool gate=approved / status≠rejected / gate 可批 / 无 blocked conflict / approved_id 为空 / evidence 存在 / high-critical 单条审批 / 变更前 writeAudit。
- AtomConflict（line 840）：类型 `disabled_expression(critical→驳回+合规审计)` / `high_risk_single_review(high→单条 HumanGate)` / `evidence_required(high→补证据或驳回)`；状态 blocked/pending_gate。
- **📌 定稿修订（详见 §C1.3，临时结论）**：①批次 20/50 配置化，敏感行业默认 20（Q14）。②FieldPool 加"目标原子数"（默认 15-30），达标停拓（Q15）。③亲和度无硬淘汰线，仅排序 + <0.5 提醒（Q16）。④risk 定级双轨：词表强制、AI 兜底、只升不降，词表后台 CRUD（Q17）。⑤pending_evidence：AI 自动补一轮 → 运营待办 → 7 天超时自动驳回可复活（Q18）。⑥同义簇留亲和度最高者，余者为 alias 不删（Q19）。⑦冻结=运营、合规暂停=合规角色、废弃复活重走审核（Q20）。

### 段 5 · PWC 候选组合（WF-04）
- Skill：PWC-BUILDER（同 PS 跨字段相撞构建）→ COMBO-VALIDATE 组合校验 → PWC-SCORING 组合评分（**品类乘数**，line 918——HTML 只有此一句，无具体公式）。
- 实体 PWC/条件包（conditionPackages, line 1780）：`combo[{fp,atom}] / weight / goals[] / strategy[] / structure[] / expression[] / compliance{ban,downgrade,gate} / score / source(ai/manual/hybrid) / usage / gate_status(pending|blocked|approved)`。
- 状态枚举（line 1780-1806）：`待用/已用/爆款/冷却/待Gate/待入库/候选/阻断/归档`。
- **📌 定稿修订（详见 §C1.4，临时结论）**：①组合生成采用"预筛→检测(可插拔:合规/逻辑/搭配)→评分→限量"漏斗【业务方参考已批准并映射】，全环节配置化（Q21）。②评分 = (合理性 0.6 + 多样性 0.4) × 品类乘数，历史项一期不进（Q22）。③重合占比 ≥0.8 疑似重复（Q23）。④已用 = 同平台+账号+发布位仅 1 次、全平台用尽转已用；冷却 7 天 3 次/回 14 天；高复用 ≥N 次打标；爆款一期手工、自动标准留段 13；**PWC 严禁跨产品/跨客户复用，共享只在知识层**（类目/模板/灵感库）（Q24）。⑤goals 用 contentGoals 字典（CRUD），与录入"内容用途"同源取交集（Q25）。⑥手拼跳预筛不豁免合规（Q26）。⑦待用池库容默认 100 可配无上限（Q27）。
- **📌 PWC-SCORING 评分细则（2026-09-13 M0 补规格，Q22/Q22a/Q22b 定稿）**：
  - 合规前置：Q17 词表命中 block 的组合直接 `gate_status=blocked`，不进评分（手拼 Q26 同样不豁免）。
  - `score = (合理性 × 0.6 + 多样性 × 0.4) × 品类乘数`，各分项与 score 量纲 0–1；品类乘数第一期各行业默认 1.0，回流跑通后经 Q61/Q65 校准。
  - 合理性 = 逻辑合理性AI分 × w1 + 场景情绪搭配AI分 × w2（w1/w2 配置化，默认各 0.5；两个 AI 分由 COMBO-VALIDATE 产出）。
  - 多样性 = 1 − max(与待用池中各组合的原子重合占比)，重合占比口径同 Q23；池为空取 1.0。
  - AI 打分失败/超时：分项记"—"、组合转 `pending_review` 人工 Gate，不用默认值凑分。
  - score 仅排序与 Gate 辅助展示，不做自动通过门槛；权重/开关/小数位全部配置化（02 §C2）。

### 段 6 · PWS 冻结（WF-05，owner=BO-07）
- 把 PS 全部已批准原子/PWC 冻结为**不可变快照 PWS**，版本化（v1.0…）。下游（段 7-11）**只能消费 frozen PWS**。
- **pwsReadiness 5 项就绪门（line 2634）**：①存在 approved FieldPool ②≥3 个已批准原子 ③≥1 个 active PWC ④0 个未解决 blocked conflict ⑤pending_gate 字段=0。
- RBAC 红线（line 7674）：PWS 冻结属红线操作，必须 BO-07 角色 + 人工 Gate。
- **📌 定稿修订（详见 §C1.5，临时结论）**：①冻结 = 系统提请（就绪门全绿出待办）+ BO-07 人工执行，7 天未冻升级（Q28）。②重冻三档：合规/事实变更强制、普通增量建议、无关变更免（Q29）。③换版四行处置：旧版 superseded 只读 / 未生成草稿作废重组装 / 未发布待复查（合规强制重生成）/ 已发布不追溯仅标记+合规提醒（Q30）。④大版本递增，全保留，同刻仅 1 个 active（Q31）。⑤增设版本 revoked 急停（Q32）。⑥查重仅同租户内做且仅提示，跨客户同款永不驳回（Q33）。

### 段 7 · 平台静/动态适配（WF-06）
- Skill：PLATFORM-PARSE → COMPAT-RULE → DYNAMIC-SIGNAL 动态信号采集 → **PLATFORM-ADAPTER（state=pending_review, runs_7d=0，即该核心 Skill 在原型中尚未启用）** → PCP-BUILD → PCP-SCORE。
- **PT-PLATFORM-ADAPTER-V1.0 Guard（line 2043）**：只读 frozen PWS；禁止消费 pending PWC/PWS；禁止输出成稿（正文/脚本/标题）；**禁止生成 final_id**；必须返回 `allow/downgrade/block/pending_review` 四态；AI 输出一律 pending_review 需 HumanGate；无 frozen PWS 时返回缺失、不造假数据。
- 静态规则实体：
  - `publishSlots`（line 1098-1221，14 平台 100+ 发布位）：每位含 slotType、推荐档、格式约束（chars/dur，如 X-01 280 字符、TT-01 15-180s）、**四维静态分 traffic/safe/conv/load（0-100）**、risk、gate。AI 拓展候选四维全 0 + pending_gate。⚠ 四维如何聚合为单一 fit_score，全文无公式（红旗 §B1.1）。
  - `platformRules`（line 1383）：**selector 4 层优先级（低→高）slotType > platform > platform+slotType > slotId**，country 为横切 modifier；effect 仅 `blocked/partial`（native 默认不存）；**规模目标 <300 条覆盖 ~10 万理论格子**；跨层触发规则 R-X01~X05（其他层已选原子也作 selector，做内部矛盾检测）。
  - `slotRuleByType`（line 1428）：13 类 slotType 默认值（约 40 列，含单账号日发布限量：主发布位 2-3 / 互动位 3-5 / 短视频位 1-3），优先级最低可被逐位覆盖。
- **平台层 4 条红线（line 9082）**：①不生产产品原子 ②不修改 PWS ③不生成 FCW/final_id ④AI 不允许静默生效——所有候选必须 HumanGate。
- **📌 定稿修订（详见 §C1.6，临时结论）**：①fit_score = 四维加权平均，权重按内容目的配置（Q34）。②发布位档案后台 CRUD，客观字段附来源、四维分明示人工评估（Q35）。③同级规则冲突取最严 + 保存时查重提示（Q36）。④动态信号一期 = 运营手工登记事件，自动采集不做（Q37）。⑤降级建议只能从可配置动作字典选组合，禁 AI 自由文本（Q38）。

### 段 8 · 平台条件包 PCP（无独立 WF，由 WF-06 的 PCP-BUILD/PCP-SCORE 产出）
- **17 字段动态策略池（strategyFields17, line 1294）**：goal/action/struct/intensity/rhythm/tone/emotion/style/perspective/stage/title/hook/opening/mid1/mid2/mid3/ending 共 17 个 `*_pool`。
- **PT-PCP-V1.5 约束（line 2057）**：**17 字段权重总和 ≤1.0**；不修改产品原子；动态信号每周更新触发重算；**平台间不共享权重池**。
- **📌 定稿修订（详见 §C1.7，临时结论）**：①初值 = 4 套平台类型模板派生（Q39）。②Σ≤1.0 统一校验器，保存/重算入库前强制，不合格拒绝（Q40）。③重算 = AI 出候选表+对照单，HumanGate 批准生效（Q41）。④单项单次 ±0.05，重大变化走人工通道（Q42）。⑤17 池选项做配置字典，池本身增删列后期（Q43）。

### 段 9 · 策略/结构/表达包（WF-07，D0 四包之三）
- Skill：CONTENT-GOAL-PLAN → STRUCT-MATCH → TONE-STYLE → CONTENT-GOAL-TAG。
- 原子来源：`layerSpaces` 通用底座（line 1261，跨产品共享）——strategy 6 维（认知阶段/目的/强度/角度/情绪/CTA）、structure 6 维（标题/钩子/开头/中段/结尾/脚本）、expression 6 维（语气/本地化/直白度/软化映射/视觉/符号）。
- 产出 packages（line 863）：CSP（goal/stage/angle/intensity/cta/emotion）、CSTP（struct 段式）、CEP（tone/perspective/explicit/soften），各带 conf 与 gate。
- **contentGoals 配比约束（line 1090）**：ENGAGEMENT ≤0.40 / CONVERSION ≤0.30 / EDUCATION ≥0.15 / TRUST ≥0.15 / RETENTION ≥0.10。⚠ 全链无消费此配比的调度逻辑（红旗 §B1.13）。
- **📌 定稿修订（详见 §C1.8，临时结论）**：①配比落地为软提示仪表盘（任务页黄条 + 回流报表栏目），不做硬闸门（Q44）。②三包按（产品×平台×目的）配一份复用，满 20 次或 PCP 更新触发重配（Q45）。③通用底座改动收权平台级管理员 + 影响面提示（Q46）。④三包必审线复用 Q9 的 0.85 同一配置项（Q47）。

### 段 10 · 合规清洗（WF-08 → CCR）
- Skill：COMPLIANCE 筛查 → CLAIM-DOWNGRADE 功效降级 → LAW-REVIEW 法审触发。
- 合规底座 layerSpaces.compliance 4 维：CP-BAN 禁用（permanent removal/cure/treat/根治/保证有效/100%）/ CP-DOWN 降级（治愈→感受改善、根治→护理、立即→逐渐、永久→持续）/ CP-LAW 法审触发（医疗健康/儿童/减肥/美白/医疗器械/金融）/ CP-CLEAN 清洗替换。
- 国家级规则：R-030（EU/GDPR 禁留邮箱手机）、R-031（CN/NMPA）、R-032（US/FDA OTC 禁 cure/treat）；国家事实库 countries（line 1417）。
- **PT-COMPLIANCE-V2.0 约束（line 2029）**：绝不放过医疗绝对化；**block_required=true 阻断后续 WF（WF-09 必须中止）**；降级只出建议、最终人工 approval；分市场独立判；历史 SkillRunLog 不可 mutate（即便回滚）。
- **📌 定稿修订（详见 §C1.10，临时结论）**：①全链合并为一张合规词库（等级/处置/降级映射/国家/行业），段 4/5/10 三关卡同源（Q48）。②law_review = 敏感领域自动触发 + 合规角色待办卡段 11 Guard + 通用待办 SLA 引擎（24h 黄/48h 升级上级）（Q49）。③优先序：国家法规 > 平台规则 > 底座默认，不可配置（Q50）。④词表生效即自动扫描快照/草稿/未发布内容，联动 Q29/Q30（Q51）。

### 段 11 · final_id 组装（WF-09，E1 唯一出口，全系统最高 Gate）
- Skill：FCW-ASSEMBLY + FCW-SCORE。产出 FCW（line 870）：`final_id / pws_id / pcp / csp / cstp / cep / ccr / platform / slot / goal / score / publish_status(draft|published) / E1_owner=publishFCW`。
- **PT-FCW-ASM-V1.0 五项 Guard（line 2071，任一失败→guards_passed=false，final_id 不生成）**：①PWS state=frozen ②compliance.block_required=false ③所有 Package state=active ④6 路输入 product_space_id 一致 ⑤tenant_id 一致。
- **单一出口红线（line 11036）**：全系统只有 E1.1 publishFCW 能生成 final_content_whitelist_id；任何其他模块/Skill/Agent 写 final_id = 越权 = 违反协议。
- **📌 定稿修订（详见 §C1.11，临时结论）**：①Guard④⑤ 校验"配置实例"归属（实例落库带 product_space_id/tenant_id），底座字典共享不受影响，红旗 §B1.6 解除（Q52）。②Guard 扩至 7 项：+⑥law_review 已通过 +⑦PWS 为当前 active 版本（Q53）。③score = 骨架 0.4 + fit_score 0.3 + 三包 conf 0.3，仅排序不做门槛，一期临时公式待回流校准（Q54，见备注）。④发证全自动（选 A），任务驱动 + 手动单条辅助，组装不设人审，发证必审计（Q55）。

### 段 12 · 内容生成（WF-10，只读消费）
- Skill：ARTICLE-GEN / VIDEO-SCRIPT / MULTILANG-GEN / CONTENT-COMPLIANCE 二次校验。
- **PT-ART-GEN-V1.5 约束（line 2085）**：只读消费 FCW，不重新决策上游、不重新打分、不加入 FCW 之外的原子；compliance 已在 FCW 内完成不重判；**生成后必走 SK-LIB-CONTENT-COMPLIANCE 复检**。
- 载体：文章生成中心、视频生成中心（video-studio 四模块：白名单信息区/分段编辑器/内容清洗区/生成结果区，AI 质量评分阈值 0.85 上线，line 5196）、内容池、成品库（ready_for_publish）。
- **📌 定稿修订（详见 §C1.12，临时结论）**：①重生成上限 3 次（配置页面），3 次转人工或作废骨架回池（Q56）。②质量分降级"辅助参考"，待回流校准（Q57）。③多语言 = 发布位市场 ∩ 产品语言，各语言版独立成品（Q58）。④客户通过/驳回（必选原因）/改稿（强制重过四项复检），复检 = 词库扫描 + 语义级检测 + 施工指令核对 + 国家规则核对（Q59）。

### 段 13 · 反馈回流 + KUP（WF-11 + WF-12）
- 输入 `catFeedback`（line 746）：按类目 `{content_count, avg_ctr, avg_read, avg_conv, hot, field_impact:[{fid, fill 填充率, lift 转化增益, impact}]}`。
- KUP 提案（line 1006）：`{type: add/promote/demote, target, reason, evidence, conf, status:pending}`——由 KUP-PROPOSE（**state=pending_review，原型中未启用**）生成，PM 人工 Gate 后经 WEIGHT-UPDATE 回写 G2 字段/原子 weight/类目模板。示例：KUP-WART-02「FLD-FREQUENCY 填充率 22% 且增益<0.5% → demote」。
- WF-12：PROMPT-EVAL（pending_review）+ DRIFT-DETECT 漂移检测。
- 这是全链**唯一反向边**（回写段 3/4/8），构成飞轮闭环。
- **📌 定稿修订（详见 §C1.13，临时结论）**：①回流 = 外部 Agent 推送制，本系统只提供 effect-callback API（契约含缺失=未采集纪律、时间序列、幂等）；发布链路澄清：客户确认→**运营发布并回填链接**→Agent 抓取推送（Q60）。②爆款 = 中位数 5 倍 + 绝对门槛，自动提名人转正，参数配置页（Q61）。③不做拉取调度，Agent 驱动（Q62）。④KUP 证据三关（30 条/0.5%/2 期，配置页）+ 预期对账可回滚（Q63）。⑤KUP 两级审批（单产品=运营，共享层=平台管理员），"PM"废除（Q64）。⑥两张常设校准月报（Q65）。

## 4. 横切治理规则（全局红线）

1. **AI 仅产候选，人工 Gate 批准**：Critical Skill 输出必须走 Candidate → Review/Confirm → Applied 通道（line 11314）；Skill 状态机 skill7：`ai_suggested→pending_review→confirmed/modified/rejected→archived/applied`。
2. **Agent 三条边界（line 2115）**：Agent 不能批正式对象；必须有 max_turns + max_tokens + emergency_stop。注册 3 个 Agent：AG-REVIEW-COPILOT（建议不批准，10 轮/8000 token）、AG-PM-AUDIT（6/6000）、AG-SUPPORT（20/4000，上线前需脱敏审核）。
3. **RBAC 红线操作（line 7674）**：PWS 冻结（BO-07）/ 原子正式化 / 合规废弃 / Prompt 修改——必须对应角色 + 人工 Gate；只读角色看不到写按钮。
4. **Prompt 治理（line 1994）**：只读 + 编辑必走 ChangeProposal + AI 不可自动 mutate；保存自动版本 +0.1、history 追加。
5. **资金动作（line 1463）**：freeze/refund/correct 必走 HumanGate（二次确认 + writeAudit）。
6. **模型注册（line 2101）**：API Key 仅 UI 槽位（P1 不真接），真接 LLM 时此页是唯一入口。⚠ 两套模型注册表并存且单价口径不同：`DATA.modelRegistry`（类目 AI，per-1K）与 `MODEL_REGISTRY`（Skill 主用，per-1M，含日预算 Opus 50/Sonnet 30/Haiku 10 美元等）。
**📌 定稿修订（详见 §C1.14）**：①AI agent 一律不持 owner/审批角色，合规/财务窗口必须真人（Q66）。②两表合并为一张模型注册表（统一 per-1M）+ 场景→模型路由配置页（Q67）。

## 5. 数值约束速查

> **数值速查表已并入 §C2 配置化清单**：所有可配置数值以 §C2（见 02 文档）为唯一权威（随 Q1–Q72 同步，每项带 line/Q 溯源）。原 HTML 原值速查表因与 Q1–Q72 定稿不同步已删除（例：冷启动旧写 `hit_rate<0.6`⚠ 定稿为 `conf<0.6`（Q1）；字段池 `<0.85 必走 HumanGate` 已改为 Q9 的"细看线"（第一期全部走 Gate）；内容目的配比（Q44）与 AI 质量分（Q57）已降为软提示/辅助参考，非硬约束）。
>
> **两项非配置的结构性约束**不属 §C2（配置化）范围，仍见正文：① **PWS 就绪门 5 项**（存在 approved FieldPool / ≥3 approved 原子 / ≥1 active PWC / 0 blocked conflict / pending_gate=0，line 2634）→ §3 段6；② **平台规则规模 <300 条覆盖 ~10 万格子**（line 1382）→ §3 段7、03 文档红旗 §B1.8。

## 6. 连带关系（改哪儿影响哪儿，均以 HTML 依赖为据）

| 改动点 | 传播路径 |
|---|---|
| G1 类目 template.field_list | → 该类目**未来产品**段 3 字段池默认 → 段 4 原子空间；**存量产品不自动重算，按 Q29 三档触发重冻**（Q69）；merge/deprecate 需 merged_into 永久重定向，否则历史 PS 悬空 |
| G2 字段（同义词/status） | → g2FieldCandidates.dup 去重判定 → C7 Layer3 挑选；deprecated 字段被历史 template 引用会悬空；**`fid:'-'` 黑户字段禁止落库、须回填 fid**（Q68，原红旗 §B1.14 已解除） |
| 产品原子变更 | → 必须重新冻结新版 PWS（触发档次见 Q29）→ 段 7-11 全部基于新版；旧 final_id 处置见 Q30 四行（原红旗 §B1.5 已解除） |
| PWS frozen | 段 7-11 的唯一合法输入（多处 Guard 强制），是全链最硬的闸 |
| 合规规则（CP-BAN/国家规则） | → 段 10 CCR → block_required=true 使段 11 组装失败；横切一票否决 |
| PCP 权重池 | 平台间不共享；动态信号每周触发重算 → 段 9-11 下游重算 |
| KUP 通过 | → 回写 G2 字段 / 原子 weight / 类目模板 → 影响段 3/4/8 未来产出（唯一反向边、唯一循环） |
| platformRules | selector 优先级仲裁；同级多规则命中取最严 + 录入时查重拦截（Q36，原红旗 §B1.8 已解除） |

## 7. 实现范围建议（以 HTML 13 段链为准）

**第 0 步 — 补规格仲裁（写代码前）**：裁决 §B1 S 级 4 条——①段 1-6 数据模型补齐（实体字段以 §A3 各实体清单为底）②平台适配与 KUP 两个 pending Skill 的协议定稿 ③回流指标降级为平台可得数据（公开互动数 + 客户手工回填转化）④评分公式定稿（四维聚合、C1 信号提取、PWC 品类乘数）。§B2 三处规格缺口决定是否采纳业务方素材（需明确告知并映射）。

**第一阶段 — 核心主链 MVP（段 1→6→10→11→12）**：
产品录入（14 态可裁剪为 8 态左右）→ C1 识别（先文本信号，图像后置）→ 字段池规划 + Gate → 原子拓展 + approveAtomGuard → PWC 构建/校验（评分先用可解释的简化公式）→ PWS 冻结（pwsReadiness 5 项）→ 合规清洗（CP-BAN/CP-DOWN 规则库驱动）→ FCW 组装（5 项 Guard，通用包一致性校验问题先按「通用包免校验 PS 归属」处理并记录）→ 内容生成（只读消费 + 强制复检）。
横切最小集：skill7 候选-审核通道、writeAudit、final_id 单一出口、RBAC 红线操作。

**第二阶段**：段 7/8 平台层（发布位静态规则 + 简化 fit_score）、段 9 D0 三包、段 13 回流（先发布记录 + 可得互动数据 + 人工 KUP，AI 提案后置）。

**第三阶段 — 周边**：§D 清单按需展开（计费/账号管理/视频工作台/Agent/成本治理等）。

---

> **信息保全**：本文档完整收录 v3 Part A 全部内容（A1–A7）。各段的定稿修订细节（Q 编号）与配置项见 02 文档；红旗依据见 03 文档；实体字段级提取见 04 文档；状态机与 API 见 05 文档；Workflow/Skill 协议见 06 文档。
