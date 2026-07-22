import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCreateCase } from '../api/cases';
import type { CreateCasePayload } from '../api/cases';

interface StepProps {
  form: CreateCasePayload;
  setForm: React.Dispatch<React.SetStateAction<CreateCasePayload>>;
  onNext?: () => void;
  onBack?: () => void;
  onSubmit?: (e?: React.FormEvent) => void;
  isLoading?: boolean;
  error?: string;
}


export default function ReportForm() {
  const [step, setStep] = useState(1);
  const [form, setForm] = useState<CreateCasePayload>({
    complaint_type: '',
    title: '',
    description: '',
    suspect_phone: '',
    suspect_account: '',
    complaint_lat: undefined,
    complaint_lon: undefined,
    reporter_entity_name: '',
    reporter_phone: '',
    language_code: 'en',
  });
  const navigate = useNavigate();
  const createCase = useCreateCase();

  const handleSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    createCase.mutate(form, {
      onSuccess: (data: any) => {
        navigate(`/cases/${data.caseId}`);
      },
    });
  };

  return (
    <div className="max-w-2xl mx-auto">
      {/* Progress bar */}
      <div className="w-full bg-gray-200 rounded-full h-2 mb-8">
        <div
          className="bg-blue-600 h-2 rounded-full transition-all duration-300"
          style={{ width: `${(step / 3) * 100}%` }}
        />
      </div>

      {/* Multi-step form content */}
      <form onSubmit={(e) => { e.preventDefault(); }} className="space-y-6">
        {step === 1 && <StepComplaintType form={form} setForm={setForm} onNext={() => setStep(2)} />}
        {step === 2 && <StepDetails form={form} setForm={setForm} onBack={() => setStep(1)} onNext={() => setStep(3)} />}
        {step === 3 && (
          <StepReview
            form={form}
            setForm={setForm}
            onBack={() => setStep(2)}
            onSubmit={handleSubmit}
            isLoading={createCase.isPending}
            error={createCase.error?.message}
          />
        )}
      </form>
    </div>
  );
}

const complaintTypes = [
  { id: 'UPI_FRAUD', label: 'UPI Fraud', icon: '💳' },
  { id: 'CALL_FRAUD', label: 'Call Fraud', icon: '📞' },
  { id: 'COUNTERFEIT_CURRENCY', label: 'Counterfeit Currency', icon: '💵' },
  { id: 'CYBER_CRIME', label: 'Cyber Crime', icon: '🖥️' },
  { id: 'OTHER', label: 'Other', icon: '❓' },
];

function StepComplaintType({ form, setForm, onNext }: StepProps) {
  return (
    <div className="space-y-6 transition-all duration-500">
      <h2 className="text-2xl font-semibold text-gray-800">What type of fraud occurred?</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {complaintTypes.map((t) => (
          <button
            key={t.id}
            type="button"
            className={`p-4 border-2 rounded-xl text-left transition-transform hover:scale-105 ${
              form.complaint_type === t.id ? 'border-blue-600 bg-blue-50' : 'border-gray-200 hover:border-blue-300'
            }`}
            onClick={() => setForm({ ...form, complaint_type: t.id })}
          >
            <div className="text-3xl mb-2">{t.icon}</div>
            <div className="font-medium text-gray-800">{t.label}</div>
          </button>
        ))}
      </div>
      <button
        type="button"
        disabled={!form.complaint_type}
        onClick={onNext}
        className="w-full bg-blue-600 text-white py-3 rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
      >
        Next Step
      </button>
    </div>
  );
}

function StepDetails({ form, setForm, onBack, onNext }: StepProps) {
  const [errors, setErrors] = useState({ title: '', description: '', suspect_phone: '', reporter_phone: '' });

  const validate = () => {
    let valid = true;
    const newErrors = { title: '', description: '', suspect_phone: '', reporter_phone: '' };

    if (!form.title.trim()) { newErrors.title = 'Title is required'; valid = false; }
    if (!form.description.trim()) { newErrors.description = 'Description is required'; valid = false; }
    
    if (form.suspect_phone && !/^\+[1-9][0-9]{7,14}$/.test(form.suspect_phone)) {
      newErrors.suspect_phone = 'Invalid E.164 format (e.g. +919876543210)';
      valid = false;
    }
    if (form.reporter_phone && !/^\+[1-9][0-9]{7,14}$/.test(form.reporter_phone)) {
      newErrors.reporter_phone = 'Invalid E.164 format (e.g. +919876543210)';
      valid = false;
    }

    setErrors(newErrors);
    if (valid) onNext?.();
  };

  return (
    <div className="space-y-6 transition-all duration-500">
      <h2 className="text-2xl font-semibold text-gray-800">Provide details</h2>
      
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Title <span className="text-red-500">*</span></label>
        <input
          type="text"
          maxLength={200}
          className={`w-full p-3 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none ${errors.title ? 'border-red-500' : 'border-gray-300'}`}
          value={form.title}
          onChange={(e) => {
            setForm({ ...form, title: e.target.value });
            if (e.target.value.trim()) setErrors({ ...errors, title: '' });
          }}
          placeholder="Brief summary (e.g., Fake customer care call)"
        />
        {errors.title && <p className="text-red-500 text-sm mt-1">{errors.title}</p>}
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Description <span className="text-red-500">*</span></label>
        <textarea
          rows={4}
          className={`w-full p-3 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none ${errors.description ? 'border-red-500' : 'border-gray-300'}`}
          value={form.description}
          onChange={(e) => {
            setForm({ ...form, description: e.target.value });
            if (e.target.value.trim()) setErrors({ ...errors, description: '' });
          }}
          placeholder="Describe exactly what happened..."
        />
        {errors.description && <p className="text-red-500 text-sm mt-1">{errors.description}</p>}
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Suspect Phone (Optional)</label>
        <input
          type="text"
          className={`w-full p-3 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none ${errors.suspect_phone ? 'border-red-500' : 'border-gray-300'}`}
          value={form.suspect_phone}
          onChange={(e) => {
            const val = e.target.value;
            setForm({ ...form, suspect_phone: val });
            if (val && !/^\+[1-9][0-9]{7,14}$/.test(val)) {
              setErrors({ ...errors, suspect_phone: 'Must be E.164 format (e.g. +919876543210)' });
            } else {
              setErrors({ ...errors, suspect_phone: '' });
            }
          }}
          placeholder="+919876543210"
        />
        {errors.suspect_phone && <p className="text-red-500 text-sm mt-1">{errors.suspect_phone}</p>}
      </div>

      {/* ── Suspect Bank Account (UPI_FRAUD only) ──────────────────── */}
      {form.complaint_type === 'UPI_FRAUD' && (
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Suspect Bank / UPI Account <span className="text-xs text-gray-400">(Optional)</span>
          </label>
          <input
            type="text"
            className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
            value={form.suspect_account || ''}
            onChange={(e) => setForm({ ...form, suspect_account: e.target.value || undefined })}
            placeholder="e.g. 9876543210@upi or 00001234567890"
          />
          <p className="text-xs text-gray-400 mt-1">Enter the UPI ID or bank account number used by the fraudster</p>
        </div>
      )}

      {/* ── Reporter Contact Details ──────────────────────────────── */}
      <div className="border-t pt-4">
        <p className="text-sm font-semibold text-gray-700 mb-3">Your Contact Details <span className="text-xs font-normal text-gray-400">(so investigators can reach you)</span></p>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Your Name / Organisation <span className="text-xs text-gray-400">(Optional)</span></label>
            <input
              type="text"
              className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
              value={form.reporter_entity_name || ''}
              onChange={(e) => setForm({ ...form, reporter_entity_name: e.target.value || undefined })}
              placeholder="e.g. Ramesh Kumar or ABC Bank Ltd"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Your Phone Number <span className="text-xs text-gray-400">(Optional)</span></label>
            <input
              type="text"
              className={`w-full p-3 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none ${errors.reporter_phone ? 'border-red-500' : 'border-gray-300'}`}
              value={form.reporter_phone || ''}
              onChange={(e) => {
                const val = e.target.value;
                setForm({ ...form, reporter_phone: val || undefined });
                if (val && !/^\+[1-9][0-9]{7,14}$/.test(val)) {
                  setErrors({ ...errors, reporter_phone: 'Must be E.164 format (e.g. +919876543210)' });
                } else {
                  setErrors({ ...errors, reporter_phone: '' });
                }
              }}
              placeholder="+919876543210"
            />
            {errors.reporter_phone && <p className="text-red-500 text-sm mt-1">{errors.reporter_phone}</p>}
          </div>
        </div>
      </div>

      {/* ── Incident Location ─────────────────────────────────────── */}
      <LocationPicker form={form} setForm={setForm} />

      <div className="flex gap-4">
        <button type="button" onClick={onBack} className="w-1/3 bg-gray-100 text-gray-700 py-3 rounded-lg font-medium hover:bg-gray-200 transition-colors">
          Back
        </button>
        <button type="button" onClick={validate} className="w-2/3 bg-blue-600 text-white py-3 rounded-lg font-medium hover:bg-blue-700 transition-colors">
          Next Step
        </button>
      </div>
    </div>
  );
}


function LocationPicker({ form, setForm }: Pick<StepProps, 'form' | 'setForm'>) {
  const [locStatus, setLocStatus] = React.useState<'idle' | 'loading' | 'ok' | 'error'>('idle');
  const [manualLat, setManualLat] = React.useState<string>(form.complaint_lat != null ? String(form.complaint_lat) : '');
  const [manualLon, setManualLon] = React.useState<string>(form.complaint_lon != null ? String(form.complaint_lon) : '');

  const useMyLocation = () => {
    if (!navigator.geolocation) {
      setLocStatus('error');
      return;
    }
    setLocStatus('loading');
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const lat = parseFloat(pos.coords.latitude.toFixed(6));
        const lon = parseFloat(pos.coords.longitude.toFixed(6));
        setManualLat(String(lat));
        setManualLon(String(lon));
        setForm({
          ...form,
          complaint_lat: lat,
          complaint_lon: lon,
        });
        setLocStatus('ok');
      },
      () => setLocStatus('error')
    );
  };

  const applyManualCoordinates = () => {
    const latNum = parseFloat(manualLat);
    const lonNum = parseFloat(manualLon);
    if (!isNaN(latNum) && !isNaN(lonNum)) {
      setForm({
        ...form,
        complaint_lat: latNum,
        complaint_lon: lonNum,
      });
      setLocStatus('ok');
    }
  };

  const clearLocation = () => {
    setForm({ ...form, complaint_lat: undefined, complaint_lon: undefined });
    setManualLat('');
    setManualLon('');
    setLocStatus('idle');
  };

  const isCaptured = form.complaint_lat != null && form.complaint_lon != null;

  return (
    <div className="border border-dashed border-gray-300 rounded-lg p-4 bg-gray-50 space-y-3">
      <label className="block text-sm font-medium text-gray-700">📍 Incident Location <span className="text-xs text-gray-400">(Optional — helps geo-hotspot analysis)</span></label>
      
      {isCaptured ? (
        <div className="flex items-center gap-3">
          <div className="flex-1 bg-white border border-green-300 rounded-lg p-3 text-sm text-green-700 flex items-center justify-between">
            <span>✅ Location confirmed: <strong>{form.complaint_lat?.toFixed(5)}, {form.complaint_lon?.toFixed(5)}</strong></span>
          </div>
          <button
            type="button"
            onClick={clearLocation}
            className="text-xs text-red-500 hover:text-red-700 underline font-semibold whitespace-nowrap"
          >
            Clear / Edit
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={useMyLocation}
              disabled={locStatus === 'loading'}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-semibold rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors shadow-sm"
            >
              {locStatus === 'loading' ? '⏳ Getting location...' : '📍 Use My GPS Location'}
            </button>
            <span className="text-xs text-gray-400 font-medium">OR Enter Coordinates:</span>
          </div>

          <div className="flex items-center gap-2">
            <input
              type="text"
              placeholder="Latitude (e.g. 19.0760)"
              className="flex-1 p-2.5 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 outline-none bg-white font-mono"
              value={manualLat}
              onChange={(e) => setManualLat(e.target.value)}
            />
            <input
              type="text"
              placeholder="Longitude (e.g. 72.8777)"
              className="flex-1 p-2.5 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 outline-none bg-white font-mono"
              value={manualLon}
              onChange={(e) => setManualLon(e.target.value)}
            />
            <button
              type="button"
              onClick={applyManualCoordinates}
              disabled={!manualLat.trim() || !manualLon.trim()}
              className="px-4 py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-300 text-white text-sm font-bold rounded-lg transition-colors shadow-sm flex items-center gap-1.5 whitespace-nowrap cursor-pointer"
            >
              <span>✓ Apply Location</span>
            </button>
          </div>
        </div>
      )}
      {locStatus === 'error' && (
        <p className="text-red-500 text-xs">Could not get your location. Please allow GPS access or type coordinates above.</p>
      )}
    </div>
  );
}

const languages = [
  { code: 'en', label: 'English' },
  { code: 'hi', label: 'Hindi' },
  { code: 'bn', label: 'Bengali' },
  { code: 'ta', label: 'Tamil' },
  { code: 'te', label: 'Telugu' },
  { code: 'mr', label: 'Marathi' },
  { code: 'gu', label: 'Gujarati' },
  { code: 'other', label: 'Other' },
];

function StepReview({ form, setForm, onBack, onSubmit, isLoading, error }: StepProps) {
  return (
    <div className="space-y-6 transition-all duration-500">
      <h2 className="text-2xl font-semibold text-gray-800">Review & Submit</h2>
      
      {error && (
        <div className="bg-red-50 border-l-4 border-red-500 p-4 rounded-r-md flex items-start">
          <div className="text-red-500 mr-3">⚠️</div>
          <div>
            <p className="text-sm text-red-700 font-medium">Failed to submit report</p>
            <p className="text-sm text-red-600">{error}</p>
          </div>
        </div>
      )}

      <div className="bg-gray-50 rounded-xl p-5 space-y-4 text-sm text-gray-700">
        <div>
          <span className="font-semibold block text-gray-500">Type</span>
          <span>{form.complaint_type}</span>
        </div>
        <div>
          <span className="font-semibold block text-gray-500">Title</span>
          <span>{form.title}</span>
        </div>
        <div>
          <span className="font-semibold block text-gray-500">Description</span>
          <p className="whitespace-pre-wrap">{form.description}</p>
        </div>
        {form.suspect_phone && (
          <div>
            <span className="font-semibold block text-gray-500">Suspect Phone</span>
            <span>{form.suspect_phone}</span>
          </div>
        )}
        {form.suspect_account && (
          <div>
            <span className="font-semibold block text-gray-500">Suspect Bank / UPI Account</span>
            <span>{form.suspect_account}</span>
          </div>
        )}
        {form.reporter_entity_name && (
          <div>
            <span className="font-semibold block text-gray-500">Your Name / Organisation</span>
            <span>{form.reporter_entity_name}</span>
          </div>
        )}
        {form.reporter_phone && (
          <div>
            <span className="font-semibold block text-gray-500">Your Contact Phone</span>
            <span>{form.reporter_phone}</span>
          </div>
        )}
        {form.complaint_lat && form.complaint_lon && (
          <div>
            <span className="font-semibold block text-gray-500">📍 Incident Location</span>
            <span className="text-green-700">{form.complaint_lat.toFixed(5)}, {form.complaint_lon.toFixed(5)}</span>
          </div>
        )}
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Preferred Language for Updates</label>
        <select
          className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none bg-white"
          value={form.language_code}
          onChange={(e) => setForm({ ...form, language_code: e.target.value })}
        >
          {languages.map((l) => (
            <option key={l.code} value={l.code}>{l.label}</option>
          ))}
        </select>
      </div>

      <div className="flex gap-4">
        <button type="button" onClick={onBack} disabled={isLoading} className="w-1/3 bg-gray-100 text-gray-700 py-3 rounded-lg font-medium hover:bg-gray-200 transition-colors disabled:opacity-50">
          Back
        </button>
        <button type="button" onClick={onSubmit} disabled={isLoading} className="w-2/3 bg-blue-600 text-white py-3 rounded-lg font-medium hover:bg-blue-700 transition-colors flex items-center justify-center disabled:opacity-50">
          {isLoading ? (
            <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
          ) : 'Submit Report'}
        </button>
      </div>
    </div>
  );
}
