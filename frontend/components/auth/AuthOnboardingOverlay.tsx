/**
 * AuthOnboardingOverlay — auth passthrough, never blocks (UI-MIG-T7)
 *
 * Owner: M-E (Frontend Chat & App Shell)
 * Module: frontend/components/auth/AuthOnboardingOverlay.tsx
 *
 * Ported steps from source design `auth/AuthOnboardingOverlay` (READ-ONLY):
 * splash -> role-select -> official-login / public-welcome.
 *
 * Standing pref: AppContext.authStep defaults to 'authenticated' and every
 * auth action (loginAsOfficial/loginAsPublic/setAuthStep) resolves back to
 * 'authenticated' — so by default this overlay renders null and NEVER shows
 * a login wall. The full step UI below only renders if a non-authenticated
 * step is ever set, and every CTA completes instantly without reload.
 */

'use client';

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Navigation,
  ShieldCheck,
  Compass,
  MessageSquareText,
  ArrowRight,
  Sparkles,
  Lock,
  Building2,
  KeyRound,
  UserCheck,
  Anchor,
  X,
  ChevronLeft,
  Info,
  Mic,
} from 'lucide-react';
import { useApp } from '@/context/AppContext';

export const AuthOnboardingOverlay: React.FC = () => {
  const { authStep, setAuthStep, loginAsOfficial, loginAsPublic } = useApp();

  const [email, setEmail] = useState('officer@incois.gov.in');
  const [password, setPassword] = useState('••••••••••••');
  const [org] = useState('INCOIS Coastal Operations');

  // Auth passthrough: default 'authenticated' never blocks the shell.
  if (authStep === 'authenticated') return null;

  return (
    <div
      data-testid="auth-overlay"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 overflow-y-auto bg-slate-950/80 backdrop-blur-xl"
    >
      <div className="relative w-full max-w-2xl my-auto">
        <AnimatePresence mode="wait">
          {authStep === 'splash' && (
            <motion.div
              key="splash"
              initial={{ opacity: 0, scale: 0.95, y: 15 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: -15 }}
              transition={{ duration: 0.3, ease: 'easeOut' }}
              className="relative overflow-hidden rounded-3xl border border-cyan-500/40 bg-slate-950/90 shadow-2xl p-8 sm:p-10 text-center"
            >
              <div className="absolute -top-24 -left-24 w-72 h-72 bg-cyan-500/20 rounded-full blur-3xl pointer-events-none" />
              <div className="absolute -bottom-24 -right-24 w-72 h-72 bg-teal-500/20 rounded-full blur-3xl pointer-events-none" />

              <div className="relative z-10 space-y-6">
                <div className="flex flex-col items-center justify-center gap-3">
                  <div className="relative">
                    <div className="w-20 h-20 rounded-3xl bg-gradient-to-br from-cyan-400 via-teal-500 to-emerald-500 p-0.5 shadow-2xl shadow-cyan-500/30 flex items-center justify-center animate-pulse">
                      <div className="w-full h-full bg-slate-950 rounded-[22px] flex items-center justify-center">
                        <Navigation className="w-10 h-10 text-cyan-400 rotate-45 stroke-[2.5]" />
                      </div>
                    </div>
                    <span className="absolute -bottom-2 -right-2 px-2 py-0.5 bg-emerald-500 text-slate-950 font-black text-[10px] rounded-full shadow-lg">
                      SIH 2026
                    </span>
                  </div>

                  <div>
                    <h1 className="text-4xl sm:text-5xl font-black tracking-wider text-transparent bg-clip-text bg-gradient-to-r from-cyan-300 via-teal-200 to-emerald-300">
                      ORCA
                    </h1>
                    <p className="text-xs sm:text-sm font-extrabold uppercase tracking-widest text-cyan-400 mt-1">
                      Marine Ecosystem Reasoning with Collaborative Agents
                    </p>
                  </div>
                </div>

                <div className="py-3 px-6 rounded-2xl bg-cyan-950/40 border border-cyan-500/30 inline-block shadow-inner">
                  <p className="text-sm sm:text-base font-semibold text-slate-200 italic">
                    “From Ocean Data to Intelligent Decisions.”
                  </p>
                </div>

                <div className="flex flex-wrap justify-center gap-2 pt-2">
                  <span className="px-3 py-1 rounded-full text-xs font-semibold bg-slate-900 border border-slate-800 text-slate-300">
                    🌊 Multi-Agent Intelligence
                  </span>
                  <span className="px-3 py-1 rounded-full text-xs font-semibold bg-slate-900 border border-slate-800 text-slate-300">
                    ⚓ Safe Fishing Zones (PFZ)
                  </span>
                  <span className="px-3 py-1 rounded-full text-xs font-semibold bg-slate-900 border border-slate-800 text-slate-300">
                    🗣️ Bhashini Voice Assistant
                  </span>
                </div>

                <div className="pt-4">
                  <button
                    type="button"
                    onClick={() => setAuthStep('role-select')}
                    data-testid="auth-continue"
                    className="w-full py-4 rounded-2xl bg-gradient-to-r from-cyan-400 via-teal-400 to-emerald-400 text-slate-950 font-black text-base shadow-xl shadow-cyan-500/25 hover:scale-[1.02] active:scale-[0.99] transition-all flex items-center justify-center gap-3 group"
                  >
                    <span>Continue to ORCA</span>
                    <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform stroke-[2.5]" />
                  </button>
                </div>
              </div>
            </motion.div>
          )}

          {authStep === 'role-select' && (
            <motion.div
              key="role-select"
              initial={{ opacity: 0, scale: 0.95, y: 15 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: -15 }}
              transition={{ duration: 0.3, ease: 'easeOut' }}
              className="relative overflow-hidden rounded-3xl border border-cyan-500/40 bg-slate-950/90 shadow-2xl p-6 sm:p-8"
            >
              <div className="text-center space-y-2 mb-6">
                <span className="px-3 py-1 rounded-full text-[11px] font-extrabold uppercase tracking-widest bg-cyan-950 text-cyan-300 border border-cyan-800">
                  Step 1 of 2 • Role Selection
                </span>
                <h2 className="text-2xl sm:text-3xl font-black text-white">Welcome to ORCA</h2>
                <p className="text-xs sm:text-sm text-slate-400 font-medium">
                  Choose how you want to use ORCA
                </p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="relative rounded-2xl p-5 border border-cyan-500/40 bg-slate-900/90 flex flex-col justify-between space-y-4 group hover:border-cyan-400">
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="w-12 h-12 rounded-xl bg-cyan-500/20 border border-cyan-500/40 flex items-center justify-center text-cyan-400 group-hover:scale-110 transition-transform">
                        <ShieldCheck className="w-6 h-6" />
                      </div>
                      <span className="text-[10px] font-extrabold px-2 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-800">
                        Official Access
                      </span>
                    </div>
                    <div>
                      <h3 className="text-base font-extrabold text-white">
                        OFFICIAL / PROFESSIONAL ACCESS
                      </h3>
                      <p className="text-xs text-slate-400 mt-1 leading-relaxed">
                        For coastal officers, maritime authorities, researchers and
                        operational teams
                      </p>
                    </div>
                  </div>

                  <button
                    type="button"
                    onClick={() => setAuthStep('official-login')}
                    data-testid="auth-official-access"
                    className="w-full py-3 rounded-xl bg-gradient-to-r from-cyan-500 to-teal-600 text-white font-bold text-xs shadow-lg hover:brightness-110 active:scale-[0.99] transition-all flex items-center justify-center gap-2"
                  >
                    <span>Official Access</span>
                    <ArrowRight className="w-4 h-4" />
                  </button>
                </div>

                <div className="relative rounded-2xl p-5 border border-emerald-500/40 bg-slate-900/90 flex flex-col justify-between space-y-4 group hover:border-emerald-400">
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="w-12 h-12 rounded-xl bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center text-emerald-400 group-hover:scale-110 transition-transform">
                        <Anchor className="w-6 h-6" />
                      </div>
                      <span className="text-[10px] font-extrabold px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800">
                        Public & Voice Access
                      </span>
                    </div>
                    <div>
                      <h3 className="text-base font-extrabold text-white">
                        FISHERFOLK / PUBLIC ACCESS
                      </h3>
                      <p className="text-xs text-slate-400 mt-1 leading-relaxed">
                        For fishermen and users seeking marine information without
                        complicated forms
                      </p>
                    </div>
                  </div>

                  <button
                    type="button"
                    onClick={() => setAuthStep('public-welcome')}
                    data-testid="auth-public-access"
                    className="w-full py-3 rounded-xl bg-gradient-to-r from-teal-400 to-emerald-400 text-slate-950 font-bold text-xs shadow-lg hover:brightness-110 active:scale-[0.99] transition-all flex items-center justify-center gap-2"
                  >
                    <span>Explore ORCA</span>
                    <ArrowRight className="w-4 h-4 stroke-[2.5]" />
                  </button>
                </div>
              </div>

              <div className="pt-6 text-center">
                <button
                  type="button"
                  onClick={() => setAuthStep('splash')}
                  className="text-xs text-slate-400 hover:text-white transition-colors inline-flex items-center gap-1 font-semibold"
                >
                  <ChevronLeft className="w-4 h-4" />
                  <span>Back to Landing</span>
                </button>
              </div>
            </motion.div>
          )}

          {authStep === 'official-login' && (
            <motion.div
              key="official-login"
              initial={{ opacity: 0, scale: 0.95, y: 15 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: -15 }}
              transition={{ duration: 0.3, ease: 'easeOut' }}
              className="relative overflow-hidden rounded-3xl border border-cyan-500/40 bg-slate-950/90 shadow-2xl p-6 sm:p-8"
            >
              <div className="flex items-center justify-between pb-4 border-b border-slate-800">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-cyan-500/20 border border-cyan-500/40 flex items-center justify-center text-cyan-400">
                    <ShieldCheck className="w-5 h-5" />
                  </div>
                  <div>
                    <h2 className="text-xl font-extrabold text-white">Official ORCA Access</h2>
                    <p className="text-xs text-slate-400">Maritime Command & Operations Portal</p>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => setAuthStep('role-select')}
                  aria-label="Back to role selection"
                  className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  loginAsOfficial(email, org);
                }}
                className="space-y-4 pt-4"
              >
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                    Official Email / Organization ID:
                  </label>
                  <div className="relative">
                    <Building2 className="w-4 h-4 text-slate-500 absolute left-3 top-3" />
                    <input
                      type="email"
                      required
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="officer@incois.gov.in"
                      data-testid="auth-email"
                      className="w-full pl-9 pr-3 py-2.5 bg-slate-900 border border-slate-800 rounded-xl text-xs text-slate-200 focus:outline-none focus:border-cyan-500 transition-colors font-mono"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                    Password:
                  </label>
                  <div className="relative">
                    <KeyRound className="w-4 h-4 text-slate-500 absolute left-3 top-3" />
                    <input
                      type="password"
                      required
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="••••••••••••"
                      data-testid="auth-password"
                      className="w-full pl-9 pr-3 py-2.5 bg-slate-900 border border-slate-800 rounded-xl text-xs text-slate-200 focus:outline-none focus:border-cyan-500 transition-colors font-mono"
                    />
                  </div>
                </div>

                <button
                  type="submit"
                  data-testid="auth-signin"
                  className="w-full py-3 rounded-xl bg-gradient-to-r from-cyan-500 via-teal-500 to-emerald-500 text-slate-950 font-extrabold text-xs shadow-lg shadow-cyan-500/20 hover:brightness-110 active:scale-[0.99] transition-all flex items-center justify-center gap-2"
                >
                  <UserCheck className="w-4 h-4 stroke-[2.5]" />
                  <span>Sign In</span>
                </button>
              </form>

              <div className="mt-4 pt-3 border-t border-slate-900">
                <button
                  type="button"
                  onClick={() => loginAsOfficial(email, org)}
                  data-testid="auth-demo-access"
                  className="w-full py-2.5 rounded-xl bg-cyan-950/60 border border-cyan-800/80 text-cyan-300 text-xs font-bold hover:bg-cyan-900/60 transition-colors flex items-center justify-center gap-2"
                >
                  <Sparkles className="w-4 h-4 text-cyan-400" />
                  <span>Demo Access (1-Click Login as Maritime Officer)</span>
                </button>
              </div>

              <div className="mt-4 pt-3 border-t border-slate-900 space-y-2">
                <p className="text-[11px] text-slate-400 font-semibold text-center">
                  Institutional Authentication (OAuth2 / SAML)
                </p>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => loginAsOfficial('sso.officer@nic.in', 'NIC Maritime SSO Portal')}
                    className="py-2 px-3 rounded-xl bg-slate-900 border border-slate-800 text-slate-300 hover:text-white hover:border-slate-700 text-[11px] font-medium transition-colors flex items-center justify-center gap-2"
                  >
                    <Lock className="w-3.5 h-3.5 text-cyan-400" />
                    <span>Institutional SSO / OAuth2</span>
                  </button>

                  <button
                    type="button"
                    onClick={() =>
                      loginAsOfficial('dept.maritime@gov.in', 'Government Maritime Directorate')
                    }
                    className="py-2 px-3 rounded-xl bg-slate-900 border border-slate-800 text-slate-300 hover:text-white hover:border-slate-700 text-[11px] font-medium transition-colors flex items-center justify-center gap-2"
                  >
                    <Building2 className="w-3.5 h-3.5 text-teal-400" />
                    <span>Organization Login</span>
                  </button>
                </div>
              </div>

              <div className="mt-4 p-2.5 rounded-xl bg-slate-900/80 border border-slate-800 flex items-start gap-2 text-[11px] text-slate-400">
                <Info className="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" />
                <span>
                  Frontend authentication states enabled. Ready to connect with FastAPI &
                  OAuth2 backend providers.
                </span>
              </div>
            </motion.div>
          )}

          {authStep === 'public-welcome' && (
            <motion.div
              key="public-welcome"
              initial={{ opacity: 0, scale: 0.95, y: 15 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: -15 }}
              transition={{ duration: 0.3, ease: 'easeOut' }}
              className="relative overflow-hidden rounded-3xl border border-emerald-500/40 bg-slate-950/90 shadow-2xl p-6 sm:p-8"
            >
              <div className="flex items-center justify-between pb-4 border-b border-slate-800">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center text-emerald-400">
                    <Anchor className="w-5 h-5" />
                  </div>
                  <div>
                    <h2 className="text-2xl font-black text-white">Ask ORCA about the sea.</h2>
                    <p className="text-xs text-emerald-400 font-medium">
                      Voice-first marine advisory for fishermen & public users
                    </p>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => setAuthStep('role-select')}
                  aria-label="Back to role selection"
                  className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 my-5">
                <button
                  type="button"
                  onClick={() => loginAsPublic('voice')}
                  data-testid="auth-public-voice"
                  className="p-4 rounded-2xl border border-cyan-500/40 bg-slate-900/90 hover:bg-cyan-950/50 hover:border-cyan-400 transition-all text-center space-y-2 group"
                >
                  <div className="w-12 h-12 mx-auto rounded-xl bg-cyan-500/20 border border-cyan-500/40 flex items-center justify-center text-cyan-300 group-hover:scale-110 transition-transform">
                    <Mic className="w-6 h-6 animate-pulse" />
                  </div>
                  <h4 className="text-sm font-extrabold text-white flex items-center justify-center gap-1">
                    🎙️ Ask by Voice
                  </h4>
                  <p className="text-[11px] text-slate-400 leading-tight">
                    Speak naturally in Indian languages
                  </p>
                </button>

                <button
                  type="button"
                  onClick={() => loginAsPublic('chat')}
                  data-testid="auth-public-chat"
                  className="p-4 rounded-2xl border border-teal-500/40 bg-slate-900/90 hover:bg-teal-950/50 hover:border-teal-400 transition-all text-center space-y-2 group"
                >
                  <div className="w-12 h-12 mx-auto rounded-xl bg-teal-500/20 border border-teal-500/40 flex items-center justify-center text-teal-300 group-hover:scale-110 transition-transform">
                    <MessageSquareText className="w-6 h-6" />
                  </div>
                  <h4 className="text-sm font-extrabold text-white flex items-center justify-center gap-1">
                    ⌨️ Ask by Text
                  </h4>
                  <p className="text-[11px] text-slate-400 leading-tight">
                    Text query & PFZ AI reasoning
                  </p>
                </button>

                <button
                  type="button"
                  onClick={() => loginAsPublic('map')}
                  data-testid="auth-public-map"
                  className="p-4 rounded-2xl border border-emerald-500/40 bg-slate-900/90 hover:bg-emerald-950/50 hover:border-emerald-400 transition-all text-center space-y-2 group"
                >
                  <div className="w-12 h-12 mx-auto rounded-xl bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center text-emerald-300 group-hover:scale-110 transition-transform">
                    <Compass className="w-6 h-6" />
                  </div>
                  <h4 className="text-sm font-extrabold text-white flex items-center justify-center gap-1">
                    🗺️ Explore Map
                  </h4>
                  <p className="text-[11px] text-slate-400 leading-tight">
                    View live PFZ & wave conditions
                  </p>
                </button>
              </div>

              <div className="p-3 rounded-2xl bg-emerald-950/40 border border-emerald-500/30 text-center space-y-1">
                <span className="px-2.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 text-[11px] font-extrabold border border-emerald-500/30 inline-block">
                  ✓ Instant Access
                </span>
                <p className="text-xs font-semibold text-slate-200">
                  No account required for basic marine information.
                </p>
              </div>

              <div className="mt-5">
                <button
                  type="button"
                  onClick={() => loginAsPublic()}
                  data-testid="auth-start-exploring"
                  className="w-full py-3.5 rounded-2xl bg-gradient-to-r from-teal-400 to-emerald-400 text-slate-950 font-black text-sm shadow-xl shadow-emerald-500/20 hover:scale-[1.01] active:scale-[0.99] transition-all flex items-center justify-center gap-2"
                >
                  <span>Start Exploring ORCA</span>
                  <ArrowRight className="w-4 h-4 stroke-[2.5]" />
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
};

export default AuthOnboardingOverlay;
