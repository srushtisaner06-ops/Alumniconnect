import React, { useEffect, useState } from 'react'
import { Copy, Plus, ShieldCheck } from 'lucide-react'
import { api } from '../api'
import { Badge, ErrorBox, PageHeader, Spinner, fmtDate, useLoad, useToast } from '../ui.jsx'

const ROLE_TONE = { ADMIN: 'red', FACULTY: 'indigo', ALUMNI: 'green', STUDENT: 'blue' }
const blank = { email: '', full_name: '', role: 'FACULTY', password: '', alumni_id: '', manual: false }

export default function Users() {
  const toast = useToast()
  const { data, error, loading, reload } = useLoad(() => api('/users'))
  const roles = useLoad(() => api('/roles'))
  const [f, setF] = useState(blank)
  const [open, setOpen] = useState(false)
  const [err, setErr] = useState(null)
  const [invite, setInvite] = useState(null)       // link to hand over when email is not set up on the server
  const [q, setQ] = useState('')
  const [hits, setHits] = useState([])
  const [picked, setPicked] = useState(null)

  useEffect(() => {   // find the alumnus by name / PRN instead of typing a database number
    const t = q.trim()
    if (f.role !== 'ALUMNI' || t.length < 2) { setHits([]); return }
    const h = setTimeout(() => api(`/alumni?search=${encodeURIComponent(t)}&page_size=6`).then((r) => setHits(r.items)).catch(() => setHits([])), 250)
    return () => clearTimeout(h)
  }, [q, f.role])

  async function create(e) {
    e.preventDefault(); setErr(null); setInvite(null)
    if (f.role === 'ALUMNI' && !picked) { setErr('Search for and choose the alumnus this login belongs to.'); return }
    try {
      const body = { email: f.email, full_name: f.full_name || null, role: f.role, alumni_id: f.role === 'ALUMNI' ? picked.id : null, password: f.manual ? f.password : null }
      const r = await api('/users', { method: 'POST', body })
      if (r.invite_link) setInvite({ email: f.email, link: r.invite_link }); else toast(r.invited ? 'Invite emailed' : 'User created')
      setF(blank); setPicked(null); setQ(''); setOpen(false); reload()
    } catch (x) { setErr(x) }
  }
  const patch = async (u, body, msg) => { try { await api(`/users/${u.id}`, { method: 'PATCH', body }); toast(msg); reload() } catch (x) { toast(x.message, 'err') } }
  const endSessions = async (u) => { try { const r = await api(`/users/${u.id}/revoke-sessions`, { method: 'POST' }); toast(`${r.sessions_ended} session(s) ended`) } catch (x) { toast(x.message, 'err') } }

  return (
    <>
      <PageHeader eyebrow="Administration" title="Users & roles" sub="Nobody can register themselves: accounts are created here. Invite faculty, alumni and students, choose what each role may do, and disable or sign out anyone. Changes take effect immediately and are written to the audit log.">
        <button className="btn-primary" onClick={() => setOpen(!open)}><Plus className="h-4 w-4" />Add user</button>
      </PageHeader>
      {open && (
        <form onSubmit={create} className="mb-10 grid gap-5 sm:grid-cols-2">
          <div className="sm:col-span-2"><ErrorBox error={err} /></div>
          <div><label className="label">Email</label><input className="input" type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></div>
          <div><label className="label">Full name</label><input className="input" value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></div>
          <div><label className="label">Role</label><select className="input" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>{['ADMIN', 'FACULTY', 'ALUMNI', 'STUDENT'].map((r) => <option key={r}>{r}</option>)}</select></div>
          {f.role === 'ALUMNI'
            ? <div className="relative"><label className="label">Alumnus</label>
                {picked ? <p className="flex items-center justify-between border-b border-sky-300 py-2 text-sm"><span>{picked.name} · {picked.prn}</span><button type="button" className="text-xs underline" onClick={() => { setPicked(null); setQ('') }}>change</button></p> : <>
                  <input className="input" placeholder="Search by name or PRN" value={q} onChange={(e) => setQ(e.target.value)} />
                  {hits.length > 0 && <ul className="absolute z-10 mt-1 w-full border border-sky-200 bg-white shadow">{hits.map((h) => (
                    <li key={h.id}><button type="button" className="block w-full px-3 py-2 text-left text-sm hover:bg-sky-50" onClick={() => { setPicked(h); setHits([]); if (!f.email && h.email) setF((x) => ({ ...x, email: h.email, full_name: x.full_name || h.name })) }}>{h.name} <span className="text-slate-500">· {h.prn} · batch {h.graduation_year}</span></button></li>))}</ul>}</>}
              </div>
            : <div />}
          <div className="sm:col-span-2 space-y-3">
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.manual} onChange={(e) => setF({ ...f, manual: e.target.checked })} />Set the password myself instead of sending an invite</label>
            {f.manual
              ? <div className="max-w-sm"><label className="label">Password</label><input className="input" type="password" autoComplete="new-password" required minLength={10} value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></div>
              : <p className="text-sm text-slate-500">The person receives a link to choose their own password (valid 72 hours). You never have to know or send one.</p>}
          </div>
          <div className="flex items-end"><button className="btn-primary">{f.manual ? 'Create user' : 'Send invite'}</button></div>
        </form>)}
      {invite && (
        <div className="mb-8 border-l-4 border-amber-400 bg-amber-50 px-4 py-3 text-sm">
          <p className="font-medium">Email is not set up on this server, so share this link with {invite.email} yourself.</p>
          <p className="mt-1 text-slate-600">It lets them choose their own password. It works once and expires in 72 hours, and it will not be shown again.</p>
          <div className="mt-2 flex gap-2"><input readOnly className="input font-mono text-xs" value={invite.link} onFocus={(e) => e.target.select()} />
            <button className="btn-ghost" aria-label="Copy invite link" onClick={() => { navigator.clipboard.writeText(invite.link); toast('Link copied') }}><Copy className="h-4 w-4" /></button>
            <button className="btn-ghost" onClick={() => setInvite(null)}>Done</button></div>
        </div>)}
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
