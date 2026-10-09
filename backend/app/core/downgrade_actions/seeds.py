"""Q38 降级动作字典种子（迁移 0051/0053 与测试的单一事实源）。

六码逐字取自 docs/02:141 用户原话（2026-10-06 Q295 已把 docs/10 的口径漂移订正为此六项）。
`name`/`why` 中文文案原文未给出 ⇒ 0051 建表种子留 NULL；Q325（2026-10-09，02 C1.268）
按 docs/design-q324 §10 审核表"按推荐"拍板，回填六码中文名与理由模板（见
`DOWNGRADE_ACTION_META`），迁移 0053 逐行 UPDATE。文案为工程候选，运营可在管理面微调。
"""

DOWNGRADE_ACTION_CODES: tuple[str, ...] = (
    "REMOVE_BRAND",
    "REMOVE_CLAIM",
    "REMOVE_LINK",
    "SOFT_CTA",
    "SHORTEN",
    "SUBST_WORD",
)

# Q325 拍板回填（docs/design-q324 §1 表）：中文名 + 理由模板（LLM 输出"动作组合+中文理由"时引用）。
DOWNGRADE_ACTION_META: dict[str, dict[str, str]] = {
    "REMOVE_BRAND": {
        "name": "移除品牌元素",
        "why": "内容含品牌名/标识，与发布位品牌露出规则冲突，建议移除后重审",
    },
    "REMOVE_CLAIM": {
        "name": "移除功效断言",
        "why": "内容存在未经证据支持的疗效/功效宣称，按合规词库命中移除",
    },
    "REMOVE_LINK": {
        "name": "移除链接",
        "why": "内容含外链，触发平台外链限制或引流规则，移除后重审",
    },
    "SOFT_CTA": {
        "name": "弱化行动引导",
        "why": "强引导（购买/下载/私信）与当前发布位宽松度不符，降级为软引导",
    },
    "SHORTEN": {
        "name": "精简篇幅",
        "why": "内容长度超过发布位字数上限，按上限截断保留核心信息",
    },
    "SUBST_WORD": {
        "name": "替换敏感词",
        "why": "命中敏感词表/黑名单词，替换为合规同义表达",
    },
}
