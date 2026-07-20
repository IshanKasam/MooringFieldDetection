"""Background enrichment jobs triggered from the web UI."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def run_enrichment_job(
    step: str,
    *,
    limit: int | None = 5,
    only_new: bool = True,
) -> dict[str, Any]:
    """Run one enrichment step (or all). Intended for BackgroundTasks."""
    from mooring_fields.enrichment import (
        enrich_all,
        enrich_places,
        enrich_research,
        enrich_supply_chain,
    )

    step = (step or "research").lower().strip()
    try:
        if step == "places":
            return enrich_places(limit=limit, only_new=only_new)
        if step == "research":
            return enrich_research(limit=limit, only_new=only_new)
        if step in ("supply_chain", "supply-chain"):
            return enrich_supply_chain(limit=limit, only_new=only_new)
        if step == "all":
            return enrich_all(limit=limit, only_new=only_new)
        return {"error": f"unknown step: {step}"}
    except Exception as exc:  # noqa: BLE001 — surface to run log
        log.exception("enrichment job failed")
        return {"error": str(exc), "step": step}
