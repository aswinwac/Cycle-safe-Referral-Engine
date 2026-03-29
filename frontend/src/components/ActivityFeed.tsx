import { useState, useEffect } from 'react';
import { UserPlus, ShieldAlert, Activity as ActivityIcon } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';

export function ActivityFeed() {
  const [events, setEvents] = useState<any[]>([]);
  const [isLive, setIsLive] = useState(true);

  // Poll backend instead of websocket for simplicity
  useEffect(() => {
    if (!isLive) return;
    
    // Initial fetch
    fetch('/api/v1/dashboard/activity-feed?limit=50')
      .then(r => r.json())
      .then(res => {
        if(res.success && res.data?.events?.length > 0) {
          setEvents(res.data.events);
        }
      })
      .catch();
      
    const interval = setInterval(() => {
      fetch('/api/v1/dashboard/activity-feed?limit=15')
        .then(r => r.json())
        .then(res => {
          if(res.success && res.data?.events?.length > 0) {
            setEvents(prev => [...res.data.events, ...prev].filter((v,i,a)=>a.findIndex(t=>(t.id === v.id))===i).slice(0, 50));
          } else {
             // Let's use mock data fallback if API returns empty
          }
        })
        .catch(e => console.error("Could not fetch activity feed"));
    }, 4000);
    return () => clearInterval(interval);
  }, [isLive]);

  return (
    <div className="flex flex-col h-full animate-slide-in">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-3xl font-bold mb-1">Live Activity</h2>
          <p className="text-secondary text-sm">System-wide event stream</p>
        </div>
        
        <div className="glass-panel px-4 py-2 flex items-center gap-3">
          <div className="flex items-center gap-2">
            <div className={`live-indicator ${isLive ? 'bg-green-500' : 'bg-red-500'}`}></div>
            <span className="text-sm font-medium">{isLive ? 'Connected' : 'Disconnected'}</span>
          </div>
          <div className="w-1px h-4 bg-white/20"></div>
          <button 
            onClick={() => setIsLive(!isLive)}
            className="text-xs text-secondary hover:text-white transition"
          >
            {isLive ? 'Pause Stream' : 'Reconnect'}
          </button>
        </div>
      </div>

      <div className="glass-card flex-1 overflow-y-auto p-2">
        <div className="flex flex-col space-y-3 p-2">
          {events.map((evt: any, idx) => {
            const isFraud = evt.event_type === 'FRAUD_FLAGGED';
            const Icon = isFraud ? ShieldAlert : UserPlus;
            
            return (
              <div 
                key={evt.id} 
                className={`flex items-start gap-4 p-4 rounded-xl border z-10 
                  bg-gradient-to-r transition-all duration-500
                  ${idx === 0 && isLive ? 'animate-slide-in scale-100' : 'scale-99 opacity-90'}
                  ${isFraud 
                    ? 'from-red-950/40 to-black/40 border-red-500/20 hover:border-red-500/50' 
                    : 'from-blue-950/40 to-black/40 border-blue-500/20 hover:border-blue-500/50'
                  }`}
              >
                <div className={`p-3 rounded-xl border shadow-lg
                  ${isFraud 
                    ? 'bg-red-500/10 border-red-500/30 text-red-400 shadow-red-500/10' 
                    : 'bg-blue-500/10 border-blue-500/30 text-blue-400 shadow-blue-500/10'
                  }`}
                >
                  <Icon className="w-6 h-6" />
                </div>
                
                <div className="flex-1">
                  <div className="flex justify-between items-center mb-1">
                    <h4 className="font-semibold text-white tracking-wide">{evt.label}</h4>
                    <span className="text-xs text-secondary bg-black/50 px-2 py-1 rounded-full">
                      {formatDistanceToNow(new Date(evt.created_at), { addSuffix: true })}
                    </span>
                  </div>
                  
                  <div className="flex items-center gap-2 text-sm text-secondary mb-2">
                    <span className="text-white bg-white/5 px-2 py-0.5 rounded flex items-center gap-1">
                      <ActivityIcon className="w-3 h-3" />
                      {evt.actor?.username || "System"}
                    </span>
                    {!isFraud && evt.target && (
                      <>
                        <span className="text-muted">→</span>
                        <span className="text-white bg-white/5 px-2 py-0.5 rounded">
                          {evt.target.username}
                        </span>
                      </>
                    )}
                  </div>
                  
                  <div className="flex flex-wrap gap-2 mt-2">
                    {evt.payload && Object.entries(evt.payload).map(([k, v]) => (
                      <span key={k} className={`text-xs px-2 py-1 rounded-md border
                        ${isFraud ? 'bg-red-500/10 border-red-500/20 text-red-300' : 'bg-white/5 border-white/10 text-muted'}
                      `}>
                        {k}: {String(v)}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
