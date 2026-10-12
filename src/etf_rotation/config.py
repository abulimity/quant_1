"""配置加载：config/params.yaml（研报默认参数 + H1–H10 假设）与 .env 的 token。"""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT = _ROOT / "config" / "params.yaml"
load_dotenv(_ROOT / ".env")


def load_params(path=None) -> dict:
    """读取参数 yaml，默认 config/params.yaml。"""
    p = Path(path) if path else _DEFAULT
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_token() -> str:
    """读取 tushare token（import 时已 load_dotenv(.env)）。"""
    return os.environ.get("TUSHARE_TOKEN", "").strip()
