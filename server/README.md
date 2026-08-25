---
title: PixieDuster
emoji: ✨
colorFrom: yellow
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
short_description: Clone a writing voice into an AI persona
---

# PixieDuster

The web app is served at `/`. Below is the metered API at `/api`, used by the [PixieDuster CLI](https://github.com/gretchenboria/PersonaPromptGenerator).

Callers authenticate with their own Hugging Face token. Usage is metered per
account against a daily allowance, with a hard global ceiling that fails closed.

## Required Space secret

| Name | Type | Value |
|---|---|---|
| `GEMINI_API_KEY` | **Secret** | Your Gemini key. Never a variable — secrets are not exposed to the build. |

## Optional Space variables

| Name | Default | What it does |
|---|---|---|
| `DAILY_PER_USER` | `5` | Personas one HF account may generate per UTC day. |
| `DAILY_GLOBAL` | `400` | Hard ceiling across everyone. This protects the bill. |
| `ALLOWED_MODELS` | `gemini-3.6-flash,gemini-2.5-flash,gemini-2.5-flash-lite` | Models callers may request. |
| `MAX_BODY_BYTES` | `6291456` | Largest request forwarded. |

## Persistent quota

Enable persistent storage on the Space so `/data` survives restarts. Without it
the quota database lives in `/tmp` and counters reset whenever the Space
rebuilds or sleeps.

## Endpoints

- `GET /api/health` — liveness and configuration
- `GET /api/me` — caller identity and remaining quota
- `GET /api/models` — allowed models
- `POST /api/models/{model}:generateContent` — metered proxy
