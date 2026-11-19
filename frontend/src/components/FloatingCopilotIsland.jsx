import React, { useState, useMemo } from 'react';
import {
  Play,
  Pause,
  Maximize2,
  Minimize2,
  Tv,
  AlertTriangle,
  ChevronUp,
  ChevronDown,
  Sparkles,
  ExternalLink,
  X
} from 'lucide-react';
import { NeuralSparkleIcon } from './CustomIcons';

/**
 * FloatingCopilotIsland
 *
 * Persistent, floating Dynamic Island & Micro-PiP HUD that floats across all mobile
 * screens (OneVault, Studio, Runs, Settings) giving the user continuous real-time
 * awareness and control over the background autonomous browser agent.
 */
export default function FloatingCopilotIsland({
  runState = 'IDLE',
  events = [],
  activeGate = null,
  screenshot = '',
  currentSection = 1,
  onPause = () => {},
  onResume = () => {},
  onOpenGate = () => {},
  onNavigateToCockpit = () => {},
  isCockpitView = false,
}) {
  const [minimized, setMinimized] = useState(false);
  const [showPiP, setShowPiP] = useState(false);

  const isRunning = ['RUNNING', 'FILLING', 'RESOLVING'].includes(runState);
  const isPaused = runState === 'PAUSED';
  const hasGate = Boolean(activeGate);
  const isSessionActive = isRunning || isPaused || hasGate || runState === 'INSPECT_READY';

  // Extract latest meaningful autonomous action event
  const latestEvent = useMemo(() => {
    if (!events || events.length === 0) return null;
    for (let i = events.length - 1; i >= 0; i--) {
      const ev = events[i];
      if (ev?.message && typeof ev.message === 'string') {
        return ev;
      }
    }
    return null;
  }, [events]);

  // If session is idle and no gate, hide the island completely
  if (!isSessionActive && !hasGate) {
    return null;
  }

  // If the user is already looking at the full Cockpit viewport, hide floating island on desktop
  // but keep compact PiP option on mobile if desired.
  if (isCockpitView && !showPiP) {
    return null;
  }

  // Minimized Floating Dot State
  if (minimized) {
    return (
      <aside
        aria-label="FormPilot Agent Minimized Indicator"
        className="fixed bottom-20 right-4 z-40 transition-transform active:scale-95"
      >
        <button
          type="button"
          onClick={() => setMinimized(false)}
          className={`flex h-12 w-12 items-center justify-center rounded-full border shadow-2xl backdrop-blur-xl ${
            hasGate
              ? 'border-amber-400 bg-amber-500/20 text-amber-300 animate-bounce'
              : isRunning
              ? 'border-emerald-400/60 bg-slate-950/90 text-emerald-300 shadow-emerald-500/20'
              : 'border-white/20 bg-slate-950/90 text-slate-300'
          }`}
          title="Restore FormPilot Floating Island"
        >
          <span className="relative">
            <NeuralSparkleIcon className="h-5 w-5" />
            <span
              className={`absolute -right-1 -top-1 h-2 w-2 rounded-full ${
                hasGate ? 'bg-amber-400 animate-ping' : isRunning ? 'bg-emerald-400 animate-pulse' : 'bg-slate-400'
              }`}
            />
          </span>
        </button>
      </aside>
    );
  }

  return (
    <aside
      aria-label="FormPilot Floating Live Copilot Island"
      className="fixed bottom-[calc(env(safe-area-inset-bottom,0px)+64px)] inset-x-3 sm:inset-x-auto sm:right-6 sm:w-[440px] z-40 flex flex-col items-end gap-2 pointer-events-none select-none transition-all duration-300"
    >
      {/* Micro-PiP Live Viewport Window */}
      {showPiP && (
        <div className="pointer-events-auto w-full sm:w-[320px] rounded-2xl border border-emerald-500/30 bg-slate-950/95 p-2 shadow-2xl backdrop-blur-2xl animate-fadeIn">
          <div className="flex items-center justify-between px-2 pb-1.5 border-b border-white/[0.08] text-[10px] font-mono">
            <div className="flex items-center gap-1.5 text-emerald-400">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
              <span className="font-bold">LIVE STREAM</span>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={onNavigateToCockpit}
                className="text-slate-400 hover:text-white flex items-center gap-0.5 text-[9px]"
                title="Fullscreen in Cockpit"
              >
                <Maximize2 className="h-3 w-3" />
                <span>Expand</span>
              </button>
              <button
                type="button"
                onClick={() => setShowPiP(false)}
                className="text-slate-500 hover:text-slate-300"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          </div>

          <div
            onClick={onNavigateToCockpit}
            className="mt-1.5 relative aspect-video w-full overflow-hidden rounded-xl bg-slate-900 border border-white/[0.06] cursor-pointer group"
          >
            {screenshot ? (
              <img
                src={screenshot}
                alt="Live portal feed"
                className="h-full w-full object-cover object-top transition-transform group-hover:scale-105"
              />
            ) : (
              <div className="flex h-full w-full items-center justify-center text-xs text-slate-500 font-mono">
                <span>Connecting live canvas...</span>
              </div>
            )}
            <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex items-end p-2">
              <span className="text-[10px] text-white font-medium flex items-center gap-1">
                <ExternalLink className="h-3 w-3 text-emerald-400" />
                Tap to take over in Cockpit
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Main Floating Capsule */}
      <div
        className={`pointer-events-auto w-full flex items-center justify-between gap-3 rounded-2xl px-3.5 py-2.5 shadow-2xl backdrop-blur-2xl transition-all ${
          hasGate
            ? 'border border-amber-400/50 bg-amber-950/80 text-amber-200 shadow-amber-500/20 animate-pulse'
            : isRunning
            ? 'border border-emerald-500/40 bg-slate-950/90 text-white shadow-emerald-500/10'
            : 'border border-white/[0.12] bg-slate-950/90 text-slate-200'
        }`}
      >
        {/* Left Status Indicator */}
        <div
          onClick={hasGate ? onOpenGate : onNavigateToCockpit}
          className="flex items-center gap-2.5 min-w-0 flex-1 cursor-pointer"
        >
          <div className="relative shrink-0 flex items-center justify-center">
            {hasGate ? (
              <AlertTriangle className="h-4 w-4 text-amber-400 animate-bounce" />
            ) : isRunning ? (
              <div className="h-2.5 w-2.5 rounded-full bg-emerald-400 shadow-[0_0_8px_#34d399] animate-pulse" />
            ) : (
              <div className="h-2.5 w-2.5 rounded-full bg-amber-400" />
            )}
          </div>

          <div className="min-w-0 flex-1">
            {hasGate ? (
              <div className="flex items-center gap-1.5">
                <span className="text-xs font-bold text-amber-300">Action Required</span>
                <span className="text-[10px] font-mono text-amber-200/80 truncate">
                  {activeGate?.type ? `(${activeGate.type})` : 'Checkpoint open'}
                </span>
              </div>
            ) : (
              <div className="flex flex-col">
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-emerald-400">
                    {runState === 'PAUSED' ? 'Paused' : `Step ${currentSection}`}
                  </span>
                  <span className="text-[9px] text-slate-400 font-mono">• Live Copilot</span>
                </div>
                <p className="text-xs text-slate-200 font-medium truncate">
                  {latestEvent?.message || 'Navigating official portal...'}
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Right Action Controls */}
        <div className="flex items-center gap-1 shrink-0">
          {hasGate ? (
            <button
              type="button"
              onClick={onOpenGate}
              className="px-2.5 py-1 rounded-xl bg-amber-400 text-slate-950 text-xs font-bold shadow hover:bg-amber-300 transition-colors"
            >
              Resolve
            </button>
          ) : (
            <>
              {/* Play/Pause Button */}
              {isRunning ? (
                <button
                  type="button"
                  onClick={onPause}
                  className="p-1.5 rounded-xl hover:bg-white/[0.08] text-slate-300 hover:text-white transition-colors"
                  title="Pause autonomous run"
                >
                  <Pause className="h-3.5 w-3.5 text-amber-300" />
                </button>
              ) : isPaused ? (
                <button
                  type="button"
                  onClick={onResume}
                  className="p-1.5 rounded-xl hover:bg-white/[0.08] text-emerald-300 hover:text-emerald-200 transition-colors"
                  title="Resume autonomous run"
                >
                  <Play className="h-3.5 w-3.5 fill-current" />
                </button>
              ) : null}

              {/* Toggle Micro-PiP preview */}
              <button
                type="button"
                onClick={() => setShowPiP(!showPiP)}
                className={`p-1.5 rounded-xl transition-colors ${
                  showPiP ? 'bg-emerald-500/20 text-emerald-300' : 'hover:bg-white/[0.08] text-slate-400 hover:text-white'
                }`}
                title="Toggle Live Viewport Preview"
              >
                <Tv className="h-3.5 w-3.5" />
              </button>

              {/* Jump to Cockpit Fullscreen */}
              <button
                type="button"
                onClick={onNavigateToCockpit}
                className="p-1.5 rounded-xl hover:bg-white/[0.08] text-slate-400 hover:text-white transition-colors"
                title="View Full Cockpit"
              >
                <Maximize2 className="h-3.5 w-3.5" />
              </button>
            </>
          )}

          {/* Minimize to Dot */}
          <button
            type="button"
            onClick={() => setMinimized(true)}
            className="p-1.5 rounded-xl hover:bg-white/[0.08] text-slate-500 hover:text-slate-300 transition-colors"
            title="Minimize to icon"
          >
            <ChevronDown className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </aside>
  );
}
