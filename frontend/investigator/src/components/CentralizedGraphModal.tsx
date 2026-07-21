import { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { useAuthStore } from '../store/authStore';

interface GraphNode {
  id: string;
  type?: string;
  fraudScore?: number;
  x: number;
  y: number;
}

interface GraphLink {
  source: string;
  target: string;
  label?: string;
}

interface CentralizedGraphModalProps {
  onClose: () => void;
}

function nodeConfig(node: GraphNode) {
  const t = (node.type || '').toUpperCase();
  if (t === 'PHONE') return { color: '#f97316', stroke: '#ea580c', symbol: '📱', label: 'SUSPECT PHONE' };
  if (t === 'CASE') return { color: '#ef4444', stroke: '#dc2626', symbol: '📋', label: 'CASE' };
  if (t === 'BANKACCOUNT') return { color: '#10b981', stroke: '#059669', symbol: '🏦', label: 'BANK / UPI ACCT' };
  return { color: '#a78bfa', stroke: '#7c3aed', symbol: '👤', label: 'VICTIM / ENTITY' };
}

function edgeColor(label: string | undefined) {
  const l = (label || '').toUpperCase();
  if (l === 'LINKED_TO') return '#ef4444';
  if (l === 'HAS_ACCOUNT') return '#10b981';
  if (l === 'REPORTED') return '#a78bfa';
  return '#64748b';
}

export default function CentralizedGraphModal({ onClose }: CentralizedGraphModalProps) {
  const { accessToken: token } = useAuthStore();
  const [loading, setLoading] = useState(true);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [links, setLinks] = useState<GraphLink[]>([]);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);

  // Zoom & Pan state
  const [zoom, setZoom] = useState(1.0);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const isDragging = useRef(false);
  const dragStart = useRef({ x: 0, y: 0 });

  const W = 1000;
  const H = 650;

  useEffect(() => {
    const fetchGlobalGraph = async () => {
      try {
        const res = await axios.get('/api/v1/investigator/graph/global', {
          headers: { Authorization: `Bearer ${token}` }
        });
        const gData = res.data?.data || {};
        const rawNodes = gData.nodes || [];
        const rawEdges = gData.edges || [];

        // Force Simulation Positioning
        const processedNodes: GraphNode[] = rawNodes.map((n: any, idx: number) => {
          const angle = (idx / Math.max(1, rawNodes.length)) * 2 * Math.PI;
          const radius = 140 + (idx % 3) * 85;
          return {
            id: n.id,
            type: n.type,
            fraudScore: n.fraudScore || 0,
            x: W / 2 + Math.cos(angle) * radius,
            y: H / 2 + Math.sin(angle) * radius
          };
        });

        const processedLinks: GraphLink[] = rawEdges.map((e: any) => ({
          source: e.from,
          target: e.to,
          label: e.relation
        }));

        setNodes(processedNodes);
        setLinks(processedLinks);
      } catch (err) {
        console.error("Failed to load global syndicate graph", err);
      } finally {
        setLoading(false);
      }
    };
    if (token) fetchGlobalGraph();
  }, [token]);

  const nodeMap = new Map<string, GraphNode>(nodes.map(n => [n.id, n]));

  // Connected edges & neighbors for selected node
  const selectedNodeLinks = selectedNode ? links.filter(l => l.source === selectedNode.id || l.target === selectedNode.id) : [];
  const connectedNodeIds = new Set<string>();
  if (selectedNode) {
    connectedNodeIds.add(selectedNode.id);
    selectedNodeLinks.forEach(l => {
      connectedNodeIds.add(l.source);
      connectedNodeIds.add(l.target);
    });
  }

  // Pan controls
  const handleMouseDown = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).tagName === 'svg' || (e.target as HTMLElement).tagName === 'rect') {
      isDragging.current = true;
      dragStart.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
    }
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (isDragging.current) {
      setPan({
        x: e.clientX - dragStart.current.x,
        y: e.clientY - dragStart.current.y
      });
    }
  };

  const handleMouseUp = () => {
    isDragging.current = false;
  };

  const zoomIn = () => setZoom(z => Math.min(3.0, z + 0.25));
  const zoomOut = () => setZoom(z => Math.max(0.4, z - 0.25));
  const resetZoom = () => { setZoom(1.0); setPan({ x: 0, y: 0 }); };

  return (
    <div className="fixed inset-0 bg-slate-950/85 backdrop-blur-md z-50 flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-6xl shadow-2xl overflow-hidden flex flex-col max-h-[92vh]">
        
        {/* Modal Header */}
        <div className="bg-slate-800 p-4 border-b border-slate-700 flex justify-between items-center">
          <div className="flex items-center gap-3">
            <span className="text-2xl">🕸️</span>
            <div>
              <h2 className="text-lg font-bold text-white">Centralized Syndicate Fraud Network</h2>
              <p className="text-xs text-slate-400">Master topology: {nodes.length} entities & {links.length} relationships mapped in Neo4j</p>
            </div>
          </div>
          
          <button onClick={onClose} className="text-slate-400 hover:text-white bg-slate-700 hover:bg-slate-600 rounded-lg px-3.5 py-1.5 text-xs font-bold transition-colors">
            Close ✕
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-4 flex-1 flex flex-col md:flex-row gap-4 relative overflow-hidden">
          {loading ? (
            <div className="flex flex-col items-center justify-center h-[550px] w-full text-slate-400">
              <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-500 mb-3"></div>
              <span>Building Master Syndicate Topology...</span>
            </div>
          ) : (
            <>
              {/* Interactive SVG Canvas */}
              <div
                className="flex-1 bg-slate-950 rounded-xl border border-slate-800 relative overflow-hidden select-none"
                onMouseDown={handleMouseDown}
                onMouseMove={handleMouseMove}
                onMouseUp={handleMouseUp}
              >
                {/* Floating Zoom Controls */}
                <div className="absolute top-4 left-4 z-20 bg-slate-900/90 border border-slate-700 p-1.5 rounded-xl flex items-center gap-1.5 shadow-lg">
                  <button onClick={zoomIn} title="Zoom In" className="bg-slate-800 hover:bg-slate-700 text-white w-8 h-8 rounded-lg font-bold text-sm flex items-center justify-center transition-colors">
                    ＋
                  </button>
                  <button onClick={zoomOut} title="Zoom Out" className="bg-slate-800 hover:bg-slate-700 text-white w-8 h-8 rounded-lg font-bold text-sm flex items-center justify-center transition-colors">
                    －
                  </button>
                  <button onClick={resetZoom} title="Reset Zoom" className="bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white px-2.5 h-8 rounded-lg text-xs font-semibold transition-colors">
                    Reset ({(zoom * 100).toFixed(0)}%)
                  </button>
                </div>

                <svg
                  width="100%"
                  height="600"
                  viewBox={`0 0 ${W} ${H}`}
                  onClick={() => setSelectedNode(null)}
                  className="w-full h-[600px] cursor-grab active:cursor-grabbing"
                >
                  <g transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`}>
                    {/* Render Links */}
                    {links.map((link, idx) => {
                      const s = nodeMap.get(link.source);
                      const t = nodeMap.get(link.target);
                      if (!s || !t) return null;

                      const isHighlighted = selectedNode && (link.source === selectedNode.id || link.target === selectedNode.id);
                      const dimmed = selectedNode && !isHighlighted;
                      const mx = (s.x + t.x) / 2;
                      const my = (s.y + t.y) / 2;

                      return (
                        <g key={idx} style={{ opacity: dimmed ? 0.2 : 1.0, transition: 'opacity 0.2s' }}>
                          <line
                            x1={s.x}
                            y1={s.y}
                            x2={t.x}
                            y2={t.y}
                            stroke={isHighlighted ? '#f59e0b' : edgeColor(link.label)}
                            strokeWidth={isHighlighted ? 3 : 1.5}
                            strokeDasharray={link.label === 'LINKED_TO' ? '4 2' : 'none'}
                          />
                          <text
                            x={mx}
                            y={my - 4}
                            fill={isHighlighted ? '#fde047' : '#94a3b8'}
                            fontSize="9"
                            fontFamily="monospace"
                            textAnchor="middle"
                          >
                            {link.label || ''}
                          </text>
                        </g>
                      );
                    })}

                    {/* Render Nodes */}
                    {nodes.map(node => {
                      const cfg = nodeConfig(node);
                      const isSelected = selectedNode?.id === node.id;
                      const isConnected = connectedNodeIds.has(node.id);
                      const dimmed = selectedNode && !isConnected;

                      return (
                        <g
                          key={node.id}
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedNode(prev => prev?.id === node.id ? null : node);
                          }}
                          className="cursor-pointer group"
                          style={{ opacity: dimmed ? 0.25 : 1.0, transition: 'all 0.2s' }}
                        >
                          {/* Circle Outer Glow */}
                          <circle
                            cx={node.x}
                            cy={node.y}
                            r={isSelected ? 17 : 13}
                            fill={cfg.color}
                            stroke={isSelected ? '#ffffff' : cfg.stroke}
                            strokeWidth={isSelected ? 3.5 : 1.5}
                            className="group-hover:stroke-white group-hover:stroke-[3px] transition-all"
                          />
                          
                          {/* Symbol Icon */}
                          <text
                            x={node.x}
                            y={node.y + 1}
                            fontSize="11"
                            textAnchor="middle"
                            dominantBaseline="central"
                            className="pointer-events-none"
                          >
                            {cfg.symbol}
                          </text>

                          {/* ID Badge Label */}
                          <text
                            x={node.x}
                            y={node.y + 22}
                            fill={isSelected ? '#ffffff' : '#cbd5e1'}
                            fontSize={isSelected ? '11' : '10'}
                            fontWeight={isSelected ? 'bold' : 'normal'}
                            textAnchor="middle"
                            className="pointer-events-none"
                          >
                            {node.id.length > 14 ? node.id.substring(0, 12) + '...' : node.id}
                          </text>
                        </g>
                      );
                    })}
                  </g>
                </svg>
              </div>

              {/* Sidebar Inspector Panel */}
              <div className="w-full md:w-80 bg-slate-800 rounded-xl p-4 border border-slate-700 space-y-4 flex flex-col">
                <h3 className="text-xs font-bold text-white uppercase tracking-wider border-b border-slate-700 pb-2">
                  Entity Linkage Inspector
                </h3>

                {selectedNode ? (
                  <div className="space-y-4 flex-1 overflow-y-auto pr-1">
                    <div className="bg-slate-900 rounded-xl p-3.5 border border-slate-700 space-y-2">
                      <div className="flex justify-between items-center text-xs text-slate-400 font-semibold uppercase">
                        <span>Selected Entity</span>
                        <button
                          onClick={() => setSelectedNode(null)}
                          className="text-amber-400 hover:text-amber-300 hover:underline text-[10px] lowercase"
                        >
                          (clear selection ✕)
                        </button>
                      </div>
                      <div className="font-mono text-sm text-white font-bold break-all">{selectedNode.id}</div>
                      <div className="flex justify-between items-center pt-1 text-xs">
                        <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-slate-800 text-slate-300 border border-slate-700">
                          {selectedNode.type}
                        </span>
                        {selectedNode.fraudScore != null && selectedNode.fraudScore > 0 && (
                          <span className="text-amber-400 font-bold">Fraud Score: {selectedNode.fraudScore}%</span>
                        )}
                      </div>
                    </div>

                    <div>
                      <div className="text-xs font-bold text-slate-300 mb-2">Connected Linkages ({selectedNodeLinks.length})</div>
                      {selectedNodeLinks.length > 0 ? (
                        <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
                          {selectedNodeLinks.map((l, idx) => {
                            const otherId = l.source === selectedNode.id ? l.target : l.source;
                            const otherNode = nodeMap.get(otherId);
                            return (
                              <div
                                key={idx}
                                onClick={() => otherNode && setSelectedNode(prev => prev?.id === otherNode.id ? null : otherNode)}
                                className="bg-slate-900 hover:bg-slate-800 p-2.5 rounded-lg border border-slate-700 text-xs cursor-pointer transition-colors"
                              >
                                <div className="flex justify-between items-center mb-1">
                                  <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-blue-900/60 text-blue-300 font-bold">
                                    {l.label || 'LINKED'}
                                  </span>
                                  {otherNode && (
                                    <span className="text-[10px] text-slate-400 uppercase">{otherNode.type}</span>
                                  )}
                                </div>
                                <div className="font-mono text-slate-200 text-[11px] truncate">{otherId}</div>
                              </div>
                            );
                          })}
                        </div>
                      ) : (
                        <div className="text-slate-500 text-xs italic">No direct connections found.</div>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="space-y-4 flex-1 overflow-y-auto pr-1">
                    <div className="text-slate-400 text-xs leading-relaxed bg-slate-900/60 p-3 rounded-lg border border-slate-700">
                      Click any entity node on the graph (or any entity in the list below) to reveal its connected phone numbers, bank accounts, and case relationships.
                    </div>

                    <div className="text-xs font-bold text-slate-300">All Entities ({nodes.length})</div>
                    <div className="space-y-1.5 max-h-64 overflow-y-auto pr-1">
                      {nodes.map(n => (
                        <div
                          key={n.id}
                          onClick={() => setSelectedNode(n)}
                          className="bg-slate-900 hover:bg-slate-700/60 p-2 rounded-lg border border-slate-800 flex justify-between items-center text-xs cursor-pointer transition-colors"
                        >
                          <span className="font-mono text-slate-200 text-[11px] truncate max-w-[170px]">{n.id}</span>
                          <span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 font-bold">{n.type}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
