# Loom · 契约层 · API 与状态机

> **本文档来源**：`../Loom_核心业务主链梳理_v3.md` **Part A / Part C / Part D 结构化提取**（重组视图，非原文直排）。
> **文档定位**：AI 落代码的硬前提之一。系统对外/对内 API 契约 + 全部已定义状态机。**原文未给出的事件/迁移/字段一律标注【待补：原文未给出】，不编造**。
> **配套文档**：实体字段见 04；WF/Skill 协议见 06。

---

## Part 1 · API 契约

### 1.1 已定稿契约（原文给出完整定义）

#### 1.1.1 POST /api/effect-callback（段13 · Q60，**契约完整**）
- **用途**：效果数据回流（全链唯一反向边的数据入口）。
- **调用方**：外部 Agent 系统（本系统不做抓取、不做定时拉取调度，Q62）。
- **鉴权**：API Key（一 Agent 一 Key，可吊销，复用 API Key 管理模块）。
- **请求体**：
  ```
  {
    source: string,                       // Agent 标识；客户回填时 = "customer-backfill"
    records: [{
      content_id: string,                 // 本系统内容 ID（发布后由运营回填 platform_post_id 建立映射）
      platform_post_id: string,           // 平台帖子链接/ID
      captured_at: datetime,              // 采集时间
      metrics: {                          // 全部可选字段
        plays, likes, comments, shares, read_rate, inquiries, conversions
      }
    }]
  }
  ```
- **数据纪律**：缺席字段=未采集记"—"，**绝不当 0 / 不许估算**。
- **幂等/时序**：同 content_id 多次推送按 captured_at 追加为时间序列；同 content_id+captured_at 幂等覆盖。
- **孤儿数据处理**：对不上 content_id 的推送进"孤儿数据"队列人工认领（Q60a）。
- **发布链路（业务澄清 Q60c）**：客户确认（仅审批信号）→ **运营用托管账号发布** → **运营回填平台链接/ID** → Agent 抓取 → 本 API 推送。前端客户不填写平台链接。

#### 1.1.2 白名单消费接口（段11/5 · Q71，**契约主体完整**）
- **用途**：系统后台 API 端消费内容配方（PWC/白名单）。
- **取用排序**：按评分从高到低取（Q22 PWC 分 / Q54 FCW 分，临时公式够排序）。
- **去重**：同平台+同账号+同发布位不重复（Q24）；命中即写 usage_record 并流转状态。
- **保底补给**：待用池跌破保底线自动触发一轮相撞补货回目标量；触发线=critical（50）、目标=target（100），补货冷却默认 5min（防抖）。
- **池健康度三档**：target 100 / min 70 / critical 50（line 1451）。
- ⚠ 参考来源：业务方 E1 `/api/whitelist/consume`（按权重取 + usage_record + 5 池保底）——采纳骨架但**不采用"上限 200"**，一律以本系统池健康度三档为准。

### 1.2 已点名但契约未定稿（开发补规格范围）

| API | 来源 | 现状 |
|---|---|---|
| 白名单查询 API | D9.5 系统后台 API 端 | 仅有页面清单，无契约【待补】 |
| 使用记录上报 API | D9.5 / Q71 | 同上【待补】 |
| 效果回流 API | D9.5 / Q60 | Q60 已定稿（见 1.1.1） |
| DB 浏览 / AI 调试台 / 调用日志 / 配额 / Key 管理 | D9.5 | 后台内部接口【待补】 |
| 中台对接 API + Webhook 反馈回流 | D4 | V2 项：中台调 API 拿白名单 + Webhook 回流【待补】 |
| 中台 SDK 嵌入 | D4 | V3 项：中台集成 Loom SDK【待补】 |
| 中台 CSV/JSON 导出 | D4 | V1 项：导出白名单包，中台手动用【待补】 |

### 1.3 鉴权与治理（横切）
- **API Key 唯一入口**：真接 LLM 时模型注册页是唯一入口（line 2101）；Q67 合并为一张模型注册表（per-1M）。
- **单一出口红线（line 11036）**：全系统只有 E1.1 publishFCW 能生成 final_content_whitelist_id；任何其他模块/Skill/Agent 写 final_id = 越权 = 违反协议。

### 1.4 M1–M11 已落地 REST 端点（2026-09-13 起后端切片实现登记；实现序 M7→M11→M8，段11 已闭合）

> 以下为已实现端点（FastAPI，前缀见各行）；原文未给契约，属"开发补规格"落地，**不是已定稿契约的替代**——后续契约层定稿以本节实现为对账输入。错误口径统一：不存在 404 / 业务状态不允许 409 / 角色不符 403 / 输入或规则校验失败 422；所有写操作 writeAudit。

**M1 段1 产品录入（前缀 `/api/intakes`）**

| 方法/路径 | 说明 | 依据 |
|---|---|---|
| POST `` | 创建申请单 | 13 §1.1 |
| GET `/{intake_id}` / `/{intake_id}/allowed-events` / `/{intake_id}/product-space` | 查询/可迁事件/生成的 PS | — |
| PATCH `/{intake_id}/profile` | 补资料（审核后不可改 409） | Q74 |
| POST `/{intake_id}/transitions` | 15 态事件迁移（缺字段 422 / 越权 403 / 非法迁移 409） | Q3/Q5 |

**M2 段2 C1 识别（前缀 `/api`）**

| 方法/路径 | 说明 | 依据 |
|---|---|---|
| GET/PUT `/admin/c1/signal-weights` | Q2 权重表（Σ≠1 → 422） | Q2 |
| GET/POST `/admin/c1/industries`，PATCH/DELETE `/admin/c1/industries/{industry}` | Q7 阈值 CRUD（默认档删 → 409） | Q7 |
| POST `/intakes/{intake_id}/c1-recognition` | conf 三分支（高置信 auto_confirm；中置信出待办；低置信须带 category_pending_id） | Q1/Q3/Q5 |
| POST `/intakes/{intake_id}/ops-decision` | 运营选定/全否 | Q3 |
| POST `/admin/ops-todos/sweep` | 72h 到期升级（手工触发；调度随 M10） | Q4 |
| POST/GET `/categories`，PUT `/categories/{category_id}/template` | G1 最小切片 + 叶子模板（fid:'-'/未知 fid → 422） | Q68 |
| POST `/intakes/{intake_id}/c7-runs` | C7 L1–L4 兜底（L4 提案入库候选） | Q6/Q68 |

**M3 段3 字段池规划（前缀 `/api`）**

| 方法/路径 | 说明 | 依据 |
|---|---|---|
| GET `/admin/fp-source-routes`，PUT/DELETE `/admin/fp-source-routes/{route}` | Q8 来源路由 CRUD（被维度引用 → 409） | Q8 |
| POST/GET `/product-spaces/{product_space_id}/field-pools`（+ `/current`） | 方案提交（一品一池；违规落 violations 仍 pending_gate）/查当前池 | PT-FP-PLAN |
| POST `/field-pools/{pool_id}/gate` | WF-02 HumanGate（product_reviewer；非合规批 → 409） | Q9/Q11/Q12 |
| POST `/field-pools/{pool_id}/dimensions/{dimension_id}/restore` | 备选档捞回（满 8 挤回最低置信） | Q12 |
| GET `/admin/g2-candidates`，POST `/admin/g2-candidates/{candidate_id}/promote` | 候选列表 / Q13 转正（dictionary_admin；fid 冲突/重复转正 → 409，转正回填池维度） | Q13/Q68 |

**M4 段4 原子拓展（前缀 `/api`）**

| 方法/路径 | 说明 | 依据 |
|---|---|---|
| GET/POST `/admin/compliance-wordlist`，PUT/DELETE `/admin/compliance-wordlist/{entry_id}` | Q48 统一词表 CRUD（operations/internal_compliance；downgrade 缺目标 422；DELETE=软归档；段 5/10 后续同表读取） | Q48/Q51 |
| POST `/product-spaces/{product_space_id}/atom-batches` | WF-03 候选批次（仅产 candidate；池非 approved → 409；Q14 超限 422 可覆盖；Q15 AI 达标 409、manual 放行；同批去重/维度归属 422；事实原子跨产品撞值 409）；响应内嵌 AtomConflict | Q14/Q15/PT-ATOM-EXP/line 11189 |
| GET `/product-spaces/{product_space_id}/atom-candidates`、`/atoms` | 候选列表（可按 status）/正式原子列表 | — |
| POST `/atom-candidates/{id}/approve`、POST `/atom-candidates/batch-approve` | approveAtomGuard（product_reviewer；违规码数组 409；high/critical 批量 409，Q70） | line 2633/Q70 |
| POST `/atom-candidates/{id}/reject` `/evidence` `/revive` | 驳回（critical 禁用表达记合规审计动作）/ 补证据（解 evidence_required）/ 仅 evidence_timeout 驳回复活 | Q18/line 840 |
| POST `/atom-clusters/{cluster_id}/resolve` | Q19 同义簇人工终裁 keeper，非 keeper 置 merged 为 alias | Q19 |
| POST `/atom-candidates/{id}/risk-override` | 人工复核改判（词表强制定级 409 不可改；AI 判级可改并重建冲突集） | Q17 |
| POST `/atoms/{id}/freeze` `/unfreeze` `/compliance-suspend` `/compliance-resume` `/deprecate` `/archive` `/reject` | atom8 生命周期：freeze/unfreeze/deprecate/archive=operations（解冻不重审、废弃不原地复活）；suspend/resume=internal_compliance；reject=product_reviewer | Q20 |
| POST `/admin/atom-evidence/sweep`（**未开 HTTP**） | Q18 超时扫描已实现为服务函数 `sweep_evidence_timeouts`，定时触发随 M10；当前仅测试/内部调用 | Q18 |

**M5 段5 PWC 条件包（前缀 `/api`）**

| 方法/路径 | 说明 | 依据 |
|---|---|---|
| GET/PUT `/admin/content-goals`，POST `/admin/content-goals/{code}/archive` | Q25 五类 contentGoals 字典（种子 ENGAGEMENT/CONVERSION/EDUCATION/TRUST/RETENTION；dictionary_admin；ratio_min≤ratio_max 否则 422；软归档） | Q25/line 1090 |
| GET/PUT `/product-spaces/{id}/pwc-pool-config` | Q27 库容配置（operations；默认 100，capacity=null 无上限；target_platforms/high_reuse_n） | Q27/Q24 |
| POST `/product-spaces/{id}/pwc/funnel` | WF-04 漏斗：预筛→Q48 合规检测（ban→blocked；手拼不豁免 Q26）→Q22 评分（AI 子分缺失不凑分）→限量 50；池非 approved 409；结构/跨租户/停用 goal 422；返回 PWC 视图数组 | Q21/Q22/Q23/Q26 |
| GET `/product-spaces/{id}/pwcs` | 条件包列表（score 降序 null 末位，含 combo 原子与合规/评分明细） | — |
| POST `/pwcs/{pwc_id}/gate` | HumanGate（product_reviewer；approve→ready 受库容 409；reject→archived；blocked 不可批 409） | Q21/Q27 |
| POST `/product-spaces/{id}/pwc/consume` | Q71 消费：score 降序取用，同平台+账号+发布位去重，跨平台可复用，goals 交集过滤；响应带 usage_record/platform_state/pool_ready_count/pool_health/restock_hint；无可取 409 | Q24/Q71 |
| POST `/pwcs/{pwc_id}/hot` `/archive` | Q61 爆款手工标/取消（operations；V1 无自动检测）；归档（operations） | Q61/Q24 |
| 冷却 sweep / 自动补货（**未开 HTTP**） | `sweep_cooldowns`（14 天到期回 available）已实现为服务函数；critical→target 自动补货（5 分钟防抖）未实现；定时触发随 M10 | Q24/Q71 |

**M6 段6 PWS 冻结（前缀 `/api`）**

| 方法/路径 | 说明 | 依据 |
|---|---|---|
| GET `/product-spaces/{id}/pws/readiness` | pwsReadiness 5 项机械求值 + 计数明细（PS 不存在 404） | line 2634 |
| POST `/product-spaces/{id}/pws/evaluate` | 全绿时系统出 pws_ready 待办（whitelist_owner，7 天 due，幂等）；不全绿只回状态不出单 | Q28 |
| POST `/product-spaces/{id}/pws/freeze` | BO-07 冻结/重冻（whitelist_owner；非属主 403；不全绿 409 回带 5 项）；首冻 v1.0 免原因，重冻须 reason_code（缺失/未知 422，none 档 409）；返回快照+items、dup_hints、Q30 dispositions | Q29/Q30/Q31/Q33/line 7674 |
| POST `/pws/{pws_id}/revoke` | Q32 急停（whitelist_owner；仅 active frozen 可作废，否则 409）；作废后可重冻新版 | Q32 |
| GET `/product-spaces/{id}/pws`、GET `/pws/{pws_id}` | 版本列表（主版本号倒序，同刻仅 1 active）/ 版本明细含物化 items；superseded/revoked 只读 | Q31 |

**M7 段10 合规清洗（前缀 `/api`）**

| 方法/路径 | 说明 | 依据 |
|---|---|---|
| GET/POST `/admin/cp-law-domains`，PUT/DELETE `/admin/cp-law-domains/{id}` | CP-LAW 敏感领域小表 CRUD（internal_compliance；code 唯一 409；DELETE=软归档；迁移种子 medical/children/weight_loss/whitening/medical_device/finance） | Q48/Q49 |
| POST `/pws/{pws_id}/ccr/run` | WF-08 机械清洗：仅 active frozen 可跑（否则 409）；同源自 M4 词库按行业+市场取词，Q50 国家>平台>底座裁决（同级 Q36 从严）；ban→`blocked/block_required=true`、downgrade→`downgrade_pending` 只出建议、无命中→`clean`；敏感领域同事务幂等触发法审；报告 append-only | PT-COMPLIANCE/Q48-Q50 |
| GET `/pws/{pws_id}/ccr`、GET `/pws/{pws_id}/ccr/gate?country=` | 报告历史（新→旧，同秒按 id 兜底）/ 供段11 Guard②⑥ 消费的机械视图（block_required/cleaning_passed/law_review_passed） | Q53 |
| POST `/ccr/{ccr_id}/approve-downgrades` | 降级建议人工 approval（internal_compliance；仅 downgrade_pending 可批，否则 409）；批后 cleaning_passed | PT-COMPLIANCE |
| GET `/pws/{pws_id}/law-reviews`、POST `/law-reviews/{id}/decision` | 法审记录查询/线下律师结论录入（internal_compliance；approved/rejected，已决再判 409；通过放行 Guard⑥、不通过维持否决；同步开关法审待办） | Q49 |
| Q51 生效即扫（**无独立端点**） | 词表 POST/PUT 保存生效即在同事务扫描全部 active frozen 快照（按行业过滤），命中产出 `wordlist_rescan` 待办（whitelist_owner，detail.reason_code=wordlist_hit，开放待办幂等），响应附 `q51_impacted`；重冻新版本仍须 BO-07 人工执行；定时扫未来生效词条随 M10 | Q51/Q29 |

**M11 段7/8 静态底表 + 段9 三包（前缀 `/api`，实现序先于 M8：段11 七 Guard 需要静态 PCP/三包实例）**

| 方法/路径 | 说明 | 依据 |
|---|---|---|
| GET/POST `/admin/publish-slots`，PUT/DELETE `/admin/publish-slots/{slot_id}` | 发布位档案 CRUD（operations；code 唯一 409；四维分 score_source=manual_eval + source_url；DELETE=软归档）；**无平台目录种子（line 1098-1221 原文【待补】）** | Q35/line 1098 |
| GET `/admin/publish-slots/{slot_id}/fit-score?goal=` | Q34 派生值（不落库）：Σ 四维分×目的权重；目的未配权重 → fit_score=null/incomplete=true，不凑分 | Q34 |
| GET/PUT `/admin/fit-weights` | 目的权重矩阵（operations；4 维齐 + Σ=1 硬校验 422，不归一化；goal 须活跃 content_goals 否则 404；种子 ENGAGEMENT/CONVERSION） | Q34 |
| GET/POST `/admin/platform-rules`，DELETE `/admin/platform-rules/{rule_id}`，GET `/admin/platform-rules/match` | 4 层 selector + country 横切；层级必填字段 422、effect 仅 blocked/partial；同级同条件异结论保存 → 409 回冲突行，`overwrite=true` 重发归档旧行；match=高优先级层级覆盖、同级从严；native 默认不存 | Q36/line 1383 |
| GET/PUT `/admin/slot-type-defaults` | slotType 默认值（operations；min>max 422；约 40 列走 defaults JSON，明细【待补】） | line 1428 |
| GET `/admin/pcp-templates` | Q39 四模板只读（种子 short_video/community/photo_text/ecommerce，17 键 Σ=1.0；实现期初值草稿） | Q39 |
| GET/POST `/product-spaces/{id}/pcp`，PUT `/pcp/{pcp_id}` | PCP 实例（operations；PS 不存在 404；模板派生或显式 weights，17 键 Σ≤1.0 统一校验器 422；同 PS×平台 active 唯一 409；PUT 为 Q42 人工直编通道，清空 template_code + before/after 审计） | Q40/Q42/Q52/PT-PCP-V1.5 |
| GET/POST `/product-spaces/{id}/packages`，PUT/DELETE `/packages/{package_id}` | 段9 CSP/CSTP/CEP 静态实例（operations；payload 键按 04 §2.17 定死，缺/多键 422；产品×平台×目的×包型 active 唯一 409；goal 须活跃；DELETE=软归档；行带 tenant/PS 供段11 Guard④⑤） | Q45/Q52/line 863 |

**M8 段11 FCW 组装（前缀 `/api`，E1.1 publishFCW = final_id 唯一出口，line 11036）**

| 方法/路径 | 说明 | 依据 |
|---|---|---|
| POST `/fcw/assemble` | 手动单条发证（operations；body 指定 PS/pws_id(缺省取 active 版)/platform/slot_id/goal/country）：机械解析六路材料→7 项 Guard，全绿 mint final_id 直接 published；任一 Guard 败 → 409 回带逐项 guards（不生成 final_id，失败尝试仍 writeAudit `fcw.assembly_blocked` 并提交）；材料缺失 409、slot/平台不符 422、goal 未知 404、重复发证 409 | PT-FCW-ASM/Q52/Q53/Q55 |
| POST `/fcw/assembly-tasks` | Q55 任务驱动批量（operations；product×platform×goal×count，可选 slot_ids 长度须=count 且不重复否则 422）：同步逐条组装，不给 slot_ids 时取该平台 active 发布位前 N；单项失败（Guard/材料/去重）不阻断其余，任务 completed，results 留痕 issued/failures 每条原因；每条发证 writeAudit `fcw.issued`（六路材料+Guard 结果+E1_owner=publishFCW），任务另记 `fcw.assembly_task` | Q55 |
| GET `/fcw/assembly-tasks/{task_id}` | 任务结果（不存在 404） | Q55 |
| GET `/product-spaces/{id}/fcw`、GET `/fcw/{final_id}` | 成品列表（新→旧）/单条明细（含 guards 明细、score/score_detail/incomplete） | line 870 |

> Guard 七项 code：`g1_pws_frozen`（PWS status=frozen）/`g2_compliance_clear`（block_required=false **且** cleaning_passed=true，无报告不放行【实现补】）/`g3_packages_active`（PCP active + CSP/CSTP/CEP active 且 gate=approved）/`g4_product_space_consistent`（六路 PS 一致）/`g5_tenant_consistent`（六路 tenant 一致）/`g6_law_review`（仅法审被触发时要求 approved，Q49）/`g7_pws_active_version`（is_active=true）。Q54 score（pwc×100×0.4 + fit×0.3 + 三包 conf 均值×100×0.3）仅排序，缺失即 null/incomplete=true，永不做门槛。draft publish_status V1 无创建入口；WF-09 AI Skill 随 V2。

**M10 切片 a · 配置中心**（2026-09-14，迁移 0010，路由前缀 `/api/admin/config`）

| 方法/路径 | 说明 | 依据 |
|---|---|---|
| GET `` （`?category=` 可过滤） | 配置项列表（key/category/value/value_type/validation/source_ref/version/时间）；只读 | 02 §C2 / 07 §2.4 |
| GET `/{key}` / GET `/{key}/history` | 单项（未知键 404）/版本历史（新→旧，种子为 v1） | 14 §2.4 |
| PUT `/{key}` | 改值发布（仅 `platform_admin`【实现补：07 §2.3 平台级管理员 Q46/Q64 的英文角色码】；body=value/change_note/actor）：类型+min/max/choices 校验失败 422、未知键 404、越权 403；发布=coerce→value/version+1→写版本行→writeAudit(`config.update`)→事务提交后进程内快照原子切换 | 14 §2.4 |
| POST `/{key}/rollback` | 回滚到历史版本（platform_admin；target_version 不存在 404）：以新版本号重发该值（非覆盖历史），默认 change_note `rollback to vN`，writeAudit(`config.rollback`) | 14 §2.4 |

> 发布语义严格按 14 §2.4：新版本 + 原子切换 + writeAudit；快照切换挂在 SQLAlchemy `after_commit`，事务回滚/校验失败不触缓存（已测试）。V1 单进程模块化单体，仅做进程内热更新；多副本变更广播（Redis pub/sub）【挂账，多副本部署前补】。配置缓存的进程启动加载与各业务模块常量消费迁移在后续切片，当前 M1–M8 拍板值仍读代码常量。

---

## Part 2 · 状态机定义

> 表格列：当前状态 → 触发事件 → 目标状态 → Guard/条件。**事件与迁移原文未逐条给出者标【待补】**（v3 只给状态清单与部分流转规则，实现时需按 Q 编号逐条补迁移表）。

### 2.1 productIntake15（段1 · 录入申请单，line 1454 + Q5）
| 状态 | 说明 | 已知迁移/触发 | Guard/条件 |
|---|---|---|---|
| 草稿 | 初始 | → AI识别中（提交） | 输入完整（G2 18 通用字段） |
| AI识别中 | 6 Skill 串行处理 | → 待确认 / 待补充参数 / 待确认额度 / 类目创建中 | 见 WF-01（06 文档） |
| 待确认 | 类目确认（由运营执行，Q3） | → 已提交 / 类目创建中 | 运营 72h 未处理升级（Q4） |
| 待补充参数 | 缺参数 | → 已提交 / 驳回 | 【待补】 |
| 待确认额度 | 额度确认 | → 已提交 | 【待补】 |
| 已提交 | 提交审核 | → 审核中 | 【待补】 |
| 审核中 | 后台审核 | → 需补充资料 / 已通过 / 驳回 | 【待补】 |
| 需补充资料 | 缺资料 | → 已提交 | 【待补】 |
| 已通过 | 审核通过 | → 建模中 | 【待补】 |
| 建模中 | 冷启动/建模 | → 已入库 / 入库失败 | 【待补】 |
| 已入库 | 完成 | 终态 | — |
| 入库失败 | 失败 | → 需补充资料 / 驳回 | 【待补】 |
| 驳回 | 终态 | — | — |
| 已归档 | 终态 | — | — |
| **类目创建中**（Q5 新增第 15 态） | 冷启动支线停靠位，关联 B2 新类目候选单 | B2 通过→待补充参数；B2 驳回→运营二选一：挂最近父类目继续 / 打回需补充资料 | 客户端显示中性话术"资料分析中" |

### 2.2 atom8（段4 · 原子实例，line 1454 + Q17-Q20）
| 状态 | 已知迁移/触发 | Guard/条件 |
|---|---|---|
| 草稿 | → 待审核（拓展产出候选） | 仅产 candidate 不直接写实例（PT-ATOM-EXP） |
| 待审核 | → 已通过 / 已驳回 | approveAtomGuard 10 项（01 段4）；high/critical 必走 HumanGate（critical 单条审） |
| 已通过 | → 已冻结 / 已废弃 / 已驳回 | 冻结=运营、废弃复活重走审核（Q20） |
| 已冻结 | 单条原子暂停（≠PWS 冻结，注意区分） | 解冻不重审（Q20） |
| 已废弃 | 终态（可恢复=重走审核） | Q20 |
| 已驳回 | → 已通过（复活重提） | pending_evidence 超时自动驳回可复活（Q18） |
| 合规暂停 | 合规角色触发；恢复须合规角色复核 | Q20 |
| 归档 | 终态 | — |

### 2.3 skill7（横切 · Skill 输出状态机，line 11314）
| 状态 | 迁移 | Guard/条件 |
|---|---|---|
| ai_suggested | → pending_review | Critical Skill 输出必须走候选通道 |
| pending_review | → confirmed / modified / rejected | 人工 Gate |
| confirmed | → applied / archived | 应用到正式对象 |
| modified | → applied / archived | 人工修改后应用 |
| rejected | → archived | 拒绝后归档 |
| applied | 应用态 | — |
| archived | 终态 | — |

### 2.4 G1 类目状态机（段2）
| 状态 | 说明 | Guard/条件 |
|---|---|---|
| active | 正常可用 | — |
| draft | 草稿 | — |
| review | 审核中 | — |
| deprecated | 已废弃 | — |
| archived | 已归档 | — |
| merged | 合并（merged_into 永久重定向，否则历史 PS 悬空） | A6 |

### 2.5 PWS 版本状态（段6 · Q28-Q33）
| 状态 | 说明 | Guard/条件 |
|---|---|---|
| 待冻结（pwsReadiness 检查中） | 5 项就绪门全绿出待办推 BO-07 | 就绪后 7 天未冻升级（Q28） |
| frozen | 可消费（下游段 7-11 唯一合法输入） | 必须 BO-07 + 人工 Gate（红线，line 7674） |
| superseded | 旧版只读保留（同刻仅 1 个 active） | Q30/Q31 |
| active | 当前版本（段 11 Guard⑦ 要求） | Q53 |
| revoked | 急停（立即断消费，作废后重冻新版） | Q32 |

> **实现补登（2026-09-14，M6 后端切片）**："待冻结"不落状态——evaluate 仅机械求值 5 门并在全绿时出 pws_ready OpsTodo（7 天 due，幂等；升级复用 M2 sweep）；快照落库即 frozen。"active"不单独成态：frozen + is_active=true 为当前版本，重冻时旧版翻 superseded/is_active=false 并写 supersede+refreeze 双日志，revoked 亦 is_active=false；superseded/revoked 为只读终态，不可再作废/再当活动版（Q32 作废后须重冻新版，仍过 5 门）。重冻触发原因 → Q29 三档（forced/suggested/none），已存在 active 版时原因缺失或未知 422、none 档 409。

### 2.6 PWC 状态流转（段5 · line 1780-1806 + Q24）
| 状态 | 已知触发 | Guard/条件 |
|---|---|---|
| 候选 | 组合生成（漏斗产出） | 预筛→检测→评分→限量（Q21） |
| 待Gate | 进审核 | 人工 Gate |
| 待用 | 审核通过入待用池（库容默认 100） | Q27 |
| 已用 | 同平台+账号+发布位用 1 次 | 跨平台可复用；全平台用尽转已用（Q24） |
| 冷却 | 同平台 7 天消费 ≥3 次 | 14 天回待用（Q24） |
| 爆款 | 一期手工标注；自动判定留段 13（Q61 中位数 5 倍+门槛） | Q24/Q61 |
| 阻断 | 冲突/合规阻断 | Q26 |
| 待入库 | 入库前 | 【待补】 |
| 归档 | 终态 | — |

### 2.7 平台适配四态（段7 · PT-PLATFORM-ADAPTER）
| 状态 | 说明 | Guard/条件 |
|---|---|---|
| allow | 允许 | 只读 frozen PWS；AI 输出一律 pending_review 需 HumanGate |
| downgrade | 降级 | 降级动作只能从 Q38 动作字典选 |
| block | 阻断 | 最严 |
| pending_review | 待审（AI 候选默认态） | 禁止生成 final_id、禁止输出成稿 |

### 2.8 发布位/平台规则 Gate 状态（段7）
| 状态 | 说明 | 来源 |
|---|---|---|
| pending_gate | AI 拓展候选默认态（四维全 0） | line 1098-1221 |
| approved | 过 Gate 启用 | Q35 |

### 2.9 客户审阅动作（段12 · Q59）
| 动作 | 结果 | Guard/条件 |
|---|---|---|
| 通过 | 转"客户已确认"进发布 | — |
| 驳回 | 必选原因，退运营，原因回流段13 | 原因必填 |
| 改稿 | 强制重过 CONTENT-COMPLIANCE 复检（4 项），不过不生效 | 复检=词库扫描+语义级+施工指令+国家规则 |

### 2.10 原子 evidence 状态（段4 · Q18）
| 状态 | 说明 | Guard/条件 |
|---|---|---|
| pending_evidence | AI 自动补一轮 → 运营待办 → 7 天超时自动驳回 | 超时自动驳回可复活 |
| evidence 完备 | 可进审核 | evidence 必填 |

### 2.11 冷启动三分支（段2 · Q1/Q3，流程分支非状态机）
- conf ≥ 行业阈值 → direct_approve
- [0.6, 行业阈值) 或 Top1-Top2 差 <0.1 → ops_assist（运营待办选定，客户无感知；72h 未处理升级；全否转 cold_start）
- conf < 0.6 → cold_start（推 B2 生成候选类目 → 申请单进"类目创建中"）

---

> **信息保全**：API 与状态机全部条目来自 v3 Part A/C/D 原文（逐项带 line/Q 来源）；原文未定义的事件/迁移/字段已显式标注【待补】，未新增虚构逻辑。PWC 状态"待入库"等原文仅列名的迁移为待补项（属开发第 0 步范围，见 01 §7）。
