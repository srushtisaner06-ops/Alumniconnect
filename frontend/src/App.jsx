import React from 'react'
import { Navigate, NavLink, Outlet, Route, Routes, useNavigate, useLocation } from 'react-router-dom'
import { BarChart3, GraduationCap, LayoutDashboard, LogOut, Send, Upload, Users, Building2 } from 'lucide-react'
import { getToken, setToken } from './api'
import { ToastProvider } from './ui.jsx'
import Login from './pages/Login.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Alumni from './pages/Alumni.jsx'
import Import from './pages/Import.jsx'
import Campaigns from './pages/Campaigns.jsx'
import Reports from './pages/Reports.jsx'
import UpdateForm from './pages/UpdateForm.jsx'
import Success from './pages/Success.jsx'

const nav = [
  { to: '/dashboard', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/dashboard/alumni', label: 'Alumni directory', icon: Users, end: true },
  { to: '/dashboard/alumni/import', label: 'Import records', icon: Upload },
  { to: '/dashboard/campaigns', label: 'Reminders', icon: Send },
  { to: '/dashboard/reports', label: 'Reports & exports', icon: BarChart3 },
]
const titles = [
  ['/dashboard/alumni/import', 'Import records'],
  ['/dashboard/campaigns', 'Reminders'],
  ['/dashboard/reports', 'Reports & exports'],
  ['/dashboard/alumni', 'Alumni directory'],
  ['/dashboard', 'Overview'],
]

function Shell() {
  const navigate = useNavigate()
  const location = useLocation()
  if (!getToken()) return <Navigate to="/login" replace />
  const currentTitle = titles.find(([path]) => location.pathname === path || (path !== '/dashboard' && location.pathname.startsWith(path)))?.[1] || 'AlumniConnect'
  const link = ({ isActive }) => `group flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition ${isActive ? 'bg-blue-50 text-blue-800' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'}`
  return (
    <div className="min-h-screen bg-slate-50 md:flex">
      <aside className="z-20 border-b border-slate-200 bg-white md:sticky md:top-0 md:flex md:h-screen md:w-64 md:shrink-0 md:flex-col md:border-b-0 md:border-r">
        <div className="flex items-center gap-3 border-b border-slate-100 px-5 py-5">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-800 text-white"><GraduationCap className="h-6 w-6" /></div>
          <div className="min-w-0"><div className="text-base font-bold tracking-tight text-slate-900">AlumniConnect</div><div className="mt-0.5 text-xs text-slate-500">Institutional records</div></div>
        </div>
        <div className="hidden px-5 pb-2 pt-6 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400 md:block">Workspace</div>
        <nav className="flex gap-1 overflow-x-auto p-3 md:flex-col md:overflow-visible md:px-3" aria-label="Main navigation">
          {nav.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className={link}><Icon className="h-[18px] w-[18px] shrink-0" /><span className="whitespace-nowrap">{label}</span></NavLink>
          ))}
        </nav>
        <div className="mt-auto hidden border-t border-slate-100 p-4 md:block">
          <div className="mb-3 flex items-center gap-3 rounded-lg bg-slate-50 p-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-blue-100 text-sm font-semibold text-blue-800"><Building2 className="h-4 w-4" /></div>
            <div className="min-w-0"><div className="text-sm font-medium text-slate-800">Faculty workspace</div><div className="text-xs text-slate-500">Alumni administration</div></div>
          </div>
          <button className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-slate-600 transition hover:bg-slate-50 hover:text-slate-900" onClick={() => { setToken(null); navigate('/login') }}><LogOut className="h-[18px] w-[18px]" />Sign out</button>
        </div>
        <button className="flex items-center gap-2 px-4 pb-3 text-sm font-medium text-slate-600 md:hidden" onClick={() => { setToken(null); navigate('/login') }}><LogOut className="h-4 w-4" />Sign out</button>
      </aside>
      <main className="min-w-0 flex-1">
        <header className="sticky top-0 z-10 hidden h-[65px] items-center justify-between border-b border-slate-200 bg-white/95 px-6 backdrop-blur md:flex lg:px-9">
          <div className="text-sm text-slate-500">Administration <span className="mx-2 text-slate-300">/</span><span className="font-medium text-slate-800">{currentTitle}</span></div>
          <div className="text-xs text-slate-500">Alumni data management</div>
        </header>
        <div className="mx-auto max-w-[1440px] p-4 sm:p-6 lg:p-9"><Outlet /></div>
      </main>
    </div>
  )
}

export default function App() {
  return (
    <ToastProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/update" element={<UpdateForm />} />
        <Route path="/submission-success" element={<Success />} />
        <Route path="/dashboard" element={<Shell />}>
          <Route index element={<Dashboard />} />
          <Route path="alumni" element={<Alumni />} />
          <Route path="alumni/import" element={<Import />} />
          <Route path="campaigns" element={<Campaigns />} />
          <Route path="reports" element={<Reports />} />
        </Route>
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </ToastProvider>
  )
}
