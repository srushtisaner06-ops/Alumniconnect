import React from 'react'
import { AlertTriangle, Download } from 'lucide-react'
import { api, download } from '../api'
import { CAREER, ErrorBox, PageHeader, Progress, Spinner, useLoad, useToast } from '../ui.jsx'

function Bars({ rows, label, value, max, unit = '' }) {
  const m = max ?? Math.max(1, ...rows.map((r) => r[value]))
  return (
    <ul className="space-y-2">
      {rows.map((r) => (
        <li key={r[label]}><div className="mb-1 flex justify-between text-sm"><span className="truncate">{r[label]}</span><span className="tabular-nums text-slate-600">{r[value]}{r.suffix ?? unit}</span></div>
          <Progress value={(100 * r[value]) / m} /></li>))}
    </ul>
  )
}

export default function Reports() {
  const toast = useToast()
  const { data, error, loading, reload } = useLoad(() => api('/reports/analytics'))
  const dl = (scope, format) => download(`/reports/export?scope=${scope}&format=${format}`, `alumni_${scope}.${format}`).catch((e) => toast(e.message, 'err'))
  if (loading) return <Spinner />
  if (error) return <ErrorBox error={error} retry={reload} />
  const { summary: s, by_batch, career, placement: p, higher_studies: hs, entrepreneurship: ent, progression: pr } = data
  const careerRows = Object.entries(career).map(([k, v]) => ({ k: CAREER[k], v }))
  return (
    <>
      <PageHeader title="Reports" sub="Analytics and exports for NIRF / NBA documentation">
        <button className="btn-ghost" onClick={() => dl('submissions', 'xlsx')}><Download className="h-4 w-4" />Submissions (Excel)</button>
        <button className="btn-ghost" onClick={() => dl('submissions', 'csv')}><Download className="h-4 w-4" />Submissions (CSV)</button>
        <button className="btn-ghost" onClick={() => dl('placement', 'xlsx')}><Download className="h-4 w-4" />Placement 4.6.1 (Excel)</button>
        <button className="btn-ghost" onClick={() => dl('higher_studies', 'xlsx')}><Download className="h-4 w-4" />Higher studies 4.6.2 (Excel)</button>
        <button className="btn-ghost" onClick={() => dl('entrepreneurship', 'xlsx')}><Download className="h-4 w-4" />Entrepreneurship 4.6.3 (Excel)</button>
      </PageHeader>
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card p-5"><h2 className="mb-1 font-medium">Submission rate</h2>
          <p className="mb-3 text-3xl font-semibold">{s.completion_pct}%</p><Progress value={s.completion_pct} />
          <p className="mt-2 text-sm text-slate-500">{s.completed} completed · {s.pending} pending · {s.overdue} overdue</p></div>
        <div className="card p-5"><h2 className="mb-3 font-medium">Career status (from submissions)</h2>
          {s.completed === 0 ? <p className="text-sm text-slate-500">No submissions yet.</p> : <Bars rows={careerRows} label="k" value="v" />}</div>
        <div className="card p-5"><h2 className="mb-3 font-medium">Submissions by batch</h2>
          <Bars rows={by_batch.map((b) => ({ k: `Batch ${b.year}`, v: b.completed, suffix: ` of ${b.total}` }))} label="k" value="v" max={Math.max(1, ...by_batch.map((b) => b.total))} /></div>
        <div className="card p-5"><h2 className="mb-3 font-medium">Packages (highest offer per student)</h2>
          <Bars rows={p.package_bands} label="band" value="students" unit=" students" /></div>
      </div>
      <div className="card mt-4 p-5">
        <h2 className="mb-3 font-medium">Placement index (Summary of Tables 4.6.1 – 4.6.3)</h2>
        <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-3 lg:grid-cols-6">
          {[['X · placed', pr.placed], ['Y · higher studies', pr.higher_studies], ['Z · entrepreneurship', pr.entrepreneurship], ['X + Y + Z', pr.total],
            ['FS · final-year students', pr.final_year_students ?? '—'], ['Placement index', pr.index != null ? `${pr.index}%` : '—']].map(([l, v]) => <div key={l}><dt className="text-slate-500">{l}</dt><dd className="text-xl font-semibold">{v}</dd></div>)}
        </dl>
        <p className="mt-3 text-xs text-slate-500">Index = (X + Y + Z) ÷ FS × 100. A student who appears in more than one category is counted once. FS comes from the placement sheet's Summary tab{pr.final_year_students ? '' : ' (not imported yet)'}.</p>
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div className="card p-5"><h2 className="mb-1 font-medium">Higher studies</h2>
          <p className="mb-3 text-sm text-slate-500">{hs.students} student{hs.students === 1 ? '' : 's'}</p>
          {hs.students === 0 ? <p className="text-sm text-slate-500">No higher-studies sheet imported yet.</p> : (<>
            <h3 className="mb-1 text-sm font-medium">Colleges / universities</h3>
            <table className="mb-3 w-full text-left text-sm"><tbody className="divide-y divide-slate-100">{hs.top_institutions.map((i) => <tr key={i.institution}><td className="py-1.5">{i.institution}</td><td className="text-right tabular-nums text-slate-500">{i.students}</td></tr>)}</tbody></table>
            <h3 className="mb-1 text-sm font-medium">Degrees</h3>
            <table className="w-full text-left text-sm"><tbody className="divide-y divide-slate-100">{hs.degrees.map((d) => <tr key={d.degree}><td className="py-1.5">{d.degree}</td><td className="text-right tabular-nums text-slate-500">{d.students}</td></tr>)}</tbody></table></>)}
        </div>
        <div className="card p-5"><h2 className="mb-1 font-medium">Entrepreneurship</h2>
          <p className="mb-3 text-sm text-slate-500">{ent.students} student{ent.students === 1 ? '' : 's'} · {ent.ventures} venture{ent.ventures === 1 ? '' : 's'}</p>
          {ent.ventures === 0 ? <p className="text-sm text-slate-500">No entrepreneurship sheet imported yet.</p> : (
            <table className="w-full text-left text-sm"><tbody className="divide-y divide-slate-100">{ent.companies.map((v) => (
              <tr key={v.registration_no + v.company}><td className="py-1.5"><div>{v.company}</div><div className="text-xs text-slate-500">{v.founder}</div></td><td className="font-mono text-xs text-slate-500">{v.registration_no}</td></tr>))}</tbody></table>)}
        </div>
      </div>
      <div className="card mt-4 p-5">
        <h2 className="mb-3 font-medium">Placement summary (from the placement sheet)</h2>
        <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-3 lg:grid-cols-6">
          {[['Students placed', p.students_placed], ['Offers', p.offers], ['Average', `${p.avg_package} LPA`], ['Median', `${p.median_package} LPA`], ['Highest', `${p.highest_package} LPA`],
            ['Placed ÷ final year', p.placement_index != null ? `${p.placement_index}%` : '—']].map(([l, v]) => <div key={l}><dt className="text-slate-500">{l}</dt><dd className="text-xl font-semibold">{v}</dd></div>)}
        </dl>
        {p.final_year_students && <p className="mt-3 text-xs text-slate-500">Placed ÷ final year = unique students placed ÷ {p.final_year_students} final-year students (from the sheet's Summary tab).</p>}
        {p.multi_offer_students > 0 && <p className="mt-3 flex gap-2 rounded-lg bg-amber-50 p-3 text-sm text-amber-800"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{p.multi_offer_students} students hold more than one offer. If the Summary tab counts offers ({p.offers}) as "students placed", its placement index is overstated. This app counts each student once ({p.students_placed}).</span></p>}
        <h3 className="mb-2 mt-5 text-sm font-medium">Top recruiters</h3>
        <table className="w-full text-left text-sm"><tbody className="divide-y divide-slate-100">
          {p.top_employers.map((e) => <tr key={e.employer}><td className="py-1.5">{e.employer}</td><td className="text-slate-500">{e.students} student{e.students > 1 ? 's' : ''}</td><td className="text-right tabular-nums">up to {e.top_package} LPA</td></tr>)}
        </tbody></table>
      </div>
    </>
  )
}
