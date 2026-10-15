import { useEffect, useMemo, useState } from 'react';
import type { Vehicle } from '../lib/types';
import { Card } from './ui';

export interface VehicleSelection {
  vehicleId?: string;
  make?: string;
  model?: string;
  year?: number;
  engine?: string;
}

/**
 * Step 3 input. Cascading make -> model -> year, mirroring how a counter clerk
 * actually asks the question. Selecting nothing is a valid state: the API then
 * reports `needs_vehicle_info` rather than inventing a fitment.
 */
export function VehiclePicker({
  vehicles,
  value,
  onChange,
}: {
  vehicles: Vehicle[];
  value: VehicleSelection;
  onChange: (next: VehicleSelection) => void;
}) {
  const makes = useMemo(() => [...new Set(vehicles.map((v) => v.make))].sort(), [vehicles]);

  const [make, setMake] = useState('');
  const [model, setModel] = useState('');

  const models = useMemo(
    () => vehicles.filter((v) => v.make === make).map((v) => v).sort((a, b) => a.model.localeCompare(b.model)),
    [vehicles, make],
  );

  const selected = vehicles.find((v) => v.id === value.vehicleId) ?? null;

  // Keep the local dropdown state in sync if a vehicle is set from outside
  // (e.g. the user clicked a catalogue candidate, or we reset the form).
  useEffect(() => {
    if (selected) {
      setMake(selected.make);
      setModel(selected.model);
    }
  }, [selected]);

  const years = useMemo(() => {
    if (!selected) return [];
    const out: number[] = [];
    for (let y = selected.yearTo; y >= selected.yearFrom; y -= 1) out.push(y);
    return out;
  }, [selected]);

  return (
    <Card step="Step 3" title="Your vehicle">
      <div className="grid3">
        <label className="field">
          <span>Make</span>
          <select
            className="input"
            value={make}
            onChange={(e) => {
              setMake(e.target.value);
              setModel('');
              onChange({});
            }}
          >
            <option value="">Select make…</option>
            {makes.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span>Model</span>
          <select
            className="input"
            value={model}
            disabled={!make}
            onChange={(e) => {
              setModel(e.target.value);
              const v = models.find((x) => x.model === e.target.value);
              onChange(v ? { vehicleId: v.id, make: v.make, model: v.model, engine: v.engine } : {});
            }}
          >
            <option value="">Select model…</option>
            {models.map((v) => (
              <option key={v.id} value={v.model}>
                {v.model} ({v.yearFrom}–{v.yearTo}) · {v.engine}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span>Year</span>
          <select
            className="input"
            value={value.year ?? ''}
            disabled={!selected}
            onChange={(e) =>
              onChange({ ...value, year: e.target.value ? Number(e.target.value) : undefined })
            }
          >
            <option value="">Any year…</option>
            {years.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="veh-actions">
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          onClick={() => {
            setMake('');
            setModel('');
            onChange({});
          }}
        >
          Clear
        </button>
        <span className="muted small">
          {selected
            ? `Resolved: ${selected.make} ${selected.model} · ${selected.engine}`
            : 'Not supplied — fitment will be reported as unverified.'}
        </span>
      </div>
    </Card>
  );
}
