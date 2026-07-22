import { useState } from 'react';
import { useTransactions, useBlockTransaction, useDismissTransaction } from '../api/transactions';
import type { FlaggedTransaction, RiskTier } from '../api/transactions';
import type { AuthUser } from '../hooks/useAuth';

const TIER_CONFIG: Record<RiskTier, { bg: string; text: string; dot: string }> = {
  LOW:      { bg: 'bg-green-50',  text: 'text-green-800',  dot: 'bg-green-500' },
  MEDIUM:   { bg: 'bg-yellow-50', text: 'text-yellow-800', dot: 'bg-yellow-500' },
  HIGH:     { bg: 'bg-orange-50', text: 'text-orange-800', dot: 'bg-orange-500' },
  CRITICAL: { bg: 'bg-red-50',    text: 'text-red-900',    dot: 'bg-red-500' },
};

function TransactionCard({
  tx, onBlock, onDismiss,
}: {
  tx: FlaggedTransaction;
  onBlock: (id: string, reason: string) => void;
  onDismiss: (id: string, note: string) => void;
}) {
  const [showBlockModal, setShowBlockModal] = useState(false);
  const [showDismissModal, setShowDismissModal] = useState(false);
  const [blockReason, setBlockReason] = useState('');
  const [dismissNote, setDismissNote] = useState('');
  const cfg = TIER_CONFIG[tx.riskTier];

  return (
    <div className={`rounded-2xl border p-5 ${cfg.bg}`}>
      {/* Header */}
      <div className="flex justify-between items-start mb-4">
        <div>
          <div className="flex items-center gap-2">
            <div className={`w-2.5 h-2.5 rounded-full ${cfg.dot}`} />
            <span className={`text-sm font-semibold ${cfg.text}`}>{tx.riskTier} RISK</span>
          </div>
          <p className="text-gray-400 text-xs mt-1 font-mono">{tx.transactionId.slice(0, 22)}...</p>
        </div>
        <div className="text-right">
          <p className="text-2xl font-bold text-gray-900">{tx.currency} {tx.amount.toLocaleString('en-IN')}</p>
          <p className="text-xs text-gray-500">{new Date(tx.flaggedAt).toLocaleString()}</p>
        </div>
      </div>

      {/* Accounts */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <div className="bg-white/60 rounded-xl p-3">
          <p className="text-xs text-gray-400 mb-1">Victim</p>
          <p className="text-sm font-semibold text-gray-800 truncate">{tx.senderName}</p>
          <p className="text-xs font-mono text-gray-500">{tx.senderAccount}</p>
        </div>
        <div className="bg-white/60 rounded-xl p-3">
          <p className="text-xs text-gray-400 mb-1">Suspect UPI / Account</p>
          <p className="text-sm font-semibold text-red-700 truncate">{tx.receiverAccount}</p>
        </div>
      </div>

      {/* Risk bar */}
      <div className="mb-4">
        <div className="flex justify-between text-xs text-gray-500 mb-1">
          <span>Risk Score</span>
          <span className="font-bold">{tx.riskScore.toFixed(1)}/100</span>
        </div>
        <div className="w-full bg-white/50 rounded-full h-2">
          <div className={`h-2 rounded-full transition-all ${cfg.dot}`} style={{ width: `${Math.min(tx.riskScore,100)}%` }} />
        </div>
      </div>

      {/* Reasons */}
      {tx.blockReasons.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-1">
          {tx.blockReasons.map((r, i) => (
            <span key={i} className="px-2 py-0.5 bg-white/70 rounded-full text-xs text-gray-600 border border-white">{r}</span>
          ))}
        </div>
      )}

      {/* Case link */}
      {tx.caseId && <p className="text-xs text-blue-600 mb-3">🔗 Case: {tx.caseId.slice(0, 8)}...</p>}

      {/* Blocked info */}
      {tx.status === 'BLOCKED' && (
        <div className="bg-red-100 border border-red-300 rounded-xl p-3 text-sm">
          <p className="font-semibold text-red-800">🚫 Blocked by {tx.blockedBy}</p>
          <p className="text-red-600 text-xs mt-1">{tx.blockedAt ? new Date(tx.blockedAt).toLocaleString() : ''}</p>
          {tx.blockReason && <p className="text-red-700 text-xs mt-1 italic">"{tx.blockReason}"</p>}
        </div>
      )}

      {/* Dismissed info */}
      {tx.status === 'CLEARED' && (
        <div className="bg-gray-100 border border-gray-300 rounded-xl p-3 text-sm">
          <p className="font-semibold text-gray-600">👁 No Action by {tx.dismissedBy}</p>
          <p className="text-gray-500 text-xs mt-1">{tx.dismissedAt ? new Date(tx.dismissedAt).toLocaleString() : ''}</p>
          {tx.dismissNote && <p className="text-gray-500 text-xs mt-1 italic">"{tx.dismissNote}"</p>}
        </div>
      )}

      {/* Actions — only on pending */}
      {tx.status === 'FLAGGED' && (
        <div className="flex gap-2 mt-3">
          <button
            id={`dismiss-btn-${tx.transactionId.slice(-6)}`}
            onClick={() => setShowDismissModal(true)}
            className="flex-1 py-2 border border-gray-300 hover:bg-gray-100 text-gray-600 text-sm font-semibold rounded-xl transition-colors"
          >
            👁 No Action
          </button>
          <button
            id={`block-btn-${tx.transactionId.slice(-6)}`}
            onClick={() => setShowBlockModal(true)}
            className="flex-1 py-2 bg-red-600 hover:bg-red-700 text-white text-sm font-semibold rounded-xl transition-colors"
          >
            🚫 Block
          </button>
        </div>
      )}

      {/* Block Modal */}
      {showBlockModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl p-6 w-96 shadow-2xl">
            <h3 className="text-lg font-bold text-gray-900 mb-2">Confirm Block Transaction</h3>
            <p className="text-sm text-gray-500 mb-1">Transaction: <span className="font-mono text-xs">{tx.transactionId.slice(0,22)}...</span></p>
            <p className="text-sm text-gray-500 mb-4">Suspect: <span className="font-semibold text-red-600">{tx.receiverAccount}</span></p>
            <textarea
              className="w-full border border-gray-300 rounded-xl p-3 text-sm mb-4 resize-none focus:outline-none focus:ring-2 focus:ring-red-500"
              rows={3}
              placeholder="Reason for blocking (min 10 chars)..."
              value={blockReason}
              onChange={(e) => setBlockReason(e.target.value)}
            />
            <p className="text-xs text-blue-600 mb-4">ℹ️ The citizen and investigator will be notified automatically.</p>
            <div className="flex gap-3">
              <button onClick={() => setShowBlockModal(false)} className="flex-1 py-2 border border-gray-300 rounded-xl text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
              <button
                onClick={() => { if (blockReason.trim().length >= 10) { onBlock(tx.transactionId, blockReason.trim()); setShowBlockModal(false); }}}
                disabled={blockReason.trim().length < 10}
                className="flex-1 py-2 bg-red-600 hover:bg-red-700 disabled:bg-gray-300 text-white rounded-xl text-sm font-semibold transition-colors"
              >Confirm Block</button>
            </div>
          </div>
        </div>
      )}

      {/* Dismiss Modal */}
      {showDismissModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl p-6 w-96 shadow-2xl">
            <h3 className="text-lg font-bold text-gray-900 mb-2">No Action — Dismiss</h3>
            <p className="text-sm text-gray-500 mb-4">This transaction will be moved to the Dismissed tab. No notification will be sent.</p>
            <textarea
              className="w-full border border-gray-300 rounded-xl p-3 text-sm mb-4 resize-none focus:outline-none focus:ring-2 focus:ring-gray-400"
              rows={2}
              placeholder="Optional note (e.g. 'Insufficient evidence', 'Already resolved')..."
              value={dismissNote}
              onChange={(e) => setDismissNote(e.target.value)}
            />
            <div className="flex gap-3">
              <button onClick={() => setShowDismissModal(false)} className="flex-1 py-2 border border-gray-300 rounded-xl text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
              <button
                onClick={() => { onDismiss(tx.transactionId, dismissNote.trim() || 'No action taken by bank'); setShowDismissModal(false); }}
                className="flex-1 py-2 bg-gray-600 hover:bg-gray-700 text-white rounded-xl text-sm font-semibold transition-colors"
              >Confirm No Action</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

type Tab = 'pending' | 'blocked' | 'dismissed';

interface Props { token: string; user: AuthUser | null; onLogout: () => void; }

export default function FlaggedTransactionsPage({ token, user, onLogout }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>('pending');
  const [filterTier, setFilterTier] = useState<RiskTier | undefined>();
  const { data: transactions = [], isLoading, error } = useTransactions(token, filterTier);
  const blockMutation   = useBlockTransaction(token);
  const dismissMutation = useDismissTransaction(token);

  const pending   = transactions.filter((t) => t.status === 'FLAGGED');
  const blocked   = transactions.filter((t) => t.status === 'BLOCKED');
  const dismissed = transactions.filter((t) => t.status === 'CLEARED');

  const handleBlock   = (id: string, reason: string) => blockMutation.mutate({ transactionId: id, reason });
  const handleDismiss = (id: string, note: string)   => dismissMutation.mutate({ transactionId: id, note });

  const tabList: { key: Tab; label: string; count: number; color: string }[] = [
    { key: 'pending',   label: '⚠️ Pending Review', count: pending.length,   color: 'text-orange-600' },
    { key: 'blocked',   label: '🚫 Blocked',         count: blocked.length,   color: 'text-red-600'    },
    { key: 'dismissed', label: '👁 Dismissed',        count: dismissed.length, color: 'text-gray-500'   },
  ];

  const shown = activeTab === 'pending' ? pending : activeTab === 'blocked' ? blocked : dismissed;
  const filteredShown = filterTier ? shown.filter((t) => t.riskTier === filterTier) : shown;
  const sortedShown = [...filteredShown].sort((a, b) => new Date(b.flaggedAt).getTime() - new Date(a.flaggedAt).getTime());

  return (
    <main className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between sticky top-0 z-10 shadow-sm">
        <div className="flex items-center gap-3">
          <span className="text-2xl">🏦</span>
          <div>
            <h1 className="text-xl font-bold text-gray-900">Bank Fraud Monitor</h1>
            <p className="text-xs text-gray-400">Cyber Fraud Detection — Bank Officer View</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
            <span className="text-xs text-gray-500">Auto-refreshing every 30s</span>
          </div>
          {user && (
            <div className="flex items-center gap-3 border-l border-gray-200 pl-4">
              <div className="text-right">
                <p className="text-xs font-semibold text-gray-800">{user.email}</p>
                <p className="text-xs text-blue-600">{user.role}</p>
              </div>
              <button id="bank-logout-btn" onClick={onLogout} className="px-3 py-1.5 rounded-lg bg-gray-100 hover:bg-gray-200 text-xs text-gray-600 border border-gray-200 transition-colors">Sign Out</button>
            </div>
          )}
        </div>
      </header>

      {/* Summary Stats */}
      <div className="grid grid-cols-4 gap-4 p-6 pb-0">
        {[
          { label: 'Total Flagged',   value: transactions.length, color: 'text-gray-900' },
          { label: 'Pending Review',  value: pending.length,      color: 'text-orange-600' },
          { label: 'Blocked',         value: blocked.length,      color: 'text-red-600' },
          { label: 'Dismissed',       value: dismissed.length,    color: 'text-gray-500' },
        ].map((s) => (
          <div key={s.label} className="bg-white rounded-2xl p-4 shadow-sm border border-gray-100">
            <p className="text-xs text-gray-400 uppercase">{s.label}</p>
            <p className={`text-3xl font-bold mt-1 ${s.color}`}>{s.value}</p>
          </div>
        ))}
      </div>

      {/* Tabs + Filter */}
      <div className="flex items-center justify-between px-6 pt-5 pb-0">
        <div className="flex gap-1 bg-gray-100 rounded-xl p-1">
          {tabList.map((t) => (
            <button
              key={t.key}
              id={`tab-${t.key}`}
              onClick={() => setActiveTab(t.key)}
              className={`px-4 py-2 rounded-lg text-sm font-semibold transition-all ${
                activeTab === t.key
                  ? 'bg-white shadow text-gray-900'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {t.label}
              <span className={`ml-2 text-xs font-bold ${activeTab === t.key ? t.color : 'text-gray-400'}`}>
                {t.count}
              </span>
            </button>
          ))}
        </div>
        <select
          value={filterTier ?? ''}
          onChange={(e) => setFilterTier((e.target.value as RiskTier) || undefined)}
          className="px-3 py-2 border border-gray-200 rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">All Risk Tiers</option>
          {(['LOW','MEDIUM','HIGH','CRITICAL'] as RiskTier[]).map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </div>

      {/* Cards */}
      <div className="px-6 pb-6 pt-4">
        {isLoading && <div className="flex justify-center py-16"><div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600" /></div>}
        {error && <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-red-700 text-sm">Failed to load transactions.</div>}
        {!isLoading && !error && filteredShown.length === 0 && (
          <div className="text-center py-16 text-gray-400">
            <p className="text-5xl mb-3">{activeTab === 'pending' ? '✅' : activeTab === 'blocked' ? '🚫' : '👁'}</p>
            <p className="text-lg font-semibold">
              {activeTab === 'pending' ? 'No transactions pending review' : activeTab === 'blocked' ? 'No blocked transactions' : 'No dismissed transactions'}
            </p>
          </div>
        )}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {sortedShown.map((tx) => (
            <TransactionCard key={tx.transactionId} tx={tx} onBlock={handleBlock} onDismiss={handleDismiss} />
          ))}
        </div>
      </div>
    </main>
  );
}
