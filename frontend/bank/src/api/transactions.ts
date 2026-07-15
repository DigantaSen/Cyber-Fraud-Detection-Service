import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

const BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8080';
const TOKEN = import.meta.env.VITE_BANK_TOKEN || '';

const headers = () => ({
  Authorization: `Bearer ${TOKEN}`,
  'Content-Type': 'application/json',
  'X-Correlation-ID': crypto.randomUUID(),
});

export type RiskTier = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
export type TxStatus = 'FLAGGED' | 'UNDER_REVIEW' | 'BLOCKED' | 'CLEARED';

export interface FlaggedTransaction {
  transactionId: string;
  amount: number;
  currency: string;
  senderAccount: string;
  receiverAccount: string;
  senderName: string;
  receiverName: string;
  riskScore: number;
  riskTier: RiskTier;
  blockReasons: string[];
  status: TxStatus;
  flaggedAt: string;
  caseId?: string;
}

export const useTransactions = (riskTier?: RiskTier, status?: TxStatus) =>
  useQuery<FlaggedTransaction[]>({
    queryKey: ['bank-transactions', riskTier, status],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (riskTier) params.set('riskTier', riskTier);
      if (status) params.set('status', status);
      const res = await fetch(`${BASE}/api/v1/bank/transactions?${params}`, { headers: headers() });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      return data.data?.items ?? [];
    },
    refetchInterval: 30_000,
  });

export const useBlockTransaction = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ transactionId, reason }: { transactionId: string; reason: string }) => {
      const res = await fetch(`${BASE}/api/v1/bank/transactions/${transactionId}/block`, {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({ reason }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['bank-transactions'] });
    },
  });
};
