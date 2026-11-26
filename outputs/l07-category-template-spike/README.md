# L-07 单路 DIM-SOURCE connector：category_template

> 后续状态（2026-11-26 同日）：本目录记录的是 `category_template` 当时的 v0.3 / 0068 证据；本机库随后已由迁移 0069 升到 DIM-MERGE v0.4，第二路 `compliance_risk` 证据见 `outputs/l07-compliance-risk-spike/`。本目录的 v0.3 数字不回写。

日期：2026-11-26  
范围：只打通七路中的 `category_template`，不接需外部凭据的其余六路，不做 commit / push / PR。

## 数据链

`ProductSpace.category_node_id`
→ `G1CategoryTemplate(status=approved).field_list`
→ `G2Field(status=active)`
→ DIM-MERGE 变量 `category_template_entries`（模板渲染）与 `_category_template`（机读）
→ DIM-MERGE prompt v0.3
→ 候选维度 `source_route=category_template`、`source_ref=category_template:<fid>`。

## 代码与模板

- 新增 `backend/app/product/fieldpool/source_connectors.py`：只读加载器，不写库、不触网、不产候选。
- `backend/app/core/model_registry/field_plan.py`：仅在 `category_template` 路由启用时注入；缺类目绑定、模板未 `approved`、G2 字段非 `active` 均 fail-closed 为空。
- `backend/app/core/model_registry/seeds.py`：新增 v0.3 模板常量；v0.1 历史种子保留不动。
- 迁移 `backend/alembic/versions/0068_dim_merge_category_template_prompt.py`：发布 v0.3 并把 `skill_prompts.current_version` 指到 v0.3。

## 本机验证

- Alembic 当前：`0068_dim_merge_category_template_prompt (head)`，见 `alembic-current.log`。
- 本机库 DIM-MERGE：`current_version=v0.3`，1477 字符、9 变量；v0.1 1083 字符、v0.2 1297 字符均保留，见 `prompt-v03-render.log`。v0.3 模板渲染实测 1448 字符，`$category_template_entries` 无残留、`source_ref=category_template:f_cat` 已进入 prompt。
- `loom-backend:latest` 已重建并重启 `infra-backend-1`，容器 healthy；容器内 `healthz` OK、`source_connectors.CATEGORY_TEMPLATE_ROUTE` 可导入，见 `container-smoke.log`。
- ruff 通过；相关单测/接口 63 passed；后端全量 1668 passed、11 skipped（88.05s），见 `gate.log` / `full-suite.log`。其中 `test_fieldpool_llm_plan_api.py` 13 passed：
  - 已审核模板注入 `f_cat`、跳过 `f_ghost`，候选 `source_route=category_template` 落 pending_review；
  - `draft` 模板不注入，变量为空。
- 迁移契约测试 `test_dim_merge_category_template_prompt_migration.py` 覆盖 revision 链、v0.3 占位符/变量、v0.1 不被污染、uuid5 确定性。

## 边界

- 只完成 `DIM-SOURCE` 七路中的第 4 路；L-07 整体仍 open。
- 本机库当前 `g1_category_templates` 0 行、`product_spaces.category_node_id` 非空 0 行（见 `db-inventory.log`）；本轮用 in-memory 集成测试证明链路，不向本机库写合成业务数据。真实本地库要跑通，需先有 `approved` 模板且产品空间绑定该类目。
- 未接外部凭据来源：`user_input` 之外的 `common_inspiration`/`product_inspiration` 已有灵感库本体；`g2_frequent`/`compliance_risk`/`case_evidence` 仍待真实数据或外部连接。
- 未 commit、未 push；工作区改动保留在 `dev`。
