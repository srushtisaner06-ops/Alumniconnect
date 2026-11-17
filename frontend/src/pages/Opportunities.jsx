import React, { useEffect, useState } from 'react'
import { Briefcase, ExternalLink, Mail, Pencil, Plus, Search, Trash2, X } from 'lucide-react'
import { api, can } from '../api'
import { Badge, ErrorBox, PageHeader, Spinner, useToast } from '../ui.jsx'

const CATS = [['all', 'All'], ['JOB', 'Jobs'], ['INTERNSHIP', 'Internships'], ['REFERRAL', 'Referrals']]
const TONE = { JOB: 'indigo', INTERNSHIP: 'green', REFERRAL: 'amber' }
const SIZE = 20
const blank = { category: 'JOB', title: '', company: '', description: '', apply_contact: '', closing_date: '' }
const day = (d) => new Date(d + 'T00:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })

function Form({ initial, today, onDone, onCancel }) {
  const toast = useToast()
  const editing = !!initial.id
  const [f, setF] = useState({ ...blank, ...initial })
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  async function save(e) {
    e.preventDefault(); setErr(null); setBusy(true)
    const body = { category: f.category, title: f.title, company: f.company, description: f.description, apply_contact: f.apply_contact, closing_date: f.closing_date }
    try {
      await api(editing ? `/opportunities/${initial.id}` : '/opportunities', { method: editing ? 'PUT' : 'POST', body })
      toast(editing ? 'Opportunity updated' : 'Opportunity posted'); onDone()
    } catch (x) { setErr(x) } finally { setBusy(false) }
  }
  const lab = 'text-xs font-semibold uppercase tracking-wide text-slate-500'
  const inp = 'input mt-1 font-normal normal-case tracking-normal'
  return (
    <form onSubmit={save} className="card mb-10 grid gap-x-8 gap-y-4 sm:grid-cols-2">
      <h2 className="section-title sm:col-span-2">{editing ? 'Edit opportunity' : 'Post an opportunity'}</h2>
      <label className={lab}>Category
        <select className={inp} value={f.category} onChange={set('category')}><option value="JOB">Job</option><option value="INTERNSHIP">Internship</option><option value="REFERRAL">Referral</option></select></label>
      <label className={lab}>Closing date
        <input className={inp} type="date" required min={editing ? undefined : today} value={f.closing_date} onChange={set('closing_date')} /></label>
      <label className={lab}>Title<input className={inp} required minLength={3} maxLength={120} value={f.title} onChange={set('title')} placeholder="e.g. Backend Engineer" /></label>
      <label className={lab}>Company<input className={inp} required minLength={2} maxLength={120} value={f.company} onChange={set('company')} /></label>
      <label className={`${lab} sm:col-span-2`}>Description
        <textarea className={`${inp} min-h-[7rem]`} required minLength={10} maxLength={2000} value={f.description} onChange={set('description')} placeholder="Role, requirements, location, how referrals work…" /></label>
      <label className={`${lab} sm:col-span-2`}>How to apply (https link or email)
        <input className={inp} required maxLength={120} value={f.apply_contact} onChange={set('apply_contact')} placeholder="https://company.com/careers/123  or  hr@company.com" /></label>
      <p className="text-xs text-slate-500 sm:col-span-2">Everything here, including the email address if you use one, is visible to all signed-in students and alumni.</p>
      <div className="sm:col-span-2"><ErrorBox error={err} /></div>
      <div className="flex gap-3 sm:col-span-2"><button className="btn" disabled={busy}>{editing ? 'Save changes' : 'Post'}</button><button type="button" className="btn-ghost" onClick={onCancel}>Cancel</button></div>
    </form>
  )
}

function Card({ o, onEdit, onDelete }) {
  const [more, setMore] = useState(false)
  const long = o.description.length > 280
  const href = o.apply_kind === 'email' ? `mailto:${o.apply_contact}` : (o.apply_contact.startsWith('https://') ? o.apply_contact : null)
  return (
    <article className={`border-t border-sky-200 pt-4 ${o.is_closed ? 'opacity-60' : ''}`}>
      <div className="flex flex-wrap items-center gap-2"><Badge tone={TONE[o.category]}>{o.category_label}</Badge>{o.is_closed && <Badge tone="slate">Closed</Badge>}
        <span className="ml-auto text-xs text-slate-500">{o.is_closed ? 'Closed' : 'Closes'} {day(o.closing_date)}</span></div>
      <h3 className="mt-2 text-lg font-semibold">{o.title}</h3>
      <p className="flex items-center gap-1.5 text-sm text-slate-600"><Briefcase className="h-3.5 w-3.5" />{o.company}</p>
      <p className={`mt-2 whitespace-pre-line text-sm text-slate-700 ${long && !more ? 'line-clamp-4' : ''}`}>{o.description}</p>
      {long && <button className="mt-1 text-xs text-indigo-700 underline" onClick={() => setMore(!more)}>{more ? 'Show less' : 'Show more'}</button>}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {href && !o.is_closed && <a className="btn-ghost" href={href} {...(o.apply_kind === 'link' ? { target: '_blank', rel: 'noopener noreferrer' } : {})}>
          {o.apply_kind === 'email' ? <><Mail className="h-4 w-4" />Email {o.apply_contact}</> : <><ExternalLink className="h-4 w-4" />Apply</>}</a>}
        {o.can_edit && <><button className="btn-ghost" onClick={() => onEdit(o)}><Pencil className="h-4 w-4" />Edit</button><button className="btn-ghost" onClick={() => onDelete(o)}><Trash2 className="h-4 w-4" />Delete</button></>}
        <span className="ml-auto text-xs text-slate-500">Posted by {o.posted_by.name}{o.posted_by.graduation_year ? ` · batch of ${o.posted_by.graduation_year}` : ''}</span>
      </div>
    </article>
  )
}

export default function Opportunities() {
  const toast = useToast()
  const canPost = can('opportunity.post')
  const [cat, setCat] = useState('all')
  const [q, setQ] = useState('')
  const [term, setTerm] = useState('')
  const [showClosed, setShowClosed] = useState(false)
  const [mine, setMine] = useState(false)
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [form, setForm] = useState(null)          // null = hidden, {} = new post, {id, ...} = editing
  const [tick, setTick] = useState(0)
  useEffect(() => { const h = setTimeout(() => { setPage(1); setTerm(q.trim()) }, 300); return () => clearTimeout(h) }, [q])
  useEffect(() => {
    let live = true
    setErr(null)
    const p = new URLSearchParams({ category: cat, status: showClosed ? 'all' : 'open', search: term, page, page_size: SIZE })
    if (mine) p.set('mine', 'true')
    api(`/opportunities?${p}`).then((r) => live && setData(r)).catch((e) => live && setErr(e))
    return () => { live = false }
  }, [cat, term, showClosed, mine, page, tick])
  const reload = () => setTick((t) => t + 1)

  async function remove(o) {
    if (!window.confirm(`Delete “${o.title}”? This cannot be undone.`)) return
    try { await api(`/opportunities/${o.id}`, { method: 'DELETE' }); toast('Opportunity deleted'); reload() } catch (e) { toast(e.message, 'err') }
  }
  const done = () => { setForm(null); reload() }

  return (
    <>
      <PageHeader eyebrow="Careers" title="Opportunities" sub="Jobs, internships and referrals shared by alumni for students and other alumni.">
        {canPost && !form && <button className="btn" onClick={() => setForm({})}><Plus className="h-4 w-4" />Post an opportunity</button>}
      </PageHeader>
      {form && <Form key={form.id || 'new'} initial={form} today={data?.today} onDone={done} onCancel={() => setForm(null)} />}
      <div className="mb-4 flex flex-wrap gap-x-6 gap-y-2 border-b border-sky-100" role="tablist">
        {CATS.map(([k, label]) => <button key={k} role="tab" aria-selected={cat === k} className={`tab ${cat === k ? 'tab-on' : ''}`} onClick={() => { setCat(k); setPage(1) }}>{label}</button>)}
      </div>
      <div className="mb-8 flex flex-wrap items-center gap-x-8 gap-y-3">
        <div className="relative w-full max-w-sm"><Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-slate-400" />
          <input className="input !pl-9" placeholder="Search title, company or details" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search opportunities" /></div>
        <label className="flex items-center gap-2 text-sm text-slate-600"><input type="checkbox" checked={showClosed} onChange={(e) => { setShowClosed(e.target.checked); setPage(1) }} />Show closed</label>
        {canPost && <label className="flex items-center gap-2 text-sm text-slate-600"><input type="checkbox" checked={mine} onChange={(e) => { setMine(e.target.checked); setPage(1) }} />My posts only</label>}
        {(q || mine || showClosed || cat !== 'all') && <button className="btn-ghost" onClick={() => { setQ(''); setTerm(''); setMine(false); setShowClosed(false); setCat('all'); setPage(1) }}><X className="h-4 w-4" />Clear</button>}
      </div>
      <ErrorBox error={err} retry={reload} />
      {!data && !err && <Spinner />}
      {data && (data.items.length === 0
        ? <p className="py-10 text-slate-500">{term || mine || cat !== 'all' ? 'Nothing matches those filters.' : canPost ? 'No open opportunities yet. Be the first to post one.' : 'No open opportunities right now. Check back soon.'}</p>
        : <>
          <div className="grid gap-x-12 gap-y-8 md:grid-cols-2">{data.items.map((o) => <Card key={o.id} o={o} onEdit={(x) => { setForm(x); window.scrollTo({ top: 0, behavior: 'smooth' }) }} onDelete={remove} />)}</div>
          <div className="mt-8 flex items-center justify-between text-sm text-slate-500"><span>{data.total} {data.total === 1 ? 'opportunity' : 'opportunities'}</span>
            <span className="space-x-2"><button className="btn-ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
              <button className="btn-ghost" disabled={page * SIZE >= data.total} onClick={() => setPage(page + 1)}>Next</button></span></div></>)}
    </>
  )
}
