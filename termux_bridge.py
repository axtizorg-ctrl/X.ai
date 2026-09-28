"""Talks to Qwen served by Ollama inside Termux (127.0.0.1 only - traffic never leaves the phone)."""
import json, os, urllib.request

API_URL = os.environ.get("X_QWEN_URL", "http://127.0.0.1:11434")
MODEL = os.environ.get("X_QWEN_MODEL", "qwen2.5-coder:1.5b")


def status():
    try:
        with urllib.request.urlopen(API_URL + "/api/tags", timeout=4) as r:
            names = [m["name"] for m in json.load(r).get("models", [])]
    except Exception as e:
        return False, f"Qwen server not reachable ({e}). In Termux run: ollama serve"
    if MODEL not in names:
        return False, f"Server is up but model missing. In Termux run: ollama pull {MODEL}"
    return True, f"Termux bridge ready ({MODEL})"


def chat(messages, model=None, timeout=600):
    body = json.dumps({"model": model or MODEL, "messages": messages, "stream": False,
                       "options": {"temperature": 0.1, "num_ctx": 8192}}).encode()
    req = urllib.request.Request(API_URL + "/api/chat", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)["message"]["content"]
