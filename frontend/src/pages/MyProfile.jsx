import React from 'react'
import { api, getSession } from '../api'
import { ErrorBox, PageHeader, Spinner, useLoad, useToast } from '../ui.jsx'

const LEVELS = [
  ['PRIVATE', 'Private', 'Only you and the department staff can see your profile.'],
  ['ALUMNI_ONLY', 'Alumni only', 'Other alumni can see your name, batch and organisations.'],
  ['INSTITUTION', 'Institution', 'Alumni and current students can see your name, batch and organisations.'],
  ['PUBLIC', 'Public', 'Anyone, signed in or not, can see your name, batch and organisations.'],
]

export default function MyProfile() {
  const toast = useToast()
  const s = getSession()
  const isAlumnus = s?.role === 'ALUMNI'
  const vis = useLoad(() => (isAlumnus ? api('/profile/me/visibility') : Promise.resolve(null)))
  const me = useLoad(() => (isAlumnus ? api('/profile/me') : Promise.resolve(null)))
  async function choose(level) {
    try { await api('/profile/me/visibility', { method: 'PUT', body: { level } }); toast('Privacy updated'); vis.reload() } catch (e) { toast(e.message, 'err') }
  }
  return (
    <>
      <PageHeader eyebrow={s?.role} title={s?.full_name || s?.email || 'My profile'} sub={isAlumnus ? 'Choose who can see your profile. Your contact details and salary are never shown to other members.' : 'Your account is set up. Alumni profiles that have been shared with students will appear here as the directory is released.'} />
      {isAlumnus && (<>
        {(vis.loading || me.loading) && <Spinner />}<ErrorBox error={vis.error || me.error} />
        {me.data && <p className="mb-8 text-sm text-slate-600">{me.data.name} · Batch of {me.data.graduation_year} · PRN {me.data.prn}</p>}
        {vis.data && <div className="grid gap-4 sm:grid-cols-2">{LEVELS.map(([v, label, text]) => (
          <button key={v} onClick={() => choose(v)} className={`border-l-4 px-4 py-3 text-left transition ${vis.data.level === v ? 'border-indigo-600 bg-indigo-50' : 'border-slate-200 hover:border-sky-300'}`}>
            <div className="font-medium">{label}{vis.data.level === v && ' · current'}</div><div className="text-sm text-slate-500">{text}</div></button>))}</div>}
      </>)}
    </>
  )
}
