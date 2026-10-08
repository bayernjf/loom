# 24 · 功能点比对报告（对照 ContentOS 产品基准）

> **性质**：产品基准 vs 实现现状的逐功能点覆盖度比对，含未做/部分项清单与推进建议。
> **基准来源（外部，未改动仅读取）**：
> - `/Users/jiangfeng/Downloads/项目2-loom-重要/ContentOS_核心业务主链梳理_v1.md`（13 段主链 + §10 规则定稿 Q1–Q72 + §10.9 配置化清单；文件名 v1 系历史命名，实为 2026-07-22 版）
> - `/Users/jiangfeng/Downloads/项目2-loom-重要/ContentOS_SaaS后台完整体系全景图_V1.0_项目北极星.html`（33 项功能点清单，含远期规划项）
> **实现现状侧基线**：docs/23 §8 功能点全景 + docs/09 全景体系各菜单实现注记 + docs/02（最高 C1.264＝Q321）+ handoff（Q321 后基线 1207 passed＋10 skipped／收集 1217、头 `0052_pool_options`、71 表·766 列）。
> **登记**：本报告随 Q322 批落地（2026-10-09，docs/02 C1.265，纯文档零代码零迁移零测试变化）。

## 0. 结论摘要

1. **核心主链完成度高**：13 段链中 **9 段闭环**（段1/2/4/5/6/8/10/11/13）、**4 段部分**（段3/7/9/12）；V1 主链段1→6→10→11 与段12/13 主体已落地，docs/20 三层判定 ① 功能覆盖达标／② 核心完全可用达标不变。
2. **「全部搞完」≠ 是**：按产品文档全景口径，剩余未做项全部属 **V2 厚度／V3 辅助系统／周边** 与 **3 个已定位的待规格或未点工项**，不阻塞已判定的核心可用。
3. **未做/部分项可归三类**：① 外部规格依赖（DIM-SOURCE 来源规格、PLATFORM-ADAPTER 真模型、fit_score 自学习数据源、agnes 视频 `mode`）；② 未点工大项（video-studio 段12 视频支线、WF-07 AI 选包 4 Skill、段9/12 运行期字典强校验）；③ V2/V3 规划（KUP 分析面、知识库/Memory/客户门户等 P5 厚度、辅助系统 10 个、周边商业/账号/BI/Webhook/SDK/移动端/国际化/白牌）。

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
| 段3 字段池 | FIELDPOOL-PLAN、DIM-SOURCE 7 路（Q8 定稿＝来源路由表）、DIM-MERGE、维度红线 | g2FieldCandidates 候选、同义词、usage 计数 | 🟡 部分（DIM-SOURCE 来源路由表规格【原文未给，待补】） |
| 段4 原子 | ATOM-EXPAND/CANON/AFFINITY、approveAtomGuard 10 项、atom8 | Atom 生产、LLM 扩写、审批/集群/冻结/吊销/暂停/归档 | ✅ 闭环 |
| 段5 PWC | PWC-BUILDER、COMBO-VALIDATE、PWC-SCORING、漏斗（预筛→检测→评分→限量） | PWC Builder LLM、组合包、restock 唯一 requested 写者（Q83） | ✅ 闭环 |
| 段6 PWS | pwsReadiness 5 项就绪门、版本化、revoked 急停、重冻三档 | PWS 包、17 权重池、规则；冻结管理引擎层 Q250＋专用 UI Q319 | ✅ 闭环 |
| 段7 平台适配 | PLATFORM-ADAPTER 四态、publishSlots 四维、fit_score、动态信号 | 静态底表全套、动态信号三口（Q259）、PCP 重算候选/HumanGate（Q300）、fit_score 可解释化＋人工校准（Q296/Q299）、只读预览口（Q296） | 🟡 部分（真模型业务接入、fit_score 真自学习未落） |
| 段8 PCP | 17 字段权重池、Σ≤1.0 统一校验、每周重算 | 17 权重池＋Σ≤1.0 校验（pa_rules）、17 池选项字典（Q308）、每周重算提醒（Q294） | ✅ 闭环 |
| 段9 三包 | CSP/CSTP/CEP（三元组复用）、layerSpaces 通用底座、contentGoals 配比软提示 | 三包建模/查重（Q288 部分唯一索引）/发证解析/复用阈值（Q263）/重配（Q264）、layerSpaces（Q262） | 🟡 部分（WF-07 AI 选包 4 Skill ⬜ 占位未定稿；配比软提示仪表盘未见独立落地） |
| 段10 合规 | 合规词库合并（Q48）、law_review（Q49）、国家规则优先（Q50）、生效即扫（Q51） | CCR 词库三层裁决、复检、snapshot；law_review Guard⑥ | ✅ 闭环 |
| 段11 FCW | 7 项 Guard（Q53）、单一出口、score＝0.4/0.3/0.3 仅排序（Q54）、全自动发证（Q55） | 组装 7 Guard、单出口闸、发证落快照、冻结管理（作废/留痕/重冻） | ✅ 闭环 |
| 段12 内容生成 | ARTICLE-GEN/VIDEO-SCRIPT/MULTILANG-GEN/CONTENT-COMPLIANCE、客户审阅三动作、重生成上限 3 次 | ARTICLE-GEN、多语言（Q119/Q123）、词库复检＋语义级检测（Q121）、AI 质量分（Q120）、客户审阅（Q122）、discarded 态（Q124）、发布回填（Q125） | 🟡 部分（video-studio 视频支线未点工） |
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
- **🟡 部分**：完整 7 大活水机制（部分）、6 种 AI Skill 全部上线（部分，WF-07 4 Skill ⬜）、知识库系统（V2 未做）、Memory 6 层（V2 未做）、客户自助门户（V2 未做）、Multi-model Router（V2 未做）、跨表亲和度自学习（V2 未做）。
- **⬜ 未启动（V3/周边）**：Knowledge Graph、Simulation Sandbox、Golden Cases 标杆库（Evaluation+Golden 已在 V1）、Drift Detection、完整 BI 仪表盘、Webhook 推送体系、SDK 嵌入式集成、移动端、国际化（多语言界面）、白牌定制方案。

## 5. 未做/部分项清单（含溯源）

### 5.1 外部规格依赖（工程侧不可自推）

| 项 | 阻塞 | 出处 |
|---|---|---|
| DIM-SOURCE 7 路来源路由表 | 原文未给【待补】 | docs/09 D3.5、docs/02 Q8 相关挂账 |
| 合理性校验「8 种检测名单＋综合评分公式」 | 原文未给【待补】，禁臆造 | docs/09 D3.5-3 |
| PLATFORM-ADAPTER 真模型业务接入 | 等供应商规格＋eval/golden | docs/02 Q296/Q300、design-v2-platform-adapter-business |
| fit_score 真自学习 | 被学的量无数据源（Q293 材料待裁） | docs/02 Q296/Q299 |
| agnes 视频 `mode` 合法取值 | 原文未给【待补】 | Q254 实测五种全 400 invalid mode |
| 付费档第 5 档额度 | 业务方给数 | docs/23 §8.5 |

### 5.2 未点工大项（纯工程，需点工）

| 项 | 现状 | 出处 |
|---|---|---|
| video-studio 段12 视频支线（白名单信息区/分段编辑器/内容清洗区/生成结果区） | VIDEO-GEN 引擎预备切片已落（Q252），载体/业务链路待点工 | docs/23 §8.5、Q252 |
| WF-07 AI 选包四 Skill（docs/12 #21–24） | 全 ⬜ 占位未定稿 | docs/23 §8.3 P2、docs/12 |
| 段9/12「选料只能从字典里选」运行期强校验 | docs/02:141/:155 一字未改 | docs/09 Q310 补登 |

### 5.3 V2/V3 规划（未做，不阻塞 MVP）

- 段13 KUP 提案/爆款自动判定/校准报表（Q61/Q63/Q65）
- P5 厚度：知识库系统（D3.7）、Memory 6 层（D3.13）、客户自助门户、反馈归因分析页、跨表亲和度自学习
- V3 辅助系统 10 个（D3.12）：Knowledge Graph/Evidence Center/Simulation Sandbox/Rollback Center/Drift Detection/Human Feedback Loop/Context Pack Builder（Evaluation+Golden 已在 V1）
- 周边（D9.5）：计费订阅（D3.11-6）、社媒账号管理、完整 BI、Webhook 推送体系、SDK 嵌入、移动端、国际化界面、白牌定制
- 内容目的配比软提示仪表盘（Q44）：未见独立落地，随段9 后续核对

## 6. 判定口径

- 与 docs/20 MVP 三层判定关系：本报告衡量「产品全景 100% 功能点」覆盖，docs/20 衡量「核心主链可用性」——两者口径不同、不冲突。核心主链维度：**① 功能覆盖达标／② 核心完全可用达标（Q295 翻正后保持）**；③ 可上线未达标（现网部署＋真 ACME 未证）不变。
- 比对结论不新增裁决，未做项按既有挂账/点工口径推进，禁止工程侧臆造外部规格。

## 7. 推进建议（2026-10-09 时点）

- **可一口气推进（纯工程/纯文档，无外部规格依赖）**：
  - A. docs/24 本报告落地＋文档合龙（本批 Q322）
  - B. 段9/12 运行期字典强校验（Q43 17 池字典已落载体，把「选料只能从字典里选」接到执行器；属可自推代码批，需点工）
  - C. video-studio 载体切片（VIDEO-GEN 引擎已备，可先做白名单信息区/生成结果区等不依赖 `mode` 取值的面）
- **需拍板/等外部输入**：DIM-SOURCE 规格、8 种检测名单＋评分公式、agnes 视频 `mode`、PLATFORM-ADAPTER 真模型供应商、fit_score 自学习数据源、付费档额度、KUP 分析面是否提前点工。
