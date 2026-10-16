"""Recognise the LLM provider behind a base_url: labels, docs, key format, data-residency warning."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    kind: str  # "cloud" | "local"
    hosts: tuple[str, ...] = ()
    base_url: str = ""  # preset offered in the UI
    docs_url: str = ""
    key_prefix: str = ""  # expected API-key prefix, if the provider uses one
    needs_key: bool = True
    note: str = ""

    def public(self) -> dict:
        d = asdict(self)
        d.pop("hosts")
        return d


PROVIDERS: tuple[Provider, ...] = (
    Provider("groq", "Groq", "cloud", ("api.groq.com",), "https://api.groq.com/openai/v1",
             "https://console.groq.com/keys", "gsk_", True,
             "Очень быстрый инференс, есть бесплатный лимит запросов."),
    Provider("openai", "OpenAI", "cloud", ("api.openai.com",), "https://api.openai.com/v1",
             "https://platform.openai.com/api-keys", "sk-", True),
    Provider("gemini", "Google Gemini", "cloud", ("generativelanguage.googleapis.com",),
             "https://generativelanguage.googleapis.com/v1beta/openai/",
             "https://aistudio.google.com/apikey", "", True,
             "OpenAI-совместимый режим Gemini. Хорошо подходит как резерв к основной модели."),
    Provider("openrouter", "OpenRouter", "cloud", ("openrouter.ai",), "https://openrouter.ai/api/v1",
             "https://openrouter.ai/keys", "sk-or-", True, "Доступ к моделям разных провайдеров через один ключ."),
    Provider("deepseek", "DeepSeek", "cloud", ("api.deepseek.com",), "https://api.deepseek.com/v1",
             "https://platform.deepseek.com/api_keys", "sk-", True),
    Provider("together", "Together AI", "cloud", ("api.together.xyz", "api.together.ai"),
             "https://api.together.xyz/v1", "https://api.together.ai/settings/api-keys", "", True),
    Provider("mistral", "Mistral", "cloud", ("api.mistral.ai",), "https://api.mistral.ai/v1",
             "https://console.mistral.ai/api-keys", "", True),
    Provider("fireworks", "Fireworks AI", "cloud", ("api.fireworks.ai",), "https://api.fireworks.ai/inference/v1",
             "https://fireworks.ai/account/api-keys", "fw_", True),
    Provider("mtplx", "MTPLX (Qwen на этом Mac)", "local", (), "http://host.docker.internal:8080/v1",
             "", "", False, "Данные не покидают компьютер. Запуск: mtplx serve --reasoning off --no-auth"),
    Provider("ollama", "Ollama", "local", (), "http://host.docker.internal:11434/v1", "", "", False,
             "Данные не покидают компьютер."),
    Provider("lmstudio", "LM Studio", "local", (), "http://host.docker.internal:1234/v1", "", "", False,
             "Данные не покидают компьютер."),
)

UNKNOWN_CLOUD = Provider("custom", "Свой сервер", "cloud", (), "", "", "", True)
UNKNOWN_LOCAL = Provider("local", "Локальный сервер", "local", (), "", "", "", False,
                         "Данные не покидают компьютер.")

LOCAL_HOSTS = ("localhost", "127.0.0.1", "host.docker.internal", "0.0.0.0", "::1")
LOCAL_PORT_HINTS = {"11434": "ollama", "1234": "lmstudio", "8080": "mtplx"}


def detect_provider(base_url: str) -> Provider:
    host = (urlparse(base_url).hostname or "").lower()
    port = str(urlparse(base_url).port or "")
    if not host:
        return UNKNOWN_CLOUD
    for p in PROVIDERS:
        if any(host == h or host.endswith("." + h) for h in p.hosts):
            return p
    if host in LOCAL_HOSTS or host.endswith(".local") or host.endswith(".internal"):
        by_port = LOCAL_PORT_HINTS.get(port)
        if by_port:
            return next(p for p in PROVIDERS if p.id == by_port)
        return UNKNOWN_LOCAL
    return UNKNOWN_CLOUD


def mask_key(key: str) -> str:
    """Never return a usable key — just enough to tell two keys apart."""
    if not key:
        return ""
    if len(key) <= 8:
        return "•" * len(key)
    return f"{key[:4]}…{key[-4:]}"


def key_warnings(provider: Provider, key: str) -> list[str]:
    out: list[str] = []
    if provider.needs_key and not key:
        out.append(f"{provider.label} требует API-ключ, но он не задан.")
    if key and not provider.needs_key:
        out.append("Локальному серверу ключ не нужен — его можно удалить.")
    if key and provider.key_prefix and not key.startswith(provider.key_prefix):
        out.append(f"Ключ не похож на ключ {provider.label}: обычно он начинается с «{provider.key_prefix}».")
    if provider.kind == "cloud":
        out.append("Тексты найденных постов будут отправляться внешнему сервису.")
    return out
