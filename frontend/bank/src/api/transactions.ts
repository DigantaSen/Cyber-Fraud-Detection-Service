import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

const BASE = '';

const headers = (token: string) => ({
  Authorization: `Bearer ${token}`,
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

export const useTransactions = (token: string, riskTier?: RiskTier, status?: TxStatus) =>
  useQuery<FlaggedTransaction[]>({
    queryKey: ['bank-transactions', riskTier, status],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (riskTier) params.set('riskTier', riskTier);
      if (status) params.set('status', status);
      const res = await fetch(`${BASE}/api/v1/bank/transactions/flagged?${params}`, {
        headers: headers(token),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      return data.data?.items ?? [];
    },
    enabled: !!token,
    refetchInterval: 30_000,
  });

export const useBlockTransaction = (token: string) => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ transactionId, reason }: { transactionId: string; reason: string }) => {
      const res = await fetch(`${BASE}/api/v1/bank/transactions/${transactionId}/block`, {
        method: 'POST',
        headers: headers(token),
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
