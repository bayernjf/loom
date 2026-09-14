"""段7/8 底表种子数据（单一事实源，供 Alembic 与测试共用）。

- Q34 目的权重：原文只给出种草/转化两组；种草≈ENGAGEMENT 为【实现补】映射，
  EDUCATION/TRUST/RETENTION 原文未给出【待补】，由后台按需补配，故不进种子。
- Q39 PCP 模板：4 套平台类型模板初值【实现补：初值草稿，回流后校准；
  Q39 明确"模板初值起草放实现阶段"】，每套 17 池权重 Σ=1.0。
"""

FIT_WEIGHT_SEEDS = [
    {"goal": "ENGAGEMENT", "weights": {"traffic": 0.4, "safe": 0.2, "conv": 0.2, "load": 0.2}},
    {"goal": "CONVERSION", "weights": {"traffic": 0.2, "safe": 0.3, "conv": 0.4, "load": 0.1}},
]

PCP_TEMPLATE_SEEDS = [
    {
        "template_id": "pcpt-short_video",
        "code": "short_video",
        "name": "短视频型",
        "weights": {
            "goal": 0.08, "action": 0.08, "struct": 0.06, "intensity": 0.06,
            "rhythm": 0.10, "tone": 0.06, "emotion": 0.08, "style": 0.04,
            "perspective": 0.04, "stage": 0.04, "title": 0.10, "hook": 0.12,
            "opening": 0.08, "mid1": 0.02, "mid2": 0.02, "mid3": 0.01, "ending": 0.01,
        },
    },
    {
        "template_id": "pcpt-community",
        "code": "community",
        "name": "社区讨论型",
        "weights": {
            "goal": 0.08, "action": 0.06, "struct": 0.04, "intensity": 0.04,
            "rhythm": 0.01, "tone": 0.10, "emotion": 0.08, "style": 0.06,
            "perspective": 0.12, "stage": 0.10, "title": 0.06, "hook": 0.02,
            "opening": 0.04, "mid1": 0.06, "mid2": 0.06, "mid3": 0.06, "ending": 0.01,
        },
    },
    {
        "template_id": "pcpt-photo_text",
        "code": "photo_text",
        "name": "图文种草型",
        "weights": {
            "goal": 0.08, "action": 0.08, "struct": 0.06, "intensity": 0.06,
            "rhythm": 0.02, "tone": 0.08, "emotion": 0.10, "style": 0.10,
            "perspective": 0.04, "stage": 0.04, "title": 0.12, "hook": 0.08,
            "opening": 0.06, "mid1": 0.04, "mid2": 0.02, "mid3": 0.01, "ending": 0.01,
        },
    },
    {
        "template_id": "pcpt-ecommerce",
        "code": "ecommerce",
        "name": "电商型",
        "weights": {
            "goal": 0.12, "action": 0.14, "struct": 0.08, "intensity": 0.10,
            "rhythm": 0.03, "tone": 0.07, "emotion": 0.06, "style": 0.06,
            "perspective": 0.04, "stage": 0.04, "title": 0.08, "hook": 0.08,
            "opening": 0.07, "mid1": 0.02, "mid2": 0.01, "mid3": 0.0, "ending": 0.0,
        },
    },
]
