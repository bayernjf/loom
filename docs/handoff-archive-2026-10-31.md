# Handoff 归档（2026-10-31）

> 归档惯例（见主文件「Conventions」节）：主文件只保留项目当前状态 + 活跃待办 + 最近 5 条进度；完成项详细过程滚到本类文档，主文件只留一行结论 + commit hash / Q 编号。本档冻结只读、不再追加。
> 本档对应（2026-10-31 例行瘦身）：① 头部进度日志按「最近 5 条」上限滚出的 Q371 批整组原文（§一，主文件留一行指针）；② 待办 #4「待核验缺口」全部收口子项与 #5「仓库基建」条目行原文（§二，主文件各留一行结论 + 指针）。

## 一、进度日志滚出：Q371 批（2026-10-19，整组原文）

> **其前（2026-10-19）：Q371 批＝E2E 两缺陷修复批（**纯前端批＋文档，零后端零迁移零测试变化**；基线照 Q370 时点引用〔**1453 passed＋11 skipped／收集 1464**、ruff 全仓净、头 `0064_field_candidate_gate_sla_seed`／75 表·821 列·迁移文件 64、`GATED` **63**、侧栏 20、ts/tsx 122〕本批未复跑（纯前端批）；前端 tsc＋七检查器全绿；02 C1.313）**——负责人「都搞」点工三件（2026-10-19）。
> - **① 静默失败修复**＝四处行内写按钮组件 `startTransition(async)` 反模式→本地 pending＋try/catch/finally（review-queue decision-cell/batch-bar、fcw freeze-island、intakes ops-intake-actions）；行内裁决/批量通过 409 现在**错误回显「操作冲突，请刷新后重试」**（第二轮 E2E 实测）。
> - **② 两套口径对齐**＝`fcw/actions.ts`＋`fcw/assemble/actions.ts` 共 7 个 action 删本地 `ADMIN_ROLE_LIST` 的 missing_role 硬返回，后端 Bearer 令牌身份唯一权威、403 透出 detail；`missing_role` 字面量保留防 check-admin 棘轮（判据不变，全绿）；其余页面存量闸不动。
> - **③ 第二轮 E2E 复验（docs/26 §6.5）**＝行内/批量裁决 409 错误回显 ✓；预填表单读口（getFcwReuseAction）不再本地拦截、六路入参自动回填 ✓；预检写口（previewAssembleAction）不再本地拦截、后端 e2e-ops 放行、七项机械核验全过＋「全部放行，可签发」✓；fcw 作废按钮无 frozen 快照未直接触发（同族修复）。环境副作用＝新签 e2e-ops-r2 令牌（key_id 09cdeafe）＋门控临时关/开（最终仍 true）＋frontend 镜像重建，记 docs/26 §6.4-⑥。
> - **④ 合龙**＝docs/26 §6.2 两行标注修复复验＋§6.5＋§6.4-⑥；docs/02 C1.313＋续编索引补登；CHANGELOG [Unreleased] 补条；handoff Q371 banner（Q370 转「其前」、**Q366 按「最近 5 条」上限逐字滚入归档「四十九、」节**，6 行零差异）；AGENTS 权威行前移 Q371；docs/08 §2.2 就地单行前移（不增行）；docs/README 地图 docs/02 行前移 Q371/C1.313；docs/16 §4 Q371 基线行；docs/24 头部 C1.312→C1.313；docs/25 头部基线加 Q371 句（验收计数不动）。
> - **⑤ 刻意不做（守边界）**＝不动任何后端/迁移/测试文件；全量基线不复跑（纯前端批）；不接 Q7 阈值 0.90（待业务权威确认，不臆造）；不接 §8.2 外部输入族与 §8.3 V2 族；不动存量 DIM-MERGE 模板（Q358 ⑤ 挂账仍在）；其余页面存量本地角色闸不动。
> - **【复判】**① 达标／② 达标（Q295 后保持）／③ **未达标**（现网部署＋真 ACME 未证）。**活跃待裁项 0**；仍等外部输入＝供应商侧视频队列容量与首次成功样本＋段12 转写／成片复检规格＋复检名单＋agency 价格＋支付通道＋现网部署＋V2 三管辖规则文本＋fit_score 真自学习余下三份业务规则与门控生产默认值（docs/19 清单二第 16 项）＋存量库 DIM-MERGE 提示词重发（运营复核，Q358 ⑤）＋Q7 阈值 0.90 待业务权威确认。

## 二、待办完成项滚出（原文逐字）

### 待办 #4「待核验缺口」（收口子项原文，2026-09-13 → 2026-09-21）

4. **待核验缺口**：
   - 两个基准 HTML 文件**经核验均不在本机**（2026-09-13，仓库目录 + Spotlight 全盘 + git 全历史）：
     ① `Loom_SaaS后台全景图.html`——docs/README 第 3/38 行称"保留在上级目录/`../`（仓库根）"，实际不存在，且从未进入 git；
     ② `Docs/Loom_后台_V6.0-需求说明（不是原型).html`——AGENTS.md 行号溯源（`line NNNN`）基准文件，`Docs/` 目录本身不存在。
     被 8 个文档引用（AGENTS / README / MIGRATION_CONVENTION / handoff / docs 01·09·12·README）。**✅ Q115 已收口（2026-09-17）**：负责人确认 V6.0 HTML 彻底丢失无法找回——line 溯源降级为历史痕迹、12 PT 名单定为最终名单（7+35）、触发方永久标【待补】、G2 fid 改判工程定稿（迁移 0024 落 12 字段）；不擅自修改或移除这些历史引用。
   - ~~12 的 PT 占位候选名单待与基准 HTML 核对~~ ✅ Q115 已收口（2026-09-17）：7 定稿 + 35 推断候选定为最终名单，35 候选保留【推断】标注；
   - ~~11/13 的接口与迁移行待 M0 裁决后补齐~~ ✅ Q112 已补（2026-09-17）：13 号 productIntake15 七处迁移行据 M1 实现补登（G1 审核流随 V3、PWC 复核/待入库维持【待补】）；11 号白名单消费/CSV/Key 治理按已落地端点回填（effect-callback 本体随段13 P3、中台 API/SDK 随 V2/V3、DB 浏览/调试台/配额、JSON/异步导出仍【待补】）；
   - ~~10 的建表要素待 DBA 复核~~ ✅ **首轮 DBA 复核已完成（2026-09-20，E 项）**：一次性 PG16 容器 upgrade head 实测 + ORM 比对，58 表零漂移，订正 content_products.status String32、tenants.detail JSONB 两处笔误，结论见 docs/10 §4；✅ **第二轮 DBA 全量列复核已完成（Q153，2026-09-21，head 0038/60 表）**：把 0037 restock_claims、0038 sweep_tick_claims 两 fence 表纳入，一次性 pg16 容器 upgrade head 到 0038 后导出 information_schema/pg_indexes/pg_constraint 并与全量 ORM metadata 比对，实测 60 表/637 列/212 索引/PK60·FK32·UQ20、列漂移 0，两新表五列/pkey 与 §2.8 逐字一致，结论见 docs/10 §4。

### 待办 #5「仓库基建」（条目行原文，含历次基线读数链）

5. **仓库基建 — ✅ 主体完成（2026-09-18；详细原文见 [docs/handoff-archive-2026-09-18.md](docs/handoff-archive-2026-09-18.md)）**：git（dev/main，GitHub origin，提交规范见 git-commit-message.md）；脚手架按 15 落地；venv=backend/.venv（uv + Python 3.12）；pytest 全绿（**现行读数＝1124 passed＋10 默认 skip（CI 实测 run 37150090423＝Q267 时点，Q270 销「1122 待确认」、Q273 跑覆盖率本机复跑 256.10s 同数；Q264 时点 1120〔+5 集成＝test_package_reuse_pending.py〕、本机 Windows 复跑 1114 passed＋6 failed 环境差异＋10 skip 差异名单见 docs/17 §1、Q263 时点 1115、Q262 时点 1110、Q260 时点 1095、Q259 时点 1084、Q252 时点 1080）**，权威行见本文件顶部与 docs/08 §2.2；**本行原写「803 绿＋8 个 real-infra 默认 skip」是 Q165 时点读数**——real-infra 现为 **9** 例且自 Q209 起作为独立 job 进 CI，"默认 skip"只描述本地不带两个 env 时的情形；747→750 Q155→757 Q156→761 Q157→769 Q160→786 Q161→803 Q162-Q165〔+42＝Q160 8、Q161 17、Q162-Q165 17，Q159/A2 纯前端 0〕，2026-09-22 Q165 后已复跑 803+8skip/eval 101/前端 tsc+八 checker，复跑见 docs/17 §7；**2026-09-21 Windows 本机首跑全量门禁亦全绿**（uv 建 CPython 3.12.13 venv：pytest 761＋8 real-infra skip〔约 309s〕/ruff 净/eval 101，前端 npm ci＋tsc＋八 checker；首跑抓到 check-admin.mjs 四条跨行字面量路由断言在 core.autocrlf=true 的 CRLF 工作区误报 4 problem，已修为读取 content/router.py 后归一 CRLF→LF，LF/CI 行为不变）；**必须在 backend/ 目录执行**——根目录跑会因 pythonpath/testpaths 失效误报）、ruff 净、迁移头现为 **0047_layer_spaces**（Q262，2026-10-03；Q263 零迁移头不变；0043 fcw_snapshots 新建两表／0044 纯种子不建表／0045 新建 platform_dynamic_events＋pcp_recalc_candidates 两表（64→66 表）／0046 纯 PLATFORM-ADAPTER 第 11 场景种子（场景注册＋Prompt v0.1＋synthetic 构造器，66 表不变）／**0047 新建 layer_spaces＋layer_space_items 两表（66→68 表，Q262 layerSpaces 通用底座，含 4 层 22 维度种子）**，0043–0047 均经 pg16 容器往返实测；其后 0040 staff_api_keys／0041 discard_retention 种子／0042 G1 类目种子亦经 pg16 往返实测；**本行原记 0042_g1_category_seed 是 Q249 时点读数、0039_import_jobs 是 Q161 时点读数**，0032–0039 经 pg16 容器实测，Q141/Q142/Q150/Q152/Q159/Q160 零迁移、Q143 迁移 0037 restock_claims 业务表 58→59、Q151 迁移 0038 sweep_tick_claims 59→60、Q161 迁移 0039 import_jobs 60→61）、eval 101/101、前端 tsc+八 checker（Q122 起含 check-content，Q130 起 sidebar 8 项；**现行 12 项**＝Q167/Q168→10、Q177→11、Q178→12，check-admin 锁的就是这个数）、next build 通过、token 86；浏览器人工验收通道 chrome-devtools MCP 已注册本仓（约定见 15 §4）。
