"""Q181：进程内指标注册表（零依赖，自写 Prometheus 文本 exposition）。

仅用标准库；提供 Counter / Gauge / Histogram 三类，标签以有序键值元组归一，
Registry.render() 输出 Prometheus 0.0.4 文本格式供 /metrics 抓取。
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

# Prometheus 官方 client 默认直方图桶（秒）。
DEFAULT_BUCKETS: tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)


def _float(value: object) -> str:
    number = float(value)  # type: ignore[arg-type]
    if number == int(number) and abs(number) < 1e15:
        return str(int(number))
    return repr(number)


def _escape_label(value: object) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace('"', '\\"')
    )


def _render_labels(key: Iterable[tuple[str, str]]) -> str:
    parts = [f'{name}="{_escape_label(value)}"' for name, value in key]
    return "{" + ",".join(parts) + "}" if parts else ""


def _merge_bucket_label(labels: str, le: str) -> str:
    extra = f'le="{le}"'
    if labels == "":
        return "{" + extra + "}"
    return labels[:-1] + "," + extra + "}"


class Metric:
    metric_type = "untyped"

    def __init__(
        self,
        name: str,
        documentation: str,
        labelnames: Sequence[str] = (),
    ) -> None:
        if not name:
            raise ValueError("metric name required")
        self.name = name
        self.documentation = documentation
        self.labelnames = tuple(labelnames)
        self._samples: dict[tuple[tuple[str, str], ...], object] = {}

    def _key(
        self, labels: dict[str, object]
    ) -> tuple[tuple[str, str], ...]:
        unexpected = set(labels) - set(self.labelnames)
        if unexpected:
            raise ValueError(
                f"unexpected labels for {self.name}: {sorted(unexpected)}"
            )
        return tuple((n, str(labels.get(n, ""))) for n in self.labelnames)

    def render(self) -> list[str]:
        raise NotImplementedError


class Counter(Metric):
    metric_type = "counter"

    def inc(self, amount: float = 1.0, /, **labels: object) -> None:
        if amount < 0:
            raise ValueError("counter cannot decrease")
        key = self._key(labels)
        self._samples[key] = self._samples.get(key, 0.0) + float(amount)

    def render(self) -> list[str]:
        return [
            f"{self.name}{_render_labels(key)} {_float(value)}"
            for key, value in self._samples.items()
        ]


class Gauge(Metric):
    metric_type = "gauge"

    def set(self, value: float, /, **labels: object) -> None:
        self._samples[self._key(labels)] = float(value)

    def inc(self, amount: float = 1.0, /, **labels: object) -> None:
        key = self._key(labels)
        self._samples[key] = self._samples.get(key, 0.0) + float(amount)

    def dec(self, amount: float = 1.0, /, **labels: object) -> None:
        self.inc(-amount, **labels)

    def render(self) -> list[str]:
        return [
            f"{self.name}{_render_labels(key)} {_float(value)}"
            for key, value in self._samples.items()
        ]


class Histogram(Metric):
    metric_type = "histogram"

    def __init__(
        self,
        name: str,
        documentation: str,
        labelnames: Sequence[str] = (),
        buckets: Sequence[float] = DEFAULT_BUCKETS,
    ) -> None:
        super().__init__(name, documentation, labelnames)
        bounds = list(buckets)
        if not bounds or not math.isinf(bounds[-1]):
            bounds = [*bounds, math.inf]
        self.buckets = bounds

    def observe(self, value: float, /, **labels: object) -> None:
        key = self._key(labels)
        series = self._samples.get(key)
        if series is None:
            series = {"count": 0, "sum": 0.0, "buckets": [0] * len(self.buckets)}
            self._samples[key] = series
        series["count"] += 1  # type: ignore[index]
        series["sum"] += float(value)  # type: ignore[index]
        for i, bound in enumerate(self.buckets):
            if value <= bound:
                series["buckets"][i] += 1  # type: ignore[index]

    def render(self) -> list[str]:
        lines: list[str] = []
        for key, series in self._samples.items():
            labels = _render_labels(key)
            for i, bound in enumerate(self.buckets):
                le = "+Inf" if math.isinf(bound) else _float(bound)
                lines.append(
                    f"{self.name}_bucket{_merge_bucket_label(labels, le)} "
                    f"{series['buckets'][i]}"  # type: ignore[index]
                )
            lines.append(f"{self.name}_sum{labels} {_float(series['sum'])}")  # type: ignore[index]
            lines.append(f"{self.name}_count{labels} {series['count']}")  # type: ignore[index]
        return lines


class Registry:
    def __init__(self) -> None:
        self._metrics: dict[str, Metric] = {}

    def register(self, metric: Metric) -> Metric:
        if metric.name in self._metrics:
            raise ValueError(f"metric already registered: {metric.name}")
        self._metrics[metric.name] = metric
        return metric

    def render(self) -> str:
        lines: list[str] = []
        for metric in self._metrics.values():
            lines.append(f"# HELP {metric.name} {metric.documentation}")
            lines.append(f"# TYPE {metric.name} {metric.metric_type}")
            lines.extend(metric.render())
        return "\n".join(lines) + ("\n" if lines else "")
