"""
End-to-end test of the Gemini integration, without a Gemini account.

    python ai-service/tests/test_gemini_integration.py

WHY A MOCK SERVER
    The sandbox these services were built in cannot reach generativelanguage.
    googleapis.com, so the live call cannot be exercised here. Rather than skip
    testing, this spins up a local HTTP server that speaks the Gemini wire format and
    points VISION_BASE_URL at it. That exercises everything we actually control:

      * URL construction          (/models/{model}:generateContent?key=...)
      * request body shape        (contents/parts, inline_data, generationConfig)
      * response parsing          (candidates -> content -> parts -> text)
      * safety-block handling     (promptFeedback.blockReason)
      * retry on 429/5xx, and no retry on 4xx
      * the full FastAPI /predict, /ocr and /describe paths

    What it does NOT prove: that the real Gemini API behaves as documented, or that
    the model identifies parts accurately. Only a real key can show that. Once you
    have one, `bash scripts/check-gemini.sh` makes the live call.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PASS = FAIL = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}{f' — {detail}' if detail else ''}")


# --------------------------------------------------------------- mock Gemini API


class State:
    requests: list[dict] = []
    response_text = '{"category":"oil_filter","confidence":0.86,"visible_brand":"Bosch","visible_part_number":"0986452036","reasoning":"blue spin-on canister with threaded base","is_part_photo":true}'
    status_code = 200
    body_override: str | None = None
    fail_times = 0
    seen_attempts = 0


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence request logging
        pass

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # model listing
        if self.path.startswith("/models"):
            self._send(200, {
                "models": [
                    {"name": "models/gemini-2.0-flash", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]},
                ]
            })
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        State.seen_attempts += 1
        State.requests.append({"path": self.path, "body": json.loads(raw or b"{}")})

        # Simulate transient failures for the retry test.
        if State.fail_times > 0:
            State.fail_times -= 1
            self._send(503, {"error": {"message": "The model is overloaded"}})
            return

        if State.body_override is not None:
            body = State.body_override.encode()
            self.send_response(State.status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self._send(200, {
            "candidates": [{
                "content": {"parts": [{"text": State.response_text}], "role": "model"},
                "finishReason": "STOP",
            }]
        })


def start_server() -> tuple[HTTPServer, str]:
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


# ------------------------------------------------------------------------ tests

server, base = start_server()
os.environ["VISION_PROVIDER"] = "gemini"
os.environ["VISION_API_KEY"] = "test-key-123"
os.environ["VISION_BASE_URL"] = base
os.environ["VISION_RETRIES"] = "2"
os.environ["VISION_TIMEOUT"] = "5"

from app import cloud_vision  # noqa: E402  (import after env is set)

print("--- configuration ---")
check("provider is gemini", cloud_vision.provider_name() == "gemini")
check("enabled with a key present", cloud_vision.enabled() is True)
check("base URL override honoured", cloud_vision.base_url() == base)
check("status reports capabilities", len(cloud_vision.status()["capabilities"]) == 3)

print("\n--- wire format ---")
import base64 as _b64mod

SAMPLE_BYTES = b"\xff\xd8\xff\xe0fake-jpeg-bytes"
EXPECTED_B64 = _b64mod.b64encode(SAMPLE_BYTES).decode()
State.requests.clear()
result = cloud_vision.classify(SAMPLE_BYTES, "image/jpeg")

check("one request reached the server", len(State.requests) == 1)
req = State.requests[0] if State.requests else {"path": "", "body": {}}
check(
    "URL targets the model with the key",
    ":generateContent" in req["path"] and "key=test-key-123" in req["path"],
    req["path"],
)
parts = (req["body"].get("contents") or [{}])[0].get("parts", [])
check("request carries a text prompt", any("text" in p for p in parts))
check("request carries inline image data", any("inline_data" in p for p in parts))
inline = next((p["inline_data"] for p in parts if "inline_data" in p), {})
check("image mime type forwarded", inline.get("mime_type") == "image/jpeg")
check(
    "image is base64 encoded",
    inline.get("data") == EXPECTED_B64,
    f"got {inline.get('data')!r}, expected {EXPECTED_B64!r}",
)
check(
    "base64 decodes back to the original bytes",
    _b64mod.b64decode(inline.get("data") or "") == SAMPLE_BYTES,
)
check("responseMimeType asks for JSON", (req["body"].get("generationConfig") or {}).get("responseMimeType") == "application/json")
check("safety settings sent", len(req["body"].get("safetySettings") or []) == 4)
check("temperature is low", (req["body"].get("generationConfig") or {}).get("temperature") == 0.1)

print("\n--- response parsing ---")
check("category parsed", result["predictions"][0]["category"] == "oil_filter")
check("confidence parsed", result["predictions"][0]["confidence"] == 0.86)
check("brand read from the part", result["visibleBrand"] == "Bosch")
check("part number read from the part", result["visiblePartNumber"] == "0986452036")
check("reasoning captured", "canister" in result["reasoning"])
check("backend is gemini", result["backend"] == "gemini")
check("modelVersion names the model", result["modelVersion"].startswith("cloud:"))
check("confidence flagged as self-report", result["confidenceSource"] == "model_self_report")
check("noPartDetected is false", result["noPartDetected"] is False)

print("\n--- not-a-part and vague replies ---")
State.response_text = '{"category":null,"confidence":0.2,"reasoning":"a person, not a part","is_part_photo":false}'
res = cloud_vision.classify(b"x")
check("null category -> no predictions", res["predictions"] == [])
check("noPartDetected is true", res["noPartDetected"] is True)

State.response_text = '{"category":"oil_filter","confidence":0.4,"is_part_photo":true}'
res = cloud_vision.classify(b"x")
check("null fields tolerated (no brand/number)", res["visibleBrand"] is None and res["visiblePartNumber"] is None)

print("\n--- malformed replies are rejected ---")
State.response_text = "I'm sorry, I can't help with that."
try:
    cloud_vision.classify(b"x")
    check("non-JSON reply raises", False, "no exception")
except cloud_vision.CloudVisionError:
    check("non-JSON reply raises", True)

State.response_text = '{"category":"turbocharger","confidence":0.9,"is_part_photo":true}'
try:
    cloud_vision.classify(b"x")
    check("out-of-taxonomy category raises", False, "no exception")
except cloud_vision.CloudVisionError:
    check("out-of-taxonomy category raises", True)

print("\n--- provider error handling ---")
State.response_text = '{"category":"belt","confidence":0.7,"is_part_photo":true}'
State.body_override = json.dumps({"promptFeedback": {"blockReason": "SAFETY"}})
try:
    cloud_vision.classify(b"x")
    check("safety block raises a clear error", False, "no exception")
except cloud_vision.CloudVisionError as exc:
    check("safety block raises a clear error", "safety" in str(exc).lower(), str(exc))
State.body_override = None

State.status_code = 400
State.body_override = json.dumps({"error": {"message": "API key not valid"}})
State.seen_attempts = 0  # reset BEFORE the call, so the delta is meaningful
try:
    cloud_vision.classify(b"x")
    check("400 is not retried", False, "no exception")
except cloud_vision.CloudVisionError as exc:
    check("400 is not retried", exc.retryable is False)
    check("400 error mentions the key", "VISION_API_KEY" in str(exc), str(exc))
check("exactly one attempt for a 400", State.seen_attempts == 1, f"attempts={State.seen_attempts}")

State.body_override = None
State.status_code = 200
State.fail_times = 1
State.seen_attempts = 0
res = cloud_vision.classify(b"x")
check("retries a 503 and then succeeds", res["predictions"][0]["category"] == "belt")
check("attempts recorded for the retry", State.seen_attempts == 2, str(State.seen_attempts))

print("\n--- label reading (OCR path) ---")
State.response_text = '{"text":"MGP 16510-61A31\\nOIL FILTER\\nLot 22","confidence":0.9,"notes":"slight glare top right"}'
out = cloud_vision.read_label(b"x")
check("text transcribed", "16510-61A31" in out["text"])
check("newlines preserved", "\n" in out["text"])
check("engine names the provider", out["engine"].startswith("gemini:"))

print("\n--- description path ---")
State.response_text = '{"category":"fuel_filter","confidence":0.72,"visible_brand":"Bosch","visible_part_number":"0450905273","reasoning":"cylindrical metal canister with threaded base","is_part_photo":true}'
out = cloud_vision.interpret_description("a round metal canister with a thread that screws on near the diesel engine")
check("category inferred from text", out["predictions"][0]["category"] == "fuel_filter")
check("part number extracted from the description", out["visiblePartNumber"] == "0450905273")

State.response_text = '{"category":null,"confidence":0.1,"reasoning":"too vague","is_part_photo":true}'
out = cloud_vision.interpret_description("something under the bonnet is broken")
check("vague description yields no category", out["predictions"] == [])

print("\n--- a real prompt reached the model ---")
State.response_text = '{"category":"belt","confidence":0.8,"is_part_photo":true}'
State.requests.clear()
cloud_vision.classify(b"x")
sent = json.dumps(State.requests[-1]["body"])
check("prompt lists the taxonomy", "oil_filter" in sent and "hydraulic_filter" in sent)
check("prompt forbids inventing part numbers", "Do not invent" in sent or "do not invent" in sent.lower())
check("prompt allows a null category", "null" in sent)

print("\n--- model listing (used by check-gemini.sh) ---")
models = cloud_vision.list_models()
check("only generateContent models returned", models == ["gemini-2.0-flash", "gemini-2.5-flash"], str(models))

print("\n--- no key, no cloud ---")
os.environ.pop("VISION_API_KEY", None)
check("enabled() is false without a key", cloud_vision.enabled() is False)
try:
    cloud_vision.classify(b"x")
    check("classify without a key raises", False, "no exception")
except cloud_vision.CloudVisionError as exc:
    # NOTE: lower() both sides. "no API key" in haystack.lower() is False because
    # the needle keeps its capitals — an easy way to write a check that can never pass.
    check("classify without a key raises", "no api key" in str(exc).lower(), str(exc))
    check("error names the provider", "gemini" in str(exc).lower())

server.shutdown()

print(f"\nRESULT: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
