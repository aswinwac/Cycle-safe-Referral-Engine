import { useState, useEffect } from 'react';
import { ShieldAlert, Filter, CheckCircle, XCircle } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';

export function FraudPanel() {
  const [events, setEvents] = useState<any[]>([]);

  useEffect(() => {
    fetch('/api/v1/dashboard/fraud-panel')
      .then(r => r.json())
      .then(res => {
        if(res.success && res.data?.events?.length > 0) {
          setEvents(res.data.events);
        }
      })
      .catch();
  }, []);

  return (
    <div className="flex flex-col h-full animate-slide-in">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-3xl font-bold mb-1">Fraud Detection</h2>
          <p className="text-secondary text-sm">Real-time alerts and manual review queue</p>
        </div>
        
        <button className="btn-glass px-4">
          <Filter className="w-4 h-4 mr-2" />
          Filter: Unreviewed High Severity
        </button>
      </div>

      <div className="glass-card flex-1 overflow-hidden flex flex-col p-0">
        <div className="grid grid-cols-12 gap-4 px-6 py-4 border-b border-white/10 text-xs font-semibold text-secondary uppercase tracking-wider">
          <div className="col-span-3">User & Attempt</div>
          <div className="col-span-3">Reason</div>
          <div className="col-span-2">Severity</div>
          <div className="col-span-2">Time</div>
          <div className="col-span-2 text-right">Actions</div>
        </div>

        <div className="overflow-y-auto flex-1 p-2">
          {events.map((evt) => (
            <div key={evt.id} className="grid grid-cols-12 gap-4 flex items-center px-4 py-4 rounded-lg hover:bg-white/5 transition border border-transparent hover:border-white/10 mb-2">
              <div className="col-span-3 flex flex-col">
                <span className="font-medium text-white">{evt.user?.username || 'Unknown'}</span>
                {evt.referral_attempt && (
                  <span className="text-xs text-secondary">
                    Tried referring <span className="text-blue-400">{evt.referral_attempt.attempted_referrer?.username}</span>
                  </span>
                )}
              </div>
              
              <div className="col-span-3 flex items-center gap-2">
                <ShieldAlert className={`w-4 h-4 ${evt.severity === 3 ? 'text-red-500' : 'text-amber-500'}`} />
                <span className="text-sm font-medium">{evt.reason.replace(/_/g, ' ')}</span>
              </div>
              
              <div className="col-span-2">
                <span className={`badge ${evt.severity === 3 ? 'red' : 'amber'}`}>
                  {evt.severity_label} ({evt.severity})
                </span>
              </div>

              <div className="col-span-2 text-sm text-secondary">
                {formatDistanceToNow(new Date(evt.created_at), { addSuffix: true })}
              </div>

              <div className="col-span-2 flex justify-end gap-2">
                {!evt.reviewed ? (
                  <>
                    <button 
                      className="p-1.5 rounded-md hover:bg-green-500/20 text-green-500 border border-transparent hover:border-green-500/30 transition"
                      title="Mark Safe"
                    >
                      <CheckCircle className="w-4 h-4" />
                    </button>
                    <button 
                      className="p-1.5 rounded-md hover:bg-red-500/20 text-red-500 border border-transparent hover:border-red-500/30 transition"
                      title="Ban User"
                    >
                      <XCircle className="w-4 h-4" />
                    </button>
                  </>
                ) : (
                  <span className="badge green">Reviewed</span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
