"""Minimal Prometheus text-format metrics (no external dependency). Labels must be low-cardinality."""
from __future__ import annotations

import threading
from collections import defaultdict


class Registry:
    def __init__(self):
        self._lock = threading.Lock()
        self.counters: dict[str, dict[tuple, float]] = defaultdict(lambda: defaultdict(float))
        self.help: dict[str, str] = {}
        self.hist: dict[str, dict[tuple, list]] = defaultdict(dict)
        self.buckets = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)

    def inc(self, name: str, help_: str = "", n: float = 1, **labels: str) -> None:
        with self._lock:
            self.help.setdefault(name, help_)
            self.counters[name][tuple(sorted(labels.items()))] += n

    def observe(self, name: str, value: float, help_: str = "", **labels: str) -> None:
        with self._lock:
            self.help.setdefault(name, help_)
            key = tuple(sorted(labels.items()))
            h = self.hist[name].setdefault(key, [[0] * len(self.buckets), 0.0, 0])
            for i, b in enumerate(self.buckets):
                if value <= b:
                    h[0][i] += 1
            h[1] += value
            h[2] += 1

    def get(self, name: str, **labels: str) -> float:
        return self.counters[name].get(tuple(sorted(labels.items())), 0.0)

    @staticmethod
    def _l(key: tuple, extra: str = "") -> str:
        parts = [f'{k}="{v}"' for k, v in key] + ([extra] if extra else [])
        return "{" + ",".join(parts) + "}" if parts else ""

    def render(self) -> str:
        out: list[str] = []
        with self._lock:
            for name, series in self.counters.items():
                out += [f"# HELP {name} {self.help.get(name, '')}", f"# TYPE {name} counter"]
                out += [f"{name}{self._l(k)} {v}" for k, v in series.items()]
            for name, series in self.hist.items():
                out += [f"# HELP {name} {self.help.get(name, '')}", f"# TYPE {name} histogram"]
                for k, (counts, total, n) in series.items():
                    for b, c in zip(self.buckets, counts, strict=True):
                        out.append(name + "_bucket" + self._l(k, f'le="{b}"') + " " + str(c))
                    out.append(name + "_bucket" + self._l(k, 'le="+Inf"') + " " + str(n))
                    out.append(f"{name}_sum{self._l(k)} {total}")
                    out.append(f"{name}_count{self._l(k)} {n}")
        return "\n".join(out) + "\n"


METRICS = Registry()
