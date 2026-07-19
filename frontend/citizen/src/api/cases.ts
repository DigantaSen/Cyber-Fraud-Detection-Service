import { useMutation, useQuery } from '@tanstack/react-query';
import apiClient from './client';

export interface CreateCasePayload {
  title: string;
  description: string;
  complaint_type: string;
  suspect_phone?: string;
  language_code: string;
}

export const useCreateCase = () =>
  useMutation({
    mutationFn: async (payload: CreateCasePayload) => {
      const idempotencyKey = crypto.randomUUID();
      const res = await apiClient.post('/api/v1/citizen/report', payload, {
        headers: { 'Idempotency-Key': idempotencyKey },
      });
      return res.data.data;
    },
  });

export const useCaseStatus = (caseId: string | null) =>
  useQuery({
    queryKey: ['case', caseId],
    queryFn: async () => {
      const res = await apiClient.get(`/api/v1/citizen/cases/${caseId}`);
      return res.data.data;
    },
    enabled: !!caseId,
    refetchInterval: 30_000,   // Poll every 30s for status updates
  });
