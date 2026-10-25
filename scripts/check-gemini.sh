#!/usr/bin/env bash
#
# Check that your Gemini (or other provider) key actually works.
#
#   export VISION_API_KEY=...        # or GEMINI_API_KEY / GOOGLE_API_KEY
#   bash scripts/check-gemini.sh
#
# Run this BEFORE the demo. It makes one real API call and tells you plainly whether
# identification will work, instead of leaving you to discover a bad key in front of
# an examiner.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

source "$ROOT/scripts/_python.sh"
PROVIDER="${VISION_PROVIDER:-gemini}"
export VISION_PROVIDER="$PROVIDER"

# Pick up the provider's own env var if VISION_API_KEY is unset.
if [ -z "${VISION_API_KEY:-}" ]; then
  case "$PROVIDER" in
    gemini)    VISION_API_KEY="${GEMINI_API_KEY:-${GOOGLE_API_KEY:-}}" ;;
    openai)    VISION_API_KEY="${OPENAI_API_KEY:-}" ;;
    anthropic) VISION_API_KEY="${ANTHROPIC_API_KEY:-}" ;;
  esac
fi

echo "════════════════════════════════════════════════════════"
echo " AI provider check"
echo "════════════════════════════════════════════════════════"
echo "  provider : $PROVIDER"
echo "  model    : ${VISION_MODEL:-(default for provider)}"
echo "  python   : $PY ${PY_ARGS[*]}"
echo

if [ -z "${VISION_API_KEY:-}" ]; then
  cat <<'EOF'
  FAIL  No API key found.

  Set one of these, then re-run:

      export VISION_API_KEY=your-key-here
      export VISION_PROVIDER=gemini          # gemini | openai | anthropic

  Get a Gemini key free at: https://aistudio.google.com/apikey
  (or use GEMINI_API_KEY / GOOGLE_API_KEY, which are picked up automatically)

  Without a key the app still runs: it falls back to the local model, which is
  accurate on rendered test images and weak on real photographs.
EOF
  exit 1
fi

# Never echo the key itself — only its shape, so you can spot a truncated paste.
echo "  key      : ${VISION_API_KEY:0:6}…${VISION_API_KEY: -4} (${#VISION_API_KEY} chars)"
echo

export VISION_API_KEY

"$PY" "${PY_ARGS[@]}" - <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, str(Path("ai-service").resolve()))
from app import cloud_vision

ok = True

print("1. Listing models available to this key…")
try:
    models = cloud_vision.list_models()
    if models:
        print(f"   OK  {len(models)} model(s) support generateContent:")
        for name in models[:12]:
            mark = "  <- default" if name == cloud_vision.model_name() else ""
            print(f"        {name}{mark}")
        configured = cloud_vision.model_name()
        if configured not in models:
            print()
            print(f"   WARNING  VISION_MODEL is '{configured}', which is not in the list above.")
            print(f"            Set VISION_MODEL to one of: {', '.join(models[:4])}")
            print("            (a retired model name returns HTTP 404 on every call)")
            ok = False
    else:
        print("   WARNING  no generateContent models returned — the key may lack access.")
        ok = False
except (cloud_vision.CloudVisionError, TimeoutError, OSError) as exc:
    print(f"   FAIL  {exc}")
    print()
    print("   Common causes:")
    print("     - the key is wrong, truncated, or revoked")
    print("     - the Generative Language API is not enabled for the project")
    print("     - this network blocks generativelanguage.googleapis.com")
    sys.exit(1)
except Exception as exc:
    # This is a user-facing diagnostic, not a debugger. Even an unusual
    # interpreter/network exception should produce a useful result, not a stack
    # trace that hides the actual next step.
    print(f"   FAIL  {type(exc).__name__}: {exc}")
    print("   The provider check could not complete. Check the network and try again.")
    sys.exit(1)

print()
print("2. Making one real identification call…")
try:
    # A tiny generated image is enough to prove the round trip works. We are testing
    # the pipe, not the model's eyesight.
    import io
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (256, 256), (60, 70, 130)).save(buf, "JPEG")
    result = cloud_vision.classify(buf.getvalue(), "image/jpeg")

    print(f"   OK  round trip completed in {result['latencyMs']:.0f} ms")
    print(f"       model        : {result['modelVersion']}")
    if result["predictions"]:
        top = result["predictions"][0]
        print(f"       it guessed   : {top['label']} ({top['confidence']:.0%})")
        print("       (a flat blue square is not a part — a low or null answer here is")
        print("        the CORRECT behaviour, not a failure)")
    else:
        print("       it correctly declined to name a category for a blank image")
except (cloud_vision.CloudVisionError, TimeoutError, OSError) as exc:
    print(f"   FAIL  {exc}")
    if isinstance(exc, TimeoutError) or "timed out" in str(exc).lower():
        print("   The API accepted the model-list request, but generation did not answer in time.")
        print("   Try a longer timeout and the flash model, for example:")
        print("     VISION_MODEL=gemini-2.5-flash VISION_TIMEOUT=60 bash scripts/check-gemini.sh")
    ok = False
except Exception as exc:
    print(f"   FAIL  {type(exc).__name__}: {exc}")
    print("   The provider check could not complete; no identification result was accepted.")
    ok = False

print()
print("3. Prompt size sanity…")
print(f"   max output tokens: not limited locally; provider default applies")
print(f"   confidence floor : 0.55 (below this the API asks for more detail)")

print()
if ok:
    print("   RESULT: provider is working. Start the services and image ID will use it.")
    print("           bash scripts/dev.sh")
else:
    print("   RESULT: provider responded but something needs attention (see above).")
sys.exit(0 if ok else 2)
PY

STATUS=$?
echo "════════════════════════════════════════════════════════"
exit "$STATUS"
