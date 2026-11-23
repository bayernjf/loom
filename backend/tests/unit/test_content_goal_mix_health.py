"""Q44 健康判定的边界（软提示不造假超标/欠配）。"""

import pytest

from app.product.condition.service import goal_mix_health


@pytest.mark.parametrize(
    ("count", "total", "ratio_min", "ratio_max", "expected"),
    [
        (0, 0, 0.15, 0.40, "no_data"),
        (1, 2, None, None, "unconfigured"),
        (2, 5, None, 0.40, "within"),       # 恰好 40% 不算超标
        (3, 5, None, 0.40, "above"),
        (1, 5, 0.15, None, "within"),       # 20% >= 15%
        (1, 10, 0.15, None, "below"),
        (2, 10, 0.15, None, "within"),      # 恰好 15% 不算欠配
        (4, 10, 0.15, 0.40, "within"),
        (5, 10, 0.15, 0.40, "above"),
        (1, 10, 0.15, 0.40, "below"),
    ],
)
def test_goal_mix_health_boundaries(count, total, ratio_min, ratio_max, expected):
    assert goal_mix_health(
        count=count, total=total, ratio_min=ratio_min, ratio_max=ratio_max
    ) == expected
