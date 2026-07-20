"""Groq API client (OpenAI-compatible) for free-tier LLM research.

Groq's free tier requires no credit card. Agentic `groq/compound` models perform
web search internally (the closest drop-in for Gemini's Google Search grounding);
plain chat models (e.g. llama-3.3-70b-versatile) do not search.
See https://console.groq.com/docs.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import httpx
from dotenv import load_dotenv

GROQ_BASE_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "groq/compound-mini"

PLACEHOLDER_KEYS = {"", "your_api_key_here", "paste_your_key_here", "gsk_your_key_here"}

_URL_RE = re.compile(r"https?://[^\s\"'<>)\]}]+")


def parse_groq_json(text: str) -> dict[str, Any]:
    """Parse a JSON object from an LLM response, tolerating ```json fences and prose."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        return json.loads(fence.group(1).strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def resolve_groq_config(cfg: dict) -> dict[str, Any]:
    groq_cfg = dict(cfg.get("groq") or {})
    return {
        "model": groq_cfg.get("model", DEFAULT_MODEL),
        "temperature": float(groq_cfg.get("temperature", 0.2)),
        "prompt_version": groq_cfg.get("prompt_version", "v2"),
        "timeout": float(groq_cfg.get("timeout_seconds", 90.0)),
    }


def get_api_key() -> str:
    load_dotenv()
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key or key in PLACEHOLDER_KEYS:
        raise EnvironmentError(
            "GROQ_API_KEY is not set. Create a free key (no credit card) at "
            "https://console.groq.com/keys and add it to your .env as GROQ_API_KEY=..."
        )
    return key


def _is_compound(model: str) -> bool:
    return model.startswith("groq/compound")


def extract_groq_sources(payload: dict[str, Any]) -> list[str]:
    """Best-effort collection of source URLs from agentic tool output."""
    sources: list[str] = []
    for choice in payload.get("choices", []):
        message = choice.get("message") or {}
        for tool in message.get("executed_tools") or []:
            output = tool.get("output")
            if isinstance(output, str):
                for url in _URL_RE.findall(output):
                    if url not in sources:
                        sources.append(url)
            search_results = tool.get("search_results") or {}
            if isinstance(search_results, dict):
                for result in search_results.get("results") or []:
                    url = result.get("url") if isinstance(result, dict) else None
                    if url and url not in sources:
                        sources.append(url)
    return sources


class GroqClient:
    """Thin wrapper around Groq chat completions returning parsed JSON."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        resolved = resolve_groq_config(cfg)
        self.model = resolved["model"]
        self.temperature = resolved["temperature"]
        self.timeout = resolved["timeout"]
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
        Call Groq and parse a JSON response.

        Returns (parsed_json_or_none, meta) where meta may include error, sources, raw_text.
        """
        try:
            api_key = get_api_key()
        except EnvironmentError as exc:
            return None, {"error": {"status": 0, "detail": str(exc), "missing_key": True}}
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
        }
        # JSON mode is supported on standard chat models but not the agentic
        # compound models (which also do web search); only request it elsewhere.
        if not _is_compound(self.model):
            body["response_format"] = {"type": "json_object"}

        self._throttle()
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    GROQ_BASE_URL,
                    json=body,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
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

        choices = payload.get("choices", [])
        text = ""
        if choices:
            text = (choices[0].get("message") or {}).get("content") or ""

        meta: dict[str, Any] = {
            "sources": extract_groq_sources(payload),
            "raw_text": text[:2000],
            "model": self.model,
        }
        try:
            return parse_groq_json(text), meta
        except json.JSONDecodeError:
            meta["error"] = {"status": 0, "detail": "invalid_json", "raw_text": text[:500]}
            return None, meta
