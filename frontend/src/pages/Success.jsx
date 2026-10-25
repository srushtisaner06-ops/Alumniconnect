import React from 'react'
import { CheckCircle2 } from 'lucide-react'
export default function Success() {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="card max-w-md p-8 text-center">
        <CheckCircle2 className="mx-auto h-12 w-12 text-emerald-600" />
        <h1 className="mt-4 text-xl font-semibold">Thank you!</h1>
        <p className="mt-2 text-sm text-slate-600">Your details have been recorded and you will not receive further reminders. You can reopen your personal link at any time to update them.</p>
      </div>
    </div>
  )
}
