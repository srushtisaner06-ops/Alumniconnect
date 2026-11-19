import React, { useEffect, useState } from 'react'
import { CalendarDays, Clock, ExternalLink, MapPin, Pencil, Plus, Search, Trash2, Users, X } from 'lucide-react'
import { api, can } from '../api'
import { Badge, ErrorBox, PageHeader, Spinner, useToast } from '../ui.jsx'

const TABS = [['upcoming', 'Upcoming'], ['past', 'Past']]
const SIZE = 20
const blank = { name: '', description: '', event_date: '', event_time: '', venue: '', registration_link: '' }
const dateLabel = (d) => new Date(d + 'T00:00:00').toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })
const timeLabel = (t) => { const [h, m] = t.split(':').map(Number); return `${h % 12 || 12}:${String(m).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}` }
const stamp = (s) => new Date(s.replace(' ', 'T') + 'Z').toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })

function Form({ initial, today, onDone, onCancel }) {
  const toast = useToast()
  const editing = !!initial.id
  const [f, setF] = useState({ ...blank, ...initial, registration_link: initial.registration_link || '' })
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  async function save(e) {
    e.preventDefault(); setErr(null); setBusy(true)
    const body = { name: f.name, description: f.description, event_date: f.event_date, event_time: f.event_time, venue: f.venue, registration_link: f.registration_link }
    try {
      await api(editing ? `/events/${initial.id}` : '/events', { method: editing ? 'PUT' : 'POST', body })
      toast(editing ? 'Event updated' : 'Event created'); onDone()
    } catch (x) { setErr(x) } finally { setBusy(false) }
  }
  const lab = 'text-xs font-semibold uppercase tracking-wide text-slate-500'
  const inp = 'input mt-1 font-normal normal-case tracking-normal'
  return (
    <form onSubmit={save} className="card mb-10 grid gap-x-8 gap-y-4 sm:grid-cols-2">
      <h2 className="section-title sm:col-span-2">{editing ? 'Edit event' : 'Create an event'}</h2>
      <label className={`${lab} sm:col-span-2`}>Event name<input className={inp} required minLength={3} maxLength={150} value={f.name} onChange={set('name')} /></label>
      <label className={lab}>Date<input className={inp} type="date" required min={editing ? undefined : today} value={f.event_date} onChange={set('event_date')} /></label>
      <label className={lab}>Time<input className={inp} type="time" required value={f.event_time} onChange={set('event_time')} /></label>
      <label className={`${lab} sm:col-span-2`}>Venue<input className={inp} required minLength={2} maxLength={200} value={f.venue} onChange={set('venue')} placeholder="e.g. Main Auditorium, or an online meeting link" /></label>
      <label className={`${lab} sm:col-span-2`}>Description
        <textarea className={`${inp} min-h-[7rem]`} required minLength={10} maxLength={3000} value={f.description} onChange={set('description')} /></label>
      <label className={`${lab} sm:col-span-2`}>Registration link (optional)
        <input className={inp} maxLength={400} value={f.registration_link} onChange={set('registration_link')} placeholder="https://… for an external form, if you use one" /></label>
      <p className="text-xs text-slate-500 sm:col-span-2">Times are India time. People can also register here on the site, and you will see who did.</p>
      <div className="sm:col-span-2"><ErrorBox error={err} /></div>
      <div className="flex gap-3 sm:col-span-2"><button className="btn" disabled={busy}>{editing ? 'Save changes' : 'Create event'}</button><button type="button" className="btn-ghost" onClick={onCancel}>Cancel</button></div>
    </form>
  )
}

function Participants({ eid }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => { api(`/events/${eid}/registrations`).then(setData).catch(setErr) }, [eid])
  if (err) return <ErrorBox error={err} />
  if (!data) return <Spinner />
  if (data.count === 0) return <p className="mt-3 text-sm text-slate-500">Nobody has registered yet.</p>
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs uppercase tracking-wide text-slate-500"><tr><th className="py-1 pr-4">Name</th><th className="pr-4">Email</th><th className="pr-4">Role</th><th>Registered</th></tr></thead>
        <tbody>{data.items.map((p, i) => (
          <tr key={i} className="border-t border-sky-100"><td className="py-1.5 pr-4">{p.name}{p.graduation_year ? <span className="text-slate-400"> · batch {p.graduation_year}</span> : null}</td>
            <td className="pr-4">{p.email}</td><td className="pr-4 capitalize">{p.role.toLowerCase()}</td><td className="text-slate-500">{stamp(p.registered_at)}</td></tr>))}</tbody>
      </table>
    </div>
  )
}

function Card({ e, onEdit, onDelete, onChanged }) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const [showWho, setShowWho] = useState(false)
  const [more, setMore] = useState(false)
  const long = e.description.length > 280
  async function toggle() {
    setBusy(true)
    try {
      await api(`/events/${e.id}/register`, { method: e.registered ? 'DELETE' : 'POST' })
      toast(e.registered ? 'Registration cancelled' : 'You are registered'); onChanged()
    } catch (x) { toast(x.message, 'err') } finally { setBusy(false) }
  }
  return (
    <article className={`border-t border-sky-200 pt-4 ${e.is_past ? 'opacity-70' : ''}`}>
      <div className="flex flex-wrap items-center gap-2">
        {e.is_past ? <Badge tone="slate">Ended</Badge> : e.registered ? <Badge tone="green">You are registered</Badge> : <Badge tone="indigo">Open for registration</Badge>}
        {e.can_manage && <Badge tone="blue">{e.registration_count} registered</Badge>}
      </div>
      <h3 className="mt-2 text-lg font-semibold">{e.name}</h3>
      <p className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-slate-600">
        <span className="flex items-center gap-1.5"><CalendarDays className="h-4 w-4" />{dateLabel(e.event_date)}</span>
        <span className="flex items-center gap-1.5"><Clock className="h-4 w-4" />{timeLabel(e.event_time)}</span>
        <span className="flex items-center gap-1.5"><MapPin className="h-4 w-4" />{e.venue}</span></p>
      <p className={`mt-2 whitespace-pre-line text-sm text-slate-700 ${long && !more ? 'line-clamp-4' : ''}`}>{e.description}</p>
      {long && <button className="mt-1 text-xs text-indigo-700 underline" onClick={() => setMore(!more)}>{more ? 'Show less' : 'Show more'}</button>}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {!e.is_past && (e.registered
          ? <button className="btn-ghost" disabled={busy} onClick={toggle}><X className="h-4 w-4" />Cancel registration</button>
          : e.can_register && <button className="btn" disabled={busy} onClick={toggle}>Register</button>)}
        {e.registration_link && !e.is_past && e.registration_link.startsWith('https://') && <a className="btn-ghost" href={e.registration_link} target="_blank" rel="noopener noreferrer"><ExternalLink className="h-4 w-4" />Registration page</a>}
        {e.can_manage && <>
          <button className="btn-ghost" onClick={() => setShowWho(!showWho)}><Users className="h-4 w-4" />{showWho ? 'Hide participants' : 'Participants'}</button>
          <button className="btn-ghost" onClick={() => onEdit(e)}><Pencil className="h-4 w-4" />Edit</button>
          <button className="btn-ghost" onClick={() => onDelete(e)}><Trash2 className="h-4 w-4" />Delete</button></>}
      </div>
      {showWho && <Participants key={e.registration_count} eid={e.id} />}
    </article>
  )
}

export default function Events() {
  const toast = useToast()
  const canManage = can('event.manage')
  const [when, setWhen] = useState('upcoming')
  const [q, setQ] = useState('')
  const [term, setTerm] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [form, setForm] = useState(null)
  const [tick, setTick] = useState(0)
  useEffect(() => { const h = setTimeout(() => { setPage(1); setTerm(q.trim()) }, 300); return () => clearTimeout(h) }, [q])
  useEffect(() => {
    let live = true
    setErr(null)
    const p = new URLSearchParams({ when, search: term, page, page_size: SIZE })
    api(`/events?${p}`).then((r) => live && setData(r)).catch((x) => live && setErr(x))
    return () => { live = false }
  }, [when, term, page, tick])
  const reload = () => setTick((t) => t + 1)
  async function remove(e) {
    const n = e.registration_count
    if (!window.confirm(`Delete “${e.name}”?${n ? ` ${n} registration${n === 1 ? '' : 's'} will be removed too.` : ''} This cannot be undone.`)) return
    try { await api(`/events/${e.id}`, { method: 'DELETE' }); toast('Event deleted'); reload() } catch (x) { toast(x.message, 'err') }
  }
  const today = data?.now?.slice(0, 10)

  return (
    <>
      <PageHeader eyebrow="Community" title="Events" sub="Alumni meets, talks and college events. Register to let the organisers know you are coming.">
        {canManage && !form && <button className="btn" onClick={() => setForm({})}><Plus className="h-4 w-4" />Create an event</button>}
      </PageHeader>
      {form && <Form key={form.id || 'new'} initial={form} today={today} onDone={() => { setForm(null); reload() }} onCancel={() => setForm(null)} />}
      <div className="mb-4 flex flex-wrap gap-x-6 gap-y-2 border-b border-sky-100" role="tablist">
        {TABS.map(([k, label]) => <button key={k} role="tab" aria-selected={when === k} className={`tab ${when === k ? 'tab-on' : ''}`} onClick={() => { setWhen(k); setPage(1) }}>{label}</button>)}
      </div>
      <div className="relative mb-8 max-w-sm"><Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-slate-400" />
        <input className="input !pl-9" placeholder="Search events" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search events" /></div>
      <ErrorBox error={err} retry={reload} />
      {!data && !err && <Spinner />}
      {data && (data.items.length === 0
        ? <p className="py-10 text-slate-500">{term ? 'No events match your search.' : when === 'upcoming' ? 'No upcoming events right now. Check back soon.' : 'No past events.'}</p>
        : <>
          <div className="grid gap-x-12 gap-y-8 md:grid-cols-2">{data.items.map((e) => <Card key={e.id} e={e} onChanged={reload} onDelete={remove} onEdit={(x) => { setForm(x); window.scrollTo({ top: 0, behavior: 'smooth' }) }} />)}</div>
          <div className="mt-8 flex items-center justify-between text-sm text-slate-500"><span>{data.total} {data.total === 1 ? 'event' : 'events'}</span>
            <span className="space-x-2"><button className="btn-ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
              <button className="btn-ghost" disabled={page * SIZE >= data.total} onClick={() => setPage(page + 1)}>Next</button></span></div></>)}
    </>
  )
}
