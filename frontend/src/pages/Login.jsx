import React, { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { GraduationCap, Loader2, ShieldCheck } from 'lucide-react'
import { api, setSession, setToken } from '../api'
import { ErrorBox } from '../ui.jsx'

export default function Login() {
  const nav = useNavigate()
  const [f, setF] = useState({ email: '', password: '' })
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  async function submit(e) {
    e.preventDefault(); setBusy(true); setErr(null)
    try { const r = await api('/auth/login', { method: 'POST', body: f, auth: false }); setToken(r.token); setSession({ email: r.email, role: r.role, full_name: r.full_name, permissions: r.permissions }); nav('/dashboard') }
    catch (x) { setErr(x) } finally { setBusy(false) }
  }
  return (
    <div className="grid min-h-screen lg:grid-cols-[1.15fr_1fr]">
      {/* picture side: full-bleed, no frame */}
      <section className="relative flex flex-col justify-between overflow-hidden bg-gradient-to-br from-blue-900 via-blue-800 to-indigo-800 px-8 pb-0 pt-10 text-white sm:px-14 lg:min-h-screen">
        <div className="pointer-events-none absolute -right-24 -top-24 h-96 w-96 rounded-full bg-indigo-300/25 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-32 -left-20 h-96 w-96 rounded-full bg-sky-200/20 blur-3xl" />
        <div className="relative">
          <div className="flex items-center gap-3">
            <div className="silver-bg flex h-11 w-11 items-center justify-center rounded-full p-0.5"><div className="flex h-full w-full items-center justify-center rounded-full bg-blue-900"><GraduationCap className="h-5 w-5" /></div></div>
            <div className="font-display text-2xl font-semibold">Alumni<span className="text-indigo-200">Connect</span></div>
          </div>
          <span className="silver-chip mt-12 !text-slate-800">Institutional portal</span>
          <h1 className="mt-5 max-w-lg text-4xl font-semibold leading-[1.1] sm:text-5xl">Every graduate, <span className="text-indigo-200">one place.</span></h1>
          <p className="mt-5 max-w-md text-base leading-7 text-slate-200">Maintain alumni records, follow up on submissions and prepare institutional reports from a single, calm workspace.</p>
        </div>
        <img src="/img/hero-campus.svg" alt="" className="relative mx-auto mt-8 w-full max-w-xl translate-y-2 drop-shadow-2xl" />
      </section>

      {/* form side: open, no card */}
      <section className="flex items-center px-8 py-14 sm:px-14 lg:px-20">
        <form onSubmit={submit} className="mx-auto w-full max-w-sm space-y-7">
          <div>
            <span className="silver-chip">Welcome back</span>
            <h2 className="mt-4 text-4xl font-semibold tracking-tight text-slate-900">Sign in</h2>
            <p className="mt-3 text-sm leading-6 text-slate-500">Sign in with your institutional account.</p>
            <div className="silver-mark mt-5 w-24" />
          </div>
          <ErrorBox error={err} />
          <div><label className="label" htmlFor="email">Institutional email</label><input id="email" type="email" autoComplete="username" required autoFocus className="input" placeholder="name@college.edu" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></div>
          <div><label className="label" htmlFor="pw">Password</label><input id="pw" type="password" autoComplete="current-password" required className="input" placeholder="Enter your password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></div>
          <button className="btn-primary w-full py-3.5 text-base" disabled={busy}>{busy && <Loader2 className="h-4 w-4 animate-spin" />}{busy ? 'Signing in…' : 'Sign in securely'}</button>
          <p className="text-center text-sm"><Link className="text-indigo-700 underline" to="/forgot-password">Forgot your password?</Link></p>
          <p className="flex items-center justify-center gap-2 text-center text-xs leading-5 text-slate-400"><ShieldCheck className="h-4 w-4 shrink-0" />For authorised users only. Sign-ins are recorded.</p>
        </form>
      </section>
    </div>
  )
}
