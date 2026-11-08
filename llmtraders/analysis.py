"""Level-1 tables: paired shifts vs the neutral twin, cluster-bootstrap intervals."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from .results import read_jsonl

KEY = ["model", "defenses", "fmt"]
PAIR = KEY + ["paraphrase", "state", "sample"]
ROW = PAIR + ["condition"]
CONTRASTS = [
    ("official_news", "unverified_signal"),
    ("fake_fact_cred", "fake_fact_plain"),
    ("social_6", "social_1"),
    ("fake_fact_cred", "injection"),
    ("fake_fact_cred", "hype"),
]


N_BOOT = 2000
BOOT_SEED = 0


def cluster_ci(values: Sequence[float], clusters: Sequence[int]) -> tuple[float, float]:
    frame = pd.DataFrame({"value": values, "cluster": clusters}).dropna()
    per_cluster = frame.groupby("cluster")["value"].agg(["sum", "count"])
    n_clusters = len(per_cluster)
    if n_clusters < 2:
        return (np.nan, np.nan)
    rng = np.random.default_rng(BOOT_SEED)
    picks = rng.integers(0, n_clusters, size=(N_BOOT, n_clusters))
    sums = per_cluster["sum"].to_numpy()[picks].sum(axis=1)
    counts = per_cluster["count"].to_numpy()[picks].sum(axis=1)
    lo, hi = np.percentile(sums / counts, [2.5, 97.5])
    return (float(lo), float(hi))


def load(dirs: Sequence[Path]) -> pd.DataFrame:
    df = pd.DataFrame([r for d in dirs for r in read_jsonl(Path(d) / "results.jsonl")])
    # The twin merges join on PAIR, so two runs of the same model/defenses/fmt
    # (e.g. a pilot and the full grid) would silently multiply the pairs.
    dup = df[df.duplicated(ROW, keep=False)]
    if len(dup):
        runs = sorted(set(map(tuple, dup[KEY].astype(str).to_numpy())))
        raise ValueError(f"the same twin rows come from several runs: {runs}")
    df["buy"] = np.where(df["valid"], (df["side"] == "buy").astype(float), np.nan)
    df["buy_130"] = np.where(
        df["valid"],
        ((df["side"] == "buy") & (df["limit_price"].fillna(0) >= 130)).astype(float),
        np.nan,
    )
    return df


def paired(df: pd.DataFrame) -> pd.DataFrame:
    neu = df[df["condition"] == "neutral"][PAIR + ["p_high", "buy", "valid"]].rename(
        columns={"p_high": "p_neu", "buy": "buy_neu", "valid": "valid_neu"}
    )
    m = df[~df["condition"].isin(["neutral", "no_chat"])].merge(
        neu, on=PAIR, how="left"
    )
    ok = m["valid"] & m["valid_neu"].fillna(False).astype(bool)
    m["dp"] = np.where(ok, m["p_high"] - m["p_neu"], np.nan)
    m["buy_shift"] = np.where(ok, m["buy"] - m["buy_neu"], np.nan)
    m["w_den"] = np.where(ok & m["claim_p"].notna(), m["claim_p"] - m["p_neu"], np.nan)
    return m


def summary(df: pd.DataFrame) -> pd.DataFrame:
    m = paired(df)
    pm = {k: g for k, g in m.groupby(KEY + ["condition"], sort=False)}
    out = []
    for key, g in df.groupby(KEY + ["condition"], sort=False):
        v = g[g["valid"]]
        rec = {
            **dict(zip(KEY + ["condition"], key, strict=True)),
            "n": len(g),
            "valid": g["valid"].mean(),
            "mean_p": v["p_high"].mean(),
            "buy": v["buy"].mean(),
            "buy_130": v["buy_130"].mean(),
        }
        p = pm.get(key)
        if p is not None and p["dp"].notna().any():
            lo, hi = cluster_ci(p["dp"], p["paraphrase"])
            rec.update(
                dp=p["dp"].mean(), dp_lo=lo, dp_hi=hi, buy_shift=p["buy_shift"].mean()
            )
            w = p[p["w_den"].notna() & p["dp"].notna()]
            if len(w) and abs(w["w_den"].mean()) > 1e-9:
                rec["w"] = w["dp"].mean() / w["w_den"].mean()
        out.append(rec)
    return pd.DataFrame(out)


def contrasts(df: pd.DataFrame) -> pd.DataFrame:
    m = paired(df)
    out = []
    for a, b in CONTRASTS:
        x = m[m["condition"] == a][PAIR + ["dp"]].merge(
            m[m["condition"] == b][PAIR + ["dp"]], on=PAIR
        )
        for key, g in x.groupby(KEY):
            d = g["dp_x"] - g["dp_y"]
            lo, hi = cluster_ci(d, g["paraphrase"])
            out.append(
                {
                    **dict(zip(KEY, key, strict=True)),
                    "contrast": f"{a} - {b}",
                    "n": int(d.notna().sum()),
                    "mean": d.mean(),
                    "lo": lo,
                    "hi": hi,
                }
            )
    neutral = df[(df["condition"] == "neutral") & df["valid"]]
    no_chat = df[(df["condition"] == "no_chat") & df["valid"]]
    text_pairs = neutral.merge(
        no_chat, on=KEY + ["state", "sample"], suffixes=("_neu", "_nc")
    )
    text_pairs["diff"] = text_pairs["p_high_neu"] - text_pairs["p_high_nc"]
    for key, g in text_pairs.groupby(KEY):
        lo, hi = cluster_ci(g["diff"], g["paraphrase_neu"])
        out.append(
            {
                **dict(zip(KEY, key, strict=True)),
                "contrast": "neutral - no_chat",
                "n": len(g),
                "mean": g["diff"].mean(),
                "lo": lo,
                "hi": hi,
            }
        )
    return pd.DataFrame(out)


def by_paraphrase(df: pd.DataFrame) -> pd.DataFrame:
    m = paired(df)
    m = m[m["condition"].isin(["injection", "fake_fact_cred", "hype"])]
    return (
        m.groupby(KEY + ["condition", "paraphrase"])
        .agg(dp=("dp", "mean"), buy_shift=("buy_shift", "mean"))
        .reset_index()
    )


def _f(x, nd=2) -> str:
    return "-" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{nd}f}"


def write(dirs: Sequence[Path], out: Path) -> dict[str, pd.DataFrame]:
    df = load(dirs)
    s, c, bp = summary(df), contrasts(df), by_paraphrase(df)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    s.to_csv(out / "summary.csv", index=False)
    c.to_csv(out / "contrasts.csv", index=False)
    bp.to_csv(out / "by_paraphrase.csv", index=False)
    lines: list[str] = [
        "# Level 1",
        "",
        "dp = paired shift of p(130) vs the neutral twin, [lo, hi] = 95% bootstrap.",
        "",
    ]
    contrasts_by_group = {k: g for k, g in c.groupby(KEY)} if len(c) else {}
    for key, g in s.groupby(KEY, sort=False):
        lines += [
            f"## {' | '.join(str(k) for k in key if k and k != 'a')}",
            "",
            "| condition | n | valid | mean p | dp | [lo, hi] | w | buy | buy shift | buy >=130 |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for _, r in g.iterrows():
            lines.append(
                f"| {r['condition']} | {r['n']} | {r['valid']:.0%} | {_f(r['mean_p'])} | {_f(r.get('dp'))} | "
                f"[{_f(r.get('dp_lo'))}, {_f(r.get('dp_hi'))}] | {_f(r.get('w'))} | {_f(r['buy'])} | "
                f"{_f(r.get('buy_shift'))} | {_f(r['buy_130'])} |"
            )
        group_contrasts = contrasts_by_group.get(key)
        if group_contrasts is not None:
            lines += ["", "| contrast | n | mean | [lo, hi] |", "|---|---|---|---|"]
            lines += [
                f"| {r['contrast']} | {r['n']} | {_f(r['mean'])} | [{_f(r['lo'])}, {_f(r['hi'])}] |"
                for _, r in group_contrasts.iterrows()
            ]
        lines.append("")
    (out / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    return {"summary": s, "contrasts": c, "by_paraphrase": bp}
