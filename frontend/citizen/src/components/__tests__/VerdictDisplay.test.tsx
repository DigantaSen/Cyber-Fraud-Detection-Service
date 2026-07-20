import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import VerdictDisplay from '../VerdictDisplay';

const mockPrediction = {
  fusedScore: 72,
  riskTier: 'HIGH' as const,
  confidence: 0.85,
  explanation: 'This appears to be a UPI scam based on reported patterns.',
  modelBreakdown: [
    { model: 'scam-nlp', score: 78, confidence: 0.88 },
    { model: 'graph', score: 65, confidence: 0.82 },
  ],
};

describe('VerdictDisplay', () => {
  it('shows spinner when prediction is null', () => {
    render(<VerdictDisplay prediction={null} />);
    expect(screen.getByText(/AI Analysis in Progress/i)).toBeInTheDocument();
  });

  it('renders risk score when prediction provided', () => {
    render(<VerdictDisplay prediction={mockPrediction} />);
    expect(screen.getByText(/72/)).toBeInTheDocument();
  });

  it('renders HIGH risk badge', () => {
    render(<VerdictDisplay prediction={mockPrediction} />);
    expect(screen.getByText(/High Risk/i)).toBeInTheDocument();
  });

  it('renders explanation text', () => {
    render(<VerdictDisplay prediction={mockPrediction} />);
    expect(screen.getByText(/UPI scam/i)).toBeInTheDocument();
  });

  it('renders model breakdown bars', () => {
    render(<VerdictDisplay prediction={mockPrediction} />);
    expect(screen.getByText(/scam-nlp/i)).toBeInTheDocument();
  });
});
