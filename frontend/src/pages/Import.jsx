import React, { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, Download, FileSpreadsheet, Loader2, XCircle } from 'lucide-react'
import { api, download } from '../api'
import { Badge, CATEGORIES, CATEGORY_KEYS, ErrorBox, PageHeader, useLoad, useToast } from '../ui.jsx'

const FILE_NAMES = { PLACEMENT: 'placement_template.xlsx', HIGHER_STUDIES: 'higher_studies_template.xlsx', ENTREPRENEURSHIP: 'entrepreneurship_template.xlsx' }

export default function Import() {
  const toast = useToast()
  const nav = useNavigate()
  const inputRef = useRef()
  const [file, setFile] = useState(null)
  const [year, setYear] = useState('')
  const [category, setCategory] = useState('')   // '' = detect from the file's columns
  const [rep, setRep] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [replace, setReplace] = useState(false)
  const [skip, setSkip] = useState(false)
  const formats = useLoad(() => api('/import/formats'), [])

  const formFor = (f, extra = {}) => {
    const fd = new FormData(); fd.append('file', f)
    if (year) fd.append('graduation_year', year)
    if (category) fd.append('category', category)
    Object.entries(extra).forEach(([k, v]) => fd.append(k, v)); return fd
  }

  async function validate(f = file, y = year, cat = category) {
    if (!f) return
    setBusy(true); setErr(null); setRep(null)
    try {
      const fd = new FormData(); fd.append('file', f); if (y) fd.append('graduation_year', y); if (cat) fd.append('category', cat)
      setRep(await api('/import/validate', { method: 'POST', form: fd }))
    } catch (e) { setErr(e) } finally { setBusy(false) }
  }
  async function commit() {
    if (replace && !window.confirm('This permanently removes ALL existing alumni (placement, higher studies and entrepreneurship), submissions and reminder history before importing. Continue?')) return
    setBusy(true); setErr(null)
    try {
      const r = await api('/import', { method: 'POST', form: formFor(file, { replace, skip_invalid: skip }) })
      toast(`Imported ${r.unique_students} ${r.category_label} record${r.unique_students === 1 ? '' : 's'} (${r.added} new student${r.added === 1 ? '' : 's'}, ${r.updated} updated).`)
      nav('/dashboard/alumni')
    } catch (e) { setErr(e); if (e.detail?.report) setRep(e.detail.report) } finally { setBusy(false) }
  }
  const hasRowErrors = rep && rep.errors.length > 0 && rep.missing_columns.length === 0
  const canImport = rep && rep.category && rep.missing_columns.length === 0 && rep.graduation_year && rep.summary?.unique_students > 0 && (rep.ok || (skip && rep.summary.valid_rows > 0))
  const cat = rep?.category ? CATEGORIES[rep.category] : null

  return (
    <>
      <PageHeader title="Import records" sub="Upload a Placement (4.6.1), Higher Studies (4.6.2) or Entrepreneurship (4.6.3) sheet in the reference format">
        {CATEGORY_KEYS.map((k) => (
          <button key={k} className="btn-ghost" onClick={() => download(`/import/template?category=${k}`, FILE_NAMES[k]).catch((e) => toast(e.message, 'err'))}>
            <Download className="h-4 w-4" />{CATEGORIES[k].label} template</button>))}
      </PageHeader>
      <div className="card p-5">
        <div className="grid gap-4 sm:grid-cols-[1fr_200px_220px]">
          <div>
            <label className="label" htmlFor="file">File (.xlsx or .csv)</label>
            <div className="flex items-center gap-3 rounded-lg border-2 border-dashed border-slate-300 p-4">
              <FileSpreadsheet className="h-8 w-8 text-slate-400" />
              <div className="min-w-0 flex-1 truncate text-sm">{file ? file.name : 'No file chosen'}</div>
              <input id="file" ref={inputRef} type="file" accept=".xlsx,.xlsm,.csv" className="sr-only" onChange={(e) => { const f = e.target.files[0]; setFile(f); validate(f) }} />
              <button className="btn-ghost" onClick={() => inputRef.current.click()}>Choose file</button>
            </div>
          </div>
          <div>
            <label className="label" htmlFor="category">Record type</label>
            <select id="category" className="input" value={category} onChange={(e) => { setCategory(e.target.value); validate(file, year, e.target.value) }}>
              <option value="">Detect automatically</option>
              {CATEGORY_KEYS.map((k) => <option key={k} value={k}>{CATEGORIES[k].label} ({CATEGORIES[k].table})</option>)}
            </select>
          </div>
          <div>
            <label className="label" htmlFor="year">Graduation year</label>
            <input id="year" className="input" inputMode="numeric" placeholder="auto from 'AY: 2025-26'" value={year}
              onChange={(e) => setYear(e.target.value.replace(/\D/g, '').slice(0, 4))} onBlur={() => year.length === 4 && validate()} />
          </div>
        </div>
      </div>
      <div className="mt-4"><ErrorBox error={err} /></div>
      {busy && <p className="mt-4 flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" />Checking file…</p>}

      {!rep && !busy && formats.data && (
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          {formats.data.formats.map((f) => (
            <div key={f.category} className="card p-4">
              <h2 className="mb-1 flex items-center gap-2 text-sm font-medium">{f.table}<Badge tone={CATEGORIES[f.category].tone}>{f.label}</Badge></h2>
              <p className="mb-2 text-xs text-slate-500">Expected columns, in any order:</p>
              <ol className="list-decimal space-y-0.5 pl-5 text-xs text-slate-700">{f.columns.map((c) => <li key={c}>{c}</li>)}</ol>
            </div>))}
        </div>)}

      {rep && (
        <div className="mt-4 space-y-4">
          <div className="card p-5">
            <h2 className="mb-3 flex flex-wrap items-center gap-2 font-medium">Format check
              {cat && <Badge tone={cat.tone}>{rep.detected ? 'Detected' : 'Selected'}: {cat.label}</Badge>}
              {rep.missing_columns.length === 0 ? <Badge tone="green">Matches reference</Badge> : <Badge tone="red">Does not match</Badge>}</h2>
            <ul className="grid gap-1 text-sm sm:grid-cols-2">
              {rep.expected_columns.map((c) => {
                const missing = rep.missing_columns.includes(c)
                return <li key={c} className="flex items-center gap-2">{missing ? <XCircle className="h-4 w-4 text-red-600" /> : <CheckCircle2 className="h-4 w-4 text-emerald-600" />}<span className={missing ? 'text-red-700' : ''}>{c}</span></li>
              })}
            </ul>
            {rep.extra_columns.length > 0 && <p className="mt-3 text-xs text-slate-500">Ignored extra columns: {rep.extra_columns.join(', ')}</p>}
          </div>

          {rep.summary && (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
              {[['Rows read', rep.summary.rows], ['Valid rows', rep.summary.valid_rows], ['Unique students', rep.summary.unique_students], ['Already in system', rep.already_in_database ?? 0], ['Graduation year', rep.graduation_year ?? '—']].map(([l, v]) => (
                <div key={l} className="card p-3"><div className="text-xs text-slate-500">{l}</div><div className="text-xl font-semibold tabular-nums">{v}</div></div>))}
            </div>)}

          {rep.errors.length > 0 && (
            <div className="card border-red-200 p-5">
              <h2 className="mb-2 flex items-center gap-2 font-medium text-red-700"><XCircle className="h-4 w-4" />{rep.errors.length} problem{rep.errors.length > 1 ? 's' : ''} found</h2>
              <div className="max-h-64 overflow-y-auto"><table className="w-full text-left text-sm"><thead className="text-xs text-slate-500"><tr><th className="py-1 pr-3">Row</th><th className="pr-3">Column</th><th>Problem</th></tr></thead>
                <tbody>{rep.errors.slice(0, 100).map((e, i) => <tr key={i} className="border-t border-slate-100"><td className="py-1 pr-3 tabular-nums">{e.row ?? '—'}</td><td className="pr-3">{e.column ?? '—'}</td><td>{e.message}</td></tr>)}</tbody></table></div>
              {rep.errors.length > 100 && <p className="mt-2 text-xs text-slate-500">Showing first 100.</p>}
            </div>)}

          {rep.warnings.length > 0 && (
            <div className="card border-amber-200 p-5">
              <h2 className="mb-2 flex items-center gap-2 font-medium text-amber-700"><AlertTriangle className="h-4 w-4" />{rep.warnings.length} note{rep.warnings.length > 1 ? 's' : ''} (not blocking)</h2>
              <ul className="max-h-40 space-y-1 overflow-y-auto text-sm text-slate-700">{rep.warnings.map((w, i) => <li key={i}>{w.row ? `Row ${w.row}: ` : ''}{w.message}</li>)}</ul>
            </div>)}

          {rep.preview?.length > 0 && (
            <div className="card overflow-x-auto p-5"><h2 className="mb-2 font-medium">Preview</h2>
              <table className="w-full text-left text-sm"><tbody>{rep.preview.map((p) => <tr key={p.prn} className="border-t border-slate-100"><td className="py-1 pr-3 font-mono text-xs">{p.prn}</td><td className="pr-3">{p.name}</td><td className="pr-3 text-slate-500">{p.details}</td></tr>)}</tbody></table></div>)}

          <div className="card space-y-3 p-5">
            {hasRowErrors && <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-0.5" checked={skip} onChange={(e) => setSkip(e.target.checked)} />
              <span>Skip the invalid rows and import the valid ones. <span className="text-slate-500">Without this, the whole file is rejected.</span></span></label>}
            <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-0.5" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
              <span>Replace all existing data. <span className="text-slate-500">This clears every category, not just {cat?.label?.toLowerCase() || 'this one'}. Otherwise records are merged by PRN: contact details are updated and new {cat?.label?.toLowerCase() || ''} records added.</span></span></label>
            <button className="btn-primary" disabled={!canImport || busy} onClick={commit}>{busy && <Loader2 className="h-4 w-4 animate-spin" />}Import {rep.summary?.unique_students ?? 0} {cat?.label?.toLowerCase() ?? ''} student{rep.summary?.unique_students === 1 ? '' : 's'}</button>
          </div>
        </div>)}
    </>
  )
}
