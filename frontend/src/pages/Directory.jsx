import React, { useEffect, useState } from 'react'
import { Briefcase, GraduationCap, MapPin, Rocket, Search, UserPlus, X } from 'lucide-react'
import { api, can, role } from '../api'
import { Badge, ErrorBox, PageHeader, Spinner, useToast } from '../ui.jsx'
import { connectionsChanged } from './Connections.jsx'

const CAREER = { EMPLOYMENT: ['Working', Briefcase], HIGHER_STUDIES: ['Higher studies', GraduationCap], ENTREPRENEURSHIP: ['Entrepreneur', Rocket] }
const CAREER_FILTER = [['', 'Any career status'], ['PLACEMENT', 'Placement'], ['HIGHER_STUDIES', 'Higher studies'], ['ENTREPRENEURSHIP', 'Entrepreneurship']]
const SORTS = [['name', 'Name (A–Z)'], ['name_desc', 'Name (Z–A)'], ['year_desc', 'Newest batch first'], ['year', 'Oldest batch first']]
const SIZE = 24
const EMPTY = { batch: '', career: '', domain: '', sort: 'name' }

// Connect / request state for one card. `rel` is that person's entry from /connections (or undefined).
function ConnectBar({ p, rel, me, onChanged }) {
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  if (p.id === me) return null
  const run = async (fn, msg) => { setBusy(true); try { await fn(); toast(msg); setOpen(false); setNote(''); connectionsChanged(); onChanged() } catch (e) { toast(e.message, 'err') } finally { setBusy(false) } }
  const post = (path) => api(path, { method: 'POST' })
  if (rel?.status === 'ACCEPTED') return <Badge tone="green">Connected</Badge>
  if (rel?.direction === 'sent' && rel.status === 'PENDING') return <span className="flex items-center gap-3 text-sm"><Badge tone="amber">Request sent</Badge>
    <button className="text-slate-500 underline" disabled={busy} onClick={() => run(() => api(`/connections/${rel.id}`, { method: 'DELETE' }), 'Request withdrawn')}>Withdraw</button></span>
  if (rel?.direction === 'sent' && rel.status === 'REJECTED') return <Badge tone="slate">Request declined</Badge>
  if (rel?.direction === 'received') return <span className="flex flex-wrap items-center gap-2 text-sm"><span className="text-slate-600">Wants to connect</span>
    <button className="btn-ghost" disabled={busy} onClick={() => run(() => post(`/connections/${rel.id}/accept`), 'Connected')}>Accept</button>
    <button className="btn-ghost" disabled={busy} onClick={() => run(() => post(`/connections/${rel.id}/reject`), 'Request declined')}>Reject</button></span>
  if (!open) return <button className="btn-ghost" onClick={() => setOpen(true)}><UserPlus className="h-4 w-4" />Connect</button>
  return (
    <div className="w-full space-y-2">
      <input className="input" maxLength={300} placeholder="Add a short note (optional)" value={note} onChange={(e) => setNote(e.target.value)} aria-label="Note to send with your request" />
      <div className="flex gap-2"><button className="btn-ghost" disabled={busy} onClick={() => run(() => api('/connections', { method: 'POST', body: { recipient_id: p.id, message: note } }), 'Request sent')}>Send request</button>
        <button className="btn-ghost" onClick={() => setOpen(false)}>Cancel</button></div>
    </div>
  )
}

function Card({ p, rel, me, onChanged, canConnect }) {
  const [label, Icon] = CAREER[p.career_status] || []
  const place = [p.profile.city, p.profile.country].filter(Boolean).join(', ')
  const links = [['LinkedIn', p.profile.linkedin_url], ['GitHub', p.profile.github_url], ['Portfolio', p.profile.portfolio_url]].filter(([, u]) => u)
  return (
    <article className="border-t border-sky-200 pt-4">
      <div className="flex items-start justify-between gap-3"><h3 className="text-lg font-semibold">{p.name}</h3><span className="shrink-0 text-xs text-slate-500">Batch of {p.graduation_year}</span></div>
      {p.profile.headline && <p className="mt-0.5 text-sm text-slate-600">{p.profile.headline}</p>}
      <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-slate-600">
        {label && <span className="flex items-center gap-1.5"><Icon className="h-4 w-4 text-indigo-600" />{label}</span>}
        {p.organisations.length > 0 && <span>{p.organisations.slice(0, 2).join(' · ')}</span>}
        {p.profile.designation && <span>{p.profile.designation}</span>}
        {p.profile.professional_domain && <span className="text-slate-500">{p.profile.professional_domain}</span>}
        {place && <span className="flex items-center gap-1"><MapPin className="h-3.5 w-3.5" />{place}</span>}
      </p>
      {p.profile.skills.length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">{p.profile.skills.slice(0, 8).map((s) => <Badge key={s} tone="blue">{s}</Badge>)}</div>}
      {links.length > 0 && <p className="mt-2 flex gap-4 text-sm">{links.map(([n, u]) => <a key={n} className="text-indigo-700 underline" href={u} target="_blank" rel="noopener noreferrer">{n}</a>)}</p>}
      {canConnect && <div className="mt-3 flex flex-wrap items-center gap-2"><ConnectBar p={p} rel={rel} me={me} onChanged={onChanged} /></div>}
    </article>
  )
}

export default function Directory() {
  const [q, setQ] = useState('')
  const [term, setTerm] = useState('')
  const [org, setOrg] = useState('')            // typed text; applied after a short pause, like the search box
  const [organisation, setOrganisation] = useState('')
  const [f, setF] = useState(EMPTY)
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [opts, setOpts] = useState({ batches: [], domains: [] })
  const [err, setErr] = useState(null)
  // Only alumni can connect (they alone have an alumni record). Students and staff just browse.
  const canConnect = can('connection.use') && role() === 'ALUMNI'
  const [rels, setRels] = useState({ me: null, map: {} })
  const loadRels = () => canConnect && api('/connections').then((r) => {
    const map = {}
    for (const k of ['received', 'sent', 'connections']) for (const x of r[k]) map[x.person.id] = { id: x.id, status: x.status, direction: x.direction }
    setRels({ me: r.me, map })
  }).catch(() => {})
  useEffect(() => { loadRels() }, [])    // eslint-disable-line
  useEffect(() => { const h = setTimeout(() => { setPage(1); setTerm(q.trim()) }, 300); return () => clearTimeout(h) }, [q])
  useEffect(() => { const h = setTimeout(() => { setPage(1); setOrganisation(org.trim()) }, 300); return () => clearTimeout(h) }, [org])
  useEffect(() => { api('/directory/filters').then(setOpts).catch(() => {}) }, [])
  useEffect(() => {
    let live = true
    setErr(null)
    const params = new URLSearchParams({ search: term, page, page_size: SIZE, sort: f.sort })
    if (f.batch) params.set('batch', f.batch)
    if (f.career) params.set('career', f.career)
    if (f.domain) params.set('domain', f.domain)
    if (organisation) params.set('organisation', organisation)
    api(`/directory?${params}`).then((r) => live && setData(r)).catch((e) => live && setErr(e))
    return () => { live = false }
  }, [term, page, f, organisation])

  const set = (k) => (e) => { setF({ ...f, [k]: e.target.value }); setPage(1) }
  const filtered = f.batch || f.career || f.domain || organisation || term
  const clearAll = () => { setQ(''); setTerm(''); setOrg(''); setOrganisation(''); setF({ ...EMPTY, sort: f.sort }); setPage(1) }

  return (
    <>
      <PageHeader eyebrow="Community" title="Alumni network" sub="Graduates who have chosen to share their profile with you. Search, then narrow by batch, career, company or field." />
      <div className="relative mb-6 max-w-xl"><Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-slate-400" />
        <input className="input !pl-9" placeholder="Try “Python”, “Pune” or a company name" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search the alumni network" /></div>
      <div className="mb-8 grid gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-5">
        <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Batch
          <select className="input mt-1 font-normal normal-case tracking-normal" value={f.batch} onChange={set('batch')}>
            <option value="">All batches</option>{opts.batches.map((y) => <option key={y} value={y}>{y}</option>)}</select></label>
        <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Career status
          <select className="input mt-1 font-normal normal-case tracking-normal" value={f.career} onChange={set('career')}>
            {CAREER_FILTER.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Company / institution
          <input className="input mt-1 font-normal normal-case tracking-normal" placeholder="e.g. Acme" value={org} onChange={(e) => setOrg(e.target.value)} /></label>
        <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Professional domain
          <select className="input mt-1 font-normal normal-case tracking-normal" value={f.domain} onChange={set('domain')} disabled={opts.domains.length === 0}>
            <option value="">{opts.domains.length ? 'All domains' : 'No domains shared yet'}</option>{opts.domains.map((d) => <option key={d} value={d}>{d}</option>)}</select></label>
        <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Sort by
          <select className="input mt-1 font-normal normal-case tracking-normal" value={f.sort} onChange={set('sort')}>
            {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
      </div>
      {filtered && <button className="btn-ghost mb-6" onClick={clearAll}><X className="h-4 w-4" />Clear search and filters</button>}
      <ErrorBox error={err} />
      {!data && !err && <Spinner />}
      {data && (data.items.length === 0
        ? <p className="py-10 text-slate-500">{filtered ? 'Nobody matches those filters.' : 'No one has shared their profile with you yet. Profiles appear here as alumni choose to share them.'}</p>
        : <>
          <div className="grid gap-x-12 gap-y-8 md:grid-cols-2">{data.items.map((p) => <Card key={p.id} p={p} rel={rels.map[p.id]} me={rels.me} onChanged={loadRels} canConnect={canConnect} />)}</div>
          <div className="mt-8 flex items-center justify-between text-sm text-slate-500"><span>{data.total} {data.total === 1 ? 'person' : 'people'}</span>
            <span className="space-x-2"><button className="btn-ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
              <button className="btn-ghost" disabled={page * SIZE >= data.total} onClick={() => setPage(page + 1)}>Next</button></span></div></>)}
    </>
  )
}
