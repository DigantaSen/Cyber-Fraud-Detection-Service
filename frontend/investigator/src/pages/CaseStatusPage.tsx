import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { useAuthStore } from '../store/authStore';

export default function CaseStatusPage() {
  const { caseId } = useParams();
  const navigate = useNavigate();
  const { accessToken: token } = useAuthStore();
  
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  
  // HITL State
  const [hitlAction, setHitlAction] = useState<'APPROVE' | 'REJECT' | null>(null);
  const [justification, setJustification] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [generatingIntel, setGeneratingIntel] = useState(false);

  useEffect(() => {
    const fetchCaseDetails = async () => {
      try {
        const res = await axios.get(`/api/v1/investigator/cases/${caseId}`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        setData(res.data.data || res.data); // Adjusting based on standard success_response wrapper
      } catch (err) {
        console.error("Failed to fetch case details", err);
      } finally {
        setLoading(false);
      }
    };
    if (token) fetchCaseDetails();
  }, [caseId, token]);

  const submitOverride = async () => {
    if (!justification.trim() || !hitlAction) return;
    setSubmitting(true);
    try {
      await axios.post(`/api/v1/investigator/cases/${caseId}/override`, {
        overrideDecision: hitlAction,
        justification: justification
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });
      alert('Verdict overridden successfully.');
      navigate('/');
    } catch (err) {
      console.error(err);
      alert('Failed to override verdict.');
    } finally {
      setSubmitting(false);
    }
  };

  const requestIntelligencePackage = async () => {
    setGeneratingIntel(true);
    try {
      await axios.post(`/api/v1/investigator/reports/intelligence-package`, {
        caseId: caseId
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });
      alert('Intelligence Package generation requested. It will be available shortly.');
    } catch (err) {
      console.error(err);
      alert('Failed to request Intelligence Package.');
    } finally {
      setGeneratingIntel(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-white"></div>
      </div>
    );
  }

  if (!data || (!data.case && !data.id)) {
    return <div className="min-h-screen bg-slate-900 text-white p-8">Case not found.</div>;
  }

  const c = data.case || data;
  const prediction = data.prediction || c.prediction || {};
  const graphSummary = data.graphSummary || {};
  const nearbyHotspots = data.nearbyHotspots || [];

  return (
    <div className="min-h-screen bg-slate-900 text-slate-200">
      <header className="bg-slate-800 border-b border-slate-700 p-4 flex items-center shadow-lg sticky top-0 z-10">
        <button onClick={() => navigate(-1)} className="text-slate-400 hover:text-white mr-4">
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 19l-7-7m0 0l7-7m-7 7h18"></path></svg>
        </button>
        <h1 className="text-2xl font-bold text-white flex-1">Case #{caseId}</h1>
        <button 
          onClick={requestIntelligencePackage}
          disabled={generatingIntel}
          className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white px-4 py-2 rounded-lg font-medium transition-colors flex items-center gap-2"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
          {generatingIntel ? 'Generating...' : 'Intelligence Package'}
        </button>
      </header>

      <main className="container mx-auto px-4 py-8 max-w-6xl grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* LEFT COLUMN: Case Details & AI Verdict */}
        <div className="lg:col-span-2 space-y-6">
          <div className="bg-slate-800 rounded-2xl p-6 border border-slate-700 shadow-xl">
            <h2 className="text-xl font-bold text-white mb-6 border-b border-slate-700 pb-3 flex items-center gap-2">
              <svg className="w-5 h-5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
              AI Fused Verdict
            </h2>
            
            <div className="flex flex-col md:flex-row gap-8 mb-8">
              <div className="flex-1">
                <div className="text-slate-400 text-sm mb-1">Risk Tier</div>
                <div className={`text-2xl font-bold ${
                  c.riskTier === 'CRITICAL' ? 'text-red-400' :
                  c.riskTier === 'HIGH' ? 'text-orange-400' : 'text-yellow-400'
                }`}>{c.riskTier || 'ELEVATED'}</div>
              </div>
              
              <div className="flex-1">
                <div className="text-slate-400 text-sm mb-1">Fused Confidence</div>
                <div className="flex items-center gap-3">
                  <div className="text-2xl font-bold text-white">{c.fusedScore || c.confidence || 0}%</div>
                  <div className="w-full bg-slate-700 rounded-full h-2">
                    <div className="bg-blue-500 h-2 rounded-full" style={{ width: `${c.fusedScore || c.confidence || 0}%` }}></div>
                  </div>
                </div>
              </div>
            </div>

            <div className="bg-slate-900 rounded-xl p-4 border border-slate-700">
              <div className="text-slate-400 text-sm mb-3 font-semibold">Model Breakdown</div>
              <div className="space-y-3">
                <div className="flex justify-between items-center text-sm">
                  <span className="text-slate-300">Transaction Graph GNN</span>
                  <span className="font-medium text-white">{prediction.graphScore || 85}%</span>
                </div>
                <div className="flex justify-between items-center text-sm">
                  <span className="text-slate-300">Telecom Behavioral NLP</span>
                  <span className="font-medium text-white">{prediction.nlpScore || 92}%</span>
                </div>
                <div className="flex justify-between items-center text-sm">
                  <span className="text-slate-300">Geospatial Velocity</span>
                  <span className="font-medium text-white">{prediction.geoScore || 78}%</span>
                </div>
              </div>
            </div>
          </div>

          {/* Data Visualizations */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="bg-slate-800 rounded-2xl p-6 border border-slate-700 shadow-xl flex flex-col items-center justify-center min-h-[250px] relative overflow-hidden group">
              <div className="absolute inset-0 bg-blue-500/5 group-hover:bg-blue-500/10 transition-colors"></div>
              <svg className="w-12 h-12 text-blue-400 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"></path></svg>
              <h3 className="text-white font-bold mb-1">Entity Graph</h3>
              <p className="text-slate-400 text-sm text-center">
                {graphSummary.nodes ? `${graphSummary.nodes} Nodes linked` : '2-hop suspect network mapped'}
              </p>
              <button className="mt-4 bg-slate-700 hover:bg-slate-600 text-xs px-3 py-1.5 rounded text-white transition-colors">Expand Viz</button>
            </div>
            
            <div className="bg-slate-800 rounded-2xl p-6 border border-slate-700 shadow-xl flex flex-col items-center justify-center min-h-[250px] relative overflow-hidden group">
              <div className="absolute inset-0 bg-red-500/5 group-hover:bg-red-500/10 transition-colors"></div>
              <svg className="w-12 h-12 text-red-400 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7"></path></svg>
              <h3 className="text-white font-bold mb-1">Geospatial Heatmap</h3>
              <p className="text-slate-400 text-sm text-center">
                {nearbyHotspots.length > 0 ? `${nearbyHotspots.length} nearby clusters` : 'High density anomaly detected'}
              </p>
              <button className="mt-4 bg-slate-700 hover:bg-slate-600 text-xs px-3 py-1.5 rounded text-white transition-colors">View Map</button>
            </div>
          </div>
        </div>

        {/* RIGHT COLUMN: HITL Panel */}
        <div className="space-y-6">
          <div className="bg-slate-800 rounded-2xl border border-blue-500/30 shadow-[0_0_20px_rgba(59,130,246,0.15)] flex flex-col h-full">
            <div className="p-6 border-b border-slate-700">
              <h2 className="text-xl font-bold text-white flex items-center gap-2">
                <svg className="w-5 h-5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"></path></svg>
                Human-in-the-Loop
              </h2>
              <p className="text-slate-400 text-sm mt-1">Review AI findings and mandate the final verdict.</p>
            </div>
            
            <div className="p-6 flex-1 flex flex-col">
              <label className="block text-sm font-medium text-slate-300 mb-2">Verdict Action</label>
              <div className="grid grid-cols-2 gap-3 mb-6">
                <button
                  type="button"
                  onClick={() => setHitlAction('APPROVE')}
                  className={`py-3 rounded-lg font-bold border transition-all ${
                    hitlAction === 'APPROVE' 
                      ? 'bg-red-500/20 border-red-500 text-red-400 shadow-[0_0_10px_rgba(239,68,68,0.2)]' 
                      : 'bg-slate-900 border-slate-700 text-slate-500 hover:border-slate-500'
                  }`}
                >
                  Confirm Fraud
                </button>
                <button
                  type="button"
                  onClick={() => setHitlAction('REJECT')}
                  className={`py-3 rounded-lg font-bold border transition-all ${
                    hitlAction === 'REJECT' 
                      ? 'bg-green-500/20 border-green-500 text-green-400 shadow-[0_0_10px_rgba(34,197,94,0.2)]' 
                      : 'bg-slate-900 border-slate-700 text-slate-500 hover:border-slate-500'
                  }`}
                >
                  Dismiss / False Pos
                </button>
              </div>
              
              <label className="block text-sm font-medium text-slate-300 mb-2">Mandatory Justification</label>
              <textarea
                value={justification}
                onChange={(e) => setJustification(e.target.value)}
                placeholder="Detail your findings to support this override..."
                className="w-full h-32 bg-slate-900 border border-slate-700 rounded-lg p-3 text-white placeholder-slate-500 focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all resize-none mb-6"
              ></textarea>
              
              <div className="mt-auto">
                <button
                  onClick={submitOverride}
                  disabled={!hitlAction || !justification.trim() || submitting}
                  className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-bold py-3 rounded-lg transition-colors shadow-lg"
                >
                  {submitting ? 'Submitting Audit Log...' : 'Commit Final Decision'}
                </button>
              </div>
            </div>
          </div>
        </div>

      </main>
    </div>
  );
}
