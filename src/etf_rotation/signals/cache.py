"""信号身份（signal_id）与信号面板缓存（内容寻址）。

为什么需要独立的 `signal_id`：
- `run_id` 含 git_sha，改一行报告脚本就会变；但底层信号（动量/波动/市场状态/
  反转/过热线）完全没变，缓存不该失效。
- 因此信号身份只由「信号代码 + 数据快照 + 信号相关参数」决定，与组合层参数
  （去重阈值、持仓上限、成本、执行口径）无关。

公式：
    signal_id = sha256( json({data_snapshot_id, signal_params, code_hash}, sort_keys=True) )[:12]
    code_hash = sha256( signals/trend.py + signals/market_state.py + signals/reversal.py
                        + portfolio/risk_layers.py + pipeline._precompute_signals 源码 )

落盘（`data/cache/signals/{signal_id}/`，可用 `ETF_SIGNAL_CACHE_DIR` 覆盖根目录）：
    {field}.parquet   —— 每个信号面板一个文件（dtype 原样保留，zstd 压缩）
    scalars.parquet   —— 标量/文本列（regime/comp/nas_mom/…）一张表
    manifest.json     —— fields/dtypes/tickers/date_min/date_max/bytes/created_at/
                         code_hash/data_snapshot_id

写入纪律（缓存跨 worktree 共享，多个进程可能同时计算同一 sid）：
- 先写 `.tmp-{sid}-{pid}-{rand}/`，全部落盘并自检后 `os.rename` 成正式目录；
  正式目录一旦可见就一定是完整的，读者不会读到半成品。
- 正式目录已存在且 manifest 与本次内容一致 → 直接复用，不重写、不覆盖；
  内容不一致 → RuntimeError（同一 sid 出现两份不同内容说明代码/数据身份有 bug，
  静默覆盖会污染别人的缓存）。
- 面板 dtype 原样保存（不降精度）：缓存命中与现算必须逐位一致，否则会违反
  「只允许 N1 一个数值改动」的全局约束。

开关：`ETF_SIGNAL_CACHE=off` 关闭**读取**（强制重算，用于纯计算计时/校验），
算出后仍写盘供下次热跑；不设置或其它值表示读写都启用。
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from etf_rotation.data import paths

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

# 落盘的面板（交易日 × 标的；rev_active/llt80/zbias 是风险池子集列）。
PANEL_FIELDS = ("m21", "m60", "vol60", "zbias", "llt80", "rev_active")
# 落盘的标量/文本列（长度 = 交易日；regime 是字符串列，其余为数值）。
SCALAR_FIELDS = ("comp", "nas_mom", "gold_mom", "nas_vol", "gold_vol",
                 "cyb_vol", "cyb_below", "cyb_drop")
# 文本列：读回时统一把 None 归一成 NaN（保持与现算一致的「缺失」语义）。
_TEXT_FIELDS = ("regime",)

# 明确声明「派生、不落盘」：可由 close/amt 廉价重算，存起来只会增大缓存体积。
DERIVED_FIELDS = ("close", "ret", "n_days", "avg20")

# 判断「同一 sid 的两份内容是否等价」时比对的 manifest 字段（created_at 除外）。
_IDENTITY_KEYS = ("fields", "dtypes", "tickers", "field_tickers", "rows",
                  "date_min", "date_max", "code_hash", "data_snapshot_id")

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


def cache_root() -> Path:
    """缓存根目录：默认与 warehouse 同级的 `cache/signals`，可用环境变量覆盖。

    锚在 `paths.WAREHOUSE.parent` 而不是包目录：worktree 通过环境变量复用主检出
    的 data/，这样多个 worktree 天然共享同一份缓存（内容寻址，重复计算可复用）。
    """
    env = os.environ.get("ETF_SIGNAL_CACHE_DIR")
    if env:
        return Path(env)
    return paths.WAREHOUSE.parent / "cache" / "signals"


def price_hash(close: pd.DataFrame) -> str:
    """价格面板内容指纹：列名 + 日期索引 + 数值字节 → sha256[:12]。

    用途：manifest 里记下「这组信号是用哪份价格面板算的」。sid 只由参数/快照/代码
    决定，合成数据或换数据目录时可能算出同一个 sid；命中前比对价格指纹，不一致就
    按未命中处理，避免把别人的面板喂给策略。
    """
    h = hashlib.sha256()
    h.update("|".join(map(str, close.columns)).encode("utf-8"))
    h.update(b"\0")
    h.update(np.asarray(close.index.asi8, dtype="int64").tobytes())
    h.update(b"\0")
    h.update(np.ascontiguousarray(close.to_numpy(dtype="float64")).tobytes())
    return h.hexdigest()[:12]


def _dtype_label(df: pd.DataFrame) -> str:
    """面板的 dtype 标签：列 dtype 一致时记该 dtype，混合记 "mixed"。"""
    labels = {str(dt) for dt in df.dtypes}
    return labels.pop() if len(labels) == 1 else "mixed"


def _iso_date(value) -> str | None:
    """索引值 → `YYYY-MM-DD`（manifest 只认日期，避免带时区/时间的歧义）。"""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if hasattr(value, "date") and not isinstance(value, str):
        return value.date().isoformat()
    return str(value)[:10]


def _describe(panels: dict[str, pd.DataFrame], scalars: pd.DataFrame | None,
              sid: str, meta: dict) -> dict:
    """由本次内容生成 manifest（不含 created_at/bytes，便于复用判断）。"""
    panels = {k: v for k, v in panels.items() if isinstance(v, pd.DataFrame)}
    scalars = scalars if isinstance(scalars, pd.DataFrame) else pd.DataFrame()

    dtypes = {name: _dtype_label(df) for name, df in panels.items()}
    dtypes.update({str(col): str(dt) for col, dt in scalars.dtypes.items()})

    field_tickers = {name: sorted(map(str, df.columns)) for name, df in panels.items()}
    tickers = sorted({t for cols in field_tickers.values() for t in cols})

    indices = [df.index for df in panels.values()]
    if len(scalars.columns):
        indices.append(scalars.index)
    date_min = min((_iso_date(idx.min()) for idx in indices if len(idx)), default=None)
    date_max = max((_iso_date(idx.max()) for idx in indices if len(idx)), default=None)
    rows = max((len(idx) for idx in indices), default=0)

    manifest = {
        "signal_id": sid,
        "params": signal_cache_key(meta.get("params") or {}),
        "fields": [*panels, *map(str, scalars.columns)],
        "panels": list(panels),
        "scalars": [str(c) for c in scalars.columns],
        "dtypes": dtypes,
        "tickers": tickers,
        "field_tickers": field_tickers,
        "rows": rows,
        "date_min": date_min,
        "date_max": date_max,
        "code_hash": meta.get("code_hash") or signal_code_hash(),
        "data_snapshot_id": meta.get("data_snapshot_id") or "",
        "price_hash": meta.get("price_hash") or "",
    }
    return manifest


def _identity(manifest: dict) -> dict:
    """取出用于「内容是否等价」比对的子集（忽略 created_at/bytes/params）。"""
    return {key: manifest.get(key) for key in _IDENTITY_KEYS}


def _read_manifest(path: Path) -> dict | None:
    """读 manifest.json；缺失或损坏返回 None（损坏按「无缓存」处理并重算）。"""
    f = path / "manifest.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_manifest(path: Path, manifest: dict) -> None:
    """manifest 写入（暂存目录内，无需原子替换：目录尚未对外可见）。"""
    (path / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )


def save(panels: dict[str, pd.DataFrame], scalars: pd.DataFrame | None,
         sid: str, root: Path, meta: dict | None = None) -> Path:
    """把信号面板/标量表写入 `{root}/{sid}/`，返回目录（已存在且一致则直接复用）。

    原子性：先写 `{root}/.tmp-{sid}-{pid}-{rand}/`，写完 rename 成 `{root}/{sid}`。
    rename 在 POSIX/Windows 上都是原子的；若目标已存在（另一进程抢先写完），
    校验内容一致后丢弃自己的暂存目录，返回对方的目录。
    """
    root = Path(root)
    base = root / sid
    meta = meta or {}
    manifest = _describe(panels, scalars, sid, meta)

    existing = _read_manifest(base)
    if existing is not None:
        if _identity(existing) == _identity(manifest):
            return base                     # 复用：不重写一个字节
        # 共享缓存纪律：不删除、不覆盖别人的目录；本次内容不落盘（等人工排查身份冲突）
        warnings.warn(
            f"信号缓存 {base} 已存在且内容不一致"
            f"（已存 fields={existing.get('fields')} tickers={existing.get('tickers')}，"
            f"本次 fields={manifest['fields']} tickers={manifest['tickers']}）；"
            "保留原目录，本次结果不落盘",
            RuntimeWarning, stacklevel=2)
        return base

    root.mkdir(parents=True, exist_ok=True)
    tmp = root / f".tmp-{sid}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    if tmp.exists():                        # 极少见的 pid+随机碰撞：清掉重写
        shutil.rmtree(tmp)
    try:
        tmp.mkdir(parents=True)
        for name, df in panels.items():
            if not isinstance(df, pd.DataFrame):
                raise TypeError(f"panel {name!r} 必须是 DataFrame，得到 {type(df).__name__}")
            df.to_parquet(tmp / f"{name}.parquet", compression="zstd")
        if isinstance(scalars, pd.DataFrame) and len(scalars.columns):
            scalars.to_parquet(tmp / "scalars.parquet", compression="zstd")

        manifest["bytes"] = sum(p.stat().st_size for p in tmp.iterdir() if p.is_file())
        manifest["created_at"] = datetime.now(timezone.utc).isoformat()
        _write_manifest(tmp, manifest)

        try:
            os.rename(tmp, base)            # 原子发布
        except OSError:
            # 目标已存在（另一个进程刚发布完）：内容一致就复用，否则保留它并报错
            theirs = _read_manifest(base)
            if theirs is not None and _identity(theirs) == _identity(manifest):
                return base
            raise RuntimeError(f"信号缓存发布失败：{base} 已被占用且内容不一致")
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
    return base


def load(sid: str, root: Path, price_hash: str | None = None) -> dict | None:
    """读回 `{root}/{sid}/`；目录/manifest 缺失返回 None。

    返回 `{面板名: DataFrame, …, "scalars": DataFrame}`；派生字段（close/ret/
    n_days/avg20）不在这里，由调用方用原始价格/成交额重算。
    读取后逐项校验 tickers / 行数 / 日期范围与 dtype：与 manifest 不符说明缓存被
    手工改过（或写到一半崩溃），抛 RuntimeError 而不是把脏数据喂给策略。
    `price_hash` 给定时与 manifest 比对：不一致说明这份缓存不是用当前价格面板算的
    （例如合成数据/换数据目录撞了同一个 sid），按未命中处理（返回 None）。
    """
    root = Path(root)
    base = root / sid
    manifest = _read_manifest(base)
    if manifest is None:
        return None
    if price_hash and manifest.get("price_hash") and manifest["price_hash"] != price_hash:
        return None

    out: dict = {}
    for name in manifest.get("panels", []):
        f = base / f"{name}.parquet"
        if not f.exists():
            raise RuntimeError(f"信号缓存损坏：缺 {f}")
        df = pd.read_parquet(f)
        _check(name, df, manifest, per_field=True)
        out[name] = df

    # 全局 tickers 也要校验：manifest 的 tickers 是所有面板列名的并集
    if manifest.get("tickers") is not None:
        actual = sorted({str(t) for name in manifest.get("panels", [])
                         for t in out.get(name, pd.DataFrame()).columns})
        if actual != list(manifest["tickers"]):
            raise RuntimeError(
                f"信号缓存损坏：面板列并集 {actual} 与 manifest tickers "
                f"{manifest['tickers']} 不一致")

    scalars_fields = manifest.get("scalars", [])
    if scalars_fields:
        f = base / "scalars.parquet"
        if not f.exists():
            raise RuntimeError(f"信号缓存损坏：缺 {f}")
        scalars = pd.read_parquet(f)
        _check_scalars(scalars, manifest)
        out["scalars"] = restore_scalars(scalars)
    else:
        out["scalars"] = pd.DataFrame()
    return out


def _check(name: str, df: pd.DataFrame, manifest: dict, per_field: bool) -> None:
    """校验一个面板/标量表与 manifest 一致（列、行数、日期范围、dtype）。"""
    if per_field:
        expected = manifest.get("field_tickers", {}).get(name, manifest.get("tickers"))
        if expected is not None and sorted(map(str, df.columns)) != list(expected):
            raise RuntimeError(
                f"信号缓存损坏：{name} 列 {sorted(map(str, df.columns))} 与 manifest {expected} 不一致")
    if manifest.get("rows") is not None and len(df) > manifest["rows"]:
        raise RuntimeError(f"信号缓存损坏：{name} 行数 {len(df)} 超过 manifest {manifest['rows']}")
    if len(df.index):
        dmin, dmax = _iso_date(df.index.min()), _iso_date(df.index.max())
        if manifest.get("date_min") and dmin < manifest["date_min"]:
            raise RuntimeError(f"信号缓存损坏：{name} 起始日 {dmin} 早于 manifest {manifest['date_min']}")
        if manifest.get("date_max") and dmax > manifest["date_max"]:
            raise RuntimeError(f"信号缓存损坏：{name} 结束日 {dmax} 晚于 manifest {manifest['date_max']}")
    expected_dtype = manifest.get("dtypes", {}).get(name)
    label = _dtype_label(df)
    if expected_dtype and expected_dtype != "mixed" and label != "mixed" and label != expected_dtype:
        raise RuntimeError(f"信号缓存损坏：{name} dtype {label} 与 manifest {expected_dtype} 不一致")


def _check_scalars(scalars: pd.DataFrame, manifest: dict) -> None:
    """校验标量表：列名与 dtype 必须和 manifest 一致。"""
    expected = [str(c) for c in manifest.get("scalars", [])]
    if sorted(map(str, scalars.columns)) != sorted(expected):
        raise RuntimeError(
            f"信号缓存损坏：scalars 列 {sorted(map(str, scalars.columns))} 与 manifest {expected} 不一致")
    if not len(scalars.index):
        return
    dmin, dmax = _iso_date(scalars.index.min()), _iso_date(scalars.index.max())
    if manifest.get("date_min") and dmin < manifest["date_min"]:
        raise RuntimeError(f"信号缓存损坏：scalars 起始日 {dmin} 早于 manifest {manifest['date_min']}")
    if manifest.get("date_max") and dmax > manifest["date_max"]:
        raise RuntimeError(f"信号缓存损坏：scalars 结束日 {dmax} 晚于 manifest {manifest['date_max']}")


def restore_scalars(scalars: pd.DataFrame, manifest: dict | None = None) -> pd.DataFrame:
    """把 parquet 读回的对象列归一：文本列缺失统一为 NaN，数值列保持原 dtype。

    必要性：object 列里的 NaN 经 parquet 往返会变成 None；下游 `regime.loc[d]`
    若拿到 None 会当成有效状态参与比较，语义与现算（NaN）不一致。
    """
    out = scalars.copy()
    for col in out.columns:
        if out[col].dtype == object or str(col) in _TEXT_FIELDS:
            out[col] = out[col].astype(object).where(pd.notna(out[col]), np.nan)
    return out
