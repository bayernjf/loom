# 21 运营 SOP — 全链操作手册（private beta · 平台代运营）

> **定位**：受控 private beta 期间由**平台运营团队代客户操作**的逐段操作手册。每步注明"谁（角色）→ 点哪个页面/调哪个端点 → 裁决什么"。
> **依据**：角色名取自后端 `app/core/rbac/__init__.py` 常量；步骤与顺序经 `backend/tests/e2e/test_fullchain_golden_path.py` 全链实测（2026-09-22）；主数据字段以 [19](./19_private_beta主数据录入模板.md) 为准。本文不新增业务事实。
> **铁律**：AI 只产候选；每个 Gate 必须人工裁决；`final_id` 只能由 E1.1 publishFCW（`POST /api/fcw/assemble`）写入；LLM 触发全部为运营显式操作，链上不会自动串发（Q83/Q84）。

---

## 0. 角色与工作台

| 角色（actor.roles） | 职责 | 主要入口 |
|---|---|---|
| `customer` | 段1 提交资料、段12 审阅成品/改稿、段13 回填效果 | 客户台：products / content / compliance / workbench / analytics / settings（social-accounts、templates 为 V2 占位） |
| `operations` | 段1 推进、段2 触发识别、段3–5 编排与 Gate 送裁、段11 组装、段12 触发生成与发布回填 | 管理台：/admin/intakes、review-workload、review-queue、content、effects、exports 等 10 页 |
| `product_reviewer` | 字段池 / 原子 / PWC 三道 Gate 的人工裁决 | /admin/review-workload、/admin/review-queue |
| `whitelist_owner` | PWS 冻结 | API（V1 无独立页面） |
| `internal_compliance` | 段10 合规清洗 CCR | /admin/content（及 API） |
| `platform_admin` | 租户、Agent Key、AI 模型与场景路由、字典管理 | /admin/tenants、/admin/agent-keys、/admin/token-cost |
| `dictionary_admin` | 内容语言清单等字典维护 | API（语言清单管理） |

> Actor 为请求体内 `{"id","roles"}` 自报（V1 无真实认证层，身份层压 V2 第一项，Q144）；private beta 由平台内控保证。

---

## 1. 标准操作流程（一个产品从录入到发证）

### 段 1 — 产品录入（客户 + operations）

1. **客户**在 products 页提交资料（`POST /api/intakes`），profile 须含全部 12 个 common 字段：f_name、f_brand、f_intro、f_selling_points、f_seo、f_main_image、f_packaging_image、f_target_market、f_language、f_channel、f_audience、f_content_usage。
2. **客户**执行 `submit`（`POST /api/intakes/{id}/transitions`）。
3. 目标语言由客户在产品页维护（Q123，`PATCH /api/intakes/{id}/target-languages`）；未声明则段12 不做产品侧语言收窄。
4. **operations** 依次推进事件：`wf01_confirm → ops_confirm → send_review → review_approve → start_modeling → model_stored`。
5. 到 `stored` 后 `GET /api/intakes/{id}/product-space` 取得 `product_space_id`，进入建模段。

> 段 1 为 15 态状态机；事件只能按合法迁移触发，跳态会被拒。

### 段 2 — 冷启动建模（operations 触发，AI 产候选）

- `POST /api/intakes/{id}/c1-recognition/llm-invoke`：跑 CAT-RECOG，返回候选与 token 计数；候选进入待审，由段1 的 wf01 Gate 人工裁决。
- C7 四层解析对应 `…/c7/llm-resolve`。
- 没有可用场景路由时返回配置错误（见 §3）；private beta 默认全部走 synthetic 或已接线的 agnes 模型。

### 段 3 — 字段池规划 + Gate

1. **operations**：`POST /api/product-spaces/{ps}/field-pools`，提交维度（role、source_route、confidence、source_ref）。
2. **product_reviewer**：`POST /api/field-pools/{id}/gate` `{decision:"approve"}`（驳回则重做）。
3. `GET …/field-pools/current` 取批准后的 `dimension_id` 列表。

### 段 4 — 字段下原子 + 逐条裁决

1. **operations**：`POST /api/product-spaces/{ps}/atom-batches`，每项 `{content, dimension_id, ai_risk, evidence}`。
2. **product_reviewer** 对每条候选 `POST /api/atom-candidates/{id}/approve`（另有 reject 等裁决）。
3. `GET /api/product-spaces/{ps}/atoms` 取 `atom_id` 列表。

### 段 5 — PWC 条件包 + Gate

1. **operations**：`POST /api/product-spaces/{ps}/pwc/funnel`，组合 `{atom_ids, logic_score, fit_score, goals}`。
2. **product_reviewer**：`POST /api/pwcs/{id}/gate` 批准。

### 段 7/8/9 — 发布位、PCP、三包（主数据，须先按 docs/19 回填）

1. 发布位：**operations** `POST /api/admin/publish-slots`（platform、code、slot_type、四维人工分 traffic/safe/conv/load）。
2. PCP：`POST /api/product-spaces/{ps}/pcp`（platform + template_code）。
3. 三包：`POST /api/product-spaces/{ps}/packages` 逐条建 csp / cstp / cep，`{kind, platform, goal, payload, conf}`。

### 段 6 — PWS 冻结

- **whitelist_owner**：`POST /api/product-spaces/{ps}/pws/freeze`。冻结即 5 门 readiness 校验，任一不过返回未就绪原因；冻结后如需变更走重冻/版本/revoke 流程。

### 段 10 — 合规清洗

- **internal_compliance**：`POST /api/pws/{pws_id}/ccr/run`；报告 `status=clean` 方可组装。命中 block_required 时按报告处理（清洗或法审，法审 SLA 48h）。

### 段 11 — FCW 组装发证（V1 主链终点）

- **operations**：`POST /api/fcw/assemble` `{product_space_id, platform, slot_id, goal, actor}`。
- 七 Guard 全量不短路；通过则签发 `final_id`，`publish_status=published`、`guards_passed=true`；不通过返回 **409** 与 `detail.guards` 逐门结果。
- 中台导出：CSV `GET /api/fcw/{final_id}.fcw.csv`、JSON envelope `….fcw.json`（含 limit/offset，行数上限 env `LOOM_EXPORT_MAX_ROWS` 默认 10 万）；台内原料 `GET /api/fcw/{final_id}/material.json`。
- 异步导出经 `/api/exports/jobs`（worker 门控默认关，关时同步落 completed）。

---

## 2. 段 12 / 段 13（beta 已接线，按需使用）

### 段 12 — 内容生成与客户审阅

1. **operations**：`POST /api/content/generate` `{final_id, kind:"article", language, actor}`。
   - language 必须在可生成清单内：`GET /api/content/eligible-languages?final_id=`（发布位市场 ∩ 产品目标语言，Q119）。
   - 默认 `zh-CN`。
2. **客户**在 content 页裁决：`approve`（→ `ready_for_publish`）/ `reject`（reason 必填）/ `revise`（客户可在改稿岛编辑后 manual_resubmit）/ `regenerate`（上限 3 次）。
3. AI 质量分（ARTICLE-QC）与语义检测（ARTICLE-SEMANTIC-CHECK）为纯 advisory，不阻断。
4. **operations** 托管发布后回填：`PUT /api/admin/content/{id}/publish-info`（url 必填）；不新增 published 态，三列非空即已发布。队列：`GET /api/admin/content/ready-to-publish`。
5. 难产骨架：**operations** `POST /api/content/{id}/discard`（reason 必填，终态，释放唯一占位回池）；队列在 needs-attention。

### 段 13 — 效果回流

1. **platform_admin** 在 /admin/agent-keys 签发 Agent Key（secret 仅显示一次）。
2. 外部系统带 `Authorization: Bearer <secret>` 调 `POST /api/effect-callback`，records 按 `content_id` 精确匹配非 discarded 成品；整批 all-or-nothing，回执 `{received, matched, orphan}`。
3. 孤儿（无匹配）：**operations** 在 /admin/effects 单条或批量认领（external_content_id→content_id 映射），可改绑/解绑。
4. 客户回填（无 Agent Key）：`POST /api/effects/backfill`（只命中本租户、绝不产生孤儿）；批量走 `/upload`（CSV）、`/upload-excel`（xlsx，上限 env `LOOM_BACKFILL_UPLOAD_MAX_ROWS` 默认 1 万）、异步任务 `/api/effects/backfill/jobs`（worker 门控默认关）。
5. metrics 字段缺席记 NULL，**绝不补 0**；captured_at 必须带时区；(content_id, captured_at) 幂等。

---

## 3. 常见 4xx / 5xx 含义与处置

| 码 | 典型含义 | 处置 |
|---|---|---|
| 401 | Agent Key 缺失/无效/停用（effect-callback、A2A tasks） | 核对 Bearer secret 与 Key 状态 |
| 403（PermissionDenied） | actor.roles 不含该口所需角色 | 换正确角色账号；勿在业务流程中提权 |
| 404 | 资源不存在（intake/ps/pws/fcw/content） | 核对 ID；FCW 未签发前段12 各口必 404 |
| 409 状态机冲突 | 事件在当前态非法 / 重复发证 / FCW 已签发 / 材料缺失 / 下载口对 queued·running 作业 | 查当前状态再决定下一步；assemble 的 409 看 `detail.guards` |
| 409 锁冲突 | 单 leader 锁被占（SLA/restock 手工 /run） | 单实例稍后重试；LockLost→409 表示锁已易主，本轮中止 |
| 422 | 请求体校验失败：submit 缺 common fids、语言不在 eligible、PWC/评分参数非法、导出行数超上限、时区缺失、Excel/CSV 坏行 | 按 detail 字段（如 missing_fids、eligible、逐行错误）修正后整批重提 |
| 503 | 锁后端故障 / 异步 worker 入流失败（fail-closed） | 排查 Redis/基础设施后重试 |
| ModelConfigError（500/配置错） | 场景无路由 / 模型或 Key 未配置 | platform_admin 在模型管理补模型、Key 与场景路由 |

---

## 4. 日常运维节奏

- **SLA sweep**：调度器自动巡检（受单 leader 锁/PG 行级 fence 保护）；手工触发 `POST /api/admin/sla/run`；阈值 SLA 72h、黄 24h、红 48h（Q149）。
- **难产/孤儿/待发布三队列**：每日在 /admin/content 与 /admin/effects 过 needs-attention、orphans、ready-to-publish。
- **审计**：每个写操作与每次 LLM 调用均落审计；异常排查先查审计与 `/admin/token-cost`。
- **演练**：全链验证跑 `infra/fullchain-rehearsal.sh`（synthetic 不花钱；真 LLM 演练需授权 + 当日预算内）；备份恢复见 `infra/restore-rehearsal.sh`。

> 校准类口径（效果反哺算法、Q54 评分等）原文【待补】，运营不得自行编公式，按业务/数据科学口径下达后执行。
