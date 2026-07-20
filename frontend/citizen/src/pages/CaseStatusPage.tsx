import { useParams, Link } from 'react-router-dom';
import { useCaseStatus } from '../api/cases';
import VerdictDisplay from '../components/VerdictDisplay';
import BotWidget from '../components/BotWidget';
import EvidenceUpload from '../components/EvidenceUpload';

const STATUS_STEPS = ['New', 'Assigned', 'Investigating', 'Pending_AI', 'Action_Taken', 'Closed'];

const STATUS_LABELS: Record<string, string> = {
  New: 'Report Received',
  Assigned: 'Assigned to Investigator',
  Investigating: 'Under Investigation',
  Pending_AI: 'AI Analysis Running',
  Action_Taken: 'Action Taken',
  Closed: 'Case Closed',
};

export default function CaseStatusPage() {
  const { caseId } = useParams<{ caseId: string }>();
  const { data: caseData, isLoading, error } = useCaseStatus(caseId ?? null);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="animate-spin rounded-full h-16 w-16 border-b-2 border-blue-600" />
      </div>
    );
  }

  if (error || !caseData) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <p className="text-red-600 text-lg mb-4">Case not found or access denied.</p>
          <Link to="/" className="text-blue-600 underline">Report a new incident</Link>
        </div>
      </div>
    );
  }

  const currentStepIndex = STATUS_STEPS.indexOf(caseData.status);

  return (
    <main className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 py-10">
      <div className="container mx-auto px-4 max-w-3xl">

        {/* Case Header */}
        <div className="bg-white rounded-2xl shadow-lg p-6 mb-6">
          <div className="flex justify-between items-start">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">{caseData.title}</h1>
              <p className="text-gray-500 text-sm mt-1">Case #{caseData.case_number}</p>
            </div>
            <span className="px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm font-medium">
              {STATUS_LABELS[caseData.status] ?? caseData.status}
            </span>
          </div>
        </div>

        {/* Progress Timeline */}
        <div className="bg-white rounded-2xl shadow-lg p-6 mb-6">
          <h2 className="text-lg font-semibold text-gray-700 mb-4">Case Progress</h2>
          <div className="flex items-center justify-between">
            {STATUS_STEPS.map((step, idx) => (
              <div key={step} className="flex flex-col items-center flex-1">
                <div
                  className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold border-2 transition-all
                    ${idx <= currentStepIndex
                      ? 'bg-blue-600 border-blue-600 text-white'
                      : 'bg-white border-gray-300 text-gray-400'
                    }`}
                >
                  {idx < currentStepIndex ? '✓' : idx + 1}
                </div>
                <p className="text-xs text-gray-500 mt-1 text-center hidden md:block">
                  {STATUS_LABELS[step]?.split(' ')[0]}
                </p>
                {idx < STATUS_STEPS.length - 1 && (
                  <div className={`h-1 w-full mt-3 -mb-3 ${idx < currentStepIndex ? 'bg-blue-600' : 'bg-gray-200'}`} />
                )}
              </div>
            ))}
          </div>
        </div>

        {/* AI Verdict */}
        <div className="bg-white rounded-2xl shadow-lg p-6 mb-6">
          <h2 className="text-lg font-semibold text-gray-700 mb-4">AI Risk Assessment</h2>
          <VerdictDisplay prediction={caseData.prediction} />
        </div>

        {/* Evidence Upload */}
        <EvidenceUpload caseId={caseId!} complaintType={caseData?.complaintType || caseData?.complaint_type} />

        {/* Next Steps */}
        <div className="bg-white rounded-2xl shadow-lg p-6">
          <h2 className="text-lg font-semibold text-gray-700 mb-3">What Happens Next?</h2>
          <ul className="space-y-2 text-gray-600 text-sm">
            <li className="flex gap-2">
              <span>📋</span> An investigator will review your case within 24–48 hours.
            </li>
            <li className="flex gap-2">
              <span>📱</span> You will be notified on the phone number you provided.
            </li>
            <li className="flex gap-2">
              <span>🔒</span> Your report is confidential and protected under law.
            </li>
          </ul>
          <div className="mt-4 pt-4 border-t border-gray-100">
            <Link to="/" className="text-blue-600 text-sm font-medium hover:underline">
              ← Report another incident
            </Link>
          </div>
        </div>

      </div>
      <BotWidget />
    </main>
  );
}
