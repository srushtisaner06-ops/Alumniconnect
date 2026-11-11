import React, { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Briefcase, CheckCircle2, Clock, GraduationCap, Loader2, Rocket, ShieldAlert } from 'lucide-react'
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
  // Verification section: proof of the situation + income range (both only ever seen by department staff)
  const [income, setIncome] = useState('')
  const [proofType, setProofType] = useState('')
  const [file, setFile] = useState(null)
  const [consent, setConsent] = useState(false)

  useEffect(() => {
    api(`/public/form?token=${encodeURIComponent(token)}`, { auth: false }).then((r) => {
      setInfo(r)
      if (r.income_band) setIncome(r.income_band)
      if (r.career_status) { setKind(r.career_status); setD(r.details || {}) }
      else if (r.prefill) {   // pre-fill from the placement / higher-studies / entrepreneurship record the department holds
        const { kind: k, source, ...rest } = r.prefill
        setKind(k); setD(Object.fromEntries(Object.entries(rest).filter(([, v]) => v)))
      }
    }).catch(setErr)
  }, [token])

  async function submit(e) {
    e.preventDefault(); setBusy(true); setErr(null)
    try {
      if (file) {   // the proof goes first, as its own request; the details below are unchanged
        const f = new FormData()
        f.append('token', token); f.append('career_status', kind); f.append('doc_type', proofType); f.append('file', file)
        const up = await api('/public/proof', { method: 'POST', auth: false, form: f })
        setInfo((i) => ({ ...i, proof: up.proof })); setFile(null)
      }
      await api('/public/submit', { method: 'POST', auth: false, body: { token, career_status: kind, details: d, income_band: bandOk ? income : null, consent } })
      nav('/submission-success')
    }
    catch (x) { setErr(x); window.scrollTo(0, 0) } finally { setBusy(false) }
  }

  const bands = kind && info?.income_bands?.[kind]
  const bandOk = !!bands && bands.options.some((o) => o.code === income)      // a band chosen for another option is not sent
  const proof = info?.proof
  const hasProof = !!proof && proof.category === kind && proof.status !== 'REJECTED'
  const needFile = !!info?.requirements?.proof && !hasProof
  const tooBig = !!file && file.size > (info?.max_upload_mb || 5) * 1024 * 1024
  const pickFile = (f) => { setFile(f || null) }

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
                  <input type="radio" name="kind" value={v} className="sr-only" checked={kind === v} onChange={() => { setKind(v); if (kind !== v) { setD({}); setIncome(''); setProofType(''); setFile(null) } }} />
                  <span className={`flex h-16 w-16 items-center justify-center rounded-full transition ${kind === v ? 'bg-gradient-to-br from-indigo-300 to-indigo-500 text-white shadow-lg shadow-indigo-900/20' : 'silver-bg text-slate-600 group-hover:brightness-105'}`}><Icon className="h-7 w-7" /></span>
                  <span className={`border-b-2 pb-0.5 ${kind === v ? 'border-indigo-500' : 'border-transparent'}`}>{label}</span></label>))}
            </div></fieldset>
          {kind && FIELDS[kind].map(([k, label, req, type, opts]) => (
            <div key={k}><label className="label" htmlFor={k}>{label}{req && <span className="text-red-600"> *</span>}</label>
              {type === 'textarea' ? <textarea id={k} rows={3} maxLength={1000} className="input" value={d[k] || ''} onChange={(e) => setD({ ...d, [k]: e.target.value })} />
                : type === 'select' ? <select id={k} required className="input" value={d[k] || ''} onChange={(e) => setD({ ...d, [k]: e.target.value })}><option value="">Select…</option>{opts.map((o) => <option key={o}>{o}</option>)}</select>
                : <input id={k} required={req} maxLength={200} className="input" value={d[k] || ''} onChange={(e) => setD({ ...d, [k]: e.target.value })} />}</div>))}
          {kind && (
            <fieldset className="space-y-5 border-t border-sky-200 pt-8">
              <legend className="section-title mb-1">Verification</legend>
              <p className="text-sm leading-6 text-slate-500">Only the department staff can see this. It confirms your details and is used for summary statistics. It is never shown to other alumni or students.</p>
              <div><label className="label" htmlFor="income">{bands.question}{info.requirements.income && <span className="text-red-600"> *</span>}</label>
                <select id="income" required={info.requirements.income} className="input" value={bandOk ? income : ''} onChange={(e) => setIncome(e.target.value)}>
                  <option value="">Select a range…</option>{bands.options.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}</select></div>
              {proof && proof.category === kind && (
                <p className={`flex items-start gap-2 border-l-4 py-1 pl-3 text-sm ${proof.status === 'APPROVED' ? 'border-emerald-400 text-emerald-800' : proof.status === 'REJECTED' ? 'border-red-400 text-red-800' : 'border-amber-400 text-amber-800'}`}>
                  {proof.status === 'APPROVED' ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : proof.status === 'REJECTED' ? <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" /> : <Clock className="mt-0.5 h-4 w-4 shrink-0" />}
                  <span><b>{proof.doc_label}</b> ({proof.original_name}):{' '}
                    {proof.status === 'APPROVED' ? 'verified.' : proof.status === 'REJECTED' ? `not accepted. ${proof.rejection_reason} Please upload a new one.` : 'received, waiting for review. You can upload a different file to replace it.'}</span></p>)}
              <div><label className="label" htmlFor="ptype">Type of proof{needFile && <span className="text-red-600"> *</span>}</label>
                <select id="ptype" required={!!file || needFile} className="input" value={proofType} onChange={(e) => setProofType(e.target.value)}>
                  <option value="">Select…</option>{info.proof_types[kind].map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}</select></div>
              <div><label className="label" htmlFor="pfile">{hasProof ? 'Replace the file (optional)' : 'Upload the proof'}{needFile && <span className="text-red-600"> *</span>}</label>
                <input id="pfile" type="file" required={needFile} accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg" className="input" onChange={(e) => pickFile(e.target.files[0])} />
                <p className={`mt-1 text-xs ${tooBig ? 'text-red-700' : 'text-slate-500'}`}>{tooBig ? `This file is larger than ${info.max_upload_mb} MB.` : `PDF, PNG or JPG, up to ${info.max_upload_mb} MB. Hide any ID, account or Aadhaar number that is not needed.`}</p></div>
              <label className="flex items-start gap-3 text-sm text-slate-700">
                <input type="checkbox" required={info.requirements.proof || info.requirements.income} className="mt-1 h-4 w-4" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
                <span>I agree that the college may store this proof and my income range to verify my details and prepare statistics, and I can ask for them to be deleted.</span></label>
            </fieldset>)}
          <button className="btn-primary w-full py-3.5 text-base" disabled={!kind || busy || tooBig}>{busy && <Loader2 className="h-4 w-4 animate-spin" />}Submit</button>
        </form>
      </div>
    </div>
  )
}
