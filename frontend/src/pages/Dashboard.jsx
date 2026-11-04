import React from 'react'
import { Link } from 'react-router-dom'
import { CheckCircle2, Clock, Percent, Users, AlertTriangle, ArrowRight, Briefcase, GraduationCap, Rocket } from 'lucide-react'
import { api } from '../api'
import { Badge, ErrorBox, PageHeader, Progress, Spinner, Stat, useLoad } from '../ui.jsx'

const QUICK = [
  { to: '/dashboard/alumni/import', title: 'Import records', text: 'Bring in placement, higher-studies and entrepreneurship sheets.', art: '/img/art-upload.svg' },
  { to: '/dashboard/alumni', title: 'Alumni directory', text: 'Search, review and maintain every alumni profile.', art: '/img/art-people.svg' },
  { to: '/dashboard/campaigns', title: 'Reminders', text: 'Send personal links to graduates who have not replied.', art: '/img/art-mail.svg' },
  { to: '/dashboard/reports', title: 'Reports & exports', text: 'Analytics and NIRF / NBA ready exports.', art: '/img/art-chart.svg' },
]

export default function Dashboard() {
  const { data, error, loading, reload } = useLoad(() => api('/dashboard'))
  if (loading) return <Spinner />
  if (error) return <ErrorBox error={error} retry={reload} />
  const s = data.summary, p = data.placement, pr = data.progression
  return (
    <>
      <PageHeader eyebrow="Alumni network" title={<>Keep every graduate <span className="text-indigo-600">connected</span></>}
        sub={`${s.completed} of ${s.total} alumni have shared their career updates. Send reminders to bring the rest on board.`} art="/img/hero-campus.svg">
        <Link to="/dashboard/campaigns" className="btn-primary">Send reminders <ArrowRight className="h-4 w-4" /></Link>
        <Link to="/dashboard/alumni/import" className="btn-ghost">Import records</Link>
      </PageHeader>

      <div className="grid grid-cols-2 gap-x-8 gap-y-10 lg:grid-cols-4">
        <Stat icon={Users} label="Total alumni" value={s.total} />
        <Stat icon={CheckCircle2} label="Completed" value={s.completed} tone="green" />
        <Stat icon={Clock} label="Pending" value={s.pending} tone="amber" sub={s.overdue ? `${s.overdue} overdue` : undefined} />
        <Stat icon={Percent} label="Completion" value={`${s.completion_pct}%`} />
      </div>

      <div className="mt-12">
        <div className="mb-3 flex justify-between text-sm"><span className="font-medium text-slate-700">Submission progress</span><span className="text-slate-500">{s.completed} of {s.total}</span></div>
        <Progress value={s.completion_pct} />
        {s.total === 0 && <p className="mt-3 text-sm text-slate-500">No alumni yet. <Link className="font-medium text-indigo-700 underline" to="/dashboard/alumni/import">Import a placement sheet</Link>.</p>}
      </div>

      <section className="mt-20">
        <div className="mb-8 flex flex-wrap items-end justify-between gap-2">
          <div><h2 className="section-title text-3xl">Student outcomes</h2><div className="silver-mark mt-3 w-24" /></div>
          <Link to="/dashboard/alumni/import" className="inline-flex items-center gap-1 text-sm font-medium text-indigo-700 hover:underline">Import records <ArrowRight className="h-3 w-3" /></Link>
        </div>
        <div className="grid grid-cols-1 gap-x-8 gap-y-10 sm:grid-cols-3">
          <Stat icon={Briefcase} label="Placement" value={pr.placed} sub="Table 4.6.1" />
          <Stat icon={GraduationCap} label="Higher studies" value={pr.higher_studies} tone="blue" sub="Table 4.6.2" />
          <Stat icon={Rocket} label="Entrepreneurship" value={pr.entrepreneurship} tone="green" sub="Table 4.6.3" />
        </div>
        <p className="mt-5 text-xs text-slate-500">
          {pr.total} student{pr.total === 1 ? '' : 's'} counted once across the three categories
          {pr.index != null ? ` · placement index (X+Y+Z)/FS = ${pr.total}/${pr.final_year_students} = ${pr.index}%` : ' · import the placement sheet (with its Summary tab) to compute the placement index'}.
        </p>
      </section>

      <section className="mt-20 grid gap-x-16 gap-y-12 lg:grid-cols-2">
        <div>
          <h2 className="section-title">Next to remind</h2><div className="silver-mark mt-3 w-16" />
          {data.next_pending.length === 0 ? <p className="mt-5 text-sm text-slate-500">Everyone has responded.</p> : (
            <ul className="mt-4 divide-y divide-sky-200">
              {data.next_pending.map((a) => (
                <li key={a.id} className="flex items-center justify-between py-3 text-sm">
                  <span className="min-w-0 truncate font-medium">{a.name}</span><span className="ml-3 font-mono text-xs text-slate-500">{a.prn}</span>
                </li>))}
            </ul>)}
          <Link to="/dashboard/alumni" className="mt-4 inline-flex items-center gap-1 text-sm font-medium text-indigo-700 hover:underline">All alumni <ArrowRight className="h-3 w-3" /></Link>
        </div>
        <div>
          <h2 className="section-title">Placement snapshot</h2><div className="silver-mark mt-3 w-16" />
          <dl className="mt-5 grid grid-cols-2 gap-6 text-sm">
            <div><dt className="text-slate-500">Students placed</dt><dd className="font-display text-3xl font-semibold">{p.students_placed}</dd></div>
            <div><dt className="text-slate-500">Offers recorded</dt><dd className="font-display text-3xl font-semibold">{p.offers}</dd></div>
            <div><dt className="text-slate-500">Highest package</dt><dd className="font-display text-3xl font-semibold">{p.highest_package}<span className="ml-1 text-base text-slate-500">LPA</span></dd></div>
            <div><dt className="text-slate-500">Median package</dt><dd className="font-display text-3xl font-semibold">{p.median_package}<span className="ml-1 text-base text-slate-500">LPA</span></dd></div>
          </dl>
          {p.multi_offer_students > 0 && (
            <p className="mt-5 flex gap-2 border-l-4 border-amber-400 py-1 pl-3 text-xs text-amber-900"><AlertTriangle className="h-4 w-4 shrink-0" />
              {p.multi_offer_students} students have more than one offer, so offers ({p.offers}) exceed students placed ({p.students_placed}).</p>)}
        </div>
      </section>

      <section className="mt-20">
        <h2 className="section-title text-3xl">Where would you like to go?</h2><div className="silver-mark mt-3 w-24" />
        <div className="mt-8 grid gap-x-10 gap-y-12 sm:grid-cols-2 lg:grid-cols-4">
          {QUICK.map((q) => (
            <Link key={q.to} to={q.to} className="group block">
              <div className="relative flex h-44 items-center justify-center overflow-hidden rounded-[2rem] bg-gradient-to-br from-indigo-100 via-slate-100 to-sky-100">
                <img src={q.art} alt="" className="h-full w-auto transition duration-500 group-hover:scale-110" />
              </div>
              <h3 className="mt-5 flex items-center gap-2 text-xl font-semibold text-slate-900">{q.title}<ArrowRight className="h-4 w-4 -translate-x-1 text-indigo-600 opacity-0 transition group-hover:translate-x-0 group-hover:opacity-100" /></h3>
              <p className="mt-1 text-sm leading-6 text-slate-500">{q.text}</p>
            </Link>))}
        </div>
      </section>

      <section className="mt-20">
        <h2 className="section-title">Reminder rounds</h2><div className="silver-mark mt-3 w-16" />
        {data.campaigns.length === 0 ? <p className="mt-5 text-sm text-slate-500">No reminder round yet. <Link className="font-medium text-indigo-700 underline" to="/dashboard/campaigns">Create one</Link>.</p>
          : <ul className="mt-4 divide-y divide-sky-200">{data.campaigns.map((c) => <li key={c.id} className="flex items-center justify-between py-3 text-sm"><span className="font-medium">{c.name}</span><Badge tone={c.status === 'RUNNING' ? 'green' : 'slate'}>{c.status}</Badge></li>)}</ul>}
      </section>
    </>
  )
}
