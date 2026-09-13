# Handoff — Loom

> **State of Loom as of 2026-09-14**（设计/文档定稿；M1+M2+M3+M4+M5 后端切片已落地，下一步 M6）。
> 续工时**先读本文件**，再读 [docs/README_文档地图与治理.md](docs/README_文档地图与治理.md)（场景导航 + 治理规则）。历史/规格细节一律以 docs 内文档为准，本文件只保留"当前状态 + 活跃任务 + 最近变更"。

## 项目一句话

Loom = 私域内容生产白名单平台（SaaS 后台）：把"产品信息 → 可发布内容"拆成 **13 段链（CHAIN_13）** 可编排生产链，AI 只产候选、人工 Gate 裁决、`final_id` 唯一出口、反馈回流反哺知识。三端：用户前端 / 管理后端（13 模块）/ 系统后台 API。

## 项目文档（完整清单，单一事实源）

> 完整清单与一句话描述**只以本节为准**；[docs/README](docs/README_文档地图与治理.md) 只做场景导航，不重复清单。

| 文档 | 一句话描述 | 状态 |
|---|---|---|
| [docs/README_文档地图与治理.md](docs/README_文档地图与治理.md) | 文档地图（场景导航）+ 治理规则 + 信息保全映射表 | ✅ 权威 |
| [docs/01_PRD_产品需求规格.md](docs/01_PRD_产品需求规格.md) | 13 段链全量规格：各段功能/实体/规则/硬闸/数值约束 | ✅ 权威（Part A 全量） |
| [docs/02_决策记录_ADR_Q1-Q72.md](docs/02_决策记录_ADR_Q1-Q72.md) | 决策日志 Q1–Q72 + Q73（路线图合并）/Q74（18 字段双落库）+ 40+ 配置化清单 | ✅ 权威（Part C 全量） |
| [docs/03_技术风险与红旗清单.md](docs/03_技术风险与红旗清单.md) | 红旗 S/A/B 三级（S 4 / A 11 / B 4）+ 裁决状态 + 业务方参考映射 | ✅ 权威（Part B 全量） |
| [docs/04_契约层_数据模型.md](docs/04_契约层_数据模型.md) | 实体与字段级数据模型（AI 落代码用） | ✅ 已提取 |
| [docs/05_契约层_API与状态机.md](docs/05_契约层_API与状态机.md) | API 契约 + 全部状态机定义 | ✅ 已提取 |
| [docs/06_契约层_WF与Skill协议.md](docs/06_契约层_WF与Skill协议.md) | Workflow / PT 协议 / Skill 注册表 / Agent 协议 | ✅ 已提取 |
| [docs/07_技术架构与工程规格.md](docs/07_技术架构与工程规格.md) | 模块边界 / 编排运行时 / 配置中心 / RBAC / 成本治理 / 工程建议 | ✅ 已提取 |
| [docs/08_迭代计划与任务包.md](docs/08_迭代计划与任务包.md) | 路线图（两套已裁决合并，Q73）+ V1/V2/V3 任务包（V1=段 1→6→10→11） | ✅ 已按合并裁决重排 |
| [docs/09_全景体系_展示口径.md](docs/09_全景体系_展示口径.md) | 展示口径全景：4 端/6 层/13 菜单/权限矩阵/中台/反馈 | ✅ 参考口径 |
| [docs/10_数据模型Schema_建表定义.md](docs/10_数据模型Schema_建表定义.md) | 35 实体建表要素（类型/约束/索引/关系） | 🟡 **待 DBA 复核** |
| [docs/11_API规范_OpenAPI.md](docs/11_API规范_OpenAPI.md) | effect-callback/白名单消费规格 + OpenAPI 通用规范 | 🟡 **待补接口待 M0** |
| [docs/12_PT协议补齐清单.md](docs/12_PT协议补齐清单.md) | 7 定稿 + 35 占位候选 + 补齐模板 | 🟡 **占位名单待 HTML 核对** |
| [docs/13_状态机迁移表.md](docs/13_状态机迁移表.md) | 11 组状态机迁移矩阵 | 🟡 **待补迁移行待 M0** |
| [docs/14_技术选型决策.md](docs/14_技术选型决策.md) | 6 项技术选型（模块化单体/自研编排器/PG+pgvector+Redis/DB 热更新/进程内合规模块/质量两件套） | ✅ **2026-09-13 已拍板定稿** |
| [docs/15_代码结构与脚手架.md](docs/15_代码结构与脚手架.md) | 目录/模块/可执行物落位 + 技术栈（FastAPI/Next.js/YAML） | 🟢 **已定稿（选型+技术栈已落）** |
| [docs/16_测试策略.md](docs/16_测试策略.md) | 分层测试 + 规则级测试清单 | 🟡 与 12 联动 |
| [docs/17_部署与运维.md](docs/17_部署与运维.md) | 环境/CI-CD/多租户/监控说明（含中间件版本） | 🟢 **已定稿（选型已落）** |
| [docs/18_前端i18n与设计Token方案.md](docs/18_前端i18n与设计Token方案.md) | 界面 i18n（next-intl 建议，V1 zh-CN）+ 设计 Token 三层模型（CSS 变量/CSS Modules 建议）；与 Q58 内容多语言划界 | 🟡 **工程建议，5 项待负责人拍板（拍板后 Q75）** |

> 根目录文档：README.md（项目介绍）/ AGENTS.md（AI 工作规范）/ CLAUDE.md（指向 AGENTS）/ handoff.md（本文件）/ git-commit-message.md（提交规范）/ CHANGELOG.md / CONTRIBUTING.md / MIGRATION_CONVENTION.md / BENCHMARK.md。

## 当前状态

- **阶段**：设计/文档阶段完成度高；代码骨架已搭（2026-09-13，按 15/17 定稿：backend FastAPI 13 模块包 + core 横切包 + Alembic + 分层 tests；runtime workflows/skills/agents/protocols 空目录；eval 两件套目录；middleplatform；frontend Next.js TS 最小页；infra docker-compose = PG16-pgvector/Redis7/MinIO）。**M1（段1 产品录入）+ M2（段2 C1 识别）+ M3（段3 字段池规划）+ M4（段4 字段下原子）+ M5（段5 PWC 条件包）后端切片已落地**：M1 productIntake15 + 录入 API + 迁移 0001；M2 信号权重/行业阈值配置、conf 三分支、ops 待办 72h、C7 四层兜底 + 迁移 0002；M3 来源路由表、方案提交/越界处置、WF-02 Gate、Q13 候选转正 + 迁移 0003；M4 Q48 统一词库、拓展批次/risk 双轨/三类冲突/approveAtomGuard、evidence 超时可复活、同义簇 alias、事实原子引用数=1、atom8 生命周期 + 迁移 0004；M5 contentGoals 字典、库容配置、WF-04 漏斗（预筛/Q48 合规检测/Q22 评分/限量 50）、Q23 疑重备选、HumanGate、Q71 按分消费+池健康、Q24 三元组去重/per-platform 冷却/全平台用尽、Q61 爆款手工标 + 迁移 0005；104 测试全绿（详见 08 §2.2 M1/M2/M3/M4/M5 完成情况）；下一步 M6（段6 PWS 冻结）。仓库**已 git init**（分支 `dev`，`main` 为主干）。
- **文档体系**：原唯一事实源 `Loom_核心业务主链梳理_v3.md` 已于 2026-09-13 归档删除，内容 **100% 迁入 docs/**（231 段段落级核验零丢失）；01–09 为 v3 忠实切分（Part A/B/C/D/E 全覆盖），10–17 为同日新增工程骨架文档，18 为同日新增前端 i18n/设计 Token 工程建议（🟡 待拍板）。
- **权威口径**：13 段链（CHAIN_13，01 PRD）为唯一权威；03-A~E 展示口径（09）并存不混用，冲突以 01 为准。
- **已定稿事实基线**：Q1–Q72 均已有决策记录（02，含正式采纳与"临时采纳"两类）；S 级红旗 4 条经 Q34/Q60 等解决（02 收官注、03 已标销账）。**M0 已于 2026-09-13 完成**：Q2/Q22/Q60(a/b/c) 转定稿（02 新增"✅定稿"状态与转正注记）；新裁 Q22a（分项打分口径）/Q22b（多样性函数 + AI 失败兜底），评分细则同步 01 段5、06 §1.1、§C2；业务方 3 份素材采纳经负责人确认（02 C1.16）；段 1-6 缺口实体 ProductSpace / g2FieldCandidates 已补字段（04/10）。挂账 4 子项（不阻塞 M1）：PS.lifecycle 迁移触发、~~18 通用字段值归属（M1 前定）~~ ✅ Q74 已裁决（两处落库 profile + profile_snapshot）、候选实体多租户可见性、候选状态枚举。**两套路线图口径冲突已于 2026-09-13 由负责人裁决合并（Q73，08 §1.3）：A7 为骨 + D9 厚度，段 12 后置 V2，V1 驾驶舱只留 Token 成本 + 人工审核 2 个；08 §2 已重排。至此原文挂起的待裁决事项全部清零。** 技术选型 6 项**已拍板定稿**（14，2026-09-13：模块化单体 / 自研注册表编排器 / PG+pgvector+Redis / DB+广播热更新 / 进程内合规模块 / Evaluation+Golden 两件套），技术栈 = FastAPI + Next.js + YAML 编排；下游 15/17/08/10/06 已同步刷新。
- **V1 范围（Q73 合并后权威）**：0–3 月 / 5–10 客户；主链段 1→6→10→**11**（到 `final_id` 发证闭环，**不含段 12**）；段 7/8 仅 FCW 必需的静态底表基础版（M11，无动态信号/fit_score 学习）；横切 skill7/writeAudit/RBAC/配置中心/SLA + 审核工作台 + 租户/Onboarding + 前端 8 菜单基础版 + CSV（M12）+ M10-Q 质量两件套 + 2 驾驶舱。段 12/13 与段 7/8/9 完整版在 V2。

## 最近进度（2026-09-14）

- **M5（段5 PWC 条件包）后端切片落地**：Q25 contentGoals 字典（5 码种子，dictionary_admin 维护，软归档）+ Q27 库容配置（默认 100、可配无上限）；WF-04 漏斗四步——预筛（本 PS 已通过原子/同租户/跨 ≥2 维度【实现补】/同批去重）、Q48 词表合规检测（ban→blocked 不评分，手拼 Q26 不豁免，逻辑/搭配检测留插拔位）、Q22 评分（(合理性0.6+多样性0.4)×品类乘数，合理性=logic/fit 各 0.5，多样性=1−与待用池最大重合；AI 子分缺失不凑分转人工 Gate，score 仅排序；重合=原子集合 Jaccard【实现补】）、单批限量 50；Q23 重合 ≥0.8 标疑重、低分进备选、人工可改判；HumanGate（product_reviewer，入库受库容 409）；Q71 消费 score 降序、同平台+账号+发布位去重、跨平台可复用、goals 交集过滤、响应带 pool_health（target100/low70/critical50）与 restock_hint；Q24 同平台 7 天 ≥3 次→14 天冷却（per-platform state，sweep 服务就绪调度随 M10）、目标平台用尽→used（平台清单来源待补）、high_reuse_n 高复用旗标；Q61 爆款 V1 仅手工标；取用流水带 tenant 隔离。迁移 0005（6 表+5 码种子，PG16 up/down/up 通过）；104 测试全绿（13 纯逻辑 + 17 HTTP 集成）。未含：WF-04 三 Skill AI 通道、sweep/自动补货定时调度、Q61 自动检测、语义向量相似度、逻辑/搭配检测插件、target_platforms 来源、拍板值配置化（均 M10 或待补）。详见 08 §2.2 M5 完成情况。
- **M4（段4 字段下原子）后端切片落地**：Q48 统一合规词库横切包先行（CRUD + 软归档 + 审计，段4 先消费、段5 已 M5 接入、段10 待 M7）；拓展批次仅产候选（PT-ATOM-EXP），Q14 批次 20/50 可覆盖、Q15 AI 达标停拓手动放行、同批去重；Q17 risk 双轨（词表命中强制定级人工不可改，AI 判级可人工复核）；AtomConflict 三类（disabled_expression/high_risk_single_review/evidence_required）；approveAtomGuard 9 项机检 + 审计，Q70 high/critical 单条审、批量整批 409；Q18 无证据 pending_evidence + 7 天 sweep 自动驳回可复活（调度随 M10）；Q19 同义簇 keeper 终裁、merged 词条作 alias 并入正式原子；line 11189 事实原子（容量/成分/浓度/疣类型/品牌）(fact_type,normalized) 全局唯一、跨租户拦截、reference_count=1；Q20 生命周期（operations 冻结/解冻/废弃/归档，解冻不重审；internal_compliance 暂停/恢复；product_reviewer 驳回；废弃恢复=新原子重审）。迁移 0004（5 表，PG16 up/down/up 通过）；74 测试全绿。未含：WF-03 四 Skill AI 通道、sweep 定时调度、Q51 生效即扫联动段 5/10、Q16 相似度本体、拍板值配置化（均 M10）。详见 08 §2.2 M4 完成情况。
- **M3（段3 字段池规划）后端切片落地**：Q8 来源路由表 CRUD（6 路种子、引用保护+审计）；方案提交一品一池——每维度强制角色/启用路由/依据标注（line 14081 红线）、fid 必须为 active G2（Q68）、新字段进 g2_field_candidates（wf02_dim_source，同名全局复用）；PT-FP-PLAN 校验（product_attribute 恒 ≥1、risk_control 仅敏感行业 Q11、>8 Top8+备选档可捞回 Q12、<3 不达标转人工）；conf<0.85 标需细看（Q9）、相似度≥0.9 仅标疑重人工终裁（Q10）、目标原子数 15-30（Q15）；WF-02 HumanGate（product_reviewer，approved 锁定、rejected 可重提）；Q13 dictionary_admin 候选转正并回填池维度。迁移 0003（PG16 up/down/up 通过）；45 测试全绿。未含：WF-02 三 Skill AI 通道（M10）、灵感库两层实体、转正保护期加权（第二期）、cat=extension 占位待基准 HTML 核对、拍板值配置化（M10）。详见 08 §2.2 M3 完成情况。
- **M2（段2 C1 识别）后端切片落地**：信号权重配置表（Σ=1 强校验，Q2，文本三信号 0.50/0.33/0.17 种子）、行业阈值 CRUD（general 默认档不可删+审计，Q7）、conf 单指标三分支（Q1：高置信系统 auto_confirm 直送已提交；中置信 ops_assist 运营待办附 AI Top 候选，72h 未处理 sweep 升级，Q3/Q4，选定/全否；低置信带 B2 候选单进类目创建中）、C7 四层兜底（L1 模板缓存→L2 兄弟继承（product_count 最大，Q6）→L3 G2 覆盖率 60% 线→L4 新字段进 g2_field_candidates；Q68 fid:'-' 在模板写入与 L4 提案入口拦截）。迁移 0002（8 表+种子，PG16 up/down/up 通过）；AuditLog 上移 core 横切包；26 测试全绿。未含：WF-01 六 Skill AI 通道与定时调度（M10）、G1 完整类目管理（V3）、拍板值配置化迁移（M10 配置中心）。详见 08 §2.2 M2 完成情况。
- **M1（段1 产品录入）后端切片落地 + Q74 裁决**：负责人对挂账子项"18 通用字段值归属"拍板（02 C1.18/Q74）——申请单 `profile`（G2 fid 键控，提交后不可变）+ ProductSpace `profile_snapshot`（start_modeling 时整体复制，同 PWS 快照哲学 Q31）；完整度闸门按 g2_fields active 行动态判定不硬编码名单。代码：纯逻辑 productIntake15 状态机（15 态/终态/B2 三分支/operations 角色闸）、service + `/api/intakes` REST（缺字段 422、越权 403、非法迁移 409、审核后资料不可改 409）、Alembic 0001 四表（PG16 实测 up/down/up 通过）、11 条单测/集成测试全绿（SQLite in-memory；venv 经 uv 装 Python 3.12）。未含：WF-01 6 Skill 候选通道（随 M10）、72h SLA（M10）、真实 fid 种子（待基准 HTML 找回）。详见 08 §2.2 M1 完成情况。
- **代码脚手架落地**：按 15/17 定稿建最小骨架——backend（Python 3.12 + FastAPI 模块化单体，13 模块包映射 product×6/platform×2/decision×2/final/content/feedback，core 9 横切包，Alembic 异步 env，tests 四层目录，.env.example）、runtime/eval/middleplatform 数据驱动目录（.gitkeep 占位）、frontend（Next.js 15 + React 19 + TS 最小页）、infra/docker-compose（pgvector/pg16 + redis:7 + MinIO）；.gitignore 补 Python/.next；MIGRATION_CONVENTION 补 Alembic 现行口径。仅骨架可跑 `/healthz`，无业务逻辑。
- **路线图合并裁决（Q73）**：负责人逐项拍板——①A7 为骨 + D9 厚度（时间盒/客户目标采用 D9）；②段 12 内容生成移出 V1（V1 到段 11 final_id 闭环，段 12 随段 13 在 V2，原 M9 改为 P4）；③段 7/8 V1 仅静态底表（新增 M11）；④V1 驾驶舱收敛为 Token 成本 + 人工审核 2 个；⑤质量两件套维持 V1 覆盖 D9 V3 口径。08 §1.3 由"待裁决"改为裁决记录 + 合并后权威路线图表，§2 重排（V1=M1–M8+M10/M10-Q+M11/M12，V2=P1–P5，V3 平台化）；02 新增 C1.17/Q73；README 治理规则 4 与待裁决清单、AGENTS、本文件同步；原文挂起待裁决事项清零。
- **选型下游文档刷新**：技术栈确认（Python 3.12 + FastAPI / React + Next.js + TS / YAML 声明式编排）；按 14 §3 刷新 15（目录/技术栈/eval 落位）、17（PG16+pgvector/Redis7/S3 中间件）、08（新增 M10-Q 质量两件套任务包）、10（§1.3 存储拓扑 + 配置中心版本化热更新 + MVP 辅助系统范围）、06（§4.2 编排器选型）；15/17 升 🟢 已定稿。
- **技术选型 6 项拍板**：负责人逐项拍板，全部采纳 docs/14 建议——模块化单体 / 自研注册表编排器最小集（协议解耦留 LangGraph 迁移）/ PG+pgvector+Redis（Streams）+对象存储 / DB+变更广播热更新 / 进程内独立合规模块 / MVP 仅 Evaluation Dataset+Golden Cases。14 升 ✅ 定稿；下一步按 §3 同步 15/17/08/10/06。
- **M0 完成**：业务方 3 份素材采纳经负责人确认（02 C1.16 注记）；段 1-6 缺口实体 ProductSpace / g2FieldCandidates 字段补齐（04 §2.2/§2.6，同步 10）；03 S1-S4 全部加销账注记；AGENTS 待裁决清单移除 M0。4 个实现时挂账子项登记在 08 §2.1。
- **M0 三项转正 + 评分规格补写**：Q2（C1 信号权重/图像后置）、Q60/a/b/c（外部 Agent 推送制回流契约）、Q22（PWC 评分公式、品类乘数一期恒 1.0 回流后校准）经负责人复核转定稿；新裁 Q22a（合规前置/合理性加权/score 仅排序不做门槛）、Q22b（多样性=1−最大重合占比、AI 失败转人工不凑分），同步 01 段5、06 §1.1、02 §C2。
- **M0 口径对齐**：核对 02/03 后订正 08 §2.1 / AGENTS / 本文件——S 级 4 条已有 Q 决策（Q34 正式，Q2/Q22/Q60 临时采纳），素材 3 份已采纳销账；M0 真实剩余 = 3 个临时采纳转定稿 + 04 §3 规格补写 + 素材采纳告知确认。
- **基准 HTML 核验**：确认全景图 HTML 与 V6.0 需求说明 HTML 均不在本机、未入 git 历史（详见"待办"第 4 条）；同步订正本文件中"尚未 git init"的过期状态（实际已 init，`dev` 分支）。
- **v3 归档删除**：`Loom_核心业务主链梳理_v3.md` 经段落级核验（231 段、业务信息零丢失）后删除；docs 成为唯一事实源体系。
- **AI 导向切分（ai-docs）**：按消费场景把 v3 五层 + HTML 渲染内容切分为 9 份子文档（01–09）+ 文档地图 README；信息保全映射表逐项可核验（README §4）。
- **工程骨架补齐**：新增 10–17 号工程文档（Schema 建表 / OpenAPI / PT 协议补齐清单 / 状态机迁移表 / 技术选型 / 代码结构 / 测试策略 / 部署运维），均为建议/待补状态（见上方状态列）。
- **治理规则确立**：唯一事实源 = docs；修改先改文档、新决策追加 Q 编号、行号引用指向基准 HTML。

## 待办 / 下一步（按依赖顺序）

1. **M0 规格仲裁（08 §2.1）— ✅ 2026-09-13 完成**：Q2/Q22/Q60(a/b/c) 转定稿；Q22a/Q22b 评分分项规格新裁决并同步 01/06/§C2；素材采纳经负责人确认（02 C1.16 注记）；段 1-6 缺口实体 ProductSpace / g2FieldCandidates 已补字段（04 §2.2/§2.6，同步 10）。挂账不阻塞 M1 的 4 个子项：PS.lifecycle 迁移触发条件、~~18 通用字段值归属（M1 前定）~~ ✅ Q74 已裁决、候选实体多租户可见性、候选状态完整枚举。KUP-PROPOSE 随第二阶段段 13 补。
2. **技术选型下游同步 — ✅ 2026-09-13 完成**：14 六选型拍板（模块化单体/自研编排器/PG+pgvector+Redis/DB+广播热更新/进程内合规模块/质量两件套）；技术栈同日确认（Python 3.12 + FastAPI / React + Next.js + TS / YAML 声明式编排）；已刷新 15（目录+技术栈）、17（中间件/部署）、08（新增 M10-Q 质量两件套）、10（§1.3 存储拓扑 + 配置中心热更新 + 辅助系统 MVP 范围）、06（§4.2 编排器选型）。
3. **排期填表（08 §2）— 待启动**：路线图已合并（Q73），V1 任务包为 M1–M8、M10、M10-Q、M11（段7/8 静态底表）、M12（平台厚度）；各包工期/人员/优先级原文未给，待负责人提供资源信息后排期。排定后即可按 15 搭脚手架进入编码。
4. **待核验缺口**：
   - 两个基准 HTML 文件**经核验均不在本机**（2026-09-13，仓库目录 + Spotlight 全盘 + git 全历史）：
     ① `Loom_SaaS后台全景图.html`——docs/README 第 3/38 行称"保留在上级目录/`../`（仓库根）"，实际不存在，且从未进入 git；
     ② `Docs/Loom_后台_V6.0-需求说明（不是原型).html`——AGENTS.md 行号溯源（`line NNNN`）基准文件，`Docs/` 目录本身不存在。
     被 8 个文档引用（AGENTS / README / MIGRATION_CONVENTION / handoff / docs 01·09·12·README）。**待用户确认**：文件是否在其他设备/网盘；找回前 12 的 PT 占位名单核对与一切 `line NNNN` 溯源均被阻塞；不擅自修改或移除这些引用。
   - 12 的 PT 占位候选名单待与基准 HTML 核对（依赖上面的文件找回）；
   - 11/13 的接口与迁移行待 M0 裁决后补齐；
   - 10 的建表要素待 DBA 复核。
5. **仓库基建 — 部分完成**：git（`dev` 分支，提交规范见 [git-commit-message.md](git-commit-message.md)）；脚手架已按 15 落地（backend/runtime/eval/middleplatform/frontend/infra）。backend venv 已用 uv + Python 3.12 建好（`uv venv --python 3.12 backend/.venv && uv pip install --python backend/.venv/bin/python -e 'backend[dev]'`），`pytest` 104 绿、ruff 通过、Alembic 0001/0002/0003/0004/0005 对 PG16 验证通过。**下一步：开 M6（段6 PWS 冻结，08 §2.2 验收行：pwsReadiness 5 项 Q28 / BO-07 红线 / 重冻三档 Q29 / 换版四行 Q30 / revoked 急停 Q32）**；18 字段归属挂账已由 Q74 关闭。

## 关键约束（接手者不得违反）

- **唯一事实源** = docs/；不得以摘要/记忆/二手来源替代文档原文。
- **不擅自裁决**：原文挂起的三项（两套路线图合并、业务方素材采纳、技术选型）均已由负责人拍板（2026-09-13，Q73 / 02 C1.16 / 14）；今后新出现的挂起事项仍须由用户/负责人拍板，禁止静默替换或默认值，并在 02 追加 Q 记录。
- **事实纪律**：文档空缺处标注【原文未给出，待补】，禁止编造业务事实；数字/比例/状态词改动需溯源（line 行号 / Q 编号）。
- **两套口径**：13 段链（权威）与展示口径（03-A~E）分置 01/09，不混用。
- **AI 治理红线**（02 Q66 等）：AI 只产候选，人工 Gate 裁决；红线操作（如 PWS 冻结）需指定角色 + 人工 Gate。

## 交接完成定义

接手者在开始编码前应能明确回答：

- Loom 的 13 段链是哪 13 段？`final_id` 由哪 6 层快照相加、唯一出口是什么？
- 为什么"白名单"是相撞产物而不是手写词表？frozen PWS 在链条中的作用是什么？
- S 级红旗 4 条分别是什么？M0 为什么必须在写代码前完成？
- 两套路线图（A7 vs D9）原来为什么并存？合并裁决（Q73）的结论是什么——V1 为什么不含段 12、段 7/8 在 V1 的最小切片是什么？
- 技术选型 6 项建议分别是什么？当前是"建议"还是"决策"？
- Q1–Q72 里哪些是硬约束（配置化/审计/AI 治理/多租户/成本/不静默生效）？
- 当前文档体系里哪些是"权威"、哪些是"待补/待拍板"？修改一份规格文档的正确流程是什么？
