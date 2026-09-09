"""
AI provider client (section 19: "Use the configured Gemma Flash Lite
model/provider available for the project").

This is the ONLY function in the AI module that performs network I/O. Every
other function is pure/DB-only, which is what makes them testable without a
live provider — tests substitute this function's behavior directly rather
than mocking HTTP at a lower layer.
"""
from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.exceptions import AppError


class AIProviderError(AppError):
    """Network failure, timeout, or non-2xx response from the AI provider."""

    code = "AI_PROVIDER_ERROR"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message, code=code or self.code, status_code=502)


def call_ai_provider(prompt: str, *, timeout_seconds: float = 15.0) -> str:
    """
    Sends `prompt` to the configured provider and returns the raw text
    response. Raises AIProviderError on timeout, connection failure, or a
    non-2xx status — callers must not assume this always succeeds (section 37).
    """
    if not settings.AI_API_KEY:
        raise AIProviderError("AI provider is not configured (missing AI_API_KEY).", code="AI_NOT_CONFIGURED")

    try:
        response = httpx.post(
            f"{settings.AI_PROVIDER_BASE_URL.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.AI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": settings.AI_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
            },
            timeout=timeout_seconds,
        )
    except httpx.TimeoutException as exc:
        raise AIProviderError("AI provider request timed out.", code="AI_TIMEOUT") from exc
    except httpx.RequestError as exc:
        raise AIProviderError(f"AI provider request failed: {exc}", code="AI_REQUEST_FAILED") from exc

    if response.status_code >= 400:
        raise AIProviderError(
            f"AI provider returned HTTP {response.status_code}.", code="AI_PROVIDER_HTTP_ERROR"
        )

    try:
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AIProviderError(
            "AI provider response was not in the expected shape.", code="AI_UNEXPECTED_RESPONSE_SHAPE"
        ) from exc
