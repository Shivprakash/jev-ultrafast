# Jev Ultrafast — machine setup (local)

Clone: `~/code/shivprakash/jev-ultrafast` (browser-use/jev-ultrafast).

## Run

```bash
lm fleet jev-browser on          # global switch
cd ~/code/shivprakash/jev-ultrafast
uv run --env-file .env jev       # inspector http://127.0.0.1:8766
```

One-shot task:

```bash
cd ~/code/shivprakash/jev-ultrafast
uv run --env-file .env python examples/run.py \
  --url 'https://en.wikipedia.org/wiki/Main_Page' \
  --goal 'Open the article about Alan Turing.'
```

## Switch

```bash
lm fleet jev-browser on
lm fleet jev-browser off
lm fleet jev-browser status
```

State: `~/.config/lm/jev/browser.json`. When OFF, `choose()` and the demo
server refuse to start.

## Backends (JEV_BACKEND in .env)

| Value | Key / endpoint | Notes |
| --- | --- | --- |
| typesafe | TYPESAFE_API_KEY | official System One |
| openrouter | OPENROUTER_API_KEY | shared key: `~/.config/lm/secrets/openrouter.key` |
| vercel | AI_GATEWAY_API_KEY | shared key: `~/.config/lm/secrets/vercel-ai-gateway.key` |
| mithila-clef | MITHILA_CLEF_BASE_URL | local Clef SystemOne (default `http://gana004:8003/v1`) |

Jev automatically loads the shared Vercel, OpenRouter, and TypeSafe key files
when the corresponding environment variable is empty. The repository `.env` may
contain only backend/model selection; provider key values do not need to be
duplicated there.

### Lab preset (mithila-clef + mithila-chat)

```bash
cd ~/code/shivprakash/jev-ultrafast
uv run python scripts/backend_preset.py status
uv run python scripts/backend_preset.py apply mithila-local   # snapshots first
uv run python scripts/backend_preset.py apply cloud           # selection back to TypeSafe+Vercel text
uv run python scripts/backend_preset.py restore               # full prior .env snapshot
```

| Role | Preset `mithila-local` |
| --- | --- |
| Decision | `JEV_BACKEND=mithila-clef` → Clef `/v1/systemone` on gana004:8003 |
| TYPE_TEXT | `TEXT_MODEL` = mithila-chat weights path on gana005:8000 |

Snapshots land in `~/.config/lm/jev/ultrafast-backend.restore.env` (mode 600).
Presets under `presets/` hold non-secret selection only.

Text for TYPE_TEXT uses any OpenAI-compatible endpoint set by
`TEXT_MODEL_BASE_URL`. If `TEXT_MODEL_API_KEY` is empty, the key for that host
is reused instead:

| `TEXT_MODEL_BASE_URL` host | Key used |
| --- | --- |
| `ai-gateway.vercel.sh` | `AI_GATEWAY_API_KEY` |
| `openrouter.ai` | `OPENROUTER_API_KEY` |
| `api.openai.com` | `OPENAI_API_KEY` |
| `api.deepseek.com` | `DEEPSEEK_API_KEY` |
| `api.typesafe.ai` | `TYPESAFE_API_KEY` |
| `gana004` / `gana005` / localhost | placeholder `local` (lab servers) |

So a provider key never has to be duplicated into `.env`. Without this,
TYPE_TEXT fails and every goal that needs typing dies mid-run, while
click-only goals still succeed — a confusing partial failure.

## Browser

Chrome must allow remote debugging. First harness attach may open
`chrome://inspect/#remote-debugging` — click Allow.

```bash
cd ~/code/shivprakash/jev-ultrafast
uv run browser-harness doctor
```

Cloud auth is optional.

## Do not commit

`.env` and API keys stay local (gitignored).
