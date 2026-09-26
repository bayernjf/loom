# Loom · AI 导向文档库（文档地图与治理）

> **本目录定位**：由原始文档《Loom_核心业务主链梳理_v3.md》（原唯一事实源，**已于 2026-09-13 归档删除，内容 100% 迁入本库**）与《Loom_SaaS后台全景图.html》（展示层，保留）**忠实切分**而来的多份 AI 导向文档。**本目录现为项目唯一事实源体系。**
> **切分原则**：不丢失任何信息——原文全部内容（含 line 行号引用、Q 编号、表格、状态词）均保留在下列文档中；本 README 末尾附**信息保全映射表**，可逐项核验。
> **生成日期**：2026-09-13；v3 归档删除经段落级核验（231 段，业务信息零丢失，仅 8 段元说明措辞差异，详见 §5.3）。

---

## 1. 文档索引

| 文档 | 信息源（v3.md） | 用途 / AI 消费场景 | 优先级 |
|---|---|---|---|
| [01_PRD_产品需求规格.md](./01_PRD_产品需求规格.md) | Part A 全量（A1–A7） | 产品需求规格：13 段链、各段功能/实体/规则、硬闸、数值约束、实现范围 | 核心 |
| [02_决策记录_ADR_Q1-Q72.md](./02_决策记录_ADR_Q1-Q72.md) | Part C 全量（C1 + C2） | 决策日志：Q1–Q72（v3 原文）+ Q73–Q216（持续追加，C1.17–C1.160）+ 配置化清单 | 核心 |
| [03_技术风险与红旗清单.md](./03_技术风险与红旗清单.md) | Part B 全量（B1 + B2） | 技术红旗（S/A/B 三级）与裁决状态、业务方参考映射 | 核心 |
| [04_契约层_数据模型.md](./04_契约层_数据模型.md) | Part A/C/D 提取 | 实体与字段级数据模型（AI 落代码） | 最高优先 |
| [05_契约层_API与状态机.md](./05_契约层_API与状态机.md) | Part A/C 提取 | API 契约 + 全部状态机定义（AI 落代码） | 最高优先 |
| [06_契约层_WF与Skill协议.md](./06_契约层_WF与Skill协议.md) | Part A/D 提取 | Workflow、PT 协议、Skill 注册表、Agent（AI 落代码） | 最高优先 |
| [07_技术架构与工程规格.md](./07_技术架构与工程规格.md) | Part A/D 提取 + 工程建议 | 模块边界、编排运行时、配置中心、RBAC、成本治理、工程建议 | 中优先 |
| [08_迭代计划与任务包.md](./08_迭代计划与任务包.md) | Part A7 + Part D9 | 路线图（两套已裁决合并，Q73）+ V1/V2/V3 任务包 | 核心 |
| [09_全景体系_展示口径.md](./09_全景体系_展示口径.md) | Part D 全量 + HTML 核对 | 展示口径全景：4 端/6 层/13 菜单/权限矩阵/中台/前端/反馈 | 参考 |
| [10_数据模型Schema_建表定义.md](./10_数据模型Schema_建表定义.md) | 04 字段清单 → 建表级 | 🟢 已补：35 实体建表要素（类型建议/约束/索引/关系） | 🟢 首轮 DBA 复核 2026-09-20（head 0036／58 表零漂移）；其后二～四轮逐批复核至 head 0040（**62 表／666 列／219 业务索引，零漂移**）；**第五轮已取消＝Q207 起由 CI `Migration gate` 每次 push 在真 PG16 上自动比对**（docs/10 §4、docs/17 §7.7） |
| [11_API规范_OpenAPI.md](./11_API规范_OpenAPI.md) | 05 契约 → OpenAPI | 🟢 已补 §2.1–2.8：效果回流族（含 Q156 CSV／Q160 Excel／Q161 异步任务三口）＋白名单消费＋中台 CSV/JSON 导出与任务口＋6 层原料包＋管理端只读台＋Key 治理＋**E1.1 发证两口（Q205 补）**，另有通用规范（§3，原文未定义处标【建议】）与未定稿补规格模板（§4） | 段13 效果回流全链与**三种批量回填（CSV／Excel／异步任务，前端岛轮询随 Q174）均已落地并在 §2.1 逐口登记**（旧「回填批量表格/CSV 随 V2」「含四端点规格」为过期口径，2026-09-26 订正）；发证两口鉴权见 §2.8；**仍随 V2／【待补】**：效果反哺与 Q54·Q57 校准算法口径、content_id↔platform_post_id 自助映射、Agent 抓取与发布自动化（Q62 不抓取）、中台对接 API/SDK（D4）。**口径边界**：11 号只收**已定稿接口**，不是实现面全量清单——全量以 `app.openapi()`（`/openapi.json`）为准，2026-09-26 实测 **175 路径／206 操作** |
| [12_PT协议补齐清单.md](./12_PT协议补齐清单.md) | 06 协议 → 补齐工程 | 🟢 已补：7 定稿 + 35 推断候选（**Q115 收口：即为最终名单**）+ 补齐模板 | 名单已定稿，不再待 HTML 核对 |
| [13_状态机迁移表.md](./13_状态机迁移表.md) | 05 状态机 → 迁移矩阵 | 🟢 已补：**14 组**状态机迁移表（含 §1.12 字段池 Gate、§1.13 content_products/Q116、§1.14 段13 效果回流/Q126–Q131）；productIntake15 迁移行 Q112 据实现补登 | G1 审核流随 V3、PWC 复核/待入库两行【待补】；§1.8 平台适配（段7）为设计规格、实现随 V2 P1；§1.9 发布位 gate 默认值与实现差异~~待拍板~~**已于 2026-09-18 Q118 拍板**（V1 仅 Q42 人工直编口径，02 C1.62；docs/13 §1.9 已载） |
| [14_技术选型决策.md](./14_技术选型决策.md) | 07 §7 工程建议 → 决策 | ✅ **已定稿**：6 项 2026-09-13 拍板（全采纳建议） | 已拍板，下游已同步 |
| [15_代码结构与脚手架.md](./15_代码结构与脚手架.md) | 07 架构 → 代码落位 | 🟢 已定稿：目录/模块/可执行物 + 技术栈（FastAPI/Next.js/YAML） | 可作脚手架依据 |
| [16_测试策略.md](./16_测试策略.md) | Guard/Q/契约 → 测试计划 | 🟢 已补：分层测试 + 规则级测试清单 | 与 12 联动；接 eval/ 两件套 |
| [17_部署与运维.md](./17_部署与运维.md) | 07/09 §11 → 运维 | 🟢 已定稿：环境/CI-CD/多租户/监控 + 中间件版本 | 可作环境搭建依据 |
| [18_前端i18n与设计Token方案.md](./18_前端i18n与设计Token方案.md) | 14/09 + Q58/Q73 + **Q96** → 前端工程 | ✅ **Q96（2026-09-16）拍板定稿**：next-intl + `[locale]`（V1 仅 zh-CN）+ 设计 Token 三层模型（CSS Modules/CSS 变量），色值借 AntD5 调色板（只借值不装依赖），§2.4/§3.6 可直接落码 | M12 前端按此逐片点工 |
| [19_private_beta主数据录入模板.md](./19_private_beta主数据录入模板.md) | 08 §2.2 Checklist #2 + Q149 → 业务方/运营 | private beta 首批主数据录入模板：publish_slots/PCP/三包字段与调用示例，最小集合＝1 个 final_id；**§0.2「最小可发证清单」（Q206）把"必填"收到代码真实要求**——只有 1 个 active 发布位（不看 `gate` 档）＋该 PS×平台一条 active PCP＋三包各一条 active，四维分／risk／source_url／fit 权重／slot_type_defaults **都不卡发证**；另 §0.1 载明令端口径分岔（发证两写口自 Q203 无条件要 `loom_staff_` Bearer） | beta 验收 #6 前置；待业务方回填 |
| [19_业务方回填指引.md](./19_业务方回填指引.md) | 19 衍生 | 业务方纯操作指引（中文）：去 API/字段技术细节，只留步骤＋字段占位表，给非工程读者；完整口径仍见 19 正文 | 业务/运营 |
| [19_business_master_data_guide.md](./19_business_master_data_guide.md) | 19 衍生 | 业务方纯操作指引（英文版 / English version）：同上内容的 English version | 业务/运营（英文） |
| [19_待办清单.md](./19_待办清单.md) | 20 §11 衍生（Q215 / 02 C1.159） | MVP 复评结论拆成两张可转发清单：清单一「要填什么」给业务/运营（两个人＋四样数据＋两坑＋自检工具）、清单二「要裁决什么」给负责人（网关/TLS、首批主数据=两个人、V2 客户认证、排期三列），并列出已结掉的 #32/#33/#34 勿重复列为待办 | 负责人 / 业务方（分转） |
| [21_运营SOP_全链操作手册.md](./21_运营SOP_全链操作手册.md) | private beta 平台代运营 → 运营/负责人 | 段1→13 逐步操作（角色/端点/页面/Gate）+ 常见 4xx/5xx 处置 + 日常运维节奏；步骤经 Q169 全链 e2e 实测 | ✅ 2026-09-22 落地（Q170） |
| [20_MVP评审_2026-09-22.md](./20_MVP评审_2026-09-22.md) | 2026-09-22 立项评审 ＋ **2026-09-25 Q199 重判报告（§7）** → 负责人/运营 | 功能性/完整度/可上线性评审：MVP 判定＝受控 private beta 有条件 GO（Q73 口径 + Q144 三判准）；门禁实测 **966 passed＋10 skipped**（总收集 976）/ eval 101/101 / 前端八 checker 全绿；**本文不是一页结论，是逐批复评台账**：§6 原始评审（Q144 口径）→ §7 Q199 重判 → §8 Q202 再判 → §9 Q203 收口 → §10 Q204 CI 首读（§9.3／§10.1 另有 Q209 追记：real-infra 真容器门已进 CI），各批数字均为当批实测快照、**不回改**；现行判定＝**① 功能覆盖达标／②「核心完全可用」未达标（工程侧卡点已于 Q203 清零，唯一卡点＝四表主数据零行）／③ 可上线未达标（另有网关与 TLS 归属待裁决）**——三层不可合并成一句"达到 MVP"。 | ✅ 已回读（2026-09-22 Q161 后）；结论不变，文档滞后已闭合。**其后五度复评**（Q199／Q202／Q203／Q204／Q207，本文 §7–§10 与 02 C1.143–C1.152）把判定拆成三层且不合并；现行卡点＝四表主数据零行（外部输入）＋网关与 TLS 归属（待裁决） |
| [design-a2a-vassal.md](./design-a2a-vassal.md) | Q150 → Zeus 联邦 A2A 封臣接入 | loom 作为 Zeus 第二封臣的设计草案：Agent Card/x-zeus-fealty 契约、三 skills plan 模式、JSON-RPC 任务层、认证复用 Q88 Agent Key、审计租户 `_platform`；第一阶段已落地（02 C1.94） | ✅ 第一阶段已落地（plan 模式）；第二阶段（持久化/真 LLM/真机联调）待点工 |
| [design-identity-layer-v2.md](./design-identity-layer-v2.md) | Q195 → 身份层第二切片 | **⬜ 待拍板**：客户侧认证与 `actor↔tenant` 归属的三个口径选项（含 A/B/C 三问各甲乙丙），附 10 条**实测**现状（205 路由、92 个自带 `actor` 的请求体模型、122 处审计写入、`assert_intake_admitted` 仅 1 处消费、导出任务口与导入口归属不对称）与改造爆炸半径 | ⬜ 待负责人拍板（A/B/C 三问，禁代裁） |
| [handoff-archive-2026-09-18.md](./handoff-archive-2026-09-18.md) | handoff 进度归档（2026-09-18 首次；09-13 ~ 09-17 进度条目 + 已销账待办详细过程，逐条原文） | 只读历史；权威逐片台账仍是 docs/02 C1 | 归档 |
| [handoff-archive-2026-09-19.md](./handoff-archive-2026-09-19.md) | handoff 进度归档（2026-09-19 首次并续写；Q118–Q126 滚出条目，逐条原文） | 只读历史；权威逐片台账仍是 docs/02 C1 | 归档 |
| [handoff-archive-2026-09-20.md](./handoff-archive-2026-09-20.md) | handoff 进度归档（2026-09-20；Q128/Q129/Q130/Q131 四片滚出条目原文，续写 Q132） | 只读历史；权威逐片台账仍是 docs/02 C1 | 归档 |
| [handoff-archive-2026-09-21.md](./handoff-archive-2026-09-21.md) | handoff 进度归档（2026-09-21；Q133–Q135 基建三件、Q136 批量 CSV、Q153 DBA 复核、Q137–Q140 接线四件滚出原文，续写 Q141–Q143／Q147／Q148） | 只读历史；权威逐片台账仍是 docs/02 C1 | 归档 |
| [handoff-archive-2026-09-22.md](./handoff-archive-2026-09-22.md) | handoff 进度归档（2026-09-22；Q149、Q150–Q152、Q153–Q154 滚出条目原文） | 只读历史；权威逐片台账仍是 docs/02 C1 | 归档 |
| [handoff-archive-2026-09-23.md](./handoff-archive-2026-09-23.md) | handoff 进度归档（2026-09-23；Q158 异机备份恢复、Q159–Q161 批量回填收口＋MVP 评审、Q162–Q165 一口气四片滚出原文） | 只读历史；权威逐片台账仍是 docs/02 C1 | 归档 |
| [handoff-archive-2026-09-24.md](./handoff-archive-2026-09-24.md) | handoff 进度归档（2026-09-24；Q166–Q168 客户 analytics／Agent Key 治理页／导出 job 管理页三片＋文档合龙滚出原文） | 只读历史；权威逐片台账仍是 docs/02 C1 | 归档 |
| [handoff-archive-2026-09-25.md](./handoff-archive-2026-09-25.md) | handoff 进度归档（2026-09-25 起持续续写，**共二十二次**：首块为 Q176/Q177 两条完整条目原文，其后为 Q188…Q210 各批按「最近 5 条」上限滚出的条目逐字搬入，滚出对象覆盖 Q162～Q205） | 只读历史；权威逐片台账仍是 docs/02 C1 | 归档 |

> 原始文档：v3.md 已于 2026-09-13 归档删除（内容 100% 迁入本库，见 §5.3 核验记录）。基准 HTML（全景图 / V6.0 需求说明）经 2026-09-13 核验**均不在本机、未入 git**，并经负责人 2026-09-17 确认**永久丢失、无法找回**（Q115，02 C1.59）：docs 中 `line NNNN` 引用**降级为历史痕迹**（记录结论当年从 HTML 哪行提取），不再作为"可重新核对的基准"；12 号文档占位名单同案定为最终名单。**自 Q115 起，本库自身即唯一事实源（自洽），不再挂"待找回后核对"。**

---

## 2. 文档治理规则（源自 v3 Part E2，全量保留；v3 删除后适配为本库规则）

1. **唯一事实源**：本目录（docs/）是项目 Loom 唯一的权威文档体系；所有原型 / PRD / 开发任务 / Skill 设计均以本库为准。原 v3.md 已于 2026-09-13 归档删除，其内容 100% 迁入本库（核验见 §5.3）。
2. **展示层**：`../Loom_SaaS后台全景图.html` 由 v3 的 Part A + Part D 渲染生成，仅用于可视化导航，不承载独立决策；HTML 修改不改变本库规格。
3. **修改流程**：任何内容变更先改本库对应文档 → 涉及新决策追加 Q 编号（继续 02 §C1 日志）→ 若改 HTML 展示层则同步渲染。
4. **两套口径**：Part A（13 段链，权威）与 Part D（03-A~E，展示）并存不混用；冲突时以 Part A 为准。**路线图口径合并已于 2026-09-13 由负责人裁决（Q73，08 §1.3）：A7 为骨 + D9 厚度，段 12 后置 V2，V1=段 1→6→10→11。**
5. **行号溯源**：本库所有 `line NNNN` 引用均指向基准文件 `Docs/Loom_后台_V6.0-需求说明（不是原型).html` 的原始行号。**Q115 收口（2026-09-17，02 C1.59）**：该基准文件经负责人确认已永久丢失、无法找回，故行号引用**降级为历史痕迹**，不再作为"可重新核对的基准"；本库自身即唯一事实源。

---

## 3. 版本沿革（源自 v3 Part E1，全量保留）

| 版本 | 日期 | 说明 |
|---|---|---|
| v1 | 2026-07-21 | 两套体系融合视角（13 段链 + 业务方五池），因冲突已被 v2 替换；⓪ 节冲突对比如需回看可恢复 |
| v2 | 2026-07-22 | 以主需求 HTML V6.0 为唯一基准，确立 13 段链体系；§10 定稿记录持续追加至 Q1–Q72（2026-07-27） |
| v3 | 2026-09-12 | **单一事实源重构**：① 吸收旧版 HTML 全景图全部独有信息为 Part D；② 章节重组为 A 规格 / B 红旗 / C 定稿日志 / D 全景展示 / E 治理 五层；③ 确立"md 为唯一事实源、HTML 为展示层"的文档治理规则；④ 修正版本号不一致（旧文件名 v1 / 正文自称 v2） |
| ai-docs | 2026-09-13 | **AI 导向切分**：按消费场景将 v3 五层 + HTML 渲染内容切分为 9 份子文档 + 本 README，信息零丢失（映射见下） |
| v3 归档 | 2026-09-13 | **v3.md 删除**：段落级核验通过（231 段、业务信息零丢失）后归档删除；本库 10 份文档成为唯一事实源；同日新增 10–17 号工程骨架文档（🟡 待补内容） |
| 18 号新增 | 2026-09-16 | 新增 18 号前端 i18n 与设计 Token 方案（原 🟡 待拍板），同日经 **Q96 拍板定稿 ✅**（next-intl + `[locale]` + 三层 Token，色值借 AntD5 调色板） |
| Q115 收口 | 2026-09-17 | 基准 HTML 确认永久丢失：`line NNNN` 溯源降级为历史痕迹、12 号名单定稿、触发方永久【待补】、G2 fid 改判工程定稿；本库自此完全自洽，不再挂"待找回后核对" |
| Q117 审计回填 | 2026-09-17 | 文档⇄代码一致性审计：实测基线（472 passed / head 0026 / 7 checker / 86 token）回填至 handoff·08·README·AGENTS 与 04/05/10/11/13，补登迁移 0021–0026 与段12 契约；4 项实现差异只挂账（handoff 待办 6），无业务口径变化 |
| Q118 收口 | 2026-09-18 | Q117 挂账 4 项均按推荐（甲）拍板落地：4 个漏网管理面 GET 补 query actor 闸、publish_slots.gate 回填 V1 人工直编口径、product_spaces 两 FK（迁移 0027）、CI 六→七 checker；另修 Alembic 版本表列长；基线 483 passed / head 0027 / CI 七 checker / 86 token，待办 6 销账 |
| Q119 段12 多语言 | 2026-09-18 | V2 P4 段12 Q58 落地（接缝按甲拍板，02 C1.63）：content_languages 语言清单配置化（dictionary_admin CRUD，种子仅 zh-CN 全市场）、ProductSpace.target_languages、发布位市场∩产品目标语言交集纯函数、content_products 唯一约束 (final_id,language,kind) 每语言独立成品；5 端点；迁移 0028（PG16 往返实测）；基线 494 passed / head 0028 / eval 101 / token 86，前端无变化 |
| Q120 段12 AI 质量分 | 2026-09-18 | V2 P4 段12 Q57 真打分 + Q56 上限配置化落地（接缝按甲拍板，02 C1.64）：模型网关第 8 场景 ARTICLE-QC 内嵌生成（只读打分、纯 advisory 不自动发证/驳回/阻断 approve、不新增状态），content_products 加 quality_score/issues，view +4 字段含 threshold/advisory；QC 故障/坏输出分数留空不阻断；阈值 content.ai_quality_threshold（0.85）与重生成上限 content.regen_limit（3）接通消费，超限 revise 422 只能 reject；迁移 0029 加列 + 0030 场景种子（PG16 往返实测，物理表仍 55）；基线 511 passed / head 0030 / eval 101·golden 21，前端零变化 |
| Q121 复检语义级检测 | 2026-09-19 | V2 P4 段12 Q59 复检第②项落地（接缝按甲拍板纯 advisory，02 C1.65）：模型网关第 9 场景 ARTICLE-SEMANTIC-CHECK 内嵌生成（只读检测不改写，输出 {findings}，四检测 code 为 v0.1 工程口径待业务方校准），结果落既有 review_hits.semantic 段，不抬 block_required/不阻断 approve/不新增状态（词库 ban 硬阻断不变）；网关异常 checked:false+error 不阻断、不落 SkillRun，坏输出归一容错仍落 SkillRun；零新端点/列/表，迁移 0031 纯场景种子（PG16 往返实测：down 语义三件套全清而 QC 三件套保留，物理表仍 55）；基线 523 passed / head 0031 / eval 101·golden 21，前端零变化；复检余施工指令核对、国家规则核对两项【待补】 |
| Q122 客户内容页 + Q56-a | 2026-09-19 | 第 3 菜单「内容生产与发布」由 v2 占位转 V1 功能页（02 C1.66；三接缝交互提问超时，沿用「按你的来」授权按推荐甲落地、**已 2026-09-19 追认销账**）：客户页=只读+审阅+人工改稿，generate/regenerate 维持 operations 闸不放客户页；六态机加 manual_resubmit（revising→review），无闸 GET /api/content（列表项去 body）/GET {id}/PATCH {id}/body（仅 revising，重过词库+语义+QC，不调 GEN、不增 regenerate_count）；前端 content 六文件+messages content 命名空间+nav v2→v1+**第八 checker check-content** 接 CI；零迁移头仍 0031；基线 528 passed（+5）/eval 101·golden 21/token 86；Q56-b 作废回池继续挂账 |
| Q123 段1 客户目标语言控件 | 2026-09-19 | Q58 产品侧客户自助落地（接缝按甲，02 C1.67）：新开客户无闸 PATCH /api/intakes/{id}/target-languages（按 intake 定位 PS，码须 active/去重，空间未生成 404，空数组清 NULL）与 GET /api/content/languages（仅 active，注册先于 {content_id}）；Q119 operations PUT 代设入口与 OPERATIONS 闸原样保留（回归锁 403），ProductSpaceView 回显；前端 TargetLanguagesForm 多选岛+check-products/check-content 守卫；零迁移头仍 0031/物理表 55；基线 534 passed（+6）/eval 101·golden 21/token 86 |
| Q124 难产骨架作废回池 Q56-b | 2026-09-19 | 负责人「按你推荐的来」拍板（02 C1.68）：内容状态机六态→七态，新增终态 discarded（只读；区别于 rejected=客户驳回可继续改）；事件 discard（operations、reason 必填 1–500）仅 review/revising/rejected→discarded；POST /api/content/{id}/discard + GET /api/admin/content/needs-attention（operations｜platform_admin）；唯一约束换 partial unique index WHERE status<>'discarded' 实现作废后同键回池（双方言），迁移 0032（pg16 往返实测）；基线 545 passed（+11）/head 0032/eval 101·golden 21 |
| Q125 运营发布回填 Q60c | 2026-09-19 | 负责人「按你推荐的来」拍板（02 C1.69）：不新增 published 态，published_at 非空即已发布；迁移 0033 加 published_url/platform_post_id/published_at 三 nullable 列（pg16 往返实测）；PUT /api/admin/content/{id}/publish-info（operations、仅 ready 409、url 必填、published_at 仅首次落）+ GET ready-to-publish（双角色、返全部 ready 行分待回填/已回填两分区）；前端管理端 /admin/content 内容运营台与 Q124 共用一页（sidebar 6→7，check-admin/check-content 扩守卫、无新 checker 文件）；Agent 抓取/effect-callback/孤儿队列/Q60a 随段13 P3/V2；基线 554 passed（+9）/head 0033/物理表 55/eval 101·golden 21/token 86 |
| Q126 段13 effect-callback 入站第一片 | 2026-09-19 | 13 段链最后一段「段13 反馈回流」入站（接缝按甲，02 C1.70）：新横切包 app/core/effects + 单表 effect_records（status matched/orphan 一列分流，迁移 0034 新建，pg16 往返实测物理表 55→56）；POST /api/effect-callback 复用 Q88 require_agent_key（首个受 Agent Key 保护业务端点，失败统一 401，命中盖 last_used_at），仅按 content_id 精确匹配非 discarded 成品，命中回填 matched_content_id/tenant_id（由 content.tenant_id 反解），查无或命中 discarded→orphan，platform_post_id 只留存不自动绑（Q60a）；metrics 六计数非负整数+read_rate 0..1，bool/未知键拒、缺席/null 省略不落绝不补 0、整组可空；captured_at 须带时区归一 UTC，同(content_id,captured_at)幂等覆盖刷 updated_at、异点追加；整批 all-or-nothing 200 回执 {received,matched,orphan,upserted}；运营只读 GET /api/admin/effects/orphans 与 /api/admin/effects?content_id= 两口 query actor 闸（limit/offset）；每批 effect.batch_received 审计；基线 554→591（+24 单+13 集）/ruff 净/eval 101·golden 21/head 0034/前端零变化 checker 仍八 token 86；明确不落随续片：Q60a 孤儿认领、customer-backfill 客户端点、自助映射、反哺 Q54·Q57·Q61·Q65 校准（口径【待补】不臆造）、Agent 抓取（Q62 不抓） |
| Q127 段13 孤儿人工认领 Q60a | 2026-09-19 | 接缝按甲（02 C1.71）：新表 effect_claims（external_content_id→content_id 持久映射）+ effect_records 加 claimed_by/claimed_at 两溯源列（不新增第三状态）；POST /api/admin/effects/claims（operations、404/409/403 闸、upsert 映射+批量回填 orphan/历史 claimed 行）；ingest 认领兜底（同 ID 后续推送经映射 matched 不回落孤儿）；迁移 0035（pg16 往返实测物理表 56→57）；基线 591→599（+8）/head 0035/ruff 净/eval 101·golden 21 |
| Q128 段13 customer-backfill 客户通道 | 2026-09-19 | 接缝按甲（02 C1.72）：POST /api/effects/backfill 无 Agent Key、source 服务端固定 customer-backfill、只命中本租户非 discarded 成品否则整批 422、绝不产生孤儿（不查认领映射）、审计 effect.customer_backfilled tenant=客户租户；零迁移头仍 0035/物理表 57；基线 599→607（+8）/eval 101·golden 21 |
| Q129 段13 认领批量/解绑 | 2026-09-20 | 接缝按甲（02 C1.73）：POST /api/admin/effects/claims/unclaim（删映射+旧目标行全部回滚 orphan 含兜底新 matched 行、映射不存在 404 ClaimMappingNotFound、审计 effect.claim_revoked）+ claims/batch（items≥1、批内重复 422、整批 all-or-nothing 回滚、逐条 effect.claimed）；service 抽 _claim_one；零迁移；基线 607→618（+11）/eval 101·golden 21 |
| Q130 管理端效果运营台 | 2026-09-20 | 接缝按甲（02 C1.74）：新建管理端 /admin/effects（sidebar 第 8 项、check-admin 锁 8 项）：孤儿队列单条/勾选批量认领岛 + 成品时序查询与解绑岛；读 operations\|platform_admin、写 operations、指标缺席显 "—" 绝不显 0；纯前端零迁移；tsc 净、八 checker、next build 通过 |
| Q131 客户效果回填 UI | 2026-09-20 | 接缝按甲（02 C1.75）：客户内容详情页对非 discarded 成品挂回填岛（V1 单条手工表单、datetime-local 转 UTC、指标留空即缺席、消费 Q128 客户通道、批量/CSV 随 V2、客户 nav 仍 8 项）；纯前端零迁移；tsc 净、八 checker、next build 通过 |
| Q132 中台导出 JSON+异步任务 | 2026-09-20 | 接缝按甲（02 C1.76）：GET fcw.json envelope 与 CSV 同口径、POST /api/exports/jobs V1 同步落 completed + 状态/下载口、export_jobs 不存 payload 下载重渲染、审计 export.job_created；迁移 0036（物理表 57→58，pg16 往返实测）；后端 618→633、eval 101，前端零改动；queued/running 真后台 worker + 任务列表口后由 Q137 落地（env 默认关） |
| Q133 fencing token | 2026-09-20 | 接缝按甲（02 C1.77）：`leader_lease` 抢锁后 INCR 取跨易主单调令牌、看门狗易主/续约故障置 lost、INCR 失败 fail-closed，`leader_lock` 保 Q89 布尔语义；纯代码零迁移；后端 633→641、eval 101，前端零改动；下游 DB fence/tick 协作中止随 V2 |
| Q134 Redis Streams 认领原语 | 2026-09-20 | 接缝按甲（02 C1.78）：新包 app/core/queue 落 XADD/XGROUP/XREADGROUP/XACK/XPENDING+XCLAIM/死信原语，StreamBackendError fail-closed，**只落原语不接 worker、不落 env、无占位端点**；零迁移；后端 641→649、eval 101，前端零改动；导出消费组 worker 已由 Q137 接、restock 生产侧 XADD 已由 Q138 接（restock 消费组水平并行因花钱隔离仍 V2） |
| Q135 配置缓存失效广播 | 2026-09-20 | 接缝按甲（02 C1.79）：after_commit fire-and-forget PUBLISH（best-effort）+ ConfigBroadcastSubscriber 收消息全量 reload、故障懒重连，env LOOM_CONFIG_CACHE_BROADCAST_ENABLED 默认关；零迁移无新配置键；后端 649→656、eval 101，前端零改动；单 key 增量/真多副本验证随 V2 |
| Q136 客户批量 CSV 回填 | 2026-09-20 | 接缝按甲（02 C1.80）：纯前端批量岛（固定 9 列表头 CSV 解析+行级校验+预览、文件/粘贴双入口、软上限 500 行、captured_at 转 UTC、空指标缺席），整批走 Q128 records[] 客户通道 all-or-nothing；**不建后端端点/无迁移/无新依赖**；后端 656·eval 101 不变，tsc/八 checker（token 86）/next build 过；服务端上传/Excel/异步导入/逐行回执随 V2 |
| Q137 中台导出真后台 worker | 2026-09-20 | 接缝按甲（02 C1.81）：导出只读幂等可安全并行，queued/running 经 Redis Streams 消费组 ExportWorker 异步处理（read_new+reclaim_pending 崩溃接管、ACK/PEL/超限死信、终态重复幂等）+ GET /jobs 列表口；状态用 String(16) 无 PG enum **零迁移**；env LOOM_EXPORT_WORKER_ENABLED 默认关；FakeStreamsRedis 抽共享 stream_fakes；后端 656→666、eval 101；大结果集分页/行数上限随 V2 |
| Q138 restock 信号 XADD 生产接线 | 2026-09-20 | 范围收敛（02 C1.82）：restock 自动花真 token 须 leader 单实例防双花，与消费组水平并行语义冲突，故**只接生产侧入流**（restock/notify.py after_commit best-effort XADD、DB requested 行为唯一事实源/DB 轮询兜底、失败只告警），worker 主认领不切消费组；env LOOM_RESTOCK_STREAM_ENABLED 默认关、零迁移；后端 666→669、eval 101；消费组并行（花钱隔离）随 V2 |
| Q139 两循环 leader_lease 协作中止 | 2026-09-20 | 接缝按甲（02 C1.83）：四持锁点（sla/restock 两 _tick + 两手工 /run）leader_lock→leader_lease，run_jobs/run_restock 加零参 checkpoint=raise_if_lost（作业会话外/每信号前），锁中途易主抛 LockLost 协作中止；两 _tick 静默返回、两手工口 409；门控关行为同 Q89、leader_lock 保留；复用 LOOM_DISTRIBUTED_LOCK_ENABLED 无新 env、零迁移；后端 669→674、eval 101；下游 PG 行级 fence 随 V2 |
| Q140 配置缓存单 key 增量失效 + 广播退避 | 2026-09-20 | 接缝按甲（02 C1.84）：cache.reload_keys 按 key 合并（DB 删除同步出快照），poll_once `*` 全量/具体 key 增量分流，断线 consecutive_failures 指数退避 1s→封顶 30s、wait_for(stop) 可唤醒、成功重置，健康路径每轮 sleep(0) 零拍让出防替身忙转饿死定时器；复用 LOOM_CONFIG_CACHE_BROADCAST_ENABLED 无新 env、零迁移；后端 674→678、eval 101；配置版本号/TTL、真多副本验证随 V2 |
| Q141 配置缓存版本号门控 + TTL 兜底 | 2026-09-20 | 接缝按甲（02 C1.85）：cache 快照携 per-key ConfigItem.version 向量、reload_keys 单调门控拒旧快照回灌（accepted/skipped/removed），after_commit apply 携权威版本；订阅器无消息超 env LOOM_CONFIG_CACHE_TTL_SECONDS 默认 300 回源全量，仅曾装载且门控开启时触发；零迁移；后端 678→684、eval 101；真多副本订阅验证随 V2 |
| Q142 中台导出分页 + 行数硬上限 | 2026-09-20 | 接缝按甲（02 C1.86）：fcw.csv/fcw.json 加 limit(1..cap)/offset，env LOOM_EXPORT_MAX_ROWS 默认 100000 超限 422；JSON envelope 加 total/limit/offset/has_more、CSV 走 X-Export-* 响应头（正文守单列）；同步/异步 worker/下载同一上限、job 不加分页列；零迁移；后端 684→692、eval 101；6 层原料包全量 JSON/多 worker 并发度随 V2 |
| Q143 下游 PG 行级 fence 接 restock 花钱路径 | 2026-09-20 | 接缝按甲（02 C1.87）：新表 restock_claims + restock/fencing.py 两段式，花钱前 claim_request 独立短事务认领（acquired/held/lost）、成功提交前 fence_current 条件 UPDATE rowcount=0 回滚；锁在模型调用期间易主旧 leader skipped_lost 不调模型；fence=None 行为同 Q87/Q139；迁移 0037（pg16 往返实测）、物理表 58→59；后端 692→699、eval 101；SLA sweep 行级 fence、真 PG/Redis 多副本验证随 V2 |
| Q144 MVP 评审与首发形态裁决 | 2026-09-21 | 02 C1.88：三判准——docs-V1 内核达标且超额、公网自助 NO-GO、受控试点有条件 GO；首发＝受控 private beta（平台代运营），P0-① 身份层压 V2 第一项；上线 Checklist 见 08 §2.2 |
| Q145–Q147 private beta 部署/备份/staging | 2026-09-21 | 02 C1.89–C1.91：Q145 前后端 Dockerfile + entrypoint 迁移先行 + compose（backend 不发布端口、frontend 唯一口 3000，699→704）；Q146 db-backup 每日 pg_dump+7 天/日志轮转/watchdog+webhook（704→710）；Q147 staging overlay `-p loom-staging` 6 服务 healthy、真实 Chrome SSR 零 console 错误（710→711，#6 不销账） |
| Q148 真实 LLM 接线 | 2026-09-21 | 02 C1.92：agnes OpenAI 兼容网关/agnes-2.5-flash/USD/日预算 50 USD/8 chat 场景真模型/Key Fernet；真实 CAT-RECOG 635/231 tokens；ATOM-AFFINITY 仍 synthetic、单价待供应商、图像/视频 V2；零迁移 |
| Q149 beta 阈值确认 + 主数据模板 | 2026-09-21 | 02 C1.93：SLA 72h/黄 24h/红 48h、QC 0.85、cluster_line 0.9 沿用为 beta 口径；G2 12 字段基线；付费档额度划掉；新增 docs/19 录入模板；#6 唯一阻塞＝主数据业务回填 |
| Q150 A2A 封臣 plan 模式任务层 | 2026-09-21 | 接缝全按草案（02 C1.94，design-a2a-vassal.md）：新包 app/core/a2a/（card/skills/rpc/router），三公开 Agent Card 发现端点 + POST /api/a2a/tasks（Q88 Bearer、JSON-RPC send/sendSubscribe(SSE)/get/cancel、进程内存 TTL 30min/上限 500、审计 a2a.task tenant=_platform）；三 skills 全 plan 模式不触链/不花 token/不越 Gate；零迁移零新 env；后端 711→733（单测 12+集成 10）；持久化/真 LLM/真机联调随第二阶段 |
| Q151 SLA sweep 写路径 PG 行级 fence | 2026-09-21 | 接缝按甲（02 C1.95）：新表 sweep_tick_claims（迁移 0038，物理表 59→60，pg16 往返实测）+ sla/fencing.py 两段式 claim_tick/fence_current + run_jobs commit_guard（门闭 LockLost 中止本轮）；scheduler/手工 /run 先认领（lost 静默/409）；fence=None 不写表同 V1；后端 733→741（+8 集成）；真 PG/Redis 多副本验证随 V2（sqlite 替身边界同 Q143） |
| Q152 导出 worker 多 consumer 并发度/批量 | 2026-09-21 | 接缝按甲（02 C1.96）：build_export_workers 工厂 N 个同消费组 ExportWorker（N>1 姊妹 consumer 共享前缀带序号、参数透传、非法值启动 ValueError）；env LOOM_EXPORT_WORKER_CONCURRENCY 默认 1/LOOM_EXPORT_STREAM_COUNT 默认 20 保 V1 行为、不入 .env.example；main 单例改列表；零迁移；后端 741→747（+6）；真 Redis 多 consumer 验证随 V2 |
| handoff 归档惯例 | 2026-09-18 | handoff.md 新增 `## Conventions`（主文件只保留当前状态 + 活跃待办 + 最近 5 条进度；完成项详细过程滚 `docs/handoff-archive-YYYY-MM-DD.md`，主文件留一行结论）；首次归档 09-13 ~ 09-17 进度条目与待办 5/6 原文至 `handoff-archive-2026-09-18.md` |

---

## 4. 信息保全映射表（核验"不丢失任何信息"）

### 4.1 v3.md 各 Part → 目标文档

| v3.md 章节 | 内容概要 | 切分去向 |
|---|---|---|
| 头部基准说明（line 2-8） | 基准文件、参考标记规则、文档治理（v3 新增） | README §2、§5 |
| Part A1 主链总览 | 13 段链表（CHAIN_13）、三端（PORTS） | 01 §1 |
| Part A2 数据流与硬闸 | 数据流图、final 定义 | 01 §2 |
| Part A3 各段规格（段1–13） | 各段功能/输入输出/实体/规则/定稿修订 | 01 §3（段1–13）+ 04/05/06 结构化提取 |
| Part A4 横切治理规则 | 6 条全局红线 | 01 §4 |
| Part A5 数值约束速查 | 数值约束说明、两项非配置结构约束 | 01 §5 |
| Part A6 连带关系 | 改动点 → 传播路径表 | 01 §6 |
| Part A7 实现范围建议 | 第 0 步 + 三阶段 | 01 §7 + 08（任务包拆解） |
| Part B1 红旗清单 | S 级 4 条 / A 级 11 条 / B 级 4 条（§B1.1–B1.20） | 03 全量 |
| Part B2 业务方参考汇总 | 3 处参考映射表 + 术语差异警告 | 03 全量 |
| Part C1 逐轮定稿记录 | C1.1–C1.16，Q1–Q72 全部 | 02 全量 |
| Part C2 配置化清单 | 40+ 配置项表 | 02 全量 |
| Part D0 两套口径差异与映射 | D0 映射表、粗粒度对应 | 09 §0 |
| Part D1 4 大端入口 | END1–END4 | 09 §1 |
| Part D2 6 层决策链 | 展示口径核心链路 | 09 §2 |
| Part D3 13 一级菜单 | D3.1–D3.13 菜单树全量（含二级/三级/角色/V 标签） | 09 §3 |
| Part D4 内容生产中台 | 中台形态 + 对接方式 | 09 §4 |
| Part D5 用户前端系统 | 8 大菜单 / 885 节点 | 09 §5 |
| Part D6 内容反馈系统 | 7 大活水机制 + 5 大反馈 Skill | 09 §6 |
| Part D7 辅助支撑系统 | 8 道闸门 + 10 条省 Token 策略 | 09 §7 |
| Part D8 权限矩阵 | 8 角色 × 13 一级菜单 | 09 §8 |
| Part D9 路线图 | V1/V2/V3 | 09 §9 + 08（并行口径） |
| Part D9.5 周边功能清单 | 主链之外模块清单 | 09 §9.5 |
| Part D10 铁律与最终口径 | 铁律 4 条 + 最终架构口径 | 09 §10 |
| Part E 版本沿革与治理 | E1/E2 | README §2、§3 |

### 4.2 HTML（V2.0）→ 目标文档

| HTML 节 | 内容 | 切分去向 |
|---|---|---|
| ① 4 大端入口 | END1–END4 卡片 | 09 §1 |
| ② 6 层决策链 | 6 层链 + 同构说明 | 09 §2 |
| ③ 13 一级菜单 | 03-A~E 菜单树（V1/V2/V3 标签细化到二级菜单） | 09 §3 |
| ④ 内容生产中台 | 中台只消费 final_id + 对接方式 | 09 §4 |
| ⑤ 用户前端 8 大菜单 | FRONT 1–8 | 09 §5 |
| ⑥ 内容反馈系统 | 反馈闭环 + 5 大反馈 Skill | 09 §6 |
| ⑦ 辅助支撑系统 | 8 道闸门 + 10 条 token 策略 | 09 §7 |
| ⑧ 权限矩阵 | 8 角色 × 13 菜单 | 09 §8 |
| ⑨ V1/V2/V3 路线图 | 三阶段目标 | 09 §9 + 08 |
| ⑩ 13 段主链（权威规格摘要） | 段表 + 数据流 + final 定义 | 01 §1–§2（全文在 01） |
| 铁律 + 最终架构口径 | D10 | 09 §10 |
| 页脚治理声明 | 展示层声明 | README §2 |

> **HTML 核对结论**：HTML 为 v3 Part A（摘要）+ Part D 的忠实渲染，无 v3 未收录的独有业务信息；其 V1/V2/V3 二级标签在 v3 D3 菜单树中已覆盖。

---

## 5. 切分说明与引用约定

1. **信息零丢失的实现方式**：每份子文档均标注来源（v3 Part X §Y / HTML §Z）；原文行号引用（`line NNNN`）、Q 编号、状态词（✅临时采纳 / 🔶待讨论 / ⬜未处理 / ⚠未做标注）一律保留。
2. **不新增业务事实**：除明确标注为【工程建议】的内容外，本库文档不新增原文没有的业务/规格事实；原文空缺处一律标注【原文未给出，待补】而非猜测。
3. **结构化提取**：契约层文档（04/05/06）是对原文的提取与重组（实体→字段、状态→迁移、Skill→协议），提取结果均在末尾附来源索引。
4. **两套口径**：13 段链（权威）与 03-A~E（展示）在本库中分置于 PRD（01）与全景（09），互不混用；冲突以 01 为准。
5. **待裁决事项**（原文明确挂起，本库不擅自裁决）：① ~~A7 三阶段 × D9 V1/V2/V3 路线图口径合并~~ **已于 2026-09-13 裁决（Q73）**；② ~~业务方 3 份素材是否采纳~~ **已于 2026-09-13 确认采纳**（见 02 C1.16 注记 / 03）；③ ~~技术栈选型等工程建议~~ **已于 2026-09-13 拍板**（见 14）。**截至 2026-09-17（Q116 后）当前无原文挂起的待裁决事项**；另有"待业务方/外部输入"项（付费档第 5 档额度、五型 SLA 与黄色窗口真实数值、G2 余 6 个 common 字段、触发方事件），属【原文未给出，待补】而非待裁决。

---

## 5.3 信息保全核验记录（v3 删除前，2026-09-13）

**方法**：将 v3 全文按空行切为 238 段（剔除表格分隔线/过短段后核验 231 段），对每段提取 line 引用、Q 编号、最长中文片段、英文专名，逐一检查是否存在于本库 10 份文档全文中。

**结果**：231 段核验，**业务信息零丢失**；仅 8 段"疑似缺失"，经人工审读全部为**文档自身元说明的措辞差异**，非业务事实：

| v3 段落 | 差异说明 |
|---|---|
| 头部"基准文件"说明 | 子文档各头部已有等价来源说明，措辞不同 |
| "Part B · 红旗清单"标题 | 03 文档标题为"技术风险与红旗清单"，内容全量在 |
| "Part C 记录格式"说明 | 02 文档头部有等价"活文档/追加更新"说明 |
| "来源：旧版全景图 V1.0" | 09 文档头部有等价来源说明 |
| "以下为旧全景图的完整菜单树" | 09 §3 有等价说明（措辞微调） |
| "Part E 版本沿革"标题 | README §3 承载 |
| "唯一事实源 = v3.md"治理声明 | **已随 v3 删除更新为本库规则（§2）** |
| "v3 生成日期"说明 | README §3 版本沿革承载 |

**结论**：v3.md 可安全删除；HTML V2.0 保留（其内容已核对无 v3 未收录的独有业务信息）。
