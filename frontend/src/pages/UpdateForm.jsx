import React, { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Briefcase, GraduationCap, Loader2, Rocket } from 'lucide-react'
import { api } from '../api'
import { ErrorBox, Spinner } from '../ui.jsx'

const OPTIONS = [
  { v: 'EMPLOYMENT', label: 'Placement / Job', icon: Briefcase },
  { v: 'HIGHER_STUDIES', label: 'Higher studies', icon: GraduationCap },
  { v: 'ENTREPRENEURSHIP', label: 'Entrepreneurship', icon: Rocket },
]
const FIELDS = {
  EMPLOYMENT: [['company', 'Company name', true], ['designation', 'Designation', true], ['industry', 'Industry', true], ['notes', 'Anything else you would like to share (optional)', false, 'textarea']],
  HIGHER_STUDIES: [['university', 'University', true], ['country', 'Country', true], ['degree', 'Degree (e.g. MS, MBA)', true], ['specialization', 'Specialization', true]],
  ENTREPRENEURSHIP: [['startup_name', 'Startup name', true], ['business_domain', 'Business domain', true], ['stage', 'Current stage', true, 'select', ['Idea', 'Prototype / MVP', 'Early revenue', 'Growth']]],
}

export default function UpdateForm() {
  const [params] = useSearchParams()
  const token = params.get('token') || ''
  const nav = useNavigate()
  const [info, setInfo] = useState(null)
  const [err, setErr] = useState(null)
  const [kind, setKind] = useState('')
  const [d, setD] = useState({})
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api(`/public/form?token=${encodeURIComponent(token)}`, { auth: false }).then((r) => {
      setInfo(r)
      if (r.career_status) { setKind(r.career_status); setD(r.details || {}) }
      else if (r.prefill) {   // pre-fill from the placement / higher-studies / entrepreneurship record the department holds
        const { kind: k, source, ...rest } = r.prefill
        setKind(k); setD(Object.fromEntries(Object.entries(rest).filter(([, v]) => v)))
      }
    }).catch(setErr)
  }, [token])

  async function submit(e) {
    e.preventDefault(); setBusy(true); setErr(null)
    try { await api('/public/submit', { method: 'POST', auth: false, body: { token, career_status: kind, details: d } }); nav('/submission-success') }
    catch (x) { setErr(x); window.scrollTo(0, 0) } finally { setBusy(false) }
  }

  if (!info && !err) return <Spinner />
  if (!info) return <div className="mx-auto max-w-md p-10"><ErrorBox error={err} /><p className="mt-3 text-sm text-slate-500">Please use the exact link from your email, or contact the department.</p></div>
  return (
    <div className="min-h-screen">
      <section className="relative overflow-hidden bg-gradient-to-br from-blue-900 via-blue-800 to-indigo-800 text-white">
        <div className="pointer-events-none absolute -right-20 -top-20 h-80 w-80 rounded-full bg-indigo-300/25 blur-3xl" />
        <div className="relative mx-auto flex max-w-4xl flex-col items-center gap-4 px-6 pt-10 sm:flex-row sm:px-10">
          <div className="flex-1 pb-6 sm:pb-12">
            <span className="silver-chip !text-slate-800">Alumni update</span>
            <h1 className="mt-4 text-4xl font-semibold leading-tight sm:text-5xl">Hello, {info.name.split(' ')[0]}</h1>
            <p className="mt-3 text-sm text-slate-200">Batch of {info.graduation_year} · PRN {info.prn}</p>
          </div>
          <img src="/img/hero-campus.svg" alt="" className="w-full max-w-xs drop-shadow-2xl sm:w-[44%]" />
        </div>
        <div className="silver-bar" />
      </section>
      <div className="mx-auto max-w-xl px-6 py-12">
        {info.career_status && <p className="mb-6 border-l-4 border-emerald-400 py-1 pl-3 text-sm text-emerald-800">You have already submitted. You can review and update your answers below.</p>}
        {info.prefill && !info.career_status && <p className="mb-6 border-l-4 border-indigo-400 py-1 pl-3 text-sm text-indigo-800">We pre-filled some details from your {info.prefill.source} record. Please confirm or correct them.</p>}
        <form onSubmit={submit} className="space-y-8">
          <ErrorBox error={err} />
          <fieldset><legend className="section-title mb-5">What are you doing now?</legend>
            <div className="grid grid-cols-3 gap-4">
              {OPTIONS.map(({ v, label, icon: Icon }) => (
                <label key={v} className={`group flex cursor-pointer flex-col items-center gap-3 break-words pb-3 text-center text-xs font-medium transition sm:text-sm ${kind === v ? 'text-indigo-800' : 'text-slate-500 hover:text-slate-800'}`}>
                  <input type="radio" name="kind" value={v} className="sr-only" checked={kind === v} onChange={() => { setKind(v); if (kind !== v) setD({}) }} />
                  <span className={`flex h-16 w-16 items-center justify-center rounded-full transition ${kind === v ? 'bg-gradient-to-br from-indigo-300 to-indigo-500 text-white shadow-lg shadow-indigo-900/20' : 'silver-bg text-slate-600 group-hover:brightness-105'}`}><Icon className="h-7 w-7" /></span>
                  <span className={`border-b-2 pb-0.5 ${kind === v ? 'border-indigo-500' : 'border-transparent'}`}>{label}</span></label>))}
            </div></fieldset>
          {kind && FIELDS[kind].map(([k, label, req, type, opts]) => (
            <div key={k}><label className="label" htmlFor={k}>{label}{req && <span className="text-red-600"> *</span>}</label>
              {type === 'textarea' ? <textarea id={k} rows={3} maxLength={1000} className="input" value={d[k] || ''} onChange={(e) => setD({ ...d, [k]: e.target.value })} />
                : type === 'select' ? <select id={k} required className="input" value={d[k] || ''} onChange={(e) => setD({ ...d, [k]: e.target.value })}><option value="">Select…</option>{opts.map((o) => <option key={o}>{o}</option>)}</select>
                : <input id={k} required={req} maxLength={200} className="input" value={d[k] || ''} onChange={(e) => setD({ ...d, [k]: e.target.value })} />}</div>))}
          <button className="btn-primary w-full py-3.5 text-base" disabled={!kind || busy}>{busy && <Loader2 className="h-4 w-4 animate-spin" />}Submit</button>
        </form>
      </div>
    </div>
  )
}
