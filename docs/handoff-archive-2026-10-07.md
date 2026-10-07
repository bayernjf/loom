# handoff 进度归档 — 2026-10-07

> 依 `handoff.md` 归档惯例：主文件只保留项目当前状态 ＋ 活跃待办 ＋ **最近 5 条**进度；超出 5 条的进度条目**逐条原文**滚入本档（可作历史检索，一字未改）。
> **权威逐片台账仍是 [docs/02](02_决策记录_ADR_Q1-Q72.md)（C1 日志）／[docs/08](08_迭代计划与任务包.md) §2.2 ／[docs/16](16_测试策略.md)。**

## Q297 banner 原文（于 2026-10-07 按「最近 5 条」上限滚出）

> **其前（2026-10-06）：Q297 新增内部角色与可签发性（V2 三件事公共前置）实现候选设计（**测试＋文档**，零生产代码零迁移；写口守卫 UNGATED 补登 PWS 冻结/吊销两口〔盲区变判据、用例数不变〕，基线仍 **1169 passed＋10 skipped**、head=0049；02 C1.240）**——负责人「好的」，工程侧挑的不需裁决可独立推进项。
> - **为何汇总**：fit_score 校准（fit 乙）、adapter 候选裁决（adapter 乙）、待裁项③ 的 `whitelist_owner` 可签发性——三件 V2 余量**共同卡在同一契约前置**（要不要新角色码／能否签发 staff 令牌／守哪些写口），拆三次裁决会造成两三次契约变更，故按 Q274/Q284/Q292/Q293 同型合成一份。
> - **grounding（head=0049 实测）**：内部 5 角色可绑 staff PAT、客户角色 `whitelist_owner` 刻意不可签发（`rbac.INTERNAL_ROLES` 与 `staff_auth INTERNAL_STAFF_ROLES` 两处须逐字一致）；守卫矩阵只用 4 种角色，`dictionary_admin` 定义但 **0 写口**挂它（可复用）；docs/06 §7 Gate 总览**无 fit_score 行**、平台适配是「平台审核员（展示口径）」均无权威角色码；PWS 冻结/吊销两口（router :78/:109）**既无 `require_internal_actor`、也不在 GATED/UNGATED 任一名单**（身份模型悬空，Q242 归并③）。
> - **推荐**：fit 校准与 adapter 裁决均**甲＝复用 operations**（零新角色零迁移，§7 把展示口径映射到权威码）；`whitelist_owner` **甲＝维持客户角色随③客户认证解决**，本批只把冻结两口补进守卫 UNGATED 显式登记（盲区变判据）。乙案（新设 fit_admin/platform_reviewer）本质是「要不要独立审计身份」的组织裁决，工程不代裁；红线＝不把客户角色塞进内部令牌集、adapter 裁决不新增硬 Guard。
> - **【复判不变】**：① 达标／② 达标（Q295 翻正后保持）／③ 未达标（现网部署＋真 ACME＋待裁项③）。本批只把③的一个子问题材料化。

## Q303 banner 原文（于 2026-10-07 按「最近 5 条」上限滚出）

> **其前（2026-10-07）：Q303 覆盖率读数复测（**纯测量**，零代码零迁移零测试改动；基线不变 **1181 passed＋10 skipped／收集 1191**、头 `0050_platform_adapter_candidates`；02 C1.246）**——「推进你自己能搞的」＝工程侧独立推进，Q298 后 Q299–Q302 四批新增真实 `app/` 语句后的例行复测。
> - **读数（head=0050，命令照 CI 原样抄＝`python -m pytest -q --cov=app --cov-report=json --cov-report=term`＋`coverage_report.py`）**：全系统 `app/` **71.71%**（**13,341** 条语句／missed 3,774；term 取整 72%）；核心规则层（9 个 `*_rules.py`＋`statemachine.py`）**99.34%**（**604** 条）。较 Q298（71.83%／13,220；核心 99.34%／604）：分母 **＋121**＝Q299 fit 校准审计＋Q300 adapter 候选 service/router 真实 `app/` 语句（覆盖 **＋71**／未覆盖 **＋50**），全系统 **−0.12pp**；核心层持平。
> - **政策不变**：≥90%／≥70% 仍【建议】、仍刻意不接 `--cov-fail-under`（Q229 负责人裁决；是否升门＝待裁项⑤）；读数已同步 docs/23 §0.1 与 docs/08 §2.2 权威行，`coverage.json` 为产物不入库。
> - **【复判不变】**：① 达标／② 达标（Q295 翻正后保持）／③ 未达标（现网部署＋真 ACME 签发未证＋待裁项③）。纯测量批不改任一层判定。

## Q301 banner 原文（于 2026-10-07 按「最近 5 条」上限滚出）

> **其前（2026-10-06）：Q301 CI 同 ref 连推自动取消旧 run（PR #150 红叉根因收口；**配置＋测试＋文档**，零迁移零生产代码；后端收集 1190→**1191**（**1181 passed**＋10 skipped，＋1＝ci.yml concurrency 契约，先红后绿）、ruff 净、前端零改动；02 C1.244）**——工程侧独立推进，门集合一字不动。
> - **根因**：PR #150（dev→main）红叉实为**被取消的重复 run**非测试失败（rerun attempt 2 六道门全绿）；GitHub Actions 默认把同 ref 每次推送的 run 全跑完，烧额度且 cancelled 叉号污染状态。
> - **交付**：`.github/workflows/ci.yml` 顶层 `concurrency: group ci-${{ github.ref }} / cancel-in-progress: true`——同 ref 新推送立即取消旧 run，不同 ref（并发 PR、dev/main）互不取消；新契约例 `test_superseded_runs_are_cancelled_per_ref` 钉组名与开关恰为该值（`test_ci_workflow_contract.py` 现 21 例）。沙箱内 2 例 backup_monitoring socket.bind EPERM 为已知假红（Q291/Q298 同型）。
> - **【复判不变】**：① 达标／② 达标／③ 未达标（现网部署＋真 ACME＋待裁项③）。只改调度不改门，不改任一层判定。


## Q300 banner 原文（于 2026-10-07 按「最近 5 条」上限滚出）

> **其前（2026-10-06）：Q300 PLATFORM-ADAPTER 候选表＋HumanGate 闭环 ＋ Q299 fit_score 人工校准审计（Q297 裁决全甲的两个乙案落地；**代码＋迁移＋测试＋文档**，迁移 **0049→0050**、业务物理表 68→**69**；后端 **1169→1180 passed＋10 skipped**〔＋11＝adapter 候选 8／fit 校准 3〕、ruff 净、eval 101/101、前端零改动；真 PG16 宿主 55460 往返实测 **69 表/754 列 NO DRIFT**；02 C1.242/C1.243）**——负责人「好的，你搞」＝Q297 三件候选全按甲。
> - **Q299 fit 人工校准（乙案，零迁移）**：`slot.update` 审计 detail 加 `fit_dim_changes`（只记变化维度 before/after，原样为 `{}`）、`fit_weights.put` 加 `weights_before`（首次 null）；端点形状不变。口径是**人工校准非「自学习」**：不设幅度上限（原文未给）、不触发下游、fit_score 仍派生不落库、Q54 0.4/0.3/0.3 不动。
> - **Q300 adapter 候选＋Gate（乙案，迁移 0050）**：新表 `platform_adapter_candidates`（partial unique `uq_platform_adapter_pending` 双 where，slot_id 可空以 coalesce 空串入键）＋四端点（候选列表/提交/approve/reject，三写口全 OPS、进守卫 GATED）；提交复用 Q296 组料＋synthetic 网关落 pending 候选，V1 仅 source=synthetic。
> - **advisory 红线**：approve 只解除 pending 留痕（审计带 `advisory_only:true`）——不改平台规则/发布位、不产 final_id、不动段11 七 Guard（PT 约束 4/6）；reject reason 必填；Q38 降级动作字典另点工（docs/02:141 vs docs/10:369 口径漂移未订正前不落码），丙案真模型仍以补 eval/golden 为硬前置。docs/06 §7 已补 fit 校准行并把「平台审核员（展示口径）」映射到 operations。
> - **【复判不变】**：① 达标／② 达标（Q295 翻正后保持）／③ 未达标（现网部署＋真 ACME＋待裁项③）。本批闭红旗 S2 的业务接线缺口，不改可上线判定。


## Q298 banner 原文（于 2026-10-07 按「最近 5 条」上限滚出）

> **其前（2026-10-06）：Q298 覆盖率读数复测（**纯测量**，零代码零迁移零测试改动；基线不变 **1169 passed＋10 skipped**、head=0049；02 C1.241）**——Q294/Q296 两批新增真实 `app/` 语句后的例行复测，工程侧独立推进。
> - **读数（head=0049，命令照 CI 原样抄）**：全系统 `app/` **71.83%**（**13,220** 条语句／missed 3,724；term 取整 72%）；核心规则层（9 个 `*_rules.py`＋`statemachine.py`）**99.34%**（**604** 条）。较 Q281（71.78%／13,100；核心 99.34%／602）：分母 **＋120**＝Q294 周扫描作业＋Q296 service/router/breakdown，全系统 **＋0.05pp**（新代码基本被同批测试覆盖、无摊薄）；核心层 602→604、读数持平。
> - **沙箱假红**：同跑 1167 passed＋2 failed＋10 skipped（143.23s），两条失败均为 `test_backup_monitoring_contract` 的 `socket.bind` EPERM（沙箱禁绑回环口）；沙箱外单跑该文件 **22 passed in 0.21s** 全绿（Q291 同型已记录），非回归、不影响读数。
> - **政策不变**：≥90%／≥70% 仍【建议】、仍刻意不接 `--cov-fail-under`（Q229 负责人裁决；是否升门＝待裁项⑤）；读数已同步 docs/16 §4，`coverage.json` 为产物不入库。
> - **【复判不变】**：① 达标／② 达标（Q295 翻正后保持）／③ 未达标（现网部署＋真 ACME＋待裁项③）。纯测量批不改任一层判定。

