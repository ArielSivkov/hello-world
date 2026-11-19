"""Thin client for any OpenAI-compatible local server (llama.cpp, Ollama, LM Studio)."""
import os
import requests

BASE_URL = os.environ.get("ION_BASE_URL", "http://localhost:8080/v1")
MODEL = os.environ.get("ION_MODEL", "local")


def chat(messages, max_tokens=200, temperature=0.0):
    r = requests.post(
        f"{BASE_URL}/chat/completions",
        json={"model": MODEL, "messages": messages, "max_tokens": max_tokens,
              "temperature": temperature, "seed": 0},
        timeout=600,
    )
    if r.status_code != 200:
        raise RuntimeError(f"llm {r.status_code}: {r.text[:300]}")
    return r.json()["choices"][0]["message"]["content"].strip()
