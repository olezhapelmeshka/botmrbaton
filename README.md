# Mr. Baton

> Telegram AI-ассистент с характером: диалог, инструменты, поиск, vision, файлы и напоминания.

[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## Русский

### О проекте

Mr. Baton — самостоятельный Telegram-ассистент, который умеет поддерживать контекст беседы,
решать задачу инструментами и аккуратно вести себя в группах. Это pet-проект про прикладные
LLM-интеграции: не просто чат, а связка памяти, маршрутизации, API и ограничений поведения.

### Возможности

- личные и групповые диалоги с памятью по чату;
- tool-use: веб-поиск, файлы, заметки и напоминания;
- vision через отдельный OpenAI-compatible endpoint;
- маршрутизация между лёгким ответом и агентным путём;
- group gate, антиспам, cooldown и защита от зацикливания;
- локальное хранение рабочих данных с TTL.

### Технологии

`Python` · `Telegram Bot API` · `OpenAI-compatible LLM APIs` · `pytest` · `SQLite` · `systemd`

### Быстрый запуск

```bash
git clone https://github.com/olezhapelmeshka/botmrbaton.git
cd botmrbaton
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Заполни **только локальный** `.env` своим Telegram token, user IDs и ключами провайдера, затем:

```bash
python bot/main.py
pytest -q
```

Подробная схема компонентов: [docs/architecture.md](docs/architecture.md).

### Безопасность и границы

- `.env`, runtime-данные, логи и временные файлы исключены из Git;
- в репозитории лежит только пустой [.env.example](.env.example), без ключей и ID;
- не публикуй Telegram token, API-ключи, чаты, файлы пользователей или production-конфигурацию;
- перед внешним деплоем обязательно замени значения из локального `.env` и проверь доступы бота.

### Статус

**Portfolio prototype / self-hosted.** Основные сценарии — память, group gate, dispatch
инструментов и напоминания — покрыты тестами. Репозиторий предназначен для собственного запуска,
а не как публичный SaaS-сервис.

---

## English

### About

Mr. Baton is a self-hosted Telegram AI assistant with per-chat memory, tool use, and deliberate
group behavior. It is a hands-on LLM integration project: routing, state, external APIs, and
safety limits rather than a plain chat wrapper.

### Features

- private and group chats with per-chat memory;
- tool use for web search, files, notes, and reminders;
- vision through a separate OpenAI-compatible endpoint;
- routing between a lightweight responder and an agent path;
- group gate, anti-spam, cooldowns, and anti-loop protection;
- local runtime storage with TTL.

### Stack

`Python` · `Telegram Bot API` · `OpenAI-compatible LLM APIs` · `pytest` · `SQLite` · `systemd`

### Quick start

```bash
git clone https://github.com/olezhapelmeshka/botmrbaton.git
cd botmrbaton
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill the **local-only** `.env` with your own Telegram token, user IDs, and provider keys, then run:

```bash
python bot/main.py
pytest -q
```

See [docs/architecture.md](docs/architecture.md) for the component map.

### Safety boundary

`.env`, runtime data, logs, and temporary files are ignored by Git. The repository contains an
empty [.env.example](.env.example) only. Never commit Telegram tokens, provider keys, user chats,
uploaded files, or production configuration.

### Status

**Portfolio prototype / self-hosted.** Core memory, group-gate, tool-dispatch, and reminder
scenarios are covered by tests. This repository is intended for a personal self-hosted instance,
not a public SaaS service.
