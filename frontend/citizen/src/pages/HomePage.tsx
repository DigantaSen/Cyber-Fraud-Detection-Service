import ReportForm from '../components/ReportForm';
import BotWidget from '../components/BotWidget';
import { useAuthStore } from '../store/authStore';
import { useNavigate, Link } from 'react-router-dom';

export default function HomePage() {
  const clearAuth = useAuthStore((state) => state.clearAuth);
  const navigate = useNavigate();

  const handleLogout = () => {
    clearAuth();
    navigate('/login');
  };
  return (
    <main className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100">
      <div className="absolute top-4 right-4 flex gap-4">
        <Link 
          to="/my-cases"
          className="bg-white/50 hover:bg-white text-blue-900 px-4 py-2 rounded-lg font-medium transition-colors shadow-sm"
        >
          My Reports
        </Link>
        <button 
          onClick={handleLogout} 
          className="bg-white/50 hover:bg-white text-blue-900 px-4 py-2 rounded-lg font-medium transition-colors shadow-sm"
        >
          Sign Out
        </button>
      </div>
      <div className="container mx-auto px-4 py-12">
        <div className="text-center mb-10">
          <h1 className="text-4xl font-bold text-gray-900 mb-3">
            🛡️ Report Cyber Fraud
          </h1>
          <p className="text-lg text-gray-600 max-w-xl mx-auto">
            Submit a report and our AI system will analyze it immediately.
            Your report is confidential and secure.
          </p>
        </div>
        <div className="bg-white rounded-2xl shadow-xl p-8 max-w-2xl mx-auto">
          <ReportForm />
        </div>
      </div>
      <BotWidget />
    </main>
  );
}
