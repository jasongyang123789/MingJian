#!/usr/bin/env python3
"""Re-check the §9 profit-headline rule at trials=50.

Rule (backtest-scoring-rules.md §9): a case-arm profit decline_p enters
the headline iff decline_p >= 0.35 AND saturation category is
informative AND required_depth <= 0.35.

Inputs (all from THIS trials50 run, downside ON, seed 42):
- decline_p: the trials=50 profit MC baseline (03c anchor / 06c child
  files) for each B arm.
- category / required_depth: from the mode-path growth factors via
  planagent.services.simulation.downside_headline (imported from the
  trials50 worktree). The mode path is the deterministic NO-SHOCK
  trajectory: the seam-fix method uses OFF replay packages, because
  the ON replay carries the shock (verified below: this run's ON
  profit factors differ from the OFF factors). This run has no OFF
  batch, so the OFF factors are reused from the seam-fix fixed-code
  OFF replays (reference/seamfix/raw-*_off, committed in this harness dir) — legitimate
  because a replay package never depends on the trial count, and the
  simulation code path is unchanged (this run's ON replays are
  value-identical to the seam-fix ON replays — the immediate
  predecessor on the same code lineage, mainline 0dc3193 — checked
  below; milestone.py is scoring-only; the two newly merged branches
  are report-only / redteam-check-only). If the ON-vs-seam-fix check
  fails, the script stops instead of silently reusing the OFF factors.
  (Note: the A/C ON replays differ in tick-0 profit ONLY — the seam
  fix, which landed after A/C and is already in mainline — so A/C is
  the wrong reference here; the seam-fix ON batch is the right one.)

Trials=20 ON decline_p values are hardcoded from the A/C + seam-fix
reports for the side-by-side.

Run with the repo worktree venv:
    <worktree>/.venv/bin/python score_headlines.py
"""
from __future__ import annotations

import json
import os

import backtest_common  # repo root on sys.path, shared config

from planagent.services.simulation.downside_headline import (  # noqa: E402
    assess_decline_saturation,
    max_window_rise_over_support,
)

HERE = str(backtest_common.get_run_dir())
SEAMFIX = str(backtest_common.get_seamfix_ref())
# Reference ON batch: the seam-fix rerun (mainline 0dc3193 lineage),
# NOT A/C — A/C predates the seam fix and differs in tick-0 profit only.
REF_ON = SEAMFIX

# (case, raw subdir, B arm name, trials=20 ON decline_p)
B_ARMS = [
    ("desay-2015", "desay", "B invest smart cockpit ADAS", 0.6),
    ("huawei", "classic", "B 坚持投入", 0.45),
    ("desay-2020", "desay", "B aggressive intelligent driving push", 0.0),
    ("nokia", "classic", "B 转向触屏生态", 1.0),
]

# Engine unified default (Track C, downside.py — read from the worktree
# module, never hardcoded; same values as the seam-fix analysis).
from planagent.services.simulation.downside import (  # noqa: E402
    DOWNSIDE_DEFAULT_DEPTH,
    DOWNSIDE_DEFAULT_DURATION,
)


def tag_of(arm_name: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in arm_name.replace(" ", "_"))


def replay_factors(case_dir: str, arm: str, metric: str = "profit") -> list[float]:
    tag = tag_of(arm)
    path = os.path.join(case_dir, f"09-child-replay-{tag}.json")
    body = json.load(open(path))["body"]
    pkg = body.get("package")
    if isinstance(pkg, str):
        pkg = json.loads(pkg)
    traj = {}
    for snap in pkg.get("snapshots", []):
        value = (snap.get("state") or {}).get(metric)
        if value is not None:
            traj[int(snap["tick"])] = float(value)
    ticks = sorted(traj)
    return [traj[ticks[i + 1]] / traj[ticks[i]] for i in range(len(ticks) - 1)
            if traj[ticks[i]] != 0.0]


def main() -> None:
    depth_high = float(max(DOWNSIDE_DEFAULT_DEPTH))
    durations = tuple(sorted(float(d) for d in DOWNSIDE_DEFAULT_DURATION))
    max_rise = max_window_rise_over_support(durations)
    print(f"engine default: depth {tuple(DOWNSIDE_DEFAULT_DEPTH)}, "
          f"duration {tuple(DOWNSIDE_DEFAULT_DURATION)}, "
          f"depth_high={depth_high}, max_window_rise={max_rise:.3f}")
    out: dict = {}
    for case, sub, arm, dp20 in B_ARMS:
        case_dir = os.path.join(HERE, f"raw-{sub}", case)
        mc = json.load(open(os.path.join(
            case_dir, f"06c-mc-profit-{tag_of(arm)}.json")))["body"]
        assert mc["seed"] == 42 and mc["trials"] == 50, (case, mc["seed"], mc["trials"])
        dp50 = mc["baseline"].get("decline_probability")
        # Mode-path factors: this run's ON replays must be value-identical
        # to the seam-fix ON replays (same simulation code path, replays
        # are trials-independent) — that is the check that licenses
        # reusing the seam-fix OFF factors for the no-shock mode path.
        # The ON factors carry the shock and are NOT the mode path; the
        # OFF factors are, exactly as in the seam-fix report.
        f_on = replay_factors(case_dir, arm)
        ref_dir = os.path.join(REF_ON, f"raw-{sub}", case)
        f_ref = replay_factors(ref_dir, arm)
        if [round(x, 4) for x in f_on] != [round(x, 4) for x in f_ref]:
            raise SystemExit(
                f"{case}/{arm}: trials50 ON replay factors {f_on} != "
                f"seam-fix ON factors {f_ref} — simulation path moved; stop.")
        off_dir = os.path.join(SEAMFIX, f"raw-{sub}_off", case)
        f_off = replay_factors(off_dir, arm)
        dec = assess_decline_saturation(f_off, depth_high, max_rise)
        rd = None if dec.required_depth is None else round(dec.required_depth, 4)
        headline = bool(dp50 is not None and dp50 >= 0.35
                        and dec.category == "informative"
                        and rd is not None and rd <= 0.35)
        out[f"{case} B profit"] = {
            "decline_p_trials20_on": dp20, "decline_p_trials50_on": dp50,
            "category": dec.category, "required_depth": rd,
            "headline": headline,
            "mode_growth_factors": [round(g, 4) for g in f_off],
        }
        print(f"{case} B profit: decline_p {dp20} (t20) -> {dp50} (t50) | "
              f"category={dec.category} required_depth={rd} | "
              f"HEADLINE {'IN' if headline else 'OUT'} "
              f"(ON factors checked == seam-fix ON; OFF mode factors used)")
    json.dump(out, open(os.path.join(HERE, "headline-check.json"), "w"),
              indent=2, ensure_ascii=False)
    print("\nwrote headline-check.json")


if __name__ == "__main__":
    main()
