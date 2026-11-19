"""Live validation script for Track 8 (NOT part of the test suite).

Runs the real red team over the desay-2020 snapshot through the
Kakouai live port (vault-backed helper; no key in this file, in logs,
or in the output beyond the model's findings). Prints the merged
result as JSON. Run once, manually; the outcome is recorded in
TRACK8-RED-TEAM.md.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT))

from planagent.services.redteam.kakouai_port import KakouaiCliPort
from planagent.services.redteam.orchestration import run_red_team
from tests.redteam_cases import desay_2020_snapshot


async def main() -> int:
    port = KakouaiCliPort()
    print(f"helper available: {port.is_available()}", file=sys.stderr, flush=True)
    result = await run_red_team(port, snapshot=desay_2020_snapshot(), mode="live")
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
