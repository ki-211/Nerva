"""Small dependency-free Prometheus metrics registry for the API process."""

from __future__ import annotations

from collections import defaultdict
from threading import Lock


LATENCY_BUCKETS = (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 15.0, 60.0)


class Metrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._request_buckets: dict[tuple[str, str, int, float], int] = defaultdict(int)
        self._request_sums: dict[tuple[str, str, int], tuple[int, float]] = defaultdict(lambda: (0, 0.0))
        self._duration_buckets: dict[tuple[str, tuple[tuple[str, str], ...], float], int] = defaultdict(int)
        self._duration_sums: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[int, float]] = defaultdict(lambda: (0, 0.0))

    @staticmethod
    def _labels(labels: dict[str, object]) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((key, str(value)) for key, value in labels.items()))

    def increment(self, name: str, value: float = 1, **labels: object) -> None:
        with self._lock:
            self._counters[(name, self._labels(labels))] += value

    def gauge(self, name: str, value: float, **labels: object) -> None:
        with self._lock:
            self._gauges[(name, self._labels(labels))] = value

    def adjust_gauge(self, name: str, delta: float, **labels: object) -> None:
        with self._lock:
            self._gauges[(name, self._labels(labels))] += delta

    def observe_request(self, method: str, route: str, status_code: int, seconds: float) -> None:
        key = (method, route, status_code)
        with self._lock:
            count, total = self._request_sums[key]
            self._request_sums[key] = count + 1, total + seconds
            for bucket in LATENCY_BUCKETS:
                if seconds <= bucket:
                    self._request_buckets[(*key, bucket)] += 1

    def observe(self, name: str, seconds: float, **labels: object) -> None:
        label_values = self._labels(labels)
        key = (name, label_values)
        with self._lock:
            count, total = self._duration_sums[key]
            self._duration_sums[key] = count + 1, total + seconds
            for bucket in LATENCY_BUCKETS:
                if seconds <= bucket:
                    self._duration_buckets[(name, label_values, bucket)] += 1

    @staticmethod
    def _format_labels(labels: tuple[tuple[str, str], ...]) -> str:
        if not labels:
            return ""
        escaped = [f'{key}="{value.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"' for key, value in labels]
        return "{" + ",".join(escaped) + "}"

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            counters = list(self._counters.items())
            gauges = list(self._gauges.items())
            buckets = list(self._request_buckets.items())
            sums = list(self._request_sums.items())
            duration_buckets = list(self._duration_buckets.items())
            duration_sums = list(self._duration_sums.items())
        for (name, labels), value in sorted(counters):
            lines.append(f"{name}{self._format_labels(labels)} {value}")
        for (name, labels), value in sorted(gauges):
            lines.append(f"{name}{self._format_labels(labels)} {value}")
        for (method, route, status_code, bucket), value in sorted(buckets):
            labels = self._labels({"method": method, "route": route, "status": status_code, "le": bucket})
            lines.append(f"nerva_http_request_duration_seconds_bucket{self._format_labels(labels)} {value}")
        for (method, route, status_code), (count, total) in sorted(sums):
            labels = self._labels({"method": method, "route": route, "status": status_code})
            infinity_labels = self._labels({
                "method": method, "route": route, "status": status_code, "le": "+Inf",
            })
            lines.append(f"nerva_http_request_duration_seconds_bucket{self._format_labels(infinity_labels)} {count}")
            lines.append(f"nerva_http_requests_total{self._format_labels(labels)} {count}")
            lines.append(f"nerva_http_request_duration_seconds_sum{self._format_labels(labels)} {total}")
            lines.append(f"nerva_http_request_duration_seconds_count{self._format_labels(labels)} {count}")
        for (name, labels, bucket), value in sorted(duration_buckets):
            bucket_labels = tuple(sorted((*labels, ("le", str(bucket)))))
            lines.append(f"{name}_seconds_bucket{self._format_labels(bucket_labels)} {value}")
        for (name, labels), (count, total) in sorted(duration_sums):
            infinity_labels = tuple(sorted((*labels, ("le", "+Inf"))))
            lines.append(f"{name}_seconds_bucket{self._format_labels(infinity_labels)} {count}")
            lines.append(f"{name}_seconds_sum{self._format_labels(labels)} {total}")
            lines.append(f"{name}_seconds_count{self._format_labels(labels)} {count}")
        return "\n".join(lines) + "\n"


metrics = Metrics()
