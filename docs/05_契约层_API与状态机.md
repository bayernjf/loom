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
- **API Key 唯一入口**：真接 LLM 时模型注册页是唯一入口（line 2101）；Q67 合并为一张模型注册表（per-1M）。**Q82 已落地 outbound 半套**：Key 密文落库 + env 主密钥、注册页录入/轮换/吊销，明文永不回显；入站"一 Agent 一 Key 可吊销"（Q60 效果回调）延后切片。
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
| GET/PUT `/admin/c1/signal-weights` | Q2 权重表（Σ≠1 → 422；operations；越权 403，Q75 补闸） | Q2 |
| GET/POST `/admin/c1/industries`，PATCH/DELETE `/admin/c1/industries/{industry}` | Q7 阈值 CRUD（operations；越权 403，Q75 补闸；默认档删 → 409） | Q7/Q75 |
| POST `/intakes/{intake_id}/c1-recognition` | conf 三分支（高置信 auto_confirm；中置信出待办；低置信须带 category_pending_id） | Q1/Q3/Q5 |
| POST `/intakes/{intake_id}/ops-decision` | 运营选定/全否 | Q3 |
| POST `/admin/ops-todos/sweep` | 72h 到期升级（手工触发，**platform_admin**，越权 403；Q75；调度随 M10） | Q4/Q75 |
| POST/GET `/categories`，PUT `/categories/{category_id}/template` | G1 最小切片 + 叶子模板（**dictionary_admin**，越权 403；fid:'-'/未知 fid → 422；Q75） | Q68/Q75 |
| POST `/intakes/{intake_id}/c7-runs` | C7 L1–L4 兜底（L4 提案入库候选） | Q6/Q68 |

**M3 段3 字段池规划（前缀 `/api`）**

| 方法/路径 | 说明 | 依据 |
|---|---|---|
| GET `/admin/fp-source-routes`，PUT/DELETE `/admin/fp-source-routes/{route}` | Q8 来源路由 CRUD（operations；越权 403，Q75 补闸；被维度引用 → 409） | Q8/Q75 |
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
| POST `/atom-candidates/{id}/reject` `/evidence` `/revive` | 驳回（critical 禁用表达记合规审计动作）/ 补证据（解 evidence_required）/ 仅 evidence_timeout 驳回复活（**revive 有意不设角色闸**，前置状态即闸，Q75） | Q18/Q75/line 840 |
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
| 冷却 sweep / 自动补货（**补货已实现，sweep 未开 HTTP**） | `sweep_cooldowns`（14 天到期回 available）已实现为服务函数；**critical→target 自动补货已于切片 e 接通**（Q76-4：跌破 critical 经 5 分钟防抖落 `skill_runs(status=requested)`，不造候选，consume 响应回带 `restock_run_id`）；冷却 sweep 定时触发随 M10 | Q24/Q71/Q76 |

**M6 段6 PWS 冻结（前缀 `/api`）**

| 方法/路径 | 说明 | 依据 |
|---|---|---|
| GET `/product-spaces/{id}/pws/readiness` | pwsReadiness 5 项机械求值 + 计数明细（PS 不存在 404） | line 2634 |
| POST `/product-spaces/{id}/pws/evaluate` | 全绿时系统出 pws_ready 待办（whitelist_owner，7 天 due，幂等）；不全绿只回状态不出单（**有意不设角色闸**：系统提请的机械求值，Q75） | Q28/Q75 |
| POST `/product-spaces/{id}/pws/freeze` | BO-07 冻结/重冻（whitelist_owner；非属主 403；不全绿 409 回带 5 项）；首冻 v1.0 免原因，重冻须 reason_code（缺失/未知 422，none 档 409）；返回快照+items、dup_hints、Q30 dispositions | Q29/Q30/Q31/Q33/line 7674 |
| POST `/pws/{pws_id}/revoke` | Q32 急停（whitelist_owner；仅 active frozen 可作废，否则 409）；作废后可重冻新版 | Q32 |
| GET `/product-spaces/{id}/pws`、GET `/pws/{pws_id}` | 版本列表（主版本号倒序，同刻仅 1 active）/ 版本明细含物化 items；superseded/revoked 只读 | Q31 |

**M7 段10 合规清洗（前缀 `/api`）**

| 方法/路径 | 说明 | 依据 |
|---|---|---|
| GET/POST `/admin/cp-law-domains`，PUT/DELETE `/admin/cp-law-domains/{id}` | CP-LAW 敏感领域小表 CRUD（internal_compliance；code 唯一 409；DELETE=软归档；迁移种子 medical/children/weight_loss/whitening/medical_device/finance） | Q48/Q49 |
| POST `/pws/{pws_id}/ccr/run` | WF-08 机械清洗（**internal_compliance 触发**，越权 403，Q75）：仅 active frozen 可跑（否则 409）；同源自 M4 词库按行业+市场取词，Q50 国家>平台>底座裁决（同级 Q36 从严）；ban→`blocked/block_required=true`、downgrade→`downgrade_pending` 只出建议、无命中→`clean`；敏感领域同事务幂等触发法审；报告 append-only | PT-COMPLIANCE/Q48-Q50/Q75 |
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

> 发布语义严格按 14 §2.4：新版本 + 原子切换 + writeAudit；快照切换挂在 SQLAlchemy `after_commit`，事务回滚/校验失败不触缓存（已测试）。V1 单进程模块化单体，仅做进程内热更新；多副本变更广播（Redis pub/sub）【挂账，多副本部署前补】。进程启动加载与业务常量消费已在切片 c 接通（见下）。

**M10 切片 c · 缓存引导 + 常量迁移**（2026-09-14，无新表/无新端点/无迁移）

> 消费侧统一入口 `knob(key)`（`app/core/config_center/knobs.py`）：读进程内 `config_cache`，缓存未引导或键缺失时回落种子表拍板值（`SEED_BY_KEY` 为默认值唯一事实源）。M1–M8 拍板值全部由代码常量迁为零参访问器函数：c1 冷启动 0.6/TopGap 0.1/ops 72h、c7 L3 覆盖 0.6、fieldpool 0.85/0.9/3–8/15–30（请求契约默认值走 `Field(default_factory=...)` 按请求取值）、atom 20·50/0.5/7 天、pwc 50/100·70·50/5min/100/0.6·0.4/0.5·0.5/1.0/0.8/7·3·14、pws 3·1/7 天、ccr 48h、sla 黄 24h、fcw 0.4·0.3·0.3；状态字符串/原因码映射等非标量规则不动。纯函数权重入参缺省为 `None` 并在函数内解析，显式传值仍覆盖（测试/未来分行业配置）。启动引导：lifespan 在调度器启动前以独立会话全量 reload；失败仅告警不阻断启动（knob 回落种子值）。发布后的热更路径不变（切片 a after_commit apply），故运营改值对所有规则访问器即时生效、无需重启。

**M10 切片 b · 通用 SLA 引擎 + 定时调度**（2026-09-14，无新表/迁移 0011 仅加列）

| 方法/路径 | 说明 | 依据 |
|---|---|---|
| POST `/sla/run` | 手工触发全部 sweep 作业（**platform_admin**，body 带 actor，越权 403；Q75）：①待办到期升级（所有 open ops_todo 过 due_at→escalated，按类型写审计）②Q18 证据超时自动驳回 ③Q24 冷却到期回 available ④Q51 未来生效词条到点激活并补扫；每作业独立会话/提交，单作业失败回滚不阻断其余，响应回带每作业 `{changed}` 或 `{error}` | Q49/Q18/Q24/Q51/Q75 |
| GET `/sla/todos?status=open\|all` | 待办 SLA 看板（due_at 升序），派生 `sla_state`：green/yellow/red/resolved（黄色仅法审 created_at+24h，其余类型黄色口径【原文未给出，待补】） | Q49/Q70 |

> 定时调度：FastAPI lifespan 内 asyncio 循环，默认 300s 一轮（`LOOM_SWEEP_INTERVAL_SECONDS`、`LOOM_SCHEDULER_ENABLED=false` 可关）；V1 单进程，多副本单实例触发（分布式锁）【挂账】。法审黄色小时数读配置中心 `sla.yellow_hours`（种子 24，缓存未引导时回退默认）——首个配置中心消费方。Q71 critical→target 自动补货（5 分钟防抖）仍未实现：V1 无 skill7 AI 漏斗可调用，挂 skill7 切片，不构造虚拟候选。**RBAC 收口已于切片 d 完成（Q75）**：`/sla/run` 与 `/admin/ops-todos/sweep` 手工触发归 platform_admin；其余端点级角色映射见切片 d 小节。

**M10 切片 d · RBAC 红线收口**（2026-09-14，无新表/无新端点；Q75 销账）

> 统一入口 `app/core/rbac`：角色常量（operations/product_reviewer/dictionary_admin/internal_compliance/whitelist_owner/platform_admin）+ `require_any_role(actor, *roles)` + 单一 `PermissionDenied`（路由统一映射 403）。闸放服务层；定时调度等系统内部调用不经 HTTP、不经角色闸。
> 新增/补闸矩阵：①`POST /api/admin/sla/run`、`POST /api/admin/ops-todos/sweep` → **platform_admin**（Q75 新裁决；sla/run 请求体新增 `actor`）；②`POST /categories`、`PUT /categories/{id}/template` → **dictionary_admin**（Q75；CategoryCreate 请求体新增 `actor`）；③`POST /pws/{id}/ccr/run` → **internal_compliance**（Q75）；④补闸既有裁决：信号权重 PUT、行业阈值 CRUD = operations（Q2/Q7），来源路由 PUT/DELETE = operations（Q8）。
> **有意开放、不加闸**（Q75 第 4 条，实现补登）：`POST /pws/{id}/pws/evaluate`（Q28"系统提请"——机械求值 + 幂等出单，非人工决策）、`POST /atom-candidates/{id}/revive`（仅 evidence_timeout 驳回可复活，前置状态即闸）。
> 既有各模块服务内 `RoleNotAllowed`（config_center/whitelist_center/compliance_center 等）保持不动，本次只收口红线，不做全库异常类合并；统一 403 口径不变。

**M10 切片 e · skill7 AI 候选通道（WF-04 试点；WF-02 字段池 Q78、WF-01 冷启动识别 Q79、WF-03 原子批次 Q80、WF-01 C7 Layer4 Q81 为复用切片）**（2026-09-14，迁移 0012 + 0013，Q76/Q78/Q79/Q80/Q81；路由前缀 `/api`）

| 方法/路径 | 说明 | 依据 |
|---|---|---|
| POST `/skill-runs` | AI 产出外部投递（**operations**，越权 403；入站机器对机器 API Key 通道仍【待补】，Q82 真 LLM 走向见切片 f 的进程内系统 Actor 投递）：body=skill_id/wf_id(可省，按注册表推导)/**锚点二选一 product_space_id 或 intake_id（Q79-4，必给且仅给一个）**/input/output/candidates[{target_type,payload}]/confidence/tokens/actor；未注册 Skill 或 Skill 不属该 WF → 422，锚点实体不存在 404（PS/intake）；**投递校验按 WF 步骤声明泛化（Q78/Q79）**：非候选产出步骤带候选 422、target_type 与声明 `candidate_target` 不符 422、payload 不符该 target 既有契约 422、步骤声明 `single_candidate: true` 时必须整结果单候选否则 422、**锚点与 WF 归属不符（c1_recognition/c7_layer4 必须 intake 锚点；pwc_combo/field_plan/atom_batch 必须 PS 锚点）422**；写不可变 `skill_runs(status=succeeded,source=delivery)` + 每候选 `skill_candidates(pending_review)`，两表按锚点回填 product_space_id/intake_id 之一，writeAudit `skill7.run_delivered`（detail.anchor=intake/product_space） | Q76-1/2/5，Q78，Q79-4，06 §4 |
| GET `/skill-runs`（`?product_space_id=&intake_id=&status=`）/ GET `/skill-runs/{run_id}` | 运行日志查询（无更新/删除端点；历史不可 mutate，PT-COMPLIANCE）；不存在 404；视图含 intake_id | 06 §4.3 |
| GET `/skill-candidates`（`?product_space_id=&intake_id=&state=`） | 候选列表；视图含 intake_id | 05 §2.3 |
| POST `/skill-candidates/{id}/decision` | 人工裁决（角色取 WF 定义 skill7 Gate 插槽；WF-02/WF-03/WF-04=**product_reviewer**（Q80-2），**WF-01=operations（Q79-3/Q81-3，WF-01 两道 Gate 同角色）**）：confirmed→适配器按 `target_type` 落库（**`pwc_combo` 经既有 `pwc/funnel`(source=ai)；`field_plan`（Q78）经既有 `fieldpool.submit_plan` 落 pending_gate，PT-FP-PLAN/Q8/Q9/Q10/Q12 全不绕过，再过 WF-02 端点 Gate；`c1_recognition`（Q79）经既有 `modeling.submit_recognition`，Q1 三分支机械逻辑一字不改（direct_approve→auto_confirm submitted / ops_assist→pending_confirm+72h OpsTodo / cold_start→需 category_pending_id 转 category_creating）；`atom_batch`（Q80）经既有 `atom.submit_batch`（通道强制 source=ai），Q14 批次上限/Q15 达标停拓/同批去重/维度归属/line 11189 事实唯一/Q17 双轨/line 840 冲突/PT-ATOM-EXP 空证据降级全不绕过，入库后逐条 approveAtomGuard·Q70·Q18·Q19 Gate 原样保留**；`c7_layer4`（Q81）经既有 `modeling.resolve_c7`，Q6 覆盖率 0.6 地板/L1 缓存/L2 approved 兄弟继承/Q68 fid:'-' 闸全不绕过，实际落 L1/2/3 时 l4_proposals 自然不生效，落 L4 才写 g2_field_candidates(pending_gate) 并继续走段3 Q13 dictionary_admin 转正**）置 applied+applied_refs（c1_recognition 回填 C1Record.record_id，atom_batch 回填 AtomBatch.batch_id，c7_layer4 回填 C7Run.run_id）；modified 必带替换 payload（按该 target 契约校验，422）、human_modified=true 后同样 apply；rejected→archived；非 pending_review 409；不存在 404；适配器业务错误沿用各业务端口径 404/409/422（field_plan：ProductSpaceNotFound 404 / GateNotAllowed 409 / InvalidPlan 422；c1_recognition：IntakeNotFound 404 / RecognitionNotAllowed 409 / ConfigError·InvalidDecision 422；atom_batch：ProductSpaceNotFound·PoolNotFound 404 / PoolNotApproved·TargetReached·FactAtomConflict 409 / InvalidBatch 422；c7_layer4：IntakeNotFound·CategoryNotFound 404 / IllegalFid·InvalidDecision 422）；适配器失败回滚事务，候选留 pending_review 可重裁；writeAudit `skill7.candidate_applied/rejected` | Q76-3，Q78，Q79-1/2/3，Q80-1/2/3，Q81-1/2/3，05 §2.3 |

> 补货（Q71/Q76-4）：`POST .../pwc/consume` 致待用数跌破 critical 时，按 `pwc.restock_cooldown_minutes`（5min）防抖创建 `skill_runs(status=requested,source=restock_auto,created_by=system)`，**只记 run 不产候选**；响应新增 `restock_run_id`（防抖期内为 null）。外部投递迟到产出后正常走 pending_review。
> 注册表：`runtime/workflows/WF-04.yaml`（顺序 Skill + 2 个 Gate 插槽）与 `runtime/skills/{PWC-BUILDER,COMBO-VALIDATE,PWC-SCORING}/skill.yaml`；**WF-02 替换切片（Q78）**`runtime/workflows/WF-02.yaml`（FIELDPOOL-PLAN→DIM-SOURCE→DIM-MERGE，DIM-MERGE 步骤 `produces_candidates: true, candidate_target: field_plan, single_candidate: true`，skill7+fieldpool 双 Gate 插槽）与 `runtime/skills/{FIELDPOOL-PLAN,DIM-SOURCE,DIM-MERGE}/skill.yaml`；**WF-01 替换切片（Q79 C1 识别 + Q81 C7 Layer4）**`runtime/workflows/WF-01.yaml`（PARSE→UNDERSTAND→CAT-RECOG→TYPE-MATCH→MISSING-INFO→RISK-TAG，**两个候选产出步骤**：CAT-RECOG `candidate_target: c1_recognition, single_candidate: true`、TYPE-MATCH `candidate_target: c7_layer4, single_candidate: true`，CAT-RECOG 后与 TYPE-MATCH 后各一个 skill7 Gate 插槽，role 均为 operations；MISSING-INFO 非产出步骤）与六张 `runtime/skills/<skill>/skill.yaml`（均 06 §4.1 的 10 字段；原文称 11 字段但逐项列出 10 项，按 10 项实现不擅补；model_tier V1 为空串、cost_limit 为 null）；**WF-03 替换切片（Q80）**`runtime/workflows/WF-03.yaml`（ATOM-EXPAND→ATOM-CANON→ATOM-AFFINITY→CONFLICT-PRECHECK，**末步 CONFLICT-PRECHECK** 声明 `produces_candidates: true, candidate_target: atom_batch, single_candidate: true`，末步后单个 skill7 Gate 插槽 role=product_reviewer）与四张 `runtime/skills/{ATOM-EXPAND,ATOM-CANON,ATOM-AFFINITY,CONFLICT-PRECHECK}/skill.yaml`；加载器 `app/core/skill7/registry.py`（`producer_step_for/candidate_target_for(wf,skill)` 供投递校验，`review_role(wf)` 供裁决角色），`LOOM_RUNTIME_DIR` 可覆盖路径。**仍挂账**：真 LLM 新字段生成体——Q82 已落地模型底座 + CAT-RECOG 试点（见切片 f），其余四个生成站点（PWC-BUILDER / FIELDPOOL-PLAN·DIM-SOURCE / ATOM-EXPAND·ATOM-AFFINITY / C7 L4）各自后续切片复用同模式；入站一 Agent 一 Key 通道随 Q60 回调切片；编排器并行/DAG 二期；多副本补货防抖锁随调度锁挂账。

**M10 切片 f · 模型网关与 CAT-RECOG 真 LLM 试点（Q67/Q82）**（2026-09-14，迁移 0014；路由前缀 `/api`；表见 04 §2.24 / 10 §2.8）

*治理类（模型注册页，红线归 platform_admin；场景路由 operations\|platform_admin）*

| 方法与路径 | 契约 | 来源 |
|---|---|---|
| POST `/admin/ai-models` / GET `/admin/ai-models` | 建模：body=model_code(唯一)/provider/input_price_per_1m/output_price_per_1m(≥0)/currency_code(3 字符可空，币种【原文未给出，待补】)/daily_budget(可空)/fallback_model_id(创建时禁带，422)/actor；**platform_admin**，越权 403；重码 422；201 视图含 has_active_key。列表按 model_code 排序，带 has_active_key | Q67 / Q82 |
| PATCH `/admin/ai-models/{id}` | 改价/币种/日预算/status(active\|disabled)/fallback_model_id；自引用 fallback 422、目标不存在 422、模型不存在 404；platform_admin | Q82 |
| POST `/admin/ai-models/{id}/keys` | 录入/轮换 outbound Key：body=secret(min 8)/actor；platform_admin，模型 404；原子地把旧 active 行置 revoked 并插新密文行；201 仅回 key_id/fingerprint(末 4 位)/status，**明文/密文均不回显**；writeAudit `ai_model_key.rotate` | Q82-3 |
| GET `/admin/ai-models/{id}/keys` | Key 清单：仅 key_id/fingerprint/status/时间元数据 | Q82-3 |
| POST `/admin/ai-model-keys/{key_id}/revoke` | 吊销（body=actor；platform_admin；幂等，重复吊销不报错）；Key 404；writeAudit `ai_model_key.revoke` | Q82-3 |
| PUT `/admin/ai-scene-routes/{scene}` / GET `/admin/ai-scene-routes` | 场景键 = `skill_id`；body=model_id/actor，模型不存在 422；**operations\|platform_admin** 可改不动代码；writeAudit `ai_scene_route.update` | Q67 / Q82 |
| POST `/admin/skill-prompts/{skill_id}/versions` | 发布 Prompt 新版本：template(非空)/change_note/variables/actor，platform_admin；首版 v0.1，之后 v0.N+1；同步移动 skill_prompts 指针，版本行 append-only；writeAudit `skill_prompt.publish` | Q82-4 |
| GET `/admin/skill-prompts` / GET `/admin/skill-prompts/{skill_id}/versions` / GET `.../versions/{version}` | 指针列表 / 版本历史（不含 template 全文）/ 单版本详情（含 template+variables）；单版本不存在 404 | Q82-4 |

*试点触发（段2 CAT-RECOG）*

| 方法与路径 | 契约 | 来源 |
|---|---|---|
| POST `/intakes/{intake_id}/c1-recognition/llm-invoke` | body=actor；**operations**（越权 403）；intake 不存在 404；仅 `ai_recognizing` 状态可调，否则 409；无启用 C1 信号权重 422。进程内同步：场景路由→模型（disabled 且无 active fallback → 409，不静默换商）→日预算硬停（用尽 409）→渲染当前 Prompt 版本（缺 Prompt/变量 422）→驱动（provider=synthetic 走确定性替身；其余 OpenAI 兼容，base_url 只从 `LOOM_LLM_BASE_URL_<PROVIDER>` 注入，缺 active Key 422，上游/协议错误 502）→输出 JSON 校验（非 JSON/信号越权重名/分值越界/候选非启用类目 → 502 ExtractionOutputInvalid）。通过后以系统机器 Actor（`system:llm-gateway`, roles=[]，Q66 不授任何角色）走 skill7 同一投递：`skill_runs(source=llm_auto, model_id, tokens, input_cost, output_cost, currency_code)` + 整结果单候选 `skill_candidates(pending_review, c1_recognition)`，WF 声明校验/intake 锚点/适配器全复用。201 返回 run_id/source/model_id/tokens/candidates[{id,state,target_type}]。后续运营经 `/skill-candidates/{id}/decision` 裁决，confirmed/modified 才由 c1_recognition 适配器跑 Q1 三分支（line 同既有投递） | Q82-1/2 |

> 种子（迁移 0014，固定 uuid5）：`synthetic-deterministic`（provider=synthetic，价 0，无预算）模型 + CAT-RECOG→synthetic 路由 + CAT-RECOG Prompt v0.1（变量 product_profile/signal_keys/category_options）。仓库不含真实供应商凭证；真实 Key 只在部署环境经 `LOOM_MASTER_KEY` + 注册页录入，主密钥不入库不入仓，未设置时本地/测试退化为进程内临时密钥（告警，重启旧密文不可解）。

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

> **实现补登（2026-09-14，M10 切片 e，Q76；WF-02 切片 Q78；WF-01 切片 Q79/Q81；WF-03 切片 Q80）**：通道落 `app/core/skill7/`；`ai_suggested` 为生产者侧态，外部投递落库即 `pending_review`，不持久化 ai_suggested 行【实现补】。confirmed/modified → 适配器应用后置 `applied`（不经过独立 confirmed/modified 持久态，二者体现在 human_modified 与审计动作上）；rejected → `archived`。已接入五个 target_type 适配器：`pwc_combo`（WF-04）复用既有 `pwc/funnel`，`field_plan`（WF-02，Q78）复用既有 `fieldpool.submit_plan`，`c1_recognition`（WF-01，Q79）复用既有 `modeling.submit_recognition`，`atom_batch`（WF-03，Q80）复用既有 `atom.submit_batch`（强制 source=ai），`c7_layer4`（WF-01，Q81）复用既有 `modeling.resolve_c7`——AI 候选落库后仍走各自待 Gate/三分支/四层兜底/逐条 approveAtomGuard→下游流程，skill7 不替代任何既有机械逻辑或 Gate（c7_layer4 落 L1/2/3 时提案不生效；L4 候选仍过段3 Q13 dictionary_admin）。投递侧契约校验按 WF 步骤 `producer_step_for(...).candidate_target/single_candidate` 分派（Q78 起不再硬编码 pwc_combo；Q79 单候选约束声明化；Q80 atom_batch 复用同一整批单候选声明；Q81 同一 WF 第二个产出步骤 TYPE-MATCH 复用同一机制）。Q79-4 起 skill_runs/skill_candidates 双锚点（PS 或 intake，后者 product_space_id 改 nullable，迁移 0013；atom_batch 走 PS 锚点，c1_recognition/c7_layer4 走 intake 锚点，无新迁移）。Q81 同时将 resolve_c7 Layer4 盲插改为同名 c7_layer4 全局候选复用（与 wf02_dim_source 同口径，避免 uq(source_layer,field_name) 冲突）【实现补】。Q82 起新增 `source=llm_auto` 运行来源（进程内真 LLM 系统 Actor 投递，角色门只在触发端点与既有投递侧，系统 Actor 不授角色 Q66），SkillRun 增 model_id/input_cost/output_cost/currency_code；候选状态机本身不变。

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
