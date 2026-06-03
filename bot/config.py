"""
Загрузка конфигурации из .env.

Все секреты живут только в .env, никогда не попадают в код и логи.
Если каких-то обязательных переменных нет — падаем сразу с понятным
сообщением, чтобы не уйти в рантайм с пустыми ключами.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"

if load_dotenv and _ENV_PATH.exists():
    load_dotenv(dotenv_path=_ENV_PATH)


def _get(name: str, default: str = "") -> str:
    raw = os.getenv(name, default)
    # Убираем inline-комментарии (всё после первого #)
    if "#" in raw:
        raw = raw.split("#", 1)[0]
    return raw.strip()


def _get_int(name: str, default: int) -> int:
    raw = _get(name, "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    raw = _get(name, "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# ---- Telegram ----
TELEGRAM_TOKEN: str = _get("TELEGRAM_BOT_TOKEN")

# Anthropic (Claude) полностью удалён из проекта.
# Бот работает только через OpenAI-совместимые API (GLM + Gemini).

# ---- Models ----
MODEL_FAST: str = _get("MODEL_FAST", "claude-haiku-4.5")
MODEL_SMART: str = _get("MODEL_SMART", "claude-sonnet-4.7")

# ---- OpenAI / GLM (optional) ----
#
# Эти переменные позволяют использовать совместимые с OpenAI API модели,
# например GLM‑4.5‑Flash от ZhipuAI через сервис OpenRouter. Если вы
# хотите использовать эти модели, укажите OPENAI_API_KEY и OPENAI_BASE_URL
# в вашем .env. По умолчанию они пустые и не используются. OPENAI_MODEL
# определяет имя модели, которое будет передано клиенту (например,
# "glm-4.5-flash").
OPENAI_API_KEY: str = _get("OPENAI_API_KEY")
OPENAI_BASE_URL: str = _get("OPENAI_BASE_URL")
OPENAI_MODEL: str = _get("OPENAI_MODEL", "glm-4.5-flash")

# ---- OpenAI-compatible Vision endpoint (optional, separate from main) ----
#
# Позволяет использовать отдельный OpenAI-совместимый эндпоинт **только для картинок**.
# Например, другой провайдер Z.ai / OpenRouter / локальный vLLM и т.д.
# Если эти переменные заполнены — при наличии изображений будет использоваться именно этот эндпоинт.
OPENAI_VISION_API_KEY: str = _get("OPENAI_VISION_API_KEY")
OPENAI_VISION_BASE_URL: str = _get("OPENAI_VISION_BASE_URL")
OPENAI_VISION_MODEL: str = _get("OPENAI_VISION_MODEL", "")

# ---- Generation ----
#
# По умолчанию Z.ai Flash ограничивает контекст до 8K токенов, поэтому
# уменьшаем лимиты токенов и времени ответа. Параметры могут быть
# переопределены через .env. MAX_TOKENS — лимит токенов для обычных
# запросов (быстрая модель), MAX_TOKENS_DOC — для сложных задач
# (документы, презентации).
MAX_TOKENS: int = _get_int("MAX_TOKENS", 1024)
MAX_TOKENS_DOC: int = _get_int("MAX_TOKENS_DOC", 2048)
TEMPERATURE: float = _get_float("TEMPERATURE", 0.65)
# Выше температура = более живая, дерзкая, непредсказуемая речь (Grok-style).
# При 0.85+ бот становится разговорчивее и саркастичнее, но tool calling может быть чуть менее стабильным.

# ---- Debug / Access ----
DEBUG_USER_IDS: frozenset[int] = frozenset({571662006})

# ---- Memory / Context (очень сильно влияет на поведение бота) ----
#
# HISTORY_ROUNDS — сколько полных "раундов" (user + assistant) храним в
# глобальной истории (bot/memory.py). Используется в тяжёлом agent-пути
# (когда есть tool calls, vision, сложные задачи). Меньше = короче память,
# меньше токенов, меньше зацикливания на старых темах.
#
# MAX_HISTORY_MESSAGES_PER_CHAT — сколько последних сообщений из per-chat
# памяти (data/memory/group_*.json) показываем модели в блоке
# "[context] recent chat history:" на КАЖДОМ запросе.
# Это самый важный параметр для семейных групп.
#
#   8 (дефолт) — довольно много. Бот хорошо помнит разговор, но часто
#               зацикливается на своих старых шутках ("4 часа картошки",
#               старые мемы и т.д.), потому что видит их в контексте.
#
#   5-6        — золотая середина для групп. Всё ещё coherent, но сильно
#                меньше повторяет старые темы.
#
#   3-4        — очень "в моменте". Бот почти не помнит, что было 4-5
#                сообщений назад. Полезно, если зацикливание совсем
#                достаёт. Минус — может задавать вопросы "а о чём мы?".
#
# MAX_CONTEXT_CHARS — жёсткий лимит по символам (примерно токены) на весь
# контекст. Защита от троттлинга на бесплатном GLM.
#
# Рекомендация для семейной группы (типа "семья"):
#   HISTORY_ROUNDS=6
#   MAX_HISTORY_MESSAGES_PER_CHAT=5
#   MAX_CONTEXT_CHARS=6000
HISTORY_ROUNDS: int = _get_int("HISTORY_ROUNDS", 10)
MAX_HISTORY_MESSAGES_PER_CHAT: int = _get_int("MAX_HISTORY_MESSAGES_PER_CHAT", 8)
MAX_CONTEXT_CHARS: int = _get_int("MAX_CONTEXT_CHARS", 8000)

# ---- Limits ----
# Нужно ли учитывать 8K‑лимит бесплатной версии GLM‑4.5‑Flash. Если False,
# контекст не будет принудительно обрезаться по размеру/количеству сообщений.
RESPECT_GLM_8K_LIMIT: bool = _get("RESPECT_GLM_8K_LIMIT", "true").lower() in ("true", "1", "yes")

# ---- Group / multi-chat ----
BOT_USERNAME: str = _get("BOT_USERNAME", "oxytocinkabot")

GROUP_TRIGGER_WORDS: list[str] = [
    # новые имена
    "мистер батон", "мр батон", "батон", "mr baton", "mister baton",
    "батончик",

    # старые имена (для обратной совместимости)
    "окситоцинка", "окситоцинк", "оксито", "оксик", "окси",
    "окситоцинка бот", "oxytocinkabot", "@oxytocinkabot",

    "ребеночек", "ребёночек", "ребенок", "ребёнок",
    "детка", "дитя", "чадо",

    "ботик", "ботяра", "бот",
]

GROUP_ALLOW_REPLY_TRIGGER: bool = True
GROUP_USER_COOLDOWN_SECONDS: int = _get_int("GROUP_USER_COOLDOWN_SECONDS", 5)
GROUP_MAX_REQUESTS_PER_MINUTE: int = _get_int("GROUP_MAX_REQUESTS_PER_MINUTE", 10)

# ---- Group Proactive Mode ----
# Если True — бот обрабатывает почти все сообщения в группе (каждое идёт в модель).
# Модель сама решает, отвечать ли. Это позволяет "живому" поведению и спонтанным репликам.
GROUP_PROACTIVE_MODE: bool = _get("GROUP_PROACTIVE_MODE", "false").lower() in ("true", "1", "yes")

# Сколько последних сообщений передавать в контекст для групп (в proactive режиме)
GROUP_CONTEXT_MESSAGES: int = _get_int("GROUP_CONTEXT_MESSAGES", 10)

# ---- Network ----
# Задержка ожидания ответа от модели в секундах. Для Z.ai Flash стоит
# уменьшить таймаут, чтобы не зависать долго при throttling.
REQUEST_TIMEOUT: int = _get_int("REQUEST_TIMEOUT", 60)
WEB_SEARCH_TIMEOUT: int = _get_int("WEB_SEARCH_TIMEOUT", 15)
WEB_SEARCH_RESULTS_LIMIT: int = _get_int("WEB_SEARCH_RESULTS_LIMIT", 3)
WEB_SEARCH_RESULTS_LIMIT_DOC: int = _get_int("WEB_SEARCH_RESULTS_LIMIT_DOC", 7)

# ---- Paths ----
DATA_DIR: Path = _PROJECT_ROOT / "data"
MEMORY_FILE: Path = DATA_DIR / "memory.json"
MEMORY_DIR: Path = DATA_DIR / "memory"
NOTEBOOK_FILE: Path = DATA_DIR / "notebook.json"
WORKSPACE_DIR: Path = DATA_DIR / "files"
WORKSPACE_META: Path = DATA_DIR / "workspace.json"

# ---- Workspace ----
WORKSPACE_TTL_HOURS: int = _get_int("WORKSPACE_TTL_HOURS", 24)
MAX_FILE_SIZE_MB: int = _get_int("MAX_FILE_SIZE_MB", 20)
MAX_EXTRACTED_CHARS: int = _get_int("MAX_EXTRACTED_CHARS", 200000)

# ---- Logging ----
LOG_LEVEL: str = _get("LOG_LEVEL", "INFO").upper()


def validate() -> None:
    """Проверка обязательных параметров перед стартом.

    Для работы бота требуется ключ хотя бы одной модели — Anthropic (Claude)
    или OpenAI‑совместимого провайдера (например, GLM через OpenRouter). Если
    оба ключа отсутствуют, бот не сможет обрабатывать запросы.
    """
    missing: list[str] = []
    if not TELEGRAM_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    has_openai = bool(OPENAI_API_KEY and OPENAI_BASE_URL)
    has_vision = bool(OPENAI_VISION_API_KEY and OPENAI_VISION_BASE_URL)

    if not has_openai and not has_vision:
        missing.append("OPENAI_API_KEY + OPENAI_BASE_URL (или только vision ключи)")
    if missing:
        raise RuntimeError(
            "Не заданы обязательные переменные в .env: "
            + ", ".join(missing)
            + ". Скопируйте .env.example в .env и заполните значения."
        )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
