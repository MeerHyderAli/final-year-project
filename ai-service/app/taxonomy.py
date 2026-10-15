"""
Shared taxonomy for the AutoParts AI vision service.

The order of `CATEGORIES` is the model's class order. It MUST stay identical to
`backend/src/taxonomy.js` and the records in `data/parts.json`.
"""

CATEGORIES = [
    {"key": "oil_filter", "label": "Oil Filter", "safety_critical": False},
    {"key": "air_filter", "label": "Air Filter", "safety_critical": False},
    {"key": "fuel_filter", "label": "Fuel Filter", "safety_critical": False},
    {"key": "brake_pad", "label": "Brake Pad", "safety_critical": True},
    {"key": "belt", "label": "Drive Belt", "safety_critical": False},
    {"key": "spark_plug", "label": "Spark Plug", "safety_critical": False},
    {"key": "clutch_plate", "label": "Clutch Plate", "safety_critical": True},
    {"key": "hydraulic_filter", "label": "Hydraulic Filter", "safety_critical": False},
]

CLASS_KEYS = [c["key"] for c in CATEGORIES]
NUM_CLASSES = len(CATEGORIES)

BY_KEY = {c["key"]: c for c in CATEGORIES}

# Search terms used by `download_images.py` to build the dataset.
SEARCH_QUERIES = {
    "oil_filter": [
        "engine oil filter car",
        "oil filter spin-on",
        "automotive oil filter part",
    ],
    "air_filter": [
        "car air filter panel",
        "engine air filter element",
        "air filter automotive",
    ],
    "fuel_filter": [
        "diesel fuel filter",
        "fuel filter car part",
        "inline fuel filter",
    ],
    "brake_pad": [
        "brake pads set",
        "disc brake pad",
        "brake pad automotive",
    ],
    "belt": [
        "serpentine belt",
        "v ribbed drive belt",
        "fan belt automotive",
    ],
    "spark_plug": [
        "spark plug ignition",
        "spark plug close up",
        "iridium spark plug",
    ],
    "clutch_plate": [
        "clutch disc plate",
        "clutch pressure plate",
        "car clutch kit",
    ],
    "hydraulic_filter": [
        "hydraulic oil filter",
        "hydraulic filter tractor",
        "heavy equipment filter",
    ],
}


def label_for(key: str) -> str:
    return BY_KEY.get(key, {}).get("label", key)


def is_safety_critical(key: str) -> bool:
    return bool(BY_KEY.get(key, {}).get("safety_critical", False))
