"""
Tests for the identification provider (Gemini by default, plus OpenAI/Anthropic).

    python ai-service/tests/test_cloud_vision.py

This sandbox has no route to the real provider APIs, so the tests split into three
groups:

  * Pure functions — reply parsing, taxonomy validation, confidence clamping, junk
    coercion. No network, no environment.
  * Configuration — provider selection, key resolution, which engine is live.
  * The three calls, with `_post_json` monkeypatched to return provider-shaped
    payloads. The failure paths matter most: a broken provider must raise a
    CloudVisionError so `app.main` falls back down the engine ladder, never fail the
    user's request.

The exact wire format is covered separately, against a local HTTP server that speaks
it: `test_gemini_integration.py`. That suite is authoritative for the request shape;
this one is authoritative for everything else.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import cloud_vision  # noqa: E402
from app.taxonomy import CLASS_KEYS  # noqa: E402

PASS = FAIL = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}{f' — {detail}' if detail else ''}")


def expect_raises(name: str, fn, exc=cloud_vision.CloudVisionError) -> None:
    try:
        fn()
    except exc:
        check(name, True)
    except Exception as other:  # noqa: BLE001
        check(name, False, f"wrong exception: {type(other).__name__}: {other}")
    else:
        check(name, False, "no exception raised")


def with_env(**env):
    """Context manager to set/clear env vars around a block."""
    class _Ctx:
        def __enter__(self):
            self.saved = {k: os.environ.get(k) for k in env}
            for k, v in env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            return self

        def __exit__(self, *exc):
            for k, v in self.saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            return False
    return _Ctx()


NO_KEY = dict(
    VISION_API_KEY=None, GEMINI_API_KEY=None, GOOGLE_API_KEY=None,
    OPENAI_API_KEY=None, ANTHROPIC_API_KEY=None,
)
NO_OVERRIDE = dict(VISION_MODEL=None, VISION_BASE_URL=None)

# --------------------------------------------------------------------- parsing

print("--- reply parsing: _extract_json ---")
check(
    "plain JSON object",
    cloud_vision._extract_json('{"category":"oil_filter","confidence":0.8}')["category"] == "oil_filter",
)
check(
    "markdown-fenced JSON",
    cloud_vision._extract_json('```json\n{"category":"belt"}\n```')["category"] == "belt",
)
check(
    "prose wrapped around JSON",
    cloud_vision._extract_json('Here you go:\n{"category":"spark_plug"} Hope that helps!')["category"]
    == "spark_plug",
)
# The regression that motivated raw_decode over find/rfind slicing:
check(
    "trailing prose containing braces",
    cloud_vision._extract_json('{"category":"brake_pad"} (0.6 = {moderate})')["category"] == "brake_pad",
)
check(
    "leading brace inside prose before the object",
    cloud_vision._extract_json('note {see below}: {"category":"drive_belt"}')["category"] == "drive_belt",
)
check(
    "nested object parsed whole",
    cloud_vision._extract_json('{"category":"belt","meta":{"a":{"b":1}}}')["meta"]["a"]["b"] == 1,
)

print("\n--- reply parsing rejects bad input ---")
expect_raises("empty response", lambda: cloud_vision._extract_json(""))
expect_raises("whitespace only", lambda: cloud_vision._extract_json("   \n  "))
expect_raises("no JSON at all", lambda: cloud_vision._extract_json("I cannot identify this part."))
expect_raises("malformed JSON", lambda: cloud_vision._extract_json('{"category": "belt",'))
expect_raises("JSON array instead of object", lambda: cloud_vision._extract_json('["belt"]'))

# --------------------------------------------------------------------- taxonomy

print("\n--- category normalisation (closed taxonomy) ---")


def cat(raw: str):
    return cloud_vision._normalise_category(raw)


check("exact key accepted", cat("oil_filter") == "oil_filter")
check("display label accepted", cat("Oil Filter") == "oil_filter")
check("spaces normalised", cat("clutch plate") == "clutch_plate")
check("hyphens normalised", cat("clutch-plate") == "clutch_plate")
check("mixed case accepted", cat("BRAKE_PAD") == "brake_pad")
check("surrounding whitespace tolerated", cat("  belt  ") == "belt")
check("null -> None", cat(None) is None)
check("empty string -> None", cat("") is None)
check("'null' string -> None", cat("null") is None)
check("'unknown' -> None", cat("unknown") is None)
expect_raises("invented category rejected", lambda: cat("flux_capacitor"))
expect_raises("plausible-but-absent category rejected", lambda: cat("radiator_cap"))

print("\n--- confidence clamping ---")
check("0.8 preserved", cloud_vision._confidence(0.8) == 0.8)
check("> 1 clamped", cloud_vision._confidence(1.9) == 1.0)
check("< 0 clamped", cloud_vision._confidence(-3) == 0.0)
check("numeric string accepted", cloud_vision._confidence("0.5") == 0.5)
check("missing -> 0", cloud_vision._confidence(None) == 0.0)
check("garbage -> 0", cloud_vision._confidence("very") == 0.0)
check("NaN -> 0", cloud_vision._confidence(float("nan")) == 0.0)

print("\n--- junk coercion for text fields ---")
check("None -> None", cloud_vision._clean_str(None) is None)
check("blank -> None", cloud_vision._clean_str("   ") is None)
check("'null' -> None", cloud_vision._clean_str("null") is None)
check("'not visible' -> None", cloud_vision._clean_str("not visible") is None)
check("real value kept", cloud_vision._clean_str(" Bosch ") == "Bosch")
check("over-long truncated", len(cloud_vision._clean_str("x" * 500, 40)) == 40)

# ---------------------------------------------------------------- configuration

print("\n--- provider selection and key resolution ---")
with with_env(VISION_PROVIDER=None, VISION_BASE_URL=None, **NO_KEY):
    check("default provider is gemini", cloud_vision.provider_name() == "gemini")
    check("gemini without a key -> disabled", cloud_vision.enabled() is False)
    check("status reports no key", cloud_vision.status()["hasKey"] is False)

with with_env(VISION_PROVIDER="openai", **NO_KEY):
    check("openai without a key -> disabled", cloud_vision.enabled() is False)

with with_env(VISION_PROVIDER="openai", VISION_API_KEY="sk-test", OPENAI_API_KEY=None):
    check("openai with VISION_API_KEY -> enabled", cloud_vision.enabled() is True)
    check("status reports hasKey", cloud_vision.status()["hasKey"] is True)
    check("status lists capabilities", cloud_vision.status()["capabilities"] != [])

with with_env(VISION_PROVIDER="anthropic", VISION_API_KEY=None, ANTHROPIC_API_KEY="sk-ant"):
    check("anthropic falls back to its own env var", cloud_vision.enabled() is True)

with with_env(VISION_PROVIDER="gemini", VISION_API_KEY=None, GOOGLE_API_KEY="gg"):
    check("gemini accepts GOOGLE_API_KEY", cloud_vision.enabled() is True)

with with_env(VISION_PROVIDER="gemini", VISION_API_KEY=None, GEMINI_API_KEY="gk-test"):
    check("gemini accepts GEMINI_API_KEY", cloud_vision.enabled() is True)

with with_env(VISION_PROVIDER="gemini", VISION_API_KEY="  spaced-key  "):
    check("key is trimmed", cloud_vision.status()["hasKey"] is True)

with with_env(VISION_PROVIDER="local", VISION_API_KEY="x"):
    check("explicit local -> disabled", cloud_vision.enabled() is False)

with with_env(VISION_PROVIDER="flux-capacitor", VISION_API_KEY="x"):
    check("unknown provider name -> disabled", cloud_vision.enabled() is False)

print("\n--- model and endpoint defaults ---")
with with_env(VISION_PROVIDER="gemini", **NO_OVERRIDE):
    check("gemini default model", cloud_vision.model_name() == "gemini-2.0-flash")
    check("gemini default base url", cloud_vision.base_url().startswith("https://generativelanguage"))
with with_env(VISION_PROVIDER="openai", **NO_OVERRIDE):
    check("openai default model", cloud_vision.model_name() == "gpt-4o")
with with_env(VISION_PROVIDER="gemini", VISION_MODEL="gemini-2.5-flash"):
    check("VISION_MODEL overrides", cloud_vision.model_name() == "gemini-2.5-flash")
with with_env(VISION_PROVIDER="gemini", VISION_BASE_URL="http://127.0.0.1:9099/"):
    check("VISION_BASE_URL overrides and strips slash", cloud_vision.base_url() == "http://127.0.0.1:9099")
with with_env(VISION_PROVIDER="gemini", VISION_BASE_URL=None):
    check("no override -> real endpoint", "googleapis.com" in cloud_vision.base_url())

with with_env(VISION_PROVIDER="openai", VISION_API_KEY=None, OPENAI_API_KEY=None):
    expect_raises("classify without a key raises", lambda: cloud_vision.classify(b"x"))
    expect_raises("read_label without a key raises", lambda: cloud_vision.read_label(b"x"))

# ------------------------------------------------------------------ happy paths

print("\n--- success path (transport monkeypatched, provider-shaped payloads) ---")


def wrap(provider: str, inner: str) -> dict:
    """Build the raw HTTP payload each provider would return."""
    if provider == "gemini":
        return {"candidates": [{"content": {"parts": [{"text": inner}], "role": "model"},
                                "finishReason": "STOP"}]}
    if provider == "openai":
        return {"choices": [{"message": {"content": inner}}]}
    return {"content": [{"text": inner}]}


CLASSIFY_BODY = ('{"category":"fuel_filter","confidence":0.77,'
                 '"visible_brand":"Bosch","visible_part_number":"0450905273",'
                 '"reasoning":"cylindrical diesel canister","is_part_photo":true}')
LABEL_BODY = '{"text":"MGP GENUINE PARTS\\n16510-61A31\\nOIL FILTER","confidence":0.91,"notes":"slight glare"}'

real_post = cloud_vision._post_json
try:
    for provider in ("gemini", "openai", "anthropic"):
        cloud_vision._post_json = (lambda url, payload, headers, timeout, p=provider:
                                   wrap(p, CLASSIFY_BODY))
        with with_env(VISION_PROVIDER=provider, VISION_API_KEY="test-key",
                      VISION_BASE_URL=None, VISION_MODEL=None):
            result = cloud_vision.classify(b"\xff\xd8\xff", "image/jpeg")
            top = result["predictions"][0]
            check(f"{provider}: one prediction returned", len(result["predictions"]) == 1)
            check(f"{provider}: backend reported", result["backend"] == provider)
            check(f"{provider}: category in taxonomy", top["category"] in CLASS_KEYS)
            check(f"{provider}: label resolved", top["label"] == "Fuel Filter")
            check(f"{provider}: confidence carried", abs(top["confidence"] - 0.77) < 1e-9)
            check(f"{provider}: classIndex valid", top["classIndex"] == CLASS_KEYS.index("fuel_filter"))
            check(f"{provider}: safetyCritical computed", "safetyCritical" in top)
            check(f"{provider}: confidenceSource labelled",
                  result["confidenceSource"] == "model_self_report")
            check(f"{provider}: modelVersion names the model",
                  result["modelVersion"].startswith("cloud:"))
            check(f"{provider}: visible part number surfaced",
                  result["visiblePartNumber"] == "0450905273")
            check(f"{provider}: visible brand surfaced", result["visibleBrand"] == "Bosch")
            check(f"{provider}: not flagged as no-part", result["noPartDetected"] is False)

    # read_label
    for provider in ("gemini", "openai", "anthropic"):
        cloud_vision._post_json = (lambda url, payload, headers, timeout, p=provider:
                                   wrap(p, LABEL_BODY))
        with with_env(VISION_PROVIDER=provider, VISION_API_KEY="test-key",
                      VISION_BASE_URL=None, VISION_MODEL=None):
            out = cloud_vision.read_label(b"\xff\xd8\xff")
            check(f"{provider}: label text returned", "16510-61A31" in out["text"])
            check(f"{provider}: label confidence returned", out["confidence"] == 0.91)
            check(f"{provider}: label engine names provider:model",
                  out["engine"] == f"{provider}:{cloud_vision.model_name(provider)}")
            check(f"{provider}: label notes carried", out["notes"] == "slight glare")

    # interpret_description — no image at all
    cloud_vision._post_json = lambda url, payload, headers, timeout: wrap(
        "gemini", '{"category":"oil_filter","confidence":0.71,"reasoning":"metal canister"}'
    )
    with with_env(VISION_PROVIDER="gemini", VISION_API_KEY="test-key",
                  VISION_BASE_URL=None, VISION_MODEL=None):
        out = cloud_vision.interpret_description("a round metal canister that screws onto the block")
        check("describe: category returned", out["predictions"][0]["category"] == "oil_filter")
        check("describe: confidenceSource labelled", out["confidenceSource"] == "model_self_report")
        check("describe: reasoning carried", out["reasoning"] == "metal canister")
        expect_raises("describe: empty description rejected",
                      lambda: cloud_vision.interpret_description("   "))
finally:
    cloud_vision._post_json = real_post

# ----------------------------------------------------------------- failure paths

print("\n--- degraded answers that are answers, not errors ---")
for label, body, expected in [
    ("null category", '{"category":null,"confidence":0.0,"is_part_photo":false}', None),
    ("category 'unknown'", '{"category":"unknown","confidence":0.2}', None),
]:
    cloud_vision._post_json = lambda url, payload, headers, timeout, b=body: wrap("gemini", b)
    with with_env(VISION_PROVIDER="gemini", VISION_API_KEY="test-key", VISION_BASE_URL=None):
        result = cloud_vision.classify(b"x")
        check(f"{label}: no prediction returned", result["predictions"] == [])
        check(f"{label}: flagged noPartDetected", result["noPartDetected"] is True)
        check(f"{label}: still a valid response, not an exception", result["backend"] == "gemini")

# A part photo with a category is a prediction even if the model says is_part_photo false —
# we trust the category over the flag, and the API's confidence floor still applies.
cloud_vision._post_json = lambda url, payload, headers, timeout: wrap(
    "gemini", '{"category":"belt","confidence":0.4,"is_part_photo":false}'
)
with with_env(VISION_PROVIDER="gemini", VISION_API_KEY="test-key", VISION_BASE_URL=None):
    result = cloud_vision.classify(b"x")
    check("is_part_photo=false suppresses the prediction", result["predictions"] == [])
cloud_vision._post_json = real_post

print("\n--- provider failure raises, so the caller can fall back ---")


def raising(exc):
    def _fn(*a, **k):
        raise exc
    return _fn


with with_env(VISION_PROVIDER="openai", VISION_API_KEY="test-key", VISION_BASE_URL=None):
    cloud_vision._post_json = raising(
        cloud_vision.CloudVisionError("simulated 500 from provider", retryable=True, status=500)
    )
    try:
        expect_raises("transport error surfaces as CloudVisionError", lambda: cloud_vision.classify(b"x"))
    finally:
        cloud_vision._post_json = real_post

with with_env(VISION_PROVIDER="openai", VISION_API_KEY="test-key", VISION_BASE_URL=None, VISION_RETRIES="1"):
    cloud_vision._post_json = lambda *a, **k: {"choices": [{"message": {"content": "not json at all"}}]}
    try:
        expect_raises("unparseable reply surfaces as CloudVisionError", lambda: cloud_vision.classify(b"x"))
    finally:
        cloud_vision._post_json = real_post

with with_env(VISION_PROVIDER="gemini", VISION_API_KEY="test-key", VISION_BASE_URL=None, VISION_RETRIES="1"):
    cloud_vision._post_json = lambda *a, **k: wrap(
        "gemini", '{"category":"flux_capacitor","confidence":0.99}'
    )
    try:
        expect_raises("out-of-taxonomy reply surfaces as CloudVisionError",
                      lambda: cloud_vision.classify(b"x"))
    finally:
        cloud_vision._post_json = real_post

with with_env(VISION_PROVIDER="gemini", VISION_API_KEY="test-key", VISION_BASE_URL=None, VISION_RETRIES="1"):
    cloud_vision._post_json = lambda *a, **k: {"candidates": []}
    try:
        expect_raises("empty candidates list surfaces as CloudVisionError",
                      lambda: cloud_vision.classify(b"x"))
    finally:
        cloud_vision._post_json = real_post

print("\n--- retry behaviour ---")
state = {"n": 0}
with with_env(VISION_PROVIDER="gemini", VISION_API_KEY="test-key", VISION_BASE_URL=None,
              VISION_RETRIES="3"):
    def flaky(url, payload, headers, timeout):
        state["n"] += 1
        if state["n"] == 1:
            raise cloud_vision.CloudVisionError("HTTP 503", retryable=True, status=503)
        return wrap("gemini", CLASSIFY_BODY)

    cloud_vision._post_json = flaky
    try:
        result = cloud_vision.classify(b"x")  # sleeps ~1.5s on the one retry
        check("retryable error is retried and succeeds", state["n"] == 2)
        check("retried call returns the good result", result["predictions"][0]["category"] == "fuel_filter")
    finally:
        cloud_vision._post_json = real_post

state["n"] = 0
with with_env(VISION_PROVIDER="gemini", VISION_API_KEY="test-key", VISION_BASE_URL=None,
              VISION_RETRIES="3"):
    def not_retryable(url, payload, headers, timeout):
        state["n"] += 1
        raise cloud_vision.CloudVisionError("HTTP 400", retryable=False, status=400)

    cloud_vision._post_json = not_retryable
    try:
        expect_raises("non-retryable error is not retried", lambda: cloud_vision.classify(b"x"))
        check("only one attempt made for a 400", state["n"] == 1)
    finally:
        cloud_vision._post_json = real_post

print(f"\nRESULT: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
