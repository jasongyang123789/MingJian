# trials50 backtest harness (FBOOK)

Four-case backtest rerun (Desay 2015, Desay 2020, Huawei 2000, Nokia 2007),
downside ON, trials=50, seed 42 — the canonical re-run tool for the
strategy-engine mainline. Ported into the repo from the research workspace
(`sync-trials50-harness-fbook-2026-11-24/`); the order-book driver now lives
in the template (finite-book depletion, FBOOK — step-1 merge 734ffdd), and
these runners carry no order-book driver of their own.

## Run order

```bash
# 1. Gate preflight (write-denial gate probe; exit 0 iff the gate is open)
python3 probe_gate.py

# 2. Scratch backend on :8024 with its own DB (never touches :8000/3000)
./start-backend.sh

# 3. Runners, in order (all write under $BACKTEST_RUN_DIR; ambient env —
#    do NOT apply `env -u NO_PROXY -u no_proxy` to these urllib scripts)
python3 acme_smoke.py      # Acme P50 must be exactly 99.8143
python3 run_classic.py     # Huawei / Nokia
python3 run_desay.py       # Desay 2015 / 2020
python3 run_profit_mc.py   # profit MC per case x arm
python3 analyze_desay.py   # prints bands + trajectories (stdout)
python3 analyze_classic.py # prints bands + trajectories (stdout)
python3 score_milestones.py  # writes milestone-scores.json
python3 score_headlines.py   # EXPECTED exit 1 under FBOOK (fail-loud, see below)
```

Run every step with the repo worktree venv
(`<worktree>/.venv/bin/python`) so `import planagent` resolves to the
checkout under test. Stop the scratch backend afterwards
(`pkill -f "uvicorn planagent.main:app --host 127.0.0.1 --port 8024"` or
the pid printed by start-backend.sh).

## Env vars

| Var | Default | Meaning |
|---|---|---|
| `BACKTEST_BASE` | `http://127.0.0.1:8024` | Scratch-backend base URL |
| `BACKTEST_PORT` | `8024` | Scratch-backend port (start-backend.sh) |
| `BACKTEST_RUN_DIR` | `~/.cache/mingjian-backtest/trials50-fbook` | Raw JSON / DB / summaries / logs (outside the repo) |
| `PLANAGENT_LOCAL_PROXY_SECRET` | — | Proxy secret (else `$BACKTEST_RUN_DIR/.proxy-secret`, else `BACKTEST_LOCAL_ENV` file) |
| `BACKTEST_LOCAL_ENV` | — | File holding `PLANAGENT_LOCAL_PROXY_SECRET=...` |
| `BACKTEST_SEAMFIX_REF` | `reference/seamfix/` | Seam-fix reference replay dir (score_headlines.py) |
| `BACKTEST_PROBE_DIR` | `tempfile.gettempdir()` | probe_gate.py write-probe directory |

## Expected baseline (FBOOK, downside ON, trials=50, seed 42)

| Case | B revenue P50 (normal value) | B profit P50 | Milestone (2026-11-20 rule) |
|---|---|---|---|
| Desay 2015 | 6325.4227 | 545.9082 | FAIL (width-only 1.98×W0, in-band) |
| Desay 2020 | 24785.9835 | 1889.1961 | FAIL (width-only 1.77×W0, in-band) |
| Huawei 2000 | 926.4655 | 123.3999 | PASS (qualitative) |
| Nokia 2007 | 29.6101 | 4.0535 | PARTIAL |

Tripwire (2015 B normal-value P50 vs 9178.73 line): **CLEAR** — 6325.4227
is 2853.31 (31.1%) below the line. Old-form (pre-FBOOK) numbers
(2015 B 7518.0782, 2020 B 34856.6101) remain on record in the step-1 /
trials50 reports in the research workspace; old and new baselines are
not directly comparable (the model form changed, not the sampling).

## Notes

- `score_headlines.py` exits 1 under FBOOK by design (fail-loud): the
  trials50 ON replay factors moved vs the seam-fix ON reference, so it
  stops instead of silently reusing the seam-fix OFF factors. The
  headline set still stands from the fresh profit MC (decline_p 0.48 →
  {2015 B}). The reference replay packages it checks against live in
  `reference/seamfix/` (B-arm `09-child-replay` files, ON + OFF).
- The 2018 Desay case is NOT part of this harness (separate case build,
  `fix/desay-2018-case`, marked non-independent).
- `run_desay_gapb.py` is intentionally not included (gapb-specific retest,
  not part of the four-case harness).
