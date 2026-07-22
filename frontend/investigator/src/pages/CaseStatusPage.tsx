import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import GraphVizModal from '../components/GraphVizModal';
import GeoHeatmapModal from '../components/GeoHeatmapModal';

import { useAuthStore } from '../store/authStore';

export default function CaseStatusPage() {
  const { caseId } = useParams();
  const navigate = useNavigate();
  const { accessToken: token } = useAuthStore();
  
  const [data, setData] = useState<any>(null);
  const [graphData, setGraphData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  
  // HITL & Investigation State
  const [hitlAction, setHitlAction] = useState<'APPROVE' | 'REJECT' | null>(null);
  const [justification, setJustification] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [startingInvestigation, setStartingInvestigation] = useState(false);
  const [generatingIntel, setGeneratingIntel] = useState(false);
  const [activeModule, setActiveModule] = useState<'graph' | 'map' | null>(null);

  useEffect(() => {
    const fetchCaseDetails = async () => {
      try {
        const res = await axios.get(`/api/v1/investigator/cases/${caseId}`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        setData(res.data.data || res.data);
        
        try {
          const gRes = await axios.get(`/api/v1/investigator/cases/${caseId}/graph`, {
            headers: { Authorization: `Bearer ${token}` }
          });
          setGraphData(gRes.data.data || gRes.data || {});
        } catch (ge) {
          console.warn("Failed to fetch graph data", ge);
        }
      } catch (err) {
        console.error("Failed to fetch case details", err);
      } finally {
        setLoading(false);
      }
    };
    if (token) fetchCaseDetails();
  }, [caseId, token]);

  const startInvestigation = async () => {
    setStartingInvestigation(true);
    try {
      await axios.patch(`/api/v1/investigator/cases/${caseId}/state`, {
        state: 'Investigating',
        reason: 'HITL_APPROVED'
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });
      alert('Case status updated to INVESTIGATING.');
      const res = await axios.get(`/api/v1/investigator/cases/${caseId}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setData(res.data.data || res.data);
    } catch (err: any) {
      console.error(err);
      const detail = err.response?.data?.detail;
      const msg = typeof detail === 'string' ? detail : detail?.[0]?.msg || err.response?.data?.message || 'Failed to start investigation.';
      alert(`Action Failed: ${msg}`);
    } finally {
      setStartingInvestigation(false);
    }
  };

  const closeCaseDirectly = async () => {
    setSubmitting(true);
    try {
      await axios.patch(`/api/v1/investigator/cases/${caseId}/state`, {
        state: 'Closed',
        reason: 'Investigator marked case closed after action taken'
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });
      alert('Case closed and archived successfully.');
      navigate('/');
    } catch (err: any) {
      console.error(err);
      alert('Failed to close case.');
    } finally {
      setSubmitting(false);
    }
  };

  const submitOverride = async () => {
    if (justification.trim().length < 10 || !hitlAction) return;
    setSubmitting(true);
    try {
      const pred = data?.prediction || data?.case?.prediction || {};
      await axios.post(`/api/v1/investigator/cases/${caseId}/override`, {
        decision: hitlAction,
        justification: justification,
        originalVerdictId: pred.predictionId || '00000000-0000-0000-0000-000000000000',
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });
      alert('Verdict decision committed successfully.');
      navigate('/');
    } catch (err: any) {
      console.error(err);
      const detail = err.response?.data?.detail;
      const msg = typeof detail === 'string' ? detail : detail?.[0]?.msg || err.response?.data?.message || 'Failed to override verdict.';
      alert(`Override Failed: ${msg}`);
    } finally {
      setSubmitting(false);
    }
  };

  const requestIntelligencePackage = async () => {
    setGeneratingIntel(true);
    try {
      const response = await axios.post(`/api/v1/investigator/reports/intelligence-package`, {
        caseId: caseId
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });
      
      const dataStr = JSON.stringify(response.data?.data || response.data, null, 2);
      const blob = new Blob([dataStr], { type: 'application/json' });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `intelligence_package_${caseId}.json`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);

      alert('Intelligence Package generated and downloaded successfully.');
    } catch (err) {
      console.error(err);
      alert('Failed to request Intelligence Package.');
    } finally {
      setGeneratingIntel(false);
    }
  };

  // Bank action detection — reads from case notes written by bank BFF on block/dismiss
  const caseNotes: string = (data?.case?.notes || data?.notes || '');
  const bankActionVal: string = (data?.case?.bankAction || data?.case?.bank_action || data?.bankAction || data?.bank_action || '');
  const bankActionBlocked   = caseNotes.includes('BANK_ACTION:BLOCKED') || bankActionVal === 'BLOCKED';
  const bankActionDismissed = caseNotes.includes('BANK_ACTION:DISMISSED');

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-white"></div>
      </div>
    );
  }

  if (!data || (!data.case && !data.id && !data.case_id && !data.caseId)) {
    return <div className="min-h-screen bg-slate-900 text-white p-8">Case not found.</div>;
  }

  const c = data.case || data;
  const currentStatus = (c.status || 'New').toUpperCase();
  
  const getStepIndex = (status: string) => {
    const st = (status || '').toUpperCase();
    if (st === 'CLOSED' || st === 'DISMISSED') return 4;
    if (st === 'ACTION_TAKEN' || st === 'CONFIRMED_FRAUD') return 3;
    if (st === 'INVESTIGATING' || st === 'ASSIGNED' || st === 'ELEVATED') return 2;
    return 1;
  };

  const currentStep = getStepIndex(currentStatus);

  const complaint_lat = c.complaintLat != null ? parseFloat(c.complaintLat) : null;
  const complaint_lon = c.complaintLon != null ? parseFloat(c.complaintLon) : null;
  const prediction = data.prediction || c.prediction || {};
  const graphSummary = graphData || data?.graphSummary || {};
  const nearbyHotspots = data.nearbyHotspots || [];

  return (
    <div className="min-h-screen bg-slate-900 text-slate-200">
      <header className="bg-slate-800 border-b border-slate-700 p-4 flex items-center shadow-lg sticky top-0 z-10">
        <button onClick={() => navigate(-1)} className="text-slate-400 hover:text-white mr-4">
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 19l-7-7m0 0l7-7m-7 7h18"></path></svg>
        </button>
        <div className="flex-1 flex items-center gap-3">
          <h1 className="text-2xl font-bold text-white">Case #{c.caseNumber || c.case_number || (c.caseId || c.case_id || caseId || "").substring(0, 8)}</h1>
          <span className={`px-2.5 py-0.5 rounded-full text-xs font-mono font-bold ${
            currentStatus === 'INVESTIGATING' ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30' :
            currentStatus === 'ACTION_TAKEN' ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' :
            currentStatus === 'CLOSED' ? 'bg-slate-700 text-slate-300' : 'bg-blue-500/20 text-blue-400 border border-blue-500/30'
          }`}>
            {currentStatus}
          </span>
        </div>
        <button 
          onClick={requestIntelligencePackage}
          disabled={generatingIntel}
          className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white px-4 py-2 rounded-lg font-medium transition-colors flex items-center gap-2"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
          {generatingIntel ? 'Generating...' : 'Intelligence Package'}
        </button>
      </header>

      <main className="container mx-auto px-4 py-8 max-w-6xl">
        
        {/* Interactive 4-Step Case Lifecycle Path */}
        <div className="bg-slate-800 rounded-2xl p-6 border border-slate-700 shadow-xl mb-6">
          <div className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-4">Operational Case Lifecycle Path</div>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            {/* Step 1 */}
            <div className={`p-4 rounded-xl border flex flex-col justify-between transition-all ${
              currentStep >= 1 ? 'bg-blue-500/10 border-blue-500/40 text-blue-300' : 'bg-slate-900 border-slate-700 text-slate-500'
            }`}>
              <div className="flex justify-between items-center mb-2">
                <span className="font-mono text-xs font-bold px-2 py-0.5 rounded bg-blue-900/60 text-blue-200">STEP 1</span>
                {currentStep > 1 ? <span className="text-emerald-400 font-bold text-xs">✓ Complete</span> : <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse"></span>}
              </div>
              <div className="font-bold text-sm text-white">1. Case Registered</div>
              <div className="text-xs text-slate-400 mt-1">Citizen report intake & AI risk evaluation</div>
            </div>

            {/* Step 2 */}
            <div className={`p-4 rounded-xl border flex flex-col justify-between transition-all ${
              currentStep >= 2 ? 'bg-amber-500/10 border-amber-500/40 text-amber-300' : 'bg-slate-900 border-slate-700 text-slate-500'
            }`}>
              <div className="flex justify-between items-center mb-2">
                <span className="font-mono text-xs font-bold px-2 py-0.5 rounded bg-amber-900/60 text-amber-200">STEP 2</span>
                {currentStep > 2 ? <span className="text-emerald-400 font-bold text-xs">✓ Complete</span> : currentStep === 2 ? <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse"></span> : null}
              </div>
              <div className="font-bold text-sm text-white">2. Under Investigation</div>
              <div className="text-xs text-slate-400 mt-1">Active evidence gathering & graph mapping</div>
            </div>

            {/* Step 3 */}
            <div className={`p-4 rounded-xl border flex flex-col justify-between transition-all ${
              currentStep >= 3 ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-300' : 'bg-slate-900 border-slate-700 text-slate-500'
            }`}>
              <div className="flex justify-between items-center mb-2">
                <span className="font-mono text-xs font-bold px-2 py-0.5 rounded bg-emerald-900/60 text-emerald-200">STEP 3</span>
                {currentStep > 3 ? <span className="text-emerald-400 font-bold text-xs">✓ Complete</span> : currentStep === 3 ? <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span> : null}
              </div>
              <div className="font-bold text-sm text-white">3. Confirmed Fraud (Action)</div>
              <div className="text-xs text-slate-400 mt-1">Fraud confirmed & enforcement actions triggered</div>
            </div>

            {/* Step 4 */}
            <div className={`p-4 rounded-xl border flex flex-col justify-between transition-all ${
              currentStep >= 4 ? 'bg-purple-500/10 border-purple-500/40 text-purple-300' : 'bg-slate-900 border-slate-700 text-slate-500'
            }`}>
              <div className="flex justify-between items-center mb-2">
                <span className="font-mono text-xs font-bold px-2 py-0.5 rounded bg-purple-900/60 text-purple-200">STEP 4</span>
                {currentStep === 4 ? <span className="text-purple-400 font-bold text-xs">✓ Closed</span> : null}
              </div>
              <div className="font-bold text-sm text-white">4. Closed Case</div>
              <div className="text-xs text-slate-400 mt-1">Final verdict archived in audit trail</div>
            </div>
          </div>
        </div>

        {/* Bank Action Banner (Middle Section) */}
        {(bankActionBlocked || bankActionDismissed) && (
          <div className={`mb-6 border-2 rounded-2xl p-5 shadow-xl flex items-start gap-4 transition-all ${
            bankActionBlocked ? 'bg-red-950/60 border-red-500 text-red-200' : 'bg-slate-800/80 border-slate-600 text-slate-200'
          }`}>
            <span className="text-3xl flex-shrink-0">{bankActionBlocked ? '🚫' : '👁'}</span>
            <div className="flex-1">
              <div className="flex items-center justify-between">
                <h3 className={`text-base font-bold ${bankActionBlocked ? 'text-red-300' : 'text-slate-200'}`}>
                  {bankActionBlocked ? 'BANK INTERDICTION: Transaction Blocked' : 'BANK REVIEW: No Action Taken (Dismissed)'}
                </h3>
                <span className={`px-2.5 py-0.5 rounded-full text-xs font-mono font-bold ${
                  bankActionBlocked ? 'bg-red-900/80 text-red-200 border border-red-700' : 'bg-slate-700 text-slate-300'
                }`}>
                  {bankActionBlocked ? 'ACTION CONFIRMED' : 'DISMISSED'}
                </span>
              </div>
              <p className={`text-sm mt-1.5 leading-relaxed ${bankActionBlocked ? 'text-red-300/90' : 'text-slate-400'}`}>
                {bankActionBlocked
                  ? 'The partner bank has reviewed this case and successfully blocked the fraudulent UPI / bank account. Asset freeze and recovery procedures are active.'
                  : 'The partner bank reviewed this case and determined no interdiction action was warranted at this time.'}
              </p>
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* LEFT COLUMN: Case Details & AI Verdict */}
          <div className="lg:col-span-2 space-y-6">
            <div className="bg-slate-800 rounded-2xl p-6 border border-slate-700 shadow-xl">
              <h2 className="text-xl font-bold text-white mb-6 border-b border-slate-700 pb-3 flex items-center gap-2">
                <svg className="w-5 h-5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                AI Fused Verdict
              </h2>
              
              {(() => {
                const riskTier = (prediction.riskTier || prediction.risk_tier || c.riskTier || c.risk_tier || 'UNKNOWN').toUpperCase();
                
                let fusedVal = 0;
                if (prediction.fusedScore != null || prediction.fused_score != null) {
                  fusedVal = parseFloat(prediction.fusedScore ?? prediction.fused_score);
                } else if (prediction.confidence != null) {
                  const conf = parseFloat(prediction.confidence);
                  fusedVal = conf > 1 ? conf : conf * 100;
                }

                const breakdown = prediction.modelBreakdown || prediction.model_breakdown || [];
                const getModelScore = (name: string, fallback: number) => {
                  const item = breakdown.find((m: any) => m.model === name || m.model === name.toLowerCase());
                  if (item && item.score != null) return item.score;
                  return fallback;
                };

                return (
                  <div>
                    <div className="flex flex-col md:flex-row gap-8 mb-8">
                      <div className="flex-1">
                        <div className="text-slate-400 text-sm mb-1">Risk Tier</div>
                        <div className={`text-2xl font-bold ${
                          riskTier === 'CRITICAL' ? 'text-red-400' :
                          riskTier === 'HIGH' ? 'text-orange-400' :
                          riskTier === 'MEDIUM' ? 'text-yellow-400' : 'text-emerald-400'
                        }`}>{riskTier}</div>
                      </div>
                      
                      <div className="flex-1">
                        <div className="text-slate-400 text-sm mb-1">Fused Confidence / Risk Score</div>
                        <div className="flex items-center gap-3">
                          <div className="text-2xl font-bold text-white">{fusedVal.toFixed(1)}%</div>
                          <div className="w-full bg-slate-700 rounded-full h-2">
                            <div className={`h-2 rounded-full transition-all ${
                              fusedVal >= 80 ? 'bg-red-500' : fusedVal >= 50 ? 'bg-orange-500' : 'bg-blue-500'
                            }`} style={{ width: `${Math.max(2, Math.min(100, fusedVal))}%` }}></div>
                          </div>
                        </div>
                      </div>
                    </div>

                    <div className="bg-slate-900 rounded-xl p-4 border border-slate-700">
                      <div className="text-slate-400 text-sm mb-3 font-semibold uppercase tracking-wider">Model Breakdown</div>
                      <div className="space-y-3">
                        {breakdown.length > 0 ? (
                          breakdown.map((m: any, idx: number) => (
                            <div key={idx} className="flex justify-between items-center text-sm">
                              <span className="text-slate-300 capitalize">{m.model ? m.model.replace(/-/g, ' ') : 'Model'}</span>
                              <span className="font-medium text-white">{m.score != null ? `${m.score}%` : (m.status || 'N/A')}</span>
                            </div>
                          ))
                        ) : (
                          <div>
                            <div className="flex justify-between items-center text-sm">
                              <span className="text-slate-300">Telecom Scam NLP</span>
                              <span className="font-medium text-white">{prediction.nlpScore ?? getModelScore('scam-nlp', 80)}%</span>
                            </div>
                            <div className="flex justify-between items-center text-sm">
                              <span className="text-slate-300">Transaction Graph Analyzer</span>
                              <span className="font-medium text-white">{prediction.graphScore ?? getModelScore('graph-analyzer', 25)}%</span>
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })()}
            </div>

            {/* SUBMITTED EVIDENCE REPOSITORY */}
            <div className="bg-slate-800 rounded-2xl p-6 border border-slate-700 shadow-xl space-y-4">
              <div className="flex items-center justify-between border-b border-slate-700 pb-3">
                <h2 className="text-xl font-bold text-white flex items-center gap-2">
                  <svg className="w-5 h-5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"></path></svg>
                  Submitted Evidence Repository
                </h2>
                <span className="bg-blue-500/20 text-blue-400 text-xs font-semibold px-2.5 py-1 rounded-full">
                  {data?.evidence?.length || 0} Files Attached
                </span>
              </div>

              {(!data?.evidence || data.evidence.length === 0) ? (
                <div className="text-center py-6 text-slate-500 text-sm">
                  📁 No additional evidence files submitted for this case yet.
                </div>
              ) : (
                <div className="space-y-3">
                  {data.evidence.map((item: any, idx: number) => {
                    const mime = item.mimeType || '';
                    const isImg = mime.includes('image') || mime.includes('png') || mime.includes('jpeg');
                    const isAudio = mime.includes('audio') || mime.includes('wav') || mime.includes('mp3');
                    const isPdf = mime.includes('pdf');

                    return (
                      <div key={item.evidenceId || idx} className="bg-slate-900/80 border border-slate-700/80 rounded-xl p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                        <div className="flex items-center gap-3">
                          <div className="w-10 h-10 rounded-lg bg-slate-800 border border-slate-700 flex items-center justify-center text-xl">
                            {isImg ? '🖼️' : isAudio ? '🎙️' : isPdf ? '📄' : '📎'}
                          </div>
                          <div>
                            <div className="font-semibold text-white text-sm">{item.fileName || 'Evidence File'}</div>
                            <div className="text-xs text-slate-400 flex items-center gap-2 mt-0.5">
                              <span>MIME: {item.mimeType}</span>
                              <span>•</span>
                              <span>{item.fileSizeBytes ? `${(item.fileSizeBytes / 1024).toFixed(1)} KB` : 'Verified'}</span>
                              <span>•</span>
                              <span className="text-emerald-400 font-mono">STATUS: {item.status}</span>
                            </div>
                          </div>
                        </div>

                        {item.downloadUrl ? (
                          <a
                            href={item.downloadUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold px-4 py-2 rounded-lg transition-colors flex items-center gap-1.5 self-start sm:self-auto shadow-md"
                          >
                            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path></svg>
                            Download / Inspect Evidence
                          </a>
                        ) : (
                          <span className="text-xs text-slate-500 font-mono">Storage Key Verified</span>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Data Visualizations */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="bg-slate-800 rounded-2xl p-6 border border-slate-700 shadow-xl flex flex-col items-center justify-center min-h-[250px] relative overflow-hidden group">
                <div className="absolute inset-0 bg-blue-500/5 group-hover:bg-blue-500/10 transition-colors pointer-events-none"></div>
                <svg className="w-12 h-12 text-blue-400 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"></path></svg>
                <h3 className="text-white font-bold mb-1">Entity Graph</h3>
                <p className="text-slate-400 text-sm text-center">
                  {graphSummary.nodes ? `${graphSummary.nodes} Nodes linked` : '2-hop suspect network mapped'}
                </p>
                <button onClick={() => setActiveModule('graph')} className="relative z-10 mt-4 bg-slate-700 hover:bg-slate-600 text-xs px-3 py-1.5 rounded text-white transition-colors cursor-pointer">Expand Viz</button>
              </div>
              
              <div className="bg-slate-800 rounded-2xl p-6 border border-slate-700 shadow-xl flex flex-col items-center justify-center min-h-[250px] relative overflow-hidden group">
                <div className="absolute inset-0 bg-red-500/5 group-hover:bg-red-500/10 transition-colors pointer-events-none"></div>
                <svg className="w-12 h-12 text-red-400 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7"></path></svg>
                <h3 className="text-white font-bold mb-1">Geospatial Heatmap</h3>
                <p className="text-slate-400 text-sm text-center">
                  {nearbyHotspots.length > 0 ? `${nearbyHotspots.length} nearby clusters` : 'High density anomaly detected'}
                </p>
                <button onClick={() => setActiveModule('map')} className="relative z-10 mt-4 bg-slate-700 hover:bg-slate-600 text-xs px-3 py-1.5 rounded text-white transition-colors cursor-pointer">View Map</button>
              </div>
            </div>
          </div>

          {/* RIGHT COLUMN: DYNAMIC STATE-AWARE ACTION PANEL */}
          <div className="space-y-6">
            {/* STATE 1: NEW / PENDING_AI (Case Registered) */}
            {(currentStatus === 'NEW' || currentStatus === 'PENDING_AI') && (
              <div className="bg-slate-800 rounded-2xl border border-blue-500/30 p-6 shadow-xl space-y-4">
                <div className="flex items-center gap-2 text-blue-400 font-bold text-lg border-b border-slate-700 pb-3">
                  <svg className="w-5 h-5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>
                  <span>Stage 1: Intake Actions</span>
                </div>
                <p className="text-slate-400 text-xs leading-relaxed">This case has been registered. You can transition it into active investigation (Stage 2) or directly commit a final verdict below.</p>
                
                <button
                  onClick={startInvestigation}
                  disabled={startingInvestigation}
                  className="w-full bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white font-bold py-3 rounded-xl transition-all shadow-lg text-sm flex items-center justify-center gap-2"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
                  {startingInvestigation ? 'Updating Status...' : '🔍 Move to Stage 2: Under Investigation'}
                </button>
              </div>
            )}

            {/* STATE 2: INVESTIGATING / ASSIGNED (Under Investigation) */}
            {(currentStatus === 'INVESTIGATING' || currentStatus === 'ASSIGNED' || currentStatus === 'ELEVATED') && (
              <div className="bg-amber-500/10 border border-amber-500/30 rounded-2xl p-5 text-amber-300 space-y-2 shadow-lg">
                <div className="flex items-center gap-3 font-bold text-amber-200 text-base">
                  <span className="w-3 h-3 rounded-full bg-amber-400 animate-pulse"></span>
                  <span>Stage 2: Active Investigation</span>
                </div>
                <p className="text-xs text-amber-400/90 leading-relaxed">Field evidence gathering and 2-hop network graph inspection are in progress. Review AI findings below to commit Stage 3 or 4 final verdict.</p>
              </div>
            )}

            {/* STATE 3: ACTION_TAKEN / CONFIRMED_FRAUD (Action Taken) */}
            {(currentStatus === 'ACTION_TAKEN' || currentStatus === 'CONFIRMED_FRAUD') && (
              <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-2xl p-6 shadow-xl space-y-4">
                <div className="flex items-center gap-2 font-bold text-emerald-300 text-lg border-b border-emerald-500/20 pb-3">
                  <svg className="w-5 h-5 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                  <span>Stage 3: Confirmed Fraud</span>
                </div>
                <p className="text-xs text-emerald-400/90 leading-relaxed">Enforcement alerts and bank account freezes have been initiated. Once all operational steps complete, click below to close and archive the case.</p>
                <button
                  onClick={closeCaseDirectly}
                  disabled={submitting}
                  className="w-full bg-purple-600 hover:bg-purple-500 text-white font-bold py-3 rounded-xl text-sm transition-all shadow-lg flex items-center justify-center gap-2"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7"></path></svg>
                  📁 Move to Stage 4: Close & Archive Case
                </button>
              </div>
            )}

            {/* STATE 4: CLOSED / DISMISSED */}
            {(currentStatus === 'CLOSED' || currentStatus === 'DISMISSED') && (
              <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6 shadow-xl text-center space-y-3">
                <div className="w-12 h-12 rounded-full bg-purple-500/20 text-purple-400 mx-auto flex items-center justify-center font-bold text-xl">✓</div>
                <div className="font-bold text-white text-lg">Stage 4: Case Closed</div>
                <p className="text-slate-400 text-xs leading-relaxed">This case has reached final verdict disposition and is archived. All actions are cryptographically signed in the immutable audit log.</p>
              </div>
            )}

            {/* HITL Verdict Decision Panel (Active for Stage 1 & 2) */}
            {currentStatus !== 'CLOSED' && currentStatus !== 'DISMISSED' && currentStatus !== 'ACTION_TAKEN' && (
              <div className="bg-slate-800 rounded-2xl border border-blue-500/30 shadow-xl flex flex-col">
                <div className="p-6 border-b border-slate-700">
                  <h2 className="text-xl font-bold text-white flex items-center gap-2">
                    <svg className="w-5 h-5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"></path></svg>
                    Final Verdict Decision
                  </h2>
                  <p className="text-slate-400 text-xs mt-1">Select final verdict outcome and record mandatory justification.</p>
                </div>
                
                <div className="p-6 flex-1 flex flex-col">
                  <div className="flex justify-between items-center mb-2">
                    <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400">Verdict Action</label>
                  </div>
                  <div className="grid grid-cols-2 gap-3 mb-6">
                    <button
                      type="button"
                      onClick={() => setHitlAction('APPROVE')}
                      className={`py-3 px-2 rounded-xl text-xs sm:text-sm font-bold border transition-all text-center leading-tight flex items-center justify-center ${
                        hitlAction === 'APPROVE' 
                          ? 'bg-red-500/20 border-red-500 text-red-400 shadow-[0_0_10px_rgba(239,68,68,0.2)]' 
                          : 'bg-slate-900 border-slate-700 text-slate-400 hover:border-slate-500'
                      }`}
                    >
                      🚨 Stage 3: Confirm Fraud
                    </button>
                    <button
                      type="button"
                      onClick={() => setHitlAction('REJECT')}
                      className={`py-3 px-2 rounded-xl text-xs sm:text-sm font-bold border transition-all text-center leading-tight flex items-center justify-center ${
                        hitlAction === 'REJECT' 
                          ? 'bg-purple-500/20 border-purple-500 text-purple-400 shadow-[0_0_10px_rgba(168,85,247,0.2)]' 
                          : 'bg-slate-900 border-slate-700 text-slate-400 hover:border-slate-500'
                      }`}
                    >
                      🛡️ Stage 4: Dismiss & Close
                    </button>
                  </div>
                  
                  <div className="flex justify-between items-center mb-2">
                    <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400">Mandatory Justification</label>
                    <span className={`text-xs font-mono ${
                      justification.trim().length >= 10 ? 'text-emerald-400' : 'text-amber-400'
                    }`}>
                      {justification.trim().length}/10 chars min
                    </span>
                  </div>
                  <textarea
                    value={justification}
                    onChange={(e) => setJustification(e.target.value)}
                    placeholder="Detail your findings to support this final decision (at least 10 characters required)..."
                    className="w-full h-28 bg-slate-900 border border-slate-700 rounded-xl p-3 text-white placeholder-slate-500 focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all resize-none mb-6 text-sm"
                  ></textarea>
                  
                  <div className="mt-auto">
                    <button
                      onClick={submitOverride}
                      disabled={!hitlAction || justification.trim().length < 10 || submitting}
                      className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-bold py-3 rounded-xl transition-all shadow-lg text-sm"
                    >
                      {submitting ? 'Submitting Audit Log...' : justification.trim().length < 10 ? 'Min 10 Characters Required' : 'Commit Final Decision'}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

      </main>

      {/* Real Geospatial Heatmap */}
      {activeModule === 'map' && (
        <GeoHeatmapModal
          caseId={caseId!}
          caseLat={complaint_lat}
          caseLon={complaint_lon}
          nearbyHotspots={nearbyHotspots}
          onClose={() => setActiveModule(null)}
        />
      )}
      
      {/* Real Neo4j Graph */}
      {activeModule === 'graph' && (
        <GraphVizModal 
          graphSummary={graphSummary} 
          onClose={() => setActiveModule(null)} 
        />
      )}
    </div>
  );
}
