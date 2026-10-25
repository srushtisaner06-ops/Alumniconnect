import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { GraduationCap, Loader2, ShieldCheck } from 'lucide-react'
import { api, setToken } from '../api'
import { ErrorBox } from '../ui.jsx'

export default function Login() {
  const nav = useNavigate()
  const [f, setF] = useState({ email: '', password: '' })
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  async function submit(e) {
    e.preventDefault(); setBusy(true); setErr(null)
    try { const r = await api('/auth/login', { method: 'POST', body: f, auth: false }); setToken(r.token); nav('/dashboard') }
    catch (x) { setErr(x) } finally { setBusy(false) }
  }
  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-slate-50 px-4 py-10">
      <div className="absolute inset-x-0 top-0 h-2 bg-blue-800" />
      <div className="grid w-full max-w-4xl overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl shadow-slate-200/60 md:grid-cols-2">
        <div className="hidden flex-col justify-between bg-blue-900 p-10 text-white md:flex">
          <div><div className="flex h-12 w-12 items-center justify-center rounded-xl bg-white/10"><GraduationCap className="h-7 w-7" /></div><div className="mt-8 text-xs font-semibold uppercase tracking-[0.2em] text-blue-200">Institutional portal</div><h1 className="mt-3 text-3xl font-semibold leading-tight">AlumniConnect</h1><p className="mt-4 max-w-xs text-sm leading-6 text-blue-100">A central workspace to maintain alumni records, follow up on submissions and prepare institutional reports.</p></div>
          <div className="flex items-center gap-2 text-xs text-blue-200"><ShieldCheck className="h-4 w-4" />Authorised faculty access</div>
        </div>
        <form onSubmit={submit} className="space-y-5 p-6 sm:p-10">
          <div className="flex items-center gap-3 md:hidden"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-800 text-white"><GraduationCap className="h-6 w-6" /></div><div><div className="font-bold text-slate-900">AlumniConnect</div><div className="text-xs text-slate-500">Institutional portal</div></div></div>
          <div><div className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-800">Welcome back</div><h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">Faculty sign in</h2><p className="mt-2 text-sm leading-6 text-slate-500">Sign in to access the alumni administration workspace.</p></div>
          <ErrorBox error={err} />
          <div><label className="label" htmlFor="email">Institutional email</label><input id="email" type="email" autoComplete="username" required autoFocus className="input" placeholder="name@college.edu" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></div>
          <div><label className="label" htmlFor="pw">Password</label><input id="pw" type="password" autoComplete="current-password" required className="input" placeholder="Enter your password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></div>
          <button className="btn-primary w-full py-3" disabled={busy}>{busy && <Loader2 className="h-4 w-4 animate-spin" />}{busy ? 'Signing in…' : 'Sign in securely'}</button>
          <p className="text-center text-xs leading-5 text-slate-400">For authorised college personnel only. Keep your sign-in details private.</p>
        </form>
      </div>
    </div>
  )
}
