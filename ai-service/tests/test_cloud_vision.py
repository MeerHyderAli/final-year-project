"""
Tests for the cloud vision provider.

    python ai-service/tests/test_cloud_vision.py

The live provider calls cannot be exercised here (this sandbox has no route to
OpenAI/Gemini/Anthropic), so the tests split into two groups:

  * Everything that does not need the network is tested directly — reply parsing,
    taxonomy validation, provider selection, key resolution.
  * The provider transport is monkeypatched with canned responses to test the
    success path, and pointed at an unreachable host to test the failure path.
    The failure path is the important one: a broken provider must degrade to the
    local model, never fail the user's request.
"""

from __future__ import annotations

import json
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


print("--- reply parsing ---")
check(
    "plain JSON object",
    cloud_vision.parse_reply('{"category":"oil_filter","confidence":0.8}')["category"] == "oil_filter",
)
check(
    "markdown-fenced JSON",
    cloud_vision.parse_reply('```json\n{"category":"belt","confidence":0.7}\n```')["category"] == "belt",
)
check(
    "prose wrapped around JSON",
    cloud_vision.parse_reply('Here you go:\n{"category":"spark_plug","confidence":0.9}\nHope that helps!')["category"]
    == "spark_plug",
)
check(
    "trailing sentence with a brace in it",
    cloud_vision.parse_reply('{"category":"brake_pad","confidence":0.6} (0.6 = {moderate})')["category"]
    == "brake_pad",
)
check(
    "category given as a display label",
    cloud_vision.parse_reply('{"category":"Oil Filter","confidence":0.5}')["category"] == "oil_filter",
)
check(
    "category given with spaces/hyphens",
    cloud_vision.parse_reply('{"category":"clutch plate","confidence":0.5}')["category"] == "clutch_plate",
)

print("\n--- reply parsing rejects bad input ---")
expect_raises("empty response", lambda: cloud_vision.parse_reply(""))
expect_raises("whitespace only", lambda: cloud_vision.parse_reply("   \n  "))
expect_raises("no JSON at all", lambda: cloud_vision.parse_reply("I cannot identify this part."))
expect_raises("malformed JSON", lambda: cloud_vision.parse_reply('{"category": "belt",'))
expect_raises("JSON array instead of object", lambda: cloud_vision.parse_reply('["belt"]'))
expect_raises(
    "category outside the taxonomy",
    lambda: cloud_vision.parse_reply('{"category":"flux_capacitor","confidence":0.9}'),
)

print("\n--- confidence clamping ---")
check("confidence > 1 clamped", cloud_vision.parse_reply('{"category":"belt","confidence":1.9}')["confidence"] == 1.0)
check("confidence < 0 clamped", cloud_vision.parse_reply('{"category":"belt","confidence":-3}')["confidence"] == 0.0)
check("missing confidence -> 0", cloud_vision.parse_reply('{"category":"belt"}')["confidence"] == 0.0)
check("garbage confidence -> 0", cloud_vision.parse_reply('{"category":"belt","confidence":"very"}')["confidence"] == 0.0)

print("\n--- null / not-a-part handling ---")
parsed = cloud_vision.parse_reply('{"category":null,"confidence":0.0,"is_part_photo":false}')
check("null category accepted", parsed["category"] is None)
check("non-part photo flagged", parsed["isPartPhoto"] is False)

print("\n--- provider selection and key resolution ---")
with with_env(VISION_PROVIDER=None, VISION_API_KEY=None, OPENAI_API_KEY=None):
    check("default is disabled", cloud_vision.enabled() is False)
    check("default provider name is local", cloud_vision.provider_name() == "local")

with with_env(VISION_PROVIDER="openai", VISION_API_KEY=None, OPENAI_API_KEY=None):
    check("openai configured without a key -> disabled", cloud_vision.enabled() is False)

with with_env(VISION_PROVIDER="openai", VISION_API_KEY="sk-test", OPENAI_API_KEY=None):
    check("openai with VISION_API_KEY -> enabled", cloud_vision.enabled() is True)
    check("status reports hasKey", cloud_vision.status()["hasKey"] is True)

with with_env(VISION_PROVIDER="anthropic", VISION_API_KEY=None, ANTHROPIC_API_KEY="sk-ant"):
    check("anthropic falls back to its own env var", cloud_vision.enabled() is True)

with with_env(VISION_PROVIDER="gemini", VISION_API_KEY=None, GOOGLE_API_KEY="gg"):
    check("gemini accepts GOOGLE_API_KEY", cloud_vision.enabled() is True)

with with_env(VISION_PROVIDER="flux-capacitor", VISION_API_KEY="x"):
    check("unknown provider name -> disabled", cloud_vision.enabled() is False)

with with_env(VISION_PROVIDER="openai", VISION_API_KEY=None, OPENAI_API_KEY=None):
    expect_raises("classify without a key raises", lambda: cloud_vision.classify(b"x"))

print("\n--- success path (transport monkeypatched) ---")
CANNED = {
    "openai": {"choices": [{"message": {"content": '{"category":"fuel_filter","confidence":0.77,"reasoning":"cylindrical diesel canister","is_part_photo":true}'}}]},
    "gemini": {"candidates": [{"content": {"parts": [{"text": '{"category":"air_filter","confidence":0.66,"is_part_photo":true}'}]}}]},
    "anthropic": {"content": [{"text": '{"category":"brake_pad","confidence":0.81,"is_part_photo":true}'}]},
}

real_post = cloud_vision._post_json
try:
    for provider, canned in CANNED.items():
        cloud_vision._post_json = lambda url, payload, headers, timeout, c=canned: c
        with with_env(VISION_PROVIDER=provider, VISION_API_KEY="test-key", VISION_MODEL=None):
            result = cloud_vision.classify(b"\xff\xd8\xff", "image/jpeg")
            top = result["predictions"][0]
            check(f"{provider}: returns a prediction", len(result["predictions"]) == 1)
            check(f"{provider}: backend reported", result["backend"] == provider)
            check(f"{provider}: category in taxonomy", top["category"] in CLASS_KEYS)
            check(
                f"{provider}: confidence flagged as self-report",
                result["confidenceSource"] == "model_self_report",
            )
            check(f"{provider}: safetyCritical computed", "safetyCritical" in top)
finally:
    cloud_vision._post_json = real_post

print("\n--- provider failure raises, so the caller can fall back ---")
with with_env(VISION_PROVIDER="openai", VISION_API_KEY="test-key"):
    cloud_vision._post_json = lambda *a, **k: (_ for _ in ()).throw(
        cloud_vision.CloudVisionError("simulated 500 from provider")
    )
    try:
        expect_raises("transport error surfaces as CloudVisionError", lambda: cloud_vision.classify(b"x"))
    finally:
        cloud_vision._post_json = real_post

with with_env(VISION_PROVIDER="openai", VISION_API_KEY="test-key"):
    cloud_vision._post_json = lambda *a, **k: {"choices": [{"message": {"content": "not json at all"}}]}
    try:
        expect_raises("unparseable reply surfaces as CloudVisionError", lambda: cloud_vision.classify(b"x"))
    finally:
        cloud_vision._post_json = real_post

print(f"\nRESULT: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
