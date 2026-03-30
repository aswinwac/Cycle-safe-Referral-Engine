import { useState, useEffect, useRef } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import type { ForceGraphMethods } from 'react-force-graph-2d';
import { Search, ZoomIn, ZoomOut, Maximize } from 'lucide-react';

export function GraphView() {
  const fgRef = useRef<ForceGraphMethods>(null);
  const [data, setData] = useState<any>({ nodes: [], links: [] });
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const containerRef = useRef<HTMLDivElement>(null);
  const [searchId, setSearchId] = useState('');

  useEffect(() => {
    if (containerRef.current) {
      setDimensions({
        width: containerRef.current.clientWidth,
        height: containerRef.current.clientHeight
      });
    }
    
    const handleResize = () => {
      if (containerRef.current) {
        setDimensions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight
        });
      }
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const handleSearch = () => {
    if(!searchId) return;
    fetch(`/api/v1/dashboard/graph/${searchId}`)
        .then(r => r.json())
        .then(res => {
            if(res.success && res.data && res.data.nodes.length > 0) {
               setData({
                 nodes: res.data.nodes.map((n: any) => ({
                    id: n.id,
                    name: n.username,
                    group: n.depth === 0 ? 1 : (n.depth === 1 ? 2 : 3),

                    val: 10
                 })),
                 links: res.data.edges.map((e: any) => ({
                    source: e.source, target: e.target
                 }))
               });
            }
        }).catch(err => console.error(err));
  };

  return (
    <div className="flex flex-col h-full animate-slide-in">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-3xl font-bold mb-1">Referral Network</h2>
          <p className="text-secondary text-sm">Interactive DAG visualization</p>
        </div>
        
        <div className="flex gap-4">
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 transform -translate-y-1/2 text-muted" />
            <input 
              type="text" 
              placeholder="Search user ID..." 
              value={searchId}
              onChange={e => setSearchId(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSearch()}
              className="bg-black/40 border border-white/10 rounded-lg pl-9 pr-4 py-2 text-sm text-white focus:outline-none focus:border-blue-500 w-64"
            />
          </div>
          <div className="flex gap-1 bg-black/40 p-1 border border-white/10 rounded-lg">
            <button className="p-1 hover:bg-white/10 rounded-md text-secondary hover:text-white" onClick={() => (fgRef.current as any)?.zoom((fgRef.current as any).zoom() * 1.2)}><ZoomIn className="w-4 h-4" /></button>
            <button className="p-1 hover:bg-white/10 rounded-md text-secondary hover:text-white" onClick={() => (fgRef.current as any)?.zoom((fgRef.current as any).zoom() / 1.2)}><ZoomOut className="w-4 h-4" /></button>
            <button className="p-1 hover:bg-white/10 rounded-md text-secondary hover:text-white" onClick={() => (fgRef.current as any)?.zoomToFit(400)}><Maximize className="w-4 h-4" /></button>
          </div>
        </div>
      </div>

      <div className="glass-card flex-1 p-0 overflow-hidden relative" ref={containerRef}>
        <ForceGraph2D
          ref={fgRef as any}
          width={dimensions.width}
          height={dimensions.height}
          graphData={data}
          nodeLabel="name"
          nodeColor={node => {
            if (node.group === 1) return '#3B82F6'; // root: blue
            if (node.group === 2) return '#10B981'; // depth 1: green
            return '#F59E0B'; // depth 2+: amber
          }}
          nodeRelSize={6}
          linkColor={() => 'rgba(255,255,255,0.2)'}
          linkDirectionalArrowLength={3.5}
          linkDirectionalArrowRelPos={1}
          backgroundColor="transparent"
          onNodeClick={(node) => {
            (fgRef.current as any)?.centerAt((node as any).x, (node as any).y, 1000);
            (fgRef.current as any)?.zoom(2, 1000);
          }}
        />
        <div className="absolute bottom-4 right-4 glass-panel p-4 flex flex-col gap-2 text-xs">
          <div className="flex items-center gap-2"><div className="w-3 h-3 rounded-full bg-blue-500"></div> Root User</div>
          <div className="flex items-center gap-2"><div className="w-3 h-3 rounded-full bg-green-500"></div> Depth 1 (Direct)</div>
          <div className="flex items-center gap-2"><div className="w-3 h-3 rounded-full bg-amber-500"></div> Depth 2+</div>
        </div>
        {!searchId && data.nodes.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="glass-panel p-6 text-center max-w-sm pointer-events-auto mt-4 px-10">
              <div className="mb-4 flex flex-col items-center">
                 <Search className="w-8 h-8 text-blue-500 mb-2" />
                 <h4 className="text-lg font-bold">Explore the Network</h4>
                 <p className="text-sm text-secondary">Enter a participant's unique ID above to visualize their referral tree and track potential fraud patterns.</p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
