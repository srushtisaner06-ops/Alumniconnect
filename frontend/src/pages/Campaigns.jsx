import React, { useState } from 'react'
import { Loader2, Pause, Pencil, Play, Plus, RefreshCw, Zap } from 'lucide-react'
import { api } from '../api'
import { Badge, ErrorBox, PageHeader, Spinner, fmtDate, useLoad, useToast } from '../ui.jsx'

const tone = { RUNNING: 'green', PAUSED: 'amber', DRAFT: 'slate', COMPLETED: 'blue' }
const BLANK = { name: '', channel: 'email', interval_hours: 72, max_attempts: 3, batch_size: 20, deadline: '',
  email_subject: 'Please update your career details – {{batch}} batch',
  email_body: 'Dear {{name}},\n\nThe department is collecting career information from the {{batch}} batch for accreditation reports. It takes about two minutes.\n\nYour personal link:\n{{unique_link}}\n\nThank you,\nDepartment of Computer Science (AI)',
  telegram_body: 'Hi {{name}}, please update your career details ({{batch}} batch): {{unique_link}}' }

export default function Campaigns() {
  const toast = useToast()
  const camps = useLoad(() => api('/campaigns'))
  const log = useLoad(() => api('/reminders?limit=40'))
  const [editing, setEditing] = useState(null)
  const [busyId, setBusyId] = useState(null)
  const refresh = () => { camps.reload(); log.reload() }

  async function act(c, action) {
    setBusyId(c.id + action)
    try {
      const r = await api(`/campaigns/${c.id}/${action}`, { method: 'POST' })
      if (action === 'run-now') toast(`Batch processed: ${r.sent + r.simulated} sent, ${r.failed} failed, ${r.skipped} skipped, ${r.remaining} waiting.`)
      else toast(`Campaign ${action === 'pause' ? 'paused' : 'running'}`)
      refresh()
    } catch (e) { toast(e.message, 'err') } finally { setBusyId(null) }
  }
  const mode = camps.data?.mode
  return (
    <>
      <PageHeader title="Reminder campaigns" sub="Personalised links are sent to alumni who have not submitted">
        <button className="btn-ghost" onClick={refresh}><RefreshCw className="h-4 w-4" />Refresh</button>
        <button className="btn-primary" onClick={() => setEditing({ ...BLANK })}><Plus className="h-4 w-4" />New campaign</button>
      </PageHeader>
      {mode && (mode.email === 'simulated' || mode.telegram === 'simulated') && (
        <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          <strong>Simulated delivery:</strong> {[mode.email === 'simulated' && 'email (SMTP not configured)', mode.telegram === 'simulated' && 'Telegram (bot token not set)'].filter(Boolean).join(' and ')}.
          Reminders are logged but nobody is contacted until you configure the backend environment.
        </div>)}
      <ErrorBox error={camps.error} retry={camps.reload} />
      {camps.loading && !camps.data && <Spinner />}
      {camps.data?.items.length === 0 && <div className="card p-8 text-center text-sm text-slate-500">No campaigns yet. Create one to start sending reminders.</div>}
      <div className="space-y-4">
        {camps.data?.items.map((c) => (
          <div key={c.id} className="card p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div><div className="flex items-center gap-2"><h2 className="font-medium">{c.name}</h2><Badge tone={tone[c.status]}>{c.status}</Badge></div>
                <p className="mt-1 text-xs text-slate-500">{c.channel} · every {c.interval_hours} h · max {c.max_attempts} attempts · batch {c.batch_size} · deadline {c.deadline || '—'}</p></div>
              <div className="flex flex-wrap gap-2">
                {c.status === 'RUNNING' ? <>
                  <button className="btn-ghost" disabled={!!busyId} onClick={() => act(c, 'run-now')}>{busyId === c.id + 'run-now' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}Run batch now</button>
                  <button className="btn-ghost" disabled={!!busyId} onClick={() => act(c, 'pause')}><Pause className="h-4 w-4" />Pause</button></>
                  : <button className="btn-primary" disabled={!!busyId} onClick={() => act(c, c.status === 'PAUSED' ? 'resume' : 'start')}><Play className="h-4 w-4" />{c.status === 'PAUSED' ? 'Resume' : c.status === 'COMPLETED' ? 'Restart' : 'Start'}</button>}
                <button className="btn-ghost" onClick={() => setEditing({ ...c, deadline: c.deadline || '' })}><Pencil className="h-4 w-4" />Edit</button>
              </div>
            </div>
            <dl className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              <div><dt className="text-slate-500">Reminders sent</dt><dd className="font-semibold tabular-nums">{c.sent}</dd></div>
              <div><dt className="text-slate-500">Failed</dt><dd className="font-semibold tabular-nums">{c.failed}</dd></div>
              <div><dt className="text-slate-500">Due now</dt><dd className="font-semibold tabular-nums">{c.eligible_now}</dd></div>
              <div><dt className="text-slate-500">Still reachable</dt><dd className="font-semibold tabular-nums">{c.reachable}</dd></div>
            </dl>
          </div>))}
      </div>

      <div className="card mt-6 overflow-x-auto">
        <h2 className="border-b border-slate-100 p-4 font-medium">Recent reminder history</h2>
        <table className="w-full text-left text-sm"><tbody className="divide-y divide-slate-100">
          {log.data?.items.length === 0 && <tr><td className="p-6 text-center text-slate-500">Nothing sent yet.</td></tr>}
          {log.data?.items.map((l) => (
            <tr key={l.id}><td className="px-4 py-2">{l.name || '—'}<span className="ml-2 font-mono text-xs text-slate-500">{l.prn}</span></td>
              <td className="px-4 py-2 text-slate-500">{l.campaign}</td><td className="px-4 py-2">{l.channel} · try {l.attempt}</td>
              <td className="px-4 py-2"><Badge tone={l.status === 'FAILED' ? 'red' : l.status === 'SKIPPED' ? 'slate' : 'green'}>{l.status}</Badge>{l.error && <span className="ml-2 text-xs text-slate-500">{l.error}</span>}</td>
              <td className="px-4 py-2 text-xs text-slate-500">{fmtDate(l.created_at)}</td></tr>))}
        </tbody></table>
      </div>
      {editing && <Editor initial={editing} placeholders={camps.data?.placeholders || []} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); refresh() }} />}
    </>
  )
}

function Editor({ initial, placeholders, onClose, onSaved }) {
  const toast = useToast()
  const [f, setF] = useState(initial)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const sample = { name: 'Aarav Sharma', batch: '2026', unique_link: 'https://…/update?token=…', prn: '12210000', employer: 'Acme' }
  const preview = (t) => t.replace(/\{\{\s*(\w+)\s*\}\}/g, (m, k) => sample[k] ?? m)
  async function save(e) {
    e.preventDefault(); setBusy(true); setErr(null)
    const body = { ...f, interval_hours: +f.interval_hours, max_attempts: +f.max_attempts, batch_size: +f.batch_size, deadline: f.deadline || null }
    ;['id', 'status', 'created_at', 'started_at', 'sent', 'failed', 'eligible_now', 'reachable'].forEach((k) => delete body[k])
    try { await api(f.id ? `/campaigns/${f.id}` : '/campaigns', { method: f.id ? 'PUT' : 'POST', body }); toast('Campaign saved'); onSaved() }
    catch (x) { setErr(x) } finally { setBusy(false) }
  }
  const chips = placeholders.map((p) => <code key={p} className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">{`{{${p}}}`}</code>)
  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-4" onClick={onClose}>
      <form onSubmit={save} onClick={(e) => e.stopPropagation()} className="card my-8 w-full max-w-2xl space-y-4 p-5" role="dialog" aria-label="Campaign">
        <h2 className="text-lg font-semibold">{f.id ? 'Edit campaign' : 'New campaign'}</h2>
        <ErrorBox error={err} />
        <div><label className="label" htmlFor="n">Name</label><input id="n" required className="input" value={f.name} onChange={set('name')} /></div>
        <div className="grid gap-3 sm:grid-cols-4">
          <div><label className="label" htmlFor="ch">Channel</label><select id="ch" className="input" value={f.channel} onChange={set('channel')}><option value="email">Email</option><option value="telegram">Telegram</option><option value="both">Both</option></select></div>
          <div><label className="label" htmlFor="iv">Interval (hours)</label><input id="iv" type="number" min="0.01" step="any" className="input" value={f.interval_hours} onChange={set('interval_hours')} /></div>
          <div><label className="label" htmlFor="ma">Max attempts</label><input id="ma" type="number" min="1" max="20" className="input" value={f.max_attempts} onChange={set('max_attempts')} /></div>
          <div><label className="label" htmlFor="bs">Batch size</label><input id="bs" type="number" min="1" className="input" value={f.batch_size} onChange={set('batch_size')} /></div>
        </div>
        <div><label className="label" htmlFor="dl">Submission deadline <span className="font-normal text-slate-500">(pending after this date count as overdue; blank = 14 days from now)</span></label>
          <input id="dl" type="date" className="input sm:w-48" value={f.deadline} onChange={set('deadline')} /></div>
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-slate-500">Placeholders: {chips}</div>
        {f.channel !== 'telegram' && <>
          <div><label className="label" htmlFor="es">Email subject</label><input id="es" className="input" value={f.email_subject} onChange={set('email_subject')} /></div>
          <div><label className="label" htmlFor="eb">Email body</label><textarea id="eb" rows={7} className="input font-mono" value={f.email_body} onChange={set('email_body')} /></div></>}
        {f.channel !== 'email' && <div><label className="label" htmlFor="tb">Telegram message</label><textarea id="tb" rows={3} className="input font-mono" value={f.telegram_body} onChange={set('telegram_body')} /></div>}
        <details className="rounded-lg bg-slate-50 p-3 text-sm"><summary className="cursor-pointer font-medium">Preview with sample data</summary>
          <pre className="mt-2 whitespace-pre-wrap font-sans text-slate-700">{f.channel !== 'telegram' ? preview(f.email_subject) + '\n\n' + preview(f.email_body) : preview(f.telegram_body)}</pre></details>
        <div className="flex justify-end gap-2"><button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={busy}>{busy && <Loader2 className="h-4 w-4 animate-spin" />}Save</button></div>
      </form>
    </div>
  )
}
