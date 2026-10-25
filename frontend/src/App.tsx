import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, ApiError } from './lib/api';
import type { AiHealth, AnalysisResponse, DescribeResponse, IdentifyResponse, Vehicle } from './lib/types';
import { DEFAULT_ORIGIN, useGeolocation, type Coords } from './lib/useGeolocation';
import { PhotoUpload } from './components/PhotoUpload';
import { IdentifyPanel } from './components/IdentifyPanel';
import { VehiclePicker, type VehicleSelection } from './components/VehiclePicker';
import { FitmentPanel } from './components/FitmentPanel';
import { PriceTable } from './components/PriceTable';
import { NearbyList } from './components/NearbyList';
import { WarningsBanner } from './components/WarningsBanner';
import { ProviderStatus } from './components/ProviderStatus';
import { DescribeInput } from './components/DescribeInput';
import { Badge, Card, Notice, Spinner } from './components/ui';

export default function App() {
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [identify, setIdentify] = useState<IdentifyResponse | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [partId, setPartId] = useState<string | null>(null);
  const [partNumber, setPartNumber] = useState<string | null>(null);
  const [vehicle, setVehicle] = useState<VehicleSelection>({});
  const [busy, setBusy] = useState<null | 'identify' | 'analyse'>(null);
  const [error, setError] = useState<string | null>(null);
  const [origin, setOriginState] = useState<Coords>(DEFAULT_ORIGIN);
  const [radiusKm, setRadiusKm] = useState(15);
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [aiHealth, setAiHealth] = useState<AiHealth | null>(null);
  const [describeResult, setDescribeResult] = useState<DescribeResponse | null>(null);

  const geo = useGeolocation();
  const resultRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api
      .vehicles()
      .then((r) => setVehicles(r.results))
      .catch(() => setApiOnline(false));
    api
      .health()
      .then(() => setApiOnline(true))
      .catch(() => setApiOnline(false));
    api
      .aiHealth()
      .then(setAiHealth)
      .catch(() => setAiHealth(null));
  }, []);

  // Keep the object URL tidy — leaking one per upload is a classic React bug.
  useEffect(() => {
    if (!file) {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  useEffect(() => setOriginState(geo.origin), [geo.origin]);

  const runAnalyse = useCallback(
    async (
      override: {
        partId?: string | null;
        partNumber?: string | null;
        prediction?: unknown;
        visiblePartNumber?: string | null;
      } = {},
    ) => {
      setBusy('analyse');
      setError(null);
      try {
        const payload: Record<string, unknown> = {
          partId: override.partId ?? partId ?? undefined,
          partNumber: override.partNumber ?? partNumber ?? undefined,
          vehicleId: vehicle.vehicleId,
          make: vehicle.make,
          model: vehicle.model,
          year: vehicle.year,
          engine: vehicle.engine,
          lat: origin.lat,
          lng: origin.lng,
          radiusKm,
          // A part number read off the physical part is the strongest evidence an
          // image can provide, so it travels with the request and outranks the
          // category guess when the API resolves the part.
          visiblePartNumber:
            override.visiblePartNumber ?? identify?.detected?.partNumber ?? undefined,
          prediction:
            override.prediction ??
            (identify
              ? { predictions: identify.predictions, modelVersion: identify.modelVersion }
              : undefined),
        };
        const res = await api.analyse(payload);
        setAnalysis(res);
        // The API does not always resolve a catalogue part from a category alone;
        // adopt whatever it decided so price/nearby stay consistent.
        if (res.stage2_fitment.part) setPartId(res.stage2_fitment.part.id);
        requestAnimationFrame(() => resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Could not reach the API.');
      } finally {
        setBusy(null);
      }
    },
    [partId, partNumber, vehicle, origin, radiusKm, identify],
  );

  const onFile = useCallback(
    async (f: File) => {
      setFile(f);
      setIdentify(null);
      setAnalysis(null);
      setDescribeResult(null);
      setPartId(null);
      setPartNumber(null);
      setBusy('identify');
      setError(null);
      try {
        const res = await api.identify(f);
        setIdentify(res);

        // If the top prediction is accepted AND exactly one catalogue part fits the
        // category, we can carry it forward automatically. Otherwise the user picks.
        const top = res.top1;
        const candidates = top?.catalogueCandidates ?? [];
        if (res.decision === 'accept_category' && candidates.length > 0) {
          await runAnalyse({ partId: candidates[0].id, prediction: { predictions: res.predictions, modelVersion: res.modelVersion } });
        }
      } catch (err) {
        setError(
          err instanceof ApiError && (err.status === 503 || err.status === 504)
            ? `${err.message} You can still use the part-number box or vehicle details.`
            : err instanceof ApiError
              ? err.message
              : 'Image analysis failed.',
        );
      } finally {
        setBusy(null);
      }
    },
    [runAnalyse],
  );

  const onPartNumber = useCallback(
    async (value: string) => {
      setPartNumber(value);
      setIdentify(null);
      setDescribeResult(null);
      setFile(null);
      setBusy('analyse');
      setError(null);
      try {
        const lookup = await api.lookupPartNumber(value);
        setPartId(lookup.part.id);
        await runAnalyse({ partId: lookup.part.id, partNumber: value });
      } catch (err) {
        setPartId(null);
        if (err instanceof ApiError && err.status === 400) {
          // A descriptive name is not an exact identifier. Keep the user on the
          // photo/description path instead of running a misleading fitment check.
          setPartNumber(null);
          setAnalysis(null);
          setError(err.message);
          return;
        }
        await runAnalyse({ partId: null, partNumber: value });
        if (err instanceof ApiError && err.status === 404) {
          setError(`"${value}" was not found in the catalogue. Fitment below reports it as an unknown part number.`);
        }
      } finally {
        setBusy(null);
      }
    },
    [runAnalyse],
  );

  /** Text description -> category, then run the same fitment/price/nearby pipeline. */
  const onDescribed = useCallback(
    async (result: DescribeResponse) => {
      setIdentify(null);
      setFile(null);
      setPartNumber(null);
      const matchedId = result.detected?.catalogueMatch?.id ?? null;
      setPartId(matchedId);
      setDescribeResult(result);
      await runAnalyse({
        partId: matchedId,
        partNumber: result.detected?.partNumber ?? null,
        prediction: { predictions: result.predictions, modelVersion: result.modelVersion },
        visiblePartNumber: result.detected?.partNumber ?? null,
      });
    },
    [runAnalyse],
  );

  const onSelectCandidate = useCallback(
    (id: string) => {
      setPartId(id);
      void runAnalyse({ partId: id });
    },
    [runAnalyse],
  );

  const showResults = Boolean(analysis);

  const stageStatus = useMemo(
    () => ({
      upload: Boolean(file || partNumber),
      identify: Boolean(identify),
      fitment: Boolean(analysis),
    }),
    [file, partNumber, identify, analysis],
  );

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar__inner">
          <div className="brand">
            <span className="brand__mark" aria-hidden="true">
              ⚙️
            </span>
            <div>
              <h1>AutoParts AI</h1>
              <p className="muted small">
                From a photo to the right part, a fair price, and a nearby seller
              </p>
            </div>
          </div>
          <div className="topbar__right">
            {apiOnline === false && <Badge tone="bad">API offline</Badge>}
            {apiOnline === true && <Badge tone="good">API online</Badge>}
          </div>
        </div>
        <div className="topbar__policy">
          <strong>AI suggests; catalogue and seller data verify.</strong> Fitment is asserted only from a
          part-number match or a vehicle-catalogue match — never from image similarity.
        </div>
      </header>

      <main className="layout">
        <div className="col-left">
          <ProviderStatus health={aiHealth} />

          <Card step="Step 1" title="Identify the part">
            <PhotoUpload onFile={onFile} busy={busy === 'identify'} previewUrl={previewUrl} onUsePartNumber={onPartNumber} />
            <DescribeInput onResult={onDescribed} disabled={busy === 'identify'} />
          </Card>

          {busy === 'identify' && <Spinner label="Running the vision model…" />}

          {error && (
            <Notice tone="bad" title="Something needs your attention">
              {error}
            </Notice>
          )}

          {identify && (
            <IdentifyPanel identify={identify} onSelectCandidate={onSelectCandidate} selectedPartId={partId} />
          )}

          {describeResult && (
            <Card
              step="Step 2"
              title="What the description suggests"
              right={<Badge tone="warn">weaker than a photo</Badge>}
            >
              <p className="muted small">{describeResult.caveat}</p>
              {describeResult.reasoning && (
                <p className="muted small">
                  <strong>Model reasoning:</strong> {describeResult.reasoning}
                </p>
              )}
              <p>{describeResult.message}</p>
              {describeResult.top1 && (
                <div className="prediction prediction--top">
                  <div className="prediction__head">
                    <strong>{describeResult.top1.label}</strong>
                    <span className="muted small">{Math.round(describeResult.top1.confidence * 100)}%</span>
                  </div>
                  <div className="bar" aria-hidden="true">
                    <span className="bar__fill" style={{ width: `${Math.max(2, describeResult.top1.confidence * 100)}%` }} />
                  </div>
                  {describeResult.top1.catalogueCandidates.length > 0 && (
                    <div className="candidates">
                      <span className="muted small">Catalogue parts in this category:</span>
                      <div className="chips">
                        {describeResult.top1.catalogueCandidates.map((c) => (
                          <button
                            key={c.id}
                            type="button"
                            className={`chip chip--button ${partId === c.id ? 'chip--selected' : ''}`}
                            onClick={() => onSelectCandidate(c.id)}
                          >
                            {c.name} · {c.brand} · {c.partNumber}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </Card>
          )}

          <VehiclePicker vehicles={vehicles} value={vehicle} onChange={(v) => { setVehicle(v); }} />

          <Card title="Search radius">
            <label className="field">
              <span>
                Within <strong>{radiusKm} km</strong> of {origin.label}
              </span>
              <input
                className="range"
                type="range"
                min={2}
                max={40}
                step={1}
                value={radiusKm}
                onChange={(e) => setRadiusKm(Number(e.target.value))}
              />
            </label>
            <div className="veh-actions">
              <button type="button" className="btn btn--ghost btn--sm" onClick={geo.locate} disabled={geo.status === 'locating'}>
                {geo.status === 'locating' ? 'Locating…' : 'Use my location'}
              </button>
              {geo.status === 'denied' && <span className="muted small">Location permission denied — using the default.</span>}
              <button
                type="button"
                className="btn btn--primary btn--sm"
                onClick={() => void runAnalyse()}
                disabled={busy === 'analyse' || (!partId && !partNumber && !identify)}
              >
                {busy === 'analyse' ? 'Checking…' : 'Re-run check'}
              </button>
            </div>
          </Card>

          <Card title="How this works">
            <ol className="steps">
              <li>
                <strong>Upload</strong> — take or upload a photo of the part.
              </li>
              <li>
                <strong>Identify</strong> — the model predicts a category and a confidence.
              </li>
              <li>
                <strong>Verify fit</strong> — enter vehicle details or the stamped part number.
              </li>
              <li>
                <strong>Compare</strong> — see catalogue and seller prices with timestamps.
              </li>
              <li>
                <strong>Locate</strong> — find nearby shops with verified stock.
              </li>
            </ol>
          </Card>
        </div>

        <div className="col-right" ref={resultRef}>
          {!showResults && (
            <Card title="Results">
              <p className="empty">
                Start by uploading a photo or entering a part number. Nothing is shown until there is real
                catalogue evidence behind it.
              </p>
              {stageStatus.upload && !analysis && <Spinner label="Gathering catalogue evidence…" />}
            </Card>
          )}

          {analysis && (
            <>
              <WarningsBanner warnings={analysis.warnings} />
              <FitmentPanel data={analysis} />
              <PriceTable price={analysis.stage3_price} />
              <NearbyList nearby={analysis.stage4_nearby} />
              <Card title="Audit trail">
                <p className="muted small">{analysis.policy}</p>
                <dl className="kv">
                  <div>
                    <dt>Generated</dt>
                    <dd>{new Date(analysis.generatedAt).toLocaleString()}</dd>
                  </div>
                  <div>
                    <dt>Identification source</dt>
                    <dd>{analysis.stage1_identify.source.replace(/_/g, ' ')}</dd>
                  </div>
                  <div>
                    <dt>Model</dt>
                    <dd>{analysis.stage1_identify.modelVersion ?? 'not used'}</dd>
                  </div>
                  <div>
                    <dt>Shape constraints</dt>
                    <dd>
                      Within {analysis.stage4_nearby.radiusKm} km of {analysis.stage4_nearby.origin
                        ? `${analysis.stage4_nearby.origin.lat}, ${analysis.stage4_nearby.origin.lng}`
                        : 'an unspecified origin'}
                    </dd>
                  </div>
                </dl>
              </Card>
            </>
          )}
        </div>
      </main>

      <footer className="footer">
        <p>
          Prototype for academic demonstration. Prices and stock are indicative catalogue data, not live
          inventory. Confirm the exact part number and price with the seller before purchase.
        </p>
      </footer>
    </div>
  );
}
