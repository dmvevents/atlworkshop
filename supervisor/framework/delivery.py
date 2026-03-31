"""
Directive Delivery — sends directives to supervised agents.

Delivery mechanisms include tmux send-keys, file-based delivery,
webhook calls, and composite multi-target delivery.
"""

from __future__ import annotations

import logging
import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class DirectiveDelivery(ABC):
    """Base class for directive delivery mechanisms."""

    @abstractmethod
    def send(self, directive: str) -> bool:
        """Send a directive string to the supervised agent.

        Returns:
            True if delivery succeeded, False otherwise.
        """


class TmuxDelivery(DirectiveDelivery):
    """Sends directives via tmux send-keys or a custom inject script.

    Parameters:
        session: tmux session (or session:window.pane) target.
        inject_script: optional path to a custom inject script that
            takes (session, directive) as arguments.
    """

    def __init__(self, session: str, inject_script: str | None = None):
        self.session = session
        self.inject_script = inject_script

    def send(self, directive: str) -> bool:
        try:
            if self.inject_script:
                result = subprocess.run(
                    [self.inject_script, self.session, directive],
                    capture_output=True, timeout=10,
                )
                return result.returncode == 0
            else:
                # Use tmux send-keys directly
                result = subprocess.run(
                    ["tmux", "send-keys", "-t", self.session,
                     directive, "Enter"],
                    capture_output=True, timeout=10,
                )
                return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.error(f"TmuxDelivery failed: {e}")
            return False


class FileDelivery(DirectiveDelivery):
    """Writes directives to a file that the agent monitors.

    Each directive is appended as a timestamped JSON line.

    Parameters:
        path: path to the directive file.
        mode: "append" (default) or "overwrite".
    """

    def __init__(self, path: str, mode: str = "append"):
        self.path = Path(path)
        self.mode = mode

    def send(self, directive: str) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            import json
            entry = json.dumps({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "directive": directive,
            })
            if self.mode == "overwrite":
                self.path.write_text(entry + "\n")
            else:
                with open(self.path, "a") as f:
                    f.write(entry + "\n")
            return True
        except OSError as e:
            logger.error(f"FileDelivery failed: {e}")
            return False


class WebhookDelivery(DirectiveDelivery):
    """Sends directives via HTTP POST to a webhook URL.

    Parameters:
        url: the webhook URL.
        headers: optional HTTP headers dict.
        timeout: request timeout in seconds.
    """

    def __init__(self, url: str, headers: dict[str, str] | None = None,
                 timeout: int = 10):
        self.url = url
        self.headers = headers or {"Content-Type": "application/json"}
        self.timeout = timeout

    def send(self, directive: str) -> bool:
        import json
        payload = json.dumps({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "directive": directive,
        })
        try:
            # Use subprocess + curl to avoid urllib dependency issues
            cmd = ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                   "-X", "POST", self.url,
                   "-d", payload]
            for k, v in self.headers.items():
                cmd.extend(["-H", f"{k}: {v}"])

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.timeout,
            )
            status = result.stdout.strip()
            return status.startswith("2")
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.error(f"WebhookDelivery failed: {e}")
            return False


class CompositeDelivery(DirectiveDelivery):
    """Sends to multiple delivery targets. Succeeds if any target succeeds.

    Parameters:
        targets: list of (name, DirectiveDelivery) tuples.
        require_all: if True, all must succeed; if False (default),
            any success counts.
    """

    def __init__(self, targets: list[tuple[str, DirectiveDelivery]],
                 require_all: bool = False):
        self.targets = targets
        self.require_all = require_all

    def send(self, directive: str) -> bool:
        results = []
        for name, target in self.targets:
            try:
                ok = target.send(directive)
                results.append(ok)
                if ok:
                    logger.debug(f"Delivery to {name}: OK")
                else:
                    logger.warning(f"Delivery to {name}: FAILED")
            except Exception as e:
                logger.error(f"Delivery to {name}: ERROR {e}")
                results.append(False)

        if self.require_all:
            return all(results)
        return any(results)


class NullDelivery(DirectiveDelivery):
    """No-op delivery that logs but does not send. For dry-run mode."""

    def __init__(self, log_prefix: str = "[DRY-RUN]"):
        self.log_prefix = log_prefix

    def send(self, directive: str) -> bool:
        logger.info(f"{self.log_prefix} Would send: {directive[:200]}")
        return True
