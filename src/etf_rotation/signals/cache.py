"""信号身份（signal_id）：信号集的内容寻址键。

为什么需要独立的 `signal_id`：
- `run_id` 含 git_sha，改一行报告脚本就会变；但底层信号（动量/波动/市场状态/
  反转/过热线）完全没变，缓存不该失效。
- 因此信号身份只由「信号代码 + 数据快照 + 信号相关参数」决定，与组合层参数
  （去重阈值、持仓上限、成本、执行口径）无关。

公式：
    signal_id = sha256( json({data_snapshot_id, signal_params, code_hash}, sort_keys=True) )[:12]
    code_hash = sha256( signals/trend.py + signals/market_state.py + signals/reversal.py
                        + portfolio/risk_layers.py + pipeline._precompute_signals 源码 )
    signal_params = _SIGNAL_KEYS 里列出的参数取值（缺失记 None，保持结构稳定）

本模块当前只提供身份计算；落盘/读取（`data/cache/signals/{signal_id}/`）由后续
任务在同一个模块里补齐。
"""
from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

# 参与信号的参数（点号路径，兼容嵌套 dict 与 config.flatten_params 的扁平 dict）。
# 只列 _precompute_signals 真正读取的量：组合/去重/成本类参数一律不进来。
_SIGNAL_KEYS = (
    "trend.windows",
    "trend.weighting",
    "reversal.ema_span",
    "reversal.z_window",
    "reversal.zbias_threshold",
    "reversal.repair_lookback",
    "market_state.alpha",
    "market_state.slope_window",
    "market_state.slope_up",
    "market_state.slope_down",
    "market_state.bull_threshold",
    "market_state.bear_threshold",
    "risk.vol_window",
    "risk.llm80_alpha",
    "nasdaq_etf",
    "gold_etf",
)

# 信号代码：这些文件的字节内容一变，缓存必须失效。
_SIGNAL_SOURCES = (
    "signals/trend.py",
    "signals/market_state.py",
    "signals/reversal.py",
    "portfolio/risk_layers.py",
)

_PKG_ROOT = Path(__file__).resolve().parents[1]   # src/etf_rotation


def _get(params: dict, dotted: str):
    """按点号路径取值：先试扁平键（config.flatten_params 输出），再逐层下钻。"""
    if dotted in params:
        return params[dotted]
    cur = params
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def signal_cache_key(params: dict) -> dict:
    """抽出参与信号计算的参数子集（键固定，缺失补 None，保证哈希结构稳定）。"""
    return {key: _get(params, key) for key in _SIGNAL_KEYS}


def signal_code_hash() -> str:
    """信号相关代码的内容哈希（不含 git_sha：改报告/改脚本不应让缓存失效）。

    取八个字节：4 个信号/风险模块的文件字节 + `_precompute_signals` 的源码文本。
    后者覆盖「预计算逻辑写在 pipeline 里」的部分，避免只改 pipeline 却命中旧缓存。
    """
    from etf_rotation import pipeline   # 延迟导入：pipeline 依赖 signals，避免循环导入

    h = hashlib.sha256()
    for rel in _SIGNAL_SOURCES:
        h.update((_PKG_ROOT / rel).read_bytes())
        h.update(b"\0")                 # 分隔符，防止相邻文件内容拼接产生歧义
    h.update(inspect.getsource(pipeline._precompute_signals).encode("utf-8"))
    return h.hexdigest()


def signal_id(params: dict, data_snapshot_id: str) -> str:
    """信号集身份：数据快照 + 信号参数 + 信号代码哈希，取前 12 位。"""
    payload = {
        "data_snapshot_id": data_snapshot_id,
        "params": signal_cache_key(params),
        "code_hash": signal_code_hash(),
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]
