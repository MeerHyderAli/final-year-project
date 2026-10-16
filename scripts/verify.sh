#!/usr/bin/env bash
# Acceptance checks for the AutoParts AI prototype.
#
#   bash scripts/verify.sh          # expects the API on :4000 and identification on :8000
#
# Every assertion here maps to a line in docs/REQUIREMENTS.md §7 (definition of done).
# The point is not coverage — it is that the *honesty* behaviours are executable
# claims rather than prose promises.
#
# Exit code: 0 when every check passes, 1 otherwise.
set -u
cd "$(dirname "$0")/.."

PASS=0; FAIL=0
chk() { # name, expected, actual
  if [ "$2" = "$3" ]; then echo "  PASS  $1"; PASS=$((PASS+1));
  else echo "  FAIL  $1 (expected '$2', got '$3')"; FAIL=$((FAIL+1)); fi
}
A=localhost:4000/api
V=localhost:8000

echo "--- health & catalogue ---"
chk "health ok" "ok" "$(curl -s $A/health | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"])')"
chk "ai reachable" "True" "$(curl -s $A/health | python3 -c 'import json,sys;print(json.load(sys.stdin)["aiService"]["ok"])')"
chk "18 parts" "18" "$(curl -s $A/catalog/parts | python3 -c 'import json,sys;print(json.load(sys.stdin)["count"])')"
chk "part lookup by number" "part-oil-filter-swift-01" "$(curl -s "$A/catalog/parts/lookup?partNumber=16510-61a31" | python3 -c 'import json,sys;print(json.load(sys.stdin)["part"]["id"])')"

echo "--- fitment verdicts ---"
fv() { curl -s -X POST $A/fitment/analyse -H 'Content-Type: application/json' -d "$1" | python3 -c 'import json,sys;print(json.load(sys.stdin)["stage2_fitment"]["verdict"])'; }
chk "part# + right vehicle -> confirmed"      "confirmed"           "$(fv '{"partNumber":"16510-61A31","vehicleId":"veh-maruti-swift-2018-k12m"}')"
chk "brake pad safety-critical"               "needs_part_number"   "$(fv '{"partId":"part-brake-pad-swift-08","vehicleId":"veh-maruti-swift-2018-k12m"}')"
chk "wrong vehicle -> incompatible"           "incompatible"        "$(fv '{"partId":"part-oil-filter-swift-01","vehicleId":"veh-jcb-3dx-2012"}')"
chk "unknown part number"                     "unknown_part_number" "$(fv '{"partNumber":"ZZZ-999-NOPE"}')"
chk "no vehicle -> needs info"                "needs_vehicle_info"  "$(fv '{"partId":"part-oil-filter-swift-01"}')"
chk "oil filter, right vehicle -> compatible" "compatible"          "$(fv '{"partId":"part-oil-filter-swift-01","vehicleId":"veh-maruti-swift-2018-k12m"}')"

echo "--- fitment must never be inferred from an image or a guess ---"
# A number the model read off a photo is evidence, not truth. If it is not in the
# catalogue the answer must degrade, never become "confirmed".
chk "number read from photo, not in catalogue -> not confirmed" "needs_vehicle_info" \
  "$(fv '{"visiblePartNumber":"XX-9999-ZZ","category":"oil_filter"}')"
chk "number read from photo, in catalogue -> confirmed" "confirmed" \
  "$(fv '{"visiblePartNumber":"16510-61A31","vehicleId":"veh-maruti-swift-2018-k12m"}')"
chk "a bare category is never fitment" "needs_vehicle_info" \
  "$(fv '{"category":"oil_filter"}')"

echo "--- price engine honesty ---"
curl -s "$A/price/compare?partId=part-brake-pad-nexon-09" > /tmp/px.json
chk "out-of-stock flagged" "out_of_stock" "$(python3 -c 'import json;print([q["stockStatus"] for q in json.load(open("/tmp/px.json"))["quote"]["quotes"] if q["stockStatus"]=="out_of_stock"][0])')"
chk "spread computed"      "True"         "$(python3 -c 'import json;d=json.load(open("/tmp/px.json"))["quote"];print(d["stats"]["spreadPct"] is not None)')"
chk "disclaimer present"   "True"         "$(python3 -c 'import json;print(len(json.load(open("/tmp/px.json"))["quote"]["disclaimer"])>50)')"
chk "no-offer part has no quotes" "0"    "$(curl -s "$A/price/compare?partId=part-hydraulic-hose-jcb-17" | python3 -c 'import json,sys;print(json.load(sys.stdin)["quote"]["stats"]["count"])')"
chk "no-offer part refuses to estimate" "none" "$(curl -s "$A/price/compare?partId=part-hydraulic-hose-jcb-17" | python3 -c 'import json,sys;print(json.load(sys.stdin)["quote"]["dataQuality"]["level"])')"
chk "no-offer part has no cheapest" "None" "$(curl -s "$A/price/compare?partId=part-hydraulic-hose-jcb-17" | python3 -c 'import json,sys;print(json.load(sys.stdin)["quote"]["cheapest"])')"
chk "brake shoe (safety-critical, no offer) still 404-free" "needs_part_number" "$(curl -s -X POST $A/fitment/analyse -H 'Content-Type: application/json' -d '{"partId":"part-brake-shoe-jd-18","vehicleId":"veh-john-deere-5050d-2010"}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["stage2_fitment"]["verdict"])')"

echo "--- nearby ranking ---"
curl -s "$A/nearby?lat=12.9716&lng=77.5946&partId=part-oil-filter-swift-01" > /tmp/nb.json
chk "caveat present" "True" "$(python3 -c 'import json;print(len(json.load(open("/tmp/nb.json"))["caveat"])>40)')"
chk "ranked ascending" "True" "$(python3 -c '
import json; r=json.load(open("/tmp/nb.json"))["results"]; s=[x["score"] for x in r]; print(s==sorted(s))')"
chk "availability claims carry evidence" "True" "$(python3 -c '
import json; r=json.load(open("/tmp/nb.json"))["results"]; print(all(x["availability"]["evidence"] for x in r))')"

echo "--- OCR path ---"
chk "ocr finds code in text" "True" "$(curl -s -X POST $A/ocr -F "rawText=Some label MG PARTS 16510-61A31 lot 22" | python3 -c '
import json,sys; d=json.load(sys.stdin); print(d["decision"]=="exact_catalogue_match")')"

echo "--- identification service: no training, no dataset ---"
chk "service healthy" "ok" "$(curl -s $V/health | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"])')"
chk "no model training required" "False" "$(curl -s $V/health | python3 -c 'import json,sys;print(json.load(sys.stdin)["requiresTraining"])')"
chk "no image dataset required"  "False" "$(curl -s $V/health | python3 -c 'import json,sys;print(json.load(sys.stdin)["requiresDataset"])')"
chk "an engine identifies itself" "True" "$(curl -s $V/health | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["engine"])>0)')"
chk "only suggests, never asserts fitment" "True" "$(curl -s $V/health | python3 -c 'import json,sys;print(json.load(sys.stdin)["categoryOnly"])')"
chk "API proxies the engine state" "True" "$(curl -s $A/identify/health | python3 -c 'import json,sys;print(json.load(sys.stdin)["reachable"])')"

ENGINE="$(curl -s $V/health | python3 -c 'import json,sys;print(json.load(sys.stdin)["engine"])')"

# A sample image is needed for the /predict checks. Real photographs and generated
# datasets both live in git-ignored directories, so on a fresh clone neither exists —
# generate a throwaway placeholder instead of failing for an environmental reason.
IMG=""
for candidate in ai-service/eval/real-photos/*.jpg data/images/*.jpg; do
  [ -f "$candidate" ] && IMG="$candidate" && break
done
if [ -z "$IMG" ]; then
  IMG="$(python3 - <<'PY' 2>/dev/null || true
from PIL import Image
import os, tempfile
path = os.path.join(tempfile.gettempdir(), "autoparts-verify-sample.png")
Image.new("RGB", (320, 320), (40, 80, 190)).save(path)
print(path)
PY
)"
  [ -n "$IMG" ] && echo "  note: generated placeholder image for the /predict checks"
fi

if [ "$ENGINE" = "heuristic" ]; then
  echo "  SKIP  engine is 'heuristic' (no API key, no checkpoint) — /predict would only guess"
elif [ -z "$IMG" ]; then
  echo "  SKIP  could not obtain a sample image (Pillow missing?)"
else
  echo "  note: engine = $ENGINE"
  PRED_OUT="$(curl -s -m 60 -X POST $V/predict -F "file=@$IMG")"
  chk "predict returns ranked predictions" "True" "$(printf '%s' "$PRED_OUT" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(len(d["predictions"])>=1)')"
  chk "category-only flag" "True" "$(printf '%s' "$PRED_OUT" | python3 -c 'import json,sys;print(json.load(sys.stdin)["categoryOnly"])')"
  chk "confidence floor reported" "0.55" "$(printf '%s' "$PRED_OUT" | python3 -c 'import json,sys;print(json.load(sys.stdin)["confidenceFloor"])')"
  chk "prediction is in the taxonomy" "True" "$(printf '%s' "$PRED_OUT" | python3 -c 'import json,sys;print(json.load(sys.stdin)["predictions"][0]["category"] in ["oil_filter","air_filter","fuel_filter","brake_pad","belt","spark_plug","clutch_plate","hydraulic_filter"])')"
  chk "confidence source declared" "True" "$(printf '%s' "$PRED_OUT" | python3 -c 'import json,sys;print(len(json.load(sys.stdin).get("confidenceSource") or "")>0)')"
fi
chk "rejects non-image" "415" "$(curl -s -o /dev/null -w '%{http_code}' -X POST $V/predict -F "file=@README.md")"

echo "--- describe path (no photo needed) ---"
DESC_OUT="$(curl -s -m 60 -X POST $A/describe -H 'Content-Type: application/json' -d '{"description":"round metal canister that screws onto the engine block"}')"
chk "describe answers" "True" "$(printf '%s' "$DESC_OUT" | python3 -c 'import json,sys;print(len(json.load(sys.stdin).get("decision") or "")>0)')"
chk "describe is flagged weaker than a photo" "weaker_than_photo" "$(printf '%s' "$DESC_OUT" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("evidenceStrength",""))')"
chk "describe carries no fitment claim" "True" "$(printf '%s' "$DESC_OUT" | python3 -c '
import json,sys; d=json.load(sys.stdin); print("fits" not in json.dumps(d).lower() or d.get("requiresHumanCheck") is not False)')"

echo
echo "RESULT: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
