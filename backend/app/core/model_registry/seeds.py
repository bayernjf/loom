"""Q82/Q83 底座种子：合成确定性模型 + CAT-RECOG/PWC-BUILDER 场景路由与 Prompt v0.1。

供 Alembic 迁移与测试共用（同 0008 平台种子模式）。仓库不持任何真实供应商
凭证：synthetic 驱动仅用于本地/测试的确定性替身，真模型由部署环境经注册页登记。
"""

import uuid

SYNTHETIC_MODEL_CODE = "synthetic-deterministic"
SYNTHETIC_PROVIDER = "synthetic"
SCENE_CAT_RECOG = "CAT-RECOG"
SCENE_PWC_BUILDER = "PWC-BUILDER"

# 固定主键，便于迁移/测试/路由解析引用同一行。
SYNTHETIC_MODEL_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "loom:ai-model:synthetic-deterministic"))
CAT_RECOG_PROMPT_VERSION = "v0.1"
CAT_RECOG_PROMPT_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "loom:skill-prompt:CAT-RECOG:v0.1"))
PWC_BUILDER_PROMPT_VERSION = "v0.1"
PWC_BUILDER_PROMPT_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "loom:skill-prompt:PWC-BUILDER:v0.1"))

CAT_RECOG_PROMPT_TEMPLATE = """你是 Loom 私域内容生产平台的类目识别 Skill（CAT-RECOG）。只输出一个 JSON 对象，不要输出任何解释或 Markdown 代码围栏。

【待识别产品资料】
$product_profile

【启用信号键】只允许输出这些键的 0..1 分：
$signal_keys

【候选类目（category_id 必须取自下表，conf 为 0..1 置信度，按置信度降序）】
$category_options

输出格式（industry 可省略；没有可信候选时 candidates 给空数组）：
{"signals": {"<signal_key>": 0.0}, "candidates": [{"category_id": "...", "conf": 0.0}], "industry": "general"}
"""

CAT_RECOG_PROMPT_VARIABLES = [
    "product_profile",
    "signal_keys",
    "category_options",
]

PWC_BUILDER_PROMPT_TEMPLATE = """你是 Loom 私域内容生产平台段5 的 PWC-BUILDER Skill，为一个产品空间生成跨字段条件组合候选。只输出一个 JSON 对象，不要输出任何解释或 Markdown 代码围栏。

【已 Gate 通过的可用原子】（atom_id 必须取自下表；每行格式 atom_id | 维度 | 内容）
$approved_atoms

【启用中的内容目的 goals】（goals 取值只能来自下表，可给空数组）
$active_goals

【库容与待用池现状】容量 $capacity（null=无上限），当前待用 ready 数 $ready_count
【目标平台】$target_platforms

硬性规则：
1. 每个 combo 的 atom_ids 至少 2 个且必须来自至少 2 个不同维度；禁止跨产品空间原子。
2. 整批最多 $batch_limit 条；combo 之间原子集合不得完全重复。
3. 只输出 {"combos": [{"atom_ids": ["..."], "goals": ["..."]}]}；不要输出任何评分（logic_score/fit_score/weight 由下游 COMBO-VALIDATE/PWC-SCORING 处理）。
4. 没有可信组合时 combos 给空数组。
"""

PWC_BUILDER_PROMPT_VARIABLES = [
    "approved_atoms",
    "active_goals",
    "capacity",
    "ready_count",
    "target_platforms",
    "batch_limit",
]
