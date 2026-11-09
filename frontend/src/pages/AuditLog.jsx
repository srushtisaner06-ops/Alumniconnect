import React, { useState } from 'react'
import { api } from '../api'
import { Badge, ErrorBox, PageHeader, Spinner, fmtDate, useLoad } from '../ui.jsx'

export default function AuditLog() {
  const [q, setQ] = useState({ action: '', actor: '', outcome: '', since: '', until: '' })
  const [page, setPage] = useState(1)
  const qs = new URLSearchParams({ ...Object.fromEntries(Object.entries(q).filter(([, v]) => v)), page, page_size: 50 }).toString()
  const { data, error, loading, reload } = useLoad(() => api('/audit-logs?' + qs), [qs])
  const set = (k) => (e) => { setPage(1); setQ({ ...q, [k]: e.target.value }) }
  return (
    <>
      <PageHeader eyebrow="Administration" title="Audit log" sub="An append-only record of sign-ins, changes, imports, exports and link actions. Entries cannot be edited or deleted." />
      <div className="mb-8 grid gap-4 sm:grid-cols-5">
        <div><label className="label">Action starts with</label><input className="input" placeholder="e.g. alumni." value={q.action} onChange={set('action')} /></div>
        <div><label className="label">Actor</label><input className="input" placeholder="email" value={q.actor} onChange={set('actor')} /></div>
        <div><label className="label">Outcome</label><select className="input" value={q.outcome} onChange={set('outcome')}><option value="">Any</option><option>OK</option><option>FAILED</option></select></div>
        <div><label className="label">From</label><input className="input" type="date" value={q.since} onChange={set('since')} /></div>
        <div><label className="label">To</label><input className="input" type="date" value={q.until} onChange={set('until')} /></div>
      </div>
      {loading && <Spinner />}<ErrorBox error={error} retry={reload} />
      {data && (<>
        <div className="overflow-x-auto"><table className="w-full text-left text-sm">
          <thead><tr className="text-[11px] uppercase tracking-[0.12em] text-slate-500"><th className="py-2">When</th><th>Actor</th><th>Action</th><th>Target</th><th>Details</th><th>IP</th></tr></thead>
          <tbody>{data.items.map((r) => (
            <tr key={r.id} className="border-t border-sky-200 align-top">
              <td className="whitespace-nowrap py-2 text-xs text-slate-500">{fmtDate(r.ts)}</td>
              <td className="text-xs">{r.actor_email || '—'}<div className="text-slate-400">{r.actor_role}</div></td>
              <td><span className="font-mono text-xs">{r.action}</span> {r.outcome !== 'OK' && <Badge tone="red">{r.outcome}</Badge>}</td>
              <td className="text-xs">{r.entity_type ? `${r.entity_type} #${r.entity_id ?? ''}` : '—'}</td>
              <td className="max-w-xs break-words font-mono text-[11px] text-slate-500">{r.detail ? JSON.stringify(r.detail) : ''}</td>
              <td className="text-xs text-slate-500">{r.ip}</td>
            </tr>))}</tbody></table></div>
        <div className="mt-5 flex items-center justify-between text-sm text-slate-500">
          <span>{data.total} entries</span>
          <span className="space-x-2"><button className="btn-ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
            <button className="btn-ghost" disabled={page * 50 >= data.total} onClick={() => setPage(page + 1)}>Next</button></span>
        </div></>)}
    </>
  )
}
