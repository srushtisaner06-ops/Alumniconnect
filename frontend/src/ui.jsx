import React, { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { CheckCircle2, AlertCircle, Loader2, X } from 'lucide-react'

export const Spinner = ({ label = 'Loading…' }) => (
  <div className="flex items-center justify-center gap-2 py-16 text-slate-500" role="status">
    <Loader2 className="h-5 w-5 animate-spin" /> {label}
  </div>
)

export const ErrorBox = ({ error, retry }) => error ? (
  <div className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">
    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
    <div className="flex-1">{String(error.message || error)}</div>
    {retry && <button className="font-medium underline" onClick={retry}>Retry</button>}
  </div>
) : null

const tones = {
  green: 'bg-emerald-50 text-emerald-700 ring-emerald-200', amber: 'bg-amber-50 text-amber-700 ring-amber-200',
  red: 'bg-red-50 text-red-700 ring-red-200', slate: 'bg-slate-100 text-slate-600 ring-slate-200',
  indigo: 'bg-indigo-50 text-indigo-700 ring-indigo-200', blue: 'bg-sky-50 text-sky-700 ring-sky-200',
}
export const Badge = ({ tone = 'slate', children }) => (
  <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${tones[tone]}`}>{children}</span>
)

export const StatusBadge = ({ a }) =>
  a.status === 'COMPLETED' ? <Badge tone="green">Completed</Badge>
  : a.overdue ? <Badge tone="red">Overdue</Badge> : <Badge tone="amber">Pending</Badge>

export const Stat = ({ icon: Icon, label, value, sub, tone = 'indigo' }) => (
  <div className="card p-4">
    <div className="flex items-center gap-3">
      <div className={`rounded-lg p-2 ring-1 ring-inset ${tones[tone]}`}><Icon className="h-5 w-5" /></div>
      <div className="min-w-0">
        <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
        <div className="text-2xl font-semibold tabular-nums">{value}</div>
      </div>
    </div>
    {sub && <div className="mt-2 text-xs text-slate-500">{sub}</div>}
  </div>
)

export const Progress = ({ value, tone = 'bg-indigo-600' }) => (
  <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100" role="progressbar" aria-valuenow={Math.round(value)} aria-valuemin={0} aria-valuemax={100}>
    <div className={`h-full rounded-full ${tone}`} style={{ width: `${Math.min(100, value)}%` }} />
  </div>
)

export const PageHeader = ({ title, sub, children }) => (
  <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
    <div><h1 className="text-2xl font-semibold">{title}</h1>{sub && <p className="mt-1 text-sm text-slate-500">{sub}</p>}</div>
    <div className="flex flex-wrap gap-2">{children}</div>
  </div>
)

// ---- toasts
const ToastCtx = createContext(() => {})
export const useToast = () => useContext(ToastCtx)
export function ToastProvider({ children }) {
  const [items, setItems] = useState([])
  const push = useCallback((msg, kind = 'ok') => {
    const id = Math.random()
    setItems((x) => [...x, { id, msg, kind }])
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), 4500)
  }, [])
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2" aria-live="polite">
        {items.map((i) => (
          <div key={i.id} className={`flex items-start gap-2 rounded-lg border bg-white p-3 text-sm shadow-lg ${i.kind === 'ok' ? 'border-emerald-200' : 'border-red-200'}`}>
            {i.kind === 'ok' ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <AlertCircle className="h-4 w-4 text-red-600" />}
            <span className="flex-1">{i.msg}</span>
            <button onClick={() => setItems((x) => x.filter((t) => t.id !== i.id))} aria-label="Dismiss"><X className="h-4 w-4 text-slate-400" /></button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}

export function useLoad(fn, deps = []) {
  const [state, set] = useState({ data: null, error: null, loading: true })
  const run = useCallback(() => {
    set((s) => ({ ...s, loading: true, error: null }))
    fn().then((data) => set({ data, error: null, loading: false })).catch((error) => set({ data: null, error, loading: false }))
  }, deps) // eslint-disable-line
  useEffect(run, [run])
  return { ...state, reload: run }
}

export const fmtDate = (s) => (s ? new Date(s.replace(' ', 'T') + (s.includes('T') ? '' : 'Z')).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : '—')
export const CAREER = { EMPLOYMENT: 'Placement', HIGHER_STUDIES: 'Higher studies', ENTREPRENEURSHIP: 'Entrepreneurship' }

// The three record categories (placement, higher studies, entrepreneurship) used across the app.
export const CATEGORIES = {
  PLACEMENT: { label: 'Placement', tone: 'indigo', table: 'Table 4.6.1' },
  HIGHER_STUDIES: { label: 'Higher studies', tone: 'blue', table: 'Table 4.6.2' },
  ENTREPRENEURSHIP: { label: 'Entrepreneurship', tone: 'green', table: 'Table 4.6.3' },
}
export const CATEGORY_KEYS = Object.keys(CATEGORIES)

export const CategoryBadges = ({ categories = [] }) => categories.length === 0 ? <span className="text-slate-400">—</span> : (
  <span className="flex flex-wrap gap-1">{categories.map((c) => <Badge key={c} tone={CATEGORIES[c]?.tone}>{CATEGORIES[c]?.label || c}</Badge>)}</span>
)
