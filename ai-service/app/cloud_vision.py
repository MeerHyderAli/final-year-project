"""
Optional cloud vision provider — use a frontier vision model instead of the local one.

WHY THIS EXISTS
    The local model scores 0.969 in-domain but 0.258 on real photographs, and it is
    confidently wrong on 48% of its errors (docs/DATASET-AND-MODEL.md). A frontier
    vision-language model has seen millions of real photographs and will identify
    real spare parts far better than a 22-feature model trained on 480 renders.

WHAT IT DOES NOT CHANGE — read this twice
    A vision model, however good, still returns a **category**. It cannot tell you
    that a part fits a 2019 Swift. Fitment still comes from a part-number match or a
    vehicle-catalogue match in the Express API. The safety architecture is unchanged:
    AI suggests; catalogue and seller data verify.

    Also: a cloud model's "confidence" is a self-reported number, not a calibrated
    probability. It is reported as `confidenceSource: "model_self_report"` and must
    not be treated as equivalent to the local model's temperature-calibrated softmax.

COST AND PRIVACY
    Every upload leaves the device and is billed per image (roughly USD 0.001-0.01
    per photo depending on provider and model). The user's photograph goes to a third
    party. For a deployment handling customer images, that is a disclosure you owe
    your users, and it is a reason to keep the local model as the default.

NO EXTRA DEPENDENCIES: stdlib urllib only.

CONFIGURATION
    VISION_PROVIDER = local | openai | gemini | anthropic      (default: local)
    VISION_API_KEY  = <key>                                    (or the provider's own
                                                                env var, see below)

    Supported key env vars, checked in order:
        VISION_API_KEY
        OPENAI_API_KEY        (openai)
        GEMINI_API_KEY / GOOGLE_API_KEY   (gemini)
        ANTHROPIC_API_KEY     (anthropic)

    Optional:
        VISION_MODEL       override the model name
        VISION_BASE_URL    override the endpoint (any OpenAI-compatible gateway)
        VISION_TIMEOUT     seconds, default 25
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request

from .taxonomy import CLASS_KEYS, is_safety_critical, label_for

DEFAULT_MODELS = {
    "openai": "gpt-4o",
    "gemini": "gemini-2.0-flash",
    "anthropic": "claude-sonnet-4-20250514",
}

KEY_ENV_VARS = {
    "openai": ["VISION_API_KEY", "OPENAI_API_KEY"],
    "gemini": ["VISION_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"],
    "anthropic": ["VISION_API_KEY", "ANTHROPIC_API_KEY"],
}


class CloudVisionError(RuntimeError):
    """Raised when the cloud provider cannot be used or fails. Callers fall back."""


# The model must choose from our closed taxonomy, and must be able to say "I don't
# know". An open-ended answer would let it invent categories the catalogue has never
# heard of, breaking the join between prediction and parts.
PROMPT = """You are identifying an automotive spare part from a photograph.

Choose EXACTLY ONE category from this closed list:
{categories}

Rules:
- Answer with the physical part you can actually see. Do not guess from context.
- If the image does not clearly show a spare part, set "category" to null.
- If two categories are plausible, pick the better one but lower the confidence.
- "confidence" is your own certainty from 0.0 to 1.0. Do not inflate it.

Reply with ONLY a JSON object, no markdown fences, no commentary:
{{"category": "<one of the keys above, or null>",
  "confidence": <number 0.0-1.0>,
  "reasoning": "<max 25 words on what visual evidence you used>",
  "is_part_photo": <true|false>}}"""


def _resolve_key(provider: str) -> str | None:
    for var in KEY_ENV_VARS.get(provider, []):
        value = os.environ.get(var)
        if value:
            return value.strip()
    return None


def provider_name() -> str:
    return (os.environ.get("VISION_PROVIDER") or "local").strip().lower()


def enabled() -> bool:
    """True only when a provider is selected AND a key is present."""
    name = provider_name()
    if name in ("", "local", "none", "off"):
        return False
    if name not in KEY_ENV_VARS:
        return False
    return _resolve_key(name) is not None


def status() -> dict:
    name = provider_name()
    key = _resolve_key(name) if name in KEY_ENV_VARS else None
    return {
        "provider": name,
        "configured": enabled(),
        "hasKey": key is not None,
        "model": os.environ.get("VISION_MODEL") or DEFAULT_MODELS.get(name),
        "knownProviders": ["local", *KEY_ENV_VARS.keys()],
        "note": (
            "Cloud vision returns a CATEGORY only, exactly like the local model. "
            "Fitment is still decided by the catalogue."
        ),
    }


# --------------------------------------------------------------------- transport


def _post_json(url: str, payload: dict, headers: dict, timeout: int) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise CloudVisionError(f"{exc.code} from provider: {detail}") from exc
    except urllib.error.URLError as exc:
        raise CloudVisionError(f"provider unreachable: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise CloudVisionError(f"provider returned non-JSON: {exc}") from exc


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


# --------------------------------------------------------------------- providers


def _call_openai(raw: bytes, mime: str, prompt: str, timeout: int) -> str:
    name = "openai"
    key = _resolve_key(name)
    base = (os.environ.get("VISION_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("VISION_MODEL") or DEFAULT_MODELS[name]

    payload = {
        "model": model,
        "max_tokens": 300,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{_b64(raw)}"}},
                ],
            }
        ],
    }
    data = _post_json(
        f"{base}/chat/completions",
        payload,
        {"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        timeout,
    )
    return data["choices"][0]["message"]["content"]


def _call_gemini(raw: bytes, mime: str, prompt: str, timeout: int) -> str:
    name = "gemini"
    key = _resolve_key(name)
    model = os.environ.get("VISION_MODEL") or DEFAULT_MODELS[name]
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={key}"
    )
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime, "data": _b64(raw)}},
                ]
            }
        ],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 300},
    }
    data = _post_json(url, payload, {"Content-Type": "application/json"}, timeout)
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _call_anthropic(raw: bytes, mime: str, prompt: str, timeout: int) -> str:
    name = "anthropic"
    key = _resolve_key(name)
    model = os.environ.get("VISION_MODEL") or DEFAULT_MODELS[name]
    payload = {
        "model": model,
        "max_tokens": 300,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": mime, "data": _b64(raw)},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }
    data = _post_json(
        "https://api.anthropic.com/v1/messages",
        payload,
        {
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        timeout,
    )
    return data["content"][0]["text"]


_CALLERS = {"openai": _call_openai, "gemini": _call_gemini, "anthropic": _call_anthropic}


# --------------------------------------------------------------------- parsing


def parse_reply(text: str) -> dict:
    """
    Extract and validate the model's JSON.

    Models wrap JSON in markdown fences, prepend "Here is the JSON:", or trail a
    sentence after it. Rather than trusting the provider's formatting (which differs
    per model and per version), scan for brace positions and use `raw_decode`, which
    parses the first complete JSON value and ignores whatever follows.

    Do NOT use the naive `find("{") ... rfind("}")` slice: a trailing sentence that
    happens to contain braces (e.g. "(0.6 = {moderate})") makes that slice invalid.
    That bug was caught by tests/test_cloud_vision.py.

    Raises CloudVisionError if nothing parseable is found — the caller then falls
    back to the local model rather than surfacing a half-parsed guess.
    """
    if not text or not text.strip():
        raise CloudVisionError("provider returned an empty response")

    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.MULTILINE).strip()

    decoder = json.JSONDecoder()
    obj = None
    for match in re.finditer(r"\{", cleaned):
        try:
            candidate, _ = decoder.raw_decode(cleaned[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            obj = candidate
            break

    if obj is None:
        raise CloudVisionError(f"no JSON object found in response: {cleaned[:120]!r}")

    category = obj.get("category")
    if category is not None:
        category = str(category).strip().lower().replace(" ", "_").replace("-", "_")
        # Accept an obvious synonym for the nearest catalogue key.
        if category not in CLASS_KEYS:
            for key in CLASS_KEYS:
                if category in (key, label_for(key).lower().replace(" ", "_")):
                    category = key
                    break
            else:
                raise CloudVisionError(
                    f"model returned a category outside the taxonomy: {category!r}"
                )

    try:
        confidence = float(obj.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = min(max(confidence, 0.0), 1.0)

    return {
        "category": category,
        "confidence": round(confidence, 4),
        "reasoning": str(obj.get("reasoning") or "").strip()[:300],
        "isPartPhoto": bool(obj.get("is_part_photo", category is not None)),
    }


# --------------------------------------------------------------------- public API


def classify(raw: bytes, mime_type: str = "image/jpeg") -> dict:
    """
    Ask the configured provider to classify an image.

    Returns the same shape as the local model's prediction list, plus provenance.
    Raises CloudVisionError on any failure so the caller can degrade to the local
    model — this function never invents a result and never silently returns empty.
    """
    name = provider_name()
    if name not in _CALLERS:
        raise CloudVisionError(f"unknown VISION_PROVIDER {name!r}")
    if _resolve_key(name) is None:
        raise CloudVisionError(f"no API key found for provider {name!r}")

    timeout = int(os.environ.get("VISION_TIMEOUT", "25"))
    prompt = PROMPT.format(categories="\n".join(f"- {k}  ({label_for(k)})" for k in CLASS_KEYS))

    started = time.perf_counter()
    text = _CALLERS[name](raw, mime_type, prompt, timeout)
    parsed = parse_reply(text)
    latency_ms = round((time.perf_counter() - started) * 1000, 1)

    if parsed["category"] is None or not parsed["isPartPhoto"]:
        # No usable category. Report it as an empty prediction list; the API's
        # min-confidence rule turns this into "tell us more", which is correct.
        return {
            "predictions": [],
            "modelVersion": f"cloud:{os.environ.get('VISION_MODEL') or DEFAULT_MODELS[name]}",
            "backend": name,
            "latencyMs": latency_ms,
            "confidenceSource": "model_self_report",
            "noPartDetected": True,
            "reasoning": parsed["reasoning"],
        }

    category = parsed["category"]
    confidence = parsed["confidence"]
    return {
        "predictions": [
            {
                "category": category,
                "label": label_for(category),
                "confidence": confidence,
                "safetyCritical": is_safety_critical(category),
                "classIndex": CLASS_KEYS.index(category),
            }
        ],
        "modelVersion": f"cloud:{os.environ.get('VISION_MODEL') or DEFAULT_MODELS[name]}",
        "backend": name,
        "latencyMs": latency_ms,
        # NOT a calibrated probability. The API surfaces this distinction.
        "confidenceSource": "model_self_report",
        "reasoning": parsed["reasoning"],
    }
