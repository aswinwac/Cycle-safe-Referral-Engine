import { useState } from 'react';
import { Sidebar } from './components/Sidebar';
import { MetricsPanel } from './components/MetricsPanel';
import { GraphView } from './components/GraphView';
import { FraudPanel } from './components/FraudPanel';
import { ActivityFeed } from './components/ActivityFeed';

function App() {
  const [activeTab, setActiveTab] = useState('metrics');

  const renderContent = () => {
    switch (activeTab) {
      case 'metrics':
        return <MetricsPanel />;
      case 'graph':
        return <GraphView />;
      case 'fraud':
        return <FraudPanel />;
      case 'activity':
        return <ActivityFeed />;
      case 'users':
        return (
          <div className="flex items-center justify-center h-full animate-slide-in text-muted">
            User listing interface pending implementation
          </div>
        );
      default:
        return <MetricsPanel />;
    }
  };

  return (
    <div className="app-container">
      <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} />
      <main className="main-content">
        {renderContent()}
      </main>
    </div>
  );
}

export default App;
