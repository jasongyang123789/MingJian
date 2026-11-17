"""P.O sub-product catalog (Phase 2, Ho Q8 ruling).

Ho 2026-11-16: P.O is decomposed to the finest workable granularity —
HUD, radar, gateway, and body-domain each carry their own penetration
dimension, and APA / AVM / UWB are all broken down in full detail.
Structure first: sub-products with no workbook data (APA, AVM, UWB)
exist as catalog entries whose fitment rates are explicit labeled
assumption parameters, never invented values.

The catalog is keyed by canonical sub-product id. A split-structure
row carries the sub-product as its ``product_id``; ``product_line_of``
maps every catalog id back to the ``"P.O"`` product line. A bare
``"P.O"`` row is the undecomposed basket: the prompt engine flags it
for decomposition (rule R13), never refuses it.

Evidence grades follow the verification report: ``B`` = market-table
series exist (industry-average table, calibers as noted);
``assumption`` = definition only, no workbook or public series.
"""

from __future__ import annotations

from typing import Literal

FitmentKind = Literal["rate", "count"]


class PoSubProduct:
    """One decomposed P.O sub-product."""

    def __init__(
        self,
        sub_id: str,
        label: str,
        fitment_kind: FitmentKind,
        evidence: str,
        assumption: bool,
        notes: str = "",
    ) -> None:
        self.sub_id = sub_id
        self.label = label
        self.fitment_kind = fitment_kind
        self.evidence = evidence
        self.assumption = assumption
        self.notes = notes

    def to_dict(self) -> dict:
        return {
            "sub_id": self.sub_id,
            "label": self.label,
            "fitment_kind": self.fitment_kind,
            "evidence": self.evidence,
            "assumption": self.assumption,
            "notes": self.notes,
        }


PO_SUBPRODUCTS: dict[str, PoSubProduct] = {
    entry.sub_id: entry
    for entry in [
        PoSubProduct(
            "HUD_AR",
            "AR-HUD",
            "rate",
            "B: industry-average table 0.116->0.35 (2026-2031); GGAI 2024 88.43k units (+273%)",
            False,
            "HUD variant rates are independent penetrations (Ho Q7): P-HUD coexists with W-HUD/AR-HUD on the same vehicle (Ho 2026-11-17 ruling), so variant rates are never summed to 1 and no HUD-slot exclusivity is assumed.",
        ),
        PoSubProduct(
            "HUD_W",
            "W-HUD",
            "rate",
            "B: industry-average table 0.22->0.23; HUD total 15.55% (2024) -> 17% (2025 Jan-Aug)",
            False,
        ),
        PoSubProduct(
            "HUD_P",
            "P-HUD",
            "rate",
            "B: industry-average table 0.015->0.06",
            False,
            "Coexists with W-HUD/AR-HUD on the same vehicle; penetration rates are non-exclusive (Ho 2026-11-17 ruling). An independent rate per model x trim (Ho Q7), never summed with other HUD variants.",
        ),
        PoSubProduct(
            "RADAR",
            "Radar (millimeter-wave)",
            "count",
            "B: industry-average table 1.15->2.17 units/vehicle; count-kind, never a penetration rate",
            False,
            "Units per vehicle; rises with ADAS level (annual-trend co-movement only, not a vehicle-level rule).",
        ),
        PoSubProduct(
            "GATEWAY",
            "Intelligent gateway",
            "rate",
            "B: industry-average table 0.6->0.75->0.4 (non-monotonic, unexplained — see synthesis F24)",
            False,
            "Non-monotonic path has no annotation; treat the series as suspect, not as a prior.",
        ),
        PoSubProduct(
            "BODY_DOMAIN",
            "Body domain / zone controller",
            "count",
            "B: industry-average table 1.04->2.3 units/vehicle; count-kind",
            False,
            "Units per vehicle; rises with central-compute adoption (trend co-movement only).",
        ),
        PoSubProduct(
            "APA",
            "Automatic parking assist",
            "rate",
            "assumption: product-line definition only; no workbook rows, no public series",
            True,
            "Structure first: fitment rates are explicit labeled assumptions until Ho data arrives.",
        ),
        PoSubProduct(
            "AVM",
            "Around-view monitoring",
            "rate",
            "assumption: product-line definition only; no workbook rows, no public series",
            True,
            "Paired with the surround-view camera group (rule AVM1): AVM present implies a surround group; the reverse does not hold.",
        ),
        PoSubProduct(
            "UWB",
            "Ultra-wideband (digital key / positioning)",
            "rate",
            "assumption: product-line definition only; no workbook rows, no public series",
            True,
            "Related series 'smart entry' 0.71->0.98 exists but is NOT UWB penetration; do not substitute.",
        ),
        PoSubProduct(
            "CMS",
            "Camera monitoring system (streaming rearview)",
            "rate",
            "B: industry-average table 0.094->0.121",
            False,
        ),
        PoSubProduct(
            "AMP",
            "Independent amplifier",
            "rate",
            "B: industry-average table 0.445->0.60",
            False,
        ),
        PoSubProduct(
            "SMART_ENTRY",
            "Smart entry",
            "rate",
            "B: industry-average table 0.71->0.98",
            False,
        ),
        PoSubProduct(
            "STEERING_SWITCH",
            "Steering-wheel switch",
            "rate",
            "assumption: product-line definition only",
            True,
        ),
        PoSubProduct(
            "HVAC_CTRL",
            "Air-conditioning controller",
            "rate",
            "assumption: product-line definition only",
            True,
        ),
        PoSubProduct(
            "ECU_ENGINE",
            "Engine control unit",
            "rate",
            "assumption: product-line definition only",
            True,
            "ICE-only by definition; no expectation is evaluated for NEV nameplates.",
        ),
    ]
}

#: Product lines of the workbook product-line definition.
PRODUCT_LINES = frozenset({"P01", "P02", "P03", "P04", "P05", "P.O"})


def product_line_of(product_id: str) -> str | None:
    """The product line a row's ``product_id`` belongs to.

    ``P01``–``P05`` and ``P.O`` map to themselves; catalog sub-product
    ids map to ``"P.O"``; anything else is unknown (``None``) — the
    prompt engine skips line-dependent checks for unknown ids rather
    than guessing.
    """

    if product_id in PRODUCT_LINES:
        return product_id
    if product_id in PO_SUBPRODUCTS:
        return "P.O"
    return None


def is_po_basket(product_id: str) -> bool:
    """True when the row is the undecomposed P.O basket."""

    return product_id == "P.O"
