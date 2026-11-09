import React from 'react'
import { Navigate, NavLink, Outlet, Route, Routes, useNavigate } from 'react-router-dom'
import { GraduationCap, LogOut } from 'lucide-react'
import { api, can, clearSession, getToken } from './api'
import { ToastProvider } from './ui.jsx'
import Login from './pages/Login.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Alumni from './pages/Alumni.jsx'
import Import from './pages/Import.jsx'
import Campaigns from './pages/Campaigns.jsx'
import Reports from './pages/Reports.jsx'
import UpdateForm from './pages/UpdateForm.jsx'
import Success from './pages/Success.jsx'
import Users from './pages/Users.jsx'
import AuditLog from './pages/AuditLog.jsx'
import MyProfile from './pages/MyProfile.jsx'
import { ForgotPassword, ResetPassword } from './pages/PasswordReset.jsx'

// Each entry names the permission that unlocks it. The menu only hides things; the API enforces the same permissions.
const nav = [
  { to: '/dashboard', label: 'Overview', end: true, perm: 'report.view' },
  { to: '/dashboard/alumni', label: 'Alumni directory', end: true, perm: 'alumni.read' },
  { to: '/dashboard/alumni/import', label: 'Import records', perm: 'import.run' },
  { to: '/dashboard/campaigns', label: 'Reminders', perm: 'campaign.manage' },
  { to: '/dashboard/reports', label: 'Reports', perm: 'report.view' },
  { to: '/dashboard/users', label: 'Users', perm: 'user.manage' },
  { to: '/dashboard/audit', label: 'Audit log', perm: 'audit.view' },
  { to: '/dashboard/profile', label: 'My profile', perm: null },
]
const isStaff = () => can('alumni.read')

// People without staff access (alumni, students) land on their own page instead of a dashboard they cannot use.
const Home = () => (isStaff() ? <Dashboard /> : <Navigate to="/dashboard/profile" replace />)

function Shell() {
  const navigate = useNavigate()
  if (!getToken()) return <Navigate to="/login" replace />
  const link = ({ isActive }) => `relative whitespace-nowrap py-2 text-sm font-medium transition after:absolute after:inset-x-0 after:-bottom-0.5 after:h-0.5 after:rounded-full after:transition ${isActive ? 'text-slate-900 after:bg-gradient-to-r after:from-indigo-400 after:to-blue-700' : 'text-slate-500 after:bg-transparent hover:text-slate-900 hover:after:bg-sky-300'}`
  const signOut = async () => { try { await api('/auth/logout', { method: 'POST' }) } catch { /* already gone */ } clearSession(); navigate('/login') }
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 bg-slate-50/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-8 gap-y-2 px-5 py-3 sm:px-8">
          <div className="flex items-center gap-3">
            <div className="silver-bg flex h-10 w-10 items-center justify-center rounded-full p-0.5 shadow-md">
              <div className="flex h-full w-full items-center justify-center rounded-full bg-gradient-to-br from-blue-700 to-blue-900 text-white"><GraduationCap className="h-5 w-5" /></div>
            </div>
            <div className="font-display text-xl font-semibold tracking-tight text-slate-900">Alumni<span className="text-indigo-600">Connect</span></div>
          </div>
          <nav className="order-3 flex w-full gap-7 overflow-x-auto pb-1 md:order-none md:w-auto md:flex-1 md:justify-center md:overflow-visible md:pb-0" aria-label="Main navigation">
            {nav.filter((n) => !n.perm || can(n.perm)).map(({ to, label, end }) => <NavLink key={to} to={to} end={end} className={link}>{label}</NavLink>)}
          </nav>
          <button className="ml-auto inline-flex items-center gap-2 text-sm font-medium text-slate-500 transition hover:text-slate-900 md:ml-0" onClick={signOut}><LogOut className="h-4 w-4" />Sign out</button>
        </div>
        <div className="silver-bar" />
      </header>
      <main className="flex-1"><div className="mx-auto max-w-6xl px-5 pb-20 sm:px-8"><Outlet /></div></main>
      <footer className="relative">
        <div className="silver-bar" />
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-5 py-8 text-sm text-slate-500 sm:px-8">
          <div className="font-display text-lg text-slate-700">Alumni<span className="text-indigo-600">Connect</span></div>
          <div>Institutional alumni records · placement, higher studies &amp; entrepreneurship</div>
        </div>
      </footer>
    </div>
  )
}

export default function App() {
  return (
    <ToastProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="/update" element={<UpdateForm />} />
        <Route path="/submission-success" element={<Success />} />
        <Route path="/dashboard" element={<Shell />}>
          <Route index element={<Home />} />
          <Route path="profile" element={<MyProfile />} />
          <Route path="users" element={<Users />} />
          <Route path="audit" element={<AuditLog />} />
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
