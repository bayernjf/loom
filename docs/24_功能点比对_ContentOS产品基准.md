# 24 · 功能点比对报告（对照 ContentOS 产品基准）

> **性质**：产品基准 vs 实现现状的逐功能点覆盖度比对，含未做/部分项清单与推进建议。
> **基准来源（外部，未改动仅读取）**：
> - `/Users/jiangfeng/Downloads/项目2-loom-重要/ContentOS_核心业务主链梳理_v1.md`（13 段主链 + §10 规则定稿 Q1–Q72 + §10.9 配置化清单；文件名 v1 系历史命名，实为 2026-07-22 版）
> - `/Users/jiangfeng/Downloads/项目2-loom-重要/ContentOS_SaaS后台完整体系全景图_V1.0_项目北极星.html`（33 项功能点清单，含远期规划项）
> **实现现状侧基线**：docs/23 §8 功能点全景 + docs/09 全景体系各菜单实现注记 + docs/02（最高 **C1.306＝Q364**）+ handoff（**Q364 基线＝Q56 重生成上限配置页前端切片（管理端 `/admin/config` 运行配置台，本批只放 `content.regen_limit` 一项、页内分区留扩展位）：**纯前端批，零后端零迁移零测试变化**，后端照 Q363 时点引用 1437 passed＋11 skipped／收集 1448（本批未复跑）、头仍 `0063_pwc_funnel_knobs_seed`（本批零迁移）、75 表·821 列、迁移文件 63、`GATED` 仍 **48**、前端 tsc＋七检查器全绿、管理端侧栏 18→**19**、前端 ts/tsx 116→**119**（git ls-files 116 tracked＋3 untracked 新文件）**；Q363 时点快照＝Q47 三包必审线接线（复用 Q9 `fieldpool.needs_detail_conf`，统一审核台 needs_detail 富化＋前端徽标）／Q9 台账合龙注记（两种读法并存）：1437 passed＋11 skipped／收集 1448（全量单跑 76.24s）、头仍 `0063_pwc_funnel_knobs_seed`（本批零迁移）、75 表·821 列、迁移文件 63、`GATED` 仍 **48**、前端 tsc＋七检查器全绿**；Q362 时点快照＝段6 PWC 漏斗批（Q21 检测项开关/顺序配置化＋评分后排序限量截断／Q26 手拼跳预筛／Q25 内容用途绑 ContentGoal／Q51 段12 未发布成品扫描）：1427 passed＋11 skipped／收集 1438（全量单跑 80.38s）、头 `0063_pwc_funnel_knobs_seed`（0063 纯数据种子零建表）、75 表·821 列、迁移文件 63、`GATED` 仍 **48**（本批零新写口）、零建表零前端**；Q361 时点快照＝B 类工程缺口批（#5 readiness ⑤ 语义修正／#15 CP-BAN 6 词种子／Q29 重冻三档配置化）：1419 passed＋11 skipped／收集 1430（全量单跑 96.62s）、头 `0062_pws_refreeze_tiers_seed`（0061/0062 纯数据种子零建表）、75 表·821 列、迁移文件 62、`GATED` 仍 **48**（本批零新写口）、零迁移零前端；Q360 时点快照＝段4 原子缺口批一次收口（Q16/Q18/Q19/Q20）：1409 passed＋11 skipped／收集 1420（全量单跑 117.29s）、头仍 `0060_inspiration_entries`（Q358 新建 1 表后未再变）、75 表·821 列、迁移文件 60、`GATED` 46→**48**（＋2 均 OPS＝AI 补证与原子恢复两新写口，见 `test_write_gate_wiring.py` 注释标 Q360）、零迁移零前端；Q357 时点快照＝**1392 passed＋11 skipped／收集 1403、头 `0059_video_generation_tasks`（新建 1 表）、74 表·811 列、迁移文件 59、覆盖率 `app/` 71.16%〔14,732 语句／missed 4,249〕／核心层 99.34%〔604，持平〕、操作面 251（写 144／读 107）、`GATED` 58、sweep 作业 7**；Q352 快照＝**1328 passed＋10 skipped／收集 1338、头 0058、73 表·787 列、71.14%〔14,331／missed 4,136〕**；Q351 快照＝**1315 passed＋10 skipped／收集 1325、头仍 0057（同窗口修订 0057）**；Q350 快照＝**1303 passed＋10 skipped／收集 1313**；Q346–Q349 基线为 **1297 passed＋10 skipped／收集 1307**〔Q346 本机带 `--cov` 复跑 198.24s；Q345 曾同数复跑 210.19s，Q343 双证原文见上方保留；此前多处抄写的「1273」是含 2 例沙箱误红的读数，与「收集 1285」不能同时成立；Q344/Q345 两批零后端改动、读数不变；Q346 是后端读闸批，涨的 22 条全在读闸矩阵测试里；Q347/Q348/Q349 三批纯文档零后端改动、读数不变〕、头 `0056_video_segments_objects`、73 表·787 列、覆盖率 `app/` **71.39%**〔14,238 语句／missed 4,074；Q343 读数 71.40%／14,245〔CI runner 同 SHA 71.41%〕，分母 −7＝Q346 删掉一条只认 operations 的读闸 helper〕／核心层 99.34%〔604 语句，持平〕；管理端侧栏 **19** 项＝Q364 新增「运行配置」`/admin/config`（18 项＝Q359 新增「灵感库」`/admin/inspiration-entries`；17 项＝Q345 新增「平台适配台」`/admin/platform-adaptation`；16 项＝Q344 新增「回滚中心」`/admin/change-ledger`）——本行由 Q364 刷新，前值 C1.305＝Q363／C1.304＝Q362／C1.303＝Q361／C1.302＝Q360（Q358/Q359 头部基线漏刷、随 Q360 一并补登）／C1.300＝Q357／C1.289＝Q346／C1.288＝Q345／C1.287＝Q344／C1.286＝Q343／1273 passed／71.85%）。
> **登记**：本报告随 Q322 批落地（2026-10-09，docs/02 C1.265，纯文档零代码零迁移零测试变化）。

## 0. 结论摘要

1. **核心主链完成度高**：13 段链中 **9 段闭环**（段1/2/4/5/6/8/10/11/13）、**4 段部分**（段3/7/9/12）；V1 主链段1→6→10→11 与段12/13 主体已落地，docs/20 三层判定 ① 功能覆盖达标／② 核心完全可用达标不变。
2. **「全部搞完」≠ 是**：按产品文档全景口径，剩余未做项全部属 **V2 厚度／V3 辅助系统／周边** 与 **3 个已定位的待规格或未点工项**，不阻塞已判定的核心可用。
3. **未做/部分项可归三类**：① 外部规格依赖（DIM-SOURCE 来源规格（第 7 路 `case_evidence` 已随 **Q325** 落地，七路种子齐全）、PLATFORM-ADAPTER 真模型、fit_score 自学习数据源（映射逻辑已落 **Q325** `fit_learning.py`，真指标数据源仍待）、agnes 视频 `mode`）；② 待规格大项（video-studio 段12 业务链路面：载体已落 Q323、管理端两屏 UI 已落 Q324、分段视图/内容清洗区操作面已随 **Q328** 落地〔S1 只读分段视图＋S2 脚本复检＋script-recheck 口〕，分段编目＋对象存储已随 **Q336** 落地〔`video_segments` 实体＋`video_objects` 登记＋MinIO 代理流，迁移 0056〕，剩转写/成片复检【待供应商/待业务方】；WF-07 四 Skill 规格已定稿（**Q325**，docs/12 §3.2）且四场景已注册模型网关 synthetic（**Q326**，纯数据迁移 0054＋20 例），**操作面已随 Q328 落地**〔`POST /api/ai-select/suggest` 只产候选、采用走统一审核台〕；段9/12 字典强校验已 Q323 核实收口）；③ V2/V3 规划（KUP 分析面、知识库/Memory/客户门户等 P5 厚度、辅助系统 10 个、周边商业/账号/BI/Webhook/SDK/移动端/国际化/白牌）。

## 1. 比对方法

- 以产品主链 md 的 §2 各段功能点 + §10 定稿规则（Q1–Q72）为功能点权威；
- 以 HTML 全景图 33 项为补充视角（多为 V2–V3 远期规划）；
- loom 侧逐段对照 docs/23 §8（官方功能点现状）与 docs/09（菜单级实现注记），个别项回代码核验（C1 信号权重、Σ≤1.0 校验、Prompt 模板、模型注册表）；
- 状态口径沿用 docs/23 §8：✅ 已落地｜🟡 部分/缓做｜⬜ 未启动。

## 2. 13 段链覆盖度矩阵

| 段 | 功能点（产品基准） | loom 落地 | 判定 |
|---|---|---|---|
| 段1 产品录入 | 产品注册、状态机、G2 字段、ProductSpace、Onboarding 派生 | 产品注册、G2 字段（12/18 落，迁移 0024）、ProductSpace、Onboarding 派生 | ✅ 闭环（G2 余 6 未知字段【待补】，Q115） |
| 段2 冷启动/C1/C7 | C1 类目识别（五信号、行业阈值三档、三分支）、C7 四层兜底模板、15 态 | C1 类目识别（LLM 解析，c1.py）、C7 Layer1–4（LLM-C7-RESOLVE） | ✅ 闭环 |
| 段3 字段池 | FIELDPOOL-PLAN、DIM-SOURCE 7 路（Q8 定稿＝来源路由表）、DIM-MERGE、维度红线 | g2FieldCandidates 候选、同义词、usage 计数 | 🟡 部分（DIM-SOURCE 第 7 路 `case_evidence` 已随 **Q325** 落地，七路种子齐全；来源路由完整规格原六路 Q8 已定稿） |
| 段4 原子 | ATOM-EXPAND/CANON/AFFINITY、approveAtomGuard 10 项、atom8 | Atom 生产、LLM 扩写、审批/集群/冻结/吊销/暂停/归档 | ✅ 闭环 |
| 段5 PWC | PWC-BUILDER、COMBO-VALIDATE、PWC-SCORING、漏斗（预筛→检测→评分→限量） | PWC Builder LLM、组合包、restock 唯一 requested 写者（Q83） | ✅ 闭环 |
| 段6 PWS | pwsReadiness 5 项就绪门、版本化、revoked 急停、重冻三档 | PWS 包、17 权重池、规则；冻结管理引擎层 Q250＋专用 UI Q319 | ✅ 闭环 |
| 段7 平台适配 | PLATFORM-ADAPTER 四态、publishSlots 四维、fit_score、动态信号 | 静态底表全套、动态信号三口（Q259）、PCP 重算候选/HumanGate（Q300）、fit_score 可解释化＋人工校准（Q296/Q299）、adapter 只读预览口**已真调模型网关**（`platform_adaptation/service.py:808` `gateway.invoke(SCENE_PLATFORM_ADAPTER, …)`，Q296；候选表＋approve/reject HumanGate＝Q300）、fit_score 自学习 **advisory 已接线**（Q352＝`fit_learning` 产出附到 `GET /fit-score` 的 `learning` 键＋平台适配台新增一列） | 🟡 部分〔Q352 订正：旧句「真模型业务接入未落」经复验**已过期**（调用点存在，见现状列），本段真缺口收窄为＝**自学习仍只是 advisory**（门控 `LOOM_FIT_LEARNING_ENABLED` 默认关、不写回四维静态分、不进任何 Gate；Q293 定的四份业务规则含「观察窗与回溯口径」仍缺权威文本，现默认 90 天＝工程甲案）〕 |
| 段8 PCP | 17 字段权重池、Σ≤1.0 统一校验、每周重算 | 17 权重池＋Σ≤1.0 校验（pa_rules）、17 池选项字典（Q308）、每周重算提醒（Q294） | ✅ 闭环 |
| 段9 三包 | CSP/CSTP/CEP（三元组复用）、layerSpaces 通用底座、contentGoals 配比软提示 | 三包建模/查重（Q288 部分唯一索引）/发证解析/复用阈值（Q263）/重配（Q264）、layerSpaces（Q262） | 🟡 部分（WF-07 四 Skill 规格已定稿（**Q325**，docs/12 §3.2）＋操作面已落地（**Q328**：`POST /api/ai-select/suggest`＋组装台「AI 选包建议」区＋apply_package_draft 字典强校验）；配比软提示仪表盘未见独立落地） |
| 段10 合规 | 合规词库合并（Q48）、law_review（Q49）、国家规则优先（Q50）、生效即扫（Q51） | CCR 词库三层裁决、复检、snapshot；law_review Guard⑥ | ✅ 闭环 |
| 段11 FCW | 7 项 Guard（Q53）、单一出口、score＝0.4/0.3/0.3 仅排序（Q54）、全自动发证（Q55） | 组装 7 Guard、单出口闸、发证落快照、冻结管理（作废/留痕/重冻） | ✅ 闭环 |
| 段12 内容生成 | ARTICLE-GEN/VIDEO-SCRIPT/MULTILANG-GEN/CONTENT-COMPLIANCE、客户审阅三动作、重生成上限 3 次 | ARTICLE-GEN、多语言（Q119/Q123）、词库复检＋语义级检测（Q121）、AI 质量分（Q120）、客户审阅（Q122）、discarded 态（Q124）、发布回填（Q125）、video 载体后端切片（Q323） | 🟡 部分（video-studio 业务链路面：载体 Q323＋两屏 UI Q324＋分段/清洗操作面 Q328＋分段编目实体＋原片留档 Q336；剩转写/成片复检【待供应商/待业务方】）。**〔Q354 订正〕段12 真视频生成任务已落地**＝新表 `video_generation_tasks`（迁移 0059，74 表·811 列）＋异步驱动 `video_drivers.py`（提交→`video_id`→轮询→顶层 `url`）＋逐单人工 Gate（`approve` 是唯一花钱口）＋零自动重试（三种失败一律终态＋开运营待办）＋配置中心当日秒数上限＋第 7 个 sweep 作业；门控 `LOOM_VIDEO_REAL_ENABLED` 默认关，**成片不回写 body**（入库口径属下一片） |
| 段13 反馈回流 | effect-callback 推送制（Q60）、孤儿认领（Q60a）、爆款自动判定（Q61）、KUP 证据三关（Q63）、两级审批（Q64）、校准报表（Q65） | effect-callback 入站（Q126）、孤儿认领（Q127/Q129）、customer-backfill（Q128/Q131/Q136）、运营台（Q130）、批量 CSV 回填（Q156） | ✅ 主体（KUP 提案/爆款自动判定/校准报表属 V2 分析面未做） |

## 3. 横切治理覆盖

| 横切规则（产品基准） | loom 落地 | 判定 |
|---|---|---|
| AI 仅产候选、人工 Gate 批准（skill7 状态机） | skill7 通道、统一审核台（Q70/Q93/Q314 读/裁分权） | ✅ |
| Agent 三边界（max_turns+max_tokens+emergency_stop） | A2A 任务面（Q150）＋Agent 边界 | ✅ |
| RBAC 红线操作 | RBAC 双命名空间、内部角色（Q297）、写口 `require_internal_actor`（Q242） | ✅ |
| Prompt 治理（ChangeProposal+版本） | Prompt 模板库（model_registry） | ✅ |
| 资金 HumanGate | 计费模块 V2 未做 | 🟡 随计费 |
| 模型注册表合并（统一 per-1M） | model_registry（价格/预算/fallback） | ✅ |

## 4. HTML 全景图 33 项对照

- **✅ 已落**：产品空间（字段池+原子管理）、平台层 16 张底表（基础版）、策略层 13 张底表（基础版）、白名单组装引擎（核心）、候选池审核工作台、AI Skill 注册表+编排器、6 个治理驾驶舱、RBAC+租户管理、客户入驻 Onboarding、CSV 导出对接中台、客户前端 8 大菜单（基础版）、反馈归因系统（操作面）、版本快照管理（PWS/FCW 族）、类目管理（G1 类目种子）、API 对接中台（导出 JSON＋A2A/MCP）。
- **🟡 部分**：完整 7 大活水机制（部分）、6 种 AI Skill 全部上线（部分，WF-07 四 Skill 规格已定稿 Q325＋操作面已落地 Q328）、知识库系统（V2 未做）、Memory 6 层（V2 未做）、客户自助门户（V2 未做）、Multi-model Router（V2 未做）、跨表亲和度自学习（V2 未做）。
- **⬜ 未启动（V3/周边）**：Knowledge Graph、Simulation Sandbox、Golden Cases 标杆库（Evaluation+Golden 已在 V1）、Drift Detection、完整 BI 仪表盘、Webhook 推送体系、SDK 嵌入式集成、移动端、国际化（多语言界面）、白牌定制方案。

## 5. 未做/部分项清单（含溯源）

### 5.1 外部规格依赖（工程侧不可自推）

| 项 | 阻塞 | 出处 |
|---|---|---|
| ~~DIM-SOURCE 7 路来源路由表~~ **〔2026-10-14 订正〕路由表早已齐、旧挂账关闭**：迁移 `0003` 播 6 路（含 `common_inspiration`／`product_inspiration`）、`0053` 补第 7 路 `case_evidence`（Q325），消费方 `model_registry/field_plan.py` 动态读 enabled 路由 ⇒ "原文未给"不成立；该项真缺口改记为「**灵感库本体未建**」，已移入 §5.2（纯工程、非外部规格） | 已无外部阻塞 | docs/10:113、迁移 0003／0053、docs/25 Q8 行 |
| 合理性校验「8 种检测名单＋综合评分公式」 | 原文未给【待补】，禁臆造 | docs/09 D3.5-3 |
| PLATFORM-ADAPTER 真模型业务接入 | 等供应商规格＋eval/golden | docs/02 Q296/Q300、design-v2-platform-adapter-business |
| fit_score 真自学习 | 被学的量无数据源（Q293 材料待裁） | docs/02 Q296/Q299 |
| agnes 视频 `mode` 合法取值 | ~~原文未给【待补】~~ **〔Q353 已取得，本行改判〕＝规格不再待补**：官方接入文档 `wiki.agnes-ai.com/zh-Hans/docs/agnes-video-25` 写明 `mode` 三值 `text`／`keyframe`／`reference`＋全参数＋异步轮询契约；**真卡点换成两件**＝供应商侧免费档队列常满（现测两发均 `503 video_queue_full`，成功路径仍未验证）＋**我方无异步视频驱动**（`drivers.py` 只有 synthetic 与 OpenAI chat，`generation.py:214` 把返回当 chat JSON `{"video_ref"}` 读）。旧句"待补"的来由＝Q254 只翻了 `AgnesAI-Models` 模型目录（那份确实不列 `mode`），未翻 video 接入页＝取证面不足 | Q254 五种候选全 400／**Q353 订正**、docs/19 清单二第 6 项与第 17 项 |
| ~~段12 真视频接线（Q353 新增待拍三件）~~ → **已裁已落（Q354）**；剩外部条件＝**供应商侧视频队列容量＋首次成功样本** | 供应商侧（非裁决） | docs/19 清单二第 17 项**已销账**（三件全按甲落地，02 C1.297）；我方驱动/表/Gate/上限都已在仓内，实测到「参数被供应商接受」为止（11 次全 `503 video_queue_full`，2026-10-14 复测仍满），**拿到 `video_id` 并轮询到 `completed` 的真成功仍未证**，故 `test_video_drivers.py` 留一条缺 key 即 skip 的真供应商用例 |
| 付费档第 5 档额度 | 业务方给数 | docs/23 §8.5 |

### 5.2 未点工大项（纯工程，需点工）

| 项 | 现状 | 出处 |
|---|---|---|
| video-studio 段12 视频支线（白名单信息区/分段编辑器/内容清洗区/生成结果区） | VIDEO-GEN 引擎预备切片已落（Q252）＋后端载体切片已落（Q323 `invoke_video_gen`＋kind 分流＋7 测试）＋管理端两屏 UI 已落（Q324：白名单信息区/生成结果区只读）；**Q326** 内置浏览器两屏验收通过并修复屏2 跨租户详情 404（新增管理端 `GET /api/admin/content/{id}` 跨租户只读口＋前端改调）；分段视图/内容清洗区操作面已随 **Q328** 全部按推荐甲落地（design-video-studio-segment-cleaning.md 已翻 ✅：S1 只读分段视图〔屏3〕＋S2 脚本复检〔屏4〕＋`GET /api/admin/content/{id}/script-recheck`）；分段编目＋对象存储已随 **Q336** 落地（①③甲），剩转写（agnes 契约【待供应商】）/成片复检（名单【待业务方】）） | docs/23 §8.5、Q252、Q323、Q324、Q326 |
| WF-07 AI 选包四 Skill（docs/12 #21–24） | ✅ 规格已定稿（**Q325**，docs/12 §3.2 四份 v0.1）＋操作面已随 **Q328** 落地（`runtime/workflows/WF-07.yaml`＋`POST /api/ai-select/suggest`＋组装台「AI 选包建议」区；AI 只产候选、采用走统一审核台） | docs/23 §8.3 P2、docs/12 §3.2、Q325 |
| 段9/12「选料只能从字典里选」运行期强校验 | Q323 核实收口：goal 维度强校验已闭环（E1.1 `_validate_goal` 404＋PWC `unknown_goals` 判红，只认 Q25 目的字典）；其余 16 池为 PCP 权重维度无自由池值输入点；Q38 六码随段7 点工挂账 | docs/02 C1.266、Q323 |
| 灵感库本体（product-inspiration，产品基准段3 的法定拆维度来源，MVP 模块） | ✅ **2026-10-14 Q358 已建**（纯工程，零外部规格）：新建 `inspiration_entries` 表（通用层 tenant 内共享／产品专属层绑定 product_space_id 两层）＋ `app/product/inspiration/` CRUD（`/api/admin/inspiration-entries` list/create/update/delete，写口 `operations`＋`platform_admin` 内部角色闸，读口同档）＋ `field_plan.py` 在 DIM-MERGE 调用时按 tenant/layer 拉取 enabled 条目灌入提示词 `inspiration_entries` 变量、`seeds.py` DIM-MERGE 模板同步引用 `$inspiration_entries` 并指示 `source_ref` 写 `inspiration:<entry_id>`；迁移 `0060_inspiration_entries`（零种子，禁止臆造）＋ **2026-10-14 Q359 前端已落**＝`/admin/inspiration-entries` 运营配置台（列表/过滤/新建/行内编辑/启停/删除；读侧 Q307 契约逐角色 append roles、写侧三岛 Server Action，管理端侧栏第 18 项）。**余一项需运营复核**＝已播种 production DB 里那条 DIM-MERGE `skill_prompts` 模板需在管理端重发一版把 `$inspiration_entries` 真正写进（fresh-install 已正确），否则存量库模型仍取不到灵感内容（属 prompt 再发布动作，不静默代裁） | 产品基准 §2 段3（灵感库＝通用＋产品专属两层）、docs/25 Q8 行、docs/02 C1.301 |

### 5.3 V2/V3 规划（未做，不阻塞 MVP）

- 段13 KUP 提案/爆款自动判定/校准报表（Q61/Q63/Q65）
- P5 厚度：知识库系统（D3.7）、Memory 6 层（D3.13）、客户自助门户、反馈归因分析页、跨表亲和度自学习
- V3 辅助系统 10 个（D3.12）：Knowledge Graph/Evidence Center/Simulation Sandbox/Drift Detection/Human Feedback Loop/Context Pack Builder 仍未启动；**Rollback Center 甲案只读聚合面已落**＝`GET /api/admin/change-ledger`（Q334）＋管理端 `/admin/change-ledger` 屏（Q344），乙＝Prompt 版本回滚写口／丙＝通用快照-恢复未裁（乙标 `no_surface` 挂账，design-v3-rollback-center.md）；Evaluation+Golden 已在 V1〔**2026-10-14 订正**：本行原把 Rollback Center 平列在"未做"里，与其甲案已落地的事实不符〕
- 周边（D9.5）：计费订阅（D3.11-6）、社媒账号管理、完整 BI、Webhook 推送体系、SDK 嵌入、移动端、国际化界面、白牌定制
- 内容目的配比软提示仪表盘（Q44）：未见独立落地，随段9 后续核对

## 6. 判定口径

- 与 docs/20 MVP 三层判定关系：本报告衡量「产品全景 100% 功能点」覆盖，docs/20 衡量「核心主链可用性」——两者口径不同、不冲突。核心主链维度：**① 功能覆盖达标／② 核心完全可用达标（Q295 翻正后保持）**；③ 可上线未达标（现网部署＋真 ACME 未证）不变。
- 比对结论不新增裁决，未做项按既有挂账/点工口径推进，禁止工程侧臆造外部规格。

## 7. 推进建议（2026-10-09 时点）

- **可一口气推进（纯工程/纯文档，无外部规格依赖）**：
  - A. docs/24 本报告落地＋文档合龙（Q322 已落地）
  - B. 段9/12 运行期字典强校验核实收口（**Q323 已落地**：goal 维度强校验已闭环（E1.1 `_validate_goal` 404＋PWC `unknown_goals` 判红，只认 Q25 目的字典）；其余 16 池为 PCP 权重维度、组装请求仅 goal/platform/slot/country 无自由池值输入点 ⇒ 无运行期自由输入；Q38 六码运行期强校验随段7 真模型接入点工挂账；落点＝`pool_options/service.py` docstring 消费方声明）
  - C. video-studio 载体后端切片（**Q323 已落地**：`invoke_video_gen`＋`_run_generation` kind 分流＋`generate_content` video 放行＋router VideoGen 三异常（404/409/502）＋`test_content_video_api.py` 7 例；管理端两屏 UI（白名单信息区/生成结果区）已随 Q324 落地，分段视图/内容清洗区操作面已随 **Q328** 落地，分段编目＋对象存储已随 **Q336** 落地（①③甲），剩转写/成片复检【待供应商/待业务方】）
- **需拍板/等外部输入（Q325 后）**：~~agnes 视频 `mode`~~〔**Q353 订正**：`mode` 取值已从官方接入文档取得（`text`／`keyframe`／`reference`＋异步轮询契约），该项不再是"等外部规格"；**新外部输入＝供应商侧免费档视频队列容量**（现测两发均 `503 video_queue_full`）＋**新增活跃待裁＝docs/19 清单二第 17 项三件**（异步任务态落点／失败与超时口径／成本·限流·是否过 Gate），且**接线本身要我方写异步视频驱动**〕、PLATFORM-ADAPTER 真模型供应商、fit_score 自学习真指标数据源、KUP 分析面是否提前点工。（**Q325 已按推荐落地**：DIM-SOURCE 第 7 路 `case_evidence`、8 检测名单＋评分公式定稿、付费档第 5 档 `agency`＋五档额度、三口角色加闸、fit_score 映射模块、WF-07 四 Skill 定稿。）（**Q326**：WF-07 四场景已注册 synthetic、video-studio 两屏浏览器验收并修复跨租户详情口；新增待裁＝video-studio 分段/清洗＋WF-07 操作面 **D1–D5**〔见 design-video-studio-segment-cleaning.md〕，**Q328 已全部按推荐甲裁决并落地（档已翻 ✅）**。）
