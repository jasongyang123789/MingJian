"""API tests for the opportunity endpoints (Step 4, 2026-11-24).

POST /opportunities/review (T2–T4 review checks) and POST
/opportunities/two-value (Ho's two-value output). Both are pure
functions of their input: no DB rows are read or written by the
handlers themselves; the isolated-SQLite setup mirrors the
completeness API tests so create_app() boots the same way.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from planagent.config import reset_settings_cache
from planagent.db import reset_database_cache
from planagent.main import create_app


def build_database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def setup_app(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(
        "PLANAGENT_DATABASE_URL", build_database_url(tmp_path / "opportunities-test.db")
    )
    monkeypatch.setenv("PLANAGENT_EVENT_BUS_BACKEND", "memory")
    monkeypatch.setenv("PLANAGENT_INLINE_INGEST_DEFAULT", "true")
    monkeypatch.setenv("PLANAGENT_INLINE_SIMULATION_DEFAULT", "true")
    monkeypatch.setenv("PLANAGENT_OPENAI_API_KEY", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reset_settings_cache()
    reset_database_cache()


def _two_value_payload() -> dict:
    def rec(p50: float, replay: float) -> dict:
        return {
            "metric": "revenue",
            "unit": "RMB m",
            "horizon_tick": 3,
            "horizon_label": "yr3",
            "p50": p50,
            "replay": replay,
            "seed": 42,
            "trials": 20,
        }

    return {
        "case_id": "desay-2015",
        "metric": "revenue",
        "unit": "RMB m",
        "horizon_tick": 3,
        "horizon_label": "yr3",
        "full": rec(7541.0392, 6503.7701),
        "stripped_all": rec(4789.2662, 4789.2662),
        "legs": [
            {
                "leg_id": "backlog",
                "label": "order-book backlog",
                "stripped": rec(5145.5631, 5145.5631),
            },
            {
                "leg_id": "adas",
                "label": "ADAS chain",
                "stripped": rec(6105.8924, 6105.8924),
            },
        ],
        "actual": 5408.74,
        "sizing": "decision_time",
        "legs_note": "backlog_conversion=0; adas_coupling=0 + adas_share_coupling=0",
    }


def test_review_returns_t2_t3_t4_in_order(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        response = client.post(
            "/opportunities/review",
            json={
                "period_label": "2021",
                "actual_first_year_growth": 0.4074,
                "modeled_first_year_growth": 0.1875,
                "fitted": [
                    {
                        "variable_id": "nev_coupling",
                        "fitted_value": 2.08,
                        "distribution_max": 0.40,
                        "target_label": "year-5 收入 32557.18",
                    }
                ],
                "orders_growth": 0.71,
                "orders_to_revenue": 1.76,
                "orders_label": "2021 年新获订单",
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [p["trigger_id"] for p in body["prompts"]] == ["T2", "T3", "T4"]
    assert body["prompts"][1]["details"]["stretch_ratio"] == pytest.approx(5.2)


def test_review_empty_inputs_return_no_prompts(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        response = client.post("/opportunities/review", json={})
    assert response.status_code == 200, response.text
    assert response.json() == {"prompts": []}


def test_two_value_returns_both_values_separately(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        response = client.post("/opportunities/two-value", json=_two_value_payload())
    assert response.status_code == 200, response.text
    body = response.json()
    # (a) normal, (b) opportunity — separate fields, never merged.
    assert body["normal_adjusted_p50"] == pytest.approx(5826.54, abs=0.01)
    assert body["normal_frozen_p50"] == pytest.approx(4789.27, abs=0.01)
    assert body["opportunity_total_clean"] == pytest.approx(1714.50, abs=0.01)
    assert body["opportunity_total_apparent"] == pytest.approx(2751.77, abs=0.01)
    assert body["combined_reference_p50"] == pytest.approx(7541.04, abs=0.01)
    assert body["residual_adjusted_pct"] == pytest.approx(7.7, abs=0.1)
    assert body["sizing"] == "decision_time"
    assert body["legs_stripped"] == ["backlog", "adas"]
    # The two values are separate fields; there is no merged field.
    assert "merged_value" not in body
    assert "forecast" not in body


def test_two_value_rejects_mismatched_pairs(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    payload = _two_value_payload()
    payload["stripped_all"]["seed"] = 7
    with TestClient(create_app()) as client:
        response = client.post("/opportunities/two-value", json=payload)
    assert response.status_code == 422
    assert "seed" in response.json()["detail"]
