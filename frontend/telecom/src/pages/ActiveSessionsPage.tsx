import { useSessions, useSessionAlerts } from '../api/sessions';
import type { CallSession } from '../api/sessions';
import type { AuthUser } from '../hooks/useAuth';

const TIER_COLORS: Record<string, string> = {
  LOW: 'bg-green-100 text-green-800',
  MEDIUM: 'bg-yellow-100 text-yellow-800',
  HIGH: 'bg-orange-100 text-orange-800',
  CRITICAL: 'bg-red-100 text-red-900',
};

function SessionRow({ session }: { session: CallSession }) {
  const tierClass = TIER_COLORS[session.riskTier] ?? TIER_COLORS.LOW;
  const isBlocked = session.status === 'BLOCKED';

  return (
    <tr className={`border-b border-gray-800 hover:bg-gray-800 transition-colors ${isBlocked ? 'opacity-50' : ''}`}>
      <td className="px-4 py-3 font-mono text-xs text-gray-400">{session.callerNumber}</td>
      <td className="px-4 py-3 font-mono text-xs text-gray-400">{session.calleeNumber}</td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="w-full bg-gray-700 rounded-full h-1.5 min-w-[5rem]">
            <div
              className="h-1.5 rounded-full"
              style={{
                width: `${session.riskScore}%`,
                backgroundColor: session.riskScore > 80 ? '#ef4444' : session.riskScore > 50 ? '#f97316' : '#22c55e',
              }}
            />
          </div>
          <span className="text-sm font-semibold">{session.riskScore}</span>
        </div>
      </td>
      <td className="px-4 py-3">
        <span className={`px-2 py-1 rounded-full text-xs font-semibold ${tierClass}`}>
          {session.riskTier}
        </span>
      </td>
      <td className="px-4 py-3 text-xs text-gray-400">
        {session.flagReasons.join(', ') || '—'}
      </td>
      <td className="px-4 py-3">
        {isBlocked ? (
          <span className="text-xs text-red-500 font-semibold">🚫 BLOCKED</span>
        ) : (
          <span className="text-xs text-green-500">● ACTIVE</span>
        )}
      </td>
      <td className="px-4 py-3 text-xs text-gray-500">
        {new Date(session.flaggedAt).toLocaleTimeString()}
      </td>
    </tr>
  );
}

interface Props {
  token: string;
  user: AuthUser | null;
  onLogout: () => void;
}

export default function ActiveSessionsPage({ token, user, onLogout }: Props) {
  const { data: sessions = [], isLoading, error } = useSessions(token);
  const { alerts, connected } = useSessionAlerts(token);

  return (
    <main className="min-h-screen bg-gray-950 text-white">
      {/* Header */}
      <header className="bg-gray-900 border-b border-gray-800 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-2xl">📡</span>
          <div>
            <h1 className="text-xl font-bold text-white">Telecom Monitoring</h1>
            <p className="text-gray-400 text-xs">Cyber Fraud Detection — Telecom Operator View</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${connected ? 'bg-green-400 animate-pulse' : 'bg-red-400'}`} />
            <span className="text-xs text-gray-400">{connected ? 'Live' : 'Reconnecting...'}</span>
          </div>
          {user && (
            <div className="flex items-center gap-3 border-l border-gray-700 pl-4">
              <div className="text-right">
                <p className="text-xs font-semibold text-white">{user.email}</p>
                <p className="text-xs text-blue-400">{user.role}</p>
              </div>
              <button
                id="telecom-logout-btn"
                onClick={onLogout}
                className="px-3 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 text-xs text-gray-300 hover:text-white border border-gray-700 transition-colors"
              >
                Sign Out
              </button>
            </div>
          )}
        </div>
      </header>

      {/* Live Alerts Ticker */}
      {alerts.length > 0 && (
        <div className="bg-red-900/40 border-b border-red-800 px-6 py-2 flex gap-4 overflow-hidden">
          <span className="text-red-400 text-xs font-bold uppercase shrink-0">⚠ Live Alerts</span>
          <div className="flex gap-6 overflow-x-auto scrollbar-hide">
            {alerts.slice(0, 5).map((a, i) => (
              <span key={i} className="text-red-300 text-xs whitespace-nowrap">
                {a.type.replace(/_/g, ' ')} — {a.message} ({new Date(a.timestamp).toLocaleTimeString()})
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Stats Bar */}
      <div className="grid grid-cols-4 gap-px bg-gray-800 border-b border-gray-800">
        {[
          { label: 'Active Sessions', value: sessions.filter((s) => s.status === 'ACTIVE').length, color: 'text-blue-400' },
          { label: 'High Risk', value: sessions.filter((s) => ['HIGH', 'CRITICAL'].includes(s.riskTier)).length, color: 'text-orange-400' },
          { label: 'Blocked', value: sessions.filter((s) => s.status === 'BLOCKED').length, color: 'text-red-400' },
          { label: 'Alerts (live)', value: alerts.length, color: 'text-yellow-400' },
        ].map((stat) => (
          <div key={stat.label} className="bg-gray-900 px-6 py-4">
            <p className="text-xs text-gray-400 uppercase">{stat.label}</p>
            <p className={`text-3xl font-bold mt-1 ${stat.color}`}>{stat.value}</p>
          </div>
        ))}
      </div>

      {/* Sessions Table */}
      <div className="p-6">
        <h2 className="text-sm text-gray-400 uppercase font-semibold mb-4">Flagged Call Sessions</h2>
        {isLoading && (
          <div className="flex items-center justify-center py-16">
            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-400" />
          </div>
        )}
        {error && (
          <div className="bg-red-900/30 border border-red-700 rounded-xl p-4 text-red-300 text-sm">
            Unable to load sessions. Check network or authentication.
          </div>
        )}
        {!isLoading && !error && (
          <div className="bg-gray-900 rounded-xl overflow-hidden border border-gray-800">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-gray-400 text-xs uppercase bg-gray-800/50">
                  <th className="px-4 py-3 text-left font-semibold">Caller</th>
                  <th className="px-4 py-3 text-left font-semibold">Callee</th>
                  <th className="px-4 py-3 text-left font-semibold">Risk Score</th>
                  <th className="px-4 py-3 text-left font-semibold">Tier</th>
                  <th className="px-4 py-3 text-left font-semibold">Flag Reasons</th>
                  <th className="px-4 py-3 text-left font-semibold">Status</th>
                  <th className="px-4 py-3 text-left font-semibold">Flagged At</th>
                </tr>
              </thead>
              <tbody>
                {sessions.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="text-center py-10 text-gray-500">
                      No flagged sessions at this time
                    </td>
                  </tr>
                ) : (
                  sessions.map((s) => <SessionRow key={s.sessionId} session={s} />)
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Alert Log Panel */}
      {alerts.length > 0 && (
        <div className="px-6 pb-6">
          <h2 className="text-sm text-gray-400 uppercase font-semibold mb-3">Recent Alerts</h2>
          <div className="bg-gray-900 rounded-xl border border-gray-800 divide-y divide-gray-800 max-h-60 overflow-y-auto">
            {alerts.map((a, i) => (
              <div key={i} className="px-4 py-3 flex items-start gap-3">
                <span className={`w-2 h-2 rounded-full mt-1 shrink-0 ${a.type === 'SESSION_BLOCKED' ? 'bg-red-400' : 'bg-yellow-400'}`} />
                <div>
                  <p className="text-xs text-white">{a.message}</p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {a.type} • Session {a.sessionId.slice(0, 8)}... • {new Date(a.timestamp).toLocaleTimeString()}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </main>
  );
}
