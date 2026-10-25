const KEY = 'ac_token'
export const getToken = () => localStorage.getItem(KEY)
export const setToken = (t) => (t ? localStorage.setItem(KEY, t) : localStorage.removeItem(KEY))

function message(detail, fallback) {
  if (!detail) return fallback
  if (typeof detail === 'string') return detail
  if (detail.message) return detail.message
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join('; ')
  return fallback
}

export class ApiError extends Error {
  constructor(msg, status, detail) { super(msg); this.status = status; this.detail = detail }
}

export async function api(path, { method = 'GET', body, form, auth = true } = {}) {
  const headers = {}
  if (auth && getToken()) headers.Authorization = 'Bearer ' + getToken()
  let payload
  if (form) payload = form
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body) }
  let res
  try { res = await fetch('/api' + path, { method, headers, body: payload }) }
  catch { throw new ApiError('Cannot reach the server. Is the backend running?', 0) }
  if (res.status === 401 && auth) { setToken(null); window.location.href = '/login'; throw new ApiError('Session expired', 401) }
  const data = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(message(data?.detail, `Request failed (${res.status})`), res.status, data?.detail)
  return data
}

export async function download(path, filename) {
  const res = await fetch('/api' + path, { headers: { Authorization: 'Bearer ' + getToken() } })
  if (!res.ok) throw new ApiError('Download failed', res.status)
  const url = URL.createObjectURL(await res.blob())
  const a = Object.assign(document.createElement('a'), { href: url, download: filename })
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
}
