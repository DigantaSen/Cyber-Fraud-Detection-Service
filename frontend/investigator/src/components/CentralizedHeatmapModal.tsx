import { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import 'leaflet.heat';
import { useAuthStore } from '../store/authStore';

interface CentralizedHeatmapModalProps {
  cases: any[];
  onClose: () => void;
}

export default function CentralizedHeatmapModal({ cases, onClose }: CentralizedHeatmapModalProps) {
  const mapRef = useRef<HTMLDivElement | null>(null);
  const leafletInstance = useRef<L.Map | null>(null);
  const { accessToken: token } = useAuthStore();
  const [hotspots, setHotspots] = useState<any[]>([]);

  useEffect(() => {
    const fetchGlobalHotspots = async () => {
      try {
        const res = await axios.get('/api/v1/geo/hotspots?bbox=68.0,6.0,97.0,36.0', {
          headers: { Authorization: `Bearer ${token}` }
        });
        setHotspots(res.data?.data?.features || []);
      } catch (err) {
        console.error("Failed to fetch global hotspots", err);
      }
    };
    if (token) fetchGlobalHotspots();
  }, [token]);

  useEffect(() => {
    if (!mapRef.current) return;

    if (leafletInstance.current) {
      leafletInstance.current.remove();
      leafletInstance.current = null;
    }

    // Center map of India
    const map = L.map(mapRef.current).setView([20.5937, 78.9629], 5);
    leafletInstance.current = map;

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 18,
      attribution: '© OpenStreetMap'
    }).addTo(map);

    const heatPoints: [number, number, number][] = [];

    // 1. Add PostGIS Fraud Hotspots
    hotspots.forEach(feat => {
      const coords = feat.geometry?.coordinates;
      if (coords && coords.length >= 2) {
        const lon = coords[0];
        const lat = coords[1];
        const count = feat.properties?.incidentCount || 10;
        const tier = (feat.properties?.riskTier || 'HIGH').toUpperCase();
        
        const weight = tier === 'CRITICAL' ? 1.0 : tier === 'HIGH' ? 0.75 : 0.4;
        heatPoints.push([lat, lon, weight]);

        const markerColor = tier === 'CRITICAL' ? '#ef4444' : tier === 'HIGH' ? '#f97316' : '#eab308';
        const customIcon = L.divIcon({
          className: 'custom-hotspot-pin',
          html: `<div style="background-color: ${markerColor}; width: 18px; height: 18px; border-radius: 50%; border: 2px solid white; box-shadow: 0 0 10px ${markerColor}; display: flex; items-center; justify-center; font-size: 9px; font-weight: bold; color: white;">🔥</div>`,
          iconSize: [18, 18],
          iconAnchor: [9, 9]
        });

        const popupContent = `
          <div style="font-family: sans-serif; padding: 4px;">
            <strong style="color: #0f172a; font-size: 13px;">Fraud Cluster: ${feat.properties?.jurisdictionId}</strong><br/>
            <span style="font-size: 11px; color: #64748b;">Incidents Recorded: ${count}</span><br/>
            <span style="font-size: 11px; font-weight: bold; color: ${markerColor};">Risk Tier: ${tier}</span>
          </div>
        `;

        L.marker([lat, lon], { icon: customIcon }).bindPopup(popupContent).addTo(map);
      }
    });

    // 2. Add Case Complaint Locations
    cases.forEach(c => {
      const lat = c.complaintLat != null ? parseFloat(c.complaintLat) : null;
      const lon = c.complaintLon != null ? parseFloat(c.complaintLon) : null;
      if (lat != null && lon != null && !isNaN(lat) && !isNaN(lon)) {
        const isConfirmed = (c.status || '').toUpperCase() === 'ACTION_TAKEN' || (c.status || '').toUpperCase() === 'CONFIRMED_FRAUD';
        heatPoints.push([lat, lon, isConfirmed ? 0.9 : 0.5]);

        const markerColor = isConfirmed ? '#ef4444' : '#3b82f6';
        const customIcon = L.divIcon({
          className: 'custom-case-pin',
          html: `<div style="background-color: ${markerColor}; width: 12px; height: 12px; border-radius: 50%; border: 2px solid white; box-shadow: 0 0 6px ${markerColor};"></div>`,
          iconSize: [12, 12],
          iconAnchor: [6, 6]
        });

        const popupContent = `
          <div style="font-family: sans-serif; padding: 4px;">
            <strong style="color: #0f172a; font-size: 13px;">${c.title || 'Case Complaint'}</strong><br/>
            <span style="font-size: 11px; color: #64748b;">ID: #${(c.caseNumber || c.caseId || '').substring(0, 8)}</span><br/>
            <span style="font-size: 11px; font-weight: bold; color: ${markerColor};">Status: ${c.status || 'NEW'}</span>
          </div>
        `;

        L.marker([lat, lon], { icon: customIcon }).bindPopup(popupContent).addTo(map);
      }
    });

    // Add Heatmap layer
    if (heatPoints.length > 0) {
      (L as any).heatLayer(heatPoints, {
        radius: 32,
        blur: 20,
        maxZoom: 10,
        gradient: {
          0.3: 'blue',
          0.6: 'lime',
          0.8: 'yellow',
          1.0: 'red'
        }
      }).addTo(map);
    }

    return () => {
      if (leafletInstance.current) {
        leafletInstance.current.remove();
        leafletInstance.current = null;
      }
    };
  }, [cases, hotspots]);

  return (
    <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-md z-50 flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-5xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* Modal Header */}
        <div className="bg-slate-800 p-4 border-b border-slate-700 flex justify-between items-center">
          <div className="flex items-center gap-3">
            <span className="text-2xl">🗺️</span>
            <div>
              <h2 className="text-lg font-bold text-white">National Centralized Fraud Heatmap</h2>
              <p className="text-xs text-slate-400">Live PostGIS cluster analysis & case density map ({hotspots.length} active hotspots loaded)</p>
            </div>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white bg-slate-700 hover:bg-slate-600 rounded-lg px-3 py-1.5 text-xs font-bold transition-colors">
            Close ✕
          </button>
        </div>

        {/* Map Canvas */}
        <div className="p-4 flex-1 flex flex-col md:flex-row gap-4 relative">
          <div ref={mapRef} className="w-full h-[550px] rounded-xl overflow-hidden border border-slate-700 z-0"></div>
          
          <div className="w-full md:w-64 bg-slate-800 rounded-xl p-4 border border-slate-700 space-y-4">
            <h3 className="text-xs font-bold text-white uppercase tracking-wider border-b border-slate-700 pb-2">Geospatial Legend</h3>
            <div className="space-y-3 text-xs">
              <div className="flex items-center gap-2">
                <span className="w-4 h-4 rounded-full bg-red-500 flex items-center justify-center text-[10px]">🔥</span>
                <span className="text-slate-300 font-bold">PostGIS Cyber Hotspot ({hotspots.length})</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-full bg-blue-500"></span>
                <span className="text-slate-300">Registered Complaint</span>
              </div>
              <div className="pt-2 border-t border-slate-700">
                <div className="text-slate-400 mb-1">Heat Density Scale</div>
                <div className="w-full h-3 rounded bg-gradient-to-r from-blue-500 via-lime-400 via-yellow-400 to-red-500"></div>
                <div className="flex justify-between text-[10px] text-slate-400 mt-1">
                  <span>Low Density</span>
                  <span>High Risk Cluster</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
