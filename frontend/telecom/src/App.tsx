import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import ActiveSessionsPage from './pages/ActiveSessionsPage';

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ActiveSessionsPage />
    </QueryClientProvider>
  );
}
