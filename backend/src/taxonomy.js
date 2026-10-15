/**
 * Single source of truth for the part taxonomy.
 *
 * The category keys MUST stay in sync with:
 *   - ai-service/app/taxonomy.py   (model class order)
 *   - data/parts.json              (catalogue documents)
 *   - frontend/src/lib/taxonomy.ts (display labels)
 *
 * Order is significant: the vision model emits class indices that map onto this list.
 */
export const CATEGORIES = [
  { key: 'oil_filter', label: 'Oil Filter', safetyCritical: false, icon: '🛢️' },
  { key: 'air_filter', label: 'Air Filter', safetyCritical: false, icon: '🌬️' },
  { key: 'fuel_filter', label: 'Fuel Filter', safetyCritical: false, icon: '⛽' },
  { key: 'brake_pad', label: 'Brake Pad', safetyCritical: true, icon: '🛑' },
  { key: 'belt', label: 'Drive Belt', safetyCritical: false, icon: '➰' },
  { key: 'spark_plug', label: 'Spark Plug', safetyCritical: false, icon: '⚡' },
  { key: 'clutch_plate', label: 'Clutch Plate', safetyCritical: true, icon: '⚙️' },
  { key: 'hydraulic_filter', label: 'Hydraulic Filter', safetyCritical: false, icon: '🚜' },
];

export const CATEGORY_KEYS = CATEGORIES.map((c) => c.key);
const BY_KEY = new Map(CATEGORIES.map((c) => [c.key, c]));

export const categoryLabel = (key) => BY_KEY.get(key)?.label ?? key;
export const isSafetyCritical = (key) => Boolean(BY_KEY.get(key)?.safetyCritical);

export const VEHICLE_CLASSES = [
  { key: 'car', label: 'Car' },
  { key: 'suv', label: 'SUV' },
  { key: 'truck', label: 'Truck / Bus' },
  { key: 'tractor', label: 'Tractor' },
  { key: 'heavy_equipment', label: 'Heavy Equipment' },
];
