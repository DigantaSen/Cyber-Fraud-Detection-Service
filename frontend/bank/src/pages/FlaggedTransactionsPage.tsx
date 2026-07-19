import { useState } from 'react';
import { useTransactions, useBlockTransaction } from '../api/transactions';
import type { FlaggedTransaction, RiskTier, TxStatus } from '../api/transactions';

const TIER_CONFIG: Record<RiskTier, { bg: string; text: string; dot: string }> = {
  LOW:      { bg: 'bg-green-50',  text: 'text-green-800',  dot: 'bg-green-500' },
  MEDIUM:   { bg: 'bg-yellow-50', text: 'text-yellow-800', dot: 'bg-yellow-500' },
  HIGH:     { bg: 'bg-orange-50', text: 'text-orange-800', dot: 'bg-orange-500' },
  CRITICAL: { bg: 'bg-red-50',    text: 'text-red-900',    dot: 'bg-red-500' },
};

function TransactionCard({ tx, onBlock }: { tx: FlaggedTransaction; onBlock: (id: string, reason: string) => void }) {
  const [showBlockModal, setShowBlockModal] = useState(false);
  const [blockReason, setBlockReason] = useState('');
  const config = TIER_CONFIG[tx.riskTier];
  const isBlocked = tx.status === 'BLOCKED';

  return (
    <div className={`rounded-2xl border p-5 ${config.bg} ${isBlocked ? 'opacity-60' : ''}`}>
      {/* Header */}
      <div className="flex justify-between items-start mb-4">
        <div>
          <div className="flex items-center gap-2">
            <div className={`w-2.5 h-2.5 rounded-full ${config.dot}`} />
            <span className={`text-sm font-semibold ${config.text}`}>{tx.riskTier} RISK</span>
          </div>
          <p className="text-gray-400 text-xs mt-1 font-mono">{tx.transactionId.slice(0, 16)}...</p>
        </div>
        <div className="text-right">
          <p className="text-2xl font-bold text-gray-900">
            {tx.currency} {tx.amount.toLocaleString('en-IN')}
          </p>
          <p className="text-xs text-gray-500">{new Date(tx.flaggedAt).toLocaleString()}</p>
        </div>
      </div>

      {/* Account details */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <div className="bg-white/60 rounded-xl p-3">
          <p className="text-xs text-gray-400 mb-1">From</p>
          <p className="text-sm font-semibold text-gray-800">{tx.senderName}</p>
          <p className="text-xs font-mono text-gray-500">{tx.senderAccount}</p>
        </div>
        <div className="bg-white/60 rounded-xl p-3">
          <p className="text-xs text-gray-400 mb-1">To</p>
          <p className="text-sm font-semibold text-gray-800">{tx.receiverName}</p>
          <p className="text-xs font-mono text-gray-500">{tx.receiverAccount}</p>
        </div>
      </div>

      {/* Risk Score Bar */}
      <div className="mb-4">
        <div className="flex justify-between text-xs text-gray-500 mb-1">
          <span>Risk Score</span>
          <span className="font-bold">{tx.riskScore}/100</span>
        </div>
        <div className="w-full bg-white/50 rounded-full h-2">
          <div
            className={`h-2 rounded-full transition-all ${config.dot}`}
            style={{ width: `${tx.riskScore}%` }}
          />
        </div>
      </div>

      {/* Flag Reasons */}
      {tx.blockReasons.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-1">
          {tx.blockReasons.map((r, i) => (
            <span key={i} className="px-2 py-0.5 bg-white/70 rounded-full text-xs text-gray-600 border border-white">
              {r}
            </span>
          ))}
        </div>
      )}

      {/* Case link */}
      {tx.caseId && (
        <p className="text-xs text-blue-600 mb-3">🔗 Case: {tx.caseId.slice(0, 8)}...</p>
      )}

      {/* Action */}
      {!isBlocked ? (
        <button
          onClick={() => setShowBlockModal(true)}
          className="w-full py-2 bg-red-600 hover:bg-red-700 text-white text-sm font-semibold rounded-xl transition-colors"
        >
          🚫 Block Transaction
        </button>
      ) : (
        <div className="w-full py-2 bg-gray-200 text-gray-500 text-sm text-center rounded-xl font-semibold">
          ✓ Transaction Blocked
        </div>
      )}

      {/* Block Modal */}
      {showBlockModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl p-6 w-96 shadow-2xl">
            <h3 className="text-lg font-bold text-gray-900 mb-2">Confirm Block</h3>
            <p className="text-sm text-gray-500 mb-4">
              This will immediately block transaction {tx.transactionId.slice(0, 16)}...
            </p>
            <textarea
              className="w-full border border-gray-300 rounded-xl p-3 text-sm mb-4 resize-none focus:outline-none focus:ring-2 focus:ring-red-500"
              rows={3}
              placeholder="Reason for blocking (required, min 10 chars)..."
              value={blockReason}
              onChange={(e) => setBlockReason(e.target.value)}
            />
            <div className="flex gap-3">
              <button
                onClick={() => setShowBlockModal(false)}
                className="flex-1 py-2 border border-gray-300 rounded-xl text-sm text-gray-600 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  if (blockReason.trim().length >= 10) {
                    onBlock(tx.transactionId, blockReason.trim());
                    setShowBlockModal(false);
                  }
                }}
                disabled={blockReason.trim().length < 10}
                className="flex-1 py-2 bg-red-600 hover:bg-red-700 disabled:bg-gray-300 text-white rounded-xl text-sm font-semibold transition-colors"
              >
                Confirm Block
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function FlaggedTransactionsPage() {
  const [filterTier, setFilterTier] = useState<RiskTier | undefined>();
  const [filterStatus, setFilterStatus] = useState<TxStatus | undefined>();
  const { data: transactions = [], isLoading, error } = useTransactions(filterTier, filterStatus);
  const blockMutation = useBlockTransaction();

  const handleBlock = (id: string, reason: string) => {
    blockMutation.mutate({ transactionId: id, reason });
  };

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
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
          <span className="text-xs text-gray-500">Auto-refreshing every 30s</span>
        </div>
      </header>

      {/* Summary Stats */}
      <div className="grid grid-cols-4 gap-4 p-6 pb-0">
        {[
          { label: 'Total Flagged', value: transactions.length, color: 'text-gray-900' },
          { label: 'Critical', value: transactions.filter((t) => t.riskTier === 'CRITICAL').length, color: 'text-red-600' },
          { label: 'Blocked', value: transactions.filter((t) => t.status === 'BLOCKED').length, color: 'text-orange-600' },
          { label: 'Pending Review', value: transactions.filter((t) => t.status === 'FLAGGED').length, color: 'text-blue-600' },
        ].map((s) => (
          <div key={s.label} className="bg-white rounded-2xl p-4 shadow-sm border border-gray-100">
            <p className="text-xs text-gray-400 uppercase">{s.label}</p>
            <p className={`text-3xl font-bold mt-1 ${s.color}`}>{s.value}</p>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="flex gap-3 px-6 py-4">
        <select
          value={filterTier ?? ''}
          onChange={(e) => setFilterTier((e.target.value as RiskTier) || undefined)}
          className="px-3 py-2 border border-gray-200 rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">All Risk Tiers</option>
          {(['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'] as RiskTier[]).map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <select
          value={filterStatus ?? ''}
          onChange={(e) => setFilterStatus((e.target.value as TxStatus) || undefined)}
          className="px-3 py-2 border border-gray-200 rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">All Statuses</option>
          {(['FLAGGED', 'UNDER_REVIEW', 'BLOCKED', 'CLEARED'] as TxStatus[]).map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>

      {/* Transaction Cards */}
      <div className="px-6 pb-6">
        {isLoading && (
          <div className="flex justify-center py-16">
            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600" />
          </div>
        )}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-red-700 text-sm">
            Failed to load transactions. Please check your connection.
          </div>
        )}
        {!isLoading && !error && transactions.length === 0 && (
          <div className="text-center py-16 text-gray-400">
            <p className="text-5xl mb-3">✅</p>
            <p className="text-lg font-semibold">No flagged transactions</p>
            <p className="text-sm mt-1">All transactions are within normal parameters.</p>
          </div>
        )}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {transactions.map((tx) => (
            <TransactionCard key={tx.transactionId} tx={tx} onBlock={handleBlock} />
          ))}
        </div>
      </div>
    </main>
  );
}
