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


def _coerce(value: str):
    """字符串值推断为 bool/int/float/list/dict，否则原样返回字符串。"""
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    if value[:1] in "[{":
        return yaml.safe_load(value)
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def set_nested(params: dict, path: str, value: str) -> None:
    """按 'a.b.c' 路径写入参数，自动推断类型。"""
    keys = path.split(".")
    node = params
    for k in keys[:-1]:
        node = node.setdefault(k, {})
    node[keys[-1]] = _coerce(value)


def flatten_params(params: dict) -> dict:
    """平铺为点分键，便于 JSON 序列化与内容寻址。"""
    out = {}

    def walk(node: dict, prefix: str) -> None:
        for k, v in node.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                walk(v, key)
            else:
                out[key] = v

    walk(params, "")
    return out
