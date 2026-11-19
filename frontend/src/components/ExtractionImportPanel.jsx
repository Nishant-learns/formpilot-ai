import React, { useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  Check,
  CheckCheck,
  ChevronDown,
  ChevronUp,
  Copy,
  Download,
  ExternalLink,
  Sparkles,
  Upload,
  X,
} from 'lucide-react';

const VERDICT_STYLE = {
  new: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
  same: 'border-slate-500/40 bg-slate-500/10 text-slate-300',
  conflict: 'border-amber-500/40 bg-amber-500/10 text-amber-200',
  uncertain: 'border-sky-500/40 bg-sky-500/10 text-sky-200',
  invalid: 'border-rose-500/40 bg-rose-500/10 text-rose-200',
};

const VERDICT_LABEL = {
  new: 'New',
  same: 'Already saved',
  conflict: 'Differs from vault',
  uncertain: 'Uncertain',
  invalid: 'Invalid',
};

const DEFAULT_STEPS = [
  'Copy the prompt below.',
  'Open ChatGPT or Gemini and paste the prompt.',
  'Attach your marksheets, certificates, ID or address proof.',
  'Copy the JSON reply the AI gives you.',
  'Paste that JSON in the box below and press Review changes.',
];

export default function ExtractionImportPanel({ notify, onApplied }) {
  const [prompt, setPrompt] = useState('');
  const [schemaVersion, setSchemaVersion] = useState('');
  const [promptVersion, setPromptVersion] = useState('');
  const [steps, setSteps] = useState(DEFAULT_STEPS);
  const [showPrompt, setShowPrompt] = useState(false);
  const [pasted, setPasted] = useState('');
  const [plan, setPlan] = useState(null);
  const [errors, setErrors] = useState([]);
  const [selected, setSelected] = useState({});
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    fetch('/api/vault/extraction-prompt')
      .then((res) => res.json())
      .then((data) => {
        setPrompt(data.prompt || '');
        setSchemaVersion(data.schema_version || '');
        setPromptVersion(data.prompt_version || '');
        if (Array.isArray(data.steps) && data.steps.length) setSteps(data.steps);
      })
      .catch(() => {
        if (notify) notify('Could not load the extraction prompt.', 'error');
      });
  }, [notify]);

  const copyPrompt = async () => {
    if (!prompt) return;
    try {
      await navigator.clipboard.writeText(prompt);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
      if (notify) notify('Prompt copied to clipboard! Paste it into Gemini or ChatGPT with your documents.', 'success');
    } catch (err) {
      if (notify) notify('Clipboard access blocked. Please select the prompt text and copy manually.', 'error');
    }
  };

  const openInGemini = async () => {
    if (prompt) {
      try {
        await navigator.clipboard.writeText(prompt);
      } catch (err) {}
    }
    window.open('https://gemini.google.com/app', '_blank', 'noopener,noreferrer');
    if (notify) notify('Prompt copied to clipboard! Opening Google Gemini. Attach your documents and press Ctrl+V.', 'success');
  };

  const openInChatGPT = async () => {
    if (prompt) {
      try {
        await navigator.clipboard.writeText(prompt);
      } catch (err) {}
    }
    window.open('https://chatgpt.com/', '_blank', 'noopener,noreferrer');
    if (notify) notify('Prompt copied to clipboard! Opening ChatGPT. Attach your documents and press Ctrl+V.', 'success');
  };

  const downloadPrompt = () => {
    if (!prompt) return;
    const blob = new Blob([prompt], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'formpilot-extraction-prompt.txt';
    link.click();
    URL.revokeObjectURL(url);
  };

  const review = async () => {
    setBusy(true);
    setErrors([]);
    setPlan(null);
    try {
      const res = await fetch('/api/vault/import-extraction', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ payload: pasted, apply: false }),
      });
      const data = await res.json();
      if (!res.ok || data.success === false) {
        setErrors(data.errors || [data.detail || 'That JSON could not be read.']);
        return;
      }
      setPlan(data.plan);
      const next = {};
      (data.plan.fields || []).forEach((field) => {
        next[field.key] = field.verdict === 'new' || field.verdict === 'same';
      });
      setSelected(next);
    } catch (err) {
      setErrors(['Network error while reading that JSON.']);
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!plan) return;
    const accept = Object.entries(selected)
      .filter(([, value]) => value)
      .map(([key]) => key);
    if (!accept.length) {
      if (notify) notify('Tick at least one field to apply.', 'error');
      return;
    }
    setBusy(true);
    try {
      const res = await fetch('/api/vault/import-extraction', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ payload: pasted, apply: true, accept }),
      });
      const data = await res.json();
      if (!res.ok || data.success === false) {
        setErrors(data.errors || [data.detail || 'Those fields could not be saved.']);
        return;
      }
      if (notify) notify(`${data.applied?.applied?.length || 0} details saved to your vault.`, 'success');
      if (onApplied) onApplied(data.vault);
      setPlan(null);
      setPasted('');
    } catch (err) {
      setErrors(['Network error while saving those details.']);
    } finally {
      setBusy(false);
    }
  };

  const counts = useMemo(() => plan?.summary || {}, [plan]);

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-teal-500/30 bg-teal-500/[0.07] p-4">
        <div className="flex items-start gap-2">
          <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-teal-300" />
          <div className="space-y-2 text-[11px] leading-relaxed text-teal-50/90">
            <p className="font-bold text-teal-50">
              Use the AI you already have. No FormPilot API bill.
            </p>
            <p>
              FormPilot gives you a ready prompt. You paste it into ChatGPT or Gemini,
              attach your own documents, and paste the JSON reply back here. Nothing is
              filled in automatically until you review and tick each field.
            </p>
          </div>
        </div>

        <ol className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {steps.map((step, index) => (
            <li
              key={step}
              className="flex items-start gap-2 rounded-xl border border-white/[0.07] bg-slate-950/40 px-3 py-2 text-[11px] text-slate-300"
            >
              <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-teal-400/30 bg-teal-500/10 font-mono text-[10px] font-bold text-teal-200">
                {index + 1}
              </span>
              <span>{step}</span>
            </li>
          ))}
        </ol>

        <div className="mt-4 flex flex-wrap items-center gap-2.5">
          <button
            type="button"
            onClick={openInGemini}
            className="flex min-h-[42px] items-center gap-2 rounded-xl border border-blue-500/50 bg-gradient-to-r from-blue-600 to-indigo-600 px-4 py-2 text-xs font-bold text-white transition-all hover:from-blue-500 hover:to-indigo-500 shadow-sm cursor-pointer"
          >
            <Sparkles className="h-4 w-4 text-blue-200" />
            <span>Copy & Open in Google Gemini</span>
            <ExternalLink className="h-3 w-3 opacity-80" />
          </button>
          <button
            type="button"
            onClick={openInChatGPT}
            className="flex min-h-[42px] items-center gap-2 rounded-xl border border-emerald-500/50 bg-gradient-to-r from-emerald-600 to-teal-600 px-4 py-2 text-xs font-bold text-white transition-all hover:from-emerald-500 hover:to-teal-500 shadow-sm cursor-pointer"
          >
            <ExternalLink className="h-4 w-4 text-emerald-200" />
            <span>Copy & Open in ChatGPT</span>
          </button>
          <button
            type="button"
            onClick={copyPrompt}
            className="flex min-h-[42px] items-center gap-2 rounded-xl border border-teal-400/40 bg-teal-700/80 hover:bg-teal-600 px-4 py-2 text-xs font-bold text-white transition-colors cursor-pointer"
          >
            {copied ? <CheckCheck className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
            <span>{copied ? 'Prompt copied' : 'Only copy prompt'}</span>
          </button>
          <button
            type="button"
            onClick={() => setShowPrompt((value) => !value)}
            className="flex min-h-[42px] items-center gap-2 rounded-xl border border-white/[0.1] bg-white/[0.04] px-4 py-2 text-xs font-semibold text-slate-200 transition-colors hover:bg-white/[0.08] cursor-pointer"
          >
            {showPrompt ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            <span>{showPrompt ? 'Hide prompt' : 'View full prompt'}</span>
          </button>
          <button
            type="button"
            onClick={downloadPrompt}
            className="flex min-h-[42px] items-center gap-2 rounded-xl border border-white/[0.1] bg-white/[0.03] px-4 py-2 text-xs font-semibold text-slate-300 transition-colors hover:bg-white/[0.07] cursor-pointer"
          >
            <Download className="h-4 w-4" />
            <span>Download .txt</span>
          </button>
          <span className="font-mono text-[10px] text-teal-300/80 ml-auto">
            schema {schemaVersion || 'formpilot_profile_v1'}
            {promptVersion ? ` · prompt v${promptVersion}` : ''}
          </span>
        </div>

        {showPrompt && (
          <div className="mt-3 space-y-2">
            <div className="flex items-center justify-between gap-2">
              <p className="text-[10px] font-mono uppercase tracking-wider text-slate-400">
                Copy this prompt into ChatGPT or Gemini along with your marksheets and Aadhaar
              </p>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={openInGemini}
                  className="inline-flex items-center gap-1 text-[10px] font-semibold text-blue-300 hover:text-blue-200 cursor-pointer"
                >
                  Open Gemini <ExternalLink className="h-3 w-3" />
                </button>
                <button
                  type="button"
                  onClick={openInChatGPT}
                  className="inline-flex items-center gap-1 text-[10px] font-semibold text-teal-300 hover:text-teal-200 cursor-pointer"
                >
                  Open ChatGPT <ExternalLink className="h-3 w-3" />
                </button>
              </div>
            </div>
            <textarea
              readOnly
              value={prompt}
              rows={12}
              spellCheck={false}
              aria-label="Extraction prompt to copy into ChatGPT or Gemini"
              className="w-full resize-y rounded-2xl border border-white/[0.08] bg-slate-950/70 p-3 font-mono text-[11px] leading-relaxed text-slate-300 outline-none focus:border-teal-500/60"
            />
            <p className="text-[10px] text-slate-500">
              The template is empty on purpose. The AI must fill it only from the
              documents you attach; FormPilot rejects anything it cannot verify.
            </p>
          </div>
        )}
      </div>

      <div className="space-y-2">
        <label htmlFor="ai-json-reply" className="text-[10px] font-mono uppercase tracking-wider text-slate-400">
          Paste the AI's JSON reply
        </label>
        <textarea
          id="ai-json-reply"
          value={pasted}
          onChange={(event) => setPasted(event.target.value)}
          rows={8}
          spellCheck={false}
          placeholder="Paste the JSON object here. Nothing is saved until you press Review changes."
          className="w-full rounded-2xl border border-white/[0.08] bg-slate-950/70 p-3 font-mono text-[11px] text-slate-200 outline-none transition-colors placeholder:text-slate-600 focus:border-teal-500/60"
        />
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={review}
            disabled={busy || !pasted.trim()}
            className="flex min-h-[42px] items-center gap-2 rounded-xl border border-white/[0.1] bg-white/[0.04] px-4 py-2 text-xs font-bold text-slate-200 transition-colors hover:bg-white/[0.08] disabled:opacity-40"
          >
            <Upload className="h-4 w-4" />
            <span>{busy ? 'Checking…' : 'Review changes'}</span>
          </button>
          <label className="flex min-h-[42px] cursor-pointer items-center gap-2 rounded-xl border border-white/[0.1] bg-white/[0.04] px-4 py-2 text-xs font-semibold text-slate-300 hover:bg-white/[0.08]">
            <Upload className="h-4 w-4" />
            <span>Choose .json file</span>
            <input
              type="file"
              accept=".json,application/json,.txt"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (!file) return;
                const reader = new FileReader();
                reader.onload = (loadEvent) => setPasted(String(loadEvent.target?.result || ''));
                reader.readAsText(file);
                event.target.value = '';
              }}
            />
          </label>
          {pasted && (
            <button
              type="button"
              onClick={() => {
                setPasted('');
                setPlan(null);
                setErrors([]);
              }}
              className="flex min-h-[42px] items-center gap-2 rounded-xl border border-white/[0.08] px-4 py-2 text-xs font-semibold text-slate-400 hover:bg-white/[0.06] hover:text-slate-200"
            >
              <X className="h-4 w-4" />
              <span>Clear box</span>
            </button>
          )}
        </div>
      </div>

      {errors.length > 0 && (
        <div className="space-y-1 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3.5 py-2.5 text-[11px] text-rose-200">
          {errors.map((message) => (
            <p key={message} className="flex items-start gap-2">
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{message}</span>
            </p>
          ))}
        </div>
      )}

      {plan && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            {Object.entries(VERDICT_LABEL).map(([verdict, label]) =>
              counts[verdict] ? (
                <span
                  key={verdict}
                  className={`rounded-full border px-2.5 py-1 text-[10px] font-bold ${VERDICT_STYLE[verdict]}`}
                >
                  {counts[verdict]} {label}
                </span>
              ) : null
            )}
          </div>

          <div className="overflow-x-auto rounded-2xl border border-white/[0.08]">
            <table className="w-full min-w-[640px] text-left text-[11px]">
              <thead className="bg-white/[0.03] text-[10px] uppercase tracking-wider text-slate-400">
                <tr>
                  <th className="px-3 py-2">Use</th>
                  <th className="px-3 py-2">Detail</th>
                  <th className="px-3 py-2">From document</th>
                  <th className="px-3 py-2">Saved now</th>
                  <th className="px-3 py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {(plan.fields || []).map((field) => (
                  <tr key={field.key} className="border-t border-white/[0.06]">
                    <td className="px-3 py-2">
                      <input
                        type="checkbox"
                        checked={Boolean(selected[field.key])}
                        disabled={field.verdict === 'invalid'}
                        onChange={(event) =>
                          setSelected((prev) => ({ ...prev, [field.key]: event.target.checked }))
                        }
                        className="h-4 w-4 rounded border-slate-600 bg-slate-900"
                      />
                    </td>
                    <td className="px-3 py-2 font-semibold text-slate-200">{field.label}</td>
                    <td className="px-3 py-2 font-mono text-emerald-200">{field.value || '—'}</td>
                    <td className="px-3 py-2 font-mono text-slate-400">{field.current || '—'}</td>
                    <td className="px-3 py-2">
                      <span className={`rounded-full border px-2 py-0.5 text-[9px] font-bold ${VERDICT_STYLE[field.verdict] || ''}`}>
                        {VERDICT_LABEL[field.verdict] || field.verdict}
                      </span>
                      {field.note && <p className="mt-1 text-[9px] text-slate-400">{field.note}</p>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {Object.keys(plan.extras || {}).length > 0 && (
            <div className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-3">
              <p className="text-[10px] font-mono uppercase tracking-wider text-slate-400">
                Extra details kept for later
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                {Object.entries(plan.extras).map(([key, value]) => (
                  <span key={key} className="rounded-lg border border-white/[0.08] bg-slate-950/60 px-2 py-1 font-mono text-[10px] text-slate-300">
                    {key}: {value}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={apply}
              disabled={busy}
              className="flex min-h-[42px] items-center gap-2 rounded-xl border border-emerald-500/40 bg-emerald-600 px-4 py-2 text-xs font-bold text-white transition-colors hover:bg-emerald-500 disabled:opacity-50"
            >
              <Check className="h-4 w-4" />
              <span>{busy ? 'Saving…' : 'Apply ticked fields'}</span>
            </button>
            <button
              type="button"
              onClick={() => setPlan(null)}
              className="flex min-h-[42px] items-center gap-2 rounded-xl border border-white/[0.1] bg-white/[0.03] px-4 py-2 text-xs font-semibold text-slate-300 hover:bg-white/[0.07]"
            >
              <X className="h-4 w-4" />
              <span>Discard</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
