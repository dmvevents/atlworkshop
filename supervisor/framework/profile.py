"""
Profile Loader — builds a Supervisor from a YAML config file.

Profiles define the full supervisor configuration declaratively:
collector type, classifier rules, escalation ladder, advisor,
recovery strategy, delivery mechanism, and state paths.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .collector import (
    StateCollector, TmuxCollector, KubectlCollector,
    LogFileCollector, CommandCollector, MockCollector,
)
from .classifier import StateClassifier, RuleBasedClassifier
from .advisor import Advisor, RuleBasedAdvisor, ScriptAdvisor
from .recovery import (
    RecoveryStrategy, ScriptRecovery, PlaybookRecovery, NullRecovery,
)
from .delivery import (
    DirectiveDelivery, TmuxDelivery, FileDelivery,
    WebhookDelivery, NullDelivery,
)
from .escalation import EscalationLadder, EscalationStep
from .state import SharedStateManager
from .supervisor import Supervisor


class SupervisorProfile:
    """Loads a supervisor from a YAML profile.

    Profile schema::

        name: "my-supervisor"
        description: "..."

        collector:
          type: tmux|kubectl|logfile|command
          # type-specific fields ...
          patterns:
            metric_name: "regex"

        classifier:
          type: rule_based
          default_state: UNKNOWN
          rules:
            - state: STATE_NAME
              conditions:
                - {metric: name, op: "==", value: 0}

        escalation:
          steps:
            - {name: OBSERVE, threshold: 0, action: observe}
            - {name: DIAGNOSE, threshold: 3, action: diagnose}
          no_escalate_states: [STATE_A, STATE_B]

        advisor:
          type: rule_based|script
          # type-specific fields ...

        recovery:
          type: script|playbook|null
          # type-specific fields ...

        delivery:
          type: tmux|file|webhook|null
          # type-specific fields ...

        state:
          path: path/to/state.json
          history_path: path/to/history.jsonl
    """

    @staticmethod
    def from_yaml(path: str, dry_run: bool = False) -> Supervisor:
        """Load a YAML profile and construct a Supervisor.

        Parameters:
            path: path to the YAML profile file.
            dry_run: if True, replaces delivery with NullDelivery.

        Returns:
            A configured Supervisor instance.
        """
        profile_path = Path(path)
        with open(profile_path) as f:
            config = yaml.safe_load(f)

        # Resolve paths relative to the profile file's directory
        base_dir = profile_path.parent

        name = config.get("name", "supervisor")

        collector = _build_collector(config.get("collector", {}), base_dir)
        classifier = _build_classifier(config.get("classifier", {}))
        escalation = _build_escalation(config.get("escalation", {}))
        advisor = _build_advisor(config.get("advisor", {}), base_dir)
        recovery = _build_recovery(config.get("recovery", {}), base_dir)
        delivery = _build_delivery(config.get("delivery", {}), base_dir)
        state_manager = _build_state_manager(config.get("state", {}), base_dir)

        return Supervisor(
            collector=collector,
            classifier=classifier,
            advisor=advisor,
            recovery=recovery,
            delivery=delivery,
            escalation=escalation,
            state_manager=state_manager,
            name=name,
            dry_run=dry_run,
        )


def _resolve_path(path_str: str, base_dir: Path) -> str:
    """Resolve a path relative to base_dir if not absolute."""
    p = Path(path_str)
    if p.is_absolute():
        return str(p)
    return str(base_dir / p)


def _build_collector(cfg: dict, base_dir: Path) -> StateCollector:
    ctype = cfg.get("type", "tmux")
    patterns = cfg.get("patterns", {})

    if ctype == "tmux":
        return TmuxCollector(
            session=cfg.get("session", "main"),
            patterns=patterns,
            capture_lines=cfg.get("capture_lines", 500),
        )
    elif ctype == "kubectl":
        return KubectlCollector(
            namespace=cfg.get("namespace", "default"),
            pod=cfg.get("pod", ""),
            patterns=patterns,
            tail_lines=cfg.get("tail_lines", 0),
            extra_args=cfg.get("extra_args"),
        )
    elif ctype == "logfile":
        return LogFileCollector(
            path=_resolve_path(cfg.get("path", "output.log"), base_dir),
            patterns=patterns,
            tail_lines=cfg.get("tail_lines", 0),
        )
    elif ctype == "command":
        return CommandCollector(
            command=cfg.get("command", ["echo", "no-op"]),
            patterns=patterns,
            timeout=cfg.get("timeout", 30),
            shell=cfg.get("shell", False),
        )
    else:
        # Default to a no-op mock
        return MockCollector(data_sequence=[("", {"_raw_empty": True})])


def _build_classifier(cfg: dict) -> StateClassifier:
    ctype = cfg.get("type", "rule_based")

    if ctype == "rule_based":
        return RuleBasedClassifier(
            rules=cfg.get("rules", []),
            default_state=cfg.get("default_state", "UNKNOWN"),
        )
    else:
        return RuleBasedClassifier(rules=[], default_state="UNKNOWN")


def _build_escalation(cfg: dict) -> EscalationLadder:
    steps_cfg = cfg.get("steps", [
        {"name": "OBSERVE", "threshold": 0, "action": "observe"},
        {"name": "DIAGNOSE", "threshold": 3, "action": "diagnose"},
        {"name": "SUGGEST", "threshold": 5, "action": "suggest"},
        {"name": "ESCALATE", "threshold": 10, "action": "escalate"},
    ])

    steps = [
        EscalationStep(
            name=s.get("name", "UNKNOWN"),
            threshold_cycles=s.get("threshold", 0),
            action=s.get("action", "observe"),
            cooldown_cycles=s.get("cooldown", 0),
        )
        for s in steps_cfg
    ]

    no_escalate = set(cfg.get("no_escalate_states", []))
    return EscalationLadder(steps=steps, no_escalate_states=no_escalate)


def _build_advisor(cfg: dict, base_dir: Path) -> Advisor:
    atype = cfg.get("type", "rule_based")

    if atype == "rule_based":
        return RuleBasedAdvisor(
            state_map=cfg.get("state_map", {}),
            default_diagnosis=cfg.get("default_diagnosis"),
        )
    elif atype == "script":
        return ScriptAdvisor(
            script_path=_resolve_path(cfg.get("script", "advisor.py"), base_dir),
            args_template=cfg.get("args"),
            timeout=cfg.get("timeout", 30),
            interpreter=cfg.get("interpreter"),
        )
    else:
        return RuleBasedAdvisor(state_map={})


def _build_recovery(cfg: dict, base_dir: Path) -> RecoveryStrategy:
    rtype = cfg.get("type", "null")

    if rtype == "script":
        return ScriptRecovery(
            script_path=_resolve_path(cfg.get("script", "recovery.py"), base_dir),
            args_template=cfg.get("args"),
            timeout=cfg.get("timeout", 120),
            interpreter=cfg.get("interpreter"),
        )
    elif rtype == "playbook":
        return PlaybookRecovery(
            playbooks=cfg.get("playbooks", {}),
            default_playbook=cfg.get("default_playbook"),
        )
    elif rtype == "null":
        return NullRecovery()
    else:
        return NullRecovery()


def _build_delivery(cfg: dict, base_dir: Path) -> DirectiveDelivery:
    dtype = cfg.get("type", "null")

    if dtype == "tmux":
        inject = cfg.get("inject_script")
        if inject:
            inject = _resolve_path(inject, base_dir)
        return TmuxDelivery(
            session=cfg.get("session", "main"),
            inject_script=inject,
        )
    elif dtype == "file":
        return FileDelivery(
            path=_resolve_path(cfg.get("path", "directives.jsonl"), base_dir),
            mode=cfg.get("mode", "append"),
        )
    elif dtype == "webhook":
        return WebhookDelivery(
            url=cfg.get("url", "http://localhost:8080/directive"),
            headers=cfg.get("headers"),
            timeout=cfg.get("timeout", 10),
        )
    elif dtype == "null":
        return NullDelivery()
    else:
        return NullDelivery()


def _build_state_manager(cfg: dict, base_dir: Path) -> SharedStateManager:
    state_path = _resolve_path(
        cfg.get("path", "supervisor-state.json"), base_dir
    )
    history_path = cfg.get("history_path")
    if history_path:
        history_path = _resolve_path(history_path, base_dir)

    return SharedStateManager(
        state_path=state_path,
        history_path=history_path,
    )
