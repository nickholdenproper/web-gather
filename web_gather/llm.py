"""Free LLM client - the optional "smart part" of web-gather.

Two providers, both free:
  * Ollama Cloud - when ``OLLAMA_API_KEY`` is set (OpenAI-compatible or native).
  * Local Ollama - when no key is set (http://localhost:11434).
Config comes from the environment (see .env.example). Mirrors the cloud/local
client pattern used across the rest of the toolkit so config feels identical.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

LOCAL_BASE_URL = "http://localhost:11434"
CLOUD_BASE_URL = "https://ollama.com"
DEFAULT_LOCAL_MODEL = "llama3.2"
DEFAULT_CLOUD_MODEL = "gpt-oss:20b-cloud"


class LLMError(RuntimeError):
    """Raised when the model cannot be reached or answers badly."""


@dataclass
class LLMClient:
    base_url: str
    model: str
    api_key: Optional[str] = None

    @property
    def is_cloud(self) -> bool:
        return self.base_url.startswith("https://")

    def complete(self, messages: list[dict], timeout: float = 180.0) -> str:
        """Send a chat request and return the assistant's text reply."""
        if self.is_cloud:
            resp = requests.post(
                f"{self.base_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "messages": messages, "stream": False},
                timeout=timeout,
            )
            if resp.status_code == 401:
                raise LLMError("Ollama cloud rejected the API key. Check OLLAMA_API_KEY.")
            if resp.status_code != 200:
                raise LLMError(f"Ollama cloud error {resp.status_code}: {resp.text[:300]}")
            return resp.json()["choices"][0]["message"]["content"]

        resp = requests.post(
            f"{self.base_url}/api/chat",
            json={"model": self.model, "messages": messages, "stream": False},
            timeout=timeout,
        )
        if resp.status_code == 404 and "no such model" in resp.text:
            raise LLMError(
                f"Local Ollama model '{self.model}' is not pulled. Run: ollama pull {self.model}"
            )
        if resp.status_code != 200:
            raise LLMError(f"Local Ollama error {resp.status_code}: {resp.text[:300]}")
        return resp.json()["message"]["content"]

    def complete_vision(self, messages: list[dict], images: list[str], timeout: float = 240.0) -> str:
        """Vision request via the native /api/chat endpoint (reliable for images)."""
        encoded = [
            base64.b64encode(Path(path).read_bytes()).decode() for path in images
        ]
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": messages[-1]["content"], "images": encoded}],
            "stream": False,
        }
        url = f"{self.base_url}/api/chat"
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.is_cloud else {}
        if self.is_cloud and not self.api_key:
            raise LLMError("OLLAMA_API_KEY is required for cloud vision requests.")
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        if resp.status_code == 401:
            raise LLMError("Ollama cloud rejected the API key. Check OLLAMA_API_KEY.")
        if resp.status_code != 200:
            raise LLMError(f"Ollama error {resp.status_code}: {resp.text[:300]}")
        return resp.json()["message"]["content"]


def resolve_client(provider: str = "auto") -> LLMClient:
    """Build a client: cloud when ``OLLAMA_API_KEY`` is set, local otherwise."""
    api_key = os.getenv("OLLAMA_API_KEY")
    cloud_kwargs = {
        "base_url": os.getenv("OLLAMA_BASE_URL", CLOUD_BASE_URL),
        "model": os.getenv("OLLAMA_MODEL", DEFAULT_CLOUD_MODEL),
        "api_key": api_key,
    }
    local_kwargs = {
        "base_url": os.getenv("OLLAMA_BASE_URL", LOCAL_BASE_URL),
        "model": os.getenv("OLLAMA_MODEL", DEFAULT_LOCAL_MODEL),
    }
    if provider == "cloud":
        return LLMClient(**cloud_kwargs)
    if provider == "local":
        return LLMClient(**local_kwargs)
    return LLMClient(**cloud_kwargs) if api_key else LLMClient(**local_kwargs)


def local_available() -> bool:
    """True when a local Ollama server is reachable (used for auto-live checks)."""
    try:
        return requests.get(f"{os.getenv('OLLAMA_BASE_URL', LOCAL_BASE_URL)}/", timeout=2).ok
    except Exception:  # noqa: BLE001
        return False