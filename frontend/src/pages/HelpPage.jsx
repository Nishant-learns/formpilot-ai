import React, { useState } from 'react';
import {
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Code2,
  ExternalLink,
  FileText,
  HelpCircle,
  KeyRound,
  Lock,
  MessageSquare,
  PlayCircle,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';

const QUICK_START = [
  {
    title: 'Add your details',
    body: 'Open OneVault and fill the core identity, contact and education sections. The more you save, the less the Copilot has to ask.',
    icon: Lock,
  },
  {
    title: 'Import documents without an API bill',
    body: 'In OneVault → AI import, copy the FormPilot prompt into ChatGPT or Gemini, attach your marksheets or ID, then paste the JSON reply back.',
    icon: FileText,
  },
  {
    title: 'Launch the portal',
    body: 'Paste an official URL or start with the practice portal. FormPilot reads the page, explains each field and asks before it acts on anything ambiguous.',
    icon: Sparkles,
  },
  {
    title: 'Review and take over',
    body: 'Use the Copilot to change a detail or go back a step. For OTP, CAPTCHA, live photo, payment or final submission, FormPilot hands the browser to you.',
    icon: MessageSquare,
  },
];

const SAFETY = [
  'FormPilot never solves a CAPTCHA or reads an OTP for you.',
  'FormPilot never pays a fee or completes a final submission.',
  'FormPilot never guesses your password, login method or account identifier.',
  'FormPilot never uploads a document to a third-party model. You choose the AI and paste the reply yourself.',
  'Your vault and documents are encrypted at rest on this device.',
];

const FAQ = [
  {
    q: 'Does FormPilot send my documents to an AI?',
    a: 'No. FormPilot does not call ChatGPT or Gemini. It gives you a prompt; you paste it into the AI account you already have, attach your documents there, and paste the JSON reply back. FormPilot only validates and stores what you approve.',
  },
  {
    q: 'Why does the JSON template have empty values?',
    a: 'The template is a shape, not a filled profile. Empty placeholders stop a model from copying an example name or date into your real record. The prompt tells the model to fill values only from the documents you attach.',
  },
  {
    q: 'What happens when the portal shows a CAPTCHA or OTP?',
    a: 'FormPilot pauses and opens a human checkpoint. You complete that step in the live browser or the checkpoint panel. FormPilot resumes only after you confirm.',
  },
  {
    q: 'Can the Copilot go back a page?',
    a: 'Yes, when the page exposes a real Previous/Back control. FormPilot clicks that control and verifies the page changed. On a single-page wizard it will not use browser history, because that could leave the portal.',
  },
  {
    q: 'Where is my data stored?',
    a: 'In the local data directory used by this FormPilot instance. The vault is encrypted with AES-256-GCM when a key is configured, and documents are always stored encrypted. Downloads are served through the API, never as public files.',
  },
  {
    q: 'Is FormPilot a government website?',
    a: 'No. FormPilot is an independent application assistant. It is not affiliated with any government portal and does not submit applications or make payments.',
  },
];

export default function HelpPage({ onReplayTour, onSelectNav }) {
  const [openFaq, setOpenFaq] = useState(0);

  return (
    <main className="mx-auto w-full max-w-5xl px-3 pb-16 pt-5 sm:px-6">
      <div className="rounded-3xl border border-white/[0.08] bg-white/[0.025] p-5 sm:p-7">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-2xl">
            <div className="flex items-center gap-2 text-[10px] font-mono uppercase tracking-widest text-teal-300">
              <BookOpen className="h-3.5 w-3.5" />
              Help & guide
            </div>
            <h1 className="mt-2 text-xl font-bold tracking-tight text-white sm:text-2xl">
              A calmer way through a long form
            </h1>
            <p className="mt-2 text-[13px] leading-relaxed text-slate-400">
              FormPilot handles the repetitive parts, explains what it is doing, and stops
              at every human-only barrier. This page is the short version of how to use it.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {onReplayTour && (
              <button
                type="button"
                onClick={onReplayTour}
                className="flex items-center gap-2 rounded-xl border border-teal-400/30 bg-teal-500/10 px-3.5 py-2 text-[11px] font-bold text-teal-200 transition-colors hover:bg-teal-500/20"
              >
                <PlayCircle className="h-4 w-4" />
                Replay the tour
              </button>
            )}
            {onSelectNav && (
              <>

                <button
                  type="button"
                  onClick={() => onSelectNav('vault')}
                  className="flex items-center gap-2 rounded-xl border border-white/[0.1] bg-white/[0.04] px-3.5 py-2 text-[11px] font-semibold text-slate-200 transition-colors hover:bg-white/[0.08]"
                >
                  <Lock className="h-4 w-4" />
                  Open OneVault
                </button>
              </>
            )}
          </div>
        </div>
      </div>

      <section className="mt-6">
        <h2 className="text-sm font-bold text-white">Quick start</h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {QUICK_START.map((step, index) => {
            const Icon = step.icon;
            return (
              <div
                key={step.title}
                className="rounded-2xl border border-white/[0.08] bg-white/[0.025] p-4"
              >
                <div className="flex items-center gap-2">
                  <span className="flex h-7 w-7 items-center justify-center rounded-xl border border-teal-400/25 bg-teal-500/10 font-mono text-[10px] font-bold text-teal-200">
                    {index + 1}
                  </span>
                  <Icon className="h-4 w-4 text-teal-300" />
                  <h3 className="text-[12px] font-bold text-slate-100">{step.title}</h3>
                </div>
                <p className="mt-2 text-[11px] leading-relaxed text-slate-400">{step.body}</p>
              </div>
            );
          })}
        </div>
      </section>

      <section className="mt-6 rounded-2xl border border-white/[0.08] bg-white/[0.025] p-4">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-teal-300" />
          <h2 className="text-sm font-bold text-white">Creating a portal account</h2>
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <div className="rounded-xl border border-white/[0.07] bg-slate-950/40 p-3">
            <p className="text-[10px] font-mono uppercase tracking-wider text-teal-300">1 · Choose the path</p>
            <p className="mt-1 text-[11px] leading-relaxed text-slate-400">
              When the portal offers New Registration, Candidate Login or Resume, FormPilot asks you
              which one applies. It never guesses.
            </p>
          </div>
          <div className="rounded-xl border border-white/[0.07] bg-slate-950/40 p-3">
            <p className="text-[10px] font-mono uppercase tracking-wider text-teal-300">2 · Fill the form</p>
            <p className="mt-1 text-[11px] leading-relaxed text-slate-400">
              FormPilot uses your saved vault and the portal's own labels. If a detail is missing or
              ambiguous, it asks you before typing.
            </p>
          </div>
          <div className="rounded-xl border border-white/[0.07] bg-slate-950/40 p-3">
            <p className="text-[10px] font-mono uppercase tracking-wider text-teal-300">3 · You finish the human steps</p>
            <p className="mt-1 text-[11px] leading-relaxed text-slate-400">
              OTP, CAPTCHA, live photo, payment and final submission are yours. FormPilot pauses and
              hands over the browser.
            </p>
          </div>
        </div>
      </section>

      <section className="mt-6 grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
        <div className="rounded-2xl border border-amber-500/20 bg-amber-500/[0.06] p-4">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-amber-300" />
            <h2 className="text-sm font-bold text-amber-100">What FormPilot never does</h2>
          </div>
          <ul className="mt-3 space-y-2">
            {SAFETY.map((item) => (
              <li key={item} className="flex items-start gap-2 text-[11px] leading-relaxed text-amber-50/80">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-300" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="rounded-2xl border border-white/[0.08] bg-white/[0.025] p-4">
          <div className="flex items-center gap-2">
            <KeyRound className="h-4 w-4 text-teal-300" />
            <h2 className="text-sm font-bold text-white">Privacy in one minute</h2>
          </div>
          <div className="mt-3 space-y-3 text-[11px] leading-relaxed text-slate-400">
            <p>
              The vault is encrypted with AES-256-GCM when <code className="rounded bg-slate-950/70 px-1 py-0.5 font-mono text-[10px] text-slate-300">FORMPILOT_VAULT_KEY</code> is set.
              Documents are always sealed with a local key and decrypted only in memory while
              Playwright uploads them.
            </p>
            <p>
              No analytics, no third-party model calls, no public document URLs. The
              extraction prompt is the only thing you copy out, and you choose where it goes.
            </p>
          </div>
        </div>
      </section>

      <section className="mt-6">
        <div className="flex items-center gap-2">
          <HelpCircle className="h-4 w-4 text-teal-300" />
          <h2 className="text-sm font-bold text-white">Frequently asked</h2>
        </div>
        <div className="mt-3 overflow-hidden rounded-2xl border border-white/[0.08]">
          {FAQ.map((item, index) => {
            const open = openFaq === index;
            return (
              <div key={item.q} className="border-b border-white/[0.06] last:border-b-0">
                <button
                  type="button"
                  onClick={() => setOpenFaq(open ? -1 : index)}
                  className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition-colors hover:bg-white/[0.03]"
                  aria-expanded={open}
                >
                  <span className="text-[12px] font-semibold text-slate-200">{item.q}</span>
                  {open ? (
                    <ChevronUp className="h-4 w-4 shrink-0 text-slate-400" />
                  ) : (
                    <ChevronDown className="h-4 w-4 shrink-0 text-slate-400" />
                  )}
                </button>
                {open && (
                  <p className="px-4 pb-3 text-[11px] leading-relaxed text-slate-400">{item.a}</p>
                )}
              </div>
            );
          })}
        </div>
      </section>

      <section className="mt-6 rounded-2xl border border-white/[0.08] bg-white/[0.025] p-4">
        <h2 className="text-sm font-bold text-white">Still stuck?</h2>
        <p className="mt-1 text-[11px] leading-relaxed text-slate-400">
          If a page does not move, the safest next step is to pause the run, take over the
          browser, and inspect the page yourself. The Copilot can explain what it sees, but
          it will not invent a result.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <a
            href="https://github.com/Nishant-learns/formpilot"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 rounded-xl border border-white/[0.1] bg-white/[0.04] px-3.5 py-2 text-[11px] font-semibold text-slate-200 transition-colors hover:bg-white/[0.08]"
          >
            Project repository
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
          {onSelectNav && (
            <button
              type="button"
              onClick={() => onSelectNav('settings')}
              className="inline-flex items-center gap-2 rounded-xl border border-white/[0.1] bg-white/[0.03] px-3.5 py-2 text-[11px] font-semibold text-slate-300 transition-colors hover:bg-white/[0.07]"
            >
              Engine settings
            </button>
          )}
        </div>
      </section>
    </main>
  );
}
