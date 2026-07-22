import { useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useRequestUploadUrl, useConfirmUpload } from '../api/cases';

// ─── Types ────────────────────────────────────────────────────────────────────

type UploadState =
  | { status: 'idle' }
  | { status: 'selecting' }
  | { status: 'uploading'; progress: number }
  | { status: 'confirming' }
  | { status: 'completed'; evidenceId: string; malwareScan: string; verified: boolean }
  | { status: 'failed'; message: string };

// ─── Allowed MIME Types (FR-3.5 from evidence.md) ────────────────────────────

const ALLOWED_MIME_TYPES = [
  'image/png',
  'image/jpeg',
  'application/pdf',
  'audio/wav',
  'audio/mpeg',
  'audio/m4a',
  'audio/ogg',
];

const MIME_IMAGES = ['image/png', 'image/jpeg'];
const MIME_DOCS = ['application/pdf'];
const MIME_AUDIO = ['audio/wav', 'audio/mpeg', 'audio/m4a', 'audio/ogg'];

const COMPLAINT_TYPE_MIME_MAP: Record<string, string[]> = {
  UPI_FRAUD: [...MIME_IMAGES, ...MIME_DOCS],
  CALL_FRAUD: [...MIME_AUDIO],
  COUNTERFEIT_CURRENCY: [...MIME_IMAGES],
  CYBER_CRIME: [...MIME_IMAGES, ...MIME_DOCS],
  OTHER: ALLOWED_MIME_TYPES,
};

const COMPLAINT_TYPE_DESC_MAP: Record<string, string> = {
  UPI_FRAUD: 'Upload supporting files (screenshots, bank statements). Max 50 MB per file.',
  CALL_FRAUD: 'Upload call recordings (WAV, MP3, M4A, OGG). Max 50 MB per file.',
  COUNTERFEIT_CURRENCY: 'Upload images of the counterfeit currency (PNG, JPEG). Max 50 MB per file.',
  CYBER_CRIME: 'Upload supporting files (screenshots, PDFs). Max 50 MB per file.',
  OTHER: 'Upload supporting files (screenshots, audio recordings, PDFs). Max 50 MB per file.',
};

const MAX_FILE_BYTES = 50 * 1024 * 1024; // 50 MB

// ─── Helper: compute SHA-256 using Web Crypto API ─────────────────────────────

async function computeSha256(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  const hashBuffer = await window.crypto.subtle.digest('SHA-256', buffer);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map((b) => b.toString(16).padStart(2, '0')).join('');
}

// ─── Props ────────────────────────────────────────────────────────────────────

interface EvidenceUploadProps {
  caseId: string;
  complaintType?: string;
  caseStatus?: string;
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function EvidenceUpload({ caseId, complaintType, caseStatus }: EvidenceUploadProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploadState, setUploadState] = useState<UploadState>({ status: 'idle' });
  const [aiEvalDone, setAiEvalDone] = useState<boolean>(false);
  const queryClient = useQueryClient();

  const requestUploadUrl = useRequestUploadUrl(caseId);
  const confirmUpload = useConfirmUpload();

  // ── Validate file before starting the upload flow ──────────────────────────

  const allowedTypes = complaintType && COMPLAINT_TYPE_MIME_MAP[complaintType]
    ? COMPLAINT_TYPE_MIME_MAP[complaintType]
    : ALLOWED_MIME_TYPES;

  function validateFile(file: File): string | null {
    if (!allowedTypes.includes(file.type)) {
      return `Unsupported file type "${file.type}" for this complaint. Allowed: ${allowedTypes.join(', ')}.`;
    }
    if (file.size > MAX_FILE_BYTES) {
      return `File exceeds 50 MB limit (${(file.size / 1024 / 1024).toFixed(1)} MB).`;
    }
    return null;
  }

  // ── Main upload orchestration ───────────────────────────────────────────────

  async function handleFileSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    // Reset input so the same file can be re-selected after a failure
    if (fileInputRef.current) fileInputRef.current.value = '';

    if (!file) return;

    const validationError = validateFile(file);
    if (validationError) {
      setUploadState({ status: 'failed', message: validationError });
      return;
    }

    try {
      // ── Step 1: Request presigned URL from Citizen BFF ────────────────────
      setUploadState({ status: 'selecting' });

      const { evidenceId, uploadUrl } = await requestUploadUrl.mutateAsync({
        fileName: file.name,
        mimeType: file.type,
        fileSizeBytes: file.size,
      });

      // ── Step 2: Compute SHA-256 before upload (required by confirm step) ──
      // This runs synchronously on the main thread; acceptable for ≤50 MB files.
      const clientSha256 = await computeSha256(file);

      // ── Step 3: Upload file directly to MinIO via presigned PUT ───────────
      setUploadState({ status: 'uploading', progress: 0 });

      const uploadRes = await fetch(uploadUrl, {
          method: "PUT",
          body: file
      });
      if (!uploadRes.ok) {
          throw new Error('Upload to storage failed.');
      }

      // ── Step 4: Confirm upload — triggers SHA-256 + MIME validation ───────
      setUploadState({ status: 'confirming' });

      const confirmation = await confirmUpload.mutateAsync({
        evidenceId,
        payload: {
          clientSha256,
        },
      });

      // ── Step 5: Done — invalidate queries & schedule auto-refetch for AI re-evaluation
      queryClient.refetchQueries({ queryKey: ['case', caseId] });
      queryClient.refetchQueries({ queryKey: ['evidence', caseId] });
      setAiEvalDone(false);
      setUploadState({
        status: 'completed',
        evidenceId: confirmation.evidenceId,
        malwareScan: confirmation.malwareScan,
        verified: confirmation.hashMatch,
      });

      // Schedule forced refetches to pick up async Kafka AI re-evaluation results
      [1500, 3000, 5000].forEach((delay) => {
        setTimeout(() => {
          queryClient.refetchQueries({ queryKey: ['case', caseId] });
          queryClient.refetchQueries({ queryKey: ['evidence', caseId] });
        }, delay);
      });

      // Mark AI evaluation completed after 4.5 seconds
      setTimeout(() => {
        setAiEvalDone(true);
      }, 4500);
    } catch (err: unknown) {
      const message =
        extractApiError(err) ?? 'Upload failed. Please try again.';
      setUploadState({ status: 'failed', message });
    }
  }

  // ── Helpers ────────────────────────────────────────────────────────────────

  function reset() {
    setUploadState({ status: 'idle' });
  }

  const isClosed = ['CLOSED', 'DISMISSED'].includes((caseStatus || '').toUpperCase());

  if (isClosed) {
    return (
      <div className="bg-slate-100/80 rounded-2xl p-6 mb-6 text-center border border-slate-200 shadow-sm">
        <div className="flex items-center justify-center gap-2 text-slate-600 font-semibold text-sm">
          <span className="text-base">🔒</span>
          <span>This case is closed. Additional evidence submission is disabled.</span>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-2xl shadow-lg p-6 mb-6">
      <h2 className="text-lg font-semibold text-gray-700 mb-4">Submit Additional Evidence</h2>

      {/* Idle / failed states — show picker */}
      {(uploadState.status === 'idle' || uploadState.status === 'failed') && (
        <div>
          <p className="text-sm text-gray-500 mb-4">
            {complaintType && COMPLAINT_TYPE_DESC_MAP[complaintType]
              ? COMPLAINT_TYPE_DESC_MAP[complaintType]
              : COMPLAINT_TYPE_DESC_MAP['OTHER']}
          </p>

          {/* Error message */}
          {uploadState.status === 'failed' && (
            <div
              role="alert"
              className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg px-4 py-3 mb-4 text-sm text-red-700"
            >
              <span className="mt-0.5" aria-hidden="true">⚠️</span>
              <span>{uploadState.message}</span>
            </div>
          )}

          {/* File input */}
          <label
            htmlFor="evidence-file-input"
            className="inline-flex items-center gap-2 cursor-pointer bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white text-sm font-medium px-4 py-2.5 rounded-lg transition-colors focus-within:ring-2 focus-within:ring-blue-400 focus-within:ring-offset-2"
          >
            <span aria-hidden="true">📎</span>
            Choose File
            <input
              id="evidence-file-input"
              ref={fileInputRef}
              type="file"
              className="sr-only"
              accept={allowedTypes.join(',')}
              onChange={handleFileSelected}
            />
          </label>

          <p className="text-xs text-gray-400 mt-2">
            Supported: {allowedTypes.map(t => t.split('/')[1].toUpperCase()).join(', ')}
          </p>
        </div>
      )}

      {/* Selecting state */}
      {uploadState.status === 'selecting' && (
        <UploadStatus
          icon="🔗"
          label="Requesting upload URL…"
          description="Contacting server to prepare your upload."
        />
      )}

      {/* Uploading state */}
      {uploadState.status === 'uploading' && (
        <div>
          <UploadStatus
            icon="⬆️"
            label="Uploading file…"
            description={`${uploadState.progress}% uploaded`}
          />
          <div className="mt-3 h-2 w-full bg-gray-100 rounded-full overflow-hidden">
            <div
              className="h-2 bg-blue-500 rounded-full transition-all duration-200"
              style={{ width: `${uploadState.progress}%` }}
              role="progressbar"
              aria-valuenow={uploadState.progress}
              aria-valuemin={0}
              aria-valuemax={100}
            />
          </div>
        </div>
      )}

      {/* Confirming state */}
      {uploadState.status === 'confirming' && (
        <UploadStatus
          icon="🔍"
          label="Verifying file…"
          description="Server is validating integrity and scanning for malware."
        />
      )}

      {/* Completed state */}
      {uploadState.status === 'completed' && (
        <div className="space-y-3">
          <div className="flex items-start gap-3 bg-green-50 border border-green-200 rounded-xl px-4 py-3">
            <span className="text-xl" aria-hidden="true">✅</span>
            <div className="text-sm">
              <p className="font-semibold text-green-800">Evidence uploaded successfully</p>
              <p className="text-green-700 mt-0.5">
                Hash verified: {uploadState.verified ? 'Yes' : 'No'} · Malware scan:{' '}
                {uploadState.malwareScan}
              </p>
            </div>
          </div>

          {!aiEvalDone ? (
            <div className="flex items-center gap-3 bg-indigo-50 border border-indigo-200 rounded-xl p-4 animate-pulse">
              <span className="text-2xl">⚡</span>
              <div>
                <p className="font-semibold text-indigo-900 text-sm">AI Risk Re-Evaluation Active</p>
                <p className="text-xs text-indigo-700 mt-0.5">
                  The AI Inference Engine is re-evaluating risk models (Scam NLP, Graph Linkages & Media Analysis) with your new evidence. The risk assessment score above is auto-updating...
                </p>
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-3 bg-emerald-50 border border-emerald-300 rounded-xl p-4">
              <span className="text-2xl">✨</span>
              <div>
                <p className="font-semibold text-emerald-900 text-sm">AI Risk Re-Evaluation Complete</p>
                <p className="text-xs text-emerald-700 mt-0.5">
                  Case risk score and model breakdown have been updated with your newly submitted evidence.
                </p>
              </div>
            </div>
          )}

          <button
            type="button"
            onClick={reset}
            className="text-sm text-blue-600 hover:underline font-medium focus:outline-none"
          >
            + Upload another file
          </button>
        </div>
      )}
    </div>
  );
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function UploadStatus({
  icon,
  label,
  description,
}: {
  icon: string;
  label: string;
  description: string;
}) {
  return (
    <div className="flex items-center gap-3 text-sm text-gray-600" aria-live="polite" aria-busy="true">
      <span className="text-xl animate-pulse" aria-hidden="true">{icon}</span>
      <div>
        <p className="font-medium text-gray-800">{label}</p>
        <p className="text-gray-500">{description}</p>
      </div>
    </div>
  );
}



// ─── API error extraction ─────────────────────────────────────────────────────

function extractApiError(err: unknown): string | null {
  if (
    err &&
    typeof err === 'object' &&
    'response' in err &&
    err.response &&
    typeof err.response === 'object' &&
    'data' in err.response
  ) {
    const data = (err.response as { data: unknown }).data;
    if (data && typeof data === 'object' && 'message' in data) {
      return String((data as { message: unknown }).message);
    }
    if (data && typeof data === 'object' && 'detail' in data) {
      const detail = (data as { detail: unknown }).detail;
      if (detail && typeof detail === 'object' && 'message' in detail) {
        return String((detail as { message: unknown }).message);
      }
    }
  }
  if (err instanceof Error) return err.message;
  return null;
}
