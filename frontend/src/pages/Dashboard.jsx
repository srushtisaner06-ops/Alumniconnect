import React from 'react'
import { Link } from 'react-router-dom'
import { CheckCircle2, Clock, Percent, Users, AlertTriangle, ArrowRight } from 'lucide-react'
import { api } from '../api'
import { Badge, ErrorBox, PageHeader, Progress, Spinner, Stat, useLoad } from '../ui.jsx'

export default function Dashboard() {
  const { data, error, loading, reload } = useLoad(() => api('/dashboard'))
  if (loading) return <Spinner />
  if (error) return <ErrorBox error={error} retry={reload} />
  const s = data.summary, p = data.placement
  return (
    <>
      <PageHeader title="Overview" sub="Alumni data collection progress" />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat icon={Users} label="Total alumni" value={s.total} />
        <Stat icon={CheckCircle2} label="Completed" value={s.completed} tone="green" />
        <Stat icon={Clock} label="Pending" value={s.pending} tone="amber" sub={s.overdue ? `${s.overdue} overdue` : undefined} />
        <Stat icon={Percent} label="Completion" value={`${s.completion_pct}%`} />
      </div>
      <div className="card mt-4 p-4">
        <div className="mb-2 flex justify-between text-sm"><span className="font-medium">Submission progress</span><span className="text-slate-500">{s.completed} of {s.total}</span></div>
        <Progress value={s.completion_pct} />
        {s.total === 0 && <p className="mt-3 text-sm text-slate-500">No alumni yet. <Link className="text-indigo-600 underline" to="/dashboard/alumni/import">Import a placement sheet</Link>.</p>}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div className="card p-4">
          <h2 className="mb-3 font-medium">Next to remind</h2>
          {data.next_pending.length === 0 ? <p className="text-sm text-slate-500">Everyone has responded.</p> : (
            <ul className="divide-y divide-slate-100">
              {data.next_pending.map((a) => (
                <li key={a.id} className="flex items-center justify-between py-2 text-sm">
                  <span className="min-w-0 truncate">{a.name}</span><span className="ml-3 font-mono text-xs text-slate-500">{a.prn}</span>
                </li>))}
            </ul>)}
          <Link to="/dashboard/alumni" className="mt-3 inline-flex items-center gap-1 text-sm text-indigo-600">All alumni <ArrowRight className="h-3 w-3" /></Link>
        </div>
        <div className="card p-4">
          <h2 className="mb-3 font-medium">Placement snapshot</h2>
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div><dt className="text-slate-500">Students placed</dt><dd className="text-lg font-semibold">{p.students_placed}</dd></div>
            <div><dt className="text-slate-500">Offers recorded</dt><dd className="text-lg font-semibold">{p.offers}</dd></div>
            <div><dt className="text-slate-500">Highest package</dt><dd className="text-lg font-semibold">{p.highest_package} LPA</dd></div>
            <div><dt className="text-slate-500">Median package</dt><dd className="text-lg font-semibold">{p.median_package} LPA</dd></div>
          </dl>
          {p.multi_offer_students > 0 && (
            <p className="mt-3 flex gap-2 rounded-lg bg-amber-50 p-2 text-xs text-amber-800"><AlertTriangle className="h-4 w-4 shrink-0" />
              {p.multi_offer_students} students have more than one offer, so offers ({p.offers}) exceed students placed ({p.students_placed}).</p>)}
        </div>
      </div>
      <div className="card mt-4 p-4">
        <h2 className="mb-2 font-medium">Reminder rounds</h2>
        {data.campaigns.length === 0 ? <p className="text-sm text-slate-500">No reminder round yet. <Link className="text-indigo-600 underline" to="/dashboard/campaigns">Create one</Link>.</p>
          : data.campaigns.map((c) => <div key={c.id} className="flex items-center justify-between py-1 text-sm"><span>{c.name}</span><Badge tone={c.status === 'RUNNING' ? 'green' : 'slate'}>{c.status}</Badge></div>)}
      </div>
    </>
  )
}
