import React, { useState } from 'react'
import { CheckCircle2, Download, XCircle } from 'lucide-react'
import { api, download } from '../api'
import { Badge, ErrorBox, PageHeader, Spinner, fmtDate, useLoad, useToast } from '../ui.jsx'

const TONE = { PENDING: 'amber', APPROVED: 'green', REJECTED: 'red' }
const CAT = { EMPLOYMENT: 'Placement', HIGHER_STUDIES: 'Higher studies', ENTREPRENEURSHIP: 'Entrepreneurship' }
const kb = (n) => (n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`)

// Shared by this page and the alumni drawer, so approving works the same way in both places.
export async function reviewDocument(doc, decision, toast, done) {
  let reason
  if (decision === 'REJECTED') {
    reason = window.prompt('Why is this proof not accepted? The alumnus will see this message, so say what to fix.')
    if (!reason) return
  }
  try { await api(`/documents/${doc.id}/review`, { method: 'POST', body: { decision, reason } }); toast(decision === 'APPROVED' ? 'Proof approved' : 'Proof rejected'); done() }
  catch (e) { toast(e.message, 'err') }
}

export default function Verification() {
  const toast = useToast()
  const [status, setStatus] = useState('PENDING')
  const [category, setCategory] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const qs = new URLSearchParams({ status, category, search, page, page_size: 25 }).toString()
  const { data, error, loading, reload } = useLoad(() => api('/verification?' + qs), [qs])
  const open = (d) => download(`/documents/${d.id}/download`, d.original_name).catch((e) => toast(e.message, 'err'))
  const pick = (setter) => (e) => { setPage(1); setter(e.target.value) }

  return (
    <>
      <PageHeader eyebrow="Records" title="Proof verification" sub="Open each alumnus' proof, check it against what they entered, then approve it or send it back with a reason." />
      <div className="mb-6 flex flex-wrap items-end gap-4">
        <div className="flex gap-2">{['PENDING', 'APPROVED', 'REJECTED', 'all'].map((s) => (
          <button key={s} className={status === s ? 'btn-primary' : 'btn-ghost'} onClick={() => { setPage(1); setStatus(s) }}>
            {s === 'all' ? 'All' : s[0] + s.slice(1).toLowerCase()}{data && s !== 'all' ? ` (${data.counts[s]})` : ''}</button>))}</div>
        <div><label className="label">Type</label><select className="input" value={category} onChange={pick(setCategory)}><option value="">All</option>{Object.entries(CAT).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
        <div><label className="label">Name or PRN</label><input className="input" value={search} onChange={pick(setSearch)} /></div>
      </div>
      {loading && <Spinner />}<ErrorBox error={error} retry={reload} />
      {data && (data.items.length === 0 ? <p className="py-10 text-center text-slate-500">Nothing here.</p> : (
        <div className="overflow-x-auto"><table className="w-full text-left text-sm">
          <thead><tr className="text-[11px] uppercase tracking-[0.12em] text-slate-500"><th className="py-2">Alumnus</th><th>Proof</th><th>Uploaded</th><th>Status</th><th /></tr></thead>
          <tbody>{data.items.map((d) => (
            <tr key={d.id} className="border-t border-sky-200 align-top">
              <td className="py-3"><div className="font-medium">{d.name}</div><div className="text-xs text-slate-500">PRN {d.prn} · Batch {d.graduation_year}</div></td>
              <td><div>{d.doc_label}</div><div className="text-xs text-slate-500">{CAT[d.category]} · {d.original_name} · {kb(d.size_bytes)}</div></td>
              <td className="whitespace-nowrap text-xs text-slate-500">{fmtDate(d.uploaded_at)}</td>
              <td><Badge tone={TONE[d.status]}>{d.status.toLowerCase()}</Badge>{d.rejection_reason && <div className="mt-1 max-w-[16rem] text-xs text-slate-500">{d.rejection_reason}</div>}</td>
              <td className="space-x-1 whitespace-nowrap text-right">
                <button className="btn-ghost" onClick={() => open(d)}><Download className="h-4 w-4" />Open</button>
                {d.status !== 'APPROVED' && <button className="btn-ghost" onClick={() => reviewDocument(d, 'APPROVED', toast, reload)}><CheckCircle2 className="h-4 w-4" />Approve</button>}
                {d.status !== 'REJECTED' && <button className="btn-danger" onClick={() => reviewDocument(d, 'REJECTED', toast, reload)}><XCircle className="h-4 w-4" />Reject</button>}
              </td>
            </tr>))}</tbody></table>
          <div className="mt-5 flex items-center justify-between text-sm text-slate-500"><span>{data.total} document(s)</span>
            <span className="space-x-2"><button className="btn-ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
              <button className="btn-ghost" disabled={page * 25 >= data.total} onClick={() => setPage(page + 1)}>Next</button></span></div>
        </div>))}
    </>
  )
}
