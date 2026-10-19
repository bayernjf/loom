# 25 · PRD 逐条验收台账（对照 docs/01 + Q1–Q72 定稿）

> **性质**：把 `docs/01_PRD_产品需求规格.md` 的 13 段规格与 `docs/02` Q1–Q72 决策口径，拆成**可逐条打勾的条目**，每条给落地状态 + 可溯源证据 + 缺口。与 `docs/24`（段级比对）互补：本档回答「哪一条满足／哪一条没满足」，不重述段级结论。
> **状态口径**（沿用 docs/23 §8）：✅ 已落地｜🟡 部分/有缺口｜⬜ 未启动。
> **判定纪律**：**只记实测读到的事实**（`文件:行号`／迁移号／配置键名）。无证据一律写【无证据，未落地】，不推测、不用"应该已实现"。
> **实现侧基线**：Q370（2026-10-19，02 C1.312；**E2E 环境副作用拍板批＝纯文档批，零代码零迁移零测试变化**；Q369 ⑥ 三项环境副作用拍板：门控 `LOOM_STAFF_AUTH_ENABLED=true` **保留**（后续 E2E 复用）、FCW 快照 537a2f28 作废 **接受**（测试数据 t-e2e、审计留痕、原行不变）、两条 E2E 令牌 **保留**（后续 E2E 复用，可随时 staff-keys 吊销）；基线照 Q369 时点引用〔**1453 passed＋11 skipped／收集 1464**、ruff 全仓净、头 `0064_field_candidate_gate_sla_seed`／75 表·821 列·迁移文件 64、`GATED` **63**、侧栏 20、ts/tsx 122〕，本批未复跑；**验收计数不动**（✅80／🟡11／⬜5）。上一条 **Q369 基线（2026-10-17，02 C1.311；**浏览器 E2E 验证批＝纯文档批＋环境验证，零代码零迁移零测试变化**；docs/26《新用户E2E验证清单》落盘＋§6 首轮实测结果（20+ 管理页实测全过、核心闭环实测：预检七项全过／E1.1 幂等唯一出口 409／Guard 材料拦截 409／作废写口 API 200／审核状态机 409／配置热更 3→4→3）；基线照 Q368 时点引用〔**1453 passed＋11 skipped／收集 1464**、ruff 全仓净、头 `0064_field_candidate_gate_sla_seed`／75 表·821 列·迁移文件 64、`GATED` **63**、侧栏 20、ts/tsx 122〕，提交前全量复跑确认；**验收计数不动**（✅80／🟡11／⬜5，E2E 批不翻任何条目）。上一条 **Q368 基线（2026-10-17，02 C1.310；四片工程批：atom 管理前端＋Q35/硬闸#12 AI 新位入口＋段12 成片入库＋Q68 候选 Gate 待办**）＝**后端全量复跑实测**〔**1453 passed＋11 skipped／收集 1464 in 127.35s**（本批净 +16＝publish_slot_gate 9＋video attach 5＋c1/fieldpool 待办 2；对照 Q367 基线 1437＋11，与目标逐位一致）〕、ruff 全仓净、Alembic 头 `0064_field_candidate_gate_sla_seed`／迁移文件 **64**（本批 +1 纯数据种子）、**`GATED` 实测 63**（+3＝ai-candidate／slot approve／attach-to-content，均 OPS）；前端 tsc＋七检查器＋`next build` exit 0、侧栏 **20** 项（atoms）、ts/tsx **122**。上一条 **Q367 基线（2026-10-16，02 C1.309；文档现状核对批＝全量复跑逐位一致＋GATED 账面漂移纠错）**＝**纯文档批，零代码零迁移零测试变化**：后端全量复跑 **1437 passed＋11 skipped／收集 1448**（**78.72s**，与 Q363 登记**逐位一致**）、ruff 全仓净、Alembic 头 `0063_pwc_funnel_knobs_seed`（本批零迁移）、75 表·821 列、迁移文件 63、测试文件 154；**`GATED` 纠错＝AST 实测 60**（账面「48」系 Q329 批 −3 误差为源头，Q354 记 58 ✓ 正确，Q360 照抄 Q329 账面致 58→60 记成 46→48，Q361–Q366 照抄传播；按 Q343 先例只注记不回改，自本条起账面回正 **60**，漂移全链见 docs/16 Q367 行）；前端零改动。上一条 Q364 基线（0063／75 表·821 列／迁移 63／1437＋11〔照 Q363 引用〕／侧栏 19 项·ts/tsx 119，02 C1.306 Q56 重生成上限配置页前端切片）保留为历史时点。
> **登记**：本台账随 Q347 批落地（2026-10-11，docs/02 C1.290）；Q350 批同步行状态与计数（见各条注记）。

## 0. 结论摘要

1. **逐条计数**：本期共验收 **96 条**（决策 75 行〔Q1–Q72，**Q60a/b/c 拆行、Q22a/b 并入 Q22**〕＋结构性硬闸/红线 21 条）＝ **✅ 80 ／ 🟡 11 ／ ⬜ 5**〔**Q368 订正（02 C1.310）**：Q35（§4 段7，AI 新位入口闭环）、Q68（§5 补登/接缝，候选 Gate 待办落地）、硬闸 #12（§6，AI 新位"四维 0＋pending_gate"入口接线）三条 🟡→✅；决策小计 62→64✅／9→7🟡、结构性 15→16✅／5→4🟡、合计 77→80✅／14→11🟡、⬜5 不变，V1 主链 40/1 不变。**Q366 订正（02 C1.308）**：负责人 2026-10-16 裁决两项两读法案均采读法一翻正 ✅——① Q9（§3.2 段3，V1 主链内）：§8.1 处置口径「加一条 lint/哨兵测试，或明确靠人工登记并写入纪律」已被 Q357 哨兵测试（`tests/unit/test_no_magic_numbers.py`，AST 扫浮点常量＋棘轮 ALLOWLIST＋待校准登记制）满足，🟡→✅；② §6 #3：Q76 定稿（02 C1.20 line 312，2026-09-14 负责人口径「进入通道即 pending_review（投递落库态），本切片不持久化 ai_suggested【实现补】」）效力高于 05 §2.3 原文 7 态字面，通道 6 态持久化即定稿 V1 口径，🟡→✅。决策小计 61→62✅／10→9🟡，主链 39/2→40/1（🟡 仅剩 Q7），结构性硬闸 14/6/1→15/5/1；合计 75→77✅／16→14🟡，⬜5 不变。**Q365 订正（02 C1.307）**：① Q69 缺口「Q29 三档重冻通道未实现」所依赖的事实已随 Q361 销 Q29 消失——重冻通道本体 `whitelist_center/service.py:423-619`＋配置键 `pws.refreeze_tier_map`（迁移 0062）俱在，Q361 销 Q29 时本行缺口未同步，属跨批账面漂移（同 Q362 代补 §6 #5 先例），🟡→✅；Q69 属补登/接缝行不在 V1 主链，主链 39/2 不变；② §6 #3 状态机加两读法并存注记（读法一＝Q76 定稿 02 C1.20 已裁可判销／读法二＝05 §2.3 字面 7 态保 🟡），照 Q363-Q9 先例留负责人裁决，计数不变。**Q364 订正（02 C1.306）**：Q56 重生成上限配置页前端切片落地（`/admin/config` 运行配置台，读写均仅 platform_admin），🟡→✅；Q56 属段12 不在 V1 主链，主链 39/2 不变。**Q363 订正（02 C1.305）**：Q47 三包必审线已接线（审核台 needs_detail 复用 `fieldpool.needs_detail_conf` 同一键），🟡→✅；Q47 属段9 不在 V1 主链，主链 39/2 不变。**Q362 订正（02 C1.304）**：① Q21 漏斗开关/顺序配置化＋评分后限量截断、Q25 内容用途绑字典、Q26 手拼跳预筛、Q51 段12 未发布成品同扫四条 🟡→✅；② §6 #5 readiness ⑤ 代 Q361 补翻正（该行 Q361 已销于 §8.1/§0 但 §6 表行未同步，照 Q359 补 Q358 先例补齐）；③ **坐实跨批账面漂移并以全表逐行实测重述**：Q360 翻正 Q16/Q18/Q19/Q20 四条未同步 §0/§2 计数（✅ 少记 4）、Q361 #5 计数先行而 §6 行未翻（✅ 多记 1），净漂移 ✅ −3（账面 64→实测 67），再＋本批 5 条翻正＝72；§2 表段8/段9/段12 三行历史错位一并刷正。Q361 订正（02 C1.303）：Q29、#5、#15 三条升 ✅（61→64、🟡30→27）；Q350 订正：① 第 16 条国家级规则裁乙案随 V2，状态落「✅ 已裁决」（原 ⬜6→⬜5 同时 ✅58→59）；② Q11、Q30 两条经 Q350 代码批满足，🟡→✅。合计仍 96。原始时点计数见 §1 Q347 注记〕。
2. **V1 主链（Q73 权威范围＝段 1→6→10→11）逐条口径下接近全绿**：该范围 41 条＝**✅ 40 ／ 🟡 1 ／ ⬜ 0**〔**Q366**：Q9（段3）经负责人 2026-10-16 裁读法一翻正 ✅（02 C1.308，主链 🟡 仅剩 Q7）；**Q362**：Q21/Q25/Q26（均段6）升 ✅；**并以全表逐行实测刷正本行**——Q361 账面 31|10 未同步 Q360 四条（Q16/Q18/Q19/Q20）等历史翻正，实测重述为 39|2；Q361：Q29（段6）升 ✅；Q350：Q11（段3）、Q30（段6）升 ✅〕。即"主链路可跑通"与"逐条满足"是两件事——`docs/23 §8.1` 的"已闭环 ✅"是按**段级可运行**判的，本档按**条级**判，未销差异仅 1 条（Q7 阈值待业务口径，明细见 §8.1）。
3. **⬜ 5 条集中在段 13 分析面与一条横切**〔Q350 订正〕：Q44（目的配比软提示）、Q63/Q64/Q65（KUP 三关/两级审批/校准月报）、资金动作 HumanGate，均随 V2 已挂账（见 §8）；国家级规则 R-030/R-031/R-032＋`countries` 表原在本数内，**Q350 经负责人裁乙案正式随 V2、从「V1 缺口」重归类为「V2 规划」**（V1 段10 核心清洗已 ✅，scope cut 见第 16 条注记与 02 C1.293）。
4. **本批新坐实的 8 处**（既有段级文档未写入的条级事实）：见 §9〔**Q350 处置**：① Q11↔Q7 联动断裂已裁甲修复（派生＋0057 种子）；② Q30 占位已回填（见各条注记）；③ 国家级规则裁乙案随 V2、不再计 V1 缺口；其余 5 处状态不变〕。~~其中 Q11↔Q7 联动断裂与国家级规则零落库两条建议优先裁决~~ 已裁决（2026-10-12）。

## 1. 口径与方法

- **条目来源**：① `docs/01` §3 各段规格（功能/实体/规则）与 §4 横切；② `docs/02` §C1.1–C1.16 的 Q1–Q72 定稿口径（行 15–263）；③ `docs/01` §2 硬闸与 §3 各结构性约束（10 项 Guard／5 项就绪门／Σ≤1.0／四层兜底等）。
- **一条多行还是合并**：Q 的子裁决（Q22a/Q22b）并入母条 Q22 判同源；Q60 的 a/b/c 是三条独立契约，拆行判。
- **判定优先级**：**代码实测 > 配置种子 > 迁移表名 > 已登记文档**。**只有文档登记而无代码产出的一律降为 🟡**（典型：Q47）。
- **可复跑校验命令**（本档每条证据都应能被下列之一复现）：
  - 规则落点：`rg "<关键词>" backend/app/ --include="*.py"`
  - 配置键是否真被消费：`rg "<键名>" backend/app/ --include="*.py"`（只命中 `config_center/seeds.py` 即＝登记未接线）
  - 是否有默认数据：`rg "<表名>" backend/alembic/versions/*.py`
  - 是否写入（判定"派生链路是否存在"）：`rg "<列名> *=" backend/app/ --include="*.py"`
- **不属本档口径**：工期估算、是否应该做（裁决权在负责人）；本档只回答"做没做、做到哪"。

## 2. 计数汇总

| 范围 | 条数 | ✅ | 🟡 | ⬜ |
|---|---|---|---|---|
| V1 主链（段 1→6→10→11） | 41 | 40 | 1 | 0 |
| 段 7（平台适配） | 5 | 4 | 1 | 0 |
| 段 8（PCP） | 5 | 4 | 1 | 0 |
| 段 9（D0 三包） | 4 | 3 | 0 | 1 |
| 段 12（内容生成） | 4 | 3 | 1 | 0 |
| 段 13（回流 + KUP） | 10 | 5 | 1 | 4* |
| 横切治理（Q66–Q72 中的 Q66/Q67） | 2 | 1 | 1 | 0 |
| 补登/接缝（Q68/Q69/Q70/Q71/Q72） | 5 | 4 | 1 | 0 |
| **决策小计** | **75** | **64** | **7** | **4** |
| 结构性硬闸与红线 | 21 | 16 | 4 | 1 |
| **合计** | **96** | **80** | **11** | **5** |

\* 段 13 的 ⬜ 4 条＝Q63/Q64/Q65（KUP 分析面）＋ Q44 计入段 9 时已单列，此处段 13 ⬜ 为 Q63/64/65 三条，跨段重复计数已在合计去重（Q44 只计一次）。

〔**Q368 刷正（02 C1.310）**：段7 行随 Q35 翻正（3|2→4|1）、补登行随 Q68 翻正（3|2→4|1）、结构性行随 #12 翻正（15|5→16|4），决策小计 62→64✅／9→7🟡、合计 77→80✅／14→11🟡；V1 主链 40|1 不变、⬜5 不变；其余行实测不变。〕〔**Q366 刷正（02 C1.308）**：V1 主链行随 Q9 裁决翻正（39|2→40|1）；决策小计 61→62✅／10→9🟡；结构性硬闸行随 #3 裁决翻正（14|6|1→15|5|1）；合计 75→77✅／16→14🟡，⬜5 不变；其余行实测不变。〕〔**Q365 刷正（02 C1.307）**：补登/接缝行随 Q69 翻正（2✅3🟡→3✅2🟡），决策小计 60→61✅／11→10🟡，合计 74→75✅／17→16🟡；其余行实测不变。〕〔**Q364 刷正（02 C1.306）**：段12 行随 Q56 翻正（2✅2🟡→3✅1🟡），决策小计 59→60✅／12→11🟡，合计 73→74✅／18→17🟡；其余行实测不变。〕〔**Q363 刷正（02 C1.305）**：段9 行随 Q47 翻正（2✅1🟡1⬜→3✅0🟡1⬜），决策小计 58→59✅／13→12🟡，合计 72→73✅／19→18🟡；其余行实测不变。〕〔**Q362 刷正（02 C1.304）**：本表七行随 §0 全表逐行实测重述——V1 主链 30|11→39|2（本行自 Q347 后多批翻正未同步：Q350 Q11/Q30、Q360 Q16/Q18/Q19/Q20、Q361 Q29、Q362 Q21/Q25/Q26 等，今以实测一次刷正，🟡 仅 Q7/Q9）；段8（Q41 🟡 原误计 ✅）；段9（一 ✅ 原误计 🟡，实测 🟡 仅 Q47）；段12（Q56/Q59 双 🟡 原只计其一）；决策小计/结构性/合计随动；段7/段13/横切/补登四行实测不变。〕

## 3. V1 主链逐条（段 1→6→10→11，41 条）

### 3.1 段 2 · 冷启动 / C1 / C7（Q1–Q7）

| # | PRD 口径 | 状态 | 证据 | 缺口 |
|---|---|---|---|---|
| Q1 | conf 单指标三分支（≥阈值 direct_approve／[0.6,阈值) ops_assist／<0.6 cold_start），hit_rate 废弃 | ✅ | `app/product/modeling/c1.py:54-84`；`models.py:79` 注「唯一判定指标 Q1，hit_rate 废弃」；`config_center/seeds.py:12` `c1.cold_start_floor=0.6`；迁移 `0002_m2_stage2`；`tests/unit/test_c1_c7_logic.py:24,52` | — |
| Q2 | 信号权重配置表，启用项之和须**精确=1** 否则拒绝保存；一期只文本三信号 0.50/0.33/0.17，图像后置 | ✅ | `models.py:35-45`；迁移 `0002:187-193` 播种三行（无图像行）；`c1.py:26-37` `WeightSumError` 不归一化；`service.py:72-105` 保存校验+审计 | — |
| Q3 | 中置信归运营 ops_assist、客户无感知；Top1−Top2<0.1 为矛盾 | ✅ | `c1.py:18-19,62-83`；`seeds.py:13` `c1.mid_confidence_top_gap=0.1`；`statemachine.py:65-70`；`service.py:250-266`（待办投 operations）；`router.py:64,198-200`（Q325 补闸） | — |
| Q4 | 运营待办 72h 未处理升级；全否转 cold_start | ✅ | `seeds.py:14` `c1.ops_assist_sla_hours=72`→`service.py:264` due_at；`service.py:355-366` escalate→`core/sla/engine.py:25-35`；`service.py:330-337` reject_all→`to_cold_start` | — |
| Q5 | productIntake**15**（新增"类目创建中"） | ✅ | `product_intake/statemachine.py:23` `CATEGORY_CREATING`、`:41`「类目创建中」、`:63` 冷启动停靠；转移表含 b2_approved／b2_parent_fallback／b2_rejected | — |
| Q6 | C7 四层兜底；Layer3 覆盖<60% 降级 Layer4 | ✅ | `modeling/c7.py:12-14,30-43`；`service.py:442-520`（四层依次命中，`:486` 覆盖率判降级）；`seeds.py:15` `c1.layer3_coverage_floor=0.6`；`test_c1_c7_logic.py:59-73` | — |
| Q7 | 行业阈值后台 CRUD：不可删默认档 general 0.85、敏感行业（食品/母婴/医疗器械）0.90、改即审计 | 🟡 | CRUD+审计+默认档保护落：`models.py:48-63`、`service.py:110-184`（`DefaultIndustryProtected` `:172-173`）；迁移 `0002:196-215` 播种 general 0.85／medical 0.90 敏感／electronics 0.80 | ~~敏感初始清单只落 medical~~〔**Q350 已补（02 C1.293）**：迁移 `0057_q7_sensitive_industry_seeds` 补食品/母婴两敏感行〕；**残留**：两行阈值无权威来源取默认档 **0.85**，原文 0.90 待业务确认后再改（禁臆造） |

### 3.2 段 3 · 字段池（Q8–Q13）

| # | PRD 口径 | 状态 | 证据 | 缺口 |
|---|---|---|---|---|
| Q8 | 来源路由表运营可配、默认 6 路、每路带"依据来源" | ✅ | `fieldpool/models.py:36-45`；迁移 `0003_m3_stage3:91-108` 播种 6 路；`planning.py:70,129-130`（source_ref 空判 `VIOL_MISSING_EVIDENCE`）；`model_registry/field_plan.py:84-86` 动态读启用路由；`0053:62-74` 另加第 7 路 case_evidence（超配） | 灵感库本体＝产品基准段3 的 MVP 模块（product-inspiration：通用＋产品专属两层）：**✅ 2026-10-14 Q358 已建**（见 docs/24 §5.2）＝`inspiration_entries` 表＋`/api/admin/inspiration-entries` CRUD＋`field_plan.py` 接线灌入 DIM-MERGE 提示词；迁移 `0060_inspiration_entries` 零种子。前端界面 **2026-10-14 Q359 已落**＝`/admin/inspiration-entries` 运营配置台（列表/过滤/新建/行内编辑/启停/删除；读侧 Q307 契约＋写侧三岛 Server Action，侧栏第 18 项；docs/02 C1.301）。余一项＝存量 production `skill_prompts` 的 DIM-MERGE 模板需运营重发一版把 `$inspiration_entries` 真正写进（fresh-install 已正确） |
| Q9 | 0.85 细看线配置化 + 全局魔法数字一律配置化 | ✅ | 0.85 落：`seeds.py:17` `fieldpool.needs_detail_conf`→`planning.py:23-25,101`；docs/02 §C2 表已登记该键 |  **"禁止硬编码"无强制手段：~~无 lint／哨兵测试扫残留魔法数字，`docs/23` 全文无配置化审计条目，仅靠人工登记 seeds~~ **✅ 2026-10-14 Q357 已补**＝`tests/unit/test_no_magic_numbers.py`：AST 扫 `app/**/*.py` 浮点常量（注释/字符串天然不计入）＋**棘轮 `ALLOWLIST`**（逐文件登记存量、实扫须完全相等：新增未登记浮点与登记项消失都判红）＋`PENDING_BUSINESS_CALIBRATION`（待业务给真值的数值须持续显式登记，当前只有 `fit_learning` 的 `_REF_PLAYS/_REF_CONV`＝清单二第 16 项②）；存量实测 21 文件 35 值逐个附「为什么可以留在代码里」；**整数本批刻意不纳入**（理由写进文件头）；种植验证（插 `PLANTED = 0.73`）判红后按原样还原。〔**Q363 两读法注记（02 C1.305）→ Q366 裁决已下（02 C1.308）**：负责人 2026-10-16 裁读法一——§8.1 处置口径「加 lint/哨兵测试，或明确靠人工登记」已被 Q357 哨兵测试满足 ⇒ 翻正 ✅；读法二（严格读法下存量 35 值仍硬编码于代码、ALLOWLIST 登记制 ≠ 配置化）不采纳——处置口径原文为「或」选其一，哨兵测试＋棘轮登记制＋`PENDING_BUSINESS_CALIBRATION` 待校准显式登记即满足。〕 |
| Q10 | 相似度≥0.9 标疑似重复，人工终裁 | ✅ | `planning.py:28-30,74-75,102`；`seeds.py:18` `=0.9`；`models.py:102-103`（dup/related_fid）；终裁走 `pool.gate=pending_gate`（`service.py:168`）；`test_fieldpool_planning.py:108` | — |
| Q11 | risk_control：敏感行业强制 ≥1 个 | ✅ | 强制逻辑：`planning.py:118,142-143`（sensitive 且无 risk_control → violation）、`fieldpool/service.py:157`、`test_fieldpool_planning.py:38`；〔**Q350 补派生链路（02 C1.293）**：`product_intake/service.py:34` `_derive_industry_flags()` 在 `start_modeling` 从最新 C1Record＋Q7 `sensitive` 旗标派生写入，迁移 0057 补种子〕 | ~~旗标无派生链路恒 False~~ 已销（§9-① 注记同） |
| Q12 | 维度 >8 留 Top8 余入备选；<3 标不达标转人工 | ✅ | `planning.py:113-147`；`seeds.py:19-20`（3/8）；`models.py:84,104-106` 落 selected/backup；`service.py:179-` 双状态；单测 `:70,:82` | — |
| Q13 | 新字段转正需字典管理员权限 | ✅ | `fieldpool/service.py:386-420`（首行校验 `ROLE_DICTIONARY_ADMIN`，转正回填 fid + `fp.candidate_promote` 审计）；`core/rbac/__init__.py:20`；`fieldpool/router.py:287-292` | — |

### 3.3 段 4 · 原子（Q14–Q20）

| # | PRD 口径 | 状态 | 证据 | 缺口 |
|---|---|---|---|---|
| Q14 | 批次 20/50 配置化，敏感 20／非敏感 50，运营可改 | ✅ | `config_center/seeds.py:24-25`；`atom/atom_rules.py:25-30,109-110`；`model_registry/atom_expand.py:109-111` 按 `ps.sensitive_industry` 取默认；`model_registry/schemas.py:117` 入参可改 | ~~实际取值受 Q11 旗标恒 False 影响~~〔Q350 派生链路已落，影响消除；§9-① 注记〕 |
| Q15 | FieldPool 目标原子数 15–30，达标停拓 | ✅ | `fieldpool/models.py:69-70`；`planning.py:33-38`；`fieldpool/schemas.py:37-38` Gate 可改；停拓 `atom_expand.py:88-92` + `atom_rules.py:211-213` `target_reached()` | 手动追加批次不受限（代码注释明示） |
| Q16 | 亲和度不设硬淘汰线；仅排序 + <0.5 标"低亲和" | ✅ | 标记落：`atom_rules.py:33-34,118-119`、`seeds.py:26` `atom.low_affinity_line=0.5`、`atom/service.py:196`、`models.py:126`；排序落（Q360 C1.302）：三列表查询加 `sort` 参数（`atom/service.py` `_apply_sort`，affinity 降序 nulls_last，默认 created_at 原契约），两读口 `sort: Literal["created_at","affinity"]` | ~~排序未落地~~ Q360 已销（2026-10-14） |
| Q17 | risk 双轨（词表强制/AI 兜底/只升不降）+ 词表后台 CRUD | ✅ | `atom_rules.py:141-146` `grade_risk()`；只升：`atom/service.py:619-630`（`risk_source=="wordlist"` → `RiskOverrideForbidden`）；词表 CRUD `core/compliance_wordlist/router.py:59-108`、`service.py:62-147` | — |
| Q18 | pending_evidence：AI 自动补一轮 → 运营待办 → 7 天超时自动驳回（可复活） | ✅ | 超时驳回 ✅ `atom/service.py:543-567` `sweep_evidence_timeouts()`；复活 ✅ `atom/service.py:503-540`；`seeds.py:28` `atom.evidence_timeout_days=7`；人工补证 `atom/service.py:470-500`；AI 补证（Q360 C1.302）＝`ATOM-EVIDENCE` 场景（`model_registry/seeds.py` 提示词 v0.1 工程口径）＋operations 显式端点 `/atom-candidates/{id}/evidence/ai-supplement`（Q354 同族花钱纪律：逐单过人不自动，失败不重试保持 pending_evidence）；运营待办＝`atom_rules.TODO_TYPE_EVIDENCE`＋`OpsTodo`（落 pending_evidence 即开、补证/超时自动关，幂等） | ~~AI 自动补一轮未落~~／~~运营待办未落~~ Q360 已销（2026-10-14） |
| Q19 | AI 标簇 + 推荐保留项（亲和度最高），被合并记 alias 不删 | ✅ | 成簇 `atom_rules.py:237-277`（Q86 起为 embedding 本地确定性算）；推荐规则 `atom_rules.py:199-208` `pick_cluster_keeper()`；保留 alias ✅ `atom/service.py:572-614`（status=merged、alias_of）、`:355`；自动推荐接线（Q360 C1.302）＝读口 `/atom-clusters/{id}/members` 返 `recommended_keeper_id` 供界面预填＋`ClusterResolveRequest.keeper_candidate_id` 可省略（service 用 `pick_cluster_keeper` 兜底） | ~~pick_cluster_keeper 未接线~~ Q360 已销（2026-10-14；"落推荐值到候选行"经裁以读口+可选入参实现，前端无 atom 页面故无预填 UI） |
| Q20 | 冻结/解冻=运营；合规暂停=合规角色；已废弃恢复重走审核 | ✅ | 冻结解冻=operations `atom/service.py:706-724`；合规暂停/恢复=internal_compliance `atom/service.py:726-745`；废弃恢复（Q360 C1.302）＝`POST /api/atoms/{id}/restore`（operations 凭证闸，GATED 登记）：新建 manual 批次候选重走 Gate/冲突/证据流程、旧实例保持 deprecated 留痕、事实原子值先排除自身再查重（line 11189） | ~~废弃恢复重走审核未落~~ Q360 已销（2026-10-14） |

### 3.4 段 5 · PWC（Q21–Q27）

| # | PRD 口径 | 状态 | 证据 | 缺口 |
|---|---|---|---|---|
| Q21 | 漏斗（预筛→检测〔合规/逻辑/情绪，可插拔〕→评分→限量），全链配置化；单次 50、待用池 100 | ✅ | 漏斗主干 ✅ `condition/service.py:186-359`；`seeds.py:30` `pwc.funnel_batch_limit=50`、`:31` `pwc.pool_target=100`；**Q362（02 C1.304）**：`seeds.py:50` `pwc.detectors`（compliance_wordlist 默认开、logic_ai/fit_ai 默认关，清单顺序即执行序）＋`seeds.py:65` `pwc.prefilter_rules`（三规则默认全关）两 json 键，迁移 0063 播种；检测 stage 按键开关/排序、启用未实现项报 InvalidFunnel 422 不静默跳过（`condition/service.py:216-227`）；评分后 score 降序（None 垫底、同分保输入序）截 batch_size 条，blocked 全量落库留痕不占截断口径、溢出不落库审计计数 truncated（`service.py:356-366,424`）；预筛 stage 按键启用同口径诚实报错（`service.py:200-214`） | AI 检测项（logic_ai/fit_ai）与 AI 预筛规则数据源未实现，键默认关、开启即 422（原文未给出，待补） |
| Q22（含 Q22a/Q22b） | score=(合理性×0.6+多样性×0.4)×品类乘数；合规前置不进加权；w1=w2=0.5；多样性=1−max 重合；AI 失败记"—"转 pending_review；score 不设门槛；乘数一期 1.0 | ✅ | `pwc_rules.py:133-183` `score_combo()`（缺失即 `scored=False`、分项「—」）；`seeds.py:36-40`；合规前置 `condition/service.py:302,323-328`；一律 pending_gate 走人工 Gate；`tests/unit/test_pwc_rules.py:46` | 重合分母取 Jaccard 属实现补（原文未定义，`pwc_rules.py:104-105` 已标注） |
| Q23 | 重合占比 ≥0.8 标疑似重复，留高分者 | ✅ | `pwc_rules.py:55-56,101-117,186-188`；`seeds.py:41` `pwc.dup_overlap_line=0.8`；`condition/service.py:296-300` low → `is_backup`+`dup_of` | — |
| Q24 | 已用＝同平台+账号+发布位 1 次；冷却 7 天 3 次/14 天回；高复用≥N 打标；爆款一期手工；严禁跨产品/跨客户 | ✅ | `condition/service.py:476-503`（used_keys）、`:529-543`+`pwc_rules.py:59-68,191-193` 冷却（7/3/14，`seeds.py:42-44`）、`:609-649` 到期回待用；高复用 `:552-555`；爆款手工 `:654-661`；禁跨产品/客户 `service.py:234-238`、`pwc_rules.py:207-215` | "已用"终态依赖 PS 级 target_platforms（未配则不产生，已标注实现补） |
| Q25 | goals 用 contentGoals 字典（CRUD，与录入"内容用途"同源取交集） | ✅ | 字典 CRUD ✅ `condition/service.py:82-138`（dictionary_admin）；建表 `0005_m5_stage5:26-48`；PWC 侧强校验 `:248-252`；取交集 `pwc_rules.py:200-204`、`:507`；三包/平台复用同表；**Q362（02 C1.304）录入端同源**：`product_intake/service.py:205-217` submit 闸校验 `f_content_usage` 必为 ContentGoal active 枚举（非法值 `InvalidContentUsage`→422，`router.py:206`）；e2e 改写字典编码 `tests/e2e/test_fullchain_golden_path.py` | — |
| Q26 | 手拼 PWC 跳预筛但合规不豁免 | ✅ | 手拼通道 ✅ `condition/schemas.py:9`（ai/manual/hybrid）、`models.py:107`；合规不豁免 ✅ `condition/service.py:279-280,302` + `tests/integration/test_pwc_api.py:248-261`；**Q362（02 C1.304）**：预筛 stage 落地（配置化开关，Q21），`condition/service.py:204` `source != "manual"` 分支＝手拼跳过预筛、校验+检测+评分+Gate 照走（集成用例 `test_pwc_api.py:309` 双场景钉死） | 预筛三规则数据源【原文未给出，待补】，启用即 422（Q21 同口径） |
| Q27 | 待用池库容默认 100 可配、可配无上限 | ✅ | `seeds.py:35` `pwc.default_capacity=100`；`condition/service.py:142-182`（`capacity=None`＝无上限）；生效点 `service.py:416-420`；仅 operations 可配 | — |

### 3.5 段 6 · PWS 冻结（Q28–Q33）

| # | PRD 口径 | 状态 | 证据 | 缺口 |
|---|---|---|---|---|
| Q28 | 5 门全绿出待办 + 人工冻结，7 天未冻升级 | ✅ | `whitelist_center/pws_rules.py:11-13`；`service.py:159-203`（全绿建 OpsTodo，due_at=+7d）；升级走通用 `core/sla/jobs.py:19-20,94`；`seeds.py:48` `pws.ready_todo_due_days=7`；人工写口 `router.py:85` | BO-07 已按 Q329 改判 operations（见 §9-⑦） |
| Q29 | 重冻三档 + 清单配置化 | ✅ | 三档落：`pws_rules.py:34-51,88-92`；`service.py:275-277,357` 落 refreeze_tier；**Q361 配置化（02 C1.303）**：`seeds.py` 加 `pws.refreeze_tier_map` json 键（默认 6 原因码→forced/suggested/none，validation `{}`），`refreeze_tier()` 改读 knob 缺键回退代码常量、非法档位 ValueError；迁移 **0062** 播种（照 0058 模式，downgrade 双指纹比对） | — |
| Q30 | 换版四行处置 | ✅ | ① `service.py` 旧版 `is_active=False`+superseded+superseded_by；〔**Q350 ②③④ 已回填（02 C1.293）**：`whitelist_center/service.py:84` `_apply_q30_dispositions()`——② draft FCW `revoke_fcw` 作废＋建指向新版的 queued 重组装任务；③ forced 未发布行建 `q30_pws_recheck`（internal_compliance）；④ published 不回改仅计数＋forced 建 `q30_fcw_outdated_notify`（operations）；另记 `pws.q30_dispositions` 审计，三例测试〕 | — |
| Q31 | 大版本递增／全保留／同刻 1 active | ✅ | `pws_rules.py:82-85` `next_version()`；迁移 `0006_m6_stage6:56` `uq_pws_ps_version`；`service.py:398-400`；`docs/10:150-153` | — |
| Q32 | revoked 急停 + 审计 + 立即断消费 | ✅ | `service.py:481-515`（revoked+ revoked_by/at/reason + freeze_logs + `pws.revoke` 审计）；断消费点 `decision/compliance_center/service.py:289`、`platform_adaptation/service.py:795`、`final_whitelist/service.py:863` | — |
| Q33 | 仅同租户查重且只提示不驳回 | ✅ | `service.py:295-303` 候选集限同 tenant；`pws_rules.py:95-103` 指纹+same_tenant_duplicates；返回 `dup_hints`（`service.py:474`、`router.py:112`），无 reject 分支 | — |

### 3.6 段 10 · 合规清洗（Q48–Q51）

| # | PRD 口径 | 状态 | 证据 | 缺口 |
|---|---|---|---|---|
| Q48 | 全链一张合规词库 + CP-LAW 单独小表 | ✅ | `core/compliance_wordlist/models.py:20-52`（word/level/action/downgrade_target/country/industry/生效期/layer）；三关卡同源 `atom/service.py:151`／`condition/service.py:255`／`compliance_center/service.py:294`／`content/service.py:186`；CP-LAW `compliance_center/models.py:29` + 迁移 `0007_m7_stage10`；**Q361：底座 6 词默认词条已种子（迁移 0061，见硬闸 #15 翻正）** | — |
| Q49 | 敏感领域自动触发 + 合规待办 + Guard⑥ + 通用 SLA 引擎 | ✅ | `models.py:40-50` `law_reviews`；`service.py:165-210` `ensure_law_review` + OpsTodo（指派 internal_compliance）；`ccr_rules.py:27-33,122`；`core/sla/policies.py:19-45`；`seeds.py:50` `ccr.law_review_due_hours=48`；Guard⑥ `fcw_rules.py:171-183` |  ~~触发旗标之一 `ps.sensitive_industry` 恒 False~~〔Q350 派生链路已落，兜底路径可触发；领域清单主路径本不受影响〕 |
| Q50 | 国家>平台>底座，不可配置 | ✅ | `compliance_center/ccr_rules.py:7-14` `LAYER_PRIORITY` 硬编码无 knob；`:38-45` 同级从严；`compliance_wordlist/models.py:31` layer 列；**Q361：底座词条已种子（0061，base 层不可配置语义有数据可跑）** | — |
| Q51 | 词表生效即扫 active 快照/draft FCW/未发布成品 | ✅ | `compliance_wordlist/router.py:31-35` `_q51_rescan`；`compliance_center/service.py:628-658` 扫 frozen 快照→强制重冻待办；draft FCW 扫描 M8 已接（`service.py:710-740` 同事务建 rescan 待办，V1 draft 通道未开通常为空集）；**Q362（02 C1.304）段12 未发布成品同扫**：`service.py:769-833`——范围取命中快照的产品空间集合（沿用快照段 industry 过滤口径）、排除 discarded、三发布列（published_url/platform_post_id/published_at）任一为空即未发布（Q125/Q60c 口径，不回改不追溯）、body casefold 命中词条才建待办（entity_type="content_product"，assignee=internal_compliance 同 Q30③ 口径，幂等不重开、PUT 同词复用 todo_id）；`ccr_rules.py:34-36` | — |

### 3.7 段 11 · FCW 组装（Q52–Q55）

| # | PRD 口径 | 状态 | 证据 | 缺口 |
|---|---|---|---|---|
| Q52 | Guard④⑤ 校验"配置实例"归属，底座字典共享不受影响 | ✅ | `fcw_rules.py:51-59` `MaterialRef(ref_id, ps_id, tenant_id)`；`:140-153` G4 六路 ps_id 一致；`:155-169` G5 tenant 一致；实例落库带归属 `layer_strategy/models.py:52-60`、`service.py:127-131`；`tests/integration/test_fcw_shared_atom_guard.py` | — |
| Q53 | Guard 扩至 7 项（+⑥law_review +⑦PWS active） | ✅ | `fcw_rules.py:29-35` G1–G7 常量（实测 `G7="g7_pws_active_version"` `:35`）；`:86-192` 逐项不短路；`:171-183`、`:185-191` | — |
| Q54 | score=0.4+0.3+0.3，仅排序不做门槛，权重配置化 | ✅ | `fcw_rules.py:208-252` `score_fcw`；`seeds.py:53-55`；`:195-196` 与 `guards_passed` 完全分离，`:201` 明示"绝不当 Guard/门槛" | — |
| Q55 | 全自动发证（任务驱动 + 手动单条），组装无人审，每次写审计 | ✅ | `final_whitelist/router.py:145` assembly-tasks、`:103` assemble、`:64` preview；`service.py:376-536` 全绿即 mint final_id；审计 `fcw.issued`/`fcw.assembly_blocked`/`fcw.assembly_task`；docs/05:189-192 | — |

## 4. 段 7 / 段 8（平台适配 + PCP，10 条）

| # | PRD 口径 | 状态 | 证据 | 缺口 |
|---|---|---|---|---|
| Q34 | fit_score=Σ(维度分×权重)，权重按目的配 | ✅ | `pa_rules.py:89-96` `compute_fit_score`；`:31` `FIT_DIMS=traffic/safe/conv/load`；`goal_fit_weights` `models.py:81-91`+`router.py:217,228`；`pa_rules.py:71-86` Σ=1 强校验 | 种子仅 ENGAGEMENT/CONVERSION 两组（`seeds.py:9-12`） |
| Q35 | 发布位档案 CRUD + 来源 + 四维人工评估 + AI 新位须补档案过 Gate | ✅ | CRUD 四口 `router.py:141,151,167,186`；`models.py:72` source_url；四维 `models.py:62-69` `score_source="manual_eval"`；**Q368（02 C1.310）AI 新位闭环**＝`POST /api/admin/publish-slots/ai-candidate`（四维强制全 0、gate=pending_gate、score_source=ai，schema `extra=forbid` 防 AI 编分）+ `POST /api/admin/publish-slots/{slot_id}/approve`（人工评估写四维、gate→approved、score_source→manual_eval，非 pending 409 `SlotGateNotPending`）；普通 upsert 一律 `exclude={"gate"}`（状态机字段不可携带）；`list_slots` 增 `gate` 过滤；GATED 平台系 +2（ai-candidate／slot approve，均 OPS；attach-to-content 属段12 见任务3） | — |
| Q36 | 同级取最严 + 保存静态查重提示 | ✅ | `pa_rules.py:139-149`（blocked>partial）；`:127-136` `find_conflicts`；`router.py:274-281` 409+conflicts+`overwrite=true` | — |
| Q37 | 动态信号一期＝运营手工登记（自动采集不做） | ✅ | `platform_dynamic_events` `models.py:181-208`；迁移 `0045_platform_dynamic_signal`；CRUD 四口 `router.py:450,460,476,495`；参与判定 `service.py:727-730,775-788` + 周重算扫描 `:1208-1234` | 自动采集不做＝Q37 原文明示，非缺口 |
| Q38 | 六码降级动作字典，AI 只能从字典选 | 🟡 | 字典落：`core/downgrade_actions/` + 迁移 `0051_downgrade_actions`、`seeds.py:9-16`、`0053` 回填中文名/理由；CRUD+审计 | **AI 侧校验未闭环**：`docs/12:150`「尚无 AI 输出动作组合的生成路径」，schema【待补】；字典无消费方强校验点 |
| Q39 | 4 套平台类型模板，各 17 项权重 | ✅ | `platform_adaptation/seeds.py:14-59` `PCP_TEMPLATE_SEEDS`（short_video/community/photo_text/ecommerce 各 17 键）；`pcp_templates` `models.py:136-143`；读口 `router.py:621` | — |
| Q40 | Σ≤1.0 统一校验器（手工拒绝/AI 打回同器） | ✅ | `pa_rules.py:56-68` `validate_weights_17`（键须落 17 池、Σ>1 拒）；复用点 `service.py:998-1000` | AI 重算生成器未落（Q41/V2），"打回"路径无实例 |
| Q41 | 每周重算＝AI 出候选 + 对照单 + HumanGate | 🟡 | 候选表+对照单+Gate 落：`models.py:211-256`（change_list 四项）、`router.py:513,522,544,563`、`service.py:1059-1129` | **AI 出候选未做**：`service.py:986,1035`「V1 仅 manual，AI 生成器随 V2」；周扫只开提醒待办不产权重（`service.py:1278`，`pcp_weekly_scan_enabled` 默认关）；"低于 Q42 阈值不生成待办"未实现 |
| Q42 | 单项单次 ±0.05，重大变化走人工通道 | ✅ | `seeds.py:94` `platform.recalc_step=0.05`（另 `pcp.recalc_step` `:75`）；`service.py:1001-1010` 超限 `RecalcStepExceeded`→422（`router.py:535-537`）指向直编口；直编无幅度限制+审计 | — |
| Q43 | 17 池选项字典 CRUD+审计，选料只从字典选；17 池本身增删列后期 | ✅ | `core/pool_options/` + 迁移 `0052_pool_options`、`seeds.py:13-34`（16 池候选值，goal 归 Q25）；池名闭合集 re-export `pa_rules.WEIGHT_KEYS_17` | 17 池增删不做＝Q43 原文明示 |

## 5. 段 9 / 段 12 / 段 13 / 横切（23 条）

| # | PRD 口径 | 状态 | 证据 | 缺口 |
|---|---|---|---|---|
| Q44 | 内容目的配比＝软提示（任务页 30 天分布黄条 + 段13 健康度栏目），不硬拦 | ⬜ | 仅字典表有 ratio_min/max（`condition/models.py:43-46`、`router.py:93`） | 【无证据，未落地】无近 30 天分布聚合、无健康度栏目；`core/dashboards/` 仅 token_cost/review_workload 两盘。同 `docs/24:87`「未见独立落地」〔Q353 随等外部输入表插一行由 `:85` 下推；2026-10-14 随 docs/24 §5.2 增「灵感库本体」一行由 `:86` 下推为 `:87`〕 |
| Q45 | 三元组配一份复用，满 20 次/PCP 更新触发重配走 Gate | ✅ | `seeds.py:76` `package.reuse_threshold=20`；`layer_strategy/service.py:111-124` 查重→`PackageExists`；迁移 `0048_packages_active_triple_unique`；`final_whitelist/service.py:559-573` usage+1 与阈值审计；`platform_adaptation/service.py:579-607`；`router.py:152` reuse-pending；`layer_strategy/service.py:171-182` 清零+审计 | — |
| Q46 | layerSpaces 增删改仅平台级管理员，普通运营只读，变更显示影响面 | ✅ | `layer_strategy/router.py:26` `_admin_gate=require_internal_actor(PLATFORM_ADMIN)`，写口 `:211/:231/:255`；影响面 `router.py:198`+`service.py:244` 409 `{active_package_refs}`；审计 tenant=`_platform`；迁移 `0047_layer_spaces` | 管理端 UI 缺（docs/23 §11.20 孤儿读口含 layer-spaces） |
| Q47 | 三包必审线复用 Q9 的 0.85 同一配置项 | ✅ | Q9 键存在（`seeds.py:17`）；`docs/06:191` 契约表登记「0.85 细看线（复用 Q9）｜Q47」；〔**Q363 已接线（02 C1.305）**：`workbench/service.py:27`（`NEEDS_DETAIL_CONF_KEY = "fieldpool.needs_detail_conf"`）＋`:31-46`（`_payload_confidences` 递归收集 payload 全部 confidence 数值键）＋`:50-60`（`needs_detail()` 任一 conf `<` knob 即 True，边界 0.85 不标＝对齐 fieldpool `<` 语义；无 conf 不标＝不编造；非 package_draft 恒 False）＋`:140`/`:184`（`_enrich`／`_candidate_view` 富化 `needs_detail`）；单测 `test_workbench_needs_detail.py` 8 例＋集成 `test_review_workbench_api.py` 2 例；前端 `/admin/review-queue` 置信度单元格「需细看」徽标（`review-queue/page.tsx`，`admin.reviewQueue.needsDetail` 键＋check-admin 棘轮登记）。compute-on-read 零迁移零 schema，knob 调参即生效〕 | ~~**未接线**：`rg "needs_detail_conf" app/decision/layer_strategy/` 零命中，三包 conf 不触发任何必审~~ 已销（Q363：落点统一审核台而非 layer_strategy——三包候选经 WF-07 进审核台按同一键判需细看；`review.batch_pass_confidence`（`seeds.py:85`）仍是审核台批量通过用的另一键，两键消费者不同） |
| Q56 | 重生成上限 3 次（须有配置页面），超限转人工或作废回池记难产原因 | ✅ | 后端齐：`seeds.py:59` `content.regen_limit=3`；`content/statemachine.py:75-78`；`content/service.py:385-387` 超限 422；`service.py:450-486` `discard_content` reason 必填 + `content.discarded` 审计；迁移 `0032_content_discard`；〔**Q364 已补前端配置页（02 C1.306）**：`/admin/config` 运行配置台三件套 `frontend/app/[locale]/admin/config/{page.tsx,actions.ts,config-island.tsx}`＋`frontend/lib/api.ts` `getConfigItem`／`updateConfigItem`（配置中心读写均仅 platform_admin，Q113 未随 Q345 放宽 operations）；页＝只读 RSC 直读当前值＋版本元信息（版本/更新人/时间），修改＝client 岛→Server Action（本地 guard 缺身份/缺角色零请求；整数 ≥1 与种子 `config_center/seeds.py:107` `{"min": 1}` 同口径预检，值未变化禁发；成功 `router.refresh()`）；超限 422／键缺 404／越权 403 三态映射；侧栏治理组第 19 项＋`admin.systemConfigNav`／`admin.systemConfig.*` 15 键＋check-admin 棘轮 Q364 判据块登记〕 | ~~**无前端配置功能页**（Q56 明确要求）：前端全仓零 `regen_limit`／`/api/config` 引用，仅后端 `PUT /api/config/{key}`~~ 已销（Q364，见证据列） |
| Q57 | AI 质量分降级"辅助参考"，阈值 0.85 配置化 | ✅ | `content/quality.py:62-66` `quality_advisory_for`（不发证不驳回）；`seeds.py:58` `content.ai_quality_threshold=0.85`；前端明示文案 `messages/zh-CN.json` `.content.qualityAdvisoryNote` 渲染于 `content/[contentId]/page.tsx:106-112` | 段13 相关性校准后置（原文明示本期不做） |
| Q58 | 语言＝发布位市场 ∩ 产品语言，各语言版独立成品，清单配置化 | ✅ | `content/languages.py:51-82,154-170`（`fcw.country` ∩ `PS.target_languages`）；唯一约束 `(final_id,language,kind)` `content/models.py:46`；迁移 `0028_content_languages`；`router.py:400` set_target_languages | — |
| Q59 | 客户三动作 + 复检四项（词库/语义/施工指令/国家规则） | 🟡 | 三动作 ✅ `content/statemachine.py:7-10`、`service.py:367-374`（reject reason 非空 422）、`router.py:479`→`service.py:416` 改稿强制重跑复检；①② ✅ `service.py:172-196` + `content/semantic.py:1-15`（advisory） | **③④【待补】**：`service.py:180` 自注「施工指令核对/国家规则核对 原文未给实现口径，仍占位」；同 `docs/12:162`、`docs/05:381`（**Q354 随 docs/05 文末插 Q354 契约块 2 行，由 `:379` 下推＝`:381`**） |
| Q60 | 外部 Agent 推送制 `POST /api/effect-callback`；缺席记"—"、时序追加、(content_id,captured_at) 幂等 | ✅ | `core/effects/router.py:68-89`；`effects/service.py:96-125`（稀疏化不补 0）、`:236-305`（同键覆盖/新时点追加）；迁移 `0034_effect_records:61-66` `uq_effect_content_captured`；`tests/integration/test_effect_callback_api.py` | — |
| Q60a | 运营回填链接/ID 建映射；不对得上进孤儿队列人工认领 | ✅ | 迁移 `0033_content_publish:29-40`；`effects/router.py:295-308` 孤儿队列、`:211-269` 认领/批量、`:272-292` 解绑；迁移 `0035_effect_claims`；`effects/service.py:465-548` | 匹配仍只按 content_id，`platform_post_id` 只留存不自动绑定（docs/08:316） |
| Q60b | Agent 推送 API Key 鉴权，一 Agent 一 Key 可吊销 | ✅ | 迁移 `0019_agent_api_keys`；`core/api_keys/models.py`；`api_keys/service.py:124-135` `require_agent_key`；吊销 `api_keys/router.py:67`（docs/22:44 登记 platform_admin 红线） | — |
| Q60c | 客户点发布＝审批信号，运营实际发布并回填链接 | ✅ | `content/service.py:595-621` `set_publish_info`（operations 闸、仅 ready_for_publish）；`content/router.py:235-243` 待发布队列、`:302-312` 回填；迁移 `0033:7-8`（不新增 published 态） | — |
| Q61 | 中位数×5 且 ≥绝对门槛 → 候选 → 运营确认；倍数/门槛/窗口配置化 | 🟡 | 仅手工标注落：`condition/models.py:122-124`（is_hot/hot_at，"自动判定留段13"）、`condition/service.py:652-670`、`router.py:272-285`；`seeds.py:68-69` `hot.median_multiplier=5.0`/`hot.window_days=90` | 自动判定与运营转正未实现；两键全仓**仅命中种子行**（登记未接线）；绝对门槛键未登记 |
| Q62 | 本系统不做定时拉取调度 | ✅ | `app/main.py:74-116`（5 类 worker：SLA sweep/restock/export/import/fcw，无外部抓取）；入站唯一入口 effect-callback | — |
| Q63 | KUP 证据三关 + 记预期 + 2 周期对账 + 未兑现回滚 | ⬜ | 仅三键：`seeds.py:70-72` `kup.min_samples=30`/`min_lift_pct=0.5`/`consecutive_periods=2`（全仓仅命中种子行） | 【无证据，未落地】无提案/三关/预期/对账/回滚代码；docs/08:316,388 列为 P3 挂账 |
| Q64 | KUP 两级审批（单产品=运营，共享层=平台管理员），"PM"废除 | ⬜ | 仅角色常量 `core/rbac/__init__.py:18-24` | 【无证据，未落地】KUP 无对象可批；代码仍留 `agent.pm_audit_max_turns/tokens`（`seeds.py:80-81`）与 AG-PM-AUDIT 命名，与"废除 PM"口径不一致 |
| Q65 | 两张常设月度校准报表 + 样本≥50 提示可校准 | ⬜ | 仅键 `calibration.min_sample=50`（`seeds.py:73`，无消费方） | 【无证据，未落地】`core/dashboards/router.py:34,49` 只有 /token-cost、/review-workload；无分档对比/可校准提示/管理员发起调整 |
| Q66 | AI agent 不持 owner/审批角色；合规/财务窗口只配真人 | 🟡 | 机器凭证零角色 `api_keys/service.py:134`（`roles=[]`）；人员令牌仅签 5 个内部人角色 `staff_auth/service.py:32-39`；AI 只产候选、采用走 Gate | `internal_finance` 角色未定义（`rbac/__init__.py:18-24` 六角色无此项）；`runtime/agents/` 为空目录 |
| Q67 | 两表合一为一张模型注册表（per-1M）+ 场景→默认模型路由配置页；Key 唯一入口 | ✅ | `core/model_registry/models.py:36-63`（ai_models：input/output_price_per_1m、daily_budget、fallback）、`:87-92` ai_scene_routes；路由端点 `router.py:193-214`；迁移 `0014_model_gateway` | — |
| Q68 | 禁止 `fid:'-'` 落库（含 Layer1）；存量一次性"上户口" | ✅ | `modeling/c7.py:20-27` `IllegalFid`；`modeling/service.py:385-406,438`（模板 upsert 与 Layer4 强校验）；未知 fid 422 映射四处 router；**Q368（02 C1.310）候选 Gate 待办落地**＝c7 Layer4 与 wf02_dim_source 新建候选即开 `OpsTodo(field_candidate_gate, g2_field_candidate, assignee_role=dictionary_admin)`（`modeling/service.py` `_open_field_candidate_todo`／`fieldpool/service.py` `_persist`），同名复用不重复开；SLA 默认 7 天＝配置键 `fieldpool.candidate_gate_sla_days`（seeds + 迁移 0064 播种，业务热更） | 存量上户口扫描＝Q357 已补（`scripts/check_field_fid_registry.py`，只读不代处置，见下行划线注记）；存量"补 fid 还是建候选"由人裁（Q13 字典管理员） |
| Q69 | G1 模板变更只影响该类目未来新产品，存量不自动重算（重冻走 Q29） | ✅ | 主口径成立：`modeling/service.py:385-420` `upsert_template` 只写表+审计，**无下游传播/重算路径**；模板仅新建模运行时读（`:464`）；**Q29 重冻通道 ✅**＝`whitelist_center/service.py:423`（RefreezeReasonRequired）→`:425`（`refreeze_tier()` 分档）→`:505`（refreeze 落快照）→`:566`（event=refreeze）→`:619`（audit pws.refreeze，BO-07 人工执行），三档阈值 `pws_rules.py:34-51,88-92`＋配置键 `pws.refreeze_tier_map`（迁移 0062，Q361） | ✅ 已销（2026-10-16 Q365 账面订正，02 C1.307）：原缺口「Q29 三档重冻通道未实现」所依赖的事实已消失——Q361 销 Q29 时本行缺口未同步，属跨批账面漂移（同 Q362 代补 §6 #5 先例）；"是否重冻"落点＝`refreeze_tier()` 三档通道（BO-07） |
| Q70 | 第一期轻量审核台：统一列表（风险+时间排序）+ 各型挂 SLA + conf>0.85 批量通过 | ✅ | `core/workbench/router.py:54` candidates、`:76` batch-approve；`workbench/service.py` `_is_batch_eligible`（risk_rank DESC, created_at ASC；conf≤阈值即拒）；`workbench/risk.py:6-33` 四档归一；`seeds.py:85` `review.batch_pass_confidence=0.85`、`:87-91` 五型 SLA（迁移 `0022_review_sla_hours`） | 分配算法/10% 抽检按原文列第二期，非缺口 |
| Q71 | 白名单消费：按分降序 + Q24 去重写 usage_record + 保底补给（critical 50→target 100，冷却 5min） | ✅ | `condition/router.py:309-336` pwc/consume；`service.py:470-472` score.desc()、`:476-487/:514-523` 去重+写 usage、`:583-590` 跌破 critical 防抖补货；`seeds.py:31-34` | — |
| Q72 | 段-WF 映射以 CHAIN_13 为准（段8→WF-06、段2→WF-01、段13→WF-11+WF-12），不新增 WF | 🟡 | `docs/06:24-27` 已登记映射脚注"不新增 WF"；代码无 WF-13（`runtime/workflows/` 仅 WF-01/02/03/04/07） | 段13 的 WF-11/WF-12 **本体未落**（无 YAML、无 KUP-PROPOSE/DRIFT-DETECT/PROMPT-EVAL） |

## 6. 结构性硬闸与红线逐条（21 条）

| # | 硬闸/红线（docs/01 出处） | 状态 | 证据 | 缺口 |
|---|---|---|---|---|
| 1 | productIntake**15**（14 态 + 类目创建中） | ✅ | `product_intake/statemachine.py:9-23,26-42`（实测 `CATEGORY_CREATING="category_creating"` `:23`、标签 `:41`）、`:57-98` 转移表、`:44/:115` 终态拦截 | — |
| 2 | atom8 状态机（8 态） | ✅ | `atom/atom_rules.py:72-77`；`atom/service.py:706-792`（freeze/unfreeze/suspend/resume/reject/deprecate/archive） | 草稿·待审核活在候选侧（`atom_rules.py:65,71`），非同一张表——DP白石洲workspace实现形态差异，非缺口 |
| 3 | skill7 状态机（7 态） | ✅ | `core/skill7/schemas.py:10`；`service.py:452-512` 裁决→applied/archived | **`ai_suggested` 不持久化**（`service.py:3-4` 标【实现补，Q76】），枚举 6 态缺第 7 态——**〔Q365 两读法并存 → Q366 裁决已下（02 C1.308）〕** 负责人 2026-10-16 裁读法一＝Q76 定稿已裁：02 C1.20（line 312）负责人 2026-09-14 口径「进入通道即 pending_review（投递落库态），本切片不持久化 ai_suggested【实现补】」＝通道 6 态持久化即定稿 V1 口径 ⇒ 翻正 ✅；读法二（05 §2.3 原文 7 态字面）不采纳——ADR 定稿效力高于 PRD 字面 |
| 4 | approveAtomGuard **10 项** | ✅ | `atom/atom_rules.py:161-196`（违规码 `:98-106`）；⑩ `atom/service.py:394`（审计先于正式化） | — |
| 5 | pwsReadiness **5 项**就绪门 | ✅ | `whitelist_center/service.py:222,269-301`（5 checks；⑤＝池内挂起新字段候选数，`pending_field_count==0`，`:269-272` 注释钉死 PRD line 2634 口径）；`pws_rules.py:17-22`（≥3 原子/≥1 PWC 走配置中心）；fieldpool `_persist` 对已转正候选同名新维度直接回填 fid（跨 PS 复用不误挂） | ~~**⑤语义漂移**~~〔**Q361 已修正（02 C1.303）**：口径定为池内挂起的新字段候选数（FPDimension 引用未转正候选＝candidate_id 非空＋fid 空，Q13 转正前）；**Q362 代补翻正本行**＝Q361 已销于 §8.1/§0 但本表行未同步，合龙欠账照 Q359 补 Q358 先例补齐〕 |
| 6 | FCW 组装 **7 项 Guard** | ✅ | `final_whitelist/fcw_rules.py:86-192`（G1–G7，实测常量 `:29-35`）；`service.py:412` 未全绿不发证 | — |
| 7 | final_id **单一出口**红线 | ✅ | `final_whitelist/exit_guard.py:50-82`（mapper before_insert 强制 issue_scope，越权抛 `OutsidePublishFCW`）；`models.py:3`；`service.py:541` E1_owner=publishFCW | 覆盖边界：Core insert／裸 SQL 不经 mapper，已在 `exit_guard.py:11-14` 显式留痕 |
| 8 | PCP **17 字段**权重池 + Σ≤1.0 | ✅ | `pa_rules.py:11-29` WEIGHT_KEYS_17；`:56-68` 校验器；`models.py:153-178` pcp_weight_tables | — |
| 9 | C1 行业置信阈值**三档**（0.90/0.80/0.85） | ✅ | 迁移 `0002_m2_stage2:198-220` 播种三档；`modeling/models.py:49-51`；`service.py:204` 默认档缺失拒绝 | 食品/母婴种子缺（见 Q7） |
| 10 | C7 模板**四层兜底** | ✅ | `modeling/service.py:442-445`(L1)/`:447-475`(L2)/`:477-485`(L3)/`model_registry/c7_resolve.py:45-199`(L4) | — |
| 11 | platformRules **selector 4 层** + country + 跨层 R-X01~X05 | 🟡 | `pa_rules.py:34-44` SELECTOR_LEVELS、`:116-124` country 入 condition_key、`:139-149` 同级取最严；`models.py:104-114` | **R-X01~X05 跨层矛盾检测未落**（`models.py:97-99` 标【原文未给出，待补】） |
| 12 | publishSlots **四维静态分** + AI 拓展候选四维全 0 + pending_gate | ✅ | `platform_adaptation/models.py:62-72`（traffic/safe/conv/load + score_source）；`pa_rules.py:31,89-96` 聚合；**Q368（02 C1.310）入口闭环**＝`service.py` `create_ai_slot_candidate`（四维强制 0.0、gate=GATE_PENDING、score_source=ai）/`approve_slot_candidate`（人工评估转 approved/manual_eval）；schema `SlotAiCandidateItem` `extra=forbid`（防传分）；普通 upsert exclude gate | — |
| 13 | slotRuleByType **13 类**默认值（含单账号日发布限量） | 🟡 | 迁移 `0008_m11_stage78:82-90` `slot_type_defaults`；`models.py:117-133` daily_limit_min/max | **13 类未种子**：约 40 列原文未给出，`defaults` JSON 占位（`models.py:120-122`） |
| 14 | 平台层 **4 条红线** | ✅ | `models.py:262-263`、`service.py:920-940`（approve 只解除 pending、`advisory_only:True`，唯一出口仍是段11）；AI 候选一律 pending_review（`:895-917`） | — |
| 15 | 合规底座 **4 维**（CP-BAN/CP-DOWN/CP-LAW/CP-CLEAN） | ✅ | CP-BAN/DOWN：`compliance_wordlist` 表 + action=ban/downgrade + downgrade_target（迁移 `0004:27`，字典 `0051`）；CP-LAW：`cp_law_sensitive_domains`（`0007:38`）+ law_reviews；CP-CLEAN：`ccr_rules.py:18,96` status=clean；**Q361：CP-BAN 默认 6 词（permanent removal/cure/treat/根治/保证有效/100%）已种子＝迁移 0061（critical/ban/base/active，ON CONFLICT DO NOTHING，downgrade 四列指纹删，02 C1.303）** | — |
| 16 | 国家级规则 **R-030/R-031/R-032** + countries 事实库 | ⬜→**V2** | 【Q350 裁乙案随 V2，02 C1.293】Q347 实测零落库属实（无 `countries` 表／无 GDPR/NMPA/FDA 代码引用）；**负责人明示接受 scope cut：V1 段10 以「核心清洗 ✅（CP-BAN/CP-DOWN/CP-CLEAN＋law_review）、国家级管辖扩展层随 V2」交付**——三管辖规则文本（GDPR 留资字段/NMPA/FDA 措辞）无权威来源，硬做即臆造红线。〔裁决前证据原文保留：仅存于 `docs/10:220`、`docs/04:259` 规格登记〕 | **不再计为 V1 缺口**（V1 口径 ⬜6→⬜5）；V2 启动前提＝业务方给三管辖权威文本 |
| 17 | Agent **三条边界**（max_turns+max_tokens+emergency_stop） | 🟡 | `config_center/seeds.py:78-83` 登记三组数（10/8000、6/6000、20/4000） | **emergency_stop 与 Agent 注册表本体未落**（seeds 注"注册表本体在 M12"，无代码） |
| 18a | RBAC 红线操作须对应角色 + 人工 Gate | ✅ | PWS 冻结 `whitelist_center/router.py:90`+`service.py:72-76`；原子正式化 `atom/router.py:31`；合规废弃 `atom/router.py:33`；Prompt 修改 `model_registry/gateway.py:233` PLATFORM_ADMIN | ⚠ 已裁决偏差：PWS 冻结由 PRD 的 BO-07 改判 operations（Q329/Q242 乙），见 §9-⑦ |
| 18b | Prompt 治理（只读 + 编辑必走 ChangeProposal + 版本 +0.1） | 🟡 | `model_registry/gateway.py:234-246`（v0.1 起步、minor+1、`skill_prompt_versions` 追加 + append_audit） | **无 ChangeProposal 实体**（走 `publish_prompt` 直写+审计）；版本恒 `v0.N` 非通用 +0.1 |
| 18c | 资金 freeze/refund/correct 必走 HumanGate | ⬜ | 【无证据，未落地】实测 `ls backend/app` 六域（product/platform/decision/final/content/core）**无 billing 包**；`rg "billing" backend/app/` 仅命中 `config_center/seeds.py`、`tenants/service.py`（价格配置） | 无二次确认+writeAudit 的资金动作实现 |
| 18d | 模型注册表为 LLM **唯一入口** | ✅ | `core/model_registry/`（迁移 `0014`：ai_models/ai_model_keys/ai_scene_routes；`gateway.py` 唯一调用口） | — |

## 7. 已裁决偏差（不是缺口，但 intentional 与 PRD 字面不一致）

| 项 | PRD 原文口径 | 现行实现 | 裁决出处 |
|---|---|---|---|
| PWS 冻结角色 | BO-07（docs/01 line 7674） | operations | Q329/Q242 乙案，`whitelist_center/service.py:73-76` |
| V1 范围 | Q73：段 1→6→10→11 | 段 12/13 主体已超范围落地（Q116–Q136） | docs/08 §1.3 + §2.3 推进实际 |
| 段 13 回流链路 | 客户/运营发布链 | 客户确认→运营发布并回填→Agent 推送 | Q60c |

## 8. 缺口清单（按可处置性归类）

### 8.1 V1 范围内、纯工程可自推（建议优先，1 条 🟡）〔Q366：Q9 经负责人 2026-10-16 裁读法一翻正已销（02 C1.308，下行划线），未销仅剩 Q7 阈值待业务口径；Q363：Q9 行处置建议（哨兵测试）Q357 已落地，条目按严格读法仍 🟡、两读法并存（见 §3.2 Q9 行与下行注记）；Q362：Q21/Q25/Q26/Q51 四条已销，表中保留删除线行；Q361：Q29 与硬闸 #5/#15 已销；Q350：Q11 簇与 Q30 两条已销〕

> 这 1 条未销项（Q7 阈值待业务口径）的存在，是「docs/23 §8.1 写的 V1 主链全部 ✅」与「本档条级判定」的唯一差异来源——差异不是矛盾，是**粒度**：前者判"这段能不能跑"，本档判"这条有没有按定稿口径做完"。

| 条 | 缺口一句话 | 处置建议 |
|---|---|---|
| ~~Q11 + Q14 + Q49~~ | ~~旗标全仓零赋值，三路径恒不触发~~ **Q350 已裁甲并落地（02 C1.293）**：Q7 派生＋0057 种子 | ✅ 已销（2026-10-12） |
| Q7 | ~~缺食品/母婴种子~~ Q350 已补迁移 0057（0.85 默认档）；**残留**：原文 0.90 阈值待业务权威确认 | 待业务方给阈值口径后改配置（纯配置，无工程缺口） |
| ~~Q9~~ | ~~"魔法数字禁止硬编码"无强制手段~~ **Q366 裁决已下（02 C1.308）**：负责人 2026-10-16 裁读法一——Q357 哨兵测试已满足处置口径 ⇒ 翻正 ✅（§3.2 Q9 行） | ✅ 已销（2026-10-16） |
| ~~Q16~~ | ~~候选列表未按亲和度排序~~ **Q360 已裁甲并落地（02 C1.302）**：三列表加 `sort` 参数，读口 `sort=affinity` | ✅ 已销（2026-10-14） |
| ~~Q18~~ | ~~AI 自动补证据一轮 + 运营待办~~ **Q360 已落地（02 C1.302）**：ATOM-EVIDENCE 场景（operations 显式端点）＋evidence todo_type 待办 | ✅ 已销（2026-10-14） |
| ~~Q19~~ | ~~`pick_cluster_keeper` 未接线自动推荐~~ **Q360 已落地（02 C1.302）**：members 读口返推荐值＋resolve 可省略 keeper | ✅ 已销（2026-10-14） |
| ~~Q20~~ | ~~原子"恢复重走审核"~~ **Q360 已落地（02 C1.302）**：新增 `/atoms/{id}/restore`（对标 fieldpool restore） | ✅ 已销（2026-10-14） |
| ~~Q21~~ | ~~检测项开关/顺序配置化 + 排序限量截断~~ **Q362 已落地（02 C1.304）**：`pwc.detectors`＋`pwc.prefilter_rules` 两 json 键（迁移 0063 播种），评分后降序限量截断、blocked 留痕不占口径、审计计数 truncated | ✅ 已销（2026-10-15） |
| ~~Q25~~ | ~~录入端"内容用途"未绑定 ContentGoal 字典~~ **Q362 已落地（02 C1.304）**：submit 闸校验 ContentGoal active 枚举，非法值 InvalidContentUsage→422 | ✅ 已销（2026-10-15） |
| ~~Q26~~ | ~~预筛未实现 ⇒ "跳预筛"无从验证~~ **Q362 已落地（02 C1.304）**：预筛 stage 随 Q21 落地，`source != "manual"` 分支＝手拼跳预筛、合规不豁免 | ✅ 已销（2026-10-15） |
| ~~Q29~~ | ~~重冻三档清单未配置化~~ **Q361 已落地（02 C1.303）**：`pws.refreeze_tier_map` 配置键＋迁移 0062 播种，`refreeze_tier()` 读 knob | ✅ 已销（2026-10-15） |
| ~~Q30~~ | ~~②③④ 占位~~ **Q350 已裁甲并回填（02 C1.293）**：`_apply_q30_dispositions()` | ✅ 已销（2026-10-12） |
| ~~Q51~~ | ~~只扫 frozen 快照，未接 draft FCW 与段12 未发布成品~~ **Q362 已落地（02 C1.304）**：段12 未发布成品同扫（命中快照的 PS 集合内、排除 discarded、三发布列任一为空、body 命中词条→content_product 待办，internal_compliance，幂等） | ✅ 已销（2026-10-15） |
| ~~#5~~ | ~~readiness ⑤ 语义漂移（pending_gate FieldPool 数 vs 字段）~~ **Q361 已落地（02 C1.303）**：口径定为**池内挂起的新字段候选数**（FPDimension 引用未转正候选＝candidate_id 非空＋fid 空，Q13 转正前），而非池子数；fieldpool `_persist` 对已转正候选的同名新维度直接回填 fid（跨 PS 复用不误挂） | ✅ 已销（2026-10-15） |
| ~~#15~~ | ~~CP-BAN 默认 6 词未种子~~ **Q361 已落地（02 C1.303）**：迁移 0061 纯数据种子（critical/ban/base/active，downgrade 指纹删） | ✅ 已销（2026-10-15） |
| ~~Q35/#12~~ | ~~AI 新位"四维 0 + pending_gate"无入口~~ **Q368 已落地（02 C1.310）**：`ai-candidate` 建候选（四维强制 0、gate=pending_gate、score_source=ai，extra=forbid 防编分）＋`approve` 人工评估转正（非 pending 409）；普通 upsert 排除 gate | ✅ 已销（2026-10-17） |
| ~~Q68 待办~~ | ~~g2FieldCandidate 挂运营待办未实现~~ **Q368 已落地（02 C1.310）**：c7 Layer4 与 wf02_dim_source 新建候选即开 `field_candidate_gate` 待办（dictionary_admin），同名复用不重复开；SLA 键 `fieldpool.candidate_gate_sla_days`（迁移 0064） | ✅ 已销（2026-10-17） |
| #16 | ~~国家级规则 R-030/031/032 + countries 零实现~~ **Q350 裁乙案随 V2**（02 C1.293）：V1 显式 scope cut，不再算 V1 缺口；V2 待业务方三管辖权威文本 | ✅ 已裁决（2026-10-12） |

### 8.2 需外部规格输入（工程侧不可自推）

| 条 | 等什么 |
|---|---|
| Q35/#12 | PLATFORM-ADAPTER 真模型供应商 + AI 新增发布位档案流程 |
| Q38 | AI 降级动作组合的生成路径 + schema（docs/12:150【待补】） |
| Q41 | AI 重算生成器；`pcp.recalc_*` 与"事件→权重"映射规则（业务方） |
| Q44 | 配比健康度栏目的口径与页面归属（产品口径） |
| Q59 ③④ | 复检"施工指令核对/国家规则核对"的实现口径【原文未给】 |
| ~~Q68 存量~~ | **✅ 2026-10-14 Q357 已补扫描器**＝`backend/scripts/check_field_fid_registry.py`（只读、不代处置；黑户落库/悬空引用＝阻断 exit 1，非 active 字段引用与 `c7_runs` 历史留痕只报不改、`pending_gate` 候选计数＝提示，缺表或无 `alembic_version` 行＝exit 2）｜**余下的是裁决不是工程**：真扫出存量后"补 fid 还是建候选"由人定，转正权限归 Q13 字典管理员 |
| #11 | R-X01~X05 跨层规则【原文未给出，待补】 |
| #13 | slotRuleByType 约 40 列默认值【原文未给出】 |
| Q61 | 爆款绝对门槛与自动判定是否提前点工 |
| Q63/Q64/Q65 | KUP 分析面是否提前点工（现列 P3/V2） |
| 结算 | ~~agnes 视频 `mode`~~〔**Q353 订正**：`mode` 三值（`text`／`keyframe`／`reference`）与异步轮询契约已由官方接入文档 `wiki.agnes-ai.com/zh-Hans/docs/agnes-video-25` 取得，不再属"待供应商"；本项改记＝供应商侧**免费档视频队列容量**（现测按官方形状两发均 `503 video_queue_full`，成功路径仍未验证）＋**接线三件待拍**（docs/19 清单二第 17 项：异步任务态落点／失败与超时口径／成本·限流·是否过 Gate），且真视频驱动属我方实现缺口（`drivers.py` 现只有 synthetic 与 OpenAI chat）〕＋转写契约（待供应商）、复检名单/agency 价格/支付通道（待业务方）、现网部署＋真 ACME〔**Q354 落地**＝「接线三件待拍」已**裁毕并落地**（docs/19 清单二第 17 项销账，02 C1.297）＝新表 `video_generation_tasks`（迁移 0059）＋异步驱动 `video_drivers.py`＋`approve` 逐单人工 Gate（唯一花钱口、四写口全 operations 凭证硬闸）＋**零自动重试**（失败/超时置终态＋开运营待办）＋配置中心当日秒数上限 120＋门控 `LOOM_VIDEO_REAL_ENABLED` 默认关＋第 7 个 sweep 作业。本台账 96 条计数**不变**（真视频生成不属 Q1–Q72 任一条目，也非结构性硬闸）。**仍未证的只有外部条件**＝供应商队列容量与首次成功样本（11 次实测全 `503 video_queue_full`，末次 2026-10-14）。〕 |

### 8.3 与原文明示"本期不做"一致，非缺口

Q37 自动采集｜Q43 第 18 池｜#17 之外 Agent 注册表本体｜Q70 分配算法与 10% 抽检｜#18c 资金 HumanGate（随计费 V2）｜Q56 段13 相关性校准｜Q57 段13 相关性校准｜段12 video 转写/成片复检（待供应商/待业务方）。

## 9. 本批新坐实的 8 处（条级事实，段级文档未写入）

1. **Q11↔Q7 联动断裂**：`rg "sensitive_industry *=" backend/app/` **零命中** —— 旗标只有列定义（default=False）与 18 处读取，无任何写入点 ⇒ Q11 强制、Q14 敏感批大小、Q49 兜底三条路径在真实数据下恒不触发。〔**Q350 已修复（02 C1.293）**：迁移 0057 补 Q7 食品/母婴敏感种子＋`_derive_industry_flags()` 在 `start_modeling` 派生写入；本条作为 Q347 时点事实原文保留〕
2. **Q30 ②③④ 是代码内自注的占位**（`whitelist_center/service.py:424-432`），不是文档没写——docs/13:98 已登记①，但 ②③④ 至今仍是 `draft_fcws_voided=[]`／`published_marked_outdated=0`。〔**Q350 已回填（02 C1.293）**：`_apply_q30_dispositions()` 替换占位，② draft 作废＋queued 重组装／③ forced 待复查／④ published 计数＋提醒，三例测试；本条作为 Q347 时点事实原文保留〕
3. **国家级规则零落库**：`rg "create_table('countries'|R-030"` 零命中，而 R-030/R-031/R-032 属 docs/01 段10 硬规格（V1 范围内）。〔**Q350 裁乙案随 V2（02 C1.293）**：负责人明示接受 V1 scope cut，本条事实成立但不再计为 V1 缺口（⬜6→⬜5）；原文保留〕
4. **Q63/Q64/Q65 是"配置项已登记、零消费方"**：三个 `kup.*`／`calibration.*` 键全仓只命中 seeds 行；`Q61` 的 `hot.*` 同型。
5. **Q47 只有文档登记、零代码**：`docs/06:191` 写明"复用 Q9"，但 `app/decision/layer_strategy/` 无消费。〔**Q363 已落地（02 C1.305）**：接线落点统一审核台 `workbench/service.py`（三包候选经 WF-07 以 package_draft 进审核台，`_enrich`/`_candidate_view` 富化 `needs_detail`，复用 `fieldpool.needs_detail_conf` 同一键；前端「需细看」徽标），条目 🟡→✅（见 §5 Q47 行）；本条作为 Q347 时点事实原文保留〕
6. **#5 语义漂移**：实现把 PRD 的「pending_gate 字段=0」落成「pending_gate 的 FieldPool 数=0」，两者在"池已批但池内字段还在挂起"场景下结论相反。**Q361 已修正（02 C1.303）**＝口径定为**池内挂起的新字段候选数**（FPDimension 引用未转正候选：candidate_id 非空＋fid 未回填，Q13 转正 Gate 前）；fieldpool `_persist` 对已转正候选（approved）的同名新维度行直接回填转正字段 fid——「已转正字段」不再计为挂起，跨 PS 同名复用不误挂（详见 §8.1 #5 销账行）。
7. **#18a 已裁决偏差**：PWS 冻结角色由 PRD 的 BO-07 实际为 operations（Q329），需在 PRD 侧补注记或在代码侧回归原文。
8. **#3/#18b 形态差异**：skill7 缺持久化 `ai_suggested`（Q76 实现补）；Prompt 无 ChangeProposal 实体（直写+审计）。〔**Q366 裁决注记（02 C1.308）**：#3 之 skill7 半句经负责人 2026-10-16 裁读法一——Q76 定稿口径即 V1 定稿口径 ⇒ 不再计为差异，§6 #3 行翻正 ✅；本条作为 Q347 时点事实原文保留。〕

## 10. 判定口径与维护规则

- **与 docs/20 三层判定的关系**：本档衡量「01 PRD 逐条是否满足」；docs/20 衡量「核心主链可用性」；docs/24 衡量「产品全景段级覆盖」。三者口径不同、不冲突，也**不可互相替代**。本档不改变三层判定（① 达标／② 达标／③ 未达标＝现网部署＋真 ACME 未证）。
- **维护规则**：
  1. 每批如关闭/新开本档任一条目，须同批更新该行状态与证据，并在 docs/02 该批条目注明。
  2. 状态只准停在三种 ✅/🟡/⬜；写证据时必须给 `文件:行号`、迁移号或配置键名三者之一，禁止"已实现"三字。
  3. 证据随时间失效的行号，按 Q309 先例**只追加新行号并标日期**，不回改原文。
  4. 本档每条证据必须能被 §1 的四条命令之一复现；无法复现的写【无证据，未落地】而非臆断。

> **信息保全**：本档全部判定来自 2026-10-11 对仓库的实测读取；凡【原文未给出，待补】处照抄上游文档口径，未作补全。口令/密钥一律不写入本档。
