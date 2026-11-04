import React, { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { CheckCircle2, AlertCircle, Loader2, X } from 'lucide-react'

export const Spinner = ({ label = 'Loading…' }) => (
  <div className="flex items-center justify-center gap-2 py-16 text-slate-500" role="status">
    <Loader2 className="h-5 w-5 animate-spin" /> {label}
  </div>
)

export const ErrorBox = ({ error, retry }) => error ? (
  <div className="my-3 flex items-start gap-3 border-l-4 border-red-400 py-1 pl-3 text-sm text-red-800" role="alert">
    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
    <div className="flex-1">{String(error.message || error)}</div>
    {retry && <button className="font-medium underline" onClick={retry}>Retry</button>}
  </div>
) : null

const tones = {
  green: 'bg-emerald-100/70 text-emerald-800', amber: 'bg-amber-100/80 text-amber-800',
  red: 'bg-red-100/80 text-red-700', slate: 'bg-slate-200/60 text-slate-600',
  indigo: 'bg-indigo-100 text-indigo-800', blue: 'bg-sky-100 text-sky-800',
}
const iconTones = { green: 'text-emerald-600', amber: 'text-amber-600', red: 'text-red-600', slate: 'text-slate-500', indigo: 'text-indigo-600', blue: 'text-sky-700' }
export const Badge = ({ tone = 'slate', children }) => (
  <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${tones[tone]}`}>{children}</span>
)

export const StatusBadge = ({ a }) =>
  a.status === 'COMPLETED' ? <Badge tone="green">Completed</Badge>
  : a.overdue ? <Badge tone="red">Overdue</Badge> : <Badge tone="amber">Pending</Badge>

// A statistic: big serif numeral set against a thin silver rule. No box.
export const Stat = ({ icon: Icon, label, value, sub, tone = 'indigo' }) => (
  <div className="relative pt-5">
    <div className="silver-rule absolute inset-x-0 top-0" />
    <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
      <Icon className={`h-4 w-4 ${iconTones[tone]}`} />{label}
    </div>
    <div className="mt-2 font-display text-5xl font-semibold tabular-nums leading-none text-slate-900">{value}</div>
    {sub && <div className="mt-2 text-xs text-slate-500">{sub}</div>}
  </div>
)

export const Progress = ({ value, tone = 'bg-gradient-to-r from-indigo-400 to-blue-700' }) => (
  <div className="silver-bg h-2 w-full overflow-hidden rounded-full opacity-90" role="progressbar" aria-valuenow={Math.round(value)} aria-valuemin={0} aria-valuemax={100}>
    <div className={`h-full rounded-full ${tone}`} style={{ width: `${Math.min(100, value)}%` }} />
  </div>
)

// Full-width hero band: big title, supporting text, actions and an illustration.
export const PageHeader = ({ title, sub, children, art, eyebrow }) => (
  <section className="full-bleed hero-band mb-12">
    <div className="mx-auto flex max-w-6xl flex-col items-center gap-6 px-5 py-10 sm:px-8 md:flex-row md:py-14">
      <div className="min-w-0 flex-1">
        {eyebrow && <span className="silver-chip">{eyebrow}</span>}
        <h1 className="mt-3 text-4xl font-semibold leading-[1.08] text-slate-900 sm:text-5xl">{title}</h1>
        {sub && <p className="mt-4 max-w-xl text-base leading-7 text-slate-600">{sub}</p>}
        {children && <div className="mt-7 flex flex-wrap items-center gap-3">{children}</div>}
      </div>
      {art && <img src={art} alt="" className="w-full max-w-sm select-none drop-shadow-xl md:w-[40%] md:max-w-md" />}
    </div>
    <div className="silver-bar" />
  </section>
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
      <div className="fixed bottom-5 right-5 z-50 flex w-80 max-w-[calc(100vw-2.5rem)] flex-col gap-2" aria-live="polite">
        {items.map((i) => (
          <div key={i.id} className={`flex items-start gap-2 rounded-full px-5 py-3 text-sm text-white shadow-2xl ${i.kind === 'ok' ? 'bg-blue-900' : 'bg-red-800'}`}>
            {i.kind === 'ok' ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-indigo-200" /> : <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />}
            <span className="flex-1">{i.msg}</span>
            <button onClick={() => setItems((x) => x.filter((t) => t.id !== i.id))} aria-label="Dismiss"><X className="h-4 w-4 opacity-70" /></button>
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
