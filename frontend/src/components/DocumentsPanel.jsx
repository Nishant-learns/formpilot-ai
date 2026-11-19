import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, Check, Download, FileText, Lock, Trash2, Upload } from 'lucide-react';

const ACCEPT = 'image/jpeg,image/png,image/webp,application/pdf';

const FALLBACK_TYPES = {
  photo: 'Passport photograph',
  signature: 'Signature',
  aadhaar_front: 'Aadhaar (front)',
  aadhaar_back: 'Aadhaar (back)',
  pan_card: 'PAN card',
  matric_certificate: '10th / Matric certificate',
  intermediate_certificate: '12th / Intermediate certificate',
  graduation_certificate: 'Graduation certificate',
  caste_certificate: 'Caste certificate',
  domicile_certificate: 'Domicile certificate',
  other: 'Other document',
};

function formatSize(bytes) {
  const value = Number(bytes || 0);
  if (value >= 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  if (value >= 1024) return `${Math.round(value / 1024)} KB`;
  return `${value} B`;
}

export default function DocumentsPanel({ notify }) {
  const [documents, setDocuments] = useState([]);
  const [docTypes, setDocTypes] = useState(FALLBACK_TYPES);
  const [loading, setLoading] = useState(true);
  const [busyType, setBusyType] = useState('');
  const [error, setError] = useState('');
  const inputs = useRef({});

  const load = useCallback(async () => {
    try {
      const res = await fetch('/api/vault/documents');
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || 'Could not read the document vault.');
      setDocuments(data.documents || []);
      if (data.doc_types) setDocTypes(data.doc_types);
      setError('');
    } catch (err) {
      setError(err.message || 'Could not read the document vault.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const upload = async (docType, file) => {
    if (!file) return;
    setBusyType(docType);
    setError('');
    try {
      const body = new FormData();
      body.append('doc_type', docType);
      body.append('file', file);
      const res = await fetch('/api/vault/documents', { method: 'POST', body });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || 'That file could not be stored.');
      await load();
      if (notify) notify(`${docTypes[docType] || docType} sealed in the encrypted vault.`, 'success');
    } catch (err) {
      setError(err.message || 'That file could not be stored.');
      if (notify) notify(err.message || 'Upload failed.', 'error');
    } finally {
      setBusyType('');
    }
  };

  const remove = async (doc) => {
    if (!window.confirm(`Delete "${doc.filename}" from the vault? This cannot be undone.`)) return;
    try {
      const res = await fetch(`/api/vault/documents/${doc.id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Could not delete that document.');
      await load();
      if (notify) notify('Document deleted from the vault.', 'info');
    } catch (err) {
      if (notify) notify(err.message, 'error');
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex items-start gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3.5 py-2.5 text-[11px] text-emerald-100">
        <Lock className="mt-0.5 h-4 w-4 shrink-0 text-emerald-300" />
        <span>
          Every file is sealed with AES-256-GCM before it touches the disk, and the index is sealed
          too. Downloads go through the API, never a public folder. Nothing here is shared with a
          portal until a form asks for it.
        </span>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3.5 py-2.5 text-[11px] text-rose-200">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {Object.entries(docTypes).map(([type, label]) => {
          const files = documents.filter((doc) => doc.doc_type === type);
          const busy = busyType === type;
          return (
            <div
              key={type}
              className="flex flex-col rounded-2xl border border-white/[0.08] bg-white/[0.02] p-3.5"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-xs font-bold text-white">{label}</p>
                  <p className="mt-0.5 font-mono text-[10px] text-slate-500">
                    {files.length ? `${files.length} stored` : 'Not uploaded'}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => inputs.current[type]?.click()}
                  disabled={busy}
                  className="flex min-h-[40px] items-center gap-1.5 rounded-xl border border-indigo-500/40 bg-indigo-500/15 px-3 py-2 text-[11px] font-bold text-indigo-100 transition-colors hover:bg-indigo-500/25 disabled:opacity-50"
                >
                  {busy ? <Check className="h-3.5 w-3.5" /> : <Upload className="h-3.5 w-3.5" />}
                  <span>{busy ? 'Sealing' : 'Upload'}</span>
                </button>
                <input
                  ref={(node) => {
                    inputs.current[type] = node;
                  }}
                  type="file"
                  accept={ACCEPT}
                  className="hidden"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    upload(type, file);
                    event.target.value = '';
                  }}
                />
              </div>

              {files.length > 0 && (
                <ul className="mt-3 space-y-2">
                  {files.slice(0, 3).map((doc) => (
                    <li
                      key={doc.id}
                      className="flex items-center justify-between gap-2 rounded-xl border border-white/[0.06] bg-slate-950/60 px-2.5 py-2"
                    >
                      <div className="flex min-w-0 items-center gap-2">
                        <FileText className="h-3.5 w-3.5 shrink-0 text-slate-400" />
                        <div className="min-w-0">
                          <p className="truncate text-[11px] font-semibold text-slate-200">
                            {doc.filename}
                          </p>
                          <p className="font-mono text-[9px] text-slate-500">
                            {formatSize(doc.size)} · {String(doc.created_at || '').slice(0, 10)}
                          </p>
                        </div>
                      </div>
                      <div className="flex shrink-0 items-center gap-1">
                        <a
                          href={`/api/vault/documents/${doc.id}`}
                          className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-white/[0.06] hover:text-white"
                          title="Download"
                        >
                          <Download className="h-3.5 w-3.5" />
                        </a>
                        <button
                          type="button"
                          onClick={() => remove(doc)}
                          className="rounded-lg p-2 text-rose-300 transition-colors hover:bg-rose-500/15 hover:text-rose-200"
                          title="Delete"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>

      {loading && <p className="font-mono text-[11px] text-slate-500">Opening the sealed vault…</p>}
    </div>
  );
}
