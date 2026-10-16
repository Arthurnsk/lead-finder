"""OpenAI-compatible LLM client (local MTPLX/Qwen now, any cloud provider later)."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    OpenAI,
    RateLimitError,
)

from app.config import settings


@dataclass
class LlmConfig:
    base_url: str
    model: str = ""
    api_key: str = "local"
    disable_thinking: bool = True

    @classmethod
    def default(cls) -> LlmConfig:
        return cls(settings.llm_base_url, settings.llm_model, settings.llm_api_key, settings.llm_disable_thinking)


class LlmUnavailable(RuntimeError):
    """retryable=True means «try again later» (quota), not «this endpoint is dead»."""

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


NON_CHAT_RE = re.compile(
    r"whisper|tts|guard|embed|moderation|playai|distil|orpheus|imagen|veo|image-|-image|aqa", re.I
)
# Auto-pick order when no model is configured: families that reliably return JSON for classification.
PREFERRED_MODELS = (
    r"qwen3\.?8", r"qwen3", r"qwen", r"gemini[\w.\-]*flash", r"gemini",
    r"llama-?3\.?[3-9]", r"llama", r"mistral", r"gemma",
)
_THINK_RE = re.compile(r"<(think|thought|reasoning)>.*?(</\1>|$)", re.DOTALL)


def strip_thinking(text: str) -> str:
    """Drop <think>/<thought>/<reasoning> blocks (even unterminated) that models leave in content."""
    for tag in ("think", "thought", "reasoning"):
        if f"</{tag}>" in text and f"<{tag}>" not in text:
            text = text.split(f"</{tag}>", 1)[1]
    return _THINK_RE.sub("", text).strip()


def parse_json(raw: str) -> dict[str, Any]:
    clean = re.sub(r"```(?:json)?|```", "", strip_thinking(raw)).strip()
    start = clean.find("{")
    if start < 0:
        raise ValueError(f"JSON not found in model response: {raw[:200]}")
    obj, _ = json.JSONDecoder().raw_decode(clean[start:])  # stops after the first object
    return obj


class LlmClient:
    def __init__(self, cfg: LlmConfig, timeout: float = 180.0):
        self.cfg = cfg
        self.base_url = cfg.base_url.rstrip("/")
        self.model = cfg.model
        self.client = OpenAI(base_url=self.base_url, api_key=cfg.api_key or "local", timeout=timeout, max_retries=1)
        self._model_checked = False
        self._variant = 0  # which extra_body variant this server accepts

    def health(self) -> tuple[bool, str]:
        try:
            r = httpx.get(f"{self.base_url}/models", timeout=3.0,
                          headers={"Authorization": f"Bearer {self.cfg.api_key or 'local'}"})
            if r.status_code < 500:
                return True, "ok"
            return False, f"HTTP {r.status_code}"
        except Exception as exc:
            return False, str(exc)

    def _resolve_model(self) -> None:
        """Use the configured model if served, else the server's first chat model.

        Cloud providers list audio/moderation models too — never auto-pick those.
        """
        if self._model_checked:
            return
        self._model_checked = True
        try:
            served = [m.id for m in self.client.models.list().data]
        except Exception:
            return
        if not served or self.model in served:
            return
        chat = [m for m in served if not NON_CHAT_RE.search(m)]
        if not chat:
            return
        for pattern in PREFERRED_MODELS:
            match = next((m for m in chat if re.search(pattern, m, re.I)), None)
            if match:
                self.model = match
                return
        self.model = chat[0]

    def _extra_body_variants(self) -> list[dict | None]:
        """Most specific first: some servers accept all knobs, clouds only a few, some none."""
        if not self.cfg.disable_thinking:
            return [None]
        return [
            {"chat_template_kwargs": {"enable_thinking": False}, "reasoning_effort": "low"},
            {"reasoning_effort": "none"},
            {"reasoning_effort": "low"},
            None,
        ]

    def chat(self, system: str, user: str, *, max_tokens: int = 500, temperature: float = 0.2) -> str:
        self._resolve_model()
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        variants = self._extra_body_variants()[self._variant:]
        for offset, extra_body in enumerate(variants):
            try:
                completion = self._create(messages, max_tokens, temperature, extra_body)
            except BadRequestError:
                if offset + 1 < len(variants):
                    self._variant += 1  # this server rejects those knobs — stop sending them
                    continue
                raise
            except (APIConnectionError, APITimeoutError) as exc:
                raise LlmUnavailable(f"LLM недоступна на {self.base_url}: {exc}") from exc
            except RateLimitError as exc:
                raise LlmUnavailable(f"Провайдер {self.base_url} отдал лимит запросов: {exc}",
                                     retryable=True) from exc
            except AuthenticationError as exc:
                raise LlmUnavailable(
                    f"LLM отклонила API-ключ ({self.base_url}): проверьте ключ в Настройках → Модель"
                ) from exc

            choice = completion.choices[0]
            text = strip_thinking(choice.message.content or "")
            if text and choice.finish_reason != "length":
                return text
            # Reasoning models spend the budget before the answer: give them a much bigger one, once
            completion = self._create(messages, max_tokens * 6, temperature, extra_body)
            return strip_thinking(completion.choices[0].message.content or "")
        return ""

    def _create(self, messages, max_tokens, temperature, extra_body):
        # Gemini lists ids as "models/gemini-…" but expects the bare name in requests
        model = (self.model or "default").removeprefix("models/")
        return self.client.chat.completions.create(
            model=model, messages=messages, temperature=temperature,
            max_tokens=max_tokens, extra_body=extra_body,
        )

    def chat_json(self, system: str, user: str, *, max_tokens: int = 500) -> dict[str, Any]:
        raw = self.chat(system + "\nОтвечай ТОЛЬКО валидным JSON без markdown и без текста вокруг.", user,
                        max_tokens=max_tokens)
        return parse_json(raw)


class FallbackLlm:
    """Primary model with a backup: on an outage or a rate limit the backup takes over for this run.

    When BOTH are rate-limited the call waits and retries instead of failing the whole run —
    provider quotas are usually per-minute.
    """

    WAIT_SECONDS = (45, 90, 150)

    def __init__(self, primary: LlmClient, backup: LlmClient | None, on_switch=None):
        self.primary, self.backup, self.on_switch = primary, backup, on_switch
        self.active = primary

    @property
    def base_url(self) -> str:
        return self.active.base_url

    @property
    def model(self) -> str:
        return self.active.model

    def health(self) -> tuple[bool, str]:
        ok, why = self.primary.health()
        if ok or not self.backup:
            return ok, why
        ok2, why2 = self.backup.health()
        if ok2:
            self._switch(f"основная модель недоступна ({why})")
            return True, "ok (резервная модель)"
        return False, f"основная: {why}; резервная: {why2}"

    def _note(self, message: str) -> None:
        if self.on_switch:
            self.on_switch(message)

    def _switch_to(self, client: LlmClient, why: str) -> None:
        if client is self.active:
            return
        self.active = client
        kind = "резервную" if client is self.backup else "основную"
        self._note(f"Переключаюсь на {kind} модель ({client.base_url}): {why}")

    def _switch(self, why: str) -> None:
        if self.backup:
            self._switch_to(self.backup, why)

    def _call(self, method: str, *args, **kwargs):
        last: LlmUnavailable | None = None
        for attempt, wait in enumerate((0, *self.WAIT_SECONDS)):
            if wait:
                if not (last and getattr(last, "retryable", False)):
                    break  # a dead endpoint won't heal in 45 seconds; only quotas do
                self._note(f"Обе модели недоступны, жду {wait} с и пробую снова "
                           f"(попытка {attempt}/{len(self.WAIT_SECONDS)})")
                time.sleep(wait)
                self.active = self.primary  # the primary's per-minute quota may have reset
            for client in filter(None, (self.active, self.backup if self.active is not self.backup else None)):
                try:
                    result = getattr(client, method)(*args, **kwargs)
                    if client is not self.active:
                        self._switch_to(client, "основная не отвечает")
                    return result
                except LlmUnavailable as exc:
                    last = exc
                    if client is self.active and self.backup and client is not self.backup:
                        self._switch_to(self.backup, str(exc)[:160])
        raise last or LlmUnavailable("LLM недоступна")

    def chat(self, *args, **kwargs) -> str:
        return self._call("chat", *args, **kwargs)

    def chat_json(self, *args, **kwargs):
        return self._call("chat_json", *args, **kwargs)
