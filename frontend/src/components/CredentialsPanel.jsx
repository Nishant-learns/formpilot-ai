import React, { useState, useEffect } from 'react';
import {
  Key,
  Eye,
  EyeOff,
  Copy,
  CheckCheck,
  Trash2,
  Plus,
  ExternalLink,
  ShieldCheck,
  Lock,
  Sparkles,
  RefreshCw,
  Search,
  Globe,
  AlertCircle,
} from 'lucide-react';

export default function CredentialsPanel({ notify }) {
  const [credentials, setCredentials] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [visiblePasswords, setVisiblePasswords] = useState({});
  const [copiedField, setCopiedField] = useState(null);

  // New credential modal/form state
  const [showAddModal, setShowAddModal] = useState(false);
  const [newSiteName, setNewSiteName] = useState('');
  const [newUrl, setNewUrl] = useState('');
  const [newUsername, setNewUsername] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newNotes, setNewNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // Quick generator state
  const [generatedPass, setGeneratedPass] = useState('');
  const [generating, setGenerating] = useState(false);

  const fetchCredentials = async () => {
    try {
      setLoading(true);
      const res = await fetch('/api/credentials');
      if (res.ok) {
        const data = await res.json();
        setCredentials(data.credentials || []);
      } else {
        setError('Failed to load saved credentials.');
      }
    } catch (err) {
      console.error('Error fetching credentials:', err);
      setError('Network error while loading credentials.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCredentials();
  }, []);

  const handleGeneratePassword = async () => {
    try {
      setGenerating(true);
      const res = await fetch('/api/credentials/generate-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ length: 12 }),
      });
      if (res.ok) {
        const data = await res.json();
        setGeneratedPass(data.password || '');
        if (showAddModal) {
          setNewPassword(data.password || '');
        }
      }
    } catch (err) {
      console.error('Error generating password:', err);
    } finally {
      setGenerating(false);
    }
  };

  const handleCreateCredential = async (e) => {
    e.preventDefault();
    if (!newPassword.trim()) {
      if (notify) notify('Password is required', 'error');
      return;
    }
    setSubmitting(true);
    try {
      const res = await fetch('/api/credentials', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          site_name: newSiteName.trim() || 'Portal Account',
          url: newUrl.trim(),
          username: newUsername.trim(),
          password: newPassword.trim(),
          notes: newNotes.trim(),
        }),
      });
      if (res.ok) {
        if (notify) notify('Saved portal credentials successfully', 'success');
        setShowAddModal(false);
        setNewSiteName('');
        setNewUrl('');
        setNewUsername('');
        setNewPassword('');
        setNewNotes('');
        await fetchCredentials();
      } else {
        if (notify) notify('Failed to save credential', 'error');
      }
    } catch (err) {
      console.error('Error creating credential:', err);
      if (notify) notify('Network error while saving credential', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeleteCredential = async (credId, siteName) => {
    if (!confirm(`Permanently delete credentials for "${siteName || 'this site'}"?`)) return;
    try {
      const res = await fetch(`/api/credentials/${credId}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        if (notify) notify('Credential deleted', 'info');
        setCredentials((prev) => prev.filter((c) => c.id !== credId));
      } else {
        if (notify) notify('Failed to delete credential', 'error');
      }
    } catch (err) {
      console.error('Error deleting credential:', err);
    }
  };

  const copyToClipboard = (fieldKey, text) => {
    if (!text) return;
    navigator.clipboard.writeText(text);
    setCopiedField(fieldKey);
    setTimeout(() => setCopiedField(null), 2000);
  };

  const togglePasswordVisibility = (id) => {
    setVisiblePasswords((prev) => ({
      ...prev,
      [id]: !prev[id],
    }));
  };

  const filteredCredentials = credentials.filter((cred) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return (
      (cred.site_name && cred.site_name.toLowerCase().includes(q)) ||
      (cred.username && cred.username.toLowerCase().includes(q)) ||
      (cred.url && cred.url.toLowerCase().includes(q)) ||
      (cred.notes && cred.notes.toLowerCase().includes(q))
    );
  });

  return (
    <div className="glass-panel p-6 rounded-3xl border border-white/[0.08] space-y-6 animate-fadeIn">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-white/[0.06] pb-4">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-sm sm:text-base font-bold text-white flex items-center gap-2">
              <Key className="w-4 h-4 text-indigo-400" />
              Saved Portal Passwords & Credentials
            </h3>
            <span className="text-[10px] font-mono text-emerald-400 font-bold bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
              Encrypted At Rest
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Portal account credentials generated or used during form applications are securely saved here and survive page refreshes, browser reloads, and session restarts.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={fetchCredentials}
            className="p-2 rounded-xl bg-white/[0.03] hover:bg-white/[0.07] border border-white/[0.08] text-slate-400 hover:text-white transition-colors"
            title="Refresh saved credentials"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={() => {
              handleGeneratePassword();
              setShowAddModal(true);
            }}
            className="px-3.5 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold flex items-center gap-1.5 shadow-sm shadow-indigo-500/20 transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Add Password</span>
          </button>
        </div>
      </div>

      {/* Password Generator Quick Bar */}
      <div className="p-3.5 rounded-2xl bg-indigo-950/20 border border-indigo-500/20 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-xl bg-indigo-500/20 text-indigo-300">
            <Sparkles className="w-4 h-4" />
          </div>
          <div>
            <span className="text-xs font-semibold text-white block">Government Portal Compliant Generator</span>
            <span className="text-[11px] text-slate-400">8–13 chars, uppercase, lowercase, numbers & special symbols (!@#$%^&*)</span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {generatedPass && (
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-900 border border-indigo-500/30">
              <span className="font-mono text-xs font-bold text-indigo-200 tracking-wider">{generatedPass}</span>
              <button
                type="button"
                onClick={() => copyToClipboard('quick_gen', generatedPass)}
                className="text-slate-400 hover:text-white p-1"
                title="Copy generated password"
              >
                {copiedField === 'quick_gen' ? <CheckCheck className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
              </button>
            </div>
          )}
          <button
            type="button"
            onClick={handleGeneratePassword}
            disabled={generating}
            className="px-3 py-1.5 rounded-xl bg-white/[0.05] hover:bg-white/[0.09] border border-white/[0.1] text-xs font-medium text-slate-200 flex items-center gap-1.5 transition-colors"
          >
            <RefreshCw className={`w-3 h-3 ${generating ? 'animate-spin' : ''}`} />
            <span>{generatedPass ? 'Generate Another' : 'Generate Strong Password'}</span>
          </button>
        </div>
      </div>

      {/* Search Bar */}
      {credentials.length > 0 && (
        <div className="relative">
          <Search className="w-4 h-4 text-slate-500 absolute left-3.5 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search saved credentials by portal name, username, or URL..."
            className="w-full pl-9 pr-3.5 py-2.5 rounded-xl bg-slate-950/80 border border-white/[0.08] text-xs text-white placeholder-slate-500 focus:border-indigo-400 focus:ring-1 focus:ring-indigo-400/30 outline-none transition-all"
          />
        </div>
      )}

      {/* Credentials List */}
      {loading ? (
        <div className="py-12 text-center text-slate-400 text-xs">
          <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-indigo-400" />
          Loading saved credentials...
        </div>
      ) : filteredCredentials.length === 0 ? (
        <div className="py-12 text-center border border-dashed border-white/[0.08] rounded-2xl p-6">
          <Lock className="w-8 h-8 text-slate-600 mx-auto mb-2" />
          <p className="text-xs font-semibold text-slate-300">No saved credentials yet</p>
          <p className="text-[11px] text-slate-500 mt-1 max-w-sm mx-auto">
            When you run an application on JEE, UPSC, SSC or state portals, generated or entered passwords will automatically be saved here.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {filteredCredentials.map((cred) => {
            const isVisible = !!visiblePasswords[cred.id];
            return (
              <div
                key={cred.id}
                className="p-4 rounded-2xl bg-white/[0.02] border border-white/[0.08] hover:border-white/[0.15] transition-all space-y-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <div className="p-2 rounded-xl bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                      <Globe className="w-4 h-4" />
                    </div>
                    <div>
                      <h4 className="text-xs font-bold text-white truncate max-w-[200px]">
                        {cred.site_name || 'Portal Account'}
                      </h4>
                      {cred.url ? (
                        <a
                          href={cred.url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-[10px] text-indigo-300 hover:underline flex items-center gap-1 font-mono truncate max-w-[220px]"
                        >
                          <span className="truncate">{cred.domain || cred.url}</span>
                          <ExternalLink className="w-2.5 h-2.5 shrink-0" />
                        </a>
                      ) : (
                        <span className="text-[10px] text-slate-500">Government Portal</span>
                      )}
                    </div>
                  </div>

                  <button
                    type="button"
                    onClick={() => handleDeleteCredential(cred.id, cred.site_name)}
                    className="p-1.5 rounded-lg text-slate-500 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                    title="Delete credential"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>

                {/* Fields */}
                <div className="space-y-2 text-xs pt-1">
                  {/* Username / Application ID */}
                  <div className="p-2 rounded-xl bg-slate-950/60 border border-white/[0.05] flex items-center justify-between">
                    <div>
                      <span className="text-[10px] uppercase font-mono text-slate-400 block">Username / App ID</span>
                      <span className="text-xs font-mono font-medium text-slate-200">
                        {cred.username || 'Not set'}
                      </span>
                    </div>
                    {cred.username && (
                      <button
                        type="button"
                        onClick={() => copyToClipboard(`user_${cred.id}`, cred.username)}
                        className="text-slate-400 hover:text-white p-1"
                        title="Copy username"
                      >
                        {copiedField === `user_${cred.id}` ? (
                          <CheckCheck className="w-3.5 h-3.5 text-emerald-400" />
                        ) : (
                          <Copy className="w-3.5 h-3.5" />
                        )}
                      </button>
                    )}
                  </div>

                  {/* Password */}
                  <div className="p-2 rounded-xl bg-slate-950/60 border border-white/[0.05] flex items-center justify-between">
                    <div>
                      <span className="text-[10px] uppercase font-mono text-slate-400 block">Password</span>
                      <span className="text-xs font-mono font-bold text-indigo-200 tracking-wider">
                        {isVisible ? cred.password : '••••••••••••'}
                      </span>
                    </div>
                    <div className="flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => togglePasswordVisibility(cred.id)}
                        className="text-slate-400 hover:text-white p-1"
                        title={isVisible ? 'Hide password' : 'Show password'}
                      >
                        {isVisible ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                      </button>
                      <button
                        type="button"
                        onClick={() => copyToClipboard(`pass_${cred.id}`, cred.password)}
                        className="text-slate-400 hover:text-white p-1"
                        title="Copy password"
                      >
                        {copiedField === `pass_${cred.id}` ? (
                          <CheckCheck className="w-3.5 h-3.5 text-emerald-400" />
                        ) : (
                          <Copy className="w-3.5 h-3.5" />
                        )}
                      </button>
                    </div>
                  </div>
                </div>

                {/* Footer timestamp & notes */}
                <div className="flex items-center justify-between text-[10px] text-slate-400 pt-1 border-t border-white/[0.04]">
                  <span>{cred.notes || 'Auto-created in session'}</span>
                  <span>{cred.created_at ? new Date(cred.created_at).toLocaleDateString() : ''}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Add Credential Modal */}
      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fadeIn">
          <div className="w-full max-w-md p-6 rounded-3xl bg-slate-900 border border-white/[0.1] shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-white/[0.08] pb-3">
              <h4 className="text-sm font-bold text-white flex items-center gap-2">
                <Key className="w-4 h-4 text-indigo-400" />
                Add Saved Portal Password
              </h4>
              <button
                type="button"
                onClick={() => setShowAddModal(false)}
                className="text-slate-400 hover:text-white text-xs"
              >
                Cancel
              </button>
            </div>

            <form onSubmit={handleCreateCredential} className="space-y-3 text-xs">
              <div>
                <label className="text-slate-300 font-semibold block mb-1">Site / Portal Name</label>
                <input
                  type="text"
                  value={newSiteName}
                  onChange={(e) => setNewSiteName(e.target.value)}
                  placeholder="e.g. JEE Main 2026 / NTA Portal"
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-white/[0.1] text-white outline-none focus:border-indigo-400"
                />
              </div>

              <div>
                <label className="text-slate-300 font-semibold block mb-1">Portal URL (Optional)</label>
                <input
                  type="text"
                  value={newUrl}
                  onChange={(e) => setNewUrl(e.target.value)}
                  placeholder="e.g. https://jeemain.nta.nic.in"
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-white/[0.1] text-white outline-none focus:border-indigo-400"
                />
              </div>

              <div>
                <label className="text-slate-300 font-semibold block mb-1">Username / Application ID</label>
                <input
                  type="text"
                  value={newUsername}
                  onChange={(e) => setNewUsername(e.target.value)}
                  placeholder="e.g. 260310001234 or email"
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-white/[0.1] text-white outline-none focus:border-indigo-400"
                />
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-slate-300 font-semibold">Password *</label>
                  <button
                    type="button"
                    onClick={handleGeneratePassword}
                    className="text-[10px] text-indigo-400 hover:text-indigo-300 flex items-center gap-1 font-medium"
                  >
                    <Sparkles className="w-3 h-3" />
                    Auto-Generate
                  </button>
                </div>
                <input
                  type="text"
                  required
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="Strong password"
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-white/[0.1] text-white font-mono font-bold outline-none focus:border-indigo-400"
                />
              </div>

              <div>
                <label className="text-slate-300 font-semibold block mb-1">Notes (Optional)</label>
                <input
                  type="text"
                  value={newNotes}
                  onChange={(e) => setNewNotes(e.target.value)}
                  placeholder="e.g. Security question answer: Blue"
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-white/[0.1] text-white outline-none focus:border-indigo-400"
                />
              </div>

              <div className="pt-2 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="px-3 py-2 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] text-slate-300 font-semibold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-bold"
                >
                  {submitting ? 'Saving...' : 'Save Password'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
