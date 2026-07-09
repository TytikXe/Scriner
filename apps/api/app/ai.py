from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone

import httpx

from .config import settings
from .domain import ai_local_analysis
from .schemas import AiFormationAnalysis, AiFormationInput
from .storage import store


def _hash_input(payload: AiFormationInput) -> str:
    canonical = payload.model_dump(mode="json")
    raw = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cached_ai_result(cache_key: str) -> AiFormationAnalysis | None:
    cached = store.get_ai_cache(cache_key)
    if not cached:
        return None
    return AiFormationAnalysis.model_validate(cached)


def _store_ai_result(cache_key: str, result: AiFormationAnalysis) -> None:
    store.set_ai_cache(cache_key, result.model_dump(mode="json"), settings.ai_ttl_minutes)


async def analyze_formation(payload: AiFormationInput, mode: str = "quick") -> AiFormationAnalysis:
    cache_key = f"{mode}:{_hash_input(payload)}"
    cached = _cached_ai_result(cache_key)
    if cached:
        return cached

    if settings.openai_api_key and settings.openai_base_url:
        result = await _openai_analysis(payload, mode)
    else:
        result = ai_local_analysis(payload)
    _store_ai_result(cache_key, result)
    return result


async def analyze_formations_batch(payloads: list[AiFormationInput], mode: str = "quick") -> list[AiFormationAnalysis]:
    results = await asyncio.gather(*(analyze_formation(payload, mode=mode) for payload in payloads))
    return list(results)


async def _openai_analysis(payload: AiFormationInput, mode: str) -> AiFormationAnalysis:
    system_prompt = (
        "Ты анализируешь формации на основе переданных данных. "
        "Не выдумывай цены и уровни, не давай прямых торговых команд, "
        "не обещай прибыль, используй вероятностные формулировки. "
        "Если данных недостаточно, прямо так и напиши. "
        "Ответь строго JSON по схеме."
    )
    schema_hint = {
        "summary": "string",
        "whyDetected": ["string"],
        "bullishScenario": "string",
        "bearishScenario": "string",
        "riskFactors": ["string"],
        "invalidation": "string",
        "watchPoints": ["string"],
        "confidenceAdjustment": "number",
    }
    user_prompt = json.dumps(
        {
            "mode": mode,
            "input": payload.model_dump(mode="json"),
            "schema": schema_hint,
        },
        ensure_ascii=False,
    )
    request_body = {
        "model": settings.openai_model_quick if mode == "quick" else settings.openai_model_deep,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{settings.openai_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json=request_body,
        )
        response.raise_for_status()
        data = response.json()
    content = data["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    return AiFormationAnalysis.model_validate(parsed)
