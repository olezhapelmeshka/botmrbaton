# Architecture

Mr. Baton is a Telegram long-polling bot with two response paths in groups.

## Request flow

1. `bot/main.py` receives an update (text / photo / document / command).
2. For groups, `GroupGate` decides whether to process the message (owner/VIP bypass, rate limits, spam, mentions, triggers).
3. If proactive mode is on, `LLMResponseDecider` returns YES/NO plus a suggested path: `casual` or `agent`.
4. **Casual** → `light_responder` (short character reply, no tools).
5. **Agent** → `agent.handle_message` tool loop (max iterations) via `openai_client` + `tools.dispatch`.
6. Persistence: memory, workspace files, notebook, schedules.

## Models

- Text: any OpenAI-compatible endpoint (`OPENAI_*`).
- Vision: optional separate endpoint (`OPENAI_VISION_*`) so cheap text models can stay free while images use a multimodal model.

## Why dual path

Full tool prompts on every group joke waste tokens and often produce empty/awkward replies on small free models. The gate keeps the bot lively without waking the agent for every message.
