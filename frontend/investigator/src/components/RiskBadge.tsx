interface RiskBadgeProps {
  tier: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
}

const tierConfig = {
  LOW: { bg: 'bg-green-100', text: 'text-green-800', label: 'Low Risk' },
  MEDIUM: { bg: 'bg-yellow-100', text: 'text-yellow-800', label: 'Medium Risk' },
  HIGH: { bg: 'bg-orange-100', text: 'text-orange-800', label: 'High Risk' },
  CRITICAL: { bg: 'bg-red-100', text: 'text-red-900', label: 'Critical Risk' },
};

export default function RiskBadge({ tier }: RiskBadgeProps) {
  const config = tierConfig[tier] ?? tierConfig.LOW;
  return (
    <span className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-semibold ${config.bg} ${config.text}`}>
      {config.label}
    </span>
  );
}
