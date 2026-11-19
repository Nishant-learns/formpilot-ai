import React, { useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  Send,
  Sparkles,
  CheckCircle2,
  Trash2,
  PauseCircle,
  PlayCircle,
  Search,
  Clock,
} from 'lucide-react';

const WELCOME = {
  sender: 'FormPilot',
  text: "Hi! I'm here while you fill this application. Ask me about a document or a step, or tell me a saved detail you want to correct. You can also ask me to pause or show your progress.",
  time: 'Now',
  action_taken: 'GREETING',
};

function FormattedMessage({ text, isUser }) {
  if (!text) return null;
  if (isUser) {
    return <div className="whitespace-pre-wrap break-words text-sm leading-relaxed">{text}</div>;
  }

  const lines = text.split('\n');

  const formatInline = (str) => {
    const parts = [];
    const regex = /(\*\*.*?\*\*|`.*?`|https?:\/\/[^\s]+)/g;
    let lastIndex = 0;
    let match;

    while ((match = regex.exec(str)) !== null) {
      if (match.index > lastIndex) {
        parts.push(str.substring(lastIndex, match.index));
      }
      const token = match[0];
      if (token.startsWith('**') && token.endsWith('**')) {
        parts.push(
          <strong key={match.index} className="font-bold text-white tracking-wide">
            {token.slice(2, -2)}
          </strong>
        );
      } else if (token.startsWith('`') && token.endsWith('`')) {
        parts.push(
          <code
            key={match.index}
            className="rounded bg-black/50 px-1.5 py-0.5 font-mono text-[12px] font-medium text-emerald-300 border border-emerald-500/20"
          >
            {token.slice(1, -1)}
          </code>
        );
      } else if (token.startsWith('http')) {
        parts.push(
          <a
            key={match.index}
            href={token}
            target="_blank"
            rel="noreferrer"
            className="text-sky-300 underline decoration-sky-400/40 hover:text-sky-200"
          >
            {token}
          </a>
        );
      }
      lastIndex = regex.lastIndex;
    }
    if (lastIndex < str.length) {
      parts.push(str.substring(lastIndex));
    }
    return parts.length ? parts : str;
  };

  return (
    <div className="space-y-1.5 break-words text-[13.5px] sm:text-[14px] leading-relaxed text-slate-100 font-normal">
      {lines.map((line, idx) => {
        const trimmed = line.trim();
        if (!trimmed) {
          return <div key={idx} className="h-2" />;
        }

        const bulletMatch = trimmed.match(/^([•\-\*]|\d+\.)\s+(.+)$/);
        if (bulletMatch) {
          const marker = bulletMatch[1];
          const content = bulletMatch[2];
          const isNum = /\d+\./.test(marker);
          return (
            <div key={idx} className="flex items-start gap-2.5 pl-0.5 py-1">
              {isNum ? (
                <span className="shrink-0 flex h-5 w-5 items-center justify-center rounded-md bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 font-bold text-[11px] mt-0.5 select-none">
                  {marker.replace('.', '')}
                </span>
              ) : (
                <span className="shrink-0 flex h-4 w-4 items-center justify-center rounded-full bg-emerald-500/25 text-emerald-300 font-black text-xs mt-1 select-none">
                  •
                </span>
              )}
              <div className="flex-1 text-slate-100 leading-relaxed">{formatInline(content)}</div>
            </div>
          );
        }

        const isHeading = trimmed.startsWith('#') || (trimmed.startsWith('**') && trimmed.endsWith('**') && !trimmed.slice(2, -2).includes('**'));
        if (isHeading) {
          const headingText = trimmed.replace(/^#+\s*/, '').replace(/^\*\*|\*\*$/g, '');
          return (
            <div key={idx} className="font-extrabold text-white text-[15px] sm:text-[15.5px] pt-2 pb-1 tracking-tight flex items-center gap-2 border-b border-emerald-500/30 mb-2 mt-1">
              <span className="h-2 w-2 rounded-full bg-emerald-400 shrink-0 shadow-sm shadow-emerald-400" />
              <span>{headingText}</span>
            </div>
          );
        }

        return (
          <div key={idx} className="text-slate-100 leading-relaxed py-0.5">
            {formatInline(trimmed)}
          </div>
        );
      })}
    </div>
  );
}

export default function LiveChat({
  onSendMessage,
  chatMessages,
  voiceEnabled,
  onClearChat,
  entryMode,
  entryOptions,
  loginMethod,
  loginIdentifier,
  activeGate,
}) {
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [aiConfigured, setAiConfigured] = useState(null);
  const scrollRef = useRef(null);
  const lastSpokenRef = useRef(WELCOME.text);

  const messages = chatMessages?.length ? chatMessages : [WELCOME];

  useEffect(() => {
    let cancelled = false;
    fetch('/api/chat/config')
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!cancelled && data) setAiConfigured(Boolean(data.configured));
      })
      .catch(() => {
        if (!cancelled) setAiConfigured(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, loading]);

  useEffect(() => {
    if (!voiceEnabled || !messages.length) return;
    const latest = messages[messages.length - 1];
    if (latest.sender === 'Candidate') return;
    if (!latest.text || latest.text === lastSpokenRef.current) return;
    if (!('speechSynthesis' in window)) return;

    lastSpokenRef.current = latest.text;
    try {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(latest.text);
      utterance.lang = 'hi-IN';
      utterance.rate = 1.05;
      window.speechSynthesis.speak(utterance);
    } catch (err) {
      // Voice is optional; text is always available.
    }
  }, [messages, voiceEnabled]);

  const handleSend = async (textToSend) => {
    const text = (textToSend || input).trim();
    if (!text || loading) return;

    setInput('');
    setLoading(true);
    try {
      if (onSendMessage) {
        await onSendMessage(text);
      }
    } catch (err) {
      console.error('Chat send error:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const quickChips = [
    { label: '🎯 JEE Main rules', query: 'What are the eligibility and photo rules for JEE Main 2026?' },
    { label: 'Documents I need', query: 'Which documents do I need for this application?' },
    { label: 'Update my date of birth', query: 'Change my date of birth to 15/08/2004' },
    { label: 'Photo requirements', query: 'What are the photo and signature requirements?' },
    { label: 'Is the fee refundable?', query: 'Is the application fee refundable?' },
    { label: 'Show my progress', query: 'What is my current status?' },
  ];

  const gateType = activeGate?.gate_type || '';
  const gateOptions = activeGate?.options || [];
  const entryNeeded = gateType === 'GATEWAY_DECISION' || (!entryMode && (entryOptions?.length || 0) > 0);
  const entryChoices = gateType === 'GATEWAY_DECISION'
    ? gateOptions
    : (entryOptions || []);
  const entryChips = entryNeeded
    ? entryChoices.slice(0, 4).map((option) => ({
        label: option.text || option.mode || option.type || 'Entry path',
        query: option.text || option.mode || option.type,
      }))
    : [];
  const loginChips = gateType === 'LOGIN_METHOD'
    ? gateOptions.slice(0, 4).map((option) => ({
        label: option.label || option.text || option.method,
        query: option.label || option.text || option.method,
      }))
    : [];
  const identifierChips = gateType === 'ACCOUNT_IDENTIFIER'
    ? gateOptions.slice(0, 4).map((option) => ({
        label: option.text || option.key,
        query: option.text || option.key,
      }))
    : [];
  const fillChips = gateType === 'FILL_INCOMPLETE'
    ? [
        { label: 'Recheck fields', query: 'Recheck the fields and fill again' },
        { label: 'Continue after review', query: 'Continue after reviewing the form' },
      ]
    : [];
  const gateChips = [...fillChips, ...entryChips, ...loginChips, ...identifierChips];
  const chips = gateChips.length
    ? [...gateChips, ...quickChips.slice(0, 2)]
    : quickChips;
  const entryBadge = entryMode === 'register'
    ? 'Creating account'
    : entryMode === 'login'
      ? 'Signing in'
      : entryMode === 'resume'
        ? 'Resuming'
        : entryMode === 'manual'
          ? 'Entry chosen by you'
          : '';
  const methodBadge = loginMethod ? String(loginMethod).replace(/_/g, ' ') : '';
  const identifierBadge = loginIdentifier ? String(loginIdentifier).replace(/_/g, ' ') : '';

  return (
    <div className="glass-panel rounded-2xl flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="p-3.5 bg-white/[0.02] border-b border-white/[0.08] flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2.5">
          <div className="relative">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-indigo-500 via-indigo-600 to-violet-700 flex items-center justify-center text-white font-black text-xs shadow-md shadow-indigo-500/20 border border-indigo-400/30">
              FP
            </div>
            <span className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 bg-emerald-400 rounded-full border border-[#0d1210] animate-pulse" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-xs font-bold text-slate-100">Ask FormPilot</h3>
              <span className="text-[10px] font-semibold text-indigo-300 bg-indigo-500/10 px-2 py-0.5 rounded-full border border-indigo-500/30">
                Copilot
              </span>
            </div>
            <p className="text-[11px] text-slate-400">
              Instant guidance, saved details, and stage actions
            </p>
            {(entryBadge || methodBadge || identifierBadge) && (
              <div className="mt-1 flex flex-wrap items-center gap-1">
                {entryBadge && (
                  <span className="rounded-full border border-sky-500/30 bg-sky-950/60 px-2 py-0.5 text-[9px] font-semibold text-sky-300">
                    {entryBadge}
                  </span>
                )}
                {methodBadge && (
                  <span className="rounded-full border border-emerald-500/30 bg-emerald-950/60 px-2 py-0.5 text-[9px] font-semibold text-emerald-300">
                    {methodBadge}
                  </span>
                )}
                {identifierBadge && (
                  <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[9px] font-semibold text-slate-300">
                    {identifierBadge}
                  </span>
                )}
              </div>
            )}
          </div>
        </div>

        <button
          type="button"
          onClick={() => onClearChat?.()}
          className="p-1.5 rounded-xl text-slate-400 hover:text-slate-200 hover:bg-white/[0.06] transition-colors"
          title="Clear conversation"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Messages Stream */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3.5 bg-transparent">
        {aiConfigured === false && (
          <div className="rounded-xl border border-indigo-500/30 bg-indigo-500/10 px-3 py-2 text-xs text-indigo-200">
            The AI model is not configured yet. Add a model key in Settings → AI assistant to enable free-form reasoning and automated execution.
          </div>
        )}
        {messages.map((m, i) => {
          const isUser = m.sender === 'Candidate';
          return (
            <div
              key={`${m.time}-${i}-${m.sender}`}
              className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} animate-fadeIn`}
            >
              <div className="flex items-center gap-1.5 mb-1 text-[11px] text-slate-400 font-medium">
                {isUser ? (
                  <>
                    <span className="text-indigo-300 font-bold">You</span>
                    <Clock className="w-3 h-3 text-slate-500" />
                    <span>{m.time}</span>
                  </>
                ) : (
                  <>
                    <span className="text-emerald-400 font-bold">FormPilot Copilot</span>
                    <Clock className="w-3 h-3 text-slate-500" />
                    <span>{m.time}</span>
                  </>
                )}
              </div>

              <div
                className={`transition-all ${
                  isUser
                    ? 'max-w-[90%] sm:max-w-[85%] rounded-2xl rounded-tr-sm bg-gradient-to-r from-indigo-600 via-indigo-600 to-violet-700 text-white font-medium px-4 py-3 shadow-md shadow-indigo-600/25 border border-indigo-400/30 text-sm leading-relaxed'
                    : 'max-w-[95%] sm:max-w-[88%] rounded-2xl rounded-tl-sm bg-[#121b16] border border-white/12 text-slate-100 px-4 py-3.5 shadow-xl shadow-black/40 text-sm leading-relaxed'
                }`}
              >
                <FormattedMessage text={m.text} isUser={isUser} />

                {m.action_taken === 'FIELD_UPDATED' && (
                  <div className="mt-2.5 pt-2 border-t border-white/10 flex items-center gap-1.5 text-xs text-emerald-300 font-semibold bg-emerald-500/10 px-2 py-1 rounded-lg">
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                    <span>Updated: {m.field_updated} → {m.new_value}</span>
                  </div>
                )}
                {m.action_taken === 'PAUSED' && (
                  <div className="mt-2.5 pt-2 border-t border-white/10 flex items-center gap-1.5 text-xs text-amber-300 font-semibold bg-amber-500/10 px-2 py-1 rounded-lg">
                    <PauseCircle className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                    <span>Application paused</span>
                  </div>
                )}
                {m.action_taken === 'RESUMED' && (
                  <div className="mt-2.5 pt-2 border-t border-white/10 flex items-center gap-1.5 text-xs text-emerald-300 font-semibold bg-emerald-500/10 px-2 py-1 rounded-lg">
                    <PlayCircle className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                    <span>Application resumed</span>
                  </div>
                )}
                {m.action_taken === 'LIVE_SEARCH' && (
                  <div className="mt-2.5 pt-2 border-t border-white/10 flex items-center gap-1.5 text-xs text-cyan-300 font-semibold bg-cyan-500/10 px-2 py-1 rounded-lg">
                    <Search className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
                    <span>Verified official web results</span>
                  </div>
                )}
                {['ENTRY_MODE_SELECTED', 'ENTRY_MODE_REQUESTED'].includes(m.action_taken) && (
                  <div className="mt-2.5 pt-2 border-t border-white/10 flex items-center gap-1.5 text-xs text-sky-300 font-semibold bg-sky-500/10 px-2 py-1 rounded-lg">
                    <CheckCircle2 className="w-3.5 h-3.5 text-sky-300 shrink-0" />
                    <span>Entry path: {m.entry_mode || 'selected'}</span>
                  </div>
                )}
                {m.action_taken === 'LOGIN_METHOD_SELECTED' && (
                  <div className="mt-2.5 pt-2 border-t border-white/10 flex items-center gap-1.5 text-xs text-emerald-300 font-semibold bg-emerald-500/10 px-2 py-1 rounded-lg">
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-300 shrink-0" />
                    <span>Sign-in method: {String(m.login_method || '').replace(/_/g, ' ')}</span>
                  </div>
                )}
                {m.action_taken === 'ACCOUNT_IDENTIFIER_SELECTED' && (
                  <div className="mt-2.5 pt-2 border-t border-white/10 flex items-center gap-1.5 text-xs text-slate-300 font-semibold bg-white/5 px-2 py-1 rounded-lg">
                    <CheckCircle2 className="w-3.5 h-3.5 text-slate-300 shrink-0" />
                    <span>Account identified by: {String(m.login_identifier || '').replace(/_/g, ' ')}</span>
                  </div>
                )}
                {['FILL_RECHECK', 'FILL_CONTINUE', 'FILL_INCOMPLETE'].includes(m.action_taken) && (
                  <div className="mt-2.5 pt-2 border-t border-white/10 flex items-center gap-1.5 text-xs text-amber-300 font-semibold bg-amber-500/10 px-2 py-1 rounded-lg">
                    <AlertTriangle className="w-3.5 h-3.5 text-amber-300 shrink-0" />
                    <span>
                      {m.action_taken === 'FILL_RECHECK'
                        ? 'Rechecking every field'
                        : m.action_taken === 'FILL_CONTINUE'
                          ? 'Continuing with an incomplete fill recorded'
                          : 'Some fields are not filled'}
                    </span>
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {loading && (
          <div className="flex items-center gap-2 text-sm text-emerald-400 animate-pulse py-1 font-medium">
            <Sparkles className="w-4 h-4 animate-spin text-emerald-400" />
            <span>FormPilot is reasoning…</span>
          </div>
        )}
      </div>

      {/* Suggested Prompt Chips */}
      <div className="px-3 py-2 bg-white/[0.02] border-t border-white/[0.08] flex items-center gap-2 overflow-x-auto no-scrollbar shrink-0">
        {chips.map((chip, idx) => (
          <button
            key={`${chip.label}-${idx}`}
            type="button"
            onClick={() => handleSend(chip.query)}
            className="whitespace-nowrap px-3.5 py-1.5 rounded-xl bg-white/[0.05] hover:bg-emerald-500/15 text-slate-200 hover:text-emerald-200 text-xs font-semibold border border-white/10 hover:border-emerald-500/40 transition-all shrink-0 shadow-sm"
          >
            {chip.label}
          </button>
        ))}
      </div>

      {/* Omnibox Input */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          handleSend();
        }}
        className="p-3 bg-[#0d1210]/95 border-t border-white/[0.08] flex items-center gap-2 shrink-0"
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about documents, JEE Main rules, or update your profile…"
          className="flex-1 px-4 py-2.5 rounded-xl glass-input text-slate-100 placeholder-slate-400 text-sm font-medium outline-none transition-all focus:border-emerald-500/50"
        />

        <button
          type="submit"
          disabled={!input.trim() || loading}
          className="px-4 py-2.5 rounded-xl bg-gradient-to-r from-emerald-500 via-emerald-600 to-teal-600 hover:from-emerald-400 hover:to-teal-500 text-white font-bold text-xs flex items-center gap-1.5 shadow-md shadow-emerald-500/20 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
        >
          <span>Send</span>
          <Send className="w-3.5 h-3.5" />
        </button>
      </form>
    </div>
  );
}
