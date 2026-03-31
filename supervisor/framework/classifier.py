"""
State Classifier — maps raw metrics to a named state.

Supports rule-based classification from YAML config and custom
callable classifiers.
"""

from __future__ import annotations

import operator
from abc import ABC, abstractmethod
from typing import Any, Callable


# Operator lookup for rule conditions
_OPS: dict[str, Callable[[Any, Any], bool]] = {
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "in": lambda a, b: a in b,
    "not_in": lambda a, b: a not in b,
    "empty": lambda a, _: (a is None or a == "" or a == 0 or
                            (isinstance(a, (list, dict)) and len(a) == 0) or
                            a is True),  # _raw_empty flag
    "not_empty": lambda a, _: not (a is None or a == "" or a == 0 or
                                    (isinstance(a, (list, dict)) and len(a) == 0) or
                                    a is True),
    "contains": lambda a, b: b in str(a),
}


class StateClassifier(ABC):
    """Base class for state classifiers."""

    @abstractmethod
    def classify(self, metrics: dict[str, Any]) -> str:
        """Determine the current state name from metrics.

        Returns:
            A state name string.
        """


class RuleBasedClassifier(StateClassifier):
    """Classifies state by evaluating ordered rules from config.

    Rules are evaluated in order. The first rule whose conditions all
    match wins. If no rule matches, returns ``default_state``.

    Parameters:
        rules: list of rule dicts, each with:
            - state: the state name to return if this rule matches.
            - conditions: list of condition dicts, each with:
                - metric: metric name (use "_raw_empty" for empty check).
                - op: comparison operator string (see _OPS).
                - value: value to compare against (ignored for "empty"/"not_empty").
        default_state: state name returned when no rule matches.
    """

    def __init__(self, rules: list[dict], default_state: str = "UNKNOWN"):
        self.rules = rules
        self.default_state = default_state

    def classify(self, metrics: dict[str, Any]) -> str:
        for rule in self.rules:
            state_name = rule.get("state", "UNKNOWN")
            conditions = rule.get("conditions", [])
            if self._all_conditions_match(conditions, metrics):
                return state_name
        return self.default_state

    def _all_conditions_match(self, conditions: list[dict],
                              metrics: dict[str, Any]) -> bool:
        for cond in conditions:
            metric_name = cond.get("metric", "")
            op_name = cond.get("op", "==")
            expected = cond.get("value")

            actual = metrics.get(metric_name)
            op_fn = _OPS.get(op_name)
            if op_fn is None:
                return False

            try:
                if not op_fn(actual, expected):
                    return False
            except (TypeError, ValueError):
                return False

        return True


class CallableClassifier(StateClassifier):
    """Wraps a plain function as a classifier.

    Parameters:
        fn: callable(metrics: dict) -> str
    """

    def __init__(self, fn: Callable[[dict[str, Any]], str]):
        self._fn = fn

    def classify(self, metrics: dict[str, Any]) -> str:
        return self._fn(metrics)


class OverrideClassifier(StateClassifier):
    """Applies override rules on top of a base classifier.

    Override rules are checked first. If none match, delegates to
    the base classifier.

    Parameters:
        base: the base classifier.
        overrides: list of rule dicts (same format as RuleBasedClassifier).
    """

    def __init__(self, base: StateClassifier, overrides: list[dict]):
        self.base = base
        self._override = RuleBasedClassifier(overrides, default_state="")

    def classify(self, metrics: dict[str, Any]) -> str:
        result = self._override.classify(metrics)
        if result:
            return result
        return self.base.classify(metrics)
