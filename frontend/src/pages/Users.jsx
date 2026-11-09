import React, { useState } from 'react'
import { Plus, ShieldCheck } from 'lucide-react'
import { api } from '../api'
import { Badge, ErrorBox, PageHeader, Spinner, fmtDate, useLoad, useToast } from '../ui.jsx'

const ROLE_TONE = { ADMIN: 'red', FACULTY: 'indigo', ALUMNI: 'green', STUDENT: 'blue' }
const blank = { email: '', full_name: '', role: 'FACULTY', password: '', alumni_id: '' }

export default function Users() {
  const toast = useToast()
  const { data, error, loading, reload } = useLoad(() => api('/users'))
  const roles = useLoad(() => api('/roles'))
  const [f, setF] = useState(blank)
  const [open, setOpen] = useState(false)
  const [err, setErr] = useState(null)

  async function create(e) {
    e.preventDefault(); setErr(null)
    try {
      await api('/users', { method: 'POST', body: { ...f, alumni_id: f.role === 'ALUMNI' && f.alumni_id ? Number(f.alumni_id) : null } })
      toast('User created'); setF(blank); setOpen(false); reload()
    } catch (x) { setErr(x) }
  }
  const patch = async (u, body, msg) => { try { await api(`/users/${u.id}`, { method: 'PATCH', body }); toast(msg); reload() } catch (x) { toast(x.message, 'err') } }
  const endSessions = async (u) => { try { const r = await api(`/users/${u.id}/revoke-sessions`, { method: 'POST' }); toast(`${r.sessions_ended} session(s) ended`) } catch (x) { toast(x.message, 'err') } }

  return (
    <>
      <PageHeader eyebrow="Administration" title="Users & roles" sub="Who can sign in, and what each role may do. Changes take effect immediately and are written to the audit log.">
        <button className="btn-primary" onClick={() => setOpen(!open)}><Plus className="h-4 w-4" />Add user</button>
      </PageHeader>
      {open && (
        <form onSubmit={create} className="mb-10 grid gap-5 sm:grid-cols-2">
          <div className="sm:col-span-2"><ErrorBox error={err} /></div>
          <div><label className="label">Email</label><input className="input" type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></div>
          <div><label className="label">Full name</label><input className="input" value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></div>
          <div><label className="label">Role</label><select className="input" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>{['ADMIN', 'FACULTY', 'ALUMNI', 'STUDENT'].map((r) => <option key={r}>{r}</option>)}</select></div>
          {f.role === 'ALUMNI'
            ? <div><label className="label">Alumni record ID</label><input className="input" type="number" required value={f.alumni_id} onChange={(e) => setF({ ...f, alumni_id: e.target.value })} placeholder="from the alumni drawer URL / list" /></div>
            : <div />}
          <div><label className="label">Temporary password</label><input className="input" type="password" autoComplete="new-password" required minLength={10} value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></div>
          <div className="flex items-end"><button className="btn-primary">Create user</button></div>
        </form>)}
      {loading && <Spinner />}<ErrorBox error={error} retry={reload} />
      {data && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead><tr className="text-[11px] uppercase tracking-[0.12em] text-slate-500"><th className="py-2">User</th><th>Role</th><th>Status</th><th>Last sign-in</th><th /></tr></thead>
            <tbody>{data.items.map((u) => (
              <tr key={u.id} className="border-t border-sky-200">
                <td className="py-3"><div className="font-medium">{u.full_name || u.email}</div><div className="text-xs text-slate-500">{u.email}</div></td>
                <td><select className="input !w-auto" value={u.role} onChange={(e) => patch(u, { role: e.target.value }, 'Role updated')}>{['ADMIN', 'FACULTY', 'ALUMNI', 'STUDENT'].map((r) => <option key={r}>{r}</option>)}</select></td>
                <td>{!u.is_active ? <Badge tone="slate">Disabled</Badge> : u.locked ? <Badge tone="amber">Locked</Badge> : <Badge tone="green">Active</Badge>}</td>
                <td className="text-xs text-slate-500">{fmtDate(u.last_login_at)}</td>
                <td className="space-x-2 text-right">
                  <button className="btn-ghost" onClick={() => endSessions(u)}>End sessions</button>
                  <button className="btn-ghost" onClick={() => patch(u, { is_active: !u.is_active }, u.is_active ? 'Account disabled' : 'Account enabled')}>{u.is_active ? 'Disable' : 'Enable'}</button>
                </td>
              </tr>))}
            </tbody>
          </table>
        </div>)}
      {roles.data && (
        <section className="mt-14">
          <h2 className="mb-4 flex items-center gap-2 text-lg font-semibold"><ShieldCheck className="h-5 w-5 text-indigo-600" />What each role can do</h2>
          <div className="grid gap-6 md:grid-cols-2">{roles.data.roles.map((r) => (
            <div key={r.name}><div className="flex items-center gap-2"><Badge tone={ROLE_TONE[r.name]}>{r.name}</Badge></div>
              <p className="mt-2 text-sm text-slate-600">{r.description}</p>
              <ul className="mt-2 space-y-0.5 text-xs text-slate-500">{r.permissions.map((p) => <li key={p}>{roles.data.permissions[p]}</li>)}</ul></div>))}</div>
        </section>)}
    </>
  )
}
