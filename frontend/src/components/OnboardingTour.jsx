import React, { useEffect, useState } from 'react';
import {
  ArrowRight,
  Check,
  FileText,
  Lock,
  MessageSquare,
  ShieldCheck,
  Sparkles,
  X,
} from 'lucide-react';

const STORAGE_KEY = 'formpilot.onboarding.v1';

const STEPS = [
  {
    title: 'Welcome to FormPilot',
    body: 'FormPilot reads long government forms, fills the details you already saved, and stops whenever a human decision is required. It never submits an application or pays on your behalf.',
    icon: Sparkles,
    tone: 'text-teal-300',
  },
  {
    title: 'Save your details once',
    body: 'Open OneVault and add your core identity, contact and education details. Your vault is encrypted on this device, and you can import documents with your own ChatGPT or Gemini account.',
    icon: Lock,
    tone: 'text-emerald-300',
    action: { label: 'Open OneVault', nav: 'vault' },
  },
  {
    title: 'Launch a portal',
    body: 'Paste an official portal URL or try the practice portal. FormPilot maps the page, explains what it needs, and asks you only for the things it cannot know.',
    icon: FileText,
    tone: 'text-sky-300',
    action: { label: 'Open the cockpit', nav: 'portal' },
  },
  {
    title: 'Stay in control with the Copilot',
    body: 'The Copilot is a real operator: ask it to change a name, explain a field, or go back to a previous step. It reports what actually changed instead of guessing.',
    icon: MessageSquare,
    tone: 'text-indigo-300',
    action: { label: 'Open Copilot', nav: 'portal' },
  },
  {
    title: 'Human-only barriers',
    body: 'CAPTCHA, OTP, live photo, payment and final submission always belong to you. FormPilot pauses and hands over the browser. That rule never changes.',
    icon: ShieldCheck,
    tone: 'text-amber-300',
  },
];

export function hasSeenOnboarding() {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === 'done';
  } catch (err) {
    return false;
  }
}

export function markOnboardingSeen() {
  try {
    window.localStorage.setItem(STORAGE_KEY, 'done');
  } catch (err) {
    // Private browsing can block storage; the tour still works for this visit.
  }
}

export default function OnboardingTour({ open, onClose, onNavigate }) {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (!open) return undefined;
    setIndex(0);
    const onKey = (event) => {
      if (event.key === 'Escape') finish();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  if (!open) return null;

  const step = STEPS[index];
  const Icon = step.icon;
  const last = index === STEPS.length - 1;

  function finish() {
    markOnboardingSeen();
    if (onClose) onClose();
  }

  function next() {
    if (last) {
      finish();
      return;
    }
    setIndex((value) => Math.min(value + 1, STEPS.length - 1));
  }

  function goTo(action) {
    markOnboardingSeen();
    if (onNavigate && action?.nav) onNavigate(action.nav);
    if (onClose) onClose();
  }

  return (
    <div
      className="fixed inset-0 z-[70] flex items-end justify-center bg-[#0d1210]/85 p-0 backdrop-blur-md animate-fadeIn sm:items-center sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="onboarding-title"
    >
      <div className="w-full max-w-lg overflow-hidden rounded-t-3xl border border-white/[0.1] bg-[#141b17] shadow-2xl sm:rounded-3xl">
        <div className="flex items-start justify-between gap-3 border-b border-white/[0.07] px-5 py-4">
          <div className="flex items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-2xl border border-teal-400/30 bg-teal-500/10">
              <Icon className={`h-5 w-5 ${step.tone}`} />
            </span>
            <div>
              <p className="text-[10px] font-mono uppercase tracking-widest text-slate-400">
                Getting started · {index + 1} of {STEPS.length}
              </p>
              <h2 id="onboarding-title" className="text-sm font-bold text-white">
                {step.title}
              </h2>
            </div>
          </div>
          <button
            type="button"
            onClick={finish}
            className="rounded-xl p-1.5 text-slate-400 transition-colors hover:bg-white/[0.06] hover:text-white"
            aria-label="Skip the tour"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4 px-5 py-5">
          <p className="text-[13px] leading-relaxed text-slate-300">{step.body}</p>

          <div className="flex items-center gap-1.5">
            {STEPS.map((item, itemIndex) => (
              <button
                key={item.title}
                type="button"
                onClick={() => setIndex(itemIndex)}
                className={`h-1.5 rounded-full transition-all ${
                  itemIndex === index
                    ? 'w-7 bg-teal-400'
                    : itemIndex < index
                      ? 'w-3 bg-teal-400/50'
                      : 'w-3 bg-white/15'
                }`}
                aria-label={`Go to step ${itemIndex + 1}`}
              />
            ))}
          </div>

          {step.action && (
            <button
              type="button"
              onClick={() => goTo(step.action)}
              className="flex items-center gap-2 rounded-xl border border-teal-400/30 bg-teal-500/10 px-3 py-2 text-[11px] font-semibold text-teal-200 transition-colors hover:bg-teal-500/20"
            >
              {step.action.label}
              <ArrowRight className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-white/[0.07] bg-white/[0.02] px-5 py-3.5">
          <button
            type="button"
            onClick={finish}
            className="text-[11px] font-semibold text-slate-400 transition-colors hover:text-slate-200"
          >
            Skip tour
          </button>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setIndex((value) => Math.max(0, value - 1))}
              disabled={index === 0}
              className="rounded-xl border border-white/[0.1] px-3 py-2 text-[11px] font-semibold text-slate-300 transition-colors hover:bg-white/[0.06] disabled:opacity-30"
            >
              Back
            </button>
            <button
              type="button"
              onClick={next}
              className="flex items-center gap-2 rounded-xl bg-teal-600 px-4 py-2 text-[11px] font-bold text-white transition-colors hover:bg-teal-500"
            >
              {last ? (
                <>
                  <Check className="h-3.5 w-3.5" />
                  Start using FormPilot
                </>
              ) : (
                <>
                  Next
                  <ArrowRight className="h-3.5 w-3.5" />
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
