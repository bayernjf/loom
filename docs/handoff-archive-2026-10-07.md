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

## Q302 banner 原文（于 2026-10-07 按「最近 5 条」上限滚出）

> **其前（2026-10-07）：Q302 入口文档对账＝docs/17 §1.3「投产最小清单」验真入账 ＋ 六处活状态句子回源码重测（**纯文档零代码零迁移零测试变化**；本机全量复跑 **1181 passed＋10 skipped／收集 1191**、头 `0050_platform_adapter_candidates`、迁移文件 50、`Base.metadata` **69 表／754 列**、测试文件 130；02 C1.245）**——负责人「看看 handoff.md 和相关文档是否需要更新」。先量后改（Q283 方法学：docs 比 docs 的一致性门挡不住过期句子）。
> - **查出一批没入账的活产物**：`docs/17` §1.3「投产最小清单」（07 日 15:24 落盘、**无 Q 编号、未提交**）＝第 0–4 步可执行清单＋「这个清单解决不了的三条」。本批把八处锚点逐条回制品验真才入账：`docker-entrypoint.sh:8-10`（空 `LOOM_MASTER_KEY` ⇒ FATAL＋`exit 1`）与 `:14`→`:19`（迁移自动跑再 exec uvicorn）／`docker-compose.yml:25/66`（两 datastore 口令裸插值无 `:-`）／`:123`（`db-backup`，`RETENTION_DAYS:-7`／`86400`）／`docker-compose.monitoring.yml:41`（grafana 口令 `${VAR:?}`＝缺失即报错）／`admin/login/page.tsx:11-12`（staff PAT→`/api/auth/me`→httpOnly cookie；`find app -type d -name '*login*'` **只命中 admin 一支**＝客户侧确无登录页）／`config.py:23`（`scheduler_enabled: bool = True`）／`product_intake/router.py:57`（客户读口 `tenant_id=Query(...)`＋零认证依赖＝**待裁项③ 的源码出处**）。
> - **六处活状态句子与树对不上，已按实测更正**：① handoff 待办 ⑤ 写「现行读数 `app/` 71.78%／核心 99.34%，Q273」→ **Q298 复测 71.83%（13,220 语句）／核心 99.34%（604）**，并标 Q299–Q301 后未再复测；② handoff 待办 ⑦ 段首已写「Q288 裁补并落地」、正文却仍写「现仅 service 层先查后插…零唯一约束…工程侧不代做」＝**同一段自相矛盾**，已改判为裁决前现状＋已落四件；③④ docs/19 清单二 §2 缺 ② 已由 **Q295** 翻正的注记、§5 覆盖率停在 2026-09-27 首读；⑤ docs/19「已经结掉的」缺 ②（Q295）与 ⑦（Q288）两行；⑥ docs/23 §0.1 测试/覆盖率两行＋§2 规模表三行（68→**69 表**、迁移 49→**50**／头 **0050**、1157→**1181**、128→**130** 测试文件）。
> - **docs/23 §11.13 追加真 PG16 复测四条**（一次性容器宿主 5543/5544，跑完即删零残留）：`pg_indexes.indexdef` 原文含 `WHERE ((status)::text = 'active'::text)`／重复 active 第二条被拒、`archived` 与异 `kind` 放行（证索引确为**部分**且键含 `kind`）／**fail-loud 实证**＝退 0047 植两行重复后 `upgrade head` **exit 1**，且 PG 事务性 DDL 使 `alembic current` 停 0047、`pg_indexes` 零残留（**不是半应用状态**），删重复行即复建／0047⇄0048 往返对称；索引计数 243→**244**（业务表闭合口径 68+29+147，含 `alembic_version` 则 245）。**该轮读数跑时工作树 head＝0048**（同日稍晚 Q300 落进同一共享工作树使 head 前移），口径已在 §11.13 就地声明。
> - **README 状态段**停在 **Q293** → 补 **Q294–Q301** 八批与逐批测试增量分解（1147→1181）。**纪律**：历史台账／评审快照／已被取代的待办段一律不回改；未新增待裁项。
> - **【复判不变】**：① 达标／② 达标（Q295 翻正后保持）／③ 未达标（现网部署＋真 ACME 签发未证＋待裁项③）。纯文档批不改任何一层判定。

## Q303 残余摘要行原文（于 2026-10-08 按「最近 5 条」上限滚出；其 banner 原文见本文件上方 Q303 节）

> **其前（2026-10-07）：Q303 覆盖率读数复测（**纯测量**，71.71%／13,341 语句／核心 99.34%·604，基线 1181 passed＋10 skipped 不变，02 C1.246）**——原文已逐字滚档至 [docs/handoff-archive-2026-10-07.md](docs/handoff-archive-2026-10-07.md)。

## Q304 banner 原文（于 2026-10-08 按「最近 5 条」上限滚出，含其四条子项，逐字未改）

> **其前（2026-10-07）：Q304 覆盖率读数对账批（**纯文档零代码零迁移零测试变化**；基线不变 **1181 passed＋10 skipped／收集 1191**、头 `0050_platform_adapter_candidates`；02 C1.247）**——负责人「开搞」＝Q303 复测后残余活状态句子一次性对账。
> - **对账六处刷到 Q303 读数（71.71%／13,341 语句／核心 99.34%·604）**：handoff 待办⑤、AGENTS 待裁⑤、docs/19 §5、docs/16 §4（追加 Q303 段）、docs/README 地图 docs/02 行（前移 Q303/C1.246）、CHANGELOG（补登 Q303 条目——Q303 批漏登，按 Q298 同型先例补）。
> - **docs/23 §8.3 两行按代码事实更正**：P1 段7/8「未落两件」按 Q296（fit 可解释化）＋Q299（人工校准审计）＋Q300（adapter 候选表/HumanGate）落地收窄为真自学习＋真模型接线两件（随 V2）；P2 段9 三包「DB 级唯一约束并不存在」删旧句改「0048 部分唯一索引已建（Q288，见 docs/23 §11.13 真 PG16 复测）」。
> - **CI 实测**：Q303 推送后两 run 全 success＝push 37634906506／PR 37634968197（六道门绿）。
> - **【复判不变】**：① 达标／② 达标（Q295 翻正后保持）／③ 未达标（现网部署＋真 ACME＋待裁项③）。

