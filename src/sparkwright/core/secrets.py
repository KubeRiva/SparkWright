"""Mask secrets before text leaves the machine or lands in a log (S11.3, D008)."""
from __future__ import annotations

import os
import re

MASK = "[REDACTED]"

TOKEN_PATTERNS = [
    r"sk-ant-[A-Za-z0-9_\-]{16,}",          # Anthropic
    r"\bsk-(proj-)?[A-Za-z0-9_\-]{20,}",     # OpenAI-style
    r"\bgh[pousr]_[A-Za-z0-9]{30,}",         # GitHub tokens
    r"\bgithub_pat_[A-Za-z0-9_]{40,}",
    r"\bAKIA[0-9A-Z]{16}\b",                 # AWS access key id
    r"\bxox[abprs]-[A-Za-z0-9\-]{10,}",      # Slack
    r"\bAIza[0-9A-Za-z_\-]{35}\b",           # Google API key
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
]
_TOKEN_RE = re.compile("|".join(f"(?:{p})" for p in TOKEN_PATTERNS), re.S)


def _env_values() -> list[str]:
    from ..runner.verify import SECRET_RE  # same notion of "secret-looking" as the sandbox (S6.10)
    vals = {v for k, v in os.environ.items() if SECRET_RE.search(k) and v and len(v) >= 8}
    return sorted(vals, key=len, reverse=True)


def redact(text: str) -> str:
    """Replace known token shapes and the values of secret-looking environment variables with [REDACTED]."""
    if not text:
        return text
    for v in _env_values():
        if v in text:
            text = text.replace(v, MASK)
    return _TOKEN_RE.sub(MASK, text)


_HIDDEN = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff\U000e0000-\U000e007f]")


def model_text(text: str) -> str:
    """D009 (S4.6, S11.3): text written by a model into specs/ loses hidden characters and secrets; it is quoted
    data when a later agent reads it, and the review scan still checks it like any other spec text."""
    return redact(_HIDDEN.sub("", str(text or "")))
