# Design — Q324 候选稿统一审阅档（八件外部输入候选 + agnes 查证）

> **状态**：✅ **已拍板并全部落地（2026-10-09 Q325，02 C1.268）**。负责人对 §10 审核表八件（#1–#8）逐行批「按推荐」；Q325 已按推荐落地八件（种子回填四件／代码能力三件／WF-07 四 Skill 规格定稿），agnes 视频 mode（#9）维持【待供应商文档】挂账。本文各候选表保留为决策依据备查。
> **登记**：Q324（2026-10-09，02 C1.267，纯文档零代码零迁移零测试变化）；Q325 落地（2026-10-09，02 C1.268）
> **来源口径**：docs/02 Q38（C1.6）/Q43（C1.7）/Q8（C1.8 已落 6 路）/Q78–Q85（DIM-MERGE 族）/docs/02 L52（灵感库来源钦定）/design-d3.5 §3.3（合理性校验缺口）/docs/05 🟡 契约待补（三条写口）/docs/02 C1.80（付费档四档）/pa_rules.py（17 池 + 四维）/effects/models.py（metrics 七键）/docs/12 #21–24（WF-07 四 Skill）
> **纪律**：候选＝可审阅草案，不代表原文口径；凡原文未给处一律保持【待补】标注，本档不臆造"已确认真值"。
> **审核方式**：末尾 §10 汇总表逐件给"推荐 / 备选 / 维持挂账"，负责人逐行批注即可。

---

## 1. Q38 六码中文名与理由（docs/02:141 原文只给了六个动作码，`name`/`why` 原文未给）

> 现状：`downgrade_actions` 表种子六码已落（迁移 0051），`name`/`why` 为 NULL，管理端字典页显示"待运营回填"。
> 用途：AI 输出"动作组合 + 中文理由"时从字典取值（Q38 原话），六码 `why` 供 LLM 提示词消费。

| 动作码 | 中文名（候选） | 中文理由模板（候选，供运营微调） | 依据 |
|---|---|---|---|
| `REMOVE_BRAND` | 移除品牌元素 | 内容含品牌名/标识，与发布位品牌露出规则冲突，建议移除后重审 | 语义直译 + 合规场景 |
| `REMOVE_CLAIM` | 移除功效断言 | 内容存在未经证据支持的疗效/功效宣称，按合规词库命中移除 | 对应 Q48 合规词库命中面 |
| `REMOVE_LINK` | 移除链接 | 内容含外链，触发平台外链限制或引流规则，移除后重审 | 平台规则面 |
| `SOFT_CTA` | 弱化行动引导 | 强引导（购买/下载/私信）与当前发布位宽松度不符，降级为软引导 | 对应强度档位（17 池 intensity） |
| `SHORTEN` | 精简篇幅 | 内容长度超过发布位字数上限，按上限截断保留核心信息 | 对应发布位 chars_max |
| `SUBST_WORD` | 替换敏感词 | 命中敏感词表/黑名单词，替换为合规同义表达 | 对应词库替换面 |

**推荐**：按上表回填 `name`；`why` 作为模板提示词存入（LLM 输出理由时引用模板 + 命中项），负责人可逐条修改措辞。
**备选**：只回填 `name`，`why` 继续留 NULL（由 LLM 自由生成理由，不强制模板）——但 Q38 原话"AI 输出 = 动作组合 + 中文理由"，模板化理由更可控。

## 2. Q43 17 池候选值（docs/02:155；`pool_options` 种子 17 行 options 全空数组待回填）

> 现状：池名闭合集＝`pa_rules.WEIGHT_KEYS_17`，写口只校形状不校语义；候选值原文未给。
> 用途：段9 选料只能从字典选项中选（Q43 强校验），每池 options 是"可选值清单"。
> 以下候选按池语义给 3–6 个专业取值（草案），负责任的运营可在界面直接增删。

| 池 | 候选值（草案，每池可增删） | 语义说明 |
|---|---|---|
| `goal` | 已闭环（ContentGoal 目的字典，Q25 独立维护，不在此池重复） | 见 Q323 A1 核实结论 |
| `action` | `awareness` / `consideration` / `conversion` / `retention` | 内容行为目标 |
| `struct` | `hook-first` / `story` / `listicle` / `problem-solution` / `demo` | 内容结构类型 |
| `intensity` | `gentle` / `moderate` / `strong` / `aggressive` | 引导强度档位 |
| `rhythm` | `fast` / `medium` / `slow` / `varied` | 节奏档位 |
| `tone` | `formal` / `friendly` / `authoritative` / `playful` / `neutral` | 语气 |
| `emotion` | `positive` / `neutral` / `aspirational` / `trust` / `urgency` | 情绪基调 |
| `style` | `corporate` / `lifestyle` / `educational` / `entertaining` / `minimal` | 内容风格 |
| `perspective` | `first-person` / `third-person` / `brand-voice` / `expert` / `user` | 叙述视角 |
| `stage` | `awareness` / `evaluation` / `decision` / `retention` | 用户旅程阶段（与 action 区分：stage＝旅程位置，action＝本内容动作） |
| `title` | `question` / `number-list` / `how-to` / `benefit-led` / `curiosity` | 标题模式 |
| `hook` | `question` / `stat` / `story` / `contrast` / `promise` | 开头钩子模式 |
| `opening` | `scene-set` / `problem-state` / `promise-led` / `data-led` | 开场方式 |
| `mid1` | `evidence` / `example` / `explanation` / `demonstration` | 中段 1 内容功能 |
| `mid2` | `comparison` / `objection-handling` / `social-proof` / `detail` | 中段 2 内容功能 |
| `mid3` | `summary` / `reinforce` / `transition` / `offer` | 中段 3 内容功能 |
| `ending` | `cta` / `soft-cta` / `summary` / `open-question` / `brand-line` | 结尾模式 |

**推荐**：按上表回填 17 池 options（每池以上述为起点），运营后续在字典页 CRUD。
**注意**：`stage` 与 `action` 的候选有语义重叠风险，已在说明中区分；若负责人认为应合并，可二选一（推荐保留两者，分属"旅程位置"与"本内容动作"）。

## 3. DIM-SOURCE 七路（第 7 路原文未给【待补】）

> 现状：Q8 已落 6 路种子（`fp_source_routes`：user_input/common_inspiration/product_inspiration/category_template/g2_frequent/compliance_risk），迁移注释明示"不足原文 7 路无妨，Q8 已裁"。
> 线索：docs/02 L52 钦定维度合法来源＝灵感库模块含"同类好内容/用户评论/问答/案例/特有表达"（line 14050）——其中"同类好内容/案例"尚未单独成路。

| 候选方案 | 第 7 路（新增） | 说明 |
|---|---|---|
| **甲（推荐）** | `case_evidence`（同类好内容/案例库） | 把"同类好内容/案例"从产品专属灵感库中拆出成独立来源路，与"特有表达/用户评论/问答"归入 product_inspiration 细分字段 |
| 乙 | 不新增，维持 6 路 | 原文"7 路并行"但 Q8 已裁 6 路足够；第 7 路语义与 product_inspiration 重叠，避免重复 |
| 丙 | `user_generated`（用户评论/问答/UGC） | 把 UGC 面单独成路，来源＝评论/问答采集 |

**推荐**：甲案（`case_evidence` 同类好内容/案例库）——补足"7 路"字面且语义与既有 6 路不重叠；若负责人认为第 7 路原文本就是灵感库细分不强制成路，选乙案维持 6 路亦合规。

## 4. 段9 字段组合合理性校验「8 种检测名单＋综合评分公式」（design-d3.5 §3.3【待补】）

> 现状：无独立实现；段5 漏斗有同源能力（Q21 预筛/检测/评分/限量、Q24 去重、Q26 冲突/合规阻断、Q22 PWC 评分公式 Q22a/Q22b）。
> 本候选**复用段5 同源能力**命名，不新造公式。

| # | 检测项（候选名） | 复用/映射 | 判据（草案） |
|---|---|---|---|
| 1 | 敏感词命中 | Q48 词表三关卡（段5 同源） | 命中即 blocked |
| 2 | 宣称/功效断言 | Q48 敏感领域 + 行业阈值 | 命中行业红线即 blocked |
| 3 | 同平台同键去重 | Q24 去重 | 同 product×platform×goal×kind 已存在 active → dup |
| 4 | 维度缺失 | Q21 预筛 | 必填维度缺失 → incomplete |
| 5 | 库容/限量 | Q21 限量 | 超库容/批次上限 → blocked |
| 6 | 目标冲突 | Q26 冲突阻断 | 维度/目标自相矛盾 → blocked |
| 7 | 平台规则冲突 | Q36 平台规则 | 命中 blocked/partial 规则 → 对应阻断 |
| 8 | 发布位适配 | 发布位四维 + chars/dur | 超字数/时长上限 → partial |

**综合评分公式（草案）**：`score = Σ(检测项权重 × 该项通过率)`，权重分配：敏感词 0.30 / 宣称断言 0.25 / 目标冲突 0.15 / 平台规则 0.10 / 发布位适配 0.10 / 维度缺失 0.05 / 去重 0.05 / 库容 0.00（一票否决项不参与加权）；任一 blocked 项 → 总分 0 且不可发布。阈值建议沿用 0.85（Q149 已确认 QC 阈值）。
**注意**：以上检测名单与权重是**工程候选草案**，供业务/法审校准口径；原 03 文档"6 种判断结果 vs 8 项"的不一致已在 design-d3.5 §3.3 登记，本草案按 8 项列。

## 5. 三条写口契约角色（docs/05 🟡 契约待补，Q277 登记）

> 现状：三口业务语义已在 docs/05，代码无角色闸（已核实：ops_decide 只校验录入单状态与待办存在；run_funnel 只校验池 approved 与批量上限；consume 无闸）。
> 候选按既有 RBAC 体系（Q75 角色收口 + Q83/Q87 同型先例）推荐。

| 写口 | 业务 | 推荐角色 | 依据 |
|---|---|---|---|
| `POST /intakes/{id}/ops-decision`（Q3） | 录入单运营决策（通过/驳回） | `operations` | 与 Q82/Q83 业务端点投递档一致；决策单属运营作业 |
| `POST /product-spaces/{id}/pwc/funnel`（WF-04） | PWC 漏斗触发 | `operations` | 同 Q76 外部投递 / Q83 llm-build 口径（operations 显式端点） |
| `POST /product-spaces/{id}/pwc/consume`（Q71） | 中台消费口 | `operations` | 消费候选走 Gate 前为运营作业；Q87 restock_auto 内部入口绕过 HTTP 不受影响 |

**推荐**：三口一律 `operations`（与 Q75 手工 sweep、Q83 llm-build、Q87 restock /run 同档，最小惊讶）。加闸方式＝`require_internal_actor(OPERATIONS)`（Q203/Q242 现行凭证标准，staff 令牌已可签发该角色）。
**备选**：`ops-decision` 改 `product_reviewer`（若负责人认为决策含审核语义）——但 Q3 决策是"录入单运营决策"非候选审核，推荐仍 `operations`。

## 6. 付费档第 5 档（docs/02 C1.80：02 §C2 line 1466 原文"trial 50 万等 5 档"，与 D3.11 三付费档+试用=四档不一致；第 5 档是什么原文未给【待补】）

> 现状：已实现四档（trial/basic/pro/enterprise），trial 额度 50 万为唯一数值，付费档额度置空。

| 候选方案 | 第 5 档 | 额度建议（草案） | 说明 |
|---|---|---|---|
| **甲（推荐）** | 新增 `agency`（代运营/多租户档） | trial 50 万 / basic 150 万 / pro 500 万 / enterprise 2000 万 / agency 5000 万（月 token） | 对齐"代运营＋无客户登录"beta 形态（Q321 ③ 已裁后置 V2），agency 服务多客户 |
| 乙 | 维持四档，把"第 5 档"解释为原文笔误 | 不新增 | 原文"等 5 档"与 D3.11 四档不一致已登记，可裁决为原文笔误 |
| 丙 | 新增 `enterprise-plus` | enterprise 2000 万 / plus 1 亿 | 纯额度顶配档 |

**推荐**：甲案（`agency`）——与产品定位（代运营服务商承载多客户）最契合；额度数值为草案，可按商业定价调整。若负责人认定原文笔误，乙案零成本。

## 7. fit_score 自学习数据源（Q293 材料：四维 traffic/safe/conv/load 全人工，缺被学的量）

> 现状：`effect_records.metrics` 七键（plays/likes/comments/shares/inquiries/conversions + read_rate）为唯一候选数据源，与四维对不上；`safe`/`load` 零候选源。
> 候选映射（草案，需业务确认语义）：

| 四维 | 候选映射指标 | 映射逻辑（草案） | 数据可用性 |
|---|---|---|---|
| `traffic`（流量） | `plays`（播放） | 播放量为流量代理 | ✅ 有数据源 |
| `conv`（转化） | `inquiries + conversions` | 询盘+转化为转化代理 | ✅ 有数据源 |
| `load`（负载/完读） | `read_rate`（完读率） | 完读率为内容承载度代理 | ✅ 有数据源（比率） |
| `safe`（安全） | **无直接指标** | 安全维度不出现在效果指标中 | ⚠️ 缺数据源 |
| 辅助信号 | `likes/comments/shares` | 作为互动加权修正（不计入四维主分，做置信度调节） | ✅ 有数据源 |

**自学习策略（草案）**：① 四维中 traffic/conv/load 用 effect 指标按周期聚合（如周均值）反哺对应发布位静态分；② `safe` 维持人工评估（无效果指标可学，不臆造映射）；③ 数据不足（段13 生产零行）时维持人工分、不触发自学习（Q293 已定：数据源缺失不按零值处理）。
**推荐**：按上表实现 3/4 维自学习（safe 例外），映射语义请业务确认后点工。

## 8. WF-07 AI 选包四 Skill 规格草案（docs/12 #21–24 占位未定稿）

> 现状：四 Skill 全 ⬜ 占位；Q272 已确认确定性三元组调度侧已闭环、缺 AI 选包本体。
> 以下按 docs/12 §3 统一模板起草（输入/输出/约束），**草案待定稿**；定稿后即可实现。

### 8.1 PT-CONTENT-GOAL-PLAN（目的规划，#21）
- 输入：产品资料 profile_snapshot、平台/发布位（platform/slot）、行业标签、敏感标记（复用 field_plan 模板变量族）
- 输出：目的规划（goal 候选 + 置信度列表，≤3 项，从 ContentGoal 活跃字典取值）
- 约束：goal 必须命中 ContentGoal 活跃表（Q25 字典）；无活跃字典 → 不产出；置信度 0..1
- 对应实现：复用 E1.1 goal 维度校验（`_validate_goal`）

### 8.2 PT-STRUCT-MATCH（结构匹配，#22）
- 输入：产品资料 + 发布位约束（chars_max/dur 区间）
- 输出：内容结构候选（从 17 池 `struct` 池 options 取值，≤2 项）+ 结构参数
- 约束：结构值必须命中 struct 池字典（Q43）；发布位约束不满足 → 该候选标记 partial

### 8.3 PT-TONE-STYLE（语气风格，#23）
- 输入：目的（goal）、平台、行业标签
- 输出：tone + style 两个维度的字典值（各 1 项）
- 约束：两值必须命中对应池字典（Q43）；缺目的 → 422

### 8.4 PT-CONTENT-GOAL-TAG（目的打标，#24）
- 输入：已生成内容（body 文本/视频描述）、goal
- 输出：打标结果（goal 标签确认 + 置信度）
- 约束：仅对已生成内容操作；标签必须命中 ContentGoal 活跃字典

**推荐**：四 Skill 规格按上述草案定稿（与 Q25/Q43 字典强校验闭环对齐），定稿后按既有 WF-07 切片流程点工实现。

## 9. agnes 视频 mode 合法取值——查证结论（B 组）

> 现状：Q254 实测 agnes 三模真模型，视频模型五种子 mode 全 400 invalid mode；`mode` 合法取值【待补】维持挂账。
> 查证范围：公开网络（agnesis 官方文档/第三方集成文档）。
> **结论**：公开渠道**未找到 agnes 视频 API 的 mode 枚举契约**。检索到的第三方内容（视频生成使用经验：Video2.5Flash 支持"快速模式"、时长 3–18 秒、720P 等）为用户侧使用经验，**不能作为 API 合法取值证据**（无官方 schema）。
> **处置**：维持【待供应商接口文档】挂账；若供应商文档可得（用户可提供 agnes 网关 API 契约或截图），本项即可从待补转落地。
> **补充候选**（不作为真值）：若供应商文档最终给出 mode 枚举，结合第三方"快速模式"线索，候选形态可能为 `fast/quality` 或 `standard/pro` 二值枚举——此仅为推断线索，不作落地依据。

## 10. 审核汇总表（负责人逐行批注）

| # | 事项 | 推荐 | 备选 | 我的批注 |
|---|---|---|---|---|
| 1 | Q38 六码 name/why 回填 | 按 §1 表 | 只回填 name | ✅ 按推荐（Q325 落地：seeds meta＋迁移 0053 UPDATE） |
| 2 | Q43 17 池候选值 | 按 §2 表（17 池） | 逐池增减 | ✅ 按推荐（Q325 落地：seeds 候选＋迁移 0053 UPDATE） |
| 3 | DIM-SOURCE 第 7 路 | 甲：新增 `case_evidence` | 乙：维持 6 路 / 丙：`user_generated` | ✅ 按推荐（Q325 落地：迁移 0053 INSERT） |
| 4 | 8 检测名单＋评分公式 | 按 §4 表（权重 0.30/0.25/0.15/0.10/0.10/0.05/0.05/0.00，阈值 0.85） | 调整权重/名单 | ✅ 按推荐（Q325 落地：规格定稿，design-d3.5 §3.3 闭合） |
| 5 | 三条写口角色 | 一律 `operations` | ops-decision 改 product_reviewer | ✅ 按推荐（Q325 落地：require_internal_actor 加闸＋GATED 移入） |
| 6 | 付费档第 5 档 | 甲：新增 `agency`（trial 50 万/basic 150 万/pro 500 万/enterprise 2000 万/agency 5000 万） | 乙：四档为原文笔误 / 丙：enterprise-plus | ✅ 按推荐（Q325 落地：PLANS＋额度映射） |
| 7 | fit_score 自学习映射 | 按 §7（traffic/conv/load 可学，safe 维持人工） | 调整映射/周期 | ✅ 按推荐（Q325 落地：fit_learning 模块＋单测） |
| 8 | WF-07 四 Skill 规格 | 按 §8 草案定稿 | 逐份修订 | ✅ 按推荐（Q325 落地：docs/12 §3.2 定稿） |
| 9 | agnes 视频 mode | 维持【待供应商文档】；可另提供文档解锁 | 提供供应商接口文档 | 维持挂账（无官方契约证据，禁臆造） |
