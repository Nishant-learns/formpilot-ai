import React, { useState, useEffect, useRef } from 'react';
import {
  ArrowRight,
  CheckCircle2,
  ExternalLink,
  Eye,
  EyeOff,
  HelpCircle,
  KeyRound,
  Loader2,
  Lock,
  Mail,
  ShieldCheck,
  Sparkles,
  User,
  UserPlus,
  X,
} from 'lucide-react';
import { setSessionToken } from '../apiConfig';
import { NeuralSparkleIcon, SecurityShieldIcon } from '../components/CustomIcons';

function GoogleIcon({ className = "h-4 w-4" }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
      />
      <path
        fill="#34A853"
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
      />
      <path
        fill="#FBBC05"
        d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"
      />
      <path
        fill="#EA4335"
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"
      />
    </svg>
  );
}

const BENEFITS = [
  'Your vault, documents, run history and live session stay private to your account.',
  'Sign in from another device and pick up the same saved profile.',
  'Documents are stored encrypted; FormPilot decrypts them only while filling a page.',
  'FormPilot still never solves a CAPTCHA, reads an OTP, pays a fee or submits for you.',
];

function Field({ icon: Icon, label, children }) {
  return (
    <label className="block">
      <span className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
        <Icon className="h-3.5 w-3.5 text-slate-500" />
        {label}
      </span>
      {children}
    </label>
  );
}

const GOOGLE_CLIENT_ID_FALLBACK = '128189450128-65rlop2c8ic54ohq3emh88n36drqcge7.apps.googleusercontent.com';

export default function AuthPage({ status, onAuthenticated, onContinueAsGuest }) {
  const accountsEnabled = status?.accounts_enabled !== false;
  const accountsRequired = status?.accounts_required !== false;
  const googleClientId = status?.google_client_id || import.meta.env.VITE_GOOGLE_CLIENT_ID || GOOGLE_CLIENT_ID_FALLBACK;
  const [showGoogleGuide, setShowGoogleGuide] = useState(false);
  const googleBtnRef = useRef(null);

  const [mode, setMode] = useState('login');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const isSignup = mode === 'signup';

  const switchMode = (next) => {
    setMode(next);
    setError('');
  };

  useEffect(() => {
    if (!googleClientId) return;

    let mounted = true;
    const initGsi = () => {
      if (window.google?.accounts?.id && googleBtnRef.current && mounted) {
        try {
          window.google.accounts.id.initialize({
            client_id: googleClientId,
            callback: handleGoogleCredentialResponse,
            auto_select: false,
          });
          googleBtnRef.current.innerHTML = '';
          window.google.accounts.id.renderButton(googleBtnRef.current, {
            theme: 'filled_black',
            size: 'large',
            shape: 'rectangular',
            text: 'continue_with',
            width: 300,
          });
        } catch (e) {
          console.warn('GSI render notice:', e);
        }
      }
    };

    if (window.google?.accounts?.id) {
      initGsi();
    } else {
      const interval = setInterval(() => {
        if (window.google?.accounts?.id) {
          clearInterval(interval);
          initGsi();
        }
      }, 300);
      return () => {
        mounted = false;
        clearInterval(interval);
      };
    }
    return () => {
      mounted = false;
    };
  }, [googleClientId]);

  const handleGoogleCredentialResponse = async (response) => {
    if (!response?.credential || busy) return;
    setBusy(true);
    setError('');
    try {
      const res = await fetch('/api/account/google', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ credential: response.credential, client_id: googleClientId }),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(payload?.detail || 'Google sign-in failed.');
      }
      setSessionToken(payload.token);
      onAuthenticated?.(payload.account, payload.token);
    } catch (err) {
      setError(err.message || 'Google sign-in failed.');
      setBusy(false);
    }
  };

  const handleSimulatedGoogleLogin = async () => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      const res = await fetch('/api/account/google', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          simulated: true,
          simulated_email: 'google.candidate@example.com',
          simulated_name: 'Google Candidate (Test)',
        }),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(payload?.detail || 'Simulated Google sign-in failed.');
      }
      setSessionToken(payload.token);
      setShowGoogleGuide(false);
      onAuthenticated?.(payload.account, payload.token);
    } catch (err) {
      setError(err.message || 'Simulated Google sign-in failed.');
      setBusy(false);
    }
  };

  const submit = async (event) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      const endpoint = isSignup ? '/api/account/signup' : '/api/account/login';
      const body = isSignup
        ? { name: name.trim(), email: email.trim(), password }
        : { email: email.trim(), password };
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload?.detail || 'That did not work. Please try again.');
      }
      setSessionToken(payload.token);
      onAuthenticated?.(payload.account, payload.token);
    } catch (err) {
      setError(err.message || 'That did not work. Please try again.');
      setBusy(false);
    }
  };

  const handleDemoLogin = async () => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      const response = await fetch('/api/account/demo-login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload?.detail || 'Instant demo login failed.');
      }
      setSessionToken(payload.token);
      onAuthenticated?.(payload.account, payload.token);
    } catch {
      // Direct fallback to guest workspace if API is offline
      onContinueAsGuest?.();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative min-h-screen overflow-x-hidden bg-[#0d1210] text-slate-100 antialiased selection:bg-emerald-500/25 selection:text-emerald-100">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(ellipse_70%_45%_at_20%_-10%,rgba(143,184,169,0.10),transparent_70%)]" />
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(ellipse_60%_40%_at_90%_110%,rgba(196,169,132,0.08),transparent_70%)]" />

      <div className="relative mx-auto flex min-h-screen w-full max-w-6xl flex-col px-4 py-6 sm:px-6">
        <header className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-emerald-500/40 bg-gradient-to-br from-emerald-500 via-emerald-600 to-teal-700 text-white shadow-lg shadow-emerald-500/25">
              <NeuralSparkleIcon className="h-5 w-5 text-white" />
            </div>
            <div>
              <h1 className="text-sm font-extrabold tracking-tight flex items-center">
                <span className="text-emerald-400">Form</span>
                <span className="bg-gradient-to-r from-emerald-400 via-teal-300 to-amber-200 bg-clip-text text-transparent">Pilot</span>
              </h1>
              <p className="text-[11px] text-slate-400">Guided application assistant</p>
            </div>
          </div>
          <div className="flex items-center gap-2.5">
            {onContinueAsGuest && (
              <button
                type="button"
                onClick={onContinueAsGuest}
                className="flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 hover:bg-emerald-500/20 px-3.5 py-1.5 text-xs font-semibold text-emerald-300 transition-all shadow-sm"
              >
                <span>Continue as Guest</span>
                <ArrowRight className="h-3.5 w-3.5" />
              </button>
            )}
            <span className="hidden items-center gap-1.5 rounded-full border border-white/[0.08] bg-white/[0.03] px-3 py-1.5 text-[11px] font-medium text-slate-300 sm:flex">
              <SecurityShieldIcon className="h-3.5 w-3.5 text-emerald-400" />
              Private by default
            </span>
          </div>
        </header>

        <main className="flex flex-1 items-center justify-center py-8">
          <div className="grid w-full gap-8 lg:grid-cols-[1.05fr_0.95fr] lg:items-center">
            {/* Story side */}
            <section className="order-2 lg:order-1">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-300/20 bg-amber-200/[0.06] px-3 py-1 text-[10px] font-bold uppercase tracking-widest text-amber-200/90">
                <Sparkles className="h-3 w-3" />
                Your own workspace
              </span>
              <h2 className="mt-4 max-w-xl text-3xl font-extrabold leading-tight tracking-tight text-white sm:text-4xl">
                One calm place for every application you fill.
              </h2>
              <p className="mt-3 max-w-lg text-sm leading-relaxed text-slate-400">
                Create a FormPilot account to keep your identity vault, sealed documents and run
                history separate from everyone else on this instance. No shared global vault behind
                the login screen.
              </p>

              <ul className="mt-6 space-y-3">
                {BENEFITS.map((benefit) => (
                  <li key={benefit} className="flex items-start gap-2.5 text-[13px] leading-relaxed text-slate-300">
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400/90" />
                    <span>{benefit}</span>
                  </li>
                ))}
              </ul>

              <div className="mt-6 flex items-start gap-2.5 rounded-2xl border border-white/[0.07] bg-white/[0.02] px-4 py-3 text-[11px] leading-relaxed text-slate-400">
                <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-300/80" />
                <span>
                  Your FormPilot account is not a government portal account. It only protects what you
                  save here; the portal login stays yours and is entered by you.
                </span>
              </div>
            </section>

            {/* Auth card */}
            <section className="order-1 w-full lg:order-2">
              <div className="rounded-3xl border border-white/[0.09] bg-[#111815]/90 p-5 shadow-2xl shadow-black/40 backdrop-blur-xl sm:p-7">
                <div className="mb-5 flex rounded-2xl border border-white/[0.07] bg-black/20 p-1">
                  <button
                    type="button"
                    onClick={() => switchMode('login')}
                    className={`flex flex-1 items-center justify-center gap-1.5 rounded-xl px-3 py-2 text-xs font-bold transition-all ${
                      !isSignup
                        ? 'bg-emerald-500/15 text-emerald-200 shadow-sm shadow-black/20'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    <KeyRound className="h-3.5 w-3.5" />
                    Sign in
                  </button>
                  <button
                    type="button"
                    onClick={() => switchMode('signup')}
                    disabled={!accountsEnabled}
                    className={`flex flex-1 items-center justify-center gap-1.5 rounded-xl px-3 py-2 text-xs font-bold transition-all disabled:cursor-not-allowed disabled:opacity-40 ${
                      isSignup
                        ? 'bg-emerald-500/15 text-emerald-200 shadow-sm shadow-black/20'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    <UserPlus className="h-3.5 w-3.5" />
                    Create account
                  </button>
                </div>

                <div className="mb-5">
                  <div className="flex items-center justify-between">
                    <h3 className="text-lg font-bold tracking-tight text-white">
                      {isSignup ? 'Create your FormPilot account' : 'Sign in to FormPilot'}
                    </h3>
                    <span className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-bold text-emerald-300">
                      Optional
                    </span>
                  </div>
                  <p className="mt-1 text-[12px] leading-relaxed text-slate-400">
                    {isSignup
                      ? 'Create an account to keep your identity vault and sealed documents synced across sessions.'
                      : 'Sign in with Google to sync your saved profile, or continue as guest to test immediately.'}
                  </p>
                </div>

                <div className="space-y-2.5 mb-4">
                  {googleClientId ? (
                    <div className="flex flex-col items-center justify-center pt-1">
                      <div ref={googleBtnRef} className="w-full flex justify-center min-h-[44px]" />
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setShowGoogleGuide(true)}
                      disabled={busy}
                      className="flex w-full items-center justify-center gap-2.5 rounded-xl border border-white/10 bg-white/[0.05] hover:bg-white/[0.09] px-4 py-2.5 text-xs font-semibold text-slate-200 transition-all shadow-sm shadow-black/20"
                    >
                      <GoogleIcon className="h-4 w-4" />
                      <span>Continue with Google</span>
                      <span className="ml-auto rounded bg-emerald-500/20 px-1.5 py-0.5 text-[9px] font-bold text-emerald-300">Fast</span>
                    </button>
                  )}

                  <button
                    type="button"
                    onClick={handleDemoLogin}
                    disabled={busy}
                    className="flex w-full items-center justify-center gap-2 rounded-xl border border-emerald-500/30 bg-gradient-to-r from-emerald-500/15 via-teal-500/15 to-emerald-500/15 hover:from-emerald-500/25 hover:to-teal-500/25 px-3.5 py-2.5 text-xs font-bold text-emerald-200 transition-all shadow-md shadow-emerald-950/20 disabled:opacity-50"
                  >
                    <Sparkles className="h-4 w-4 text-emerald-400" />
                    <span>⚡ 1-Click Demo Sign-In (Candidate Nishant)</span>
                  </button>
                </div>

                <div className="relative my-4 text-center">
                  <div className="absolute inset-0 flex items-center">
                    <div className="w-full border-t border-white/[0.08]" />
                  </div>
                  <span className="relative bg-[#111815] px-3 text-[10px] uppercase tracking-widest text-slate-500 font-semibold">
                    or email & password
                  </span>
                </div>

                {!accountsEnabled ? (
                  <div className="rounded-2xl border border-amber-400/25 bg-amber-400/[0.07] px-4 py-3 text-[12px] leading-relaxed text-amber-100">
                    Account creation is disabled on this instance. You can continue in the local
                    single-user workspace.
                  </div>
                ) : (
                  <form onSubmit={submit} className="space-y-4">
                    {isSignup && (
                      <Field icon={User} label="Name (optional)">
                        <input
                          type="text"
                          value={name}
                          onChange={(event) => setName(event.target.value)}
                          autoComplete="name"
                          maxLength={80}
                          placeholder="How should FormPilot address you?"
                          className="w-full rounded-xl border border-white/[0.09] bg-black/25 px-3.5 py-2.5 text-sm text-slate-100 placeholder:text-slate-600 outline-none transition-colors focus:border-emerald-400/50 focus:ring-2 focus:ring-emerald-400/10"
                        />
                      </Field>
                    )}

                    <Field icon={Mail} label="Email">
                      <input
                        type="email"
                        value={email}
                        onChange={(event) => setEmail(event.target.value)}
                        autoComplete="email"
                        required
                        maxLength={254}
                        placeholder="you@example.com"
                        className="w-full rounded-xl border border-white/[0.09] bg-black/25 px-3.5 py-2.5 text-sm text-slate-100 placeholder:text-slate-600 outline-none transition-colors focus:border-emerald-400/50 focus:ring-2 focus:ring-emerald-400/10"
                      />
                    </Field>

                    <Field icon={Lock} label="Password">
                      <div className="relative">
                        <input
                          type={showPassword ? 'text' : 'password'}
                          value={password}
                          onChange={(event) => setPassword(event.target.value)}
                          autoComplete={isSignup ? 'new-password' : 'current-password'}
                          required
                          minLength={isSignup ? 8 : undefined}
                          maxLength={200}
                          placeholder={isSignup ? 'At least 8 characters' : 'Your password'}
                          className="w-full rounded-xl border border-white/[0.09] bg-black/25 px-3.5 py-2.5 pr-10 text-sm text-slate-100 placeholder:text-slate-600 outline-none transition-colors focus:border-emerald-400/50 focus:ring-2 focus:ring-emerald-400/10"
                        />
                        <button
                          type="button"
                          onClick={() => setShowPassword((value) => !value)}
                          className="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-slate-500 transition-colors hover:text-slate-300"
                          title={showPassword ? 'Hide password' : 'Show password'}
                          aria-label={showPassword ? 'Hide password' : 'Show password'}
                        >
                          {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                        </button>
                      </div>
                    </Field>

                    {error && (
                      <div role="alert" className="rounded-xl border border-red-400/30 bg-red-500/[0.08] px-3.5 py-2.5 text-[12px] leading-relaxed text-red-200">
                        {error}
                      </div>
                    )}

                    <button
                      type="submit"
                      disabled={busy || !email.trim() || !password}
                      className="flex w-full items-center justify-center gap-2 rounded-xl border border-emerald-400/30 bg-gradient-to-r from-emerald-500/20 via-teal-500/15 to-emerald-500/20 px-4 py-2.5 text-sm font-bold text-emerald-100 shadow-lg shadow-black/20 transition-all hover:from-emerald-500/30 hover:to-teal-500/25 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {busy ? (
                        <>
                          <Loader2 className="h-4 w-4 animate-spin" />
                          {isSignup ? 'Creating your workspace…' : 'Signing in…'}
                        </>
                      ) : (
                        <>
                          {isSignup ? 'Create account' : 'Sign in'}
                          <ArrowRight className="h-4 w-4" />
                        </>
                      )}
                    </button>
                  </form>
                )}

                <div className="mt-3 pt-3 border-t border-white/[0.08]">
                  <button
                    type="button"
                    onClick={onContinueAsGuest}
                    className="w-full rounded-xl border border-emerald-500/30 bg-emerald-500/10 hover:bg-emerald-500/20 px-4 py-2.5 text-xs font-bold text-emerald-200 transition-all flex items-center justify-center gap-2 shadow-sm"
                  >
                    <span>🚀 Continue as Guest (Instant Access)</span>
                    <ArrowRight className="h-3.5 w-3.5" />
                  </button>
                  <p className="mt-1 text-center text-[10px] text-slate-400">
                    No signup required. Test and explore the assistant immediately.
                  </p>
                </div>

                <p className="mt-4 flex items-start gap-1.5 text-[10px] leading-relaxed text-slate-500">
                  <ShieldCheck className="mt-0.5 h-3 w-3 shrink-0 text-emerald-500/80" />
                  Passwords are stored as salted PBKDF2 hashes. Session tokens are stored only as
                  digests, so a copy of the account file cannot be replayed.
                </p>
              </div>
            </section>
          </div>
        </main>

        {showGoogleGuide && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in">
            <div className="relative w-full max-w-md rounded-3xl border border-white/10 bg-[#141b18] p-6 shadow-2xl text-slate-200">
              <button
                type="button"
                onClick={() => setShowGoogleGuide(false)}
                className="absolute right-4 top-4 rounded-xl p-1.5 text-slate-400 hover:bg-white/5 hover:text-white"
              >
                <X className="h-5 w-5" />
              </button>

              <div className="flex items-center gap-2.5 mb-3">
                <div className="p-2 rounded-xl bg-white/5 border border-white/10">
                  <GoogleIcon className="h-5 w-5" />
                </div>
                <div>
                  <h4 className="text-sm font-bold text-white">Google Sign-In Configuration</h4>
                  <p className="text-[11px] text-slate-400">OAuth 2.0 Web Application Setup</p>
                </div>
              </div>

              <div className="space-y-2.5 text-xs text-slate-300 mb-5 leading-relaxed bg-black/30 p-3.5 rounded-2xl border border-white/5">
                <p className="font-semibold text-emerald-300">How to activate live Google login:</p>
                <ol className="list-decimal list-inside space-y-1.5 text-slate-400 text-[11px]">
                  <li>Open <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noreferrer" className="text-teal-400 underline inline-flex items-center gap-0.5">Google Cloud Console <ExternalLink className="h-2.5 w-2.5" /></a></li>
                  <li>Create an <strong>OAuth 2.0 Client ID</strong> (Web application)</li>
                  <li>Add JavaScript origin: <code className="text-emerald-300 bg-white/5 px-1 py-0.5 rounded font-mono text-[10px]">http://localhost:5173</code> and <code className="text-emerald-300 bg-white/5 px-1 py-0.5 rounded font-mono text-[10px]">http://127.0.0.1:8000</code></li>
                  <li>Set <code className="text-amber-300 bg-white/5 px-1 py-0.5 rounded font-mono text-[10px]">GOOGLE_CLIENT_ID=your-id.apps.googleusercontent.com</code> in <code className="text-slate-200">.env</code></li>
                </ol>
              </div>

              <div className="space-y-2">
                <button
                  type="button"
                  onClick={handleSimulatedGoogleLogin}
                  disabled={busy}
                  className="w-full flex items-center justify-center gap-2 py-2.5 px-4 rounded-xl bg-gradient-to-r from-emerald-500/20 to-teal-500/20 border border-emerald-500/40 text-xs font-bold text-emerald-200 hover:from-emerald-500/30 hover:to-teal-500/30 transition-all shadow-md"
                >
                  <Sparkles className="h-4 w-4 text-emerald-400" />
                  <span>⚡ Try Instant Simulated Google Sign-In</span>
                </button>
                <button
                  type="button"
                  onClick={() => setShowGoogleGuide(false)}
                  className="w-full py-2 px-3 rounded-xl border border-white/5 bg-white/[0.02] text-xs font-medium text-slate-400 hover:text-slate-200"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        )}

        <footer className="border-t border-white/[0.06] pt-4 text-center text-[11px] text-slate-500">
          <p>
            FormPilot is an independent application assistant. It is not a government website and does
            not submit applications or make payments on your behalf.
          </p>
          <p className="mt-1.5 flex flex-wrap items-center justify-center gap-x-1.5 gap-y-1 text-[10px] text-slate-600">
            <span>
              Built by <span className="font-semibold text-slate-400">Nishant</span>
            </span>
            <span aria-hidden="true" className="text-slate-700">·</span>
            <span>dev:</span>
            <a
              href="https://nishant-kr.vercel.app"
              target="_blank"
              rel="noreferrer"
              className="font-mono text-teal-400/90 underline decoration-teal-500/30 underline-offset-2 transition-colors hover:text-teal-300"
            >
              nishant-kr.vercel.app
            </a>
          </p>
        </footer>
      </div>
    </div>
  );
}
