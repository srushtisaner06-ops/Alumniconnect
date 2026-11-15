import React from 'react'

// Phase 2: tiny dependency-free horizontal bar chart (no chart library needed).
// rows: [{ label, value, note? }]. `max` fixes the scale (defaults to the largest value).
export function BarChart({ rows, max, empty = 'No data yet.', unit = '' }) {
  if (!rows || rows.length === 0 || rows.every((r) => !r.value)) return <p className="text-sm text-slate-500">{empty}</p>
  const m = max ?? Math.max(1, ...rows.map((r) => r.value))
  return (
    <ul className="space-y-3" role="list">
      {rows.map((r) => (
        <li key={r.label}>
          <div className="mb-1 flex justify-between gap-3 text-sm">
            <span className="min-w-0 truncate">{r.label}</span>
            <span className="shrink-0 tabular-nums text-slate-600">{r.value}{unit}{r.note ? <span className="ml-1 text-xs text-slate-400">{r.note}</span> : null}</span>
          </div>
          <div className="h-2.5 w-full overflow-hidden rounded-full bg-slate-200/70" role="img" aria-label={`${r.label}: ${r.value}`}>
            <div className="h-full rounded-full bg-gradient-to-r from-indigo-400 to-blue-700" style={{ width: `${Math.max(2, (100 * r.value) / m)}%` }} />
          </div>
        </li>))}
    </ul>
  )
}
