"""
State Collector — gathers raw metrics from external sources.

Collectors read from tmux panes, kubectl logs, log files, or arbitrary
commands, then apply regex patterns to extract named metrics.
"""

from __future__ import annotations

import re
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class StateCollector(ABC):
    """Base class for all state collectors."""

    @abstractmethod
    def collect(self) -> tuple[str, dict[str, Any]]:
        """Collect state from the source.

        Returns:
            (raw_text, metrics_dict) where raw_text is the raw captured
            output and metrics_dict maps metric names to extracted values.
        """


class PatternExtractor:
    """Shared helper that applies regex patterns to raw text.

    Each pattern value may be:
      - A plain regex string: returns the count of matches (int).
      - A dict with keys ``pattern`` and ``extract``:
          - extract="count" (default): count of matches.
          - extract="last_group1": last match group(1) as string.
          - extract="all": list of all match strings.
    """

    def __init__(self, patterns: dict[str, Any]):
        self.patterns = patterns

    def extract(self, text: str) -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        for name, spec in self.patterns.items():
            if isinstance(spec, str):
                metrics[name] = len(re.findall(spec, text))
            elif isinstance(spec, dict):
                pat = spec.get("pattern", "")
                mode = spec.get("extract", "count")
                matches = re.findall(pat, text)
                if mode == "count":
                    metrics[name] = len(matches)
                elif mode == "last_group1":
                    metrics[name] = matches[-1] if matches else None
                elif mode == "all":
                    metrics[name] = matches
                else:
                    metrics[name] = len(matches)
            else:
                metrics[name] = 0
        # Always include a special _raw_empty flag
        metrics["_raw_empty"] = len(text.strip()) == 0
        return metrics


class TmuxCollector(StateCollector):
    """Captures a tmux pane and extracts metrics via regex patterns.

    Parameters:
        session: tmux session name (or session:window.pane).
        patterns: metric_name -> regex pattern string or spec dict.
        capture_lines: number of lines to capture from the pane (default 500).
    """

    def __init__(self, session: str, patterns: dict[str, Any],
                 capture_lines: int = 500):
        self.session = session
        self.capture_lines = capture_lines
        self._extractor = PatternExtractor(patterns)

    def collect(self) -> tuple[str, dict[str, Any]]:
        try:
            result = subprocess.run(
                ["tmux", "capture-pane", "-p", "-S",
                 str(-self.capture_lines), "-t", self.session],
                capture_output=True, text=True, timeout=10,
            )
            raw = result.stdout if result.returncode == 0 else ""
        except (subprocess.TimeoutExpired, FileNotFoundError):
            raw = ""

        return raw, self._extractor.extract(raw)


class KubectlCollector(StateCollector):
    """Reads kubectl logs and extracts metrics via regex patterns.

    Parameters:
        namespace: Kubernetes namespace.
        pod: pod name (or pod/container).
        patterns: metric_name -> regex pattern.
        tail_lines: number of recent lines (0 = all).
        extra_args: additional kubectl args (e.g. ["--container", "main"]).
    """

    def __init__(self, namespace: str, pod: str, patterns: dict[str, Any],
                 tail_lines: int = 0, extra_args: list[str] | None = None):
        self.namespace = namespace
        self.pod = pod
        self.tail_lines = tail_lines
        self.extra_args = extra_args or []
        self._extractor = PatternExtractor(patterns)

    def collect(self) -> tuple[str, dict[str, Any]]:
        cmd = ["kubectl", "logs", self.pod, "-n", self.namespace]
        if self.tail_lines > 0:
            cmd.extend(["--tail", str(self.tail_lines)])
        cmd.extend(self.extra_args)

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
            )
            raw = result.stdout if result.returncode == 0 else ""
        except (subprocess.TimeoutExpired, FileNotFoundError):
            raw = ""

        return raw, self._extractor.extract(raw)


class LogFileCollector(StateCollector):
    """Reads a log file and extracts metrics via regex patterns.

    Parameters:
        path: path to the log file.
        patterns: metric_name -> regex pattern.
        tail_lines: only read the last N lines (0 = read all).
    """

    def __init__(self, path: str, patterns: dict[str, Any],
                 tail_lines: int = 0):
        self.path = Path(path)
        self.tail_lines = tail_lines
        self._extractor = PatternExtractor(patterns)

    def collect(self) -> tuple[str, dict[str, Any]]:
        try:
            text = self.path.read_text()
            if self.tail_lines > 0:
                lines = text.splitlines()
                text = "\n".join(lines[-self.tail_lines:])
        except (OSError, IOError):
            text = ""

        return text, self._extractor.extract(text)


class CommandCollector(StateCollector):
    """Runs an arbitrary shell command and extracts metrics.

    Parameters:
        command: command as a list of strings.
        patterns: metric_name -> regex pattern.
        timeout: command timeout in seconds.
        shell: if True, run via shell (command should be a single string).
    """

    def __init__(self, command: list[str] | str, patterns: dict[str, Any],
                 timeout: int = 30, shell: bool = False):
        self.command = command
        self.shell = shell
        self.timeout = timeout
        self._extractor = PatternExtractor(patterns)

    def collect(self) -> tuple[str, dict[str, Any]]:
        try:
            result = subprocess.run(
                self.command, capture_output=True, text=True,
                timeout=self.timeout, shell=self.shell,
            )
            raw = result.stdout if result.returncode == 0 else ""
        except (subprocess.TimeoutExpired, FileNotFoundError):
            raw = ""

        return raw, self._extractor.extract(raw)


class CompositeCollector(StateCollector):
    """Combines multiple collectors into a single metrics dict.

    Each sub-collector's metrics are merged. If names collide, later
    collectors overwrite earlier ones. Raw text is concatenated with
    section markers.

    Parameters:
        collectors: list of (name, StateCollector) tuples.
    """

    def __init__(self, collectors: list[tuple[str, StateCollector]]):
        self.collectors = collectors

    def collect(self) -> tuple[str, dict[str, Any]]:
        combined_raw: list[str] = []
        combined_metrics: dict[str, Any] = {}

        for name, collector in self.collectors:
            raw, metrics = collector.collect()
            combined_raw.append(f"--- {name} ---\n{raw}")
            # Prefix metrics with collector name to avoid collisions
            for k, v in metrics.items():
                if k.startswith("_"):
                    combined_metrics[f"{name}{k}"] = v
                else:
                    combined_metrics[k] = v

        full_raw = "\n".join(combined_raw)
        combined_metrics["_raw_empty"] = len(full_raw.strip()) == 0
        return full_raw, combined_metrics


class MockCollector(StateCollector):
    """Returns pre-configured data, useful for testing and demos.

    Parameters:
        data_sequence: list of (raw_text, metrics_dict) tuples. Cycles
            through the list on each call.
    """

    def __init__(self, data_sequence: list[tuple[str, dict[str, Any]]]):
        self.data_sequence = data_sequence
        self._index = 0

    def collect(self) -> tuple[str, dict[str, Any]]:
        if not self.data_sequence:
            return "", {"_raw_empty": True}
        item = self.data_sequence[self._index % len(self.data_sequence)]
        self._index += 1
        return item
