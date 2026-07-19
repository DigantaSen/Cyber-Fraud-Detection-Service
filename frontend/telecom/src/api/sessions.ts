import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

const BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8080';

// ── REST: Fetch paginated session list ────────────────────────────────────────

export interface CallSession {
  sessionId: string;
  callerNumber: string;
  calleeNumber: string;
  duration: number;         // seconds
  riskScore: number;        // 0–100
  riskTier: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  flaggedAt: string;        // ISO timestamp
  status: 'ACTIVE' | 'ENDED' | 'BLOCKED';
  flagReasons: string[];
}

export const useSessions = (token: string | null) =>
  useQuery<CallSession[]>({
    queryKey: ['telecom-sessions'],
    queryFn: async () => {
      if (!token) return [];
      const res = await fetch(`${BASE}/api/v1/telecom/sessions`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      return data.data?.items ?? [];
    },
    enabled: !!token,
    refetchInterval: 15_000,   // Poll every 15s as fallback when SSE reconnects
  });


// ── SSE: Real-time alert stream ───────────────────────────────────────────────

export interface SSEAlert {
  type: 'SESSION_FLAGGED' | 'SESSION_BLOCKED' | 'RISK_UPDATED';
  sessionId: string;
  riskTier: string;
  message: string;
  timestamp: string;
}

export function useSessionAlerts(token: string | null) {
  const [alerts, setAlerts] = useState<SSEAlert[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!token) return;

    // EventSource doesn't support custom headers — use query param for token
    const url = `${BASE}/api/v1/telecom/sessions/stream?token=${token}`;
    const es = new EventSource(url);

    es.onopen = () => setConnected(true);

    es.onmessage = (e) => {
      try {
        const alert: SSEAlert = JSON.parse(e.data);
        setAlerts((prev) => [alert, ...prev].slice(0, 50));  // Keep last 50
      } catch { /* ignore malformed events */ }
    };

    es.onerror = () => {
      setConnected(false);
      // EventSource auto-reconnects — no manual retry needed
    };

    return () => {
      es.close();
      setConnected(false);
    };
  }, [token]);

  return { alerts, connected };
}
