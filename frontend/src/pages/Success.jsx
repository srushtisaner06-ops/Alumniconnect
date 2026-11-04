import React from 'react'
export default function Success() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-6 text-center">
      <img src="/img/success.svg" alt="" className="h-56 w-auto drop-shadow-xl" />
      <span className="silver-chip mt-6">All done</span>
      <h1 className="mt-4 text-5xl font-semibold text-slate-900">Thank you!</h1>
      <div className="silver-bar mt-5 w-28" />
      <p className="mt-5 max-w-md text-base leading-7 text-slate-600">Your details have been recorded and you will not receive further reminders. You can reopen your personal link at any time to update them.</p>
    </div>
  )
}
