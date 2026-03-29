import { useState, useEffect } from 'react';
import { Users, CheckCircle, AlertTriangle, Coins } from 'lucide-react';
import { 
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
} from 'recharts';

export function MetricsPanel() {
  const [metrics, setMetrics] = useState<any>({ users: { total: 0, new_in_window: 0, active: 0 }, referrals: { total: 0, valid: 0, rejected: 0, fraud: 0, in_window: 0, valid_rate: 0 }, rewards: { total_issued: 0, amount_distributed: 0, pending_amount: 0 }, fraud: { total_events: 0, by_reason: {}, unreviewed_high_severity: 0 }, system: { graph_node_count: 0, graph_edge_count: 0, avg_referral_latency_ms: 0, cache_hit_rate: 0 } });
  const [windowRange, setWindowRange] = useState('24h');

  useEffect(() => {
    fetch(`/api/v1/dashboard/metrics?window=${windowRange}`)
      .then(r => r.json())
      .then(res => {
        if(res.success && res.data) {
          setMetrics(res.data);
        }
      })
      .catch(e => console.error("Could not fetch metrics", e));
  }, [windowRange]);

  const chartData = [
    { time: '12:00', valid: 400, fraud: 24, rejected: 120 },
    { time: '16:00', valid: 300, fraud: 13, rejected: 200 },
    { time: '20:00', valid: 200, fraud: 38, rejected: 150 },
    { time: '00:00', valid: 600, fraud: 25, rejected: 210 },
    { time: '04:00', valid: 450, fraud: 15, rejected: 180 },
    { time: '08:00', valid: 500, fraud: 18, rejected: 160 },
    { time: '12:00', valid: 700, fraud: 45, rejected: 290 },
  ];

  const statCards = [
    { title: "Total Users", value: metrics.users.total.toLocaleString(), delta: `+${metrics.users.new_in_window}`, icon: Users, color: 'blue' },
    { title: "Valid Referrals", value: metrics.referrals.valid.toLocaleString(), delta: `${(metrics.referrals.valid_rate * 100).toFixed(1)}% rate`, icon: CheckCircle, color: 'green' },
    { title: "Fraud Events", value: metrics.fraud.total_events.toLocaleString(), delta: `${metrics.fraud.unreviewed_high_severity} critical`, icon: AlertTriangle, color: 'red' },
    { title: "Rewards Issued", value: `$${metrics.rewards.amount_distributed.toLocaleString()}`, delta: `$${metrics.rewards.pending_amount} pending`, icon: Coins, color: 'amber' },
  ];

  return (
    <div className="flex-col gap-6 animate-slide-in">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-3xl font-bold mb-1">System Metrics</h2>
          <p className="text-secondary text-sm">Real-time aggregation from Postgres & Redis</p>
        </div>
        <div className="flex gap-2 bg-black/40 p-1 border border-white/10 rounded-lg">
          {['1h','24h','7d','30d'].map(win => (
            <button key={win} onClick={() => setWindowRange(win)} className={`px-3 py-1 rounded-md text-sm ${win === windowRange ? 'bg-white/10 text-white' : 'text-secondary hover:text-white transition'}`}>
              {win}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-4 gap-4 mb-6">
        {statCards.map((stat, i) => {
          const Icon = stat.icon;
          return (
            <div key={i} className="glass-card flex-col justify-between">
              <div className="flex justify-between items-start mb-4">
                <div className={`p-2 rounded-lg bg-${stat.color}-500/20 text-${stat.color}-400`}>
                  <Icon className="w-5 h-5" />
                </div>
                <span className={`text-xs badge ${stat.color}`}>{stat.delta}</span>
              </div>
              <div>
                <h3 className="text-muted text-sm font-medium mb-1">{stat.title}</h3>
                <p className="text-2xl font-bold text-white tracking-tight">{stat.value}</p>
              </div>
            </div>
          )
        })}
      </div>

      <div className="grid grid-cols-3 gap-6">
        <div className="col-span-2 glass-card h-400px flex-col">
          <h3 className="text-lg font-bold mb-4">Referral Velocity (24h)</h3>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="colorValid" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="var(--accent-blue)" stopOpacity={0.3}/>
                  <stop offset="95%" stopColor="var(--accent-blue)" stopOpacity={0}/>
                </linearGradient>
                <linearGradient id="colorFraud" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="var(--accent-red)" stopOpacity={0.3}/>
                  <stop offset="95%" stopColor="var(--accent-red)" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
              <XAxis dataKey="time" stroke="rgba(255,255,255,0.3)" fontSize={12} tickLine={false} axisLine={false} />
              <YAxis stroke="rgba(255,255,255,0.3)" fontSize={12} tickLine={false} axisLine={false} />
              <Tooltip 
                contentStyle={{ backgroundColor: 'rgba(10,10,11,0.9)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px' }}
                itemStyle={{ color: '#fff' }}
              />
              <Area type="monotone" dataKey="valid" stroke="var(--accent-blue)" strokeWidth={2} fillOpacity={1} fill="url(#colorValid)" />
              <Area type="monotone" dataKey="fraud" stroke="var(--accent-red)" strokeWidth={2} fillOpacity={1} fill="url(#colorFraud)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="col-span-1 glass-card flex-col">
          <h3 className="text-lg font-bold mb-4">Fraud Typology</h3>
          <div className="flex-1 overflow-y-auto pr-2" style={{ scrollbarWidth: 'none' }}>
            {Object.entries(metrics.fraud.by_reason || {}).sort(([,a], [,b]) => Number(b) - Number(a)).map(([k, v]) => (
              <div key={k} className="mb-4">
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-secondary truncate mr-2" title={k}>{k.replace(/_/g, ' ')}</span>
                  <span className="font-medium">{String(v)}</span>
                </div>
                <div className="w-full bg-white/5 rounded-full h-1.5">
                  <div 
                    className="bg-red-500 h-1.5 rounded-full" 
                    style={{ width: `${(Number(v) / Math.max(1, metrics.fraud.total_events)) * 100}%` }}
                  ></div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
