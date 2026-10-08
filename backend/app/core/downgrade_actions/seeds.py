"""Q38 降级动作字典种子（迁移 0051 与测试的单一事实源）。

六码逐字取自 docs/02:141 用户原话（2026-10-06 Q295 已把 docs/10 的口径漂移订正为此六项）。
`name`/`why` 中文文案原文未给出 ⇒ 不在此编造，留 NULL 由运营经管理面回填。
"""

DOWNGRADE_ACTION_CODES: tuple[str, ...] = (
    "REMOVE_BRAND",
    "REMOVE_CLAIM",
    "REMOVE_LINK",
    "SOFT_CTA",
    "SHORTEN",
    "SUBST_WORD",
)
