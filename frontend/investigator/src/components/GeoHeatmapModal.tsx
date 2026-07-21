import { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { useAuthStore } from '../store/authStore';

// ── Leaflet types (dynamic import to avoid SSR issues) ───────────────────────
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import 'leaflet.heat';

// Fix default marker icons broken by webpack/vite
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png';
import markerIcon from 'leaflet/dist/images/marker-icon.png';
import markerShadow from 'leaflet/dist/images/marker-shadow.png';

// @ts-expect-error leaflet internal
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x,
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
});

// ── Types ────────────────────────────────────────────────────────────────────
interface GeoPoint {
  lat: number;
  lon: number;
  weight?: number;          // 0–1 heat intensity
  riskTier?: string;
  complaintType?: string;
  caseId?: string;
  isCurrentCase?: boolean;
}

interface GeoHeatmapModalProps {
  caseId: string;
  caseLat?: number | null;
  caseLon?: number | null;
  nearbyHotspots?: any[];
  onClose: () => void;
}

// ── Tier → colour map ────────────────────────────────────────────────────────
function tierColor(tier?: string): string {
  const t = (tier || '').toUpperCase();
  if (t === 'CRITICAL') return '#ef4444';
  if (t === 'HIGH')     return '#f97316';
  if (t === 'MEDIUM')   return '#fbbf24';
  return '#10b981';
}

// ── Custom circle marker SVG icon ────────────────────────────────────────────
function makeIcon(color: string, pulse = false): L.DivIcon {
  const size = pulse ? 20 : 14;
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="${size * 3}" height="${size * 3}" viewBox="0 0 ${size * 3} ${size * 3}">
      ${pulse ? `<circle cx="${size * 1.5}" cy="${size * 1.5}" r="${size * 1.4}" fill="${color}" opacity="0.2">
        <animate attributeName="r" values="${size * 0.8};${size * 1.4};${size * 0.8}" dur="2s" repeatCount="indefinite"/>
        <animate attributeName="opacity" values="0.3;0.05;0.3" dur="2s" repeatCount="indefinite"/>
      </circle>` : ''}
      <circle cx="${size * 1.5}" cy="${size * 1.5}" r="${size * 0.7}" fill="${color}" stroke="white" stroke-width="2" opacity="0.9"/>
    </svg>`;
  return L.divIcon({
    html: svg,
    className: '',
    iconSize: [size * 3, size * 3],
    iconAnchor: [size * 1.5, size * 1.5],
  });
}

// ── Component ────────────────────────────────────────────────────────────────
export default function GeoHeatmapModal({
  caseId, caseLat, caseLon, nearbyHotspots = [], onClose,
}: GeoHeatmapModalProps) {
  const { accessToken: token } = useAuthStore();
  const mapRef    = useRef<L.Map | null>(null);
  const divRef    = useRef<HTMLDivElement>(null);
  const [points,  setPoints]  = useState<GeoPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [tileLayer, setTileLayer] = useState<'street' | 'satellite'>('street');
  const tileRef   = useRef<L.TileLayer | null>(null);
  const [anomaly, setAnomaly] = useState(false);

  // ── Load data ──────────────────────────────────────────────────────────────
  useEffect(() => {
    const load = async () => {
      try {
        const res = await axios.get('/api/v1/investigator/cases', {
          params: { limit: 500 },
          headers: { Authorization: `Bearer ${token}` },
        });
        const raw = res.data?.data?.cases || res.data?.cases || res.data?.data || [];
        const pts: GeoPoint[] = [];

        for (const c of raw) {
          const lat = parseFloat(c.complaintLat ?? c.complaint_lat);
          const lon = parseFloat(c.complaintLon ?? c.complaint_lon);
          if (!isNaN(lat) && !isNaN(lon)) {
            const tier = (c.riskTier ?? c.risk_tier ?? 'MEDIUM').toUpperCase();
            const w = tier === 'CRITICAL' ? 1.0 : tier === 'HIGH' ? 0.75 : tier === 'MEDIUM' ? 0.5 : 0.25;
            pts.push({
              lat, lon, weight: w,
              riskTier: tier,
              complaintType: c.complaintType ?? c.complaint_type,
              caseId: c.caseId ?? c.case_id,
              isCurrentCase: (c.caseId ?? c.case_id) === caseId,
            });
          }
        }

        // Geo service hotspots
        for (const h of nearbyHotspots) {
          const lat = h.geometry?.coordinates?.[1] ?? h.lat;
          const lon = h.geometry?.coordinates?.[0] ?? h.lon;
          if (lat && lon) {
            pts.push({ lat, lon, weight: 0.9, riskTier: 'HIGH' });
          }
        }

        // Always include current case pin
        if (caseLat && caseLon && !pts.find(p => p.isCurrentCase)) {
          pts.push({ lat: caseLat, lon: caseLon, weight: 1, riskTier: 'CRITICAL', caseId, isCurrentCase: true });
        }

        setPoints(pts);
        setAnomaly(pts.length >= 3);
      } catch {
        if (caseLat && caseLon) {
          setPoints([{ lat: caseLat, lon: caseLon, weight: 1, riskTier: 'CRITICAL', isCurrentCase: true }]);
        }
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [caseId, caseLat, caseLon, token]); // eslint-disable-line

  // ── Init map ───────────────────────────────────────────────────────────────
  useEffect(() => {
    if (loading || !divRef.current || mapRef.current) return;

    // Centre on current case or India centre
    const initLat = caseLat ?? 20.5937;
    const initLon = caseLon ?? 78.9629;
    const zoom    = caseLat ? 8 : 5;

    const map = L.map(divRef.current, {
      center: [initLat, initLon],
      zoom,
      zoomControl: true,
    });
    mapRef.current = map;

    // Street tile
    const street = L.tileLayer(
      'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
      { attribution: '© OpenStreetMap contributors', maxZoom: 19 }
    );
    street.addTo(map);
    tileRef.current = street;

    // Heatmap layer via leaflet.heat (loaded dynamically)
    const heatPoints = points.map(p => [p.lat, p.lon, p.weight ?? 0.5] as [number, number, number]);
    if (heatPoints.length > 0) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const heat = (L as any).heatLayer(heatPoints, {
        radius: 35,
        blur: 25,
        maxZoom: 14,
        max: 1.0,
        gradient: { 0.2: '#10b981', 0.5: '#fbbf24', 0.75: '#f97316', 1.0: '#ef4444' },
      });
      heat.addTo(map);
    }

    // Individual markers
    for (const pt of points) {
      const color = tierColor(pt.riskTier);
      const icon  = makeIcon(color, !!pt.isCurrentCase);
      const label = pt.isCurrentCase
        ? `<b>📍 THIS CASE</b><br/>${pt.complaintType ?? ''}<br/>(${pt.lat.toFixed(4)}, ${pt.lon.toFixed(4)})`
        : `${pt.riskTier ?? 'UNKNOWN'} risk<br/>${pt.complaintType ?? ''}`;
      L.marker([pt.lat, pt.lon], { icon })
        .bindPopup(label, { className: 'leaflet-dark-popup' })
        .addTo(map);
    }

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [loading, points]); // eslint-disable-line

  // ── Swap tile layer ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!mapRef.current || !tileRef.current) return;
    mapRef.current.removeLayer(tileRef.current);
    const url = tileLayer === 'satellite'
      ? 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
      : 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
    const attr = tileLayer === 'satellite'
      ? 'Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics'
      : '© OpenStreetMap contributors';
    tileRef.current = L.tileLayer(url, { attribution: attr, maxZoom: 19 });
    tileRef.current.addTo(mapRef.current);
  }, [tileLayer]);

  // Popup type breakdowns
  const typeGroups = points.reduce<Record<string, number>>((a, p) => {
    if (p.complaintType) a[p.complaintType] = (a[p.complaintType] || 0) + 1;
    return a;
  }, {});

  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-md z-[60] flex items-center justify-center p-4">
      <div
        className="bg-slate-900 border border-slate-700 rounded-2xl w-full shadow-2xl flex flex-col overflow-hidden"
        style={{ maxWidth: '1100px', height: '92vh' }}
      >
        {/* ── Header ── */}
        <div className="p-4 border-b border-slate-800 flex justify-between items-center flex-shrink-0">
          <div>
            <h2 className="text-xl font-bold text-white flex items-center gap-2">
              <span className="text-2xl">🗺️</span>
              Fraud Geospatial Heatmap
            </h2>
            <p className="text-sm text-slate-400 mt-0.5">
              {points.length} incident{points.length !== 1 ? 's' : ''} mapped · OpenStreetMap · PostGIS enriched
            </p>
          </div>
          <div className="flex items-center gap-3">
            {/* Tile toggle */}
            <div className="flex bg-slate-800 rounded-lg border border-slate-700 overflow-hidden text-xs">
              {(['street', 'satellite'] as const).map(t => (
                <button
                  key={t}
                  onClick={() => setTileLayer(t)}
                  className={`px-3 py-1.5 font-medium transition-colors capitalize ${
                    tileLayer === t ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'
                  }`}
                >
                  {t === 'street' ? '🗺 Street' : '🛰 Satellite'}
                </button>
              ))}
            </div>
            <button onClick={onClose} className="text-slate-400 hover:text-white bg-slate-800 p-2 rounded-lg transition-colors">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* ── Anomaly banner ── */}
        {anomaly && (
          <div className="flex-shrink-0 mx-4 mt-3 bg-red-950/60 border border-red-700 rounded-xl px-4 py-2.5 flex items-center gap-3">
            <span className="text-xl animate-pulse">🚨</span>
            <div>
              <p className="text-red-400 font-bold text-sm">High Density Anomaly Detected</p>
              <p className="text-red-300 text-xs mt-0.5">
                {points.length} fraud incidents mapped ·
                {Object.entries(typeGroups).map(([t, c]) => ` ${t.replace(/_/g, ' ')}: ${c}`).join(' ·')}
              </p>
            </div>
          </div>
        )}

        {/* ── Map container ── */}
        <div className="flex-1 relative m-4 rounded-xl overflow-hidden border border-slate-800">
          {loading && (
            <div className="absolute inset-0 bg-slate-950 flex items-center justify-center z-10">
              <div className="flex flex-col items-center gap-3">
                <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-400" />
                <p className="text-slate-400 text-sm">Loading map data…</p>
              </div>
            </div>
          )}
          <div ref={divRef} style={{ width: '100%', height: '100%' }} />
        </div>

        {/* ── Legend ── */}
        <div className="flex-shrink-0 flex flex-wrap items-center gap-x-5 gap-y-1 px-4 pb-3 text-xs text-slate-400">
          {[
            { label: 'Critical',    color: '#ef4444' },
            { label: 'High',        color: '#f97316' },
            { label: 'Medium',      color: '#fbbf24' },
            { label: 'Low',         color: '#10b981' },
          ].map(({ label, color }) => (
            <span key={label} className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-full inline-block" style={{ background: color, opacity: 0.85 }} />
              {label}
            </span>
          ))}
          <span className="ml-auto">Click any marker for details · Scroll to zoom · Drag to pan</span>
        </div>
      </div>

      {/* Dark popup style */}
      <style>{`
        .leaflet-dark-popup .leaflet-popup-content-wrapper {
          background: #1e293b;
          color: #e2e8f0;
          border: 1px solid #475569;
          border-radius: 8px;
          font-size: 12px;
        }
        .leaflet-dark-popup .leaflet-popup-tip {
          background: #1e293b;
        }
        .leaflet-control-zoom a {
          background: #1e293b !important;
          color: #e2e8f0 !important;
          border-color: #475569 !important;
        }
        .leaflet-control-attribution {
          background: rgba(15,23,42,0.8) !important;
          color: #64748b !important;
        }
      `}</style>
    </div>
  );
}
