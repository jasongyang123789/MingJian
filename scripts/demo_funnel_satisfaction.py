"""Demo: B2B funnel conversion + satisfaction feedback as one-click
features (Track 4).

One click = an automotive run with the built-in template
(``variable_template_id: "builtin:automotive"``). No manual variable
overrides: the funnel rates, pipeline stocks, satisfaction score, and
overall conversion are all computed by the template's tick drivers.

Run from the worktree root with the worktree venv::

    .venv/bin/python scripts/demo_funnel_satisfaction.py

It boots the app against a throwaway SQLite DB in a temp dir (never
the standing local deployment), then shows, end to end:

1. a 6-tick baseline funnel trajectory (rates, stocks, satisfaction,
   overall conversion per tick);
2. the satisfaction -> next-RFQ feedback loop: the same seed with
   starting satisfaction 0.4 vs 0.9 — lower satisfaction means lower
   tick-1 RFQ rates and fewer RFQs / deliveries by tick 6;
3. the evidence-triggered complaint rule: a late-delivery claim fires
   ``auto.delivery_satisfaction_slip`` and dips tick-1 satisfaction
   below the baseline.
"""

from __future__ import annotations

import os
import tempfile

os.environ["PLANAGENT_EVENT_BUS_BACKEND"] = "memory"
os.environ["PLANAGENT_INLINE_INGEST_DEFAULT"] = "true"
os.environ["PLANAGENT_INLINE_SIMULATION_DEFAULT"] = "true"
os.environ["PLANAGENT_OPENAI_API_KEY"] = ""
os.environ["PLANAGENT_OPENAI_BASE_URL"] = ""

_TMPDIR = tempfile.mkdtemp(prefix="funnel-demo-")
os.environ["PLANAGENT_DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMPDIR}/demo.db"

from planagent.config import reset_settings_cache
from planagent.db import reset_database_cache
from planagent.main import create_app

reset_settings_cache()
reset_database_cache()

from fastapi.testclient import TestClient

HEADER = (
    f"{'tick':>4} {'prospects':>9} {'leads':>6} {'rfqs':>6} {'contr':>6} "
    f"{'proj':>6} {'deliv':>6} {'overall':>7} {'satisf':>6} {'l>rfq':>6} {'win':>6}"
)


def _payload(**overrides) -> dict:
    payload: dict = {
        "company_id": "funnel-demo-oem",
        "company_name": "Funnel Demo OEM",
        "market": "china-auto",
        "domain_id": "automotive",
        "actor_template": "tier1_supplier",
        "tick_count": 6,
        "seed": 7,
        "variable_template_id": "builtin:automotive",
    }
    payload.update(overrides)
    return payload


def _create_run(client: TestClient, **overrides) -> dict:
    created = client.post("/simulation/runs", json=_payload(**overrides))
    assert created.status_code == 201, created.text
    return created.json()


def _snapshots(client: TestClient, run_id: str) -> list[dict]:
    package = client.get(f"/runs/{run_id}/replay-package")
    assert package.status_code == 200, package.text
    return package.json()["package"]["snapshots"]


def _print_trajectory(title: str, snapshots: list[dict]) -> None:
    print(f"\n{title}")
    print(HEADER)
    for snapshot in snapshots:
        state = snapshot["state"]
        print(
            f"{snapshot['tick']:>4} "
            f"{state['funnel_prospects']:>9.2f} {state['funnel_leads']:>6.2f} "
            f"{state['funnel_rfqs']:>6.2f} {state['funnel_contracts']:>6.2f} "
            f"{state['funnel_projects']:>6.2f} {state['funnel_deliveries_total']:>6.2f} "
            f"{state['funnel_overall_conversion']:>7.3f} "
            f"{state['delivery_satisfaction']:>6.3f} "
            f"{state['funnel_lead_to_rfq_rate']:>6.3f} {state['funnel_rfq_win_rate']:>6.3f}"
        )


def main() -> None:
    with TestClient(create_app()) as client:
        baseline = _create_run(client)
        base_snaps = _snapshots(client, baseline["id"])
        _print_trajectory(
            "1) BASELINE — one click (builtin:automotive, 6 ticks, seed 7):",
            base_snaps,
        )

        low = _create_run(client, initial_state={"delivery_satisfaction": 0.4})
        high = _create_run(client, initial_state={"delivery_satisfaction": 0.9})
        low_snaps = _snapshots(client, low["id"])
        high_snaps = _snapshots(client, high["id"])
        print("\n2) SATISFACTION -> NEXT-RFQ FEEDBACK LOOP (same seed, only the")
        print("   starting satisfaction differs: 0.4 vs 0.9):")
        for label, snaps in (("low  (0.4)", low_snaps), ("high (0.9)", high_snaps)):
            tick1 = snaps[1]["state"]
            tick6 = snaps[6]["state"]
            print(
                f"   {label}: tick-1 lead->RFQ {tick1['funnel_lead_to_rfq_rate']:.3f}, "
                f"win {tick1['funnel_rfq_win_rate']:.3f} | tick-6 RFQs "
                f"{tick6['funnel_rfqs']:.2f}, deliveries "
                f"{tick6['funnel_deliveries_total']:.2f}, overall "
                f"{tick6['funnel_overall_conversion']:.3f}"
            )
        print("   -> low satisfaction: lower RFQ rates from tick 1, fewer RFQs")
        print("      and deliveries by tick 6. The loop is modeled, not overridden.")

        ingested = client.post(
            "/ingest/runs",
            json={
                "requested_by": "funnel-demo",
                "items": [
                    {
                        "source_type": "research",
                        "source_url": "https://example.com/funnel-demo-complaint",
                        "title": "Late delivery complaint",
                        "content_text": (
                            "A late delivery caused a customer complaint about "
                            "delivery satisfaction after a delivery delay."
                        ),
                        "published_at": "2026-01-05T08:00:00Z",
                    }
                ],
            },
        )
        assert ingested.status_code == 201, ingested.text
        items = client.get("/review/items").json()
        accepted = client.post(
            f"/review/items/{items[0]['id']}/accept",
            json={"reviewer_id": "funnel-demo"},
        )
        assert accepted.status_code == 200, accepted.text
        complaint = _create_run(client)
        complaint_snaps = _snapshots(client, complaint["id"])
        print("\n3) EVIDENCE-TRIGGERED RULE — late-delivery complaint ingested:")
        print(f"   matched rules: {complaint['summary'].get('matched_rules')}")
        print(
            f"   tick-1 satisfaction: baseline {base_snaps[1]['state']['delivery_satisfaction']:.4f} "
            f"vs complaint {complaint_snaps[1]['state']['delivery_satisfaction']:.4f}"
        )
        print("   -> the complaint dips satisfaction; the dip then feeds the")
        print("      next ticks' RFQ rates through the same feedback loop.")
        print(f"\nDemo DB (throwaway): {_TMPDIR}/demo.db")


if __name__ == "__main__":
    main()
