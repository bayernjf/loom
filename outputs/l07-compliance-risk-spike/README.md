# L-07 compliance_risk connector 证据（2026-11-26）

## 结论

`compliance_risk` 单路已打通：本机统一合规词库中当前生效、适用本产品行业/全球的词条 → `compliance_risk_entries` / `_compliance_risk` 变量 → DIM-MERGE Prompt v0.4 → 候选维度 `source_ref=compliance_risk:<entry_id>`。真实本机库 2 个 ProductSpace 各读到 6 条生效词条。

## 数据链

1. `ComplianceWordlistEntry(status=active)`；
2. 生效窗口：`effective_from <= now < effective_until`，空值视为不设限；
3. 范围：`country is NULL`，且 `industry is NULL` 或等于 `ProductSpace.industry_tag`；
4. 最多 20 条，按 `critical > high`、词面、entry_id 稳定排序；
5. `field_plan.py` 仅在 `compliance_risk` 路由启用时注入；空列表给「（无）」，不编造来源。

## 关键文件

- `backend/app/product/fieldpool/source_connectors.py`：新增 `load_compliance_risk_entries` / `format_compliance_risk_context`。
- `backend/app/core/model_registry/field_plan.py`：注入 `compliance_risk_entries`、`_compliance_risk`，Run input 增 `compliance_risk_entry_count`。
- `backend/app/core/model_registry/seeds.py`：新增 DIM-MERGE v0.4 常量；v0.1/v0.2/v0.3 保留。
- `backend/alembic/versions/0069_dim_merge_compliance_risk_prompt.py`：发布 v0.4 并切换 current_version。
- `backend/tests/integration/test_fieldpool_llm_plan_api.py`：合规词条注入 + 过期/未来/行业不匹配/国家定向过滤。
- `backend/tests/unit/test_dim_merge_compliance_risk_prompt_migration.py`：迁移契约。

## 门禁

- 定向测试：24 passed（2.63s）。
- 后端全量：1674 passed / 11 skipped（89.56s）。
- ruff：All checks passed。
- mypy：4 source files，0 errors。
- 本机 Alembic：`0069_dim_merge_compliance_risk_prompt (head)`。
- 本机库 DIM-MERGE：`current_version=v0.4`；v0.1 1083、v0.2 1297、v0.3 1477、v0.4 1657 字符；v0.4 10 变量。
- 容器：`infra-backend-1` healthy；`/healthz` `{"status":"ok"}`；新 connector 可导入。
- Prompt 渲染：2255 字符，`$compliance_risk_entries` 无残留，含 `source_ref=compliance_risk:`。

## 边界

- 只完成七路中的第二路；`user_input`/`g2_frequent`/`common_inspiration`/`product_inspiration`/`case_evidence` 仍未接。
- `country` 定向词条暂不注入：`ProductSpace` 尚无国家字段，无法可靠匹配，fail-closed。
- 未 commit / 未 push；工作区改动保留。
- `next-route-audit.log` 显示本机 `inspiration_entries=0`、`case_evidence` 表不存在，这两路没有可复现数据，不写合成数据冒充闭环。
