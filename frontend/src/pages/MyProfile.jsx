import React, { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { api, download } from '../api'
import { Badge, ErrorBox, PageHeader, Spinner, fmtDate, useLoad, useToast } from '../ui.jsx'

const LEVELS = [
  ['PRIVATE', 'Private', 'Only you and the department staff can see your profile.'],
  ['ALUMNI_ONLY', 'Alumni only', 'Other alumni can see your name, batch, organisations and the details below.'],
  ['INSTITUTION', 'Institution', 'Alumni and current students can see them.'],
  ['PUBLIC', 'Public', 'Anyone, signed in or not, can see them.'],
]
const EVENT_TYPES = [['ACHIEVEMENT', 'Achievement'], ['PROMOTION', 'Promotion'], ['JOB_CHANGE', 'Job change'], ['FIRST_JOB', 'First job'], ['HIGHER_STUDIES', 'Higher studies'], ['ENTREPRENEURSHIP', 'Entrepreneurship']]
const PROOF_TONE = { PENDING: 'amber', APPROVED: 'green', REJECTED: 'red' }
const tags = (s) => s.split(',').map((x) => x.trim()).filter(Boolean)
const BLANK = { whatsapp: '', headline: '', country: '', city: '', professional_domain: '', designation: '', years_experience: '', linkedin_url: '', github_url: '', portfolio_url: '', skills: '', interests: '' }

function About({ profile, onSaved }) {
  const toast = useToast()
  const [f, setF] = useState(BLANK)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!profile) return
    setF({ ...BLANK, ...Object.fromEntries(Object.entries(profile).filter(([k]) => k in BLANK && k !== 'skills' && k !== 'interests').map(([k, v]) => [k, v ?? ''])),
      skills: (profile.skills || []).join(', '), interests: (profile.interests || []).join(', ') })
  }, [profile])
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  async function save(e) {
    e.preventDefault(); setBusy(true); setErr(null)
    try {
      await api('/profile/me/details', { method: 'PUT', body: { ...f, years_experience: f.years_experience === '' ? null : Number(f.years_experience), skills: tags(f.skills), interests: tags(f.interests) } })
      toast('Profile saved'); onSaved()
    } catch (x) { setErr(x) } finally { setBusy(false) }
  }
  const field = (k, label, props = {}) => <div><label className="label" htmlFor={k}>{label}</label><input id={k} className="input" value={f[k]} onChange={set(k)} {...props} /></div>
  return (
    <form onSubmit={save} className="grid gap-5 sm:grid-cols-2">
      <div className="sm:col-span-2"><ErrorBox error={err} /></div>
      <div className="sm:col-span-2">{field('headline', 'Headline', { placeholder: 'e.g. Data engineer building payment systems', maxLength: 160 })}</div>
      {field('designation', 'Designation')}{field('professional_domain', 'Field / domain', { placeholder: 'e.g. Data, Cloud, Finance' })}
      {field('city', 'City')}{field('country', 'Country')}
      {field('years_experience', 'Years of experience', { type: 'number', min: 0, max: 60, step: 0.5 })}
      <div><label className="label" htmlFor="whatsapp">WhatsApp number <span className="font-normal text-slate-500">(only you and staff see this)</span></label><input id="whatsapp" className="input" value={f.whatsapp} onChange={set('whatsapp')} placeholder="+91 98765 43210" /></div>
      {field('linkedin_url', 'LinkedIn', { placeholder: 'linkedin.com/in/…' })}{field('github_url', 'GitHub', { placeholder: 'github.com/…' })}
      <div className="sm:col-span-2">{field('portfolio_url', 'Portfolio or website', { placeholder: 'https://…' })}</div>
      <div className="sm:col-span-2">{field('skills', 'Skills', { placeholder: 'Python, SQL, Spark' })}<p className="mt-1 text-xs text-slate-500">Separate with commas. Up to 30.</p></div>
      <div className="sm:col-span-2">{field('interests', 'Interests', { placeholder: 'Open source, Hiking' })}</div>
      <div className="sm:col-span-2"><button className="btn-primary" disabled={busy}>{busy && <Loader2 className="h-4 w-4 animate-spin" />}Save details</button></div>
    </form>
  )
}

function Timeline({ events, onChanged }) {
  const toast = useToast()
  const [f, setF] = useState({ event_type: 'ACHIEVEMENT', title: '', event_date: '', organisation: '', detail: '' })
  const [err, setErr] = useState(null)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  async function add(e) {
    e.preventDefault(); setErr(null)
    try { await api('/profile/me/career-events', { method: 'POST', body: f }); toast('Added to your timeline'); setF({ ...f, title: '', event_date: '', organisation: '', detail: '' }); onChanged() } catch (x) { setErr(x) }
  }
  async function retract(ev) {
    const reason = window.prompt('Why are you removing this? (It stays on record, struck through, so your history is never rewritten.)')
    if (!reason) return
    try { await api(`/profile/me/career-events/${ev.id}/retract`, { method: 'POST', body: { reason } }); toast('Removed'); onChanged() } catch (x) { toast(x.message, 'err') }
  }
  return (
    <>
      <ol className="mb-8 space-y-4 border-l-2 border-sky-200 pl-5">{events.map((ev) => (
        <li key={ev.id} className={ev.retracted ? 'opacity-50' : ''}>
          <div className={`flex flex-wrap items-baseline gap-x-3 ${ev.retracted ? 'line-through' : ''}`}><span className="font-medium">{ev.title}</span>
            <Badge tone="slate">{ev.type_label}</Badge><span className="text-xs text-slate-500">{ev.event_date || 'date not given'}</span></div>
          {ev.organisation && <div className="text-sm text-slate-600">{ev.organisation}</div>}
          {ev.detail && <div className="text-sm text-slate-500">{ev.detail}</div>}
          {ev.retracted ? <div className="text-xs text-slate-500">Removed: {ev.retract_reason}</div>
            : ev.event_type !== 'GRADUATION' && <button className="mt-0.5 text-xs text-slate-500 underline" onClick={() => retract(ev)}>Remove</button>}
        </li>))}</ol>
      <form onSubmit={add} className="grid gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2 text-sm font-medium">Add to your timeline</div>
        <div className="sm:col-span-2"><ErrorBox error={err} /></div>
        <div><label className="label" htmlFor="et">What happened</label><select id="et" className="input" value={f.event_type} onChange={set('event_type')}>{EVENT_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></div>
        <div><label className="label" htmlFor="ed">When <span className="font-normal text-slate-500">(2025, 2025-03 or 2025-03-15)</span></label><input id="ed" className="input" value={f.event_date} onChange={set('event_date')} /></div>
        <div className="sm:col-span-2"><label className="label" htmlFor="tt">Title</label><input id="tt" required maxLength={150} className="input" value={f.title} onChange={set('title')} placeholder="e.g. Promoted to Senior Engineer" /></div>
        <div><label className="label" htmlFor="eo">Organisation</label><input id="eo" className="input" value={f.organisation} onChange={set('organisation')} /></div>
        <div><label className="label" htmlFor="edt">Details</label><input id="edt" className="input" value={f.detail} onChange={set('detail')} /></div>
        <div className="sm:col-span-2"><button className="btn-primary">Add</button></div>
      </form>
    </>
  )
}

export default function MyProfile() {
  const toast = useToast()
  const me = useLoad(() => api('/profile/me'))
  const vis = useLoad(() => api('/profile/me/visibility'))
  const docs = useLoad(() => api('/profile/me/documents'))
  async function choose(level) {
    try { await api('/profile/me/visibility', { method: 'PUT', body: { level } }); toast('Privacy updated'); vis.reload() } catch (e) { toast(e.message, 'err') }
  }
  if (me.error) return <><PageHeader eyebrow="My profile" title="Your profile" /><ErrorBox error={me.error.status === 404 ? 'Your login is not linked to an alumni record yet. Please ask the department to link it.' : me.error} /></>
  if (!me.data) return <Spinner />
  const a = me.data
  return (
    <>
      <PageHeader eyebrow={`Batch of ${a.graduation_year}`} title={a.name} sub="Keep your details current and choose who can see them. Your contact details and income are never shown to other members." />

      <section className="mb-14">
        <h2 className="mb-4 text-xl font-semibold">Who can see my profile</h2>
        {vis.data && <div className="grid gap-4 sm:grid-cols-2">{LEVELS.map(([v, label, text]) => (
          <button key={v} onClick={() => choose(v)} className={`border-l-4 px-4 py-3 text-left transition ${vis.data.level === v ? 'border-indigo-600 bg-indigo-50' : 'border-slate-200 hover:border-sky-300'}`}>
            <div className="font-medium">{label}{vis.data.level === v && ' · current'}</div><div className="text-sm text-slate-500">{text}</div></button>))}</div>}
      </section>

      <section className="mb-14"><h2 className="mb-4 text-xl font-semibold">About you</h2><About profile={a.profile} onSaved={me.reload} /></section>
      <section className="mb-14"><h2 className="mb-4 text-xl font-semibold">Career timeline</h2><Timeline events={a.career_events || []} onChanged={me.reload} /></section>

      <section className="mb-10">
        <h2 className="mb-2 text-xl font-semibold">Your verification proof</h2>
        <p className="mb-4 max-w-2xl text-sm text-slate-600">Proof is uploaded from your personal link (the one in the department's email). Only staff reviewing it, and you, can open it.</p>
        {docs.data && (docs.data.items.length === 0 ? <p className="text-sm text-slate-500">No proof on file yet.</p> : (
          <ul className="space-y-3">{docs.data.items.filter((d) => !d.superseded).map((d) => (
            <li key={d.id} className="text-sm"><span className="font-medium">{d.doc_label}</span> <Badge tone={PROOF_TONE[d.status]}>{d.status.toLowerCase()}</Badge>
              <span className="text-slate-500"> · {d.original_name} · {fmtDate(d.uploaded_at)}</span>
              {d.rejection_reason && <div className="text-red-700">Not accepted: {d.rejection_reason}</div>}
              <button className="ml-3 underline" onClick={() => download(`/documents/${d.id}/download`, d.original_name).catch((e) => toast(e.message, 'err'))}>Open</button></li>))}</ul>))}
      </section>
    </>
  )
}
