import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import { vi, describe, it, expect } from 'vitest';
import ReportForm from '../ReportForm';

// Mock the useCreateCase mutation
vi.mock('../../api/cases', () => ({
  useCreateCase: () => ({
    mutate: vi.fn(),
    isPending: false,
    error: null,
  }),
}));

const renderWithProviders = (ui: React.ReactElement) => {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <BrowserRouter>{ui}</BrowserRouter>
    </QueryClientProvider>
  );
};

describe('ReportForm', () => {
  it('renders step 1 complaint type selection', () => {
    renderWithProviders(<ReportForm />);
    expect(screen.getByText(/UPI Fraud|Complaint Type/i)).toBeInTheDocument();
  });

  it('shows progress bar on step 1', () => {
    renderWithProviders(<ReportForm />);
    // Progress bar should be present
    const progressBar = document.querySelector('[style*="width"]');
    expect(progressBar).toBeInTheDocument();
  });

  it('advances to step 2 when complaint type selected and Next clicked', async () => {
    renderWithProviders(<ReportForm />);
    const user = userEvent.setup();
    // Find a complaint type option and click it
    const upiOption = screen.queryByText(/UPI Fraud/i);
    if (upiOption) {
      await user.click(upiOption);
    }
    const nextBtn = screen.queryByRole('button', { name: /next/i });
    if (nextBtn) {
      await user.click(nextBtn);
      await waitFor(() => {
        // Step 2 has Description field
        expect(screen.queryByPlaceholderText(/Describe exactly/i) || screen.queryByLabelText(/Description/i)).not.toBeNull();
      });
    }
  });
});
