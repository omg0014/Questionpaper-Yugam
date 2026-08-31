"""Multi-provider LLM abstraction with automatic failover.

Chains free-tier providers so the app keeps working when any one rate-limits:
  Gemini  ->  Groq  ->  Yugam AI gateway  ->  OpenRouter (free models)

Each provider implements:
  - generate(prompt) -> str            (one-shot)
  - stream(prompt)   -> Iterator[str]  (token chunks)

`generate_with_fallback()` tries each registered provider in order, with
exponential-backoff retries on transient errors (429/5xx/timeout).
"""

from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Iterator, Optional

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)


class ProviderError(Exception):
    """Raised when a provider fails after retries."""


class TransientError(ProviderError):
    """Recoverable error (429, 5xx, timeout) — retry inside the provider."""


class FatalError(ProviderError):
    """Non-recoverable error (401 invalid key, 400 bad prompt) — skip to next."""


_RETRY = dict(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(TransientError),
    reraise=True,
)


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def generate(self, prompt: str) -> str: ...

    def stream(self, prompt: str) -> Iterator[str]:
        """Default: yield the full response as one chunk. Override for true streaming."""
        yield self.generate(prompt)


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-2.5-flash"):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        self.model = model
        self._client = None
        if self.api_key:
            try:
                from google import genai  # new SDK
                self._client = genai.Client(api_key=self.api_key)
            except Exception as e:
                log.warning("Gemini new SDK init failed (%s); will try legacy SDK", e)
                self._client = None

    def is_available(self) -> bool:
        return bool(self.api_key)

    @retry(**_RETRY)
    def _call(self, prompt: str) -> str:
        if not self._client:
            # Legacy SDK fallback
            import google.generativeai as legacy_genai
            legacy_genai.configure(api_key=self.api_key)
            try:
                model = legacy_genai.GenerativeModel(self.model)
                resp = model.generate_content(prompt)
                return (resp.text or "").strip()
            except Exception as e:
                raise self._classify(e)
        try:
            resp = self._client.models.generate_content(model=self.model, contents=prompt)
            return (resp.text or "").strip()
        except Exception as e:
            raise self._classify(e)

    def generate(self, prompt: str) -> str:
        return self._call(prompt)

    def stream(self, prompt: str) -> Iterator[str]:
        if not self._client:
            yield self.generate(prompt)
            return
        try:
            stream = self._client.models.generate_content_stream(
                model=self.model, contents=prompt
            )
            for chunk in stream:
                txt = getattr(chunk, "text", None)
                if txt:
                    yield txt
        except Exception as e:
            raise self._classify(e)

    @staticmethod
    def _classify(e: Exception) -> ProviderError:
        msg = str(e).lower()
        if any(s in msg for s in ("429", "rate limit", "quota", "resource_exhausted", "503", "500", "timeout", "unavailable")):
            return TransientError(f"gemini transient: {e}")
        if any(s in msg for s in ("401", "403", "invalid api key", "permission_denied", "unauthenticated")):
            return FatalError(f"gemini fatal: {e}")
        return TransientError(f"gemini unknown: {e}")


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(self, api_key: Optional[str] = None, model: str = "openai/gpt-oss-120b"):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.model = model
        self._client = None
        if self.api_key:
            try:
                from groq import Groq
                self._client = Groq(api_key=self.api_key)
            except Exception as e:
                log.warning("Groq init failed: %s", e)

    def is_available(self) -> bool:
        return bool(self._client)

    @retry(**_RETRY)
    def _call(self, prompt: str) -> str:
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=6000,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:
            raise self._classify(e)

    def generate(self, prompt: str) -> str:
        return self._call(prompt)

    def stream(self, prompt: str) -> Iterator[str]:
        try:
            stream = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=6000,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    yield delta
        except Exception as e:
            raise self._classify(e)

    @staticmethod
    def _classify(e: Exception) -> ProviderError:
        msg = str(e).lower()
        if any(s in msg for s in ("429", "rate", "503", "500", "timeout", "overloaded")):
            return TransientError(f"groq transient: {e}")
        if any(s in msg for s in ("401", "403", "invalid api key", "unauthorized")):
            return FatalError(f"groq fatal: {e}")
        return TransientError(f"groq unknown: {e}")


class YugamProvider(LLMProvider):
    """Yugam AI gateway (https://ai.yugam.co).

    Not OpenAI-compatible: auth is an X-API-Key header, the body is
    {"prompt": ...}, and the reply comes back as {"reply": ...}.
    Self-hosted and noticeably slower than the hosted providers, so it sits
    late in the chain as a backup. Mode "balanced" is used deliberately —
    "fast" emits type names like "multiplechoice" that _normalize_qtype
    does not map to a section.
    """

    name = "yugam"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        mode: str = "balanced",
    ):
        self.api_key = api_key or os.getenv("YUGAM_API_KEY")
        self.base_url = (base_url or os.getenv("YUGAM_API_URL")
                         or "https://ai.yugam.co/api/v1").rstrip("/")
        self.mode = mode

    def is_available(self) -> bool:
        return bool(self.api_key)

    @retry(**_RETRY)
    def _call(self, prompt: str) -> str:
        import requests
        try:
            # Answers run on their own hardware; docs advise >= 300s.
            resp = requests.post(
                f"{self.base_url}/chat",
                headers={"X-API-Key": self.api_key,
                         "Content-Type": "application/json"},
                json={"prompt": prompt, "mode": self.mode},
                timeout=300,
            )
        except Exception as e:
            raise TransientError(f"yugam network: {e}")

        if resp.status_code >= 400:
            raise self._classify_status(resp.status_code, resp.text[:300])
        try:
            return (resp.json().get("reply") or "").strip()
        except ValueError as e:
            raise TransientError(f"yugam bad JSON envelope: {e}")

    def generate(self, prompt: str) -> str:
        return self._call(prompt)

    @staticmethod
    def _classify_status(code: int, body: str) -> ProviderError:
        if code in (401, 403):
            return FatalError(f"yugam fatal: {code} {body}")
        if code == 400:
            return FatalError(f"yugam fatal: {code} {body}")
        return TransientError(f"yugam transient: {code} {body}")


class OpenRouterProvider(LLMProvider):
    """OpenRouter via OpenAI-compatible SDK. Uses free models by default."""

    name = "openrouter"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "deepseek/deepseek-chat-v3.1:free",
    ):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.model = model
        self._client = None
        if self.api_key:
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    api_key=self.api_key,
                    base_url="https://openrouter.ai/api/v1",
                )
            except Exception as e:
                log.warning("OpenRouter init failed: %s", e)

    def is_available(self) -> bool:
        return bool(self._client)

    @retry(**_RETRY)
    def _call(self, prompt: str) -> str:
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=8192,
                extra_headers={
                    "HTTP-Referer": "https://paper-generator.local",
                    "X-Title": "AI Paper Generator",
                },
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:
            raise self._classify(e)

    def generate(self, prompt: str) -> str:
        return self._call(prompt)

    def stream(self, prompt: str) -> Iterator[str]:
        try:
            stream = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=8192,
                stream=True,
                extra_headers={
                    "HTTP-Referer": "https://paper-generator.local",
                    "X-Title": "AI Paper Generator",
                },
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    yield delta
        except Exception as e:
            raise self._classify(e)

    @staticmethod
    def _classify(e: Exception) -> ProviderError:
        msg = str(e).lower()
        if any(s in msg for s in ("429", "rate", "503", "500", "502", "timeout")):
            return TransientError(f"openrouter transient: {e}")
        if any(s in msg for s in ("401", "403", "invalid api key", "unauthorized")):
            return FatalError(f"openrouter fatal: {e}")
        return TransientError(f"openrouter unknown: {e}")


_REGISTRY: list[LLMProvider] = []

# Last known health of the provider chain, surfaced on the home page. Quota
# exhaustion is only observable from a failed call, so it is recorded here
# rather than probed.
_STATUS: dict = {"ok": True, "reason": None, "quota": False, "at": 0.0}

# A failure older than this stops being reported: Groq's free tier trips its
# 8k tokens-per-minute cap regularly, and one blip should not leave a scary
# banner up for the rest of the day.
_STATUS_TTL_SECONDS = 15 * 60

_QUOTA_HINTS = ("429", "rate limit", "rate_limit", "quota", "insufficient_quota",
                "tokens per", "resource_exhausted", "billing", "credit")


def _note_success() -> None:
    _STATUS.update(ok=True, reason=None, quota=False, at=0.0)


def _note_failure(err: object) -> None:
    msg = str(err).lower()
    quota = any(h in msg for h in _QUOTA_HINTS)
    _STATUS.update(
        ok=False,
        quota=quota,
        at=time.time(),
        reason=("The Groq API key has run out of quota or hit its rate limit. "
                "Update GROQ_API_KEY and redeploy to keep generating papers."
                if quota else
                "AI generation is currently failing. Check GROQ_API_KEY, then redeploy."),
    )


def provider_status() -> dict:
    """Health of the AI chain for the home-page banner."""
    providers = available_providers()
    if not providers:
        return {
            "ok": False, "configured": False, "quota": False,
            "reason": "No AI provider is configured. Set GROQ_API_KEY and redeploy.",
        }
    stale = _STATUS["at"] and (time.time() - _STATUS["at"]) > _STATUS_TTL_SECONDS
    if _STATUS["ok"] or stale:
        return {"ok": True, "configured": True, "quota": False, "reason": ""}
    return {
        "ok": False,
        "configured": True,
        "quota": _STATUS["quota"],
        # Never None: the template prints this straight out, and Jinja renders
        # None as the literal string "None".
        "reason": _STATUS["reason"] or "AI generation is currently failing. "
                                       "Check GROQ_API_KEY, then redeploy.",
    }



def init_providers() -> list[LLMProvider]:
    """Build and cache the provider chain in priority order."""
    global _REGISTRY
    chain: list[LLMProvider] = []
    # Groq only for now. Gemini (project denied) and Yugam are parked — add
    # them back to this tuple to re-enable the failover chain.
    for cls in (GroqProvider,):
        try:
            p = cls()
            if p.is_available():
                chain.append(p)
                log.info("AI provider enabled: %s", p.name)
            else:
                log.info("AI provider skipped (no key): %s", cls.name)
        except Exception as e:
            log.warning("Failed to initialize %s: %s", cls.name, e)
    _REGISTRY = chain
    return chain


def available_providers() -> list[LLMProvider]:
    if not _REGISTRY:
        init_providers()
    return _REGISTRY


def generate_with_fallback(prompt: str) -> tuple[str, str]:
    """Try each provider; on failure, advance to the next.

    Returns: (response_text, provider_name_used)
    Raises: ProviderError if all providers fail.
    """
    providers = available_providers()
    if not providers:
        raise ProviderError("No AI providers configured. Set GOOGLE_API_KEY, GROQ_API_KEY, or OPENROUTER_API_KEY.")

    last_err: Optional[Exception] = None
    for p in providers:
        t0 = time.monotonic()
        try:
            out = p.generate(prompt)
            log.info("provider=%s status=ok latency_ms=%d", p.name, int((time.monotonic() - t0) * 1000))
            _note_success()
            return out, p.name
        except Exception as e:
            log.warning("provider=%s status=fail latency_ms=%d err=%s",
                        p.name, int((time.monotonic() - t0) * 1000), e)
            last_err = e
            continue
    _note_failure(last_err)
    raise ProviderError(f"All providers failed; last error: {last_err}")


def stream_with_fallback(prompt: str) -> Iterator[tuple[str, str]]:
    """Stream chunks from the first provider that succeeds.

    Yields: (chunk_text, provider_name)
    Raises: ProviderError if all providers fail before yielding anything.
    """
    providers = available_providers()
    if not providers:
        raise ProviderError("No AI providers configured.")

    last_err: Optional[Exception] = None
    for p in providers:
        try:
            yielded_any = False
            for chunk in p.stream(prompt):
                yielded_any = True
                yield chunk, p.name
            if yielded_any:
                _note_success()
                return
        except Exception as e:
            log.warning("stream provider=%s failed: %s", p.name, e)
            last_err = e
            continue
    _note_failure(last_err)
    raise ProviderError(f"All streaming providers failed; last error: {last_err}")
