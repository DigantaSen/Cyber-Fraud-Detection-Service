import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import FlaggedTransactionsPage from './pages/FlaggedTransactionsPage';

const queryClient = new QueryClient();
export default function App() {
  return <QueryClientProvider client={queryClient}><FlaggedTransactionsPage /></QueryClientProvider>;
}
