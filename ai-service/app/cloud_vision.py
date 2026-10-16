"""
Gemini (and other frontier vision models) as the identification engine.

WHY THIS IS THE DEFAULT NOW
    Training and shipping a local CNN was the wrong trade for this project: it needed
    a labelled dataset we do not have, and measured 0.258 accuracy on real
    photographs. A frontier vision model has seen millions of real spare parts and
    needs no dataset, no training run, and no GPU.

THREE JOBS, ONE PROVIDER
    classify()               image -> category (+ any part number and brand visible)
    read_label()             image -> raw text, for the OCR / part-number path
    interpret_description()  text  -> category, so the app works with no photo at all

WHAT DOES NOT CHANGE — read this twice
    A vision model still returns a CATEGORY. It cannot confirm that a part fits a
    2019 Swift. Fitment still comes from a part-number match or a vehicle-catalogue
    match in the Express API. The safety architecture is identical:

        AI suggests; catalogue and seller data verify.

    A model's "confidence" is a self-report, not a calibrated probability, so it is
    labelled `confidenceSource: "model_self_report"` and must never be treated as
    equivalent to a measured accuracy.

NO NEW DEPENDENCIES: stdlib urllib only.

CONFIGURATION
    VISION_PROVIDER = gemini | openai | anthropic | local      (default: gemini)
    VISION_API_KEY  = <key>          (or GEMINI_API_KEY / GOOGLE_API_KEY / ...)

    Optional:
        VISION_MODEL      default gemini-2.0-flash
        VISION_BASE_URL   override the endpoint. Used for two things: routing through
                          a proxy, and pointing the tests at a local mock server.
        VISION_TIMEOUT    seconds, default 30
        VISION_RETRIES    attempts on 429/5xx, default 2
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

DEFAULT_PROVIDER = "gemini"

DEFAULT_MODELS = {
    "gemini": "gemini-2.0-flash",
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4-20250514",
}

DEFAULT_BASE_URLS = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
}

KEY_ENV_VARS = {
    "gemini": ["VISION_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"],
    "openai": ["VISION_API_KEY", "OPENAI_API_KEY"],
    "anthropic": ["VISION_API_KEY", "ANTHROPIC_API_KEY"],
}

CLOUD_PROVIDERS = tuple(DEFAULT_MODELS.keys())


class CloudVisionError(RuntimeError):
    """Provider unusable or call failed. Callers fall back to the local model."""

    def __init__(self, message: str, *, retryable: bool = False, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


# --------------------------------------------------------------------------- config


def provider_name() -> str:
    return (os.environ.get("VISION_PROVIDER") or DEFAULT_PROVIDER).strip().lower()


def _resolve_key(provider: str) -> str | None:
    for var in KEY_ENV_VARS.get(provider, []):
        value = os.environ.get(var)
        if value and value.strip():
            return value.strip()
    return None


def enabled() -> bool:
    """True only when the provider is a cloud one AND a key is present."""
    name = provider_name()
    if name in ("", "local", "none", "off"):
        return False
    return name in DEFAULT_MODELS and _resolve_key(name) is not None


def model_name(provider: str | None = None) -> str:
    name = provider or provider_name()
    return os.environ.get("VISION_MODEL") or DEFAULT_MODELS.get(name, "unknown")


def base_url(provider: str | None = None) -> str:
    name = provider or provider_name()
    return (os.environ.get("VISION_BASE_URL") or DEFAULT_BASE_URLS.get(name, "")).rstrip("/")


def status() -> dict:
    name = provider_name()
    key = _resolve_key(name) if name in DEFAULT_MODELS else None
    return {
        "provider": name,
        "configured": enabled(),
        "hasKey": key is not None,
        "model": model_name(name) if name in DEFAULT_MODELS else None,
        "baseUrl": base_url(name) if name in DEFAULT_MODELS else None,
        "knownProviders": ["gemini", "openai", "anthropic", "local"],
        "capabilities": ["classify", "readLabel", "interpretDescription"] if enabled() else [],
        "note": (
            "Cloud vision returns a CATEGORY only. Fitment is still decided by the "
            "catalogue, never by image similarity."
        ),
    }


# --------------------------------------------------------------------------- prompts

# The taxonomy is closed. Letting the model invent categories would break the join
# between a prediction and catalogue records, which is the only reason the answer is
# useful at all.
_CLASS_LIST = "\n".join(f"- {k}  ({label_for(k)})" for k in CLASS_KEYS)

CLASSIFY_PROMPT = """You are an expert automotive parts counter technician identifying a spare part from a photograph.

Classify it into EXACTLY ONE of these categories:
{categories}

Critical rules:
1. Identify the physical object you can actually SEE. Do not guess from what the
   vehicle might need, and do not be swayed by surrounding clutter.
2. If the object is clearly visible, ALWAYS give a best category — even if it is
   dirty, worn, rusty, or photographed at an awkward angle.
3. If the image does not contain a spare part at all (a person, a receipt, a car
   exterior, an engine bay where no individual part is the subject), set
   "category" to null and "is_part_photo" to false.
4. Read any text you can see on the part — part numbers, brand names, printed
   labels, stamped codes. Report ONLY text you can actually read. Do not invent or
   complete a part number from a partial glimpse; if a character is ambiguous,
   still report your best reading, because the caller cross-checks it against a
   catalogue.
5. "confidence" is YOUR OWN certainty that the category is right, from 0.0 to 1.0.
   Be honest and calibrated: use 0.9+ only when the part is unmistakable, and use
   0.4-0.6 when several categories are plausible. Do not inflate it.

Reply with ONLY a JSON object:
{{"category": "<one of the keys above, or null>",
  "confidence": <number 0.0-1.0>,
  "visible_brand": "<brand you can read, or null>",
  "visible_part_number": "<part number you can read, or null>",
  "reasoning": "<max 30 words on the visual evidence you used>",
  "is_part_photo": <true|false>}}"""

LABEL_PROMPT = """Read all text from this photograph of a spare-part label, box, or a
stamped/embossed marking on the part itself.

Rules:
- Transcribe EXACTLY what is printed, preserving part numbers character for
  character, including digits, letters, hyphens and slashes.
- Part numbers matter most. If the image is angled, blurred or glared, report your
  best reading anyway — the caller cross-checks it against a catalogue and can
  resolve common mis-reads.
- Do NOT invent, complete or normalise a part number. Never guess a missing
  character.
- Put each distinct piece of text on its own line, most prominent/legible first.

Reply with ONLY a JSON object:
{"text": "<transcribed text, newline separated>",
 "confidence": <number 0.0-1.0>,
 "notes": "<max 20 words on image quality, or null>"}"""

DESCRIBE_PROMPT = """A user is describing an automotive spare part in their own words
because they cannot photograph it. Work out which category they mean.

Available categories:
{categories}

Rules:
1. Choose the single best category from the list above.
2. If the description is too vague to choose one — for example "a part", "something
   under the bonnet", "it is broken" — set "category" to null and lower your
   confidence. Do NOT guess.
3. If they describe something that is not a spare part in this taxonomy, set
   "category" to null.
4. "confidence" is your own certainty from 0.0 to 1.0. Be honest.
5. Extract any part number or brand they mention, verbatim.

Reply with ONLY a JSON object:
{{"category": "<one of the keys above, or null>",
  "confidence": <number 0.0-1.0>,
  "visible_brand": "<brand mentioned, or null>",
  "visible_part_number": "<part number mentioned, or null>",
  "reasoning": "<max 25 words>",
  "is_part_photo": true}}"""


# --------------------------------------------------------------------------- transport


def _extract_json(text: str) -> dict:
    """
    Pull the first complete JSON object out of a model reply.

    Models wrap JSON in markdown fences, prepend "Here is the JSON:", or trail a
    sentence after it. `raw_decode` parses the first complete value and ignores the
    rest — do NOT use a `find("{") ... rfind("}")` slice, which breaks when trailing
    prose happens to contain braces (that bug is captured in tests).
    """
    if not text or not text.strip():
        raise CloudVisionError("provider returned an empty response")

    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE).strip()

    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", cleaned):
        try:
            candidate, _ = decoder.raw_decode(cleaned[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            return candidate

    raise CloudVisionError(f"no JSON object found in response: {cleaned[:160]!r}")


def _post_json(url: str, payload: dict, headers: dict, timeout: int) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            pass
        # 429 and 5xx are worth retrying; 4xx is a bug in our request or a bad key.
        retryable = exc.code == 429 or 500 <= exc.code < 600
        hint = ""
        if exc.code == 400 and "API key not valid" in detail:
            hint = " — check VISION_API_KEY"
        elif exc.code == 404:
            hint = f" — model {model_name()!r} may not exist; run scripts/check-gemini.sh to list models"
        elif exc.code == 403:
            hint = " — key may lack access to this model, or the API is not enabled for the project"
        raise CloudVisionError(
            f"HTTP {exc.code} from provider{hint}: {detail[:300]}",
            retryable=retryable,
            status=exc.code,
        ) from exc
    except urllib.error.URLError as exc:
        raise CloudVisionError(f"provider unreachable: {exc.reason}", retryable=True) from exc
    except json.JSONDecodeError as exc:
        raise CloudVisionError(f"provider returned non-JSON: {exc}") from exc


def _with_retries(fn):
    attempts = max(1, int(os.environ.get("VISION_RETRIES", "2")))
    last: CloudVisionError | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except CloudVisionError as exc:
            last = exc
            if not exc.retryable or attempt == attempts - 1:
                raise
            delay = 1.5 * (2**attempt)
            print(f"[ai] attempt {attempt + 1}/{attempts} failed ({exc}); retrying in {delay:.0f}s")
            time.sleep(delay)
    raise last  # pragma: no cover


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


# --------------------------------------------------------------------------- providers


def _call_gemini(parts: list[dict], timeout: int) -> str:
    key = _resolve_key("gemini")
    url = f"{base_url('gemini')}/models/{model_name('gemini')}:generateContent?key={key}"
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 512,
            # Ask for JSON directly. We deliberately do NOT send responseSchema:
            # its exact type casing has changed across API versions, and a malformed
            # schema risks a 400 on every call. _extract_json tolerates stray prose.
            "responseMimeType": "application/json",
        },
        # Part-identification prompts often trip safety filters on cropped or oily
        # close-ups; these settings keep the classification call reliable.
        "safetySettings": [
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"},
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_ONLY_HIGH"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_ONLY_HIGH"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_ONLY_HIGH"},
        ],
    }
    data = _post_json(url, payload, {"Content-Type": "application/json"}, timeout)

    candidates = data.get("candidates") or []
    if not candidates:
        blocked = (data.get("promptFeedback") or {}).get("blockReason")
        if blocked:
            raise CloudVisionError(f"request blocked by provider safety filter ({blocked})")
        raise CloudVisionError(f"provider returned no candidates: {json.dumps(data)[:200]}")

    candidate = candidates[0]
    finish = candidate.get("finishReason")
    parts_out = (candidate.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts_out)
    if not text.strip():
        raise CloudVisionError(f"provider returned empty content (finishReason={finish})")
    return text


def _call_openai(content: list[dict], timeout: int) -> str:
    key = _resolve_key("openai")
    payload = {
        "model": model_name("openai"),
        "max_tokens": 512,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": content}],
    }
    data = _post_json(
        f"{base_url('openai')}/chat/completions",
        payload,
        {"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        timeout,
    )
    return data["choices"][0]["message"]["content"]


def _call_anthropic(content: list[dict], timeout: int) -> str:
    key = _resolve_key("anthropic")
    payload = {"model": model_name("anthropic"), "max_tokens": 512, "messages": [{"role": "user", "content": content}]}
    data = _post_json(
        f"{base_url('anthropic')}/messages",
        payload,
        {"Content-Type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"},
        timeout,
    )
    return data["content"][0]["text"]


def _ask(prompt: str, image: bytes | None = None, mime_type: str = "image/jpeg") -> str:
    """Send one prompt (optionally with an image) to the configured provider."""
    name = provider_name()
    if name not in DEFAULT_MODELS:
        raise CloudVisionError(f"unknown VISION_PROVIDER {name!r}")
    if _resolve_key(name) is None:
        raise CloudVisionError(f"no API key found for provider {name!r} (set VISION_API_KEY or {KEY_ENV_VARS[name][1]})")

    timeout = int(os.environ.get("VISION_TIMEOUT", "30"))

    if name == "gemini":
        parts: list[dict] = [{"text": prompt}]
        if image is not None:
            parts.append({"inline_data": {"mime_type": mime_type, "data": _b64(image)}})
        return _with_retries(lambda: _call_gemini(parts, timeout))

    if name == "openai":
        content: list[dict] = [{"type": "text", "text": prompt}]
        if image is not None:
            content.append(
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{_b64(image)}"}}
            )
        return _with_retries(lambda: _call_openai(content, timeout))

    content = []
    if image is not None:
        content.append({"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": _b64(image)}})
    content.append({"type": "text", "text": prompt})
    return _with_retries(lambda: _call_anthropic(content, timeout))


# --------------------------------------------------------------------------- parsing


def _normalise_category(raw) -> str | None:
    """Map the model's answer onto our closed taxonomy, or reject it."""
    if raw is None:
        return None
    value = str(raw).strip().lower()
    if not value or value in ("null", "none", "unknown"):
        return None
    value = value.replace(" ", "_").replace("-", "_")
    if value in CLASS_KEYS:
        return value
    # Accept a display label ("Oil Filter" -> oil_filter) or a loose variant.
    for key in CLASS_KEYS:
        variants = {
            key,
            label_for(key).lower().replace(" ", "_"),
            key.replace("_", ""),
            label_for(key).lower().replace(" ", ""),
        }
        if value in variants or value.replace("_", "") in variants:
            return key
    raise CloudVisionError(f"model returned a category outside the taxonomy: {raw!r}")


def _clean_str(value, limit: int = 64) -> str | None:
    """Coerce a model field to a trimmed string, treating junk as absent."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in ("null", "none", "n/a", "na", "unknown", "not visible", "unreadable"):
        return None
    return text[:limit]


def _confidence(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number:  # NaN
        return 0.0
    return round(min(max(number, 0.0), 1.0), 4)


# --------------------------------------------------------------------------- public API


def classify(raw: bytes, mime_type: str = "image/jpeg") -> dict:
    """
    Identify a part from a photograph.

    Returns the predictions list plus anything readable on the part. The visible
    part number is the most valuable field: it feeds the exact-match path, which is
    the only route to a `confirmed` fitment verdict.
    """
    started = time.perf_counter()
    text = _ask(CLASSIFY_PROMPT.format(categories=_CLASS_LIST), image=raw, mime_type=mime_type)
    obj = _extract_json(text)
    latency_ms = round((time.perf_counter() - started) * 1000, 1)

    category = _normalise_category(obj.get("category"))
    confidence = _confidence(obj.get("confidence"))
    is_part = bool(obj.get("is_part_photo", category is not None))

    brand = _clean_str(obj.get("visible_brand"), 40)
    part_number = _clean_str(obj.get("visible_part_number"), 40)

    predictions = []
    if category is not None and is_part:
        predictions.append(
            {
                "category": category,
                "label": label_for(category),
                "confidence": confidence,
                "safetyCritical": is_safety_critical(category),
                "classIndex": CLASS_KEYS.index(category),
            }
        )

    return {
        "predictions": predictions,
        "modelVersion": f"cloud:{model_name()}",
        "backend": provider_name(),
        "latencyMs": latency_ms,
        "confidenceSource": "model_self_report",
        "noPartDetected": not predictions,
        "reasoning": _clean_str(obj.get("reasoning"), 300) or "",
        "visibleBrand": brand,
        "visiblePartNumber": part_number,
    }


def read_label(raw: bytes, mime_type: str = "image/jpeg") -> dict:
    """
    OCR a label, box or stamped marking via the vision model.

    Replaces the PaddleOCR/EasyOCR/Tesseract stack: no system packages, no model
    downloads, and far better on angled, glared or embossed text — which is exactly
    how part numbers appear in practice.
    """
    started = time.perf_counter()
    text = _ask(LABEL_PROMPT, image=raw, mime_type=mime_type)
    obj = _extract_json(text)
    return {
        "engine": f"{provider_name()}:{model_name()}",
        "text": str(obj.get("text") or ""),
        "confidence": _confidence(obj.get("confidence")),
        "notes": _clean_str(obj.get("notes"), 160),
        "latencyMs": round((time.perf_counter() - started) * 1000, 1),
    }


def interpret_description(description: str) -> dict:
    """
    Turn a free-text description into a category, so the app is usable with no
    photograph at all. Returns an empty prediction list when the description is too
    vague — the API's confidence floor then asks the user for more detail, which is
    the correct behaviour rather than a guess.
    """
    if not description or not description.strip():
        raise CloudVisionError("empty description")

    started = time.perf_counter()
    prompt = (
        f"{DESCRIBE_PROMPT.format(categories=_CLASS_LIST)}\n\n"
        f"User description: {description.strip()[:600]}"
    )
    text = _ask(prompt)
    obj = _extract_json(text)
    latency_ms = round((time.perf_counter() - started) * 1000, 1)

    category = _normalise_category(obj.get("category"))
    confidence = _confidence(obj.get("confidence"))

    predictions = []
    if category is not None:
        predictions.append(
            {
                "category": category,
                "label": label_for(category),
                "confidence": confidence,
                "safetyCritical": is_safety_critical(category),
                "classIndex": CLASS_KEYS.index(category),
            }
        )

    return {
        "predictions": predictions,
        "modelVersion": f"cloud:{model_name()}",
        "backend": provider_name(),
        "latencyMs": latency_ms,
        "confidenceSource": "model_self_report",
        "noPartDetected": not predictions,
        "reasoning": _clean_str(obj.get("reasoning"), 300) or "",
        "visibleBrand": _clean_str(obj.get("visible_brand"), 40),
        "visiblePartNumber": _clean_str(obj.get("visible_part_number"), 40),
    }


def list_models() -> list[str]:
    """
    Ask the provider which models the key can actually use.

    Exists because guessing a model name from memory is unreliable — model ids are
    added and retired constantly. `scripts/check-gemini.sh` runs this so setup is
    verifiable instead of a stack trace.
    """
    name = provider_name()
    key = _resolve_key(name)
    if key is None:
        raise CloudVisionError(f"no API key for provider {name!r}")
    if name != "gemini":
        raise CloudVisionError(f"model listing is only implemented for gemini, not {name!r}")

    timeout = int(os.environ.get("VISION_TIMEOUT", "30"))
    req = urllib.request.Request(f"{base_url('gemini')}/models?key={key}", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise CloudVisionError(f"HTTP {exc.code} listing models: {exc.read().decode('utf-8', 'replace')[:200]}") from exc
    except urllib.error.URLError as exc:
        raise CloudVisionError(f"provider unreachable: {exc.reason}") from exc

    out = []
    for model in data.get("models", []):
        methods = model.get("supportedGenerationMethods") or []
        if "generateContent" in methods:
            out.append(str(model.get("name", "")).replace("models/", ""))
    return sorted(out)
