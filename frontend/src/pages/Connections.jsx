import React, { useState } from 'react'
import { Check, Link2, UserMinus, X } from 'lucide-react'
import { api } from '../api'
import { Badge, ErrorBox, PageHeader, Spinner, fmtDate, useLoad, useToast } from '../ui.jsx'

const TABS = [['received', 'Requests received'], ['sent', 'Requests sent'], ['connections', 'My connections']]
const EMPTY = {
  received: 'No requests waiting. When another alumnus asks to connect, it appears here.',
  sent: 'You have not sent any requests. Open the Alumni network and press Connect on a profile.',
  connections: 'No connections yet. They appear here once a request is accepted.',
}

// Tell the menu badge (App.jsx) that the number of waiting requests may have changed.
export const connectionsChanged = () => window.dispatchEvent(new Event('connections-changed'))

function Person({ p }) {
  const links = p.profile_visible ? [['LinkedIn', p.profile.linkedin_url], ['GitHub', p.profile.github_url], ['Portfolio', p.profile.portfolio_url]].filter(([, u]) => u) : []
  const place = p.profile_visible ? [p.profile.city, p.profile.country].filter(Boolean).join(', ') : ''
  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-baseline gap-x-3"><h3 className="text-lg font-semibold">{p.name}</h3><span className="text-xs text-slate-500">Batch of {p.graduation_year}</span></div>
      {p.profile_visible
        ? <>
          {p.profile.headline && <p className="mt-0.5 text-sm text-slate-600">{p.profile.headline}</p>}
          <p className="mt-1 text-sm text-slate-500">{[p.organisations.slice(0, 2).join(' · '), p.profile.designation, place].filter(Boolean).join(' — ')}</p>
          {links.length > 0 && <p className="mt-1 flex gap-4 text-sm">{links.map(([n, u]) => <a key={n} className="text-indigo-700 underline" href={u} target="_blank" rel="noopener noreferrer">{n}</a>)}</p>}
        </>
        : <p className="mt-0.5 text-sm text-slate-400">This alumnus keeps the rest of their profile private.</p>}
    </div>
  )
}

export default function Connections() {
  const toast = useToast()
  const { data, error, loading, reload } = useLoad(() => api('/connections'))
  const [tab, setTab] = useState('received')
  const [busy, setBusy] = useState(null)

  async function act(id, verb) {
    if (verb === 'remove' && !window.confirm('Remove this connection? You can send a new request later.')) return
    setBusy(id)
    try {
      if (verb === 'accept' || verb === 'reject') await api(`/connections/${id}/${verb}`, { method: 'POST' })
      else await api(`/connections/${id}`, { method: 'DELETE' })
      toast({ accept: 'Connected', reject: 'Request declined', withdraw: 'Request withdrawn', remove: 'Connection removed' }[verb])
      connectionsChanged(); reload()
    } catch (e) { toast(e.message, 'err') } finally { setBusy(null) }
  }

  const rowActions = (r) => {
    const b = (props) => <button className="btn-ghost" disabled={busy === r.id} {...props} />
    if (tab === 'received') return <>{b({ onClick: () => act(r.id, 'accept'), children: <><Check className="h-4 w-4" />Accept</> })}{b({ onClick: () => act(r.id, 'reject'), children: <><X className="h-4 w-4" />Reject</> })}</>
    if (tab === 'sent') return r.status === 'PENDING' ? <><Badge tone="amber">Waiting for a reply</Badge>{b({ onClick: () => act(r.id, 'withdraw'), children: 'Withdraw' })}</> : <Badge tone="slate">Declined {fmtDate(r.responded_at)}</Badge>
    return b({ onClick: () => act(r.id, 'remove'), children: <><UserMinus className="h-4 w-4" />Remove</> })
  }

  return (
    <>
      <PageHeader eyebrow="Community" title="My connections" sub="Requests from and to other alumni. Connecting shares only the profile details each person has chosen to show. Email and phone numbers are never shared." />
      <ErrorBox error={error} retry={reload} />
      {loading && !data && <Spinner />}
      {data && (
        <>
          <div className="mb-8 flex flex-wrap gap-x-6 gap-y-2 border-b border-sky-100" role="tablist">
            {TABS.map(([k, label]) => (
              <button key={k} role="tab" aria-selected={tab === k} className={`tab ${tab === k ? 'tab-on' : ''}`} onClick={() => setTab(k)}>
                {label}<span className="ml-1.5 text-xs text-slate-400">{data.counts[k]}</span>
              </button>))}
          </div>
          {data[tab].length === 0
            ? <p className="py-10 text-slate-500">{EMPTY[tab]}</p>
            : <ul className="grid gap-x-12 gap-y-8 md:grid-cols-2">
              {data[tab].map((r) => (
                <li key={r.id} className="border-t border-sky-200 pt-4">
                  <Person p={r.person} />
                  {tab === 'received' && r.message && <p className="mt-3 rounded bg-slate-100 px-3 py-2 text-sm text-slate-700">“{r.message}”</p>}
                  {tab === 'sent' && r.message && <p className="mt-2 text-xs text-slate-500">Your note: “{r.message}”</p>}
                  <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                    {rowActions(r)}
                    <span className="ml-auto flex items-center gap-1"><Link2 className="h-3 w-3" />{tab === 'connections' ? `Connected ${fmtDate(r.responded_at)}` : `Sent ${fmtDate(r.created_at)}`}</span>
                  </div>
                </li>))}
            </ul>}
        </>)}
    </>
  )
}
