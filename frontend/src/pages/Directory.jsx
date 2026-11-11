import React, { useEffect, useState } from 'react'
import { Briefcase, GraduationCap, MapPin, Rocket, Search } from 'lucide-react'
import { api } from '../api'
import { Badge, ErrorBox, PageHeader, Spinner } from '../ui.jsx'

const CAREER = { EMPLOYMENT: ['Working', Briefcase], HIGHER_STUDIES: ['Higher studies', GraduationCap], ENTREPRENEURSHIP: ['Entrepreneur', Rocket] }
const SIZE = 24

function Card({ p }) {
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
        {place && <span className="flex items-center gap-1"><MapPin className="h-3.5 w-3.5" />{place}</span>}
      </p>
      {p.profile.skills.length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">{p.profile.skills.slice(0, 8).map((s) => <Badge key={s} tone="blue">{s}</Badge>)}</div>}
      {links.length > 0 && <p className="mt-2 flex gap-4 text-sm">{links.map(([n, u]) => <a key={n} className="text-indigo-700 underline" href={u} target="_blank" rel="noopener noreferrer">{n}</a>)}</p>}
    </article>
  )
}

export default function Directory() {
  const [q, setQ] = useState('')
  const [term, setTerm] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => { const h = setTimeout(() => { setPage(1); setTerm(q.trim()) }, 300); return () => clearTimeout(h) }, [q])
  useEffect(() => {
    let live = true
    setErr(null)
    api(`/directory?${new URLSearchParams({ search: term, page, page_size: SIZE })}`).then((r) => live && setData(r)).catch((e) => live && setErr(e))
    return () => { live = false }
  }, [term, page])

  return (
    <>
      <PageHeader eyebrow="Community" title="Alumni network" sub="Graduates who have chosen to share their profile with you. Search by name, company, city, skill or field." />
      <div className="relative mb-8 max-w-xl"><Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-slate-400" />
        <input className="input !pl-9" placeholder="Try “Python”, “Pune” or a company name" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search the alumni network" /></div>
      <ErrorBox error={err} />
      {!data && !err && <Spinner />}
      {data && (data.items.length === 0
        ? <p className="py-10 text-slate-500">{term ? 'Nobody matches that search.' : 'No one has shared their profile with you yet. Profiles appear here as alumni choose to share them.'}</p>
        : <>
          <div className="grid gap-x-12 gap-y-8 md:grid-cols-2">{data.items.map((p) => <Card key={p.id} p={p} />)}</div>
          <div className="mt-8 flex items-center justify-between text-sm text-slate-500"><span>{data.total} {data.total === 1 ? 'person' : 'people'}</span>
            <span className="space-x-2"><button className="btn-ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
              <button className="btn-ghost" disabled={page * SIZE >= data.total} onClick={() => setPage(page + 1)}>Next</button></span></div></>)}
    </>
  )
}
