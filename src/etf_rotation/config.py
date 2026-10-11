from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT = _ROOT / "config" / "params.yaml"
load_dotenv(_ROOT / ".env")


def load_params(path=None) -> dict:
    p = Path(path) if path else _DEFAULT
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_token() -> str:
    return os.environ.get("TUSHARE_TOKEN", "").strip()
