#!/usr/bin/env python3
"""Score the four milestone nodes at trials=50 with the product rule.

Reads the synced trials50 (FBOOK) anchor bands from $BACKTEST_RUN_DIR/trials50-fbook.db +
raw-classic/raw-desay (same percentile definition as the analyze
scripts: linear interpolation over the baseline trial runs), scores
each node with the single source of truth
``planagent.evaluation.milestone.score_milestone_node`` (new rule:
band-in + baseline-width cap W0 + point error <= 35%), and prints the
verdict table with the new band-edge-distance columns (absolute +
relative, from the ``band_edge_distance`` helper). Old band rule shown
as contrast. The trials=20 A/C values are hardcoded from
backtest-rerun-merged-ac-2026-11-23/REPORT.md for the side-by-side.

Run with the repo worktree venv so the import resolves to the
code under test:
    <worktree>/.venv/bin/python score_milestones.py
"""
from __future__ import annotations

import json
import os
import sqlite3

import backtest_common  # repo root on sys.path, shared config

from planagent.evaluation.milestone import (
    BASELINE_BAND_WIDTHS,
    band_edge_distance,
    old_rule_verdict,
    score_milestone_case,
    score_milestone_node,
)

HERE = str(backtest_common.get_run_dir())
DB = str(backtest_common.get_db_path())

# (case, raw subdir, field, anchor tick, actual, label)
NODES = [
    ("desay-2015", "desay", "revenue", 3, 5408.74, "desay-2015 revenue yr3"),
    ("desay-2020", "desay", "revenue", 3, 21908.0, "desay-2020 revenue yr3"),
    ("nokia", "classic", "market_share", 3, 0.27, "nokia share yr3"),
    ("nokia", "classic", "market_share", 5, 0.064, "nokia share yr5"),
    # Blockbuster partial case (branch fix/blockbuster-partial-case):
    # revenue milestones only, profit not built. Actuals are 10-K total
    # revenues: 2003 $5,911.7M, 2005 $5,551.1M (2009 10-K reclassified
    # series — see the case report).
    ("blockbuster", "classic", "revenue", 3, 5.9117, "blockbuster revenue yr3"),
    ("blockbuster", "classic", "revenue", 5, 5.5511, "blockbuster revenue yr5"),
]

# trials=20 A/C bands (REPORT.md §0/§3-§5), for the side-by-side.
AC20 = {
    "desay-2015 revenue yr3": {"p10": 6225.2611, "p50": 7541.0392, "p90": 8563.0103},
    "desay-2020 revenue yr3": {"p10": 25252.0497, "p50": 29726.4454, "p90": 33213.7481},
    "nokia share yr3": {"p10": 0.2343, "p50": 0.2732, "p90": 0.326},
    "nokia share yr5": {"p10": 0.0792, "p50": 0.0935, "p90": 0.1442},
}


def pct(vals, q):
    s = sorted(vals)
    if not s:
        return None
    i = (len(s) - 1) * q
    lo, hi = int(i), min(int(i) + 1, len(s) - 1)
    f = i - lo
    return round(s[lo] * (1 - f) + s[hi] * f, 4)


def band(con, trials, field, tick):
    ph = ",".join("?" * len(trials))
    rows = con.execute(
        f"SELECT json_extract(state, '$.{field}') FROM state_snapshots "
        f"WHERE run_id IN ({ph}) AND tick = ?",
        (*trials, tick),
    ).fetchall()
    vals = [r[0] for r in rows if r[0] is not None]
    return {"n": len(vals), "p10": pct(vals, 0.1), "p50": pct(vals, 0.5), "p90": pct(vals, 0.9)}


def load_mc(raw_dir, case, kind):
    fn = "03-anchor-monte-carlo.json" if kind == "share" else "03b-anchor-monte-carlo-revenue.json"
    return json.load(open(os.path.join(raw_dir, case, fn)))["body"]


def main():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = []
    for case, sub, field, tick, actual, label in NODES:
        w0 = BASELINE_BAND_WIDTHS[(case, field, tick)]
        raw = os.path.join(HERE, "raw-desay" if sub == "desay" else "raw-classic")
        mc = load_mc(raw, case, "share" if field == "market_share" else "revenue")
        assert mc["seed"] == 42 and mc["trials"] == 50, (label, mc["seed"], mc["trials"])
        b = band(con, mc["trial_run_ids"]["baseline"], field, tick)
        assert b["n"] == 50, (label, b)
        s = score_milestone_node(p10=b["p10"], p50=b["p50"], p90=b["p90"],
                                 actual=actual, baseline_width=w0)
        # Cross-check: helper agrees with the dataclass fields.
        assert band_edge_distance(b["p10"], b["p90"], actual) == s.band_edge_distance
        # Blockbuster has no trials=20 band on this caliber (the 11-19
        # rerun ran a different model — no template attach, trials 20);
        # its trials=20 column stays empty.
        a20 = AC20.get(label)
        s20 = (score_milestone_node(p10=a20["p10"], p50=a20["p50"], p90=a20["p90"],
                                    actual=actual, baseline_width=w0)
               if a20 is not None else None)
        rows.append((label, actual, w0, b, s, a20, s20))
        print(f"{label}: n=50 band [{b['p10']}, {b['p50']}, {b['p90']}] "
              f"width={s.width:.4f} W/W0={s.width_ratio:.2f} "
              f"point_err={100 * s.point_error:.1f}% in_band={s.in_band} "
              f"edge_dist={s.band_edge_distance} ({100 * s.band_edge_distance_rel:.2f}%) "
              f"OLD={old_rule_verdict(b['p10'], b['p90'], actual)} "
              f"NEW={s.verdict} ({s.reason})")
        if s20 is not None:
            print(f"    trials=20: band [{a20['p10']}, {a20['p50']}, {a20['p90']}] "
                  f"edge_dist={s20.band_edge_distance} ({100 * s20.band_edge_distance_rel:.2f}%) "
                  f"NEW={s20.verdict} ({s20.reason})")
    con.close()
    print("\n== case verdicts (worst node, new rule) ==")
    for case in ("desay-2015", "desay-2020", "nokia", "blockbuster"):
        nodes50 = [r[4] for r in rows if r[0].startswith(case)]
        nodes20 = [r[6] for r in rows if r[0].startswith(case)]
        if case == "blockbuster":
            # No trials=20 band on this caliber (the 11-19 rerun ran a
            # different model); the trials=20 column is not scored.
            print(f"  {case}: trials=50 {score_milestone_case(nodes50)}")
            continue
        print(f"  {case}: trials=20 {score_milestone_case(nodes20)} "
              f"-> trials=50 {score_milestone_case(nodes50)}")
    print("  huawei: PASS (qualitative carve-out — not scored by this rule)")
    out = {}
    for label, actual, w0, b, s, a20, s20 in rows:
        entry = {
            "actual": actual, "w0": w0,
            "trials50": {"p10": b["p10"], "p50": b["p50"], "p90": b["p90"],
                         "width": round(s.width, 4), "width_ratio": round(s.width_ratio, 4),
                         "point_error_pct": round(100 * s.point_error, 2),
                         "in_band": s.in_band,
                         "band_edge_distance": s.band_edge_distance,
                         "band_edge_distance_rel": round(s.band_edge_distance_rel, 6),
                         "old_verdict": old_rule_verdict(b["p10"], b["p90"], actual),
                         "new_verdict": s.verdict, "new_reason": s.reason},
        }
        if s20 is not None:
            entry["trials20"] = {"p10": a20["p10"], "p50": a20["p50"], "p90": a20["p90"],
                                 "band_edge_distance": s20.band_edge_distance,
                                 "band_edge_distance_rel": round(s20.band_edge_distance_rel, 6),
                                 "new_verdict": s20.verdict, "new_reason": s20.reason}
        out[label] = entry
    json.dump(out, open(os.path.join(HERE, "milestone-scores.json"), "w"),
              indent=2, ensure_ascii=False)
    print("\nwrote milestone-scores.json")


if __name__ == "__main__":
    main()
