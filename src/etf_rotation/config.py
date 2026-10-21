"""配置加载：config/params.yaml（研报默认参数 + H1–H10 假设）与 .env 的 token。

两件事：
  ① 读参数：yaml → schema 校验 → 嵌套字典
  ② 读 token：从 .env 取 TUSHARE_TOKEN（只在内存中传递，不打印、不落盘）

`set_nested` / `flatten_params` 是敏感性扫描的工具：
前者按点分路径覆写单个参数（如 "risk.vol_target_portfolio"），后者把嵌套参数树
压平成点分键，便于 JSON 序列化与内容寻址。
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from etf_rotation.config_schema import validate_params

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT = _ROOT / "config" / "params.yaml"
load_dotenv(_ROOT / ".env")   # 把 .env 里的键注入 os.environ（token 不打印）


def load_params(path=None) -> dict:
    """读取参数 yaml，默认 config/params.yaml，返回经 schema 校验的字典。"""
    p = Path(path) if path else _DEFAULT
    with open(p, "r", encoding="utf-8") as f:
        params = yaml.safe_load(f)
    return validate_params(params)


def load_token() -> str:
    """读取 tushare token（import 时已 load_dotenv(.env)）。"""
    return os.environ.get("TUSHARE_TOKEN", "").strip()


def _coerce(value: str):
    """字符串值推断为 bool/int/float/list/dict，否则原样返回字符串。

    敏感性扫描的网格值以字符串形式传入（命令行/CSV），这里做类型还原：
      "true"/"false" → bool；以 "[" 或 "{" 开头 → yaml 解析（list/dict）；
      能转 int / float 的转数字；其余保持字符串。
    """
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
    """按 'a.b.c' 路径写入参数，自动推断类型，并立即做 schema 校验（越界/未知键报错）。

    例：set_nested(params, "risk.vol_target_portfolio", "0.3")
      → params["risk"]["vol_target_portfolio"] = 0.3
    写入后立即 validate_params：任何越界或未知键都会当场抛 ConfigError，
    保证「坏参数不会流到回测里」。
    """
    keys = path.split(".")          # "a.b.c" → ["a", "b", "c"]
    node = params
    for k in keys[:-1]:
        node = node.setdefault(k, {})   # 缺失的中间层自动补空 dict
    node[keys[-1]] = _coerce(value)     # 末层写入（值类型自动推断）
    validate_params(params)             # 写完立刻校验


def flatten_params(params: dict) -> dict:
    """平铺为点分键，便于 JSON 序列化与内容寻址。

    递归下降，prefix 为当前路径前缀（根层为空串）：
        key = f"{prefix}.{k}"（prefix 非空时）否则直接用 k
        值为 dict → 继续递归；否则作为叶子写入结果。
    结果形如 {"risk.vol_target_portfolio": 0.34, "trend.windows": [21, 60], ...}
    """
    out = {}

    def walk(node: dict, prefix: str) -> None:
        """递归遍历参数树：dict 继续下钻，叶子写成点分键。"""
        for k, v in node.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                walk(v, key)
            else:
                out[key] = v

    walk(params, "")
    return out
