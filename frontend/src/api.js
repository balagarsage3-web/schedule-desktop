import { reactive } from 'vue'

function readToken() {
  try { return localStorage.getItem('token') || '' } catch { return '' }
}

export const auth = reactive({ token: readToken(), login: '' })

export function setToken(token, login = '') {
  auth.token = token
  auth.login = login
  try { token ? localStorage.setItem('token', token) : localStorage.removeItem('token') } catch { /* приватный режим */ }
}

export class ApiError extends Error {
  constructor(message, status, data) {
    super(message)
    this.status = status
    this.data = data
  }
}

function errorText(data, status) {
  if (!data) return `Ошибка ${status}`
  if (typeof data.detail === 'string') return data.detail
  if (Array.isArray(data.detail)) {
    return data.detail.map(d => {
      const field = (d.loc || []).filter(x => x !== 'body').join('.')
      return (field ? field + ': ' : '') + String(d.msg || '').replace(/^Value error, /, '')
    }).join('; ')
  }
  return `Ошибка ${status}`
}

export async function api(path, { method = 'GET', body, params, form, raw } = {}) {
  let url = '/api' + path
  if (params) {
    const q = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') q.set(k, v) })
    const s = q.toString()
    if (s) url += '?' + s
  }
  const headers = {}
  if (auth.token) headers.Authorization = 'Bearer ' + auth.token
  let payload
  if (form) payload = form
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  const res = await fetch(url, { method, headers, body: payload })
  if (res.status === 401 && !path.startsWith('/auth/login') && !path.startsWith('/public')) {
    setToken('')
    location.assign('/login')
    throw new ApiError('Требуется вход', 401)
  }
  if (raw) {
    if (!res.ok) {
      let data = null
      try { data = await res.json() } catch { /* не JSON */ }
      throw new ApiError(errorText(data, res.status), res.status, data)
    }
    return res
  }
  let data = null
  const text = await res.text()
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  if (!res.ok) throw new ApiError(errorText(data, res.status), res.status, data)
  return data
}

/** Скачивание файла с авторизацией (без токена в адресе). */
export async function download(path, params, fallbackName) {
  const res = await api(path, { params, raw: true })
  const cd = res.headers.get('Content-Disposition') || ''
  const m = cd.match(/filename\*=UTF-8''([^;]+)/)
  const name = m ? decodeURIComponent(m[1]) : fallbackName
  const blob = await res.blob()
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}
