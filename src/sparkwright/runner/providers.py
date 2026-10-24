"""Provider-neutral model access (SYSTEM 'Model provider interface', S4.3, S11.3).

No provider SDK is required: calls use the standard library's urllib.
API keys come from environment variables only.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field


class ProviderError(RuntimeError):
    pass


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class Message:
    role: str  # system | user | assistant
    content: str


class Provider:
    name = "base"

    def complete(self, messages: list[Message], model: str, max_tokens: int = 4000) -> tuple[str, Usage]:
        raise NotImplementedError


def _post(url: str, headers: dict, payload: dict, timeout: int = 300) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"content-type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise ProviderError(f"HTTP {exc.code} from {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise ProviderError(f"cannot reach {url}: {exc.reason}") from exc


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, api_key_env: str = "ANTHROPIC_API_KEY", base_url: str = "https://api.anthropic.com"):
        self.api_key_env, self.base_url = api_key_env, base_url.rstrip("/")

    def complete(self, messages, model, max_tokens=4000):
        key = os.environ.get(self.api_key_env)
        if not key:
            raise ProviderError(f"environment variable {self.api_key_env} is not set")
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        convo = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        payload = {"model": model, "max_tokens": max_tokens, "messages": convo}
        if system:
            payload["system"] = system
        out = _post(f"{self.base_url}/v1/messages", {"x-api-key": key, "anthropic-version": "2023-06-01"}, payload)
        text = "".join(b.get("text", "") for b in out.get("content", []) if b.get("type") == "text")
        u = out.get("usage", {})
        return text, Usage(u.get("input_tokens", 0), u.get("output_tokens", 0))


class OpenAICompatibleProvider(Provider):
    """Any server implementing POST {base_url}/chat/completions (OpenAI, many hosted and local servers)."""

    name = "openai-compatible"

    def __init__(self, base_url: str = "https://api.openai.com/v1", api_key_env: str = "OPENAI_API_KEY"):
        self.base_url, self.api_key_env = base_url.rstrip("/"), api_key_env

    def complete(self, messages, model, max_tokens=4000):
        key = os.environ.get(self.api_key_env, "")
        headers = {"authorization": f"Bearer {key}"} if key else {}
        payload = {"model": model, "max_tokens": max_tokens,
                   "messages": [{"role": m.role, "content": m.content} for m in messages]}
        out = _post(f"{self.base_url}/chat/completions", headers, payload)
        try:
            text = out["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"unexpected response shape: {str(out)[:300]}") from exc
        u = out.get("usage", {}) or {}
        return text, Usage(u.get("prompt_tokens", 0), u.get("completion_tokens", 0))


@dataclass
class FakeProvider(Provider):
    """Deterministic provider for tests and dry runs.

    `script` maps a persona name (found in the system prompt's first line
    `persona: <name>`) to a list of responses returned in order; `default` is
    used when nothing matches.
    """

    script: dict[str, list[str]] = field(default_factory=dict)
    default: str = "[]"
    calls: list[tuple[str, str]] = field(default_factory=list)  # (persona, model)
    fail_times: dict[str, int] = field(default_factory=dict)
    name: str = "fake"

    def complete(self, messages, model, max_tokens=4000):
        system = next((m.content for m in messages if m.role == "system"), "")
        persona = ""
        for line in system.splitlines():
            if line.startswith("persona:"):
                persona = line.split(":", 1)[1].strip()
                break
        self.calls.append((persona, model))
        if self.fail_times.get(persona, 0) > 0:
            self.fail_times[persona] -= 1
            raise ProviderError(f"scripted failure for {persona}")
        queue = self.script.get(persona)
        text = queue.pop(0) if queue else self.default
        words = sum(len(m.content.split()) for m in messages)
        return text, Usage(words, len(text.split()))


def make(spec: dict) -> Provider:
    """Build a provider from a config entry like {provider: anthropic, model: ...}."""
    kind = spec.get("provider")
    if kind == "anthropic":
        return AnthropicProvider(spec.get("api_key_env", "ANTHROPIC_API_KEY"), spec.get("base_url", "https://api.anthropic.com"))
    if kind == "openai-compatible":
        return OpenAICompatibleProvider(spec.get("base_url", "https://api.openai.com/v1"), spec.get("api_key_env", "OPENAI_API_KEY"))
    if kind == "fake":
        return FakeProvider()
    raise ProviderError(f"unknown provider '{kind}' (expected anthropic, openai-compatible or fake)")
