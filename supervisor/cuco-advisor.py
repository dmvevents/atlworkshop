#!/usr/bin/env python3
"""
CUCo Design-Space-Aware Diagnostic Advisor

Takes the current Transport supervisor state and maps it to the CUCo 5D design
space (B x P x S x I x G) defined in culink-efa.yaml. Outputs structured
diagnostics with the failing dimension, current config, suggested alternatives,
and rationale.

Usage:
    # Interactive diagnostic
    python3 cuco-advisor.py --state C0_NO_WORKER

    # With current config dimensions
    python3 cuco-advisor.py --state C0_NO_WORKER \
        --config B=d2h_ring_fi_send,S=d2h_ring,I=multi_warp

    # JSON output for programmatic consumption
    python3 cuco-advisor.py --state DISPATCHING --timeout --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    # Inline minimal YAML loader fallback — only supports the subset we need
    yaml = None


# ---------------------------------------------------------------------------
# Design-space loader
# ---------------------------------------------------------------------------

DESIGN_SPACE_PATH = (
    Path(__file__).resolve().parent.parent
    / "cuco-codesign"
    / "design-space"
    / "culink-efa.yaml"
)

DIMENSION_KEYS = ["backend", "placement", "sync", "issuer", "granularity"]
DIMENSION_SYMBOLS = {"backend": "B", "placement": "P", "sync": "S", "issuer": "I", "granularity": "G"}


def load_design_space(path: Path | None = None) -> dict:
    """Load and return the CULink-EFA design space YAML."""
    path = path or DESIGN_SPACE_PATH
    if not path.exists():
        print(f"ERROR: Design space file not found: {path}", file=sys.stderr)
        sys.exit(1)

    text = path.read_text()
    if yaml is not None:
        return yaml.safe_load(text)

    # Minimal fallback — should not be needed if PyYAML is installed
    raise ImportError(
        "PyYAML is required. Install with: pip install pyyaml"
    )


def get_dimension_values(ds: dict, dim_key: str) -> list[str]:
    """Return the list of valid value names for a dimension."""
    dim = ds.get(dim_key, {})
    values = dim.get("values", {})
    return list(values.keys())


def get_default_config(ds: dict) -> dict[str, str]:
    """Return the default config from the design space."""
    config = {}
    for key in DIMENSION_KEYS:
        dim = ds.get(key, {})
        default = dim.get("default")
        if default:
            config[DIMENSION_SYMBOLS[key]] = default
    return config


def get_recommendations(ds: dict) -> dict[str, dict]:
    """Return the named recommendation configs."""
    return ds.get("recommendations", {})


# ---------------------------------------------------------------------------
# State-to-dimension mapping
# ---------------------------------------------------------------------------

STATE_DIMENSION_MAP: dict[str, dict] = {
    "C0_NO_WORKER": {
        "failing_dimension": "S",
        "failing_dimension_name": "Sync",
        "rationale": (
            "GPU coordinator (C0) fired a signal but no CPU worker picked it up. "
            "This indicates the GPU-to-CPU synchronization mechanism is not "
            "delivering the signal to the worker thread. The Sync (S) dimension "
            "controls how the GPU notifies the CPU proxy."
        ),
        "suggestions": ["gdrcopy_mmio", "host_pinned_volatile", "cuda_event"],
        "exclude_from_suggestions": ["eventfd_hybrid"],  # too slow for dispatch
        "additional_checks": [
            "Verify host_dispatch_signals address matches between GPU and worker",
            "Check worker poll loop is reading the correct memory address",
            "Ensure __threadfence_system() is called before GPU writes the signal",
        ],
    },
    "C0_TIMEOUT": {
        "failing_dimension": "I",
        "failing_dimension_name": "Issuer",
        "rationale": (
            "DIAG-F barrier passed but no BOLT-C0 coordinator signal was generated. "
            "The GPU warp responsible for issuing descriptors never fired. The Issuer (I) "
            "dimension controls which GPU threads generate communication descriptors."
        ),
        "suggestions": ["single_warp", "cpu_worker"],
        "exclude_from_suggestions": [],
        "additional_checks": [
            "Check g_bolt_dispatch_signals is non-null in the coordinator warp",
            "Verify the coordinator warp index matches BOLT_COORDINATOR_WARP",
            "Ensure sender warps have completed their data staging before C0 fires",
            "Check if the coordinator is blocked on a __syncwarp() or __syncthreads()",
        ],
    },
    "DISPATCHING": {
        # Only relevant when DISPATCHING + timeout
        "failing_dimension": "B",
        "failing_dimension_name": "Backend",
        "rationale": (
            "Worker dispatched data (fi_writemsg posted) but transfer is timing out. "
            "The data transport mechanism is failing. The Backend (B) dimension "
            "controls how data moves from GPU memory to the remote node via EFA."
        ),
        "suggestions": ["d2h_ring_fi_send", "gdrcopy_mmio", "staging_copy_bulk"],
        "exclude_from_suggestions": [],
        "additional_checks": [
            "Check EFA HW counters: /sys/class/infiniband/rdmap*/ports/1/hw_counters/",
            "Verify fi_writemsg return code is not -FI_EAGAIN (CQ full)",
            "Check if cudaMemcpy in staging path is blocking or returning errors",
            "Verify remote MR rkey and address are correct",
            "Check SRD security group: self-referencing EGRESS rule required",
        ],
    },
    "NO_WORKERS": {
        "failing_dimension": None,
        "failing_dimension_name": "Infrastructure",
        "rationale": (
            "No Bolt workers started. This is an infrastructure issue, not a "
            "design-space problem. bolt_start_worker() must be called after peers "
            "are applied."
        ),
        "suggestions": [],
        "exclude_from_suggestions": [],
        "additional_checks": [
            "Verify bolt_start_worker() is called in runtime.cu after bolt_apply_peers()",
            "Check that USE_BOLT=1 is set during build",
        ],
    },
    "PEERS_MISSING": {
        "failing_dimension": None,
        "failing_dimension_name": "Infrastructure",
        "rationale": (
            "Workers started but have no peers. bolt_apply_peers() needs to be called "
            "with correct remote endpoint names and addresses."
        ),
        "suggestions": [],
        "exclude_from_suggestions": [],
        "additional_checks": [
            "Add bolt_apply_peers() call in fabric_apply_remote() of runtime.cu",
            "Verify AV insert return code is 1 (success) and rkey is non-zero",
            "Check ep_name_len is 32 for all peers",
        ],
    },
    "NO_BOLT": {
        "failing_dimension": None,
        "failing_dimension_name": "Infrastructure",
        "rationale": "Bolt not initialized on pods. Rebuild with USE_BOLT=1.",
        "suggestions": [],
        "exclude_from_suggestions": [],
        "additional_checks": [
            "Rebuild DeepEP with USE_BOLT=1 flag",
            "Verify bolt_init() is called in runtime.cu",
        ],
    },
    "NO_PODS": {
        "failing_dimension": None,
        "failing_dimension_name": "Infrastructure",
        "rationale": "No pods running. Deploy pods first.",
        "suggestions": [],
        "exclude_from_suggestions": [],
        "additional_checks": [],
    },
    "BARRIER_WAIT": {
        "failing_dimension": None,
        "failing_dimension_name": "Waiting",
        "rationale": "Waiting for DIAG-F barrier to complete. This is normal during startup.",
        "suggestions": [],
        "exclude_from_suggestions": [],
        "additional_checks": [],
    },
    "ALL_PASS": {
        "failing_dimension": None,
        "failing_dimension_name": "None",
        "rationale": "All tests passing. No design-space intervention needed.",
        "suggestions": [],
        "exclude_from_suggestions": [],
        "additional_checks": [],
    },
}


# ---------------------------------------------------------------------------
# Advisor logic
# ---------------------------------------------------------------------------

def parse_config_string(config_str: str) -> dict[str, str]:
    """Parse 'B=val,S=val,I=val' into a dict."""
    if not config_str:
        return {}
    config = {}
    for pair in config_str.split(","):
        pair = pair.strip()
        if "=" in pair:
            k, v = pair.split("=", 1)
            config[k.strip().upper()] = v.strip()
    return config


def advise(
    state: str,
    current_config: dict[str, str] | None = None,
    has_timeout: bool = False,
    ds: dict | None = None,
) -> dict:
    """
    Generate a CUCo design-space-aware diagnostic for the given supervisor state.

    Returns a structured dict with:
      - state: the supervisor state
      - failing_dimension: which CUCo dimension is likely failing (or None)
      - current_config: the active config (filled from defaults if missing)
      - suggestions: list of alternative values for the failing dimension
      - rationale: human-readable explanation
      - additional_checks: concrete debugging steps
      - recommendation: a named CUCo recommendation to try if available
    """
    if ds is None:
        ds = load_design_space()

    # Fill in defaults for any missing config dimensions
    defaults = get_default_config(ds)
    config = dict(defaults)
    if current_config:
        config.update(current_config)

    # Special case: DISPATCHING only gets design-space advice when there is a timeout
    effective_state = state
    if state == "DISPATCHING" and not has_timeout:
        # Dispatching without timeout is normal progress
        return {
            "state": state,
            "failing_dimension": None,
            "failing_dimension_name": "None",
            "current_config": config,
            "suggestions": [],
            "rationale": "Dispatching in progress without timeout. Normal operation.",
            "additional_checks": [],
            "recommendation": None,
        }

    mapping = STATE_DIMENSION_MAP.get(effective_state, {
        "failing_dimension": None,
        "failing_dimension_name": "Unknown",
        "rationale": f"Unknown state '{state}'. No design-space mapping available.",
        "suggestions": [],
        "exclude_from_suggestions": [],
        "additional_checks": [],
    })

    failing_dim = mapping["failing_dimension"]
    suggestions = list(mapping["suggestions"])
    exclude = mapping.get("exclude_from_suggestions", [])

    # If we have a failing dimension, augment suggestions from the design space
    if failing_dim:
        dim_key = None
        for k, sym in DIMENSION_SYMBOLS.items():
            if sym == failing_dim:
                dim_key = k
                break

        if dim_key:
            all_values = get_dimension_values(ds, dim_key)
            current_value = config.get(failing_dim, "")

            # Build enriched suggestions: alternatives that aren't the current value
            enriched = []
            for val in suggestions:
                if val != current_value and val not in exclude and val in all_values:
                    # Look up description from design space
                    val_info = ds.get(dim_key, {}).get("values", {}).get(val, {})
                    desc = val_info.get("description", "").strip().split("\n")[0].strip()
                    enriched.append({
                        "value": val,
                        "description": desc,
                    })

            # Also add any design-space values not already in suggestions
            for val in all_values:
                if val != current_value and val not in exclude:
                    already = any(s["value"] == val for s in enriched)
                    if not already:
                        val_info = ds.get(dim_key, {}).get("values", {}).get(val, {})
                        desc = val_info.get("description", "").strip().split("\n")[0].strip()
                        enriched.append({
                            "value": val,
                            "description": desc,
                        })

            suggestions = enriched

    # Find a relevant recommendation
    recommendation = None
    recs = get_recommendations(ds)
    if failing_dim and state not in ("ALL_PASS", "BARRIER_WAIT"):
        # Suggest the conservative recommendation if current config matches aggressive
        current_b = config.get("B", "")
        if "fi_send" in current_b or "staging" in current_b:
            # Already on a simpler backend, suggest balanced or aggressive
            for name in ("balanced", "aggressive"):
                rec = recs.get(name, {})
                rec_config = rec.get("config", {})
                if rec_config.get(failing_dim) != config.get(failing_dim):
                    recommendation = {
                        "name": name,
                        "config": rec_config,
                        "description": rec.get("description", ""),
                        "expected_improvement": rec.get("expected_improvement", ""),
                        "risk": rec.get("risk", ""),
                    }
                    break
        else:
            # Try conservative first
            for name in ("conservative", "balanced"):
                rec = recs.get(name, {})
                rec_config = rec.get("config", {})
                if rec_config.get(failing_dim) != config.get(failing_dim):
                    recommendation = {
                        "name": name,
                        "config": rec_config,
                        "description": rec.get("description", ""),
                        "expected_improvement": rec.get("expected_improvement", ""),
                        "risk": rec.get("risk", ""),
                    }
                    break

    return {
        "state": state,
        "failing_dimension": failing_dim,
        "failing_dimension_name": mapping["failing_dimension_name"],
        "current_config": config,
        "suggestions": suggestions,
        "rationale": mapping["rationale"],
        "additional_checks": mapping["additional_checks"],
        "recommendation": recommendation,
    }


def format_human_readable(result: dict) -> str:
    """Format the advisory result as human-readable text."""
    lines = []
    lines.append(f"[CUCO] Diagnostic for state: {result['state']}")
    lines.append(f"[CUCO] Failing dimension: {result['failing_dimension'] or 'N/A'} ({result['failing_dimension_name']})")
    lines.append(f"[CUCO] Rationale: {result['rationale']}")
    lines.append("")

    config = result["current_config"]
    lines.append("[CUCO] Current config:")
    for sym in ("B", "P", "S", "I", "G"):
        lines.append(f"  {sym} = {config.get(sym, '?')}")
    lines.append("")

    suggestions = result["suggestions"]
    if suggestions:
        dim = result["failing_dimension"]
        lines.append(f"[CUCO] Suggested alternatives for {dim}:")
        for i, s in enumerate(suggestions, 1):
            if isinstance(s, dict):
                lines.append(f"  {i}. {s['value']}: {s['description']}")
            else:
                lines.append(f"  {i}. {s}")
        lines.append("")

    checks = result["additional_checks"]
    if checks:
        lines.append("[CUCO] Additional checks:")
        for c in checks:
            lines.append(f"  - {c}")
        lines.append("")

    rec = result["recommendation"]
    if rec:
        lines.append(f"[CUCO] Recommended config ({rec['name']}): {rec['description']}")
        rc = rec["config"]
        lines.append(f"  Config: B={rc.get('B','?')} P={rc.get('P','?')} S={rc.get('S','?')} I={rc.get('I','?')} G={rc.get('G','?')}")
        lines.append(f"  Expected: {rec['expected_improvement']} | Risk: {rec['risk']}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="CUCo design-space-aware diagnostic advisor for the Transport supervisor"
    )
    parser.add_argument(
        "--state",
        required=True,
        help="Current supervisor state (e.g., C0_NO_WORKER, C0_TIMEOUT, DISPATCHING)",
    )
    parser.add_argument(
        "--config",
        default="",
        help="Current config dimensions as 'B=val,S=val,I=val' (defaults filled from design space)",
    )
    parser.add_argument(
        "--timeout",
        action="store_true",
        help="Whether a timeout has been detected (relevant for DISPATCHING state)",
    )
    parser.add_argument(
        "--design-space",
        default=None,
        help="Path to culink-efa.yaml (default: auto-detected relative to this script)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output as JSON instead of human-readable text",
    )
    args = parser.parse_args()

    ds_path = Path(args.design_space) if args.design_space else None
    ds = load_design_space(ds_path)

    current_config = parse_config_string(args.config)

    result = advise(
        state=args.state,
        current_config=current_config,
        has_timeout=args.timeout,
        ds=ds,
    )

    if args.json_output:
        print(json.dumps(result, indent=2))
    else:
        print(format_human_readable(result))


if __name__ == "__main__":
    main()
