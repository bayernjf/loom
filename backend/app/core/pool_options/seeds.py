"""17 池池名与候选值（迁移 0052/0053 与测试的单一事实源）。

池名不在这儿重列——它已经有一个权威定义：`pa_rules.WEIGHT_KEYS_17`（Q40 统一校验器
"键必须落在 17 池内"用的就是它）。在这里重抄一份只会让两处各自漂移，故直接引用。
**选项列表本身原文未给出**（docs/02 Q43 只定"池→选项列表做配置字典"），0052 建表种子
`options` 留空数组；Q325（2026-10-09，02 C1.268）按 docs/design-q324 §10 审核表"按推荐"
拍板，回填每池候选值（见 `POOL_OPTION_CANDIDATES`，每池 3–6 个取值起点），迁移 0053
逐行 UPDATE。候选为工程起点，运营可在管理面 CRUD 增删。
"""

from app.platform.platform_adaptation.pa_rules import WEIGHT_KEYS_17

POOL_KEYS: tuple[str, ...] = WEIGHT_KEYS_17

# Q325 拍板回填（docs/design-q324 §2 表）：每池可选值清单起点（运营可增删）。
# 键必须 ⊆ WEIGHT_KEYS_17；goal 池已闭环（Q25 目的字典独立维护，见 Q323 A1），不在本表重复。
POOL_OPTION_CANDIDATES: dict[str, list[str]] = {
    "action": ["awareness", "consideration", "conversion", "retention"],
    "struct": ["hook-first", "story", "listicle", "problem-solution", "demo"],
    "intensity": ["gentle", "moderate", "strong", "aggressive"],
    "rhythm": ["fast", "medium", "slow", "varied"],
    "tone": ["formal", "friendly", "authoritative", "playful", "neutral"],
    "emotion": ["positive", "neutral", "aspirational", "trust", "urgency"],
    "style": ["corporate", "lifestyle", "educational", "entertaining", "minimal"],
    "perspective": ["first-person", "third-person", "brand-voice", "expert", "user"],
    "stage": ["awareness", "evaluation", "decision", "retention"],
    "title": ["question", "number-list", "how-to", "benefit-led", "curiosity"],
    "hook": ["question", "stat", "story", "contrast", "promise"],
    "opening": ["scene-set", "problem-state", "promise-led", "data-led"],
    "mid1": ["evidence", "example", "explanation", "demonstration"],
    "mid2": ["comparison", "objection-handling", "social-proof", "detail"],
    "mid3": ["summary", "reinforce", "transition", "offer"],
    "ending": ["cta", "soft-cta", "summary", "open-question", "brand-line"],
}
