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

| Value | Key | Notes |
| --- | --- | --- |
| openrouter | OPENROUTER_API_KEY | **default on this machine** (works now) |
| vercel | AI_GATEWAY_API_KEY | needs Vercel AI Gateway credit card / billing unlock |
| typesafe | TYPESAFE_API_KEY | official System One |

If Vercel returns `customer_verification_required`, keep `JEV_BACKEND=openrouter`.

Text for TYPE_TEXT uses OpenRouter (`TEXT_MODEL_API_KEY`, mercury-2.5).

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
