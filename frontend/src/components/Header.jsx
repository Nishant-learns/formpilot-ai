import React from 'react';
import {
  BookOpen,
  Cloud,
  FileText,
  KeyRound,
  LogOut,
  Pause,
  Play,
  Settings,
} from 'lucide-react';
import {
  NeuralSparkleIcon,
  SecurityShieldIcon,
  AudioWaveformIcon,
  BiometricFingerprintIcon,
  CommandKeyIcon,
} from './CustomIcons';

function ReadinessRing({ percent }) {
  const value = Math.max(0, Math.min(100, Number(percent) || 0));
  const radius = 9;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (value / 100) * circumference;
  return (
    <span className="relative flex h-7 w-7 items-center justify-center">
      <svg viewBox="0 0 24 24" className="h-7 w-7 -rotate-90">
        <circle cx="12" cy="12" r={radius} fill="none" stroke="currentColor" strokeWidth="2.4" className="text-slate-800" />
        <circle
          cx="12"
          cy="12"
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth="2.4"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className={value >= 80 ? 'text-emerald-400' : value >= 50 ? 'text-indigo-400' : 'text-amber-400'}
        />
      </svg>
      <span className="absolute text-[8px] font-extrabold text-slate-200">{value}</span>
    </span>
  );
}

export default function Header({
  agentRunning,
  paused,
  runState,
  engineConfig,
  readiness,
  onSelectNav,
  onOpenSettings,
  onOpenVault,
  onOpenBiometrics,
  onPauseToggle,
  voiceEnabled,
  setVoiceEnabled,
  currentGate,
  copilotDocked,
  copilotMinimized,
  onToggleCopilot,
  account,
  accountsEnabled,
  onOpenAuth,
  onLogout,
}) {
  const navigate = (page) => {
    if (onSelectNav) {
      onSelectNav(page);
    } else {
      if (page === 'vault' && onOpenVault) onOpenVault();
      if (page === 'biometrics' && onOpenBiometrics) onOpenBiometrics();
      if (page === 'settings' && onOpenSettings) onOpenSettings();
    }
  };

  const cloudActive = engineConfig?.effective_mode === 'cloud' || engineConfig?.mode === 'cloud';
  const paymentReview = currentGate?.gate_type === 'PRE_PAYMENT_SAFETY_LOCK';
  const inspectReady = runState === 'INSPECT_READY';
  const finished = ['STOPPED', 'FAILED', 'COMPLETED'].includes(runState);
  const active = agentRunning && !paused;

  return (
    <header className="sticky top-0 z-40 border-b border-white/[0.08] bg-[#0d1210]/80 px-3 py-2.5 backdrop-blur-2xl specular-top sm:px-5">
      <div className="mx-auto flex w-full max-w-[1560px] items-center justify-between gap-3">
        {/* Brand */}
        <div className="flex min-w-0 items-center gap-3">
          <div className="relative shrink-0">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-emerald-500/40 bg-gradient-to-br from-emerald-500 via-emerald-600 to-teal-700 text-xs font-black text-white shadow-lg shadow-emerald-500/25">
              <NeuralSparkleIcon className="w-5 h-5 text-white" />
            </div>
            <span className={`absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-[#0d1210] ${active ? 'animate-pulse bg-emerald-400' : paused ? 'bg-amber-400' : 'bg-slate-600'}`} />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="text-sm font-extrabold tracking-tight flex items-center">
                <span className="text-emerald-400">Form</span>
                <span className="bg-gradient-to-r from-emerald-400 via-teal-300 to-amber-200 bg-clip-text text-transparent">Pilot</span>
              </h1>
              <span className="hidden rounded-full border border-indigo-500/30 bg-indigo-500/10 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-indigo-300 sm:inline">
                Autonomous Co-Pilot
              </span>
            </div>
            <p className="hidden items-center gap-1.5 text-[11px] text-slate-400 sm:flex">
              <SecurityShieldIcon className="h-3.5 w-3.5 text-emerald-400" />
              <span>Institutional Safety</span>
              <span className="text-slate-700">•</span>
              <span className={cloudActive ? 'text-sky-300' : 'text-slate-400'}>
                <Cloud className="mr-0.5 inline h-3 w-3" />
                {cloudActive ? 'Cloud browser' : 'On this device'}
              </span>
            </p>
          </div>
        </div>

        {/* Live state */}
        <div
          className={`hidden items-center gap-2 rounded-full border px-3.5 py-1.5 text-xs font-semibold backdrop-blur-md md:flex shadow-sm transition-all ${
            paymentReview
              ? 'border-amber-500/40 bg-amber-500/10 text-amber-300 glow-amber'
              : paused
                ? 'border-amber-500/40 bg-amber-500/10 text-amber-300'
                : inspectReady
                  ? 'border-sky-500/40 bg-sky-500/10 text-sky-300'
                  : active
                    ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300 glow-emerald'
                    : 'border-white/[0.08] bg-white/[0.04] text-slate-300'
          }`}
        >
          <span className={`h-2 w-2 rounded-full ${active ? 'bg-emerald-400 animate-pulse' : paused ? 'bg-amber-400' : finished ? 'bg-slate-500' : 'bg-emerald-400'}`} />
          <span>
            {paymentReview
              ? currentGate?.final_action === 'submission'
                ? 'Review before submitting'
                : 'Review before payment'
              : paused
                ? 'Paused by you'
                : inspectReady
                  ? 'Inspect mode · Mapping page'
                  : finished
                    ? 'Session concluded'
                    : active
                      ? 'Live filling in progress'
                      : 'AI Assistant ready'}
          </span>
        </div>

        {/* Controls */}
        <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
          {agentRunning && !currentGate && onPauseToggle && (
            <button
              type="button"
              onClick={onPauseToggle}
              className={`flex items-center gap-1.5 rounded-xl border px-2.5 py-1.5 text-xs font-semibold transition-all ${
                paused
                  ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25 glow-emerald'
                  : 'border-white/[0.08] bg-white/[0.04] text-slate-200 hover:bg-white/[0.08]'
              }`}
              title={paused ? 'Resume the agent' : 'Pause the agent'}
            >
              {paused ? <Play className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />}
              <span className="hidden xl:inline">{paused ? 'Resume' : 'Pause'}</span>
            </button>
          )}

          <button
            type="button"
            onClick={() => navigate('vault')}
            className="flex items-center gap-2 rounded-xl border border-white/[0.09] bg-white/[0.04] hover:bg-white/[0.08] hover:border-emerald-500/30 px-2.5 py-1.5 text-xs font-semibold text-slate-200 transition-all shadow-sm"
            title={readiness ? `Profile ${readiness.percent}% ready — ${readiness.filled} of ${readiness.total} core details saved` : 'Open your saved details'}
          >
            {readiness ? <ReadinessRing percent={readiness.percent} /> : <FileText className="h-4 w-4 text-emerald-400" />}
            <span className="hidden sm:inline">Vault</span>
            {readiness && <span className="font-mono text-[10px] text-emerald-300 bg-emerald-950/60 px-1.5 py-0.5 rounded-full border border-emerald-500/30">{readiness.percent}%</span>}
          </button>

          <button
            type="button"
            onClick={() => setVoiceEnabled(!voiceEnabled)}
            className={`hidden items-center gap-1.5 rounded-xl border px-2.5 py-1.5 text-xs font-medium transition-all sm:flex shadow-sm ${
              voiceEnabled
                ? 'border-indigo-500/40 bg-indigo-500/15 text-indigo-200 shadow-indigo-500/10'
                : 'border-white/[0.08] bg-white/[0.03] text-slate-400 hover:bg-white/[0.06] hover:text-slate-200'
            }`}
            title="Spoken voice guidance"
          >
            <AudioWaveformIcon active={voiceEnabled} className="h-3.5 w-3.5" />
            <span className="hidden xl:inline">{voiceEnabled ? 'Voice on' : 'Voice off'}</span>
          </button>

          <button
            type="button"
            onClick={() => navigate('biometrics')}
            className="hidden items-center gap-1.5 rounded-xl border border-white/[0.08] bg-white/[0.03] hover:bg-white/[0.06] px-2.5 py-1.5 text-xs font-medium text-slate-300 hover:text-slate-100 transition-all shadow-sm sm:flex"
            title="Photo and signature studio"
          >
            <BiometricFingerprintIcon className="h-3.5 w-3.5 text-violet-400" />
            <span className="hidden xl:inline">Studio</span>
          </button>

          <button
            type="button"
            onClick={() => navigate('help')}
            className="rounded-xl border border-white/[0.08] bg-white/[0.03] hover:bg-white/[0.06] p-2 text-slate-400 hover:text-slate-100 transition-all shadow-sm"
            title="Help, guide and safety rules"
            aria-label="Help and guide"
          >
            <BookOpen className="h-4 w-4" />
          </button>



          {!account && accountsEnabled && onOpenAuth && (
            <button
              type="button"
              onClick={onOpenAuth}
              className="hidden items-center gap-1.5 rounded-xl border border-emerald-400/25 bg-emerald-500/10 px-2.5 py-1.5 text-xs font-semibold text-emerald-200 transition-all hover:bg-emerald-500/20 md:flex"
              title="Sign in or create a FormPilot account"
            >
              <KeyRound className="h-3.5 w-3.5" />
              <span>Sign in</span>
            </button>
          )}

          {account && (
            <div className="hidden items-center gap-1.5 rounded-xl border border-white/[0.08] bg-white/[0.03] py-1 pl-1 pr-1.5 md:flex">
              <span className="flex h-6 w-6 items-center justify-center rounded-lg border border-white/10 bg-slate-800 text-[9px] font-bold text-slate-300">
                {(account.name || account.email || 'U').slice(0, 2).toUpperCase()}
              </span>
              <span className="max-w-[110px] truncate text-[11px] font-semibold text-slate-200" title={account.email}>
                {account.name || account.email}
              </span>
              {onLogout && (
                <button
                  type="button"
                  onClick={onLogout}
                  className="rounded-lg p-1 text-slate-500 transition-colors hover:bg-white/[0.06] hover:text-slate-200"
                  title="Sign out of FormPilot"
                  aria-label="Sign out"
                >
                  <LogOut className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          )}

          {onToggleCopilot && (
            <button
              type="button"
              onClick={onToggleCopilot}
              className={`hidden items-center gap-1.5 rounded-xl border px-2.5 py-1.5 text-xs font-semibold transition-all shadow-sm sm:flex ${
                copilotDocked && !copilotMinimized
                  ? 'border-indigo-500/40 bg-indigo-500/15 text-indigo-200 shadow-indigo-500/10'
                  : 'border-white/[0.08] bg-white/[0.03] text-slate-400 hover:bg-white/[0.06] hover:text-slate-200'
              }`}
              title={copilotDocked && !copilotMinimized ? 'Collapse Copilot inspector' : 'Expand Copilot inspector'}
            >
              <NeuralSparkleIcon className="h-3.5 w-3.5 text-indigo-400" />
              <span className="hidden xl:inline">Copilot</span>
              <span className={`w-1.5 h-1.5 rounded-full ${copilotDocked && !copilotMinimized ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'}`} />
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
