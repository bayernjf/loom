# Changelog

All notable changes are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/).

## [Unreleased]

### Added

- **契约层文档同步 M1–M3 实现（2026-09-13）** — 以"实现补登"形式（不改设计原文、不升级文档状态）把后端切片登记回契约层：05 §1.4 新增已落地 REST 端点清单（M1–M3 全量路由 + 404/409/403/422 错误口径）；04 §2.4/2.6/2.7 补物理表名与字段（M2 七表、候选唯一约束与转正回填、M3 三表与 violations 取值）；10 §2.1/2.2 补 Alembic 0001–0003 物理表与设计名映射；13 §1.12 新增字段池 Gate 流转（标注 Gate 非状态机）；15 §1 补实际包结构（product_intake/modeling/fieldpool）与规划名对应。

- **M3（段3 字段池规划）后端切片落地（2026-09-13）** — Q8 维度来源路由表后台 CRUD（6 路种子：用户输入/通用灵感库/产品专属灵感库/类目模板/G2 高频/合规风险面，被引用禁删，改动 writeAudit）；字段池方案提交（一品一池，每维度强制角色+启用路由+依据标注 line 14081 红线，fid 必须为 active G2 否则违规，新字段进 g2_field_candidates 同名全局复用）；PT-FP-PLAN-V2.0 校验（product_attribute 恒 ≥1；risk_control 仅敏感行业强制 Q11；>8 按 conf 留 Top8、余者入备选档可人工捞回 Q12；<3 不达标转人工不自动补）；conf<0.85 标"需细看"不自动通过（Q9，第一期全量过 Gate）、相似度 ≥0.9 仅机器标记人工终裁（Q10）、目标原子数 15-30（Q15）；WF-02 HumanGate（product_reviewer 角色，非合规方案 409 拒批，approved 锁定，rejected 可重提）；Q13 新字段转正端点（dictionary_admin 角色，fid 冲突/重复转正 409，转正后回填池维度，G2 cat 完整取值待基准 HTML，默认 extension 不污染 common）。迁移 0003（fp_source_routes/field_pools/fp_dimensions + 6 路种子，PG16 up/down/up 通过）；45 测试全绿。未含：WF-02 三 Skill AI 通道（M10）、灵感库两层实体、转正保护期加权（第二期）、拍板值配置中心迁移（M10）。

- **M2（段2 C1 识别）后端切片落地（2026-09-13）** — 信号权重配置表（启用行 Σ 必须精确等于 1 否则拒绝保存，文本三信号 0.50/0.33/0.17 种子，图像后置，Q2）；行业阈值后台 CRUD（general 默认档不可删 + writeAudit，medical 0.90/electronics 0.80/general 0.85 种子，Q7）；conf 单指标三分支（Q1/Q3：高置信 wf01_confirm+系统 auto_confirm 直送已提交；中置信出 ops_assist 运营待办、72h 未处理 sweep 升级、全否转 cold_start；低置信带 B2 候选单进类目创建中；Top1-Top2 差<0.1 矛盾规则）；C7 四层兜底（L1 模板缓存/L2 兄弟 product_count 最大继承/L3 G2 覆盖率 60% 降级线/L4 新字段进 g2_field_candidates，Q6；模板写入与 L4 提案两入口禁止 fid:'-'，Q68）。迁移 0002（8 表 + 权重/阈值种子，PG16 up/down/up 通过）；AuditLog 上移 core 横切包；26 测试全绿。未含：WF-01 六 Skill AI 通道、定时调度（M10）、G1 完整类目管理（V3）、拍板值配置中心迁移（M10）。

- **M1（段1 产品录入）后端切片落地（2026-09-13）** — productIntake15 状态机（15 态全流转；类目创建中态仅受 B2 三结果，Q5；类目确认 operations 角色闸，Q3；三终态拒事件）；录入 REST `/api/intakes`（创建/查询/allowed-events/profile 补资料/事件迁移/ProductSpace 查询），提交时按 `g2_fields` active 的 cat='common' 行动态校验缺字段阻断（D7.1 闸门1，名单不硬编码），非法迁移 409/越权 403/缺字段 422/审核后资料不可改 409；writeAudit append-only 审计；Alembic 0001（g2_fields/product_intake_applications/product_spaces/audit_logs，PostgreSQL 16 实测 up/down/up 通过）；11 条单元 + 集成测试全绿。配套 Q74 双落库裁决（见下）。未含：WF-01 6 Skill 候选通道（随 M10）、72h SLA（M10）、18 字段真实 fid 种子（待基准 HTML 找回）。

- **决策 Q74（2026-09-13）** — 18 个 G2 cat='common' 字段值两处落库、职责不同：申请单 `profile`（fid 键控，提交后不可变）+ ProductSpace `profile_snapshot`（start_modeling 时整体复制的不可变快照，同 PWS 快照哲学 Q31）；02 新增 C1.18/Q74，04 §2.2、10 §2.1 同步；M0 挂账子项"18 通用字段值归属"销账。

- **建立 docs 唯一事实源体系（2026-09-13）** — 原唯一事实源《Loom_核心业务主链梳理_v3.md》经段落级核验（231 段、业务信息零丢失）后归档删除，内容 100% 迁入 `docs/`（01–09 为 v3 忠实切分，10–17 为工程骨架文档）；配套文档地图 README 承载治理规则与信息保全映射表。详见 [docs/README_文档地图与治理.md](docs/README_文档地图与治理.md)。

- **根目录项目文档** — README（项目介绍与 13 段链一图流）/ handoff（当前状态、待办与文档清单单一事实源）/ AGENTS + CLAUDE（AI 工作规范）/ git-commit-message（提交规范）/ CONTRIBUTING（贡献指南）/ MIGRATION_CONVENTION（迁移规范）/ BENCHMARK（基准登记表，代码启动后启用）。

- **仓库基建** — git init（`main` + `dev` 工作分支），推送至 GitHub private 仓库（bayernjf/loom）。

- **代码脚手架落地（2026-09-13）** — 按 15/17 定稿建最小骨架：backend（Python 3.12 + FastAPI 模块化单体，13 模块包 + core 9 横切包 + Alembic + tests 四层 + `.env.example`）、runtime/eval/middleplatform 数据驱动目录、frontend（Next.js + TS 最小页）、infra docker-compose（pgvector/pg16、redis:7、MinIO）；MIGRATION_CONVENTION 补 Alembic 现行口径。仅骨架，业务代码自 V1 M1 起写。

- **路线图口径合并裁决 Q73（2026-09-13）** — A7 三阶段与 D9 V1/V2/V3 两套并存路线图由负责人裁决合并：**A7 为骨 + D9 厚度**；V1（0–3 月/5–10 客户）主链到段 11 `final_id` 发证闭环，**段 12 内容生成后置 V2**，段 7/8 V1 仅交付 FCW 必需的静态底表基础版，驾驶舱收敛为 Token 成本 + 人工审核 2 个，Evaluation/Golden 两件套维持 V1；08 §1.3 改为裁决记录 + 合并后权威路线图表，§2 任务包重排（V1=M1–M8+M10/M10-Q+新增 M11/M12；V2=P1–P5）；02 新增 C1.17/Q73；01/03/06/09/12/16/README/handoff/AGENTS 同步；原文挂起待裁决事项清零。

- **技术选型 6 项定稿（2026-09-13）** — 模块化单体；自研注册表驱动编排器最小集（YAML 声明式，留 LangGraph 逃生口）；PostgreSQL 16 + pgvector + Redis 7（Streams）+ S3 兼容对象存储；DB 配置中心 + 变更广播热更新；进程内独立合规模块；MVP 仅建 Evaluation Dataset + Golden Cases。技术栈 = Python 3.12 + FastAPI / React + Next.js + TS。14 升 ✅ 定稿，15/17/08/10/06 已同步。

- **M0 规格仲裁完成（2026-09-13）** — Q2/Q22/Q60(a/b/c) 临时采纳转定稿；新增 Q22a/Q22b（PWC 分项评分：合规前置硬条件、合理性加权、多样性=1−最大重合占比、AI 失败转人工不凑分、score 仅排序不做门槛），同步 01 段5/06 §1.1/02 §C2；业务方 3 份素材采纳经负责人确认（02 C1.16）；段 1-6 缺口实体 ProductSpace/g2FieldCandidates 补字段（04/10）；03 S1–S4 销账注记。

## 待办（未入本日志）

- V1 任务包排期（工期/人员/优先级待负责人提供资源信息）、两个基准 HTML 找回（阻塞 12 占位名单核对与 line 溯源）、10 建表要素 DBA 复核——见 [handoff.md](handoff.md) 待办区。
