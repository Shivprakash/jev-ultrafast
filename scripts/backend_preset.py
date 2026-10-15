#!/usr/bin/env python3
"""Switch Jev Ultrafast backend/text selection via presets; restore prior values.

Usage:
  uv run python scripts/backend_preset.py status
  uv run python scripts/backend_preset.py list
  uv run python scripts/backend_preset.py apply mithila-local
  uv run python scripts/backend_preset.py apply cloud
  uv run python scripts/backend_preset.py snapshot   # save current .env as restore point
  uv run python scripts/backend_preset.py restore    # reload last snapshot

Presets only rewrite selection keys (backend, models, base URLs). Provider API
keys already in .env are kept unless the preset sets the same key explicitly.
Snapshots live under ~/.config/lm/jev/ (mode 600) and are never committed.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PRESETS = REPO / "presets"
ENV_PATH = Path(os.environ.get("JEV_ULTRAFAST_ENV", REPO / ".env"))
STATE_DIR = Path.home() / ".config" / "lm" / "jev"
SNAPSHOT = STATE_DIR / "ultrafast-backend.restore.env"

# Keys a preset is allowed to set/clear. Secrets may be placeholders only.
SELECTION_KEYS = {
    "JEV_BACKEND",
    "TYPESAFE_MODEL",
    "JEV_MODEL",
    "AI_GATEWAY_BASE_URL",
    "TEXT_MODEL",
    "TEXT_MODEL_BASE_URL",
    "TEXT_MODEL_API_KEY",
    "TEXT_MODEL_REASONING",
    "MITHILA_CLEF_BASE_URL",
    "MITHILA_CLEF_MODEL",
    "MITHILA_CLEF_API_KEY",
}


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value
    return values


def render_env(base_text: str, updates: dict[str, str]) -> str:
    """Merge updates into existing .env text; append missing keys at end."""
    lines = base_text.splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw:
            out.append(raw)
            continue
        key, _, _ = raw.partition("=")
        key = key.strip()
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(raw)
            seen.add(key)
    missing = [k for k in updates if k not in seen]
    if missing:
        if out and out[-1].strip():
            out.append("")
        out.append("# backend_preset.py")
        for key in missing:
            out.append(f"{key}={updates[key]}")
    return "\n".join(out) + ("\n" if out else "")


def load_preset(name: str) -> dict[str, str]:
    path = PRESETS / f"{name}.env"
    if not path.is_file():
        known = ", ".join(sorted(p.stem for p in PRESETS.glob("*.env"))) or "(none)"
        raise SystemExit(f"Unknown preset {name!r}. Available: {known}")
    data = parse_env(path.read_text(encoding="utf-8"))
    unknown = sorted(k for k in data if k not in SELECTION_KEYS)
    if unknown:
        raise SystemExit(f"Preset {name} has unsupported keys: {', '.join(unknown)}")
    return data


def snapshot(path: Path | None = None) -> Path:
    """Copy current env file to the restore snapshot. Resolve paths at call time."""
    env_path = path or ENV_PATH
    snap_path = SNAPSHOT
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not env_path.is_file():
        raise SystemExit(f"No env file at {env_path}")
    shutil.copy2(env_path, snap_path)
    snap_path.chmod(0o600)
    return snap_path


def apply_updates(updates: dict[str, str], *, take_snapshot: bool) -> None:
    env_path = ENV_PATH
    if not env_path.is_file():
        raise SystemExit(f"No env file at {env_path}; copy .env.example first")
    if take_snapshot:
        snap = snapshot(env_path)
        print(f"snapshot → {snap}")
    text = env_path.read_text(encoding="utf-8")
    env_path.write_text(render_env(text, updates), encoding="utf-8")
    env_path.chmod(0o600)
    print(f"updated {env_path}")
    for key in sorted(updates):
        value = updates[key]
        shown = value if not re.search(r"(KEY|TOKEN|SECRET|PASSWORD)", key, re.I) else ("(set)" if value else "(cleared)")
        print(f"  {key}={shown}")


def status() -> None:
    """Print effective backend selection from the env file (not stale process env)."""
    sys.path.insert(0, str(REPO))
    os.chdir(REPO)
    env_file = ENV_PATH
    file_values = parse_env(env_file.read_text(encoding="utf-8")) if env_file.is_file() else {}
    # Force file values over process env so status matches disk after apply/restore.
    for key, value in file_values.items():
        os.environ[key] = value
    # Clear selection keys removed from the file so stale process values cannot linger.
    for key in SELECTION_KEYS:
        if key not in file_values:
            os.environ.pop(key, None)
    from jev_ultrafast import model

    backend = model.resolve_backend()
    base = model.text_model_base()
    key, source = model.text_model_key(base)
    print(f"env_file={env_file}")
    print(f"snapshot={SNAPSHOT} exists={SNAPSHOT.is_file()}")
    print(f"JEV_BACKEND_effective={backend}")
    print(f"TYPESAFE_MODEL={os.environ.get('TYPESAFE_MODEL', '')}")
    print(f"MITHILA_CLEF_BASE_URL={os.environ.get('MITHILA_CLEF_BASE_URL', model.DEFAULT_MITHILA_CLEF_BASE)}")
    print(f"TEXT_MODEL={os.environ.get('TEXT_MODEL', '')}")
    print(f"TEXT_MODEL_BASE_URL={base}")
    print(f"text_key_source={source} has_key={bool(key)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["status", "list", "apply", "snapshot", "restore"])
    parser.add_argument("preset", nargs="?", help="Preset name for apply")
    parser.add_argument("--no-snapshot", action="store_true", help="Do not write restore snapshot before apply")
    args = parser.parse_args(argv)

    if args.command == "list":
        for path in sorted(PRESETS.glob("*.env")):
            print(path.stem)
        return 0
    if args.command == "status":
        status()
        return 0
    if args.command == "snapshot":
        path = snapshot()
        print(f"snapshot → {path}")
        return 0
    if args.command == "restore":
        if not SNAPSHOT.is_file():
            raise SystemExit(f"No snapshot at {SNAPSHOT}; run apply or snapshot first")
        shutil.copy2(SNAPSHOT, ENV_PATH)
        ENV_PATH.chmod(0o600)
        print(f"restored {ENV_PATH} from {SNAPSHOT}")
        status()
        return 0
    if args.command == "apply":
        if not args.preset:
            raise SystemExit("apply requires a preset name (see list)")
        updates = load_preset(args.preset)
        apply_updates(updates, take_snapshot=not args.no_snapshot)
        status()
        return 0
    raise SystemExit(f"unknown command {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
