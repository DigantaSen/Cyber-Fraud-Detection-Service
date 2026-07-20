import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import axios from 'axios';

// Allowed roles exactly as declared in backend/auth/models/schemas.py RegisterRequest.validate_role
const ALLOWED_ROLES = ['CITIZEN', 'INVESTIGATOR', 'BANK_OFFICIAL', 'TELECOM_ADMIN', 'GOV_OFFICIAL'] as const;
type Role = typeof ALLOWED_ROLES[number];

export default function RegisterPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [phone, setPhone] = useState('');
  const [role, setRole] = useState<Role>('CITIZEN');
  const [orgId, setOrgId] = useState('');
  const [jurisdictionId, setJurisdictionId] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    // Build request body — only include optional fields when non-empty
    const body: Record<string, unknown> = { email, password, phone, role };
    if (orgId.trim()) body.org_id = orgId.trim();
    if (jurisdictionId.trim()) body.jurisdiction_id = jurisdictionId.trim();

    try {
      // POST /api/v1/auth/register
      // Uses bare axios (same as LoginPage) — baseURL is handled by Vite proxy.
      // Idempotency-Key is a UUID generated per submission as required by the backend.
      await axios.post('/api/v1/auth/register', body, {
        headers: { 'Idempotency-Key': crypto.randomUUID() },
      });
      navigate('/login');
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      const message =
        detail?.message ||
        (typeof detail === 'string' ? detail : null) ||
        err.response?.data?.message ||
        'Registration failed. Please check your details.';
      setError(message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-xl p-8 max-w-md w-full">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-gray-900 mb-2">🛡️ Cyber Fraud Shield</h1>
          <p className="text-gray-600">Create your account</p>
        </div>

        {error && (
          <div className="bg-red-50 text-red-700 p-3 rounded-lg text-sm mb-4">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-5">
          {/* Email */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
            <input
              id="register-email"
              type="email"
              required
              className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="name@example.com"
            />
          </div>

          {/* Password */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
            <div className="relative">
              <input
                id="register-password"
                type={showPassword ? 'text' : 'password'}
                required
                minLength={8}
                className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none pr-10"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Min 8 chars, one uppercase, one digit"
              />
              <button
                type="button"
                className="absolute inset-y-0 right-0 pr-3 flex items-center text-gray-500 hover:text-gray-700"
                onClick={() => setShowPassword(!showPassword)}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? (
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-5 h-5">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3.98 8.223A10.477 10.477 0 001.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0112 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 01-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 10-4.243-4.243m4.242 4.242L9.88 9.88" />
                  </svg>
                ) : (
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-5 h-5">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  </svg>
                )}
              </button>
            </div>
          </div>

          {/* Phone */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Phone (E.164)</label>
            <input
              id="register-phone"
              type="tel"
              required
              className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+919876543210"
            />
          </div>

          {/* Role */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Role</label>
            <select
              id="register-role"
              required
              className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none bg-white"
              value={role}
              onChange={(e) => setRole(e.target.value as Role)}
            >
              {ALLOWED_ROLES.map((r) => (
                <option key={r} value={r}>{r.replace('_', ' ')}</option>
              ))}
            </select>
          </div>

          {/* Jurisdiction ID — required for non-CITIZEN roles */}
          {role !== 'CITIZEN' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Jurisdiction ID <span className="text-red-500">*</span>
              </label>
              <input
                id="register-jurisdiction"
                type="text"
                required
                className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
                value={jurisdictionId}
                onChange={(e) => setJurisdictionId(e.target.value)}
                placeholder="e.g. JUR-MH-001"
              />
            </div>
          )}

          {/* Org ID — optional */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Organisation ID <span className="text-gray-400 text-xs font-normal">(optional)</span>
            </label>
            <input
              id="register-org-id"
              type="text"
              className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
              value={orgId}
              onChange={(e) => setOrgId(e.target.value)}
              placeholder="UUID of your organisation"
            />
          </div>

          <button
            id="register-submit"
            type="submit"
            disabled={isLoading}
            className="w-full bg-blue-600 text-white py-3 rounded-lg font-medium hover:bg-blue-700 transition-colors disabled:opacity-50"
          >
            {isLoading ? 'Creating Account...' : 'Create Account'}
          </button>
        </form>

        <p className="text-center text-sm text-gray-600 mt-6">
          Already have an account?{' '}
          <Link to="/login" className="text-blue-600 hover:underline font-medium">
            Sign In
          </Link>
        </p>
      </div>
    </main>
  );
}
