import { useCallback, useState } from 'react';

export interface Coords {
  lat: number;
  lng: number;
  label: string;
}

/** Bengaluru city centre — the catalogue's vendor set is there, so it is the sane default. */
export const DEFAULT_ORIGIN: Coords = { lat: 12.9716, lng: 77.5946, label: 'Bengaluru city centre (default)' };

export function useGeolocation() {
  const [origin, setOrigin] = useState<Coords>(DEFAULT_ORIGIN);
  const [status, setStatus] = useState<'idle' | 'locating' | 'denied' | 'unsupported'>('idle');

  const locate = useCallback(() => {
    if (!('geolocation' in navigator)) {
      setStatus('unsupported');
      return;
    }
    setStatus('locating');
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setOrigin({
          lat: Number(pos.coords.latitude.toFixed(5)),
          lng: Number(pos.coords.longitude.toFixed(5)),
          label: 'Your current location',
        });
        setStatus('idle');
      },
      () => setStatus('denied'),
      { timeout: 8000, maximumAge: 600_000 },
    );
  }, []);

  return { origin, setOrigin, status, locate };
}
