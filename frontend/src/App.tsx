import { useState } from 'react';
import { Sidebar } from './components/Sidebar';
import { MetricsPanel } from './components/MetricsPanel';
import { GraphView } from './components/GraphView';
import { FraudPanel } from './components/FraudPanel';
import { ActivityFeed } from './components/ActivityFeed';
import { UserList } from './components/UserList';

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
        return <UserList />;
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
