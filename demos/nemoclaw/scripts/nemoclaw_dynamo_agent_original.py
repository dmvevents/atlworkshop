#!/usr/bin/env python3
"""NemoClaw Agent — Powered by NVIDIA Dynamo on EKS.

Uses Nemotron-Mini-4B served by NVIDIA Dynamo (disaggregated inference
with NIXL/EFA RDMA) on the SAME cluster that trains the model. The agent
calls the local Dynamo OpenAI-compatible endpoint for commentary and
orchestration — no external API needed.

This demonstrates the full loop:
  1. Train the model with NeMo RL GRPO on 32x H200
  2. Serve the trained model with NVIDIA Dynamo (disaggregated)
  3. The served model powers the AI agent that orchestrates the demo

Architecture:
  Agent Brain:  Nemotron-Mini-4B on NVIDIA Dynamo (local EKS cluster)
  KV Transfer:  NIXL LIBFABRIC over EFA RDMA (3.2 Tbps)
  Training:     NeMo RL GRPO on 32x NVIDIA H200
  Infra:        2x P5en.48xlarge, Amazon EKS, FSx Lustre

Fallback:
  If the Dynamo endpoint is unavailable (e.g., during training when GPUs
  are occupied), the agent falls back to AWS Bedrock automatically.

Usage:
  # Dynamo-only (requires Dynamo Nemotron pods running)
  python3 scripts/nemoclaw_dynamo_agent.py

  # With Bedrock fallback
  NEMOCLAW_FALLBACK=bedrock python3 scripts/nemoclaw_dynamo_agent.py

  # Force Bedrock (skip Dynamo)
  NEMOCLAW_BACKEND=bedrock python3 scripts/nemoclaw_dynamo_agent.py

  # Custom Dynamo endpoint
  DYNAMO_ENDPOINT=http://10.240.87.215:8001 python3 scripts/nemoclaw_dynamo_agent.py
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error

# ── Config ──
NS = "antonai"
K = os.environ.get("KUBECTL", "docker exec aws-do-eks kubectl")

# Dynamo endpoint (auto-discovered or manual)
DYNAMO_ENDPOINT = os.environ.get("DYNAMO_ENDPOINT", "")  # auto-discover if empty
DYNAMO_MODEL = os.environ.get(
    "DYNAMO_MODEL",
    "dmvevents/Nemotron-Mini-4B-Instruct"
)
DYNAMO_PORT = os.environ.get("DYNAMO_PORT", "8001")

# Bedrock fallback
BEDROCK_REGION = os.environ.get("AWS_REGION", "us-east-1")
BEDROCK_MODEL = os.environ.get("BEDROCK_MODEL", "nvidia.nemotron-nano-3-30b")

# Backend selection
BACKEND = os.environ.get("NEMOCLAW_BACKEND", "dynamo")  # dynamo | bedrock | auto
FALLBACK = os.environ.get("NEMOCLAW_FALLBACK", "bedrock")  # bedrock | none

# ANSI colors
C, G, Y, R, B, N, D = (
    "\033[0;36m", "\033[0;32m", "\033[1;33m",
    "\033[0;31m", "\033[1m", "\033[0m", "\033[2m",
)


def banner(backend_info):
    print(f"""
{C}┌────────────────────────────────────────────────────────────────┐{N}
{C}│{N}                                                                {C}│{N}
{C}│{N}   {B}NemoClaw — AI Agent on NVIDIA Dynamo{N}                        {C}│{N}
{C}│{N}   {B}Powered by the model it trains{N}                              {C}│{N}
{C}│{N}                                                                {C}│{N}
{C}│{N}   {D}Agent Brain:  {backend_info}{N}       {C}│{N}
{C}│{N}   {D}Inference:    NVIDIA Dynamo (NIXL/EFA RDMA){N}                {C}│{N}
{C}│{N}   {D}Training:     NeMo RL GRPO on 32x H200{N}                    {C}│{N}
{C}│{N}   {D}Stack:        Curator → Train → Dynamo → NemoClaw{N}         {C}│{N}
{C}│{N}   {D}Infra:        2x P5en.48xlarge (32x H200, 32x EFA){N}       {C}│{N}
{C}│{N}                                                                {C}│{N}
{C}│{N}   {Y}The agent IS the model being trained and served{N}            {C}│{N}
{C}│{N}                                                                {C}│{N}
{C}└────────────────────────────────────────────────────────────────┘{N}
""")


def nemoclaw_say(msg):
    print(f"  {C}nemoclaw ▸{N} {msg}")


def nemoclaw_think(msg):
    print(f"  {D}            {msg}{N}")


def run(cmd, show=True):
    if show:
        print(f"  {G}    exec ▸{N} {D}{cmd}{N}")
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)
        out = r.stdout.strip()
        if show and out:
            for line in out.split("\n")[:25]:
                print(f"             {line}")
        return out
    except Exception as e:
        return f"(error: {e})"


def divider():
    print(f"\n  {C}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{N}\n")


# ── Endpoint Discovery ──

def discover_dynamo_endpoint():
    """Auto-discover Dynamo endpoint from cluster pod IPs."""
    global DYNAMO_ENDPOINT
    if DYNAMO_ENDPOINT:
        return DYNAMO_ENDPOINT

    # Try kubectl to find the frontend pod IP
    for port in [DYNAMO_PORT, "8001", "8000"]:
        try:
            result = subprocess.run(
                f"{K} get pod -n {NS} -l app=dynamo-nemotron-8gpu "
                f"--no-headers -o wide 2>/dev/null",
                shell=True, capture_output=True, text=True, timeout=10,
            )
            # If no nemotron-specific pods, try the qwen25 frontend
            if not result.stdout.strip():
                result = subprocess.run(
                    f"{K} get pod -n {NS} -l app.kubernetes.io/name=dynamo-frontend "
                    f"--no-headers -o wide 2>/dev/null",
                    shell=True, capture_output=True, text=True, timeout=10,
                )
            if not result.stdout.strip():
                # Try any pod with "frontend" in the name
                result = subprocess.run(
                    f"{K} get pods -n {NS} --no-headers 2>/dev/null",
                    shell=True, capture_output=True, text=True, timeout=10,
                )
                for line in result.stdout.strip().split("\n"):
                    if "frontend" in line and "Running" in line:
                        pod_name = line.split()[0]
                        ip_result = subprocess.run(
                            f'{K} get pod {pod_name} -n {NS} '
                            f'-o jsonpath="{{.status.podIP}}" 2>/dev/null',
                            shell=True, capture_output=True, text=True, timeout=10,
                        )
                        ip = ip_result.stdout.strip().strip('"')
                        if ip:
                            endpoint = f"http://{ip}:{port}"
                            DYNAMO_ENDPOINT = endpoint
                            return endpoint
        except Exception:
            continue

    # Last resort: try well-known node IPs from the cluster
    for ip in ["10.240.71.150", "10.240.87.215"]:
        try:
            url = f"http://{ip}:{DYNAMO_PORT}/v1/models"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    DYNAMO_ENDPOINT = f"http://{ip}:{DYNAMO_PORT}"
                    return DYNAMO_ENDPOINT
        except Exception:
            continue

    return ""


# ── Dynamo Backend ──

def call_dynamo(prompt, system_prompt=None, max_tokens=500, temperature=0.3):
    """Call Nemotron via local Dynamo OpenAI-compatible endpoint."""
    endpoint = discover_dynamo_endpoint()
    if not endpoint:
        raise ConnectionError("No Dynamo endpoint discovered")

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    body = json.dumps({
        "model": DYNAMO_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode("utf-8")

    url = f"{endpoint}/v1/chat/completions"
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())

    return result["choices"][0]["message"]["content"].strip()


def dynamo_health_check():
    """Check if Dynamo endpoint is reachable and serving the model."""
    try:
        endpoint = discover_dynamo_endpoint()
        if not endpoint:
            return False, "No Dynamo endpoint found"
        url = f"{endpoint}/v1/models"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            models = json.loads(resp.read())
        model_ids = [m.get("id", "") for m in models.get("data", [])]
        if DYNAMO_MODEL in model_ids:
            return True, f"Model {DYNAMO_MODEL} available"
        if model_ids:
            return True, f"Models available: {', '.join(model_ids)}"
        return False, "No models registered"
    except Exception as e:
        return False, str(e)


# ── Bedrock Backend ──

def call_bedrock(prompt, system_prompt=None, max_tokens=500, temperature=0.3):
    """Call Nemotron via AWS Bedrock (fallback)."""
    import boto3
    client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    body = json.dumps({
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    })
    response = client.invoke_model(
        modelId=BEDROCK_MODEL,
        contentType="application/json",
        accept="application/json",
        body=body,
    )
    result = json.loads(response["body"].read())
    return result["choices"][0]["message"]["content"].strip()


# ── Unified Call ──

SYSTEM_PROMPT = (
    "You are NemoClaw, an autonomous AI agent orchestrating a live GPU training "
    "demo at GTC 2026. You are powered by NVIDIA Nemotron-Mini-4B, the same model "
    "being trained and served in this demo. You explain each step to a technical "
    "audience. Be concise (2-3 sentences max), technical but accessible. "
    "The demo uses NeMo Curator, NeMo RL GRPO, NVRx fault tolerance, "
    "and NVIDIA Dynamo on 2x P5en.48xlarge (32x H200 GPUs, 32x EFA NICs)."
)

_active_backend = None


def ask_nemoclaw(prompt):
    """Call the model with automatic fallback."""
    global _active_backend

    # Try Dynamo first (unless forced to Bedrock)
    if BACKEND in ("dynamo", "auto"):
        try:
            text = call_dynamo(prompt, system_prompt=SYSTEM_PROMPT)
            _active_backend = "dynamo"
            sentences = text.split(". ")
            return ". ".join(sentences[:3]) + ("." if len(sentences) > 3 else "")
        except Exception as e:
            if FALLBACK == "none":
                return f"(Dynamo unavailable: {e})"
            nemoclaw_think(f"Dynamo unavailable, falling back to Bedrock...")

    # Bedrock fallback
    if BACKEND == "bedrock" or FALLBACK == "bedrock":
        try:
            text = call_bedrock(prompt, system_prompt=SYSTEM_PROMPT)
            _active_backend = "bedrock"
            sentences = text.split(". ")
            return ". ".join(sentences[:3]) + ("." if len(sentences) > 3 else "")
        except Exception as e:
            return f"(All backends failed: {e})"

    return "(No backend available)"


# ── Demo Orchestration ──

def main():
    # Determine initial backend
    if BACKEND == "bedrock":
        backend_info = f"Nemotron 30B on Bedrock ({BEDROCK_REGION})"
    else:
        nemoclaw_say("Discovering Dynamo endpoint...")
        ok, msg = dynamo_health_check()
        if ok:
            ep = DYNAMO_ENDPOINT or "(discovered)"
            backend_info = f"Nemotron-4B on Dynamo ({ep})"
            nemoclaw_say(f"Dynamo health check: {G}OK{N} — {msg}")
        elif FALLBACK == "bedrock":
            backend_info = f"Bedrock fallback (Dynamo: {msg})"
            nemoclaw_say(f"Dynamo unavailable: {msg}")
            nemoclaw_say(f"Falling back to Bedrock ({BEDROCK_MODEL})")
        else:
            backend_info = f"Dynamo (will retry each call)"
            nemoclaw_say(f"{Y}Dynamo not ready yet: {msg}{N}")
            nemoclaw_say("Will retry on each call — Bedrock fallback disabled")

    banner(backend_info)

    iteration = 0
    while True:
        iteration += 1

        # ── Intro ──
        divider()
        nemoclaw_say(f"{B}Demo iteration {iteration} — starting{N}")
        if _active_backend:
            nemoclaw_think(f"Active backend: {_active_backend}")
        print()

        intro = ask_nemoclaw(
            f"Introduce demo iteration {iteration}. "
            f"Mention you are NemoClaw, powered by the same Nemotron model "
            f"being trained and served in this demo. "
            f"Highlight the full NVIDIA AI stack on AWS."
        )
        nemoclaw_say(intro)
        print()
        time.sleep(2)

        # ── Check infrastructure ──
        divider()
        nemoclaw_say(f"{B}Checking infrastructure{N}")
        print()
        pods = run(f"{K} get pods -n {NS} --no-headers 2>/dev/null | head -12", show=True)
        commentary = ask_nemoclaw(
            f"The cluster has these pods:\n{pods}\n"
            f"Briefly describe the infrastructure status."
        )
        nemoclaw_say(commentary)
        print()
        time.sleep(2)

        # ── Step 1: Curate ──
        divider()
        nemoclaw_say(f"{B}Step 1/6: NeMo Curator — Data Curation{N}")
        commentary = ask_nemoclaw(
            "Explain NeMo Curator: generating and filtering synthetic math "
            "problems for GRPO training. 12 categories, Python-verified answers."
        )
        nemoclaw_say(commentary)
        print()
        run("cd /tmp/nemo-rl && bash scripts/gtc-demo-v6.sh 1")
        print()

        # ── Step 2: Dynamo inference ──
        divider()
        nemoclaw_say(f"{B}Step 2/6: NVIDIA Dynamo — Disaggregated Inference{N}")
        commentary = ask_nemoclaw(
            "Explain disaggregated inference: 8 prefill GPUs on node 1, "
            "8 decode GPUs on node 2. KV cache transferred via NIXL over "
            "EFA RDMA at 3.2 Tbps. Note that you (NemoClaw) are being served "
            "by this same Dynamo infrastructure."
        )
        nemoclaw_say(commentary)
        print()
        run("cd /tmp/nemo-rl && bash scripts/gtc-demo-v6.sh 2")
        print()

        # ── Step 3: Training ──
        divider()
        nemoclaw_say(f"{B}Step 3/6: NeMo RL GRPO — Training{N}")
        commentary = ask_nemoclaw(
            "Explain GRPO training: the model generates multiple solutions "
            "per math problem, scores them, and uses group relative policy "
            "optimization. Running on 32x H200 with attention-only LoRA."
        )
        nemoclaw_say(commentary)
        print()
        nemoclaw_say("Starting training — ~15 minutes to reach step 27...")
        run("cd /tmp/nemo-rl && bash scripts/gtc-demo-v6.sh 3")
        print()

        # ── Step 4: Fault injection ──
        divider()
        nemoclaw_say(f"{B}Step 4/6: NVRx — Fault Injection & Recovery{N}")
        commentary = ask_nemoclaw(
            "Explain fault injection: kill -9 at step 27, RayJob detects "
            "failure, creates new cluster, NeMo RL resumes from step 25 "
            "checkpoint on FSx. Recovery takes ~3 minutes."
        )
        nemoclaw_say(commentary)
        print()
        run("cd /tmp/nemo-rl && bash scripts/gtc-demo-v6.sh fault")
        print()

        # ── Step 5: Eval ──
        divider()
        nemoclaw_say(f"{B}Step 5/6: Evaluation{N}")
        commentary = ask_nemoclaw(
            "Explain evaluation: 200 held-out math problems tested on both "
            "base model and GRPO-trained model. Measuring accuracy improvement."
        )
        nemoclaw_say(commentary)
        print()
        run("cd /tmp/nemo-rl && bash scripts/gtc-demo-v6.sh 4")
        print()

        # ── Step 6: Results ──
        divider()
        nemoclaw_say(f"{B}Step 6/6: Results{N}")
        run("cd /tmp/nemo-rl && bash scripts/gtc-demo-v6.sh 5")
        print()

        # ── Summary ──
        divider()
        summary = ask_nemoclaw(
            f"Demo iteration {iteration} complete. Give a 3-bullet summary: "
            f"data curation, training with fault recovery, and inference. "
            f"Mention you (NemoClaw) are powered by the same trained model."
        )
        nemoclaw_say(f"{B}Summary:{N}")
        nemoclaw_say(summary)
        print()

        # Show which backend was used
        if _active_backend == "dynamo":
            nemoclaw_say(
                f"{G}This commentary was generated by Nemotron on Dynamo "
                f"(local cluster, EFA RDMA){N}"
            )
        elif _active_backend == "bedrock":
            nemoclaw_say(
                f"{D}Commentary via Bedrock fallback "
                f"(Dynamo GPUs occupied by training){N}"
            )

        nemoclaw_say(f"Iteration {iteration} complete. Next run in 5 minutes.")
        print(f"  {D}(Press Ctrl+C to stop){N}")
        time.sleep(300)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n  {C}nemoclaw ▸{N} Demo stopped by operator.")
