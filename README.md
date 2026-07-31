# Мистер Батон

**Бесплатный** способ сделать себе Telegram-ассистента с характером: без подписки на ChatGPT, без своего GPU — только открытый код + бесплатные/дешёвые API (GLM на Z.ai, vision через OpenRouter).

Болтает в личке и группах, ищет в интернете, смотрит картинки, работает с файлами и ставит напоминания.

**Открыть бота:** [t.me/misterbatonbot](https://t.me/misterbatonbot)  
Можно писать сразу или добавить в группу как обычного бота. Свой инстанс поднимается за пару минут по инструкции ниже.

---

## Что это

Не корпоративный ассистент, а живой собеседник с tool-агентом под капотом:

- диалог с памятью по чату  
- веб-поиск  
- vision (фото)  
- файлы PDF / DOCX / XLSX / …  
- блокнот и напоминания  

Весь стек рассчитан на **$0** : текст — `glm-4.5-flash` на Z.ai, картинки — `google/gemini-2.5-flash` на OpenRouter. Код открыт (MIT).

Как устроены gate, casual/agent и модули — в [docs/architecture.md](docs/architecture.md).

---

## Примеры

Живой бот: [t.me/misterbatonbot](https://t.me/misterbatonbot) — напиши в личку или добавь в группу.

Пример общения в личных сообщениях:

<img width="300" height="800" alt="telegram-cloud-photo-size-2-5431466302120859483-y" src="https://github.com/user-attachments/assets/37cfd1c7-01ce-4611-9d21-2526f6b7e2e4" />
<img width="300" height="800" alt="telegram-cloud-photo-size-2-5431466302120859484-y" src="https://github.com/user-attachments/assets/bfd86a4d-389b-475d-bc3a-f3a5a45dd192" />

Пример общения в группе:

<img width="300" height="800" alt="telegram-cloud-photo-size-2-5431466302120859488-y" src="https://github.com/user-attachments/assets/6752fd1c-9333-4d7f-be77-f4dc443c8603" />
<img width="300" height="800" alt="telegram-cloud-photo-size-2-5431466302120859489-y" src="https://github.com/user-attachments/assets/52b622bc-1a8a-4740-8468-ea6ed333a3f5" />
<img width="300" height="800" alt="telegram-cloud-photo-size-2-5431466302120859490-y" src="https://github.com/user-attachments/assets/ee63a16e-cf8d-4ae6-a453-692520077d1e" />

---

## Быстрый запуск своего бота

Нужны: Python 3.9+, токен Telegram, **ключ текста (Z.ai)** и **ключ vision (OpenRouter)**.

### 1) Telegram

1. [@BotFather](https://t.me/BotFather) → `/newbot` (или `/token`) → скопируй токен → это `TELEGRAM_BOT_TOKEN`
2. [@userinfobot](https://t.me/userinfobot) → свой числовой id → это `OWNER_USER_ID`

### 2) Текст — Z.ai (`glm-4.5-flash`)

Это основной чат-движок бота (дешёвый/бесплатный GLM).

1. Открой [z.ai/model-api](https://z.ai/model-api) → зарегистрируйся / войди  
2. Ключ: [z.ai/manage-apikey/apikey-list](https://z.ai/manage-apikey/apikey-list) → **Create API Key** → копируй → это `OPENAI_API_KEY`  
3. Модель: в `.env` пиши ровно `OPENAI_MODEL=glm-4.5-flash`  
   (карточка модели: [docs.z.ai — GLM-4.5](https://docs.z.ai/guides/llm/glm-4.5))  
4. Base URL (не меняй): `OPENAI_BASE_URL=https://api.z.ai/api/paas/v4`

Документация OpenAI-совместимого SDK: [docs.z.ai](https://docs.z.ai/guides/develop/openai/python).

### 3) Картинки — OpenRouter (`google/gemini-2.5-flash`)

Отдельный ключ только для vision (фото). Текст по-прежнему идёт в Z.ai.

1. Открой [openrouter.ai](https://openrouter.ai) → Sign In  
2. Ключ: [openrouter.ai/keys](https://openrouter.ai/keys) → **Create API Key** → копируй → это `OPENAI_VISION_API_KEY`  
3. Модель: страница [google/gemini-2.5-flash](https://openrouter.ai/google/gemini-2.5-flash) → в `.env` пиши ровно  
   `OPENAI_VISION_MODEL=google/gemini-2.5-flash`  
4. Base URL (не меняй): `OPENAI_VISION_BASE_URL=https://openrouter.ai/api/v1`

### 4) Установка и `.env`

```bash
git clone https://github.com/olezhapelmeshka/botmrbaton.git
cd botmrbaton
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Ключи через терминал (интерактивно):

```bash
bash scripts/setup_env.sh
```

Или одной пачкой (подставь свои значения):

```bash
cp .env.example .env
cat > .env <<'EOF'
TELEGRAM_BOT_TOKEN=123456:ABC...
OWNER_USER_ID=123456789

# текст = Z.ai API Key + glm-4.5-flash
OPENAI_API_KEY=вставь_ключ_с_z.ai_manage-apikey
OPENAI_BASE_URL=https://api.z.ai/api/paas/v4
OPENAI_MODEL=glm-4.5-flash

# картинки = OpenRouter API Key + google/gemini-2.5-flash
OPENAI_VISION_API_KEY=вставь_ключ_с_openrouter.ai_keys
OPENAI_VISION_BASE_URL=https://openrouter.ai/api/v1
OPENAI_VISION_MODEL=google/gemini-2.5-flash
EOF
```

Запуск:

```bash
python bot/main.py
```

Постоянно на macOS (автостарт + рестарт при падении):

```bash
bash scripts/install_launchagent.sh
```

> Публичный инстанс [@misterbatonbot](https://t.me/misterbatonbot) уже крутится. Скрипт выше — для своей копии.

---

## Краткая история проекта

- **Июнь 2026** — первая рабочая версия: личный Telegram-бот с характером, памятью, инструментами и групповым gate; пре-релиз на GitHub.  
- **Июль 2026** — публичный релиз для портфолио: обезличенные промпты, MIT, тесты/CI, анти-зацикливание на мемах, README с пошаговым бесплатным стеком (Z.ai + OpenRouter), живой [@misterbatonbot](https://t.me/misterbatonbot).

Идея с самого начала: показать, что нормальный AI-ассистент в Telegram можно собрать **бесплатно** на открытых моделях, без корпоративного «helpdesk»-тона.

---

# Mr. Baton (English)

A **free** way to make your own Telegram assistant with personality: no ChatGPT subscription, no GPU of your own — just open-source code + free/cheap APIs (GLM on Z.ai, vision via OpenRouter).

It chats in DMs and groups, searches the web, looks at photos, works with files, and sets reminders.

**Open the bot:** [t.me/misterbatonbot](https://t.me/misterbatonbot)  
You can message it right away or add it to a group like a normal bot. Your own instance takes a couple of minutes with the steps below.

---

## What it is

Not a corporate assistant — a lively chat partner with a tool-using agent under the hood:

- chat with per-chat memory  
- web search  
- vision (photos)  
- files PDF / DOCX / XLSX / …  
- notebook and reminders  

The whole stack is aimed at **$0** (or nearly $0): text — `glm-4.5-flash` on Z.ai, images — `google/gemini-2.5-flash` on OpenRouter. Code is open (MIT).

How the gate, casual/agent paths, and modules work — see [docs/architecture.md](docs/architecture.md).

---

## Examples

Live bot: [t.me/misterbatonbot](https://t.me/misterbatonbot) — DM it or add it to a group.

Private chat examples:

<img width="300" height="800" alt="private chat example 1" src="https://github.com/user-attachments/assets/37cfd1c7-01ce-4611-9d21-2526f6b7e2e4" />
<img width="300" height="800" alt="private chat example 2" src="https://github.com/user-attachments/assets/bfd86a4d-389b-475d-bc3a-f3a5a45dd192" />

Group chat examples:

<img width="300" height="800" alt="group chat example 1" src="https://github.com/user-attachments/assets/6752fd1c-9333-4d7f-be77-f4dc443c8603" />
<img width="300" height="800" alt="group chat example 2" src="https://github.com/user-attachments/assets/52b622bc-1a8a-4740-8468-ea6ed333a3f5" />
<img width="300" height="800" alt="group chat example 3" src="https://github.com/user-attachments/assets/ee63a16e-cf8d-4ae6-a453-692520077d1e" />

---

## Quick start (your own bot)

You need: Python 3.9+, a Telegram token, a **text key (Z.ai)**, and a **vision key (OpenRouter)**.

### 1) Telegram

1. [@BotFather](https://t.me/BotFather) → `/newbot` (or `/token`) → copy the token → `TELEGRAM_BOT_TOKEN`
2. [@userinfobot](https://t.me/userinfobot) → your numeric id → `OWNER_USER_ID`

### 2) Text — Z.ai (`glm-4.5-flash`)

This is the main chat engine (cheap/free GLM).

1. Open [z.ai/model-api](https://z.ai/model-api) → sign up / log in  
2. Key: [z.ai/manage-apikey/apikey-list](https://z.ai/manage-apikey/apikey-list) → **Create API Key** → copy → `OPENAI_API_KEY`  
3. Model: in `.env` set exactly `OPENAI_MODEL=glm-4.5-flash`  
   (model card: [docs.z.ai — GLM-4.5](https://docs.z.ai/guides/llm/glm-4.5))  
4. Base URL (do not change): `OPENAI_BASE_URL=https://api.z.ai/api/paas/v4`

OpenAI-compatible SDK docs: [docs.z.ai](https://docs.z.ai/guides/develop/openai/python).

### 3) Images — OpenRouter (`google/gemini-2.5-flash`)

A separate key only for vision (photos). Text still goes to Z.ai.

1. Open [openrouter.ai](https://openrouter.ai) → Sign In  
2. Key: [openrouter.ai/keys](https://openrouter.ai/keys) → **Create API Key** → copy → `OPENAI_VISION_API_KEY`  
3. Model: page [google/gemini-2.5-flash](https://openrouter.ai/google/gemini-2.5-flash) → in `.env` set exactly  
   `OPENAI_VISION_MODEL=google/gemini-2.5-flash`  
4. Base URL (do not change): `OPENAI_VISION_BASE_URL=https://openrouter.ai/api/v1`

### 4) Install and `.env`

```bash
git clone https://github.com/olezhapelmeshka/botmrbaton.git
cd botmrbaton
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Keys via terminal (interactive):

```bash
bash scripts/setup_env.sh
```

Or in one shot (paste your values):

```bash
cp .env.example .env
cat > .env <<'EOF'
TELEGRAM_BOT_TOKEN=123456:ABC...
OWNER_USER_ID=123456789

# text = Z.ai API Key + glm-4.5-flash
OPENAI_API_KEY=paste_key_from_z.ai_manage-apikey
OPENAI_BASE_URL=https://api.z.ai/api/paas/v4
OPENAI_MODEL=glm-4.5-flash

# images = OpenRouter API Key + google/gemini-2.5-flash
OPENAI_VISION_API_KEY=paste_key_from_openrouter.ai_keys
OPENAI_VISION_BASE_URL=https://openrouter.ai/api/v1
OPENAI_VISION_MODEL=google/gemini-2.5-flash
EOF
```

Run:

```bash
python bot/main.py
```

Always-on on macOS (autostart + restart on crash):

```bash
bash scripts/install_launchagent.sh
```

> The public instance [@misterbatonbot](https://t.me/misterbatonbot) is already running. The script above is for your own copy.

---

## Short project history

- **June 2026** — first working version: personal Telegram bot with character, memory, tools, and group gate; pre-release on GitHub.  
- **July 2026** — public portfolio release: depersonalized prompts, MIT, tests/CI, anti-meme looping, README with a free stack walkthrough (Z.ai + OpenRouter), live [@misterbatonbot](https://t.me/misterbatonbot).

The idea from day one: show that a normal AI assistant in Telegram can be built **for free** on open models, without a corporate helpdesk tone.

Built with ❤️ by [olezhapelmeshka](https://github.com/olezhapelmeshka) and developed by [Claude Code](https://claude.com/claude-code) 🤖
