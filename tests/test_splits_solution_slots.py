"""Solution-slot gate tests (S-layer real splits, 2026-11-18).

The supplier-share sum gate groups rows by (product, solution code),
not by product alone: different solutions of one product line coexist
independently (Ho Q7), each carrying its own supplier split, while
two suppliers splitting ONE solution must still sum to 1 (the FAW-VW
pattern). The one-host backstop stays product-level across solutions.
Uncoded rows group into one slot per product, preserving Phase 1
behavior for structures without solution codes.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from planagent.services.splits import (
    OemProductionShares,
    SplitStructure,
    evaluate_prompts,
    validate_oem_shares,
    validate_split_structure,
)


def _row(
    product: str,
    fitment: float,
    supplier: str,
    share: float,
    code: str | None = None,
    kind: str = "rate",
    price: float = 1000.0,
) -> dict:
    row: dict = {
        "product_id": product,
        "fitment_kind": kind,
        "fitment": fitment,
        "supplier_id": supplier,
        "supplier_share": share,
        "price": price,
    }
    if code is not None:
        row["solution_code"] = code
    return row


def _structure(fitments: list[dict]) -> SplitStructure:
    return SplitStructure.model_validate(
        {
            "oems": [
                {
                    "oem_id": "hongqi",
                    "customer_status": "existing",
                    "nameplates": [
                        {
                            "nameplate_id": "h5",
                            "energy": "ICE",
                            "price_band": "15-20",
                            "share": 1.0,
                            "model_year": 2026,
                            "generations": [
                                {
                                    "generation_id": "current",
                                    "lifecycle_phase": "mature",
                                    "share": 1.0,
                                    "trims": [
                                        {
                                            "trim_id": "all",
                                            "share": 1.0,
                                            "fitments": fitments,
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    )


def _kinds(structure: SplitStructure) -> list[str]:
    return [issue.kind for issue in validate_split_structure(structure).issues]


def test_two_solutions_same_supplier_validate() -> None:
    """Hongqi H5 P03: instrument + central screens, same supplier, each
    at full fitment with its own full supplier split — valid."""

    structure = _structure(
        [
            _row("P03", 1.0, "佛吉亚", 1.0, code="仪表10.25inch"),
            _row("P03", 1.0, "佛吉亚", 1.0, code="中控15.6inch"),
        ]
    )
    assert validate_split_structure(structure).is_valid is True


def test_two_solutions_different_suppliers_validate() -> None:
    """Hongqi E-H7 P03: two solutions from different suppliers, each
    fully supplied — valid (the per-product slot halved these)."""

    structure = _structure(
        [
            _row("P03", 1.0, "富赛", 1.0, code="仪表8.88inch"),
            _row("P03", 1.0, "天马", 1.0, code="中控17.3inch"),
        ]
    )
    assert validate_split_structure(structure).is_valid is True


def test_same_solution_supplier_split_must_sum_to_one() -> None:
    """The FAW-VW pattern: two suppliers splitting ONE solution must
    sum to 1 — the gate still refuses 0.6 + 0.3."""

    structure = _structure(
        [
            _row("P01", 1.0, "ho", 0.6, code="SA8155P"),
            _row("P01", 1.0, "other", 0.3, code="SA8155P"),
        ]
    )
    assert "supplier_shares_sum" in _kinds(structure)


def test_same_solution_supplier_split_valid() -> None:
    """Two suppliers splitting one solution 0.9/0.1 — valid."""

    structure = _structure(
        [
            _row("P01", 1.0, "ho", 0.9, code="SA8155P"),
            _row("P01", 1.0, "other", 0.1, code="SA8155P"),
        ]
    )
    assert validate_split_structure(structure).is_valid is True


def test_duplicate_supplier_same_solution_refused() -> None:
    """The same supplier twice for the same solution slot refuses."""

    structure = _structure(
        [
            _row("P03", 1.0, "佛吉亚", 0.5, code="仪表10.25inch"),
            _row("P03", 1.0, "佛吉亚", 0.5, code="仪表10.25inch"),
        ]
    )
    assert "duplicate_supplier_slot" in _kinds(structure)


def test_uncoded_rows_group_per_product() -> None:
    """Phase 1 behavior preserved: uncoded rows of one product share
    one slot, so 1.0 + 1.0 refuses and 0.5 + 0.5 validates."""

    refused = _structure(
        [_row("P03", 1.0, "a", 1.0), _row("P03", 1.0, "b", 1.0)]
    )
    assert "supplier_shares_sum" in _kinds(refused)
    valid = _structure([_row("P03", 1.0, "a", 0.5), _row("P03", 1.0, "b", 0.5)])
    assert validate_split_structure(valid).is_valid is True


def test_one_host_backstop_spans_solutions() -> None:
    """Two full-penetration P01 solutions in one trim still mean two
    hosts per car: refused. The E-H7 pattern (0.5 + 0.5, weighted
    exactly 1.0) validates."""

    refused = _structure(
        [
            _row("P01", 1.0, "东软", 1.0, code="8155"),
            _row("P01", 1.0, "东软", 1.0, code="8397"),
        ]
    )
    assert "one_host_fitment_exceeded" in _kinds(refused)
    valid = _structure(
        [
            _row("P01", 0.5, "东软", 1.0, code="8155"),
            _row("P01", 0.5, "东软", 1.0, code="8397"),
        ]
    )
    assert validate_split_structure(valid).is_valid is True


def test_p05_supplier_split_counts_once_in_ladder() -> None:
    """R2 ladder: a 10-camera group split across two suppliers (rate
    rows, 0.5/0.5) counts 10, not 20 — no R2 flag against the 8650
    ladder (10 for 2026)."""

    structure = _structure(
        [
            _row("P02", 1.0, "卓驭", 1.0, code="8650"),
            _row(
                "P05",
                1.0,
                "海康",
                0.5,
                code="环视摄像头*4 前视三目摄像头*1 侧视摄像头*2 后视摄像头*1",
            ),
            _row(
                "P05",
                1.0,
                "卓驭",
                0.5,
                code="环视摄像头*4 前视三目摄像头*1 侧视摄像头*2 后视摄像头*1",
            ),
        ]
    )
    report = evaluate_prompts(structure)
    assert [p for p in report.prompts if p.rule_id == "R2"] == []


def test_p05_count_split_counts_once_in_ladder() -> None:
    """R2 ladder, count-kind variant: an 11-camera count split across
    two suppliers (0.5/0.5) counts 11 — no R2 flag against the
    RHP/NGX ladder (11)."""

    structure = _structure(
        [
            _row("P02", 0.8, "ho", 1.0, code="RHP:SA8650"),
            _row("P05", 11.0, "a", 0.5, kind="count"),
            _row("P05", 11.0, "b", 0.5, kind="count"),
        ]
    )
    report = evaluate_prompts(structure)
    assert [p for p in report.prompts if p.rule_id == "R2"] == []


# --- Stored OEM shares: model + gate ---------------------------------------


def test_oem_shares_model_rejects_bad_values() -> None:
    with pytest.raises(ValidationError):
        OemProductionShares(shares={"a": 1.5}, source="test")
    with pytest.raises(ValidationError):
        OemProductionShares(shares={}, source="test")
    with pytest.raises(ValidationError):
        OemProductionShares(shares={"a": 1.0}, source="")


def test_validate_oem_shares_accepts_exact_coverage() -> None:
    structure = SplitStructure.model_validate(
        {
            "oems": [
                {
                    "oem_id": "a",
                    "customer_status": "existing",
                    "nameplates": [
                        {
                            "nameplate_id": "n1",
                            "energy": "ICE",
                            "price_band": "x",
                            "share": 1.0,
                            "generations": [
                                {
                                    "generation_id": "g",
                                    "lifecycle_phase": "mature",
                                    "share": 1.0,
                                    "trims": [
                                        {
                                            "trim_id": "t",
                                            "share": 1.0,
                                            "fitments": [
                                                _row("P01", 1.0, "s", 1.0)
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
                {
                    "oem_id": "b",
                    "customer_status": "prospect",
                    "nameplates": [
                        {
                            "nameplate_id": "n2",
                            "energy": "ICE",
                            "price_band": "x",
                            "share": 1.0,
                            "generations": [
                                {
                                    "generation_id": "g",
                                    "lifecycle_phase": "mature",
                                    "share": 1.0,
                                    "trims": [
                                        {
                                            "trim_id": "t",
                                            "share": 1.0,
                                            "fitments": [
                                                _row("P01", 1.0, "s", 1.0)
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
            ]
        }
    )
    good = OemProductionShares(shares={"a": 0.6, "b": 0.4}, source="test")
    assert validate_oem_shares(structure, good) == []
    unknown = OemProductionShares(shares={"a": 0.6, "zzz": 0.4}, source="test")
    kinds = [issue.kind for issue in validate_oem_shares(structure, unknown)]
    assert "oem_shares_unknown_oem" in kinds
    assert "oem_shares_missing_oem" in kinds
    bad_sum = OemProductionShares(shares={"a": 0.6, "b": 0.3}, source="test")
    kinds = [issue.kind for issue in validate_oem_shares(structure, bad_sum)]
    assert kinds == ["oem_shares_sum"]
    zero_prospect = OemProductionShares(shares={"a": 1.0, "b": 0.0}, source="test")
    assert validate_oem_shares(structure, zero_prospect) == []
