import React, { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { api } from '../api'
import { ErrorBox } from '../ui.jsx'

const Frame = ({ title, sub, children }) => (
  <div className="flex min-h-screen items-center justify-center px-6 py-14">
    <div className="w-full max-w-sm space-y-6">
      <div><span className="silver-chip">Account</span><h1 className="mt-4 text-3xl font-semibold text-slate-900">{title}</h1><p className="mt-2 text-sm text-slate-500">{sub}</p></div>
      {children}
      <p className="text-center text-sm"><Link className="text-indigo-700 underline" to="/login">Back to sign in</Link></p>
    </div>
  </div>
)

export function ForgotPassword() {
  const [email, setEmail] = useState('')
  const [done, setDone] = useState(false)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  async function submit(e) {
    e.preventDefault(); setBusy(true); setErr(null)
    try { await api('/auth/password-reset/request', { method: 'POST', auth: false, body: { email } }); setDone(true) }
    catch (x) { setErr(x) } finally { setBusy(false) }
  }
  return (
    <Frame title="Reset your password" sub="Enter your account email and we will send a reset link, valid for one hour.">
      {done ? <p className="text-sm leading-6 text-slate-700">If that email belongs to an account, a reset link is on its way. If email is not set up on this server, ask an administrator to run <code>python -m app.manage set-password</code>.</p> : (
        <form onSubmit={submit} className="space-y-5">
          <ErrorBox error={err} />
          <div><label className="label" htmlFor="em">Email</label><input id="em" type="email" required autoFocus className="input" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
          <button className="btn-primary w-full py-3" disabled={busy}>{busy && <Loader2 className="h-4 w-4 animate-spin" />}Send reset link</button>
        </form>)}
    </Frame>
  )
}

export function ResetPassword() {
  const [params] = useSearchParams()
  const nav = useNavigate()
  const [pw, setPw] = useState('')
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  async function submit(e) {
    e.preventDefault(); setBusy(true); setErr(null)
    try { await api('/auth/password-reset/confirm', { method: 'POST', auth: false, body: { token: params.get('token') || '', new_password: pw } }); nav('/login') }
    catch (x) { setErr(x) } finally { setBusy(false) }
  }
  return (
    <Frame title="Choose a new password" sub="At least 10 characters, with a letter and a digit. All your other sessions will be signed out.">
      <form onSubmit={submit} className="space-y-5">
        <ErrorBox error={err} />
        <div><label className="label" htmlFor="np">New password</label><input id="np" type="password" autoComplete="new-password" required minLength={10} className="input" value={pw} onChange={(e) => setPw(e.target.value)} /></div>
        <button className="btn-primary w-full py-3" disabled={busy}>{busy && <Loader2 className="h-4 w-4 animate-spin" />}Set password</button>
      </form>
    </Frame>
  )
}
