import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import apiClient from './client';

// ─── Evidence Upload Types ────────────────────────────────────────────────────

export interface RequestUploadUrlPayload {
  fileName: string;
  mimeType: string;
  fileSizeBytes: number;
}

export interface UploadUrlResponse {
  evidenceId: string;
  uploadUrl: string;
  uploadUrlExpiresAt: string;
  instructions: string;
}

export interface ConfirmUploadPayload {
  /** SHA-256 hex digest of the file, computed client-side before upload. */
  clientSha256: string;
}

export interface ConfirmUploadResponse {
  evidenceId: string;
  sha256: string;
  hashMatch: boolean;
  malwareScan: string;
  status: string;
  verifiedAt: string;
}

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

export interface CaseSummary {
  caseId: string;
  caseNumber: string;
  title: string;
  complaintType: string;
  status: string;
  createdAt: string;
}

export const useMyCases = () =>
  useQuery({
    queryKey: ['my-cases'],
    queryFn: async () => {
      const res = await apiClient.get('/api/v1/citizen/cases');
      return res.data.data.items as CaseSummary[];
    },
  });

// ─── Evidence: Request Pre-signed Upload URL ──────────────────────────────────

export const useRequestUploadUrl = (caseId: string) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: RequestUploadUrlPayload): Promise<UploadUrlResponse> => {
      const idempotencyKey = crypto.randomUUID();
      const res = await apiClient.post(
        `/api/v1/citizen/cases/${caseId}/evidence`,
        payload,
        { headers: { 'Idempotency-Key': idempotencyKey } },
      );
      return res.data.data as UploadUrlResponse;
    },
    onSuccess: () => {
      // Invalidate so evidence count refreshes after the full upload flow.
      queryClient.invalidateQueries({ queryKey: ['case', caseId] });
    },
  });
};

// ─── Evidence: Confirm Upload (triggers SHA-256 + MIME validation) ────────────

export const useConfirmUpload = () =>
  useMutation({
    mutationFn: async ({
      evidenceId,
      payload,
    }: {
      evidenceId: string;
      payload: ConfirmUploadPayload;
    }): Promise<ConfirmUploadResponse> => {
      const res = await apiClient.post(
        `/api/v1/citizen/evidence/${evidenceId}/confirm`,
        payload,
      );
      return res.data.data as ConfirmUploadResponse;
    },
  });

export interface EvidenceItem {
  evidenceId: string;
  fileName: string;
  mimeType: string;
  fileSizeBytes: number;
  status: string;
  createdAt: string | null;
  verifiedAt: string | null;
}

export const useEvidenceList = (caseId: string | null) =>
  useQuery({
    queryKey: ['evidence', caseId],
    queryFn: async () => {
      const res = await apiClient.get(`/api/v1/citizen/cases/${caseId}/evidence`);
      return res.data.data as EvidenceItem[];
    },
    enabled: !!caseId,
  });
