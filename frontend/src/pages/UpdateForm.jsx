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
  if (!info) return <div className="mx-auto max-w-md p-6"><ErrorBox error={err} /><p className="mt-3 text-sm text-slate-500">Please use the exact link from your email, or contact the department.</p></div>
  return (
    <div className="mx-auto max-w-xl p-4 sm:p-8">
      <div className="card p-5 sm:p-7">
        <h1 className="text-xl font-semibold">Hello, {info.name.split(' ')[0]}</h1>
        <p className="mt-1 text-sm text-slate-500">Batch of {info.graduation_year} · PRN {info.prn}</p>
        {info.status === 'COMPLETED' && <p className="mt-4 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">You have already submitted. You can review and update your answers below.</p>}
        {info.prefill && info.status !== 'COMPLETED' && <p className="mt-4 rounded-lg bg-indigo-50 p-3 text-sm text-indigo-800">We pre-filled some details from your {info.prefill.source} record. Please confirm or correct them.</p>}
        <form onSubmit={submit} className="mt-5 space-y-5">
          <ErrorBox error={err} />
          <fieldset><legend className="label">What are you doing now?</legend>
            <div className="grid grid-cols-3 gap-2">
              {OPTIONS.map(({ v, label, icon: Icon }) => (
                <label key={v} className={`flex cursor-pointer flex-col items-center gap-1 break-words rounded-lg border p-2 text-center text-xs font-medium sm:p-3 sm:text-sm ${kind === v ? 'border-indigo-600 bg-indigo-50 text-indigo-700 ring-2 ring-indigo-200' : 'border-slate-300 hover:bg-slate-50'}`}>
                  <input type="radio" name="kind" value={v} className="sr-only" checked={kind === v} onChange={() => { setKind(v); if (kind !== v) setD({}) }} /><Icon className="h-5 w-5" />{label}</label>))}
            </div></fieldset>
          {kind && FIELDS[kind].map(([k, label, req, type, opts]) => (
            <div key={k}><label className="label" htmlFor={k}>{label}{req && <span className="text-red-600"> *</span>}</label>
              {type === 'textarea' ? <textarea id={k} rows={3} maxLength={1000} className="input" value={d[k] || ''} onChange={(e) => setD({ ...d, [k]: e.target.value })} />
                : type === 'select' ? <select id={k} required className="input" value={d[k] || ''} onChange={(e) => setD({ ...d, [k]: e.target.value })}><option value="">Select…</option>{opts.map((o) => <option key={o}>{o}</option>)}</select>
                : <input id={k} required={req} maxLength={200} className="input" value={d[k] || ''} onChange={(e) => setD({ ...d, [k]: e.target.value })} />}</div>))}
          <button className="btn-primary w-full py-2.5" disabled={!kind || busy}>{busy && <Loader2 className="h-4 w-4 animate-spin" />}Submit</button>
        </form>
      </div>
    </div>
  )
}
