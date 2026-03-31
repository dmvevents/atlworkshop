#!/usr/bin/env python3
"""Proxy that translates OpenAI Responses API -> Chat Completions for vLLM.

OpenCode v1.3.10 uses the /v1/responses endpoint (OpenAI Responses API),
which vLLM doesn't support. This proxy translates requests on the fly.

Usage:
    # Start vLLM port-forward on 8000
    kubectl port-forward -n workshop svc/qwen-coder-frontend 8000:8000 &

    # Start this proxy on 8001
    python3 opencode-proxy.py &

    # Point OpenCode at the proxy
    OPENAI_API_KEY=x OPENAI_BASE_URL=http://localhost:8001/v1 opencode -m openai/gpt-4o
"""
import json, http.server, urllib.request, uuid, time

TARGET = "http://localhost:8000"
MODEL = "gpt-4o"

class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        try:
            data = json.loads(body)
        except:
            data = {}
        
        data['model'] = MODEL
        
        if '/v1/responses' in self.path:
            print(f">>> /v1/responses -> /v1/chat/completions | tools={len(data.get('tools',[]))}", flush=True)
            inp = data.get('input', '')
            messages = []
            if data.get('instructions'):
                # Truncate system instructions to fit within context window
                # OpenCode sends ~30K tokens of tool descriptions in instructions
                instr = str(data['instructions'])[:3000]
                messages.append({"role": "system", "content": instr})
            if isinstance(inp, str):
                messages.append({"role": "user", "content": inp})
            elif isinstance(inp, list):
                for item in inp:
                    if isinstance(item, dict):
                        role = item.get('role', 'user')
                        content = item.get('content', '')
                        # Flatten array content to string (vLLM doesn't accept array content)
                        if isinstance(content, list):
                            parts = []
                            for c in content:
                                if isinstance(c, dict):
                                    parts.append(c.get('text', c.get('input_text', str(c))))
                                else:
                                    parts.append(str(c))
                            content = '\n'.join(parts)
                        messages.append({"role": role, "content": str(content)})
                    else:
                        messages.append({"role": "user", "content": str(item)})
            
            # Cap total message size to fit in 8192 context window
            # Reserve 2048 for output, budget 6000 for input (~4 chars/token)
            MAX_INPUT_CHARS = 20000
            total = 0
            capped_messages = []
            for m in messages:
                content = m.get('content', '')
                if total + len(content) > MAX_INPUT_CHARS:
                    remaining = MAX_INPUT_CHARS - total
                    if remaining > 200:
                        capped_messages.append({"role": m['role'], "content": content[:remaining] + "\n[truncated]"})
                    break
                capped_messages.append(m)
                total += len(content)

            chat_req = {"model": MODEL, "messages": capped_messages,
                       "max_tokens": min(data.get('max_output_tokens', 2048), 2048),
                       "temperature": data.get('temperature', 0.7)}
            
            # Skip tools entirely -- they add ~50K tokens to the prompt which
            # exceeds the 8192 max_model_len. The 7B model doesn't reliably
            # use tools anyway. OpenCode will still work for code generation.
            # To re-enable: increase --max-model-len to 32768+ on the worker.
            
            try:
                req = urllib.request.Request(f"{TARGET}/v1/chat/completions",
                    data=json.dumps(chat_req).encode(),
                    headers={"Content-Type": "application/json"}, method='POST')
                with urllib.request.urlopen(req, timeout=120) as resp:
                    cr = json.loads(resp.read())
                msg = cr.get('choices', [{}])[0].get('message', {})
                out = {"id": f"resp_{uuid.uuid4().hex[:24]}", "object": "response",
                       "created_at": int(time.time()), "status": "completed",
                       "model": data.get('model', MODEL),
                       "output": [{"type": "message", "id": f"msg_{uuid.uuid4().hex[:24]}",
                                   "status": "completed", "role": "assistant",
                                   "content": [{"type": "output_text", "text": msg.get('content', ''), "annotations": []}]}],
                       "usage": cr.get('usage', {}), "text": {"format": {"type": "text"}}}
                rb = json.dumps(out).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(rb)))
                self.end_headers()
                self.wfile.write(rb)
                print(f"    <<< OK: {msg.get('content','')[:80]}", flush=True)
            except urllib.error.HTTPError as e:
                err_body = e.read().decode()[:500]
                print(f"    <<< HTTP {e.code}: {err_body}", flush=True)
                # Return a fake success so OpenCode doesn't retry forever
                fake = {"id": f"resp_{uuid.uuid4().hex[:24]}", "object": "response",
                    "created_at": int(time.time()), "status": "completed", "model": MODEL,
                    "output": [{"type": "message", "id": f"msg_{uuid.uuid4().hex[:24]}",
                        "status": "completed", "role": "assistant",
                        "content": [{"type": "output_text", "text": f"[proxy error: {err_body[:100]}]", "annotations": []}]}],
                    "usage": {}, "text": {"format": {"type": "text"}}}
                rb = json.dumps(fake).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(rb)))
                self.end_headers()
                self.wfile.write(rb)
            except Exception as e:
                print(f"    <<< ERR: {e}", flush=True)
                self.send_response(502)
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return
        
        # Pass-through for /v1/chat/completions (strip strict)
        for t in data.get('tools', []):
            t.get('function', {}).pop('strict', None)
            t.get('function', {}).get('parameters', {}).pop('strict', None)
        body = json.dumps(data).encode()
        try:
            req = urllib.request.Request(f"{TARGET}{self.path}", data=body,
                headers={"Content-Type": "application/json"}, method='POST')
            with urllib.request.urlopen(req, timeout=120) as resp:
                rb = resp.read()
                self.send_response(resp.status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(rb)))
                self.end_headers()
                self.wfile.write(rb)
        except Exception as e:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())
    
    def do_GET(self):
        try:
            with urllib.request.urlopen(f"{TARGET}{self.path}") as resp:
                rb = resp.read()
                self.send_response(resp.status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(rb)))
                self.end_headers()
                self.wfile.write(rb)
        except Exception as e:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(str(e).encode())
    
    def log_message(self, *a): pass

if __name__ == '__main__':
    print("OpenCode Proxy :8001 -> vLLM :8000")
    print("  Translates /v1/responses -> /v1/chat/completions")
    print("  Strips 'strict' from tool definitions")
    http.server.HTTPServer(('127.0.0.1', 8001), Handler).serve_forever()
