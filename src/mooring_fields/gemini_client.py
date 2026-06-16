"""Free-tier-safe Gemini API client shared by enrichment modules."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import httpx
from dotenv import load_dotenv

PLACEHOLDER_KEYS = {"", "your_api_key_here", "paste_your_key_here"}

# Models with free-tier token quotas in Google AI Studio (no billing account required).
FREE_TIER_MODELS = frozenset(
    {
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
    }
)

# Substrings that indicate paid-only models; blocked when free_tier_only is true.
PAID_MODEL_MARKERS = ("pro", "ultra", "preview")


def parse_gemini_json(text: str) -> dict[str, Any]:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


def resolve_gemini_config(cfg: dict) -> dict[str, Any]:
    """Return normalized gemini settings with free-tier defaults."""
    gemini_cfg = dict(cfg.get("gemini") or {})
    free_only = bool(gemini_cfg.get("free_tier_only", True))
    allowed = set(gemini_cfg.get("allowed_models") or FREE_TIER_MODELS)
    if free_only:
        allowed &= FREE_TIER_MODELS
    model = gemini_cfg.get("model", "gemini-2.0-flash-lite")
    if free_only:
        model = _coerce_free_tier_model(model, allowed)
    else:
        validate_model_allowed(model, allowed, free_only=False)
    return {
        "model": model,
        "free_tier_only": free_only,
        "allowed_models": allowed,
        "use_google_search": bool(gemini_cfg.get("use_google_search", True)),
    }


def _coerce_free_tier_model(model: str, allowed: set[str]) -> str:
    lowered = model.lower()
    if any(marker in lowered for marker in PAID_MODEL_MARKERS):
        return "gemini-2.0-flash-lite"
    if model not in allowed:
        return "gemini-2.0-flash-lite"
    return model


def validate_model_allowed(model: str, allowed: set[str], *, free_only: bool) -> None:
    lowered = model.lower()
    if free_only and any(marker in lowered for marker in PAID_MODEL_MARKERS):
        raise ValueError(
            f"Model '{model}' is not on the Gemini free tier. "
            f"Use one of: {', '.join(sorted(allowed))}"
        )
    if model not in allowed:
        raise ValueError(
            f"Model '{model}' is not in allowed_models. "
            f"Allowed: {', '.join(sorted(allowed))}"
        )


def get_api_key(*, free_tier_only: bool = True) -> str:
    load_dotenv()
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key or key in PLACEHOLDER_KEYS:
        if free_tier_only:
            raise EnvironmentError(
                "GEMINI_API_KEY is not set. Create a free key at https://aistudio.google.com/apikey "
                "without attaching a billing account (free_tier_only is enabled)."
            )
        key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not key or key in PLACEHOLDER_KEYS:
        raise EnvironmentError("GEMINI_API_KEY is not set.")
    return key


def extract_grounding_sources(payload: dict[str, Any]) -> list[str]:
    sources: list[str] = []
    for candidate in payload.get("candidates", []):
        meta = candidate.get("groundingMetadata") or {}
        for chunk in meta.get("groundingChunks", []):
            for bucket in (chunk.get("web") or {}, chunk.get("maps") or {}):
                if isinstance(bucket, dict):
                    uri = bucket.get("uri")
                    if uri and uri not in sources:
                        sources.append(uri)
    return sources


class GeminiClient:
    """Thin wrapper around generateContent with free-tier guards."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.gemini = resolve_gemini_config(cfg)
        self.model = self.gemini["model"]
        self.use_grounding = self.gemini["use_google_search"]
        self.free_tier_only = self.gemini["free_tier_only"]
        self.calls_made = 0
        self._rps = float(cfg.get("requests_per_second", 2))
        self._last_call = 0.0

    def _throttle(self) -> None:
        if self._rps <= 0:
            return
        gap = 1.0 / self._rps
        elapsed = time.monotonic() - self._last_call
        if elapsed < gap:
            time.sleep(gap - elapsed)
        self._last_call = time.monotonic()

    def generate_json(
        self,
        *,
        prompt: str,
        system_instruction: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """
        Call Gemini and parse JSON response.

        Returns (parsed_json_or_none, meta) where meta may include error, sources, raw_text.
        """
        api_key = get_api_key(free_tier_only=self.free_tier_only)
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={api_key}"
        )
        body: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
        }
        if self.use_grounding:
            body["tools"] = [{"google_search": {}}]

        self._throttle()
        try:
            with httpx.Client(timeout=90.0) as client:
                resp = client.post(url, json=body)
                resp.raise_for_status()
                self.calls_made += 1
                payload = resp.json()
        except httpx.HTTPStatusError as exc:
            return None, {
                "error": {
                    "status": exc.response.status_code,
                    "detail": exc.response.text[:500],
                }
            }
        except httpx.HTTPError as exc:
            return None, {"error": {"status": 0, "detail": str(exc)}}

        candidates = payload.get("candidates", [])
        text = ""
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            text = parts[0].get("text", "") if parts else ""

        meta: dict[str, Any] = {
            "sources": extract_grounding_sources(payload),
            "raw_text": text[:2000],
            "model": self.model,
            "free_tier_only": self.free_tier_only,
        }
        try:
            return parse_gemini_json(text), meta
        except json.JSONDecodeError:
            meta["error"] = {"status": 0, "detail": "invalid_json", "raw_text": text[:500]}
            return None, meta
