import { reactive } from 'vue'
import { api } from './api'

export const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
export const WEEKDAYS_FULL = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']

function lsGet(k) { try { return localStorage.getItem(k) } catch { return null } }
function lsSet(k, v) { try { localStorage.setItem(k, v) } catch { /* ignore */ } }

export const store = reactive({
  terms: [],
  termId: Number(lsGet('termId')) || null,
  versions: [],
  versionId: Number(lsGet('versionId')) || null,
  jobId: null,
  toasts: [],
})

export function setTerm(id) {
  store.termId = id
  lsSet('termId', id || '')
}

export function setVersion(id) {
  store.versionId = id
  lsSet('versionId', id || '')
}

export async function loadTerms() {
  store.terms = await api('/terms')
  if (!store.terms.find(t => t.id === store.termId)) setTerm(store.terms[0]?.id || null)
  return store.terms
}

export async function loadVersions() {
  if (!store.termId) { store.versions = []; return [] }
  store.versions = await api('/versions', { params: { term_id: store.termId } })
  if (!store.versions.find(v => v.id === store.versionId)) setVersion(store.versions[0]?.id || null)
  return store.versions
}

let toastId = 0
export function toast(text, kind = 'ok', ms = 3500) {
  const id = ++toastId
  store.toasts.push({ id, text, kind })
  setTimeout(() => { store.toasts = store.toasts.filter(t => t.id !== id) }, ms)
}

// --- даты ------------------------------------------------------------------
export function parseDate(s) {
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, m - 1, d)
}
export function iso(d) {
  const p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}
export function addDays(d, n) {
  const x = new Date(d)
  x.setDate(x.getDate() + n)
  return x
}
export function mondayOf(d) {
  const x = new Date(d)
  const wd = (x.getDay() + 6) % 7
  x.setDate(x.getDate() - wd)
  return x
}
export function fmt(d) {
  if (typeof d === 'string') d = parseDate(d)
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })
}
export function fmtFull(d) {
  if (typeof d === 'string') d = parseDate(d)
  return d.toLocaleDateString('ru-RU')
}
