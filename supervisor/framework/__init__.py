"""
Agent Supervisor Framework — generic, reusable supervision engine.

Build supervisors from composable components:
  - Collector: gathers metrics from tmux, kubectl, log files, etc.
  - Classifier: maps metrics to a named state.
  - Advisor: produces diagnostic suggestions.
  - Recovery: generates recovery candidates.
  - Delivery: sends directives to the supervised agent.
  - Escalation: configurable multi-level escalation ladder.
  - State: persistent JSON-based state and history.
  - Supervisor: the main engine tying it all together.
  - Profile: loads a complete Supervisor from a YAML config.
"""

from .collector import (
    StateCollector,
    TmuxCollector,
    KubectlCollector,
    LogFileCollector,
    CommandCollector,
    CompositeCollector,
    MockCollector,
    PatternExtractor,
)

from .classifier import (
    StateClassifier,
    RuleBasedClassifier,
    CallableClassifier,
    OverrideClassifier,
)

from .advisor import (
    Advisor,
    RuleBasedAdvisor,
    ScriptAdvisor,
    ChainedAdvisor,
)

from .recovery import (
    RecoveryStrategy,
    ScriptRecovery,
    PlaybookRecovery,
    ChainedRecovery,
    NullRecovery,
)

from .delivery import (
    DirectiveDelivery,
    TmuxDelivery,
    FileDelivery,
    WebhookDelivery,
    CompositeDelivery,
    NullDelivery,
)

from .escalation import (
    EscalationStep,
    EscalationLadder,
)

from .state import SharedStateManager

from .supervisor import Supervisor

from .profile import SupervisorProfile

__all__ = [
    # Collector
    "StateCollector",
    "TmuxCollector",
    "KubectlCollector",
    "LogFileCollector",
    "CommandCollector",
    "CompositeCollector",
    "MockCollector",
    "PatternExtractor",
    # Classifier
    "StateClassifier",
    "RuleBasedClassifier",
    "CallableClassifier",
    "OverrideClassifier",
    # Advisor
    "Advisor",
    "RuleBasedAdvisor",
    "ScriptAdvisor",
    "ChainedAdvisor",
    # Recovery
    "RecoveryStrategy",
    "ScriptRecovery",
    "PlaybookRecovery",
    "ChainedRecovery",
    "NullRecovery",
    # Delivery
    "DirectiveDelivery",
    "TmuxDelivery",
    "FileDelivery",
    "WebhookDelivery",
    "CompositeDelivery",
    "NullDelivery",
    # Escalation
    "EscalationStep",
    "EscalationLadder",
    # State
    "SharedStateManager",
    # Supervisor
    "Supervisor",
    # Profile
    "SupervisorProfile",
]
