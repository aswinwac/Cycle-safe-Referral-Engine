import { useState } from 'react';
import { X, UserPlus, Mail, Lock, Ticket } from 'lucide-react';

interface RegistrationModalProps {
  onClose: () => void;
  onSuccess: () => void;
}

export function RegistrationModal({ onClose, onSuccess }: RegistrationModalProps) {
  const [formData, setFormData] = useState({
    username: '',
    email: '',
    password: '',
    referral_code: '',
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const response = await fetch('/api/v1/users/register', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          ...formData,
          referral_code: formData.referral_code.trim() || null,
        }),
      });

      const data = await response.json();
      if (data.success) {
        onSuccess();
        onClose();
      } else {
        // Handle detailed validation errors
        if (data.error?.details?.errors) {
            const messages = data.error.details.errors.map((err: any) => {
                const field = err.loc[err.loc.length - 1];
                return `${field}: ${err.msg}`;
            }).join(', ');
            setError(`Validation failed - ${messages}`);
        } else {
            setError(data.error?.message || 'Registration failed');
        }
      }
    } catch (err) {
      setError('Connection error. Is the backend running?');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="glass-card w-full max-w-md p-8 relative animate-scale-in">
        <button 
          onClick={onClose}
          className="absolute top-4 right-4 p-1 hover:bg-white/10 rounded-full text-secondary transition"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="flex items-center gap-3 mb-6">
          <div className="p-3 rounded-xl bg-blue-500/20 text-blue-400">
            <UserPlus className="w-6 h-6" />
          </div>
          <div>
            <h3 className="text-xl font-bold">New Participant</h3>
            <p className="text-secondary text-sm">Join the referral network</p>
          </div>
        </div>

        {error && (
          <div className="mb-6 p-4 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1">
            <label className="text-xs font-semibold text-secondary uppercase ml-1">Username</label>
            <div className="relative">
              <UserPlus className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
              <input
                required
                type="text"
                placeholder="Unique handle..."
                className="input-field"
                value={formData.username}
                onChange={e => setFormData({...formData, username: e.target.value})}
              />
            </div>
          </div>

          <div className="space-y-1">
            <label className="text-xs font-semibold text-secondary uppercase ml-1">Email Address</label>
            <div className="relative">
              <Mail className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
              <input
                required
                type="email"
                placeholder="email@example.com"
                className="input-field"
                value={formData.email}
                onChange={e => setFormData({...formData, email: e.target.value})}
              />
            </div>
          </div>

          <div className="space-y-1">
            <label className="text-xs font-semibold text-secondary uppercase ml-1">Password</label>
            <div className="relative">
              <Lock className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
              <input
                required
                type="password"
                placeholder="••••••••"
                className="input-field"
                value={formData.password}
                onChange={e => setFormData({...formData, password: e.target.value})}
              />
            </div>
          </div>

          <div className="space-y-1 pt-2">
            <label className="text-xs font-semibold text-amber-500 uppercase ml-1">Referral Code (Optional)</label>
            <div className="relative">
              <Ticket className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-amber-500/60" />
              <input
                type="text"
                placeholder="USER-XXXX"
                className="input-field border-amber-500/20 focus:border-amber-500"
                value={formData.referral_code}
                onChange={e => setFormData({...formData, referral_code: e.target.value.toUpperCase()})}
              />
            </div>
            <p className="text-[10px] text-muted ml-1">Leave blank to join as a root user</p>
          </div>

          <button 
            type="submit" 
            disabled={loading}
            className="btn-primary w-full mt-6"
          >
            {loading ? 'Processing...' : 'Complete Registration'}
          </button>
        </form>
      </div>
    </div>
  );
}
