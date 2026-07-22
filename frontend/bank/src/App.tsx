import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useAuth } from './hooks/useAuth';
import FlaggedTransactionsPage from './pages/FlaggedTransactionsPage';
import LoginPage from './pages/LoginPage';

const queryClient = new QueryClient();

function AppContent() {
  const { token, user, loading, error, login, logout } = useAuth();

  if (!token) {
    return <LoginPage onLogin={login} loading={loading} error={error} />;
  }

  return <FlaggedTransactionsPage token={token} user={user} onLogout={logout} />;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppContent />
    </QueryClientProvider>
  );
}
