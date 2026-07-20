import RiskBadge from './RiskBadge';

interface VerdictDisplayProps {
  prediction: {
    fusedScore: number;
    riskTier: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
    confidence: number;
    explanation: string;
    modelBreakdown: Array<{ model: string; score: number; confidence: number }>;
  } | null;
}

export default function VerdictDisplay({ prediction }: VerdictDisplayProps) {
  if (!prediction) {
    return (
      <div className="flex flex-col items-center py-8 text-gray-500">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mb-4" />
        <p className="text-lg">AI Analysis in Progress...</p>
        <p className="text-sm mt-1">This usually takes 30–60 seconds</p>
      </div>
    );
  }

  const { fusedScore, riskTier, confidence, explanation, modelBreakdown } = prediction;

  // Color for the gauge needle
  const gaugeColor =
    fusedScore < 30 ? '#22c55e' :
    fusedScore < 60 ? '#f59e0b' :
    fusedScore < 80 ? '#f97316' : '#ef4444';

  return (
    <div className="space-y-6">
      {/* Risk Score Gauge */}
      <div className="text-center">
        <div className="relative inline-block">
          <svg width="200" height="110" viewBox="0 0 200 110">
            {/* Background arc */}
            <path d="M 10 100 A 90 90 0 0 1 190 100" fill="none" stroke="#e5e7eb" strokeWidth="20" strokeLinecap="round" />
            {/* Score arc */}
            <path
              d="M 10 100 A 90 90 0 0 1 190 100"
              fill="none"
              stroke={gaugeColor}
              strokeWidth="20"
              strokeLinecap="round"
              strokeDasharray={`${(fusedScore / 100) * 283} 283`}
            />
            {/* Score text */}
            <text x="100" y="95" textAnchor="middle" className="fill-gray-900 text-3xl font-bold" fontSize="32" fontWeight="bold" fill="#111827">
              {Math.round(fusedScore)}
            </text>
          </svg>
        </div>
        <div className="mt-2">
          <RiskBadge tier={riskTier} />
        </div>
        <p className="text-sm text-gray-500 mt-1">
          Confidence: {Math.round(confidence * 100)}%
        </p>
      </div>

      {/* Explanation */}
      <div className="bg-blue-50 rounded-xl p-4">
        <h3 className="font-semibold text-blue-900 mb-2">AI Analysis</h3>
        <p className="text-blue-800 text-sm">{explanation}</p>
      </div>

      {/* Model Breakdown */}
      {modelBreakdown.length > 0 && (
        <div>
          <h3 className="font-semibold text-gray-700 mb-3">Analysis Details</h3>
          <div className="space-y-2">
            {modelBreakdown.map((m) => (
              <div key={m.model} className="flex items-center gap-3">
                <span className="text-xs text-gray-500 w-28 truncate">{m.model}</span>
                <div className="flex-1 bg-gray-200 rounded-full h-2">
                  <div
                    className="h-2 rounded-full transition-all duration-500"
                    style={{ width: `${m.score}%`, backgroundColor: gaugeColor }}
                  />
                </div>
                <span className="text-xs font-mono text-gray-700 w-8">{m.score}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
