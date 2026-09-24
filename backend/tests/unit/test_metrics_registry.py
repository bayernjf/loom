"""Q181：进程内指标注册表单元测试（Counter/Gauge/Histogram/render，零外部依赖）。"""
from __future__ import annotations

import pytest

from app.core.metrics.registry import Counter, Gauge, Histogram, Registry


def render(metric) -> str:
    registry = Registry()
    registry.register(metric)
    return registry.render()


def test_counter_increments_and_partitions_by_labels() -> None:
    counter = Counter("c_total", "doc", ("method",))
    counter.inc(method="GET")
    counter.inc(2, method="GET")
    counter.inc(method="POST")
    text = render(counter)
    assert '# HELP c_total doc' in text
    assert "# TYPE c_total counter" in text
    assert 'c_total{method="GET"} 3' in text
    assert 'c_total{method="POST"} 1' in text


def test_counter_cannot_decrease() -> None:
    with pytest.raises(ValueError):
        Counter("c_total", "doc").inc(-1)


def test_unexpected_label_rejected() -> None:
    with pytest.raises(ValueError):
        Counter("c_total", "doc", ("method",)).inc(unknown="x")


def test_gauge_set_inc_dec() -> None:
    gauge = Gauge("g", "doc", ("kind",))
    gauge.set(5, kind="a")
    gauge.inc(kind="a")
    gauge.dec(2, kind="a")
    assert 'g{kind="a"} 4' in render(gauge)


def test_histogram_buckets_sum_count() -> None:
    hist = Histogram("h", "doc", ("route",), buckets=(0.1, 0.5, 1.0))
    hist.observe(0.3, route="r")
    text = render(hist)
    assert "# TYPE h histogram" in text
    assert 'h_bucket{route="r",le="0.1"} 0' in text
    assert 'h_bucket{route="r",le="0.5"} 1' in text
    assert 'h_bucket{route="r",le="1"} 1' in text
    assert 'h_bucket{route="r",le="+Inf"} 1' in text
    assert 'h_sum{route="r"} 0.3' in text
    assert 'h_count{route="r"} 1' in text


def test_label_value_escaped() -> None:
    counter = Counter("e", "doc", ("path",))
    counter.inc(path='a"b\nc\\d')
    text = render(counter)
    assert 'path="a\\"b\\nc\\\\d"' in text


def test_duplicate_registration_rejected() -> None:
    registry = Registry()
    registry.register(Counter("x", "doc"))
    with pytest.raises(ValueError):
        registry.register(Counter("x", "doc"))


def test_empty_registry_renders_empty_string() -> None:
    assert Registry().render() == ""
