import { Activity, AlertTriangle, BarChart3, Users, Network, Settings, LogOut } from 'lucide-react';

interface SidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
}

export function Sidebar({ activeTab, setActiveTab }: SidebarProps) {
  const menuItems = [
    { id: 'metrics', label: 'Metrics', icon: BarChart3 },
    { id: 'graph', label: 'Network Graph', icon: Network },
    { id: 'fraud', label: 'Fraud Review', icon: AlertTriangle },
    { id: 'activity', label: 'Activity Feed', icon: Activity },
    { id: 'users', label: 'Users', icon: Users },
  ];

  return (
    <aside className="sidebar p-6 flex-col justify-between">
      <div>
        <div className="flex items-center gap-3 mb-8">
          <div className="w-8 h-8 rounded-lg bg-blue-500/20 flex items-center justify-center border border-blue-500/30">
            <Network className="text-blue-500 w-5 h-5" />
          </div>
          <h1 className="text-xl font-bold text-gradient">CSRE</h1>
        </div>
        
        <div className="flex flex-col gap-2">
          {menuItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                onClick={() => setActiveTab(item.id)}
                className={`btn-glass ${activeTab === item.id ? 'active' : ''} justify-start py-3`}
              >
                <Icon className="w-5 h-5 opacity-80" />
                {item.label}
              </button>
            )
          })}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <button className="btn-glass justify-start py-3 text-muted">
          <Settings className="w-5 h-5" />
          System Config
        </button>
        <button className="btn-glass justify-start py-3 text-muted">
          <LogOut className="w-5 h-5" />
          Logout
        </button>
      </div>
    </aside>
  );
}
