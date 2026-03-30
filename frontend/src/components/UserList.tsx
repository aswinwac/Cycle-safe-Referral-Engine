import { useState, useEffect } from 'react';
import { User, Copy, ExternalLink, Plus } from 'lucide-react';
import { RegistrationModal } from './RegistrationModal';

export function UserList() {
  const [users, setUsers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);

  const fetchUsers = () => {
    setLoading(true);
    fetch('/api/v1/users')
      .then(r => {
        if (!r.ok) throw new Error(`HTTP error! status: ${r.status}`);
        return r.json();
      })
      .then(data => {
        console.log("Users API data:", data);
        if (Array.isArray(data)) {
          setUsers(data.map((u: any) => ({
             id: u.user_id,
             username: u.username,
             referral_code: u.referral_code
          })));
        } else if (data.data && Array.isArray(data.data)) {
           setUsers(data.data.map((u: any) => ({
             id: u.user_id,
             username: u.username,
             referral_code: u.referral_code
          })));
        }
        setLoading(false);
      })
      .catch(err => {
        console.error("Failed to fetch users:", err);
        setLoading(false);
      });

  };


  useEffect(() => {
    fetchUsers();
  }, []);

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    // Simple toast could be added here
  };

  if(loading) return <div className="p-8 text-center text-secondary">Searching for users...</div>;

  return (
    <div className="flex flex-col h-full animate-slide-in">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-3xl font-bold mb-1">User Directory</h2>
          <p className="text-secondary text-sm">Recently registered participants</p>
        </div>
        <button 
          onClick={() => setIsModalOpen(true)}
          className="btn-primary"
        >
          <Plus className="w-4 h-4" />
          Register New User
        </button>
      </div>

      <div className="glass-card flex-1 p-0 overflow-hidden flex flex-col">
          <div className="grid grid-cols-12 gap-4 px-6 py-4 border-b border-white/10 text-xs font-semibold text-secondary uppercase tracking-wider">
            <div className="col-span-1">Icon</div>
            <div className="col-span-3">Username</div>
            <div className="col-span-3">Referral Code (To Ref)</div>
            <div className="col-span-3">User ID (For Graph)</div>
            <div className="col-span-2 text-right">Portal</div>
          </div>
          
          <div className="overflow-y-auto flex-1">
             {users.length === 0 ? (
               <div className="p-12 text-center text-muted">No users found yet. Try seeding data.</div>
             ) : (
               users.map((u) => (
                <div key={u.id} className="grid grid-cols-12 gap-4 px-6 py-4 items-center hover:bg-white/5 transition group">
                  <div className="col-span-1">
                    <div className="w-8 h-8 rounded-full bg-blue-500/20 flex items-center justify-center text-blue-400">
                      <User className="w-4 h-4" />
                    </div>
                  </div>
                  <div className="col-span-3">
                    <span className="font-medium text-white">{u.username}</span>
                  </div>
                  <div className="col-span-3 flex items-center gap-2">
                    <span className="text-xs bg-amber-500/10 px-2 py-1 rounded text-amber-500 font-bold border border-amber-500/20">
                        {u.referral_code || '---'}
                    </span>
                    {u.referral_code && u.referral_code !== 'N/A' && (
                        <button onClick={() => copyToClipboard(u.referral_code)} className="p-1 hover:text-white text-muted transition opacity-0 group-hover:opacity-100">
                            <Copy className="w-3 h-3" />
                        </button>
                    )}
                  </div>
                  <div className="col-span-3 flex items-center gap-2">
                    <code className="text-[10px] bg-black/40 px-2 py-1 rounded text-secondary truncate max-w-[120px]">{u.id}</code>
                    <button onClick={() => copyToClipboard(u.id)} className="p-1 hover:text-white text-muted transition opacity-0 group-hover:opacity-100">
                        <Copy className="w-3 h-3" />
                    </button>
                  </div>
                  <div className="col-span-2 text-right">
                    <button className="text-secondary hover:text-white transition">
                       <ExternalLink className="w-4 h-4 ml-auto" />
                    </button>
                  </div>
                </div>
               ))
             )}
          </div>
      </div>

      {isModalOpen && (
        <RegistrationModal 
          onClose={() => setIsModalOpen(false)} 
          onSuccess={fetchUsers} 
        />
      )}
    </div>
  );
}
