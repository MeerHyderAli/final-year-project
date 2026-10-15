import { useCallback, useRef, useState } from 'react';
import { Notice } from './ui';

export interface PhotoUploadProps {
  onFile: (file: File) => void;
  busy: boolean;
  previewUrl: string | null;
  onUsePartNumber: (value: string) => void;
}

/**
 * Step 1. Two entry paths are offered side by side on purpose: the image path is
 * best-effort, while the part-number path is exact. The project's design rule is
 * "AI suggests; catalogue verifies", and the UI should make the exact route as
 * easy to reach as the photographic one.
 */
export function PhotoUpload({ onFile, busy, previewUrl, onUsePartNumber }: PhotoUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [partNumber, setPartNumber] = useState('');

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files?.[0];
      if (file && file.type.startsWith('image/')) onFile(file);
    },
    [onFile],
  );

  return (
    <div className="upload">
      <div
        className={`dropzone ${dragging ? 'dropzone--active' : ''}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click();
        }}
        role="button"
        tabIndex={0}
        aria-label="Upload a photo of the spare part"
      >
        {previewUrl ? (
          <img className="dropzone__preview" src={previewUrl} alt="Selected spare part" />
        ) : (
          <div className="dropzone__hint">
            <span className="dropzone__icon" aria-hidden="true">
              📷
            </span>
            <strong>Take or upload a photo of the part</strong>
            <span className="muted">Drop a file here, or click to browse · JPEG / PNG / WebP up to 8 MB</span>
          </div>
        )}
        {busy && <div className="dropzone__busy">Analysing image…</div>}
      </div>

      <input
        ref={inputRef}
        className="visually-hidden"
        type="file"
        accept="image/*"
        capture="environment"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onFile(file);
          e.target.value = '';
        }}
      />

      <div className="or-divider">
        <span>or identify it exactly</span>
      </div>

      <form
        className="partnum"
        onSubmit={(e) => {
          e.preventDefault();
          if (partNumber.trim()) onUsePartNumber(partNumber.trim());
        }}
      >
        <input
          className="input"
          placeholder="Stamped part number, e.g. 16510-61A31"
          value={partNumber}
          onChange={(e) => setPartNumber(e.target.value)}
          aria-label="Part number"
        />
        <button className="btn btn--ghost" type="submit" disabled={!partNumber.trim()}>
          Look up
        </button>
      </form>

      <Notice tone="info">
        A photo gives you a <strong>category suggestion only</strong>. A part number or full vehicle details
        are what actually confirm the part fits.
      </Notice>
    </div>
  );
}
