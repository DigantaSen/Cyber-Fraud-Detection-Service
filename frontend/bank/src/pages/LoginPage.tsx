import { useState, type FormEvent } from 'react';

interface LoginPageProps {
  onLogin: (email: string, password: string) => Promise<void>;
  loading: boolean;
  error: string | null;
}

export default function LoginPage({ onLogin, loading, error }: LoginPageProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPass, setShowPass] = useState(false);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    onLogin(email, password);
  };

  return (
    <div
      className="min-h-screen flex items-center justify-center p-4"
      style={{
        fontFamily: "'Inter', sans-serif",
        background: 'linear-gradient(135deg, #f0f4ff 0%, #fafbff 50%, #eff6ff 100%)',
      }}
    >
      {/* Decorative blobs */}
      <div
        style={{
          position: 'fixed', top: '-10%', right: '-10%', width: '40vw', height: '40vw',
          borderRadius: '50%', background: 'rgba(59,130,246,0.08)', pointerEvents: 'none',
        }}
      />
      <div
        style={{
          position: 'fixed', bottom: '-10%', left: '-10%', width: '35vw', height: '35vw',
          borderRadius: '50%', background: 'rgba(99,102,241,0.07)', pointerEvents: 'none',
        }}
      />

      <div className="w-full max-w-sm relative">
        {/* Card */}
        <div
          className="rounded-3xl border border-blue-100 p-8 shadow-2xl"
          style={{ background: 'rgba(255,255,255,0.95)', backdropFilter: 'blur(20px)' }}
        >
          {/* Logo */}
          <div className="flex flex-col items-center mb-8">
            <div
              className="w-16 h-16 rounded-2xl flex items-center justify-center mb-4 shadow-lg"
              style={{ background: 'linear-gradient(135deg, #1e40af 0%, #3b82f6 100%)' }}
            >
              <span className="text-3xl">🏦</span>
            </div>
            <h1 className="text-xl font-bold text-gray-900">Bank Fraud Monitor</h1>
            <p className="text-gray-400 text-sm mt-1">Cyber Fraud Detection Platform</p>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Email */}
            <div>
              <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">
                Email Address
              </label>
              <input
                id="bank-email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="officer@bank.gov.in"
                className="w-full px-4 py-3 rounded-xl bg-gray-50 border border-gray-200 text-gray-900 placeholder-gray-400 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 transition-all"
              />
            </div>

            {/* Password */}
            <div>
              <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">
                Password
              </label>
              <div className="relative">
                <input
                  id="bank-password"
                  type={showPass ? 'text' : 'password'}
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full px-4 py-3 rounded-xl bg-gray-50 border border-gray-200 text-gray-900 placeholder-gray-400 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 transition-all pr-12"
                />
                <button
                  type="button"
                  onClick={() => setShowPass(v => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 text-xs"
                >
                  {showPass ? '🙈' : '👁'}
                </button>
              </div>
            </div>

            {/* Error */}
            {error && (
              <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-3 text-red-700 text-sm flex items-start gap-2">
                <span className="shrink-0 mt-0.5">⚠</span>
                <span>{error}</span>
              </div>
            )}

            {/* Submit */}
            <button
              id="bank-login-btn"
              type="submit"
              disabled={loading}
              className="w-full py-3 rounded-xl font-semibold text-sm text-white transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 mt-2"
              style={{
                background: loading
                  ? 'rgba(30,64,175,0.5)'
                  : 'linear-gradient(135deg, #1e40af 0%, #3b82f6 100%)',
                boxShadow: loading ? 'none' : '0 4px 20px rgba(59,130,246,0.35)',
              }}
            >
              {loading ? (
                <>
                  <div
                    className="w-4 h-4 rounded-full border-2 border-white/30 border-t-white"
                    style={{ animation: 'spin 0.8s linear infinite' }}
                  />
                  Signing in…
                </>
              ) : (
                'Sign In →'
              )}
            </button>
          </form>

          {/* Footer */}
          <p className="text-center text-xs text-gray-400 mt-6">
            Role required: <span className="text-blue-600 font-mono font-semibold">BANK_OFFICIAL</span>
          </p>
        </div>

        <p className="text-center text-xs text-gray-400 mt-4">
          AI-Powered Fraud Detection · Government of India
        </p>
      </div>

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}
