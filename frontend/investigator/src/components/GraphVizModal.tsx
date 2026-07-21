import { useRef, useEffect, useState, useCallback } from 'react';

interface GraphNode {
  id: string;
  type?: string;      // PHONE | CASE | BANKACCOUNT | UNKNOWN
  isAnchor?: boolean;
  fraudScore?: number;
  isVictim?: boolean;
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
}

interface GraphLink {
  source: string;
  target: string;
  label?: string;
}

interface GraphVizModalProps {
  graphSummary: any;
  onClose: () => void;
}

// Node appearance by type
function nodeConfig(node: GraphNode) {
  if (node.isAnchor) return { color: '#3b82f6', symbol: '📱', label: 'PHONE (ANCHOR)' };
  const t = (node.type || '').toUpperCase();
  if (t === 'PHONE') {
    if (node.isVictim) return { color: '#a78bfa', symbol: '👤', label: 'VICTIM' };
    return { color: '#f97316', symbol: '📱', label: 'PHONE' };
  }
  if (t === 'CASE')        return { color: '#ef4444', symbol: '📋', label: 'CASE' };
  if (t === 'BANKACCOUNT') return { color: '#10b981', symbol: '🏦', label: 'BANK ACCT' };
  return { color: '#94a3b8', symbol: '?', label: t || 'ENTITY' };
}

function edgeColor(label: string | undefined) {
  const l = (label || '').toUpperCase();
  if (l === 'LINKED_TO')    return 'rgba(239,68,68,0.6)';
  if (l === 'HAS_ACCOUNT')  return 'rgba(16,185,129,0.7)';
  if (l === 'REPORTED')     return 'rgba(167,139,250,0.7)';
  if (l === 'CALLED')       return 'rgba(251,191,36,0.7)';
  return 'rgba(148,163,184,0.45)';
}

function riskColor(score: number | undefined) {
  if (!score) return '#94a3b8';
  if (score >= 80) return '#ef4444';
  if (score >= 50) return '#f59e0b';
  return '#10b981';
}

export default function GraphVizModal({ graphSummary, onClose }: GraphVizModalProps) {
  const animRef = useRef<number>(0);

  // Build nodes from real data
  const rawNodes: GraphNode[] = (() => {
    const ns: GraphNode[] = [];
    if (graphSummary?.anchor) {
      ns.push({ ...graphSummary.anchor, isAnchor: true });
    }
    for (const n of (graphSummary?.nodes || [])) {
      if (!ns.find((x) => x.id === n.id)) ns.push(n);
    }
    if (ns.length === 0) {
      // Show a placeholder if truly no data
      return [{ id: 'No graph data', isAnchor: true }];
    }
    return ns;
  })();

  const rawLinks: GraphLink[] = (graphSummary?.edges || []).map((e: any) => ({
    source: e.from,
    target: e.to,
    label: e.relation,
  }));

  const W = 900, H = 540;
  const cx = W / 2, cy = H / 2;
  const radius = Math.min(W, H) * 0.35;

  const initNodes = (): GraphNode[] => rawNodes.map((n, i) => {
    if (n.isAnchor) return { ...n, x: cx, y: cy, vx: 0, vy: 0 };
    const angle = (2 * Math.PI * i) / rawNodes.length;
    return { ...n, x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle), vx: 0, vy: 0 };
  });

  const [nodes, setNodes] = useState<GraphNode[]>(initNodes);
  const [hovered, setHovered] = useState<string | null>(null);

  const nodesRef = useRef<GraphNode[]>(nodes);
  nodesRef.current = nodes;

  const runForce = useCallback(() => {
    const ns = nodesRef.current.map(n => ({ ...n }));
    const alpha = 0.06;
    const repulsion = 5000;
    const linkStrength = 0.10;
    const linkDist = 160;
    const damping = 0.82;

    for (let i = 0; i < ns.length; i++) {
      for (let j = i + 1; j < ns.length; j++) {
        const dx = (ns[j].x ?? 0) - (ns[i].x ?? 0);
        const dy = (ns[j].y ?? 0) - (ns[i].y ?? 0);
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const force = (repulsion / (dist * dist)) * alpha;
        ns[i].vx = (ns[i].vx ?? 0) - (dx / dist) * force;
        ns[i].vy = (ns[i].vy ?? 0) - (dy / dist) * force;
        ns[j].vx = (ns[j].vx ?? 0) + (dx / dist) * force;
        ns[j].vy = (ns[j].vy ?? 0) + (dy / dist) * force;
      }
    }

    for (const link of rawLinks) {
      const src = ns.find(n => n.id === link.source);
      const tgt = ns.find(n => n.id === link.target);
      if (!src || !tgt) continue;
      const dx = (tgt.x ?? 0) - (src.x ?? 0);
      const dy = (tgt.y ?? 0) - (src.y ?? 0);
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const force = (dist - linkDist) * linkStrength * alpha;
      src.vx = (src.vx ?? 0) + (dx / dist) * force;
      src.vy = (src.vy ?? 0) + (dy / dist) * force;
      tgt.vx = (tgt.vx ?? 0) - (dx / dist) * force;
      tgt.vy = (tgt.vy ?? 0) - (dy / dist) * force;
    }

    for (const n of ns) {
      if (n.isAnchor) { n.x = cx; n.y = cy; continue; }
      n.vx = (n.vx ?? 0) + (cx - (n.x ?? 0)) * 0.004 * alpha;
      n.vy = (n.vy ?? 0) + (cy - (n.y ?? 0)) * 0.004 * alpha;
      n.vx = (n.vx ?? 0) * damping;
      n.vy = (n.vy ?? 0) * damping;
      n.x = Math.max(40, Math.min(W - 40, (n.x ?? 0) + (n.vx ?? 0)));
      n.y = Math.max(40, Math.min(H - 40, (n.y ?? 0) + (n.vy ?? 0)));
    }

    setNodes(ns);
    animRef.current = requestAnimationFrame(runForce);
  }, []); // eslint-disable-line

  useEffect(() => {
    animRef.current = requestAnimationFrame(runForce);
    return () => cancelAnimationFrame(animRef.current);
  }, [runForce]);

  const nodeMap = Object.fromEntries(nodes.map(n => [n.id, n]));

  // Stats
  const nodeTypeCount: Record<string, number> = {};
  for (const n of rawNodes) {
    const t = n.isAnchor ? 'PHONE (ANCHOR)' : (n.type || 'UNKNOWN').toUpperCase();
    nodeTypeCount[t] = (nodeTypeCount[t] || 0) + 1;
  }

  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-md z-[60] flex items-center justify-center p-4">
      <div
        className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-5xl shadow-2xl flex flex-col overflow-hidden"
        style={{ height: '90vh' }}
      >
        {/* Header */}
        <div className="p-4 border-b border-slate-800 flex justify-between items-center flex-shrink-0">
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <svg className="w-5 h-5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
            </svg>
            Entity Graph — {rawNodes.length} nodes · {rawLinks.length} edges
          </h2>
          <div className="flex items-center gap-4">
            {/* Legend */}
            <div className="flex items-center gap-3 text-xs text-slate-400">
              <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-blue-500 inline-block" /> Anchor Phone</span>
              <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-orange-500 inline-block" /> Phone</span>
              <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-red-500 inline-block" /> Case</span>
              <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-emerald-500 inline-block" /> Bank Acct</span>
              <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-violet-400 inline-block" /> Victim</span>
            </div>
            <button onClick={onClose} className="text-slate-400 hover:text-white bg-slate-800 p-2 rounded-lg transition-colors">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* SVG Canvas */}
        <div className="flex-1 bg-slate-950 overflow-hidden relative">
          <svg width="100%" height="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }}>
            <defs>
              <marker id="arrow-red" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                <path d="M0,0 L0,6 L6,3 z" fill="rgba(239,68,68,0.6)" />
              </marker>
              <marker id="arrow-green" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                <path d="M0,0 L0,6 L6,3 z" fill="rgba(16,185,129,0.7)" />
              </marker>
              <marker id="arrow-violet" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                <path d="M0,0 L0,6 L6,3 z" fill="rgba(167,139,250,0.7)" />
              </marker>
              <marker id="arrow-default" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                <path d="M0,0 L0,6 L6,3 z" fill="rgba(148,163,184,0.45)" />
              </marker>
            </defs>

            {/* Edges */}
            {rawLinks.map((link, i) => {
              const src = nodeMap[link.source];
              const tgt = nodeMap[link.target];
              if (!src || !tgt) return null;
              const mx = ((src.x ?? 0) + (tgt.x ?? 0)) / 2;
              const my = ((src.y ?? 0) + (tgt.y ?? 0)) / 2;
              const color = edgeColor(link.label);
              const l = (link.label || '').toUpperCase();
              const markerId = l === 'LINKED_TO' ? 'arrow-red'
                : l === 'HAS_ACCOUNT' ? 'arrow-green'
                : l === 'REPORTED' ? 'arrow-violet'
                : 'arrow-default';
              return (
                <g key={i}>
                  <line
                    x1={src.x} y1={src.y}
                    x2={tgt.x} y2={tgt.y}
                    stroke={color}
                    strokeWidth="1.8"
                    markerEnd={`url(#${markerId})`}
                    strokeDasharray={l === 'REPORTED' ? '5,3' : undefined}
                  />
                  <text x={mx} y={my - 5} textAnchor="middle" fontSize="8" fill={color} fontFamily="monospace" opacity={0.9}>
                    {link.label}
                  </text>
                </g>
              );
            })}

            {/* Nodes */}
            {nodes.map((node) => {
              const cfg = nodeConfig(node);
              const isH = hovered === node.id;
              const r = node.isAnchor ? 20 : 14;
              const score = node.fraudScore;
              const ringColor = riskColor(score);
              // Truncate label for display
              const displayId = node.id.length > 20 ? node.id.slice(0, 20) + '…' : node.id;
              return (
                <g
                  key={node.id}
                  transform={`translate(${node.x ?? 0},${node.y ?? 0})`}
                  style={{ cursor: 'pointer' }}
                  onMouseEnter={() => setHovered(node.id)}
                  onMouseLeave={() => setHovered(null)}
                >
                  {/* Outer risk ring */}
                  {score !== undefined && (
                    <circle r={r + 4} fill="none" stroke={ringColor} strokeWidth="2" opacity={0.5} />
                  )}
                  {/* Glow */}
                  <circle r={r + 8} fill={cfg.color} opacity={isH ? 0.18 : 0.06} />
                  {/* Node circle */}
                  <circle r={r} fill={cfg.color} stroke={isH ? 'white' : 'rgba(255,255,255,0.15)'} strokeWidth={isH ? 2 : 1} opacity={0.92} />
                  {/* Type label tag above node */}
                  <text y={-r - 6} textAnchor="middle" fontSize="8" fill={cfg.color} fontFamily="monospace" opacity={0.85}>
                    [{cfg.label}]
                  </text>
                  {/* Node ID below */}
                  <text y={r + 14} textAnchor="middle" fontSize="10" fill="#cbd5e1" fontFamily="ui-sans-serif, sans-serif">
                    {displayId}
                  </text>
                  {/* Fraud score */}
                  {score !== undefined && (
                    <text y={r + 25} textAnchor="middle" fontSize="8" fill={ringColor} fontFamily="monospace">
                      ⚠ {score.toFixed ? score.toFixed(1) : score}% risk
                    </text>
                  )}
                  {/* Full ID tooltip on hover */}
                  {isH && (
                    <g>
                      <rect x={-100} y={-r - 44} width={200} height={28} rx={5} fill="#0f172a" stroke="#475569" strokeWidth={1} />
                      <text x={0} y={-r - 26} textAnchor="middle" fontSize="10" fill="white" fontFamily="ui-sans-serif">
                        {node.id}
                      </text>
                    </g>
                  )}
                </g>
              );
            })}
          </svg>

          {/* Stats overlay */}
          <div className="absolute bottom-3 left-3 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-400 backdrop-blur-sm">
            {Object.entries(nodeTypeCount).map(([t, c]) => (
              <div key={t}>{t}: {c}</div>
            ))}
            <div className="mt-1 border-t border-slate-700 pt-1">{rawLinks.length} relationships</div>
          </div>
        </div>
      </div>
    </div>
  );
}
