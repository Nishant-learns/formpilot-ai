import React from 'react';
import {
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Code2,
  Layers,
  Lock,
  LogOut,
  Radio,
  Settings,
  ShieldCheck,
  Terminal,
  User,
  Zap,
} from 'lucide-react';
import {
  BiometricFaceScanIcon,
  BiometricFingerprintIcon,
  NeuralSparkleIcon,
  SecurityShieldIcon,
  UPSCSealIcon,
} from './CustomIcons';

export default function Sidebar({
  collapsed,
  onToggleCollapse,
  activeItem,
  onSelectNav,
  sessionVisible,
  agentRunning,
  liveSession,
  formMap,
  readiness,
  currentGate,
  onOpenVault,
  onOpenBiometrics,
  onOpenSettings,
  vault,
  account,
  accountsEnabled,
  onOpenAuth,
  onLogout,
}) {
  const portalName = formMap?.portal || liveSession?.portal || (liveSession?.url ? new URL(liveSession.url).hostname : 'Active Portal');

  return (
    <aside
      className={`hidden lg:flex glass-panel specular-top border-r border-white/[0.08] transition-all duration-300 flex-col shrink-0 z-30 select-none ${
        collapsed ? 'w-[68px]' : 'w-64'
      }`}
    >
      {/* Brand Header */}
      <div className="p-3.5 border-b border-white/[0.08] flex items-center justify-between gap-2">
        <div className="flex items-center gap-2.5 overflow-hidden">
          <div className="w-9 h-9 rounded-2xl bg-gradient-to-tr from-emerald-600 via-emerald-500 to-teal-500 flex items-center justify-center text-white font-black text-sm shrink-0 shadow-lg shadow-emerald-500/25 border border-emerald-400/40">
            <span className="tracking-tighter">FP</span>
          </div>
          {!collapsed && (
            <div className="min-w-0 transition-opacity duration-200">
              <div className="flex items-center gap-1.5">
                <h2 className="text-xs font-black tracking-wider uppercase truncate">
                  <span className="text-emerald-400">Form</span><span className="text-teal-300">Pilot</span>
                </h2>
                <span className="text-[9px] font-mono px-1.5 py-0.2 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 font-bold uppercase">
                  v2.4
                </span>
              </div>
              <p className="text-[10px] text-slate-400 font-mono truncate">Autonomous GovTech Agent</p>
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={onToggleCollapse}
          className="p-1.5 rounded-xl text-slate-400 hover:text-white hover:bg-white/[0.06] transition-colors"
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
      </div>

      {/* Active Session Status Pill */}
      {sessionVisible && !collapsed && (
        <div className="p-3 border-b border-white/[0.08]">
          <div className="p-2.5 rounded-2xl bg-gradient-to-br from-indigo-950/40 via-slate-900/60 to-slate-950 border border-indigo-500/30 shadow-inner">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <span className="relative flex h-2.5 w-2.5 shrink-0">
                  <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${agentRunning ? 'bg-emerald-400' : 'bg-amber-400'}`} />
                  <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${agentRunning ? 'bg-emerald-500' : 'bg-amber-500'}`} />
                </span>
                <span className="text-[11px] font-bold text-white truncate font-mono">
                  {portalName}
                </span>
              </div>
              <span className="text-[9px] font-mono text-emerald-400 font-bold bg-emerald-500/10 px-1.5 py-0.5 rounded border border-emerald-500/20">
                {agentRunning ? 'LIVE' : 'ACTIVE'}
              </span>
            </div>
            {readiness && (
              <div className="mt-2 flex items-center justify-between text-[10px] font-mono text-slate-400">
                <span>Profile Match:</span>
                <span className="text-emerald-400 font-bold">{readiness.percent}%</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Primary Navigation */}
      <nav className="flex-1 p-2 space-y-1 overflow-y-auto">
        {!collapsed && (
          <div className="px-2 pt-2 pb-1 text-[9px] font-bold text-slate-400 uppercase tracking-widest font-mono">
            Cockpit Workstation
          </div>
        )}

        {/* 1. Live Portal Viewport */}
        <button
          type="button"
          onClick={() => onSelectNav('portal')}
          className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-2xl text-xs font-semibold transition-all ${
            activeItem === 'portal'
              ? 'bg-indigo-500/20 text-indigo-200 border border-indigo-500/40 shadow-sm shadow-indigo-500/20'
              : 'text-slate-400 hover:text-white hover:bg-white/[0.04] border border-transparent'
          }`}
          title="Live Portal Viewport"
        >
          <div className="w-5 h-5 flex items-center justify-center shrink-0">
            <Radio className="w-4 h-4 text-indigo-400" />
          </div>
          {!collapsed && (
            <div className="flex-1 text-left flex items-center justify-between min-w-0">
              <span className="truncate">Live Portal</span>
              {sessionVisible && (
                <span className="text-[9px] font-mono px-1.5 py-0.5 rounded-full bg-emerald-500/15 text-emerald-300 font-bold">
                  Active
                </span>
              )}
            </div>
          )}
        </button>

        {/* 2. OneVault Identity */}
        <button
          type="button"
          onClick={() => onSelectNav('vault')}
          className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-2xl text-xs font-semibold transition-all ${
            activeItem === 'vault'
              ? 'bg-indigo-500/20 text-indigo-200 border border-indigo-500/40 shadow-sm shadow-indigo-500/20'
              : 'text-slate-400 hover:text-white hover:bg-white/[0.04] border border-transparent'
          }`}
          title="OneVault Identity"
        >
          <div className="w-5 h-5 flex items-center justify-center shrink-0">
            <SecurityShieldIcon className="w-4 h-4 text-emerald-400" />
          </div>
          {!collapsed && (
            <div className="flex-1 text-left flex items-center justify-between min-w-0">
              <span className="truncate">OneVault Identity</span>
              <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-bold">
                AES
              </span>
            </div>
          )}
        </button>

        {/* 3. Biometrics Studio */}
        <button
          type="button"
          onClick={() => onSelectNav('biometrics')}
          className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-2xl text-xs font-semibold transition-all ${
            activeItem === 'biometrics'
              ? 'bg-indigo-500/20 text-indigo-200 border border-indigo-500/40 shadow-sm shadow-indigo-500/20'
              : 'text-slate-400 hover:text-white hover:bg-white/[0.04] border border-transparent'
          }`}
          title="Biometrics Studio"
        >
          <div className="w-5 h-5 flex items-center justify-center shrink-0">
            <BiometricFaceScanIcon className="w-4 h-4 text-violet-400" />
          </div>
          {!collapsed && (
            <div className="flex-1 text-left flex items-center justify-between min-w-0">
              <span className="truncate">Biometrics Studio</span>
              <span className="text-[9px] font-mono text-slate-500">
                UPSC/SSC
              </span>
            </div>
          )}
        </button>

        {/* 4. Merkle Audit Ledger */}
        <button
          type="button"
          onClick={() => onSelectNav('runs')}
          className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-2xl text-xs font-semibold transition-all ${
            activeItem === 'runs'
              ? 'bg-indigo-500/20 text-indigo-200 border border-indigo-500/40 shadow-sm shadow-indigo-500/20'
              : 'text-slate-400 hover:text-white hover:bg-white/[0.04] border border-transparent'
          }`}
          title="Merkle Audit Ledger & Run History"
        >
          <div className="w-5 h-5 flex items-center justify-center shrink-0">
            <Zap className="w-4 h-4 text-amber-400" />
          </div>
          {!collapsed && (
            <div className="flex-1 text-left flex items-center justify-between min-w-0">
              <span className="truncate">Audit Ledger</span>
              <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/20 font-bold">
                SHA-256
              </span>
            </div>
          )}
        </button>

        {/* 5. Cognitive Stream */}
        <button
          type="button"
          onClick={() => onSelectNav('stream')}
          className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-2xl text-xs font-semibold transition-all ${
            activeItem === 'stream'
              ? 'bg-indigo-500/20 text-indigo-200 border border-indigo-500/40'
              : 'text-slate-400 hover:text-white hover:bg-white/[0.04] border border-transparent'
          }`}
          title="Cognitive Thought Stream"
        >
          <div className="w-5 h-5 flex items-center justify-center shrink-0">
            <Terminal className="w-4 h-4 text-sky-400" />
          </div>
          {!collapsed && (
            <div className="flex-1 text-left flex items-center justify-between min-w-0">
              <span className="truncate">Cognitive Stream</span>
              <span className="text-[9px] font-mono text-slate-500">Live</span>
            </div>
          )}
        </button>

        {/* 6. DOM Field Telemetry */}
        <button
          type="button"
          onClick={() => onSelectNav('map')}
          className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-2xl text-xs font-semibold transition-all ${
            activeItem === 'map'
              ? 'bg-indigo-500/20 text-indigo-200 border border-indigo-500/40'
              : 'text-slate-400 hover:text-white hover:bg-white/[0.04] border border-transparent'
          }`}
          title="DOM Map & Locators"
        >
          <div className="w-5 h-5 flex items-center justify-center shrink-0">
            <Layers className="w-4 h-4 text-emerald-400" />
          </div>
          {!collapsed && (
            <div className="flex-1 text-left flex items-center justify-between min-w-0">
              <span className="truncate">DOM Telemetry</span>
              {formMap?.field_count ? (
                <span className="text-[9px] font-mono text-emerald-400 font-bold">
                  {formMap.field_count} fields
                </span>
              ) : null}
            </div>
          )}
        </button>

        {/* Security Policy Section */}
        {!collapsed && (
          <div className="pt-4 px-2 pb-1 text-[9px] font-bold text-slate-400 uppercase tracking-widest font-mono">
            Safety Barriers
          </div>
        )}

        <div className="space-y-1">
          <div
            className={`flex items-center gap-3 px-3 py-2 rounded-xl text-xs text-slate-400 ${
              collapsed ? 'justify-center' : 'justify-between'
            }`}
            title="CAPTCHA Defense: Automatic human handoff only"
          >
            <div className="flex items-center gap-2.5 min-w-0">
              <Lock className="w-4 h-4 text-amber-400 shrink-0" />
              {!collapsed && <span className="truncate">CAPTCHA Defense</span>}
            </div>
            {!collapsed && (
              <span className="text-[9px] font-mono text-amber-300 bg-amber-500/10 px-1.5 py-0.5 rounded border border-amber-500/20 font-bold">
                Auto
              </span>
            )}
          </div>

          <div
            className={`flex items-center gap-3 px-3 py-2 rounded-xl text-xs text-slate-400 ${
              collapsed ? 'justify-center' : 'justify-between'
            }`}
            title="Pre-Payment Lock: 100% human-only final barrier"
          >
            <div className="flex items-center gap-2.5 min-w-0">
              <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0" />
              {!collapsed && <span className="truncate">Payment Lock</span>}
            </div>
            {!collapsed && (
              <span className="text-[9px] font-mono text-emerald-300 bg-emerald-500/10 px-1.5 py-0.5 rounded border border-emerald-500/20 font-bold">
                Locked
              </span>
            )}
          </div>

          <div
            className={`flex items-center gap-3 px-3 py-2 rounded-xl text-xs text-slate-400 ${
              collapsed ? 'justify-center' : 'justify-between'
            }`}
            title="SSRF Defense: Cloud metadata (169.254.169.254) and private subnet boundary active"
          >
            <div className="flex items-center gap-2.5 min-w-0">
              <ShieldCheck className="w-4 h-4 text-cyan-400 shrink-0" />
              {!collapsed && <span className="truncate">SSRF Guard</span>}
            </div>
            {!collapsed && (
              <span className="text-[9px] font-mono text-cyan-300 bg-cyan-500/10 px-1.5 py-0.5 rounded border border-cyan-500/20 font-bold">
                Enforced
              </span>
            )}
          </div>

          <div
            className={`flex items-center gap-3 px-3 py-2 rounded-xl text-xs text-slate-400 ${
              collapsed ? 'justify-center' : 'justify-between'
            }`}
            title="Merkle Audit Hash Chain: Cryptographic non-repudiation ledger"
          >
            <div className="flex items-center gap-2.5 min-w-0">
              <Zap className="w-4 h-4 text-violet-400 shrink-0" />
              {!collapsed && <span className="truncate">Merkle Ledger</span>}
            </div>
            {!collapsed && (
              <span className="text-[9px] font-mono text-violet-300 bg-violet-500/10 px-1.5 py-0.5 rounded border border-violet-500/20 font-bold">
                SHA-256
              </span>
            )}
          </div>
        </div>
      </nav>

      {/* Sidebar Footer: Help, Settings & Candidate Identifier */}
      <div className="p-3 border-t border-white/[0.08] space-y-2">
        <button
          type="button"
          onClick={() => onSelectNav('help')}
          className={`w-full flex items-center gap-3 px-3 py-2 rounded-xl text-xs font-semibold transition-colors ${
            activeItem === 'help'
              ? 'bg-teal-500/15 text-teal-200 border border-teal-500/30'
              : 'text-slate-400 hover:text-white hover:bg-white/[0.04]'
          } ${collapsed ? 'justify-center' : ''}`}
          title="Help, guide and safety rules"
        >
          <BookOpen className={`w-4 h-4 ${activeItem === 'help' ? 'text-teal-300' : 'text-slate-400'}`} />
          {!collapsed && <span>Help & Guide</span>}
        </button>


        <button
          type="button"
          onClick={() => onSelectNav('settings')}
          className={`w-full flex items-center gap-3 px-3 py-2 rounded-xl text-xs font-semibold transition-colors ${
            activeItem === 'settings'
              ? 'bg-indigo-500/20 text-indigo-200 border border-indigo-500/40'
              : 'text-slate-400 hover:text-white hover:bg-white/[0.04]'
          } ${collapsed ? 'justify-center' : ''}`}
          title="Engine & Distributed Architecture Settings"
        >
          <Settings className={`w-4 h-4 ${activeItem === 'settings' ? 'text-indigo-400' : 'text-slate-400'}`} />
          {!collapsed && <span>Engine Settings</span>}
        </button>

        {!account && accountsEnabled && onOpenAuth && (
          <button
            type="button"
            onClick={onOpenAuth}
            className={`w-full flex items-center gap-3 px-3 py-2 rounded-xl text-xs font-semibold transition-colors text-emerald-200/90 hover:text-emerald-100 hover:bg-emerald-500/10 ${
              collapsed ? 'justify-center' : ''
            }`}
            title="Sign in or create a FormPilot account"
          >
            <User className="w-4 h-4 text-emerald-400/90" />
            {!collapsed && <span>Sign in / Create account</span>}
          </button>
        )}

        <div
          className={`p-2 rounded-2xl bg-white/[0.02] border border-white/[0.06] flex items-center gap-2.5 ${
            collapsed ? 'justify-center' : ''
          }`}
          title={account ? `${account.name || 'Account'} · ${account.email}` : 'Local single-user workspace'}
        >
          <div className="w-7 h-7 rounded-xl bg-slate-800 border border-white/10 flex items-center justify-center font-bold text-xs text-slate-300 shrink-0">
            {(account?.name || account?.email || vault?.full_name || 'FP').slice(0, 2).toUpperCase()}
          </div>
          {!collapsed && (
            <div className="min-w-0 flex-1">
              <div className="text-xs font-bold text-white truncate">
                {account ? (account.name || 'Your account') : (vault?.full_name || 'Local Candidate')}
              </div>
              <div className="text-[10px] text-slate-400 font-mono truncate">
                {account ? account.email : (vault?.mobile ? `+91 ${vault.mobile}` : 'Offline Encrypted')}
              </div>
              {account && vault?.full_name && (
                <div className="text-[9px] text-slate-500 truncate">
                  Vault: {vault.full_name}
                </div>
              )}
            </div>
          )}
          {account && onLogout && (
            <button
              type="button"
              onClick={onLogout}
              className={`shrink-0 rounded-lg p-1.5 text-slate-500 transition-colors hover:bg-white/[0.06] hover:text-slate-200 ${
                collapsed ? 'hidden' : ''
              }`}
              title="Sign out of FormPilot"
              aria-label="Sign out"
            >
              <LogOut className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>
    </aside>
  );
}
