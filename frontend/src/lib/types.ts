/** Shared response types — mirror the Express API contracts exactly. */

export type StockStatus = 'confirmed' | 'likely' | 'unconfirmed' | 'out_of_stock';
export type SourceType = 'supplier_feed' | 'shop_submitted' | 'authorised_catalogue' | 'manual_verified';
export type Freshness = 'fresh' | 'recent' | 'stale' | 'unknown';

export interface Vendor {
  id: string;
  name: string;
  area: string;
  city: string;
  phone: string;
  openingHours: string;
  verified: boolean;
  rating: number;
  lat: number;
  lng: number;
}

export interface Quote {
  offerId: string;
  vendor: Vendor;
  price: number;
  mrp?: number;
  discountPct: number;
  currency: string;
  condition: 'genuine' | 'aftermarket';
  genuineLabel: string;
  stockStatus: StockStatus;
  stockLabel: string;
  inStock: boolean;
  source: { type: SourceType; name: string };
  updatedAt: string;
  ageDays: number | null;
  freshness: Freshness;
  warrantyMonths: number;
  usefulness: number;
  watchFor: string[];
  valueScore?: number;
}

export interface PriceBlock {
  partId: string;
  currency: string;
  offerCount: number;
  stats: { count: number; min: number | null; max: number | null; median: number | null; spreadPct: number | null };
  cheapest: Quote | null;
  mostVerified: Quote | null;
  bestValue: Quote | null;
  genuineLowest: Quote | null;
  aftermarketLowest: Quote | null;
  quotes: Quote[];
  disclaimer: string;
  dataQuality: { level: 'none' | 'weak' | 'fair' | 'good'; confirmed?: number; stale?: number; message: string };
}

export interface NearbyResult {
  vendor: Vendor & { pincode: string; notes: string; categories: string[] };
  distanceKm: number | null;
  distanceLabel: string | null;
  ranking: Record<string, number>;
  score: number;
  availability: { claim: string; strength: string; evidence: string };
  offer: null | {
    offerId: string;
    price: number;
    currency: string;
    condition: string;
    stockStatus: StockStatus;
    sourceType: SourceType;
    sourceName: string;
    updatedAt: string;
  };
}

export interface NearbyBlock {
  origin: { lat: number; lng: number } | null;
  radiusKm: number;
  category: string | null;
  partId: string | null;
  count: number;
  results: NearbyResult[];
  caveat: string;
  originNote?: string;
}

export type Verdict =
  | 'confirmed'
  | 'compatible'
  | 'needs_part_number'
  | 'needs_vehicle_info'
  | 'unknown_part_number'
  | 'incompatible';

export interface Evidence {
  type: string;
  strength: 'strong' | 'medium' | 'none' | 'negative';
  detail: string;
  source: string;
}

export interface FitmentBlock {
  verdict: Verdict;
  verdictRank: number;
  confidence: number;
  part: null | { id: string; name: string; brand: string; partNumber: string; category: string; condition: string };
  vehicle: null | { id: string; make: string; model: string; yearFrom: number; yearTo: number; engine: string };
  category: string | null;
  categoryLabel: string | null;
  safetyCritical: boolean;
  evidence: Evidence[];
  verifications: { reason: string; message: string }[];
  summary: string;
  listedFitments: string[] | null;
  alternatives: string[] | null;
  requiresHumanCheck: boolean;
}

export interface Prediction {
  category: string;
  label: string;
  confidence: number;
  safetyCritical: boolean;
  classIndex: number;
  categoryLabel: string;
  catalogueCandidates: { id: string; name: string; brand: string; partNumber: string; condition: string }[];
}

export interface AnalysisResponse {
  input: Record<string, unknown>;
  stage1_identify: {
    source: string;
    prediction: Prediction | null;
    allPredictions: Prediction[];
    modelVersion: string | null;
    uncertainty: string;
    predictedCategoryLabel: string | null;
  };
  stage2_fitment: FitmentBlock;
  stage3_price: PriceBlock | null;
  stage4_nearby: NearbyBlock;
  warnings: { code: string; message: string; severity?: string }[];
  policy: string;
  generatedAt: string;
}

export interface DetectedInfo {
  partNumber: string | null;
  brand: string | null;
  catalogueMatch: null | {
    id: string;
    name: string;
    brand: string;
    partNumber: string;
    category: string;
    condition: string;
  };
}

export interface DescribeResponse {
  input: { description: string };
  modelVersion: string;
  backend: string | null;
  latencyMs: number | null;
  confidenceSource: string | null;
  predictions: Prediction[];
  top1: Prediction | null;
  confidenceThreshold: number;
  decision: 'accept_category' | 'ask_for_more_info';
  detected: DetectedInfo;
  reasoning: string | null;
  message: string;
  evidenceStrength: string;
  caveat: string;
  nextSteps: string[];
}

export interface AiHealth {
  reachable?: boolean;
  detail?: string;
  message?: string;
  engine: string;
  engines: {
    cloud: {
      provider: string;
      configured: boolean;
      hasKey: boolean;
      model: string | null;
      knownProviders: string[];
    };
    local: { available: boolean; testAccuracy: number | null; note: string };
    heuristic: { available: boolean; confidenceCap: number; note: string };
  };
  requiresTraining: boolean;
  requiresDataset: boolean;
  warnings: string[];
}

export interface IdentifyResponse {
  modelVersion: string;
  backend: string | null;
  latencyMs: number | null;
  confidenceSource: string | null;
  predictions: Prediction[];
  top1: Prediction | null;
  confidenceThreshold: number;
  decision: 'accept_category' | 'ask_for_more_info';
  message: string;
  detected: DetectedInfo;
  reasoning: string | null;
  warnings: { code: string; message: string; severity?: string }[];
  outOfDistribution: null | {
    distance: number;
    trainP99: number;
    level: string;
    inDistribution: boolean;
    note: string;
    caveat: string;
  };
  validity: null | {
    inDomainAccuracy: number | null;
    measuredCrossDomainAccuracy: number;
    statement: string;
  };
}

export interface Vehicle {
  id: string;
  make: string;
  model: string;
  yearFrom: number;
  yearTo: number;
  engine: string;
  vehicleClass: string;
}
