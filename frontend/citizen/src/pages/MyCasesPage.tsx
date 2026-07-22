import { Link } from 'react-router-dom';
import { useMyCases } from '../api/cases';
import BotWidget from '../components/BotWidget';

const STATUS_LABELS: Record<string, string> = {
  New: 'Report Received',
  Assigned: 'Assigned to Investigator',
  Investigating: 'Under Investigation',
  Pending_AI: 'AI Analysis Running',
  Action_Taken: 'Action Taken',
  Closed: 'Case Closed',
};

const COMPLAINT_TYPE_LABELS: Record<string, string> = {
  UPI_FRAUD: 'UPI Fraud',
  CALL_FRAUD: 'Call Scam',
  COUNTERFEIT_CURRENCY: 'Counterfeit Currency',
  CYBER_CRIME: 'Cyber Crime',
  OTHER: 'Other / Not sure',
};

export default function MyCasesPage() {
  const { data: cases, isLoading, error } = useMyCases();

  return (
    <main className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 py-10">
      <div className="container mx-auto px-4 max-w-4xl">
        <div className="flex justify-between items-center mb-8">
          <h1 className="text-3xl font-bold text-gray-900">My Reports</h1>
          <Link
            to="/"
            className="bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 px-4 rounded shadow transition-colors"
          >
            Report New Incident
          </Link>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600" />
          </div>
        ) : error ? (
          <div className="bg-white rounded-2xl shadow-lg p-8 text-center">
            <p className="text-red-600 text-lg mb-4">Failed to load your reports.</p>
          </div>
        ) : !cases || cases.length === 0 ? (
          <div className="bg-white rounded-2xl shadow-lg p-12 text-center">
            <div className="text-gray-400 mb-4 text-6xl">📁</div>
            <h2 className="text-2xl font-semibold text-gray-800 mb-2">No reports found</h2>
            <p className="text-gray-600 mb-6">You haven't submitted any incident reports yet.</p>
            <Link
              to="/"
              className="inline-block bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 px-6 rounded shadow transition-colors"
            >
              Start a New Report
            </Link>
          </div>
        ) : (
          <div className="grid gap-6">
            {cases.map((c) => (
              <Link
                key={c.caseId}
                to={`/cases/${c.caseId}`}
                className="bg-white rounded-xl shadow p-6 hover:shadow-lg transition-shadow border border-gray-100 block"
              >
                <div className="flex justify-between items-start flex-col sm:flex-row gap-4 sm:gap-0">
                  <div>
                    <h2 className="text-xl font-bold text-gray-900 mb-1">{c.title}</h2>
                    <div className="flex items-center gap-3 text-sm text-gray-500">
                      <span className="font-medium text-gray-700">{c.caseNumber}</span>
                      <span>•</span>
                      <span>{COMPLAINT_TYPE_LABELS[c.complaintType] || c.complaintType}</span>
                      <span>•</span>
                      <span>{new Date(c.createdAt).toLocaleDateString()}</span>
                    </div>
                  </div>
                  <span className="px-3 py-1 bg-blue-50 text-blue-700 rounded-full text-sm font-semibold whitespace-nowrap">
                    {STATUS_LABELS[c.status] || c.status}
                  </span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
      <BotWidget />
    </main>
  );
}
