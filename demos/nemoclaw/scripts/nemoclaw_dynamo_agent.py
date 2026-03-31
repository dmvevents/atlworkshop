#!/usr/bin/env python3
"""NemoClaw Agent — Powered by NVIDIA Dynamo on EKS.

Adapted for Qwen2.5-Coder-7B-Instruct served by NVIDIA Dynamo on the
workshop EKS cluster. The agent calls the local Dynamo OpenAI-compatible
endpoint for commentary and orchestration.

This demonstrates the full loop:
  1. Serve the model with NVIDIA Dynamo (disaggregated inference)
  2. The served model powers the AI agent that narrates the demo
  3. Auto-discovers Dynamo endpoints on EKS via kubectl or service DNS

Architecture:
  Agent Brain:  Qwen2.5-Coder-7B-Instruct on NVIDIA Dynamo
  Serving:      Dynamo frontend + worker pods (workshop namespace)
  Infra:        Amazon EKS with GPU nodes

Fallback:
  If the Dynamo endpoint is unavailable (e.g., during training when GPUs
  are occupied), the agent falls back to AWS Bedrock automatically.

Usage:
  # Dynamo-only (requires Dynamo pods running in workshop namespace)
  python3 nemoclaw_dynamo_agent.py

  # With Bedrock fallback
  NEMOCLAW_FALLBACK=bedrock python3 nemoclaw_dynamo_agent.py

  # Force Bedrock (skip Dynamo)
  NEMOCLAW_BACKEND=bedrock python3 nemoclaw_dynamo_agent.py

  # Custom Dynamo endpoint (e.g., via port-forward)
  DYNAMO_ENDPOINT=http://localhost:8084 python3 nemoclaw_dynamo_agent.py

  # Single iteration (no loop)
  NEMOCLAW_SINGLE=1 python3 nemoclaw_dynamo_agent.py
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error

# -- Config --
NS = os.environ.get("NEMOCLAW_NAMESPACE", "workshop")
K = os.environ.get("KUBECTL", "kubectl")

# Dynamo endpoint (auto-discovered or manual)
DYNAMO_ENDPOINT = os.environ.get("DYNAMO_ENDPOINT", "")  # auto-discover if empty
DYNAMO_MODEL = os.environ.get(
    "DYNAMO_MODEL",
    "Qwen/Qwen2.5-Coder-7B-Instruct"
)
DYNAMO_PORT = os.environ.get("DYNAMO_PORT", "8000")

# Bedrock fallback
BEDROCK_REGION = os.environ.get("AWS_REGION", "us-east-1")
BEDROCK_MODEL = os.environ.get("BEDROCK_MODEL", "anthropic.claude-3-haiku-20240307-v1:0")

# Backend selection
BACKEND = os.environ.get("NEMOCLAW_BACKEND", "dynamo")  # dynamo | bedrock | auto
FALLBACK = os.environ.get("NEMOCLAW_FALLBACK", "none")  # bedrock | none

# Single iteration mode (for testing)
SINGLE_MODE = os.environ.get("NEMOCLAW_SINGLE", "").strip() in ("1", "true", "yes")

# ANSI colors
C, G, Y, R, B, N, D = (
    "\033[0;36m", "\033[0;32m", "\033[1;33m",
    "\033[0;31m", "\033[1m", "\033[0m", "\033[2m",
)


def banner(backend_info):
    print(f"""
{C}+-----------------------------------------------------------------+{N}
{C}|{N}                                                                 {C}|{N}
{C}|{N}   {B}NemoClaw -- AI Agent on NVIDIA Dynamo{N}                        {C}|{N}
{C}|{N}   {B}Self-referential inference loop{N}                              {C}|{N}
{C}|{N}                                                                 {C}|{N}
{C}|{N}   {D}Agent Brain:  {backend_info:<45}{N} {C}|{N}
{C}|{N}   {D}Model:        {DYNAMO_MODEL:<45}{N} {C}|{N}
{C}|{N}   {D}Inference:    NVIDIA Dynamo (OpenAI-compatible API){N}          {C}|{N}
{C}|{N}   {D}Namespace:    {NS:<45}{N} {C}|{N}
{C}|{N}                                                                 {C}|{N}
{C}|{N}   {Y}The agent calls the model it narrates about{N}                 {C}|{N}
{C}|{N}                                                                 {C}|{N}
{C}+-----------------------------------------------------------------+{N}
""")


def nemoclaw_say(msg):
    print(f"  {C}nemoclaw >{N} {msg}")


def nemoclaw_think(msg):
    print(f"  {D}            {msg}{N}")


def run(cmd, show=True):
    if show:
        print(f"  {G}    exec >{N} {D}{cmd}{N}")
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
    print(f"\n  {C}------------------------------------------------------{N}\n")


# -- Endpoint Discovery --

def discover_dynamo_endpoint():
    """Auto-discover Dynamo endpoint from cluster service or pod IPs."""
    global DYNAMO_ENDPOINT
    if DYNAMO_ENDPOINT:
        return DYNAMO_ENDPOINT

    # Strategy 1: Try the well-known Kubernetes service DNS name
    svc_url = f"http://qwen-coder-frontend.{NS}.svc.cluster.local:{DYNAMO_PORT}"
    try:
        req = urllib.request.Request(f"{svc_url}/v1/models", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                DYNAMO_ENDPOINT = svc_url
                return DYNAMO_ENDPOINT
    except Exception:
        pass

    # Strategy 2: Try kubectl to find the ClusterIP of the frontend service
    for svc_name in ["qwen-coder-frontend", "dynamo-frontend"]:
        try:
            result = subprocess.run(
                f"{K} get svc {svc_name} -n {NS} -o jsonpath='{{.spec.clusterIP}}' 2>/dev/null",
                shell=True, capture_output=True, text=True, timeout=10,
            )
            ip = result.stdout.strip().strip("'")
            if ip and ip != "None":
                endpoint = f"http://{ip}:{DYNAMO_PORT}"
                try:
                    req = urllib.request.Request(f"{endpoint}/v1/models", method="GET")
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        if resp.status == 200:
                            DYNAMO_ENDPOINT = endpoint
                            return DYNAMO_ENDPOINT
                except Exception:
                    continue
        except Exception:
            continue

    # Strategy 3: kubectl get pods and find frontend pod IP
    try:
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
                    endpoint = f"http://{ip}:{DYNAMO_PORT}"
                    DYNAMO_ENDPOINT = endpoint
                    return endpoint
    except Exception:
        pass

    # Strategy 4: Try localhost (for port-forward scenarios)
    for port in ["8084", "8000", "8001"]:
        try:
            url = f"http://localhost:{port}/v1/models"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    DYNAMO_ENDPOINT = f"http://localhost:{port}"
                    return DYNAMO_ENDPOINT
        except Exception:
            continue

    return ""


# -- Dynamo Backend --

def call_dynamo(prompt, system_prompt=None, max_tokens=500, temperature=0.3):
    """Call model via local Dynamo OpenAI-compatible endpoint."""
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
    with urllib.request.urlopen(req, timeout=60) as resp:
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


# -- Bedrock Backend --

def call_bedrock(prompt, system_prompt=None, max_tokens=500, temperature=0.3):
    """Call model via AWS Bedrock (fallback)."""
    import boto3
    client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)

    messages = [{"role": "user", "content": [{"text": prompt}]}]
    system = []
    if system_prompt:
        system = [{"text": system_prompt}]

    response = client.converse(
        modelId=BEDROCK_MODEL,
        messages=messages,
        system=system,
        inferenceConfig={
            "maxTokens": max_tokens,
            "temperature": temperature,
        },
    )
    return response["output"]["message"]["content"][0]["text"].strip()


# -- Unified Call --

SYSTEM_PROMPT = (
    "You are NemoClaw, an autonomous AI agent running on NVIDIA Dynamo. "
    "You are powered by Qwen2.5-Coder-7B-Instruct, served via Dynamo's "
    "OpenAI-compatible API on an Amazon EKS cluster. "
    "You explain each step of a GPU training and inference demo to a "
    "technical audience. Be concise (2-3 sentences max), technical but "
    "accessible. The demo uses NVIDIA Dynamo for disaggregated inference "
    "on AWS GPU instances with EFA networking."
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


# -- Demo Orchestration --

def run_demo_step(step_name, prompt, cmd=None):
    """Run a single demo step: get AI commentary, optionally execute command."""
    divider()
    nemoclaw_say(f"{B}{step_name}{N}")
    commentary = ask_nemoclaw(prompt)
    nemoclaw_say(commentary)
    print()
    if cmd:
        run(cmd)
        print()


def main():
    # Determine initial backend
    if BACKEND == "bedrock":
        backend_info = f"Bedrock ({BEDROCK_MODEL})"
    else:
        nemoclaw_say("Discovering Dynamo endpoint...")
        ok, msg = dynamo_health_check()
        if ok:
            ep = DYNAMO_ENDPOINT or "(discovered)"
            backend_info = f"Qwen-Coder-7B on Dynamo ({ep})"
            nemoclaw_say(f"Dynamo health check: {G}OK{N} -- {msg}")
        elif FALLBACK == "bedrock":
            backend_info = f"Bedrock fallback (Dynamo: {msg})"
            nemoclaw_say(f"Dynamo unavailable: {msg}")
            nemoclaw_say(f"Falling back to Bedrock ({BEDROCK_MODEL})")
        else:
            backend_info = f"Dynamo (will retry each call)"
            nemoclaw_say(f"{Y}Dynamo not ready yet: {msg}{N}")
            nemoclaw_say("Will retry on each call -- Bedrock fallback disabled")

    banner(backend_info)

    iteration = 0
    while True:
        iteration += 1

        # -- Intro --
        divider()
        nemoclaw_say(f"{B}Demo iteration {iteration} -- starting{N}")
        if _active_backend:
            nemoclaw_think(f"Active backend: {_active_backend}")
        print()

        intro = ask_nemoclaw(
            f"Introduce demo iteration {iteration}. "
            f"Mention you are NemoClaw, an AI agent powered by "
            f"Qwen2.5-Coder-7B-Instruct served via NVIDIA Dynamo. "
            f"This is a self-referential loop: you are the model narrating "
            f"about the model serving infrastructure."
        )
        nemoclaw_say(intro)
        print()
        time.sleep(2)

        # -- Check infrastructure --
        divider()
        nemoclaw_say(f"{B}Checking infrastructure{N}")
        print()
        pods = run(f"{K} get pods -n {NS} --no-headers 2>/dev/null | head -12", show=True)
        svcs = run(f"{K} get svc -n {NS} --no-headers 2>/dev/null | head -6", show=True)
        commentary = ask_nemoclaw(
            f"The cluster has these pods:\n{pods}\n\n"
            f"Services:\n{svcs}\n\n"
            f"Briefly describe the infrastructure status. "
            f"Note the Dynamo frontend and worker pods."
        )
        nemoclaw_say(commentary)
        print()
        time.sleep(2)

        # -- Step 1: Model info --
        run_demo_step(
            "Step 1/5: Model Discovery",
            "Explain what model auto-discovery means in the Dynamo context: "
            "the agent queries /v1/models to find what models are available, "
            "and uses that to configure itself. No hardcoded IPs needed.",
            f"curl -s {DYNAMO_ENDPOINT}/v1/models 2>/dev/null | python3 -m json.tool"
        )
        time.sleep(1)

        # -- Step 2: Inference test --
        run_demo_step(
            "Step 2/5: Live Inference Test",
            "Explain that you are about to call yourself -- the agent is "
            "calling the same model that generates its own narration. "
            "This demonstrates the self-referential nature of NemoClaw.",
        )
        # Do a live inference call and show it
        nemoclaw_say("Calling Dynamo endpoint for a coding question...")
        start = time.time()
        response = ask_nemoclaw(
            "Write a Python one-liner to compute the fibonacci sequence "
            "up to N=10. Show just the code."
        )
        elapsed = time.time() - start
        nemoclaw_say(f"Response ({elapsed:.2f}s):")
        nemoclaw_say(response)
        print()
        time.sleep(1)

        # -- Step 3: Latency benchmark --
        divider()
        nemoclaw_say(f"{B}Step 3/5: Latency Measurement{N}")
        nemoclaw_say("Running 3 inference calls to measure response latency...")
        print()
        latencies = []
        for i in range(3):
            start = time.time()
            resp = ask_nemoclaw(f"Test call {i+1}: What is {i+1} * {i+7}? Answer with just the number.")
            elapsed = time.time() - start
            latencies.append(elapsed)
            nemoclaw_say(f"  Call {i+1}: {elapsed:.2f}s -- {resp[:80]}")
        avg_latency = sum(latencies) / len(latencies)
        nemoclaw_say(f"Average latency: {avg_latency:.2f}s")
        print()
        time.sleep(1)

        # -- Step 4: Code generation --
        run_demo_step(
            "Step 4/5: Code Generation Demo",
            "Explain that Qwen2.5-Coder-7B-Instruct excels at code generation. "
            "The agent will ask the model to generate a useful code snippet.",
        )
        code_response = ask_nemoclaw(
            "Write a concise Python function that checks if a Kubernetes pod "
            "is in Running state using kubectl. Include error handling. "
            "Show only the code, no explanation."
        )
        nemoclaw_say("Generated code:")
        nemoclaw_say(code_response)
        print()
        time.sleep(1)

        # -- Step 5: Self-reflection --
        run_demo_step(
            "Step 5/5: Self-Reflection",
            f"Reflect on this demo iteration. You are NemoClaw -- an AI agent "
            f"powered by Qwen2.5-Coder-7B-Instruct on NVIDIA Dynamo. "
            f"You just used yourself to narrate a demo about yourself. "
            f"Average inference latency was {avg_latency:.2f}s. "
            f"Give a brief technical summary of what was demonstrated.",
        )

        # -- Summary --
        divider()
        summary = ask_nemoclaw(
            f"Demo iteration {iteration} complete. Give a 3-bullet summary: "
            f"1) Self-referential inference (agent powered by the model it demos), "
            f"2) Dynamo serving performance ({avg_latency:.2f}s avg latency), "
            f"3) Code generation capability of Qwen2.5-Coder-7B."
        )
        nemoclaw_say(f"{B}Summary:{N}")
        nemoclaw_say(summary)
        print()

        # Show which backend was used
        if _active_backend == "dynamo":
            nemoclaw_say(
                f"{G}All commentary generated by Qwen-Coder-7B on Dynamo "
                f"(local cluster){N}"
            )
        elif _active_backend == "bedrock":
            nemoclaw_say(
                f"{D}Commentary via Bedrock fallback "
                f"(Dynamo GPUs occupied){N}"
            )

        if SINGLE_MODE:
            nemoclaw_say(f"Single iteration mode -- done.")
            break

        nemoclaw_say(f"Iteration {iteration} complete. Next run in 60 seconds.")
        print(f"  {D}(Press Ctrl+C to stop){N}")
        time.sleep(60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n  {C}nemoclaw >{N} Demo stopped by operator.")
