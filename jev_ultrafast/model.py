"""TypeSafe/Jev makes choices; an optional small OpenAI-compatible model writes field values.

Backends (JEV_BACKEND):
  typesafe  — https://api.typesafe.ai/v1/systemone (TYPESAFE_API_KEY)
  openrouter — OpenRouter Decisions API (OPENROUTER_API_KEY)
  vercel — Vercel AI Gateway evaluation model (AI_GATEWAY_API_KEY)

Machine kill switch: ~/.config/lm/jev/browser.json enabled flag, or
JEV_ULTRAFAST_ENABLED=0|1. Managed by `lm fleet jev-browser on|off`.
"""

import json
import math
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .questions import NEXT_ACTION, TARGET, TEXT_VALUE

CLIENT = httpx.Client(http2=True, timeout=25)
BROWSER_STATE_PATH = Path.home() / ".config" / "lm" / "jev" / "browser.json"
SHARED_SECRET_DIR = Path.home() / ".config" / "lm" / "secrets"

DEFAULT_TEXT_MODEL_BASE = "https://api.deepseek.com/v1"

# TEXT_MODEL_BASE_URL is any OpenAI-compatible endpoint. When no dedicated
# TEXT_MODEL_API_KEY is set, reuse the provider key already on the machine for
# that host rather than duplicating a secret into the repository .env.
TEXT_MODEL_KEY_VARIABLES = {
    "openrouter.ai": "OPENROUTER_API_KEY",
    "api.openai.com": "OPENAI_API_KEY",
    "ai-gateway.vercel.sh": "AI_GATEWAY_API_KEY",
    "api.deepseek.com": "DEEPSEEK_API_KEY",
    "api.typesafe.ai": "TYPESAFE_API_KEY",
}


def text_model_base():
    return os.environ.get("TEXT_MODEL_BASE_URL", DEFAULT_TEXT_MODEL_BASE).rstrip("/")


def text_model_key(base):
    """Return (key, source_variable) for the TYPE_TEXT writer model.

    An explicit TEXT_MODEL_API_KEY always wins. Otherwise fall back to the
    provider key matching the configured host, which load_shared_gateway_credentials
    may itself have hydrated from ~/.config/lm/secrets.
    """
    explicit = os.environ.get("TEXT_MODEL_API_KEY", "").strip()
    if explicit:
        return explicit, "TEXT_MODEL_API_KEY"
    variable = TEXT_MODEL_KEY_VARIABLES.get(urlsplit(base).hostname or "")
    if variable:
        return os.environ.get(variable, "").strip(), variable
    return "", None


def load_shared_gateway_credentials():
    """Use the shared lm gateway secrets when dotenv leaves keys empty."""
    mappings = {
        "AI_GATEWAY_API_KEY": SHARED_SECRET_DIR / "vercel-ai-gateway.key",
        "OPENROUTER_API_KEY": SHARED_SECRET_DIR / "openrouter.key",
    }
    for variable, path in mappings.items():
        if os.environ.get(variable, "").strip():
            continue
        try:
            value = path.read_text(encoding="utf-8").splitlines()[0].strip()
        except (OSError, IndexError):
            continue
        if value:
            os.environ[variable] = value


load_shared_gateway_credentials()


def assert_enabled():
    """Raise if the machine-level Jev browser agent switch is off.

    Precedence:
      1. ~/.config/lm/jev/browser.json `enabled` when the file exists
      2. else JEV_ULTRAFAST_ENABLED env (0/1)
      3. else allow (dev default)
    """
    if BROWSER_STATE_PATH.is_file():
        try:
            data = json.loads(BROWSER_STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if data.get("enabled") is False:
            raise RuntimeError(
                "Jev Ultrafast is OFF (lm fleet jev-browser). Enable with: lm fleet jev-browser on"
            )
        if data.get("enabled") is True:
            return
    env = os.environ.get("JEV_ULTRAFAST_ENABLED", "").strip().lower()
    if env in {"0", "false", "off", "no"}:
        raise RuntimeError(
            "Jev Ultrafast is OFF (JEV_ULTRAFAST_ENABLED). Enable with: lm fleet jev-browser on"
        )


def post_json(url, key, body, extra_headers=None):
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    for attempt in range(3):
        try:
            response = CLIENT.post(url, json=body, headers=headers)
        except httpx.HTTPError:
            raise RuntimeError("Model connection failed; no action executed.") from None
        if response.status_code in {429, 529, 503} and attempt < 2:
            time.sleep(0.5 * 2**attempt)
            continue
        if response.is_error:
            detail = (response.text or "")[:300].replace("\n", " ")
            raise RuntimeError(
                f"Model provider returned HTTP {response.status_code}: {detail}; no action executed."
            )
        return response.json()
    raise RuntimeError("Model unavailable")


def normalize_choice_answer(answer):
    """Fill confidence when a backend omits it (e.g. some gateway paths)."""
    if not isinstance(answer, dict):
        return answer
    out = dict(answer)
    probs = out.get("probabilities") or {}
    if out.get("confidence") is None and isinstance(probs, dict) and probs:
        values = [v for v in probs.values() if isinstance(v, (int, float))]
        out["confidence"] = max(values) if values else 0.0
    return out


def validate_choice(answer, ids):
    answer = normalize_choice_answer(answer)
    try:
        probabilities = answer["probabilities"]
        numbers = [*probabilities.values(), answer["confidence"]]
        valid = (
            answer["choice"] in ids
            and set(probabilities) == set(ids)
            and all(type(n) in (int, float) and math.isfinite(n) and 0 <= n <= 1 for n in numbers)
            and abs(sum(probabilities.values()) - 1) < 0.02
            and probabilities[answer["choice"]] >= max(probabilities.values()) - 1e-6
        )
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("Invalid TypeSafe response; no action executed.")
    return answer


def resolve_backend():
    """Pick Jev backend from env, defaulting to whatever key is present.

    Prefer OpenRouter when both Vercel and OpenRouter keys exist: Vercel AI
    Gateway may require billing verification even with a valid API key.
    """
    explicit = os.environ.get("JEV_BACKEND", "").strip().lower()
    if explicit in {"typesafe", "openrouter", "vercel"}:
        return explicit
    if os.environ.get("TYPESAFE_API_KEY", "").strip():
        return "typesafe"
    if os.environ.get("OPENROUTER_API_KEY", "").strip():
        return "openrouter"
    if os.environ.get("AI_GATEWAY_API_KEY", "").strip():
        return "vercel"
    return "typesafe"


def jev_decide(body):
    """POST the System One / Decisions payload to the configured backend."""
    backend = resolve_backend()
    if backend == "openrouter":
        key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY required for JEV_BACKEND=openrouter")
        payload = {
            **body,
            "model": os.environ.get("TYPESAFE_MODEL", os.environ.get("JEV_MODEL", "~typesafe/jev-latest")),
        }
        result = post_json(
            "https://openrouter.ai/api/alpha/decisions",
            key,
            payload,
            extra_headers={
                "HTTP-Referer": "https://github.com/browser-use/jev-ultrafast",
                "X-OpenRouter-Title": "jev-ultrafast",
            },
        )
        if "model" not in result:
            result = {**result, "model": payload["model"]}
        return result, backend

    if backend == "vercel":
        key = os.environ.get("AI_GATEWAY_API_KEY", "").strip()
        if not key:
            raise RuntimeError("AI_GATEWAY_API_KEY required for JEV_BACKEND=vercel")
        base = os.environ.get("AI_GATEWAY_BASE_URL", "https://ai-gateway.vercel.sh/v4/ai").rstrip("/")
        model = os.environ.get("TYPESAFE_MODEL", os.environ.get("JEV_MODEL", "typesafe-ai/jev"))
        # Evaluation API: state + questions only; model via header.
        payload = {"state": body["state"], "questions": body["questions"]}
        result = post_json(
            f"{base}/evaluation-model",
            key,
            payload,
            extra_headers={
                "ai-gateway-protocol-version": "0.0.1",
                "ai-gateway-auth-method": "api-key",
                "ai-evaluation-model-specification-version": "4",
                "ai-model-id": model,
            },
        )
        answers = result.get("answers") or {}
        # Normalize choice answers that omit confidence.
        normalized = {
            qid: normalize_choice_answer(ans) if isinstance(ans, dict) else ans
            for qid, ans in answers.items()
        }
        usage = result.get("usage") or {}
        if "input_tokens" not in usage and "inputTokens" in usage:
            usage = {
                "input_tokens": usage.get("inputTokens"),
                "output_tokens": usage.get("outputTokens"),
                **usage,
            }
        return {"model": model, "answers": normalized, "usage": usage, "_vercel": True}, backend

    # typesafe (default)
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "No Jev credentials. Set TYPESAFE_API_KEY, or AI_GATEWAY_API_KEY (vercel), "
            "or OPENROUTER_API_KEY (openrouter)."
        )
    payload = {
        **body,
        "model": os.environ.get("TYPESAFE_MODEL", "jev-latest"),
    }
    return post_json("https://api.typesafe.ai/v1/systemone", key, payload), "typesafe"


def action_space(actions):
    """One index per observed element; each operation has its own valid target choices."""
    elements, indices, targets, controls = [], {}, {}, {}
    operations = {"click": "CLICK", "fill": "TYPE_TEXT", "select": "SELECT"}
    for action in actions:
        kind = action["kind"]
        if kind not in operations:
            controls[action["id"].upper()] = action
            continue
        node = action["node"]
        if node not in indices:
            index = str(len(elements) + 1)
            indices[node] = index
            element = {k: action[k] for k in ("role", "value", "checked", "selected", "expanded") if k in action}
            element.update(index=index, label=action["label"].split(" → ")[0], operations=[])
            if kind == "select":
                element["value"] = action.get("current_value", "")
                element["options"] = []
            elements.append(element)
        index = indices[node]
        operation = operations[kind]
        group = targets.setdefault(operation, {})
        element = elements[int(index) - 1]
        if operation not in element["operations"]:
            element["operations"].append(operation)
        target = index
        if kind == "select":
            target = f"{index}:{len(element['options']) + 1}"
            element["options"].append({"index": target, "label": action["label"], "value": action["value"]})
        group[target] = action
    return elements, targets, controls


def choose(state, goal, history):
    elements, targets, controls = action_space(state["actions"])
    labels = {
        "CLICK": "Click an element, button, menu option, autocomplete suggestion, or calendar day.",
        "TYPE_TEXT": "Enter or replace text in an editable field. A small LLM will supply the value from the goal.",
        "SELECT": "Select an observed dropdown value.",
    }
    operations = {key: labels[key] for key in targets}
    operations.update({key: value["label"] for key, value in controls.items()})
    operations.update(DONE="Every requirement is visibly satisfied.", BLOCKED="No supported operation can progress.")
    questions = {
        "operation": {"type": "choice", "criteria": operations, "instructions": {"goal": goal, "rules": NEXT_ACTION}}
    }
    for operation, candidates in targets.items():
        questions[operation.lower() + "_target"] = {
            "type": "choice",
            "criteria": {
                index: {
                    "element": f"[{index}] {a['label']}",
                    "current_value": a.get("current_value", a.get("value", "")),
                    **{k: a[k] for k in ("role", "checked", "selected", "expanded") if k in a},
                }
                for index, a in candidates.items()
            },
            "instructions": {"goal": goal, "operation": operation, "rules": [NEXT_ACTION, TARGET]},
        }
    assert_enabled()
    body = {
        "model": os.environ.get("TYPESAFE_MODEL", "jev-latest"),
        "state": {
            "page": {k: state[k] for k in ("url", "title", "text")},
            "elements": elements,
            "recent_actions": [
                {k: h.get(k) for k in ("action", "kind", "text", "page_changed")} for h in history[-10:]
            ],
        },
        "questions": questions,
    }
    started = time.perf_counter()
    result, backend = jev_decide(body)
    operation_answer = validate_choice(result["answers"].get("operation", {}), operations)
    operation = operation_answer["choice"]
    target = None
    target_answer = None
    probabilities = {}
    if operation in targets:
        # Unused target heads cannot cause an action. Validate the head selected by the operation.
        target_answer = validate_choice(result["answers"].get(operation.lower() + "_target", {}), targets[operation])
        target = target_answer["choice"]
        choice = targets[operation][target]["id"]
        probabilities = {a["id"]: target_answer["probabilities"][index] for index, a in targets[operation].items()}
    else:
        choice = controls[operation]["id"] if operation in controls else operation
        probabilities[choice] = operation_answer["probabilities"][operation]
    return {
        "choice": choice,
        "operation": operation,
        "target": target,
        "confidence": operation_answer["confidence"],
        "probabilities": probabilities,
        "operation_probabilities": operation_answer["probabilities"],
        "target_probabilities": target_answer["probabilities"] if target_answer else {},
        "target_confidence": target_answer["confidence"] if target_answer else None,
        "raw_answers": result["answers"],
        "model": result.get("model"),
        "backend": backend,
        "usage": result.get("usage", {}),
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "request": body,
    }


def field_context(goal, action, page, history):
    return {
        "goal": goal,
        "field": {k: action.get(k) for k in ("label", "role", "value")},
        "page": {"title": page["title"], "text": page["text"][:6000]},
        "recent_actions": [{k: h.get(k) for k in ("action", "text")} for h in history[-6:]],
    }


def field_text(context):
    base = text_model_base()
    key, source = text_model_key(base)
    if not key:
        wanted = f"TEXT_MODEL_API_KEY or {source}" if source else "TEXT_MODEL_API_KEY"
        raise ValueError(
            f"TYPE_TEXT needs {wanted} for {base}; no text is hardcoded or guessed by the executor."
        )
    model = os.environ.get("TEXT_MODEL", "deepseek-chat")
    reasoning = {"thinking": {"type": "disabled"}} if "api.deepseek.com/" in base else {"reasoning": {"effort": "low"}}
    if os.environ.get("TEXT_MODEL_REASONING") == "none":
        reasoning = {"reasoning": {"enabled": False}}
    started = time.perf_counter()
    result = post_json(
        base + "/chat/completions",
        key,
        {
            "model": model,
            "max_tokens": 1024,
            "response_format": {"type": "json_object"},
            **reasoning,
            "messages": [
                {"role": "system", "content": TEXT_VALUE},
                {
                    "role": "user",
                    "content": json.dumps(context),
                },
            ],
        },
    )
    try:
        output = json.loads(result["choices"][0]["message"]["content"])
        value = output["text"]
        if set(output) != {"text"} or not isinstance(value, str) or not value.strip() or len(value) > 2000:
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise ValueError("Text helper returned no valid field value; nothing typed.") from None
    return value, {
        "model": model,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "usage": result.get("usage", {}),
    }
