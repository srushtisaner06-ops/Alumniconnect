import React, { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { api, clearSession } from '../api'
import { Badge, ErrorBox, PageHeader, Spinner, fmtDate, useLoad, useToast } from '../ui.jsx'

// What each role can do, in plain words. (The server enforces the real permissions; this is only an explanation.)
const ROLE_TEXT = {
  ADMIN: 'You can manage everything: records, imports, reminders, proof verification, reports, users and the audit log.',
  FACULTY: 'You can maintain alumni records, imports, exports, reminders, proof verification and reports. You cannot delete records or manage users.',
  ALUMNI: 'You can manage your own profile, career timeline and who may see them, and browse the alumni network.',
  STUDENT: 'You can browse the profiles that alumni have chosen to share with students.',
}

export default function Account() {
  const toast = useToast()
  const me = useLoad(() => api('/auth/me'))
  const sessions = useLoad(() => api('/auth/sessions'))
  const [f, setF] = useState({ current_password: '', new_password: '' })
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)

  async function change(e) {
    e.preventDefault(); setBusy(true); setErr(null)
    try {
      const r = await api('/auth/change-password', { method: 'POST', body: f })
      toast(r.other_sessions_ended ? `Password changed. ${r.other_sessions_ended} other device(s) signed out.` : 'Password changed')
      setF({ current_password: '', new_password: '' }); sessions.reload()
    } catch (x) { setErr(x) } finally { setBusy(false) }
  }
  const endOne = async (s) => { try { await api(`/auth/sessions/${s.id}`, { method: 'DELETE' }); toast('Device signed out'); sessions.reload() } catch (x) { toast(x.message, 'err') } }
  async function endAll() {
    if (!window.confirm('Sign out of every device, including this one?')) return
    try { await api('/auth/logout-all', { method: 'POST' }) } catch { /* already gone */ }
    clearSession(); window.location.href = '/login'
  }

  return (
    <>
      <PageHeader eyebrow="Account" title={me.data?.full_name || me.data?.email || 'Your account'} sub="Your sign-in details and security." />
      {me.loading && <Spinner />}<ErrorBox error={me.error} />
      {me.data && (
        <section className="mb-12 max-w-2xl">
          <p className="flex flex-wrap items-center gap-3 text-sm"><span>{me.data.email}</span><Badge tone="indigo">{me.data.role}</Badge></p>
          <p className="mt-2 text-sm leading-6 text-slate-600">{ROLE_TEXT[me.data.role]}</p>
        </section>)}

      <section className="mb-12 max-w-md">
        <h2 className="mb-4 text-xl font-semibold">Change password</h2>
        <form onSubmit={change} className="space-y-4">
          <ErrorBox error={err} />
          <div><label className="label" htmlFor="cp">Current password</label><input id="cp" type="password" autoComplete="current-password" required className="input" value={f.current_password} onChange={(e) => setF({ ...f, current_password: e.target.value })} /></div>
          <div><label className="label" htmlFor="np">New password</label><input id="np" type="password" autoComplete="new-password" required minLength={10} className="input" value={f.new_password} onChange={(e) => setF({ ...f, new_password: e.target.value })} />
            <p className="mt-1 text-xs text-slate-500">At least 10 characters, with a letter and a digit.</p></div>
          <button className="btn-primary" disabled={busy}>{busy && <Loader2 className="h-4 w-4 animate-spin" />}Change password</button>
        </form>
      </section>

      <section className="max-w-2xl">
        <div className="mb-4 flex items-center justify-between"><h2 className="text-xl font-semibold">Where you are signed in</h2><button className="btn-ghost" onClick={endAll}>Sign out everywhere</button></div>
        {sessions.loading && <Spinner />}
        <ul className="divide-y divide-sky-200">{sessions.data?.items.map((s) => (
          <li key={s.id} className="flex items-center justify-between gap-4 py-3 text-sm">
            <div><div className="font-medium">{s.current ? 'This device' : 'Another device'} {s.current && <Badge tone="green">current</Badge>}</div>
              <div className="max-w-md truncate text-xs text-slate-500">{s.user_agent || 'Unknown browser'} · {s.ip || 'unknown address'} · signed in {fmtDate(s.created_at)}</div></div>
            {!s.current && <button className="btn-ghost" onClick={() => endOne(s)}>Sign out</button>}
          </li>))}</ul>
      </section>
    </>
  )
}
