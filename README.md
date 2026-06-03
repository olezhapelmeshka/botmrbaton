# 🥖 Mr. Baton — Telegram AI Assistant

**Mr. Baton** — лёгкий Telegram-бот с характером для групповых чатов.  
Работает на **GLM + Gemini через OpenAI-совместимые API**, совместимость с Claude(опционально). Прост в настройке, быстрый и живой.

---

## Основная идея

- Бот для **живых групп** — не корпоративный помощник.  
- Поддерживает диалог, память, напоминания, работу с файлами и простые инструменты.  
- Контекст сохраняется аккуратно, чтобы бот не зацикливался на старых сообщениях.  
- Фокус на **характере**, а не на интеллекте: живо, хаотично, но полезно.

---

## Возможности

| Функция                    | Как работает |
|----------------------------|---|
| 💬 Диалог                  | GLM через OpenAI-совместимый API, история по chat_id |
| 🔍 Веб-поиск               | DuckDuckGo HTML без ключа |
| 👁️ Vision                 | Gemini видит присланные картинки |
| 📄 Работа с файлами        | PDF, DOCX, XLSX, TXT, MD, CSV, JSON |
| 📝 Создание/редактирование | TXT, MD, CSV, JSON, DOCX, XLSX, PPTX |
| 📓 Блокнот                 | Личные заметки JSON |
| ⏰ Напоминания              | Один раз, ежедневно, по расписанию |

---


## Установка

```bash
pip install -r requirements.txt
cp .env.example .env
```

Заполни `.env` :
предлагается использовать GLM как основная бесплатная модель и gemini 2.5 flash как обработчик картинок
```ini
TELEGRAM_BOT_TOKEN=123456:ABC...
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://api.z.ai/api/paas/v4
OPENAI_MODEL=glm-4.5-flash
OPENAI_VISION_MODEL=gemini-2.5-flash
```


---

## Запуск

```bash
python bot/main.py
```

---

## Основные команды бота

| Команда | Действие |
|---|---|
| /start | Приветствие и описание |
| /help | Список команд |
| /reset | Очистить историю диалога |
| /files | Список файлов в workspace |
| /clear | Удалить все файлы и историю |
| /model | Выбрать модель |
| /schedule_add ЧЧ:ММ текст | Добавить напоминание |
| /schedule_list | Список напоминаний |
| /schedule_remove N | Удалить напоминание по номеру |

---

## Workspace и файлы

- Файлы сохраняются в `data/<chat_tag>/files/`  
- Метаданные в `data/<chat_tag>/workspace.json`  
- Поддерживаемые форматы для чтения: txt, md, csv, json, pdf, docx, xlsx, png, jpg, jpeg, webp, gif  
- Поддерживаемые форматы для создания: txt, md, csv, json, docx, xlsx, pptx  
- Автоочистка по `WORKSPACE_TTL_HOURS`  
- Ручная очистка: /clear

---

## Безопасность

- Ключи только в `.env`  
- `.env`, `.venv`, `data/`, `logs/`, `tmp/` в `.gitignore`  
- Base64 изображений и system prompts не сохраняются в памяти
