"""测试侧读取进程全局指标的公共助手（Q188）。

REGISTRY 跨用例累积，故调用方一律取**前后增量**而不是断言绝对值。
"""

from app.core.metrics.registry import Counter, Gauge, Histogram


def counter_value(metric: Counter, **labels) -> float:
    return float(metric._samples.get(metric._key(labels), 0.0))


def gauge_value(metric: Gauge, **labels) -> float | None:
    key = metric._key(labels)
    return float(metric._samples[key]) if key in metric._samples else None


def histogram_count(metric: Histogram, **labels) -> int:
    series = metric._samples.get(metric._key(labels))
    return 0 if series is None else int(series["count"])
