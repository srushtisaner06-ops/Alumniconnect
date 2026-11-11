import React, { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, Copy, ExternalLink, Search, Trash2, Undo2, X } from 'lucide-react'
import { api, can, download } from '../api'
import { reviewDocument } from './Verification.jsx'
import { Badge, CAREER, CATEGORIES, CATEGORY_KEYS, CategoryBadges, ErrorBox, PageHeader, Spinner, StatusBadge, fmtDate, useLoad, useToast } from '../ui.jsx'

const TABS = [['all', 'All'], ['PENDING', 'Pending'], ['COMPLETED', 'Completed'], ['OVERDUE', 'Overdue']]

// What to show in the "organisation" and "detail" columns for the category being viewed.
const COLS = {
  all: ['Organisation', 'Package / degree / reg. no.'], PLACEMENT: ['Employer', 'Package'],
  HIGHER_STUDIES: ['College / university', 'Degree'], ENTREPRENEURSHIP: ['Company', 'Registration no.'],
}
function summarize(a, cat) {
  const c = cat !== 'all' ? cat : a.categories?.[0]
  if (c === 'PLACEMENT' && a.offers?.length) return { org: a.offers[0].employer, more: a.offers.length - 1, extra: a.best_package ? `${a.best_package} LPA` : '—' }
  if (c === 'HIGHER_STUDIES' && a.higher_studies?.length) return { org: a.higher_studies[0].institution, more: a.higher_studies.length - 1, extra: a.higher_studies[0].degree }
  if (c === 'ENTREPRENEURSHIP' && a.ventures?.length) return { org: a.ventures[0].company, more: a.ventures.length - 1, extra: a.ventures[0].registration_no }
  return { org: '', more: 0, extra: '—' }
}

export default function Alumni() {
  const toast = useToast()
  const [q, setQ] = useState('')
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('all')
  const [category, setCategory] = useState('all')
  const [page, setPage] = useState(1)
  const [openId, setOpenId] = useState(null)
  function submitSearch(e) { e.preventDefault(); setSearch(q.trim()); setPage(1) }
  function clearSearch() { setQ(''); setSearch(''); setPage(1) }
  const list = useLoad(() => api(`/alumni?search=${encodeURIComponent(search)}&status=${status}&category=${category}&page=${page}&page_size=25`), [search, status, category, page])
  const undo = useLoad(() => api('/undo'), [])
  const reloadAll = () => { list.reload(); undo.reload() }
  const pages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.page_size)) : 1

  async function doUndo() {
    try { const r = await api('/undo', { method: 'POST' }); toast('Undone: ' + r.undone); reloadAll() } catch (e) { toast(e.message, 'err') }
  }
  return (
    <>
      <PageHeader eyebrow="Directory" title="Alumni directory" sub="Search, review and maintain alumni records." art="/img/art-people.svg">
        <button className="btn-ghost" onClick={doUndo} disabled={!undo.data?.count} title={undo.data?.next || 'Nothing to undo'}>
          <Undo2 className="h-4 w-4" />Undo last action</button>
      </PageHeader>
      <div className="mb-8">
        <form onSubmit={submitSearch} className="flex flex-col gap-3 sm:flex-row">
          <div className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-slate-400" />
            <input aria-label="Search alumni" className="input pl-9" placeholder="Enter name, PRN, email, employer, university or company" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <button className="btn-primary sm:min-w-28" type="submit"><Search className="h-4 w-4" />Search</button>
          {(q || search) && <button className="btn-ghost" type="button" onClick={clearSearch}>Clear</button>}
        </form>
        <div className="mt-4 flex flex-col gap-3 border-t border-sky-200 pt-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Filter by category</div>
          <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Filter alumni by category">
            {[['all', 'All categories'], ...CATEGORY_KEYS.map((k) => [k, CATEGORIES[k].label])].map(([v, l]) => (
              <button key={v} role="tab" aria-selected={category === v} onClick={() => { setCategory(v); setPage(1) }}
                className={`tab ${category === v ? 'tab-on' : ''}`}>
                {l}{list.data?.category_counts && <span className="ml-1.5 opacity-75">{list.data.category_counts[v]}</span>}</button>))}
          </div>
        </div>
        <div className="mt-3 flex flex-col gap-3 border-t border-sky-200 pt-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Filter by submission status</div>
          <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Filter alumni by status">
            {TABS.map(([v, l]) => (
              <button key={v} role="tab" aria-selected={status === v} onClick={() => { setStatus(v); setPage(1) }}
                className={`tab ${status === v ? 'tab-on' : ''}`}>{l}</button>))}
          </div>
        </div>
      </div>
      <ErrorBox error={list.error} retry={list.reload} />
      <div className="card">
        <div className="flex items-center justify-between border-b border-sky-200 px-4 py-3 sm:px-5"><h2 className="section-title">Alumni records</h2><span className="text-xs text-slate-500">{list.data ? `${list.data.total} total` : 'Loading records'}</span></div>
        <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500">
            <tr><th className="px-4 py-3">Sr</th><th className="px-4 py-3">Name</th><th className="px-4 py-3">PRN</th><th className="px-4 py-3">Category</th><th className="px-4 py-3">{COLS[category][0]}</th><th className="px-4 py-3">{COLS[category][1]}</th><th className="px-4 py-3">Status</th></tr>
          </thead>
          <tbody className="divide-y divide-sky-200">
            {list.loading && <tr><td colSpan={7}><Spinner /></td></tr>}
            {!list.loading && list.data?.items.map((a) => { const sm = summarize(a, category); return (
              <tr key={a.id} className="cursor-pointer transition-colors hover:bg-indigo-100/40" onClick={() => setOpenId(a.id)} tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && setOpenId(a.id)}>
                <td className="px-4 py-3 text-slate-500">{a.sr_no}</td>
                <td className="px-4 py-3 font-medium">{a.name}{a.unsubscribed ? <span className="ml-2"><Badge>unsubscribed</Badge></span> : null}</td>
                <td className="px-4 py-3 font-mono text-xs">{a.prn}</td>
                <td className="px-4 py-3"><CategoryBadges categories={a.categories} /></td>
                <td className="px-4 py-3">{sm.org}{sm.more > 0 && <span className="ml-1 text-xs text-slate-500">+{sm.more}</span>}</td>
                <td className="px-4 py-3 tabular-nums">{sm.extra}</td>
                <td className="px-4 py-3"><StatusBadge a={a} /></td>
              </tr>) })}
            {!list.loading && list.data?.items.length === 0 && <tr><td colSpan={7} className="px-4 py-12 text-center text-slate-500">No alumni match.</td></tr>}
          </tbody>
        </table>
        </div>
      </div>
      {list.data && (
        <div className="mt-3 flex items-center justify-between text-sm text-slate-500">
          <span>{list.data.total} record{list.data.total === 1 ? '' : 's'}</span>
          <div className="flex items-center gap-2">
            <button className="btn-ghost px-2" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page"><ChevronLeft className="h-4 w-4" /></button>
            <span>Page {page} of {pages}</span>
            <button className="btn-ghost px-2" disabled={page >= pages} onClick={() => setPage(page + 1)} aria-label="Next page"><ChevronRight className="h-4 w-4" /></button>
          </div>
        </div>)}
      {openId && <Drawer id={openId} onClose={() => setOpenId(null)} onChanged={reloadAll} />}
    </>
  )
}

function LetterLink({ href, label }) {
  return href ? <div><a className="inline-flex items-center gap-1 text-xs text-indigo-600" href={href} target="_blank" rel="noreferrer">{label} <ExternalLink className="h-3 w-3" /></a></div> : null
}

function Drawer({ id, onClose, onChanged }) {
  const toast = useToast()
  const { data: a, error, loading, reload } = useLoad(() => api(`/alumni/${id}`), [id])
  const [chat, setChat] = useState('')
  useEffect(() => { if (a) setChat(a.telegram_chat_id || '') }, [a])
  async function patch(body, msg) {
    try { await api(`/alumni/${id}`, { method: 'PATCH', body }); toast(msg); reload(); onChanged() } catch (e) { toast(e.message, 'err') }
  }
  async function link(action) {
    if (action === 'regenerate' && !window.confirm('Generate a new link? The current link stops working immediately.')) return
    if (action === 'revoke' && !window.confirm('Disable this link? The person will not receive reminders until you generate a new one.')) return
    try { await api(`/alumni/${id}/link/${action}`, { method: 'POST' }); toast(action === 'regenerate' ? 'New link generated' : 'Link disabled'); reload(); onChanged() } catch (e) { toast(e.message, 'err') }
  }
  async function createLogin() {
    if (!a.email) { toast('This alumnus has no email address on record.', 'err'); return }
    if (!window.confirm(`Create a login for ${a.name} and send an invite to ${a.email}?`)) return
    try {
      const r = await api('/users', { method: 'POST', body: { email: a.email, full_name: a.name, role: 'ALUMNI', alumni_id: id, password: null } })
      if (r.invite_link) window.prompt('Email is not set up on this server. Copy this one-time invite link and send it to the alumnus:', r.invite_link)
      else toast('Invite emailed')
      reload()
    } catch (e) { toast(e.message, 'err') }
  }
  async function del() {
    if (!window.confirm(`Delete ${a.name}? You can undo this from the Alumni page.`)) return
    try { await api(`/alumni/${id}`, { method: 'DELETE' }); toast('Deleted. Use Undo to restore.'); onChanged(); onClose() } catch (e) { toast(e.message, 'err') }
  }
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-blue-900/30" onClick={onClose}>
      <aside className="h-full w-full max-w-md overflow-y-auto bg-slate-50 p-7 shadow-2xl" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Alumnus details">
        <div className="mb-4 flex items-start justify-between">
          <div><h2 className="text-lg font-semibold">{a?.name || 'Alumnus'}</h2>{a && <div className="font-mono text-xs text-slate-500">PRN {a.prn}</div>}</div>
          <button onClick={onClose} aria-label="Close" className="rounded-full p-1.5 hover:bg-slate-200/60"><X className="h-5 w-5" /></button>
        </div>
        {loading && <Spinner />}<ErrorBox error={error} retry={reload} />
        {a && (
          <div className="space-y-5 text-sm">
            <div className="flex items-center gap-2"><StatusBadge a={a} />{a.submitted_at && <span className="text-xs text-slate-500">submitted {fmtDate(a.submitted_at)}</span>}</div>
            <dl className="grid grid-cols-2 gap-3">
              <div><dt className="text-slate-500">Class</dt><dd>{a.class_div}</dd></div>
              <div><dt className="text-slate-500">Batch</dt><dd>{a.graduation_year}</dd></div>
              <div><dt className="text-slate-500">Phone</dt><dd>{a.phone}</dd></div>
              <div className="min-w-0"><dt className="text-slate-500">Email</dt><dd className="truncate">{a.email}</dd></div>
            </dl>
            {a.categories.length === 0 && <p className="text-slate-500">No placement, higher-studies or entrepreneurship record yet.</p>}
            {a.offers.length > 0 && (
              <section><h3 className="mb-2 flex items-center gap-2 font-medium">Placement record <Badge tone={CATEGORIES.PLACEMENT.tone}>{CATEGORIES.PLACEMENT.table}</Badge></h3>
                {a.offers.map((o) => (
                  <div key={o.id} className="mb-2 border-l-2 border-sky-300 py-1 pl-3">
                    <div className="flex justify-between"><span className="font-medium">{o.employer}</span><span className="tabular-nums">{o.package_lpa} LPA</span></div>
                    <div className="text-slate-500">{o.position || 'Position not recorded'}</div>
                    {o.letter_ref && <div className="text-xs text-slate-500">Letter: {o.letter_ref}</div>}
                    <LetterLink href={o.letter_link} label="Appointment letter" />
                  </div>))}
              </section>)}
            {a.higher_studies.length > 0 && (
              <section><h3 className="mb-2 flex items-center gap-2 font-medium">Higher studies <Badge tone={CATEGORIES.HIGHER_STUDIES.tone}>{CATEGORIES.HIGHER_STUDIES.table}</Badge></h3>
                {a.higher_studies.map((h) => (
                  <div key={h.id} className="mb-2 border-l-2 border-sky-300 py-1 pl-3">
                    <div className="font-medium">{h.degree}</div>
                    <div className="text-slate-500">{h.institution}</div>
                    <LetterLink href={h.letter_link} label="Admission / appointment letter" />
                  </div>))}
              </section>)}
            {a.ventures.length > 0 && (
              <section><h3 className="mb-2 flex items-center gap-2 font-medium">Entrepreneurship <Badge tone={CATEGORIES.ENTREPRENEURSHIP.tone}>{CATEGORIES.ENTREPRENEURSHIP.table}</Badge></h3>
                {a.ventures.map((v) => (
                  <div key={v.id} className="mb-2 border-l-2 border-sky-300 py-1 pl-3">
                    <div className="font-medium">{v.company}</div>
                    <div className="font-mono text-xs text-slate-500">Reg. no. {v.registration_no}</div>
                    {v.website && <a className="inline-flex items-center gap-1 break-all text-xs text-indigo-600" href={v.website} target="_blank" rel="noreferrer">{v.website} <ExternalLink className="h-3 w-3 shrink-0" /></a>}
                    <LetterLink href={v.letter_link} label="Registration letter" />
                  </div>))}
              </section>)}
            {a.details && (
              <section><h3 className="mb-2 font-medium">Submitted details · {CAREER[a.career_status]}</h3>
                <dl className="space-y-1">{Object.entries(a.details).map(([k, v]) => <div key={k} className="flex gap-2"><dt className="w-32 shrink-0 capitalize text-slate-500">{k.replace('_', ' ')}</dt><dd>{v}</dd></div>)}</dl></section>)}
            {can('verification.review') && (
              <section><h3 className="mb-2 font-medium">Proof and income</h3>
                <p className="text-sm text-slate-600">Income range: <b>{a.income_label || 'not provided'}</b></p>
                {!(a.documents || []).length ? <p className="mt-1 text-sm text-slate-500">No proof uploaded yet.</p> : (
                  <ul className="mt-2 space-y-3">{a.documents.map((d) => (
                    <li key={d.id} className={`border-l-4 pl-3 ${d.superseded ? 'border-slate-200 opacity-60' : d.status === 'APPROVED' ? 'border-emerald-400' : d.status === 'REJECTED' ? 'border-red-400' : 'border-amber-400'}`}>
                      <div className="flex flex-wrap items-center gap-2 text-sm"><span className="font-medium">{d.doc_label}</span>
                        <Badge tone={d.superseded ? 'slate' : d.status === 'APPROVED' ? 'green' : d.status === 'REJECTED' ? 'red' : 'amber'}>{d.superseded ? 'replaced' : d.status.toLowerCase()}</Badge></div>
                      <div className="text-xs text-slate-500">{d.original_name} · {fmtDate(d.uploaded_at)}{d.reviewed_by && ` · reviewed by ${d.reviewed_by}`}</div>
                      {d.rejection_reason && <div className="text-xs text-red-700">{d.rejection_reason}</div>}
                      {!d.superseded && <div className="mt-1 flex gap-2">
                        <button className="btn-ghost" onClick={() => download(`/documents/${d.id}/download`, d.original_name).catch((e) => toast(e.message, 'err'))}>Open</button>
                        {d.status !== 'APPROVED' && <button className="btn-ghost" onClick={() => reviewDocument(d, 'APPROVED', toast, () => { reload(); onChanged() })}>Approve</button>}
                        {d.status !== 'REJECTED' && <button className="btn-danger" onClick={() => reviewDocument(d, 'REJECTED', toast, () => { reload(); onChanged() })}>Reject</button>}</div>}
                    </li>))}</ul>)}
              </section>)}
            {a.profile && (
              <section><h3 className="mb-2 font-medium">Profile</h3>
                {[a.profile.designation, a.profile.professional_domain, [a.profile.city, a.profile.country].filter(Boolean).join(', '), a.profile.years_experience != null && `${a.profile.years_experience} yrs experience`].filter(Boolean).length === 0 && !a.profile.skills.length
                  ? <p className="text-sm text-slate-500">Nothing filled in yet.</p>
                  : <div className="space-y-1 text-sm text-slate-700">
                      <p>{[a.profile.designation, a.profile.professional_domain].filter(Boolean).join(' · ')}</p>
                      <p>{[a.profile.city, a.profile.country].filter(Boolean).join(', ')}{a.profile.years_experience != null && ` · ${a.profile.years_experience} yrs experience`}</p>
                      {a.profile.whatsapp && <p>WhatsApp: {a.profile.whatsapp}</p>}
                      {a.profile.skills.length > 0 && <p className="text-slate-500">Skills: {a.profile.skills.join(', ')}</p>}</div>}
              </section>)}
            {a.career_events && (
              <section><h3 className="mb-2 font-medium">Career timeline</h3>
                <ol className="space-y-2 border-l-2 border-sky-200 pl-4 text-sm">{a.career_events.map((ev) => (
                  <li key={ev.id} className={ev.retracted ? 'opacity-50' : ''}>
                    <div className={ev.retracted ? 'line-through' : ''}><span className="font-medium">{ev.title}</span> <Badge tone="slate">{ev.type_label}</Badge> <span className="text-xs text-slate-500">{ev.event_date || 'date not given'}</span></div>
                    {(ev.organisation || ev.detail) && <div className="text-xs text-slate-500">{[ev.organisation, ev.detail].filter(Boolean).join(' · ')}</div>}
                    {ev.retracted && <div className="text-xs text-slate-500">Retracted by {ev.retracted_by}: {ev.retract_reason}</div>}
                  </li>))}</ol>
              </section>)}
            {a.account !== undefined && (
              <section><h3 className="mb-2 font-medium">Login</h3>
                {a.account ? <p className="text-sm text-slate-600">Has a login: {a.account.email} <Badge tone={a.account.is_active ? 'green' : 'slate'}>{a.account.is_active ? 'active' : 'disabled'}</Badge></p>
                  : <><p className="mb-2 text-sm text-slate-500">No login yet. A login lets this person manage their own profile and privacy.</p><button className="btn-ghost" onClick={createLogin}>Create login &amp; send invite</button></>}
              </section>)}
            <section><h3 className="mb-2 flex items-center gap-2 font-medium">Personal link
              <Badge tone={a.link_status === 'active' ? 'green' : a.link_status === 'expired' ? 'amber' : 'red'}>{a.link_status}</Badge></h3>
              <div className="flex gap-2"><input readOnly className="input font-mono text-xs" value={a.link} onFocus={(e) => e.target.select()} disabled={a.link_status !== 'active'} />
                <button className="btn-ghost" aria-label="Copy link" disabled={a.link_status !== 'active'} onClick={() => { navigator.clipboard.writeText(a.link); toast('Link copied') }}><Copy className="h-4 w-4" /></button>
                {a.link_status === 'active' && <a className="btn-ghost whitespace-nowrap" target="_blank" rel="noopener noreferrer" title="Opens the alumni form on the address you are using now"
                  href={`${window.location.origin}/update?token=${a.link.split('token=')[1]}`}>Open form</a>}</div>
              <p className="mt-1 text-xs text-slate-500">{a.link_status === 'revoked' ? 'Disabled. This person is left out of reminders until you generate a new link.' : `Valid until ${fmtDate(a.token_expires_at)}. Each reminder renews it.`}</p>
              {can('alumni.link.manage') && <div className="mt-2 flex gap-2">
                <button className="btn-ghost" onClick={() => link('regenerate')}>New link</button>
                {a.link_status !== 'revoked' && <button className="btn-danger" onClick={() => link('revoke')}>Disable link</button>}</div>}
            </section>
            <section><h3 className="mb-2 font-medium">Telegram chat ID</h3>
              <div className="flex gap-2"><input className="input" value={chat} onChange={(e) => setChat(e.target.value)} placeholder="optional" />
                <button className="btn-ghost" onClick={() => patch({ telegram_chat_id: chat }, 'Saved')}>Save</button></div></section>
            <section><h3 className="mb-2 font-medium">Reminders · {a.reminders_sent} sent</h3>
              {a.history.length === 0 ? <p className="text-slate-500">None yet.</p> : a.history.map((h) => (
                <div key={h.id} className="flex items-center justify-between border-b border-sky-200 py-1 text-xs">
                  <span>{h.campaign} · {h.channel}</span><span className="flex items-center gap-2"><Badge tone={h.status === 'FAILED' ? 'red' : h.status === 'SKIPPED' ? 'slate' : 'green'}>{h.status}</Badge>{fmtDate(h.created_at)}</span></div>))}
            </section>
            <div className="flex flex-wrap gap-2 border-t border-sky-200 pt-4">
              <button className="btn-ghost" onClick={() => patch({ unsubscribed: !a.unsubscribed }, a.unsubscribed ? 'Re-subscribed' : 'Unsubscribed')}>{a.unsubscribed ? 'Re-subscribe' : 'Unsubscribe from reminders'}</button>
              {can('alumni.delete') && <button className="btn-danger" onClick={del}><Trash2 className="h-4 w-4" />Delete</button>}
            </div>
          </div>)}
      </aside>
    </div>
  )
}
