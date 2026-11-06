<template>
  <div v-if="!store.versions.length && loaded" class="card empty">
    Расписание ещё не составлено. <router-link to="/generate">Перейти к генерации</router-link>
  </div>
  <div v-else-if="ctx">
    <div class="card toolbar">
      <div class="row">
        <label class="field"><span>Версия</span>
          <select :value="store.versionId" @change="pickVersion(Number($event.target.value))">
            <option v-for="v in store.versions" :key="v.id" :value="v.id">№{{ v.number }} · {{ v.name }}</option>
          </select>
        </label>
        <div class="field"><span>Показать</span>
          <div class="seg">
            <button v-for="m in modes" :key="m.key" :class="{ active: mode === m.key }" @click="setMode(m.key)">{{ m.label }}</button>
          </div>
        </div>
        <label class="field"><span>{{ modes.find(m => m.key === mode).label }}</span>
          <select v-model.number="entityId">
            <option v-for="e in entities" :key="e.id" :value="e.id">{{ e.name }}</option>
          </select>
        </label>
        <div class="field"><span>Неделя</span>
          <div class="row week">
            <button class="sm" aria-label="Предыдущая неделя" @click="shift(-7)">‹</button>
            <input type="date" :value="iso(weekStart)" @change="goto($event.target.value)" />
            <button class="sm" aria-label="Следующая неделя" @click="shift(7)">›</button>
          </div>
        </div>
      </div>
      <div class="row sub">
        <label class="check"><input v-model="series" type="checkbox" /> Переносить пару во всех следующих неделях</label>
        <span class="spacer" />
        <span v-if="weekConflicts" class="badge bad">Конфликтов на неделе: {{ weekConflicts }}</span>
        <span class="muted small">{{ fmt(weekStart) }} – {{ fmt(addDays(weekStart, ctx.term.days_per_week - 1)) }}, пар: {{ shown.length }}</span>
        <button class="sm" @click="publish">{{ version?.public_token ? 'Публичная ссылка' : 'Опубликовать ссылку' }}</button>
      </div>
    </div>

    <WeekGrid :days="days" :slots="ctx.slots" :lessons="shown" :mode="mode" :non-working="ctx.non_working"
              editable :check="checkCell" @drop="onDrop" @open="openLesson" />
    <p class="muted small legend">
      <span class="sw t-lec" /> лекция <span class="sw t-pr" /> практика <span class="sw t-lab" /> лаба
      <span class="sw bad" /> конфликт · Перетащите пару: зелёные ячейки свободны, красные — с конфликтом (подсказка при наведении).
    </p>

    <Modal v-if="pending" title="Перенос с конфликтами" @close="pending = null">
      <p>Перенос нарушает жёсткие правила:</p>
      <ul class="issues">
        <li v-for="(c, i) in pending.conflicts.slice(0, 20)" :key="i" class="error">
          <strong>{{ fmtFull(c.date) }}:</strong> {{ c.messages.join(' ') }}
        </li>
      </ul>
      <p v-if="pending.conflicts.length > 20" class="muted small">…и ещё {{ pending.conflicts.length - 20 }}</p>
      <template #foot>
        <button class="primary" @click="pending = null">Отменить перенос</button>
        <button class="danger" @click="forceMove">Перенести всё равно</button>
      </template>
    </Modal>

    <Modal v-if="opened" :title="opened.subject" @close="opened = null">
      <dl class="info">
        <dt>Тип</dt><dd>{{ opened.lesson_type }}</dd>
        <dt>Когда</dt><dd>{{ fmtFull(opened.date) }}, {{ opened.slot_number }}-я пара ({{ opened.time }})</dd>
        <dt>{{ opened.group_ids.length > 1 ? 'Поток' : 'Группа' }}</dt>
        <dd>{{ opened.groups }}<span v-if="opened.stream" class="muted small"> · {{ opened.stream }}</span></dd>
        <dt>Преподаватель</dt><dd>{{ opened.teacher }}</dd>
        <dt>Аудитория</dt>
        <dd class="row">
          <select v-model.number="roomChoice">
            <option :value="opened.room_id">{{ opened.room }} (текущая)</option>
            <option v-for="r in freeRooms" :key="r.id" :value="r.id">{{ r.number }} · {{ r.capacity }} мест</option>
          </select>
          <button class="sm" :disabled="roomChoice === opened.room_id" @click="changeRoom">Сменить</button>
        </dd>
      </dl>
      <ul v-if="opened.conflicts.length" class="issues">
        <li v-for="(c, i) in opened.conflicts" :key="i" class="error">{{ c }}</li>
      </ul>
      <template #foot>
        <button @click="togglePin">{{ opened.pinned ? 'Открепить' : 'Закрепить' }}</button>
        <button class="primary" @click="opened = null">Закрыть</button>
      </template>
    </Modal>

    <Modal v-if="shareUrl" title="Публичная ссылка" @close="shareUrl = ''">
      <p>По этой ссылке студенты и преподаватели видят опубликованную версию без входа (только просмотр):</p>
      <div class="row"><input :value="shareUrl" type="text" readonly style="flex:1" @focus="$event.target.select()" /><button @click="copy">Копировать</button></div>
      <template #foot>
        <button class="danger" @click="unpublish">Снять с публикации</button>
        <button class="primary" @click="shareUrl = ''">Готово</button>
      </template>
    </Modal>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import Modal from '../components/Modal.vue'
import WeekGrid from '../components/WeekGrid.vue'
import { api } from '../api'
import { addDays, fmt, fmtFull, iso, loadVersions, mondayOf, parseDate, setVersion, store, toast } from '../store'

const modes = [{ key: 'group', label: 'Группа' }, { key: 'teacher', label: 'Преподаватель' }, { key: 'room', label: 'Аудитория' }]
const mode = ref(sessionGet('mode') || 'group')
const entityId = ref(null)
const ctx = ref(null)
const weekStart = ref(mondayOf(new Date()))
const lessons = ref([])
const lists = ref({ group: [], teacher: [], room: [] })
const series = ref(false)
const pending = ref(null)
const opened = ref(null)
const freeRooms = ref([])
const roomChoice = ref(null)
const shareUrl = ref('')
const loaded = ref(false)

function sessionGet(k) { try { return sessionStorage.getItem(k) } catch { return null } }
function sessionSet(k, v) { try { sessionStorage.setItem(k, v) } catch { /* ignore */ } }

const version = computed(() => store.versions.find(v => v.id === store.versionId))
const days = computed(() => [...Array(ctx.value?.term.days_per_week || 5).keys()].map(i => addDays(weekStart.value, i)))
const entities = computed(() => lists.value[mode.value])
const key = computed(() => ({ group: 'group_id', teacher: 'teacher_id', room: 'room_id' })[mode.value])
const shown = computed(() => {
  const list = lessons.value.filter(l => l[key.value] === entityId.value)
  if (mode.value === 'group') return list
  // У преподавателя и в аудитории общая пара потока — одна карточка со всеми группами.
  const seen = new Set()
  return list.filter(l => {
    const k = `${l.unit_id}|${l.date}|${l.slot_number}`
    if (seen.has(k)) return false
    seen.add(k)
    return true
  })
})
const weekConflicts = computed(() => lessons.value.filter(l => l.conflicts.length).length)

onMounted(async () => {
  await loadVersions()
  loaded.value = true
  const [g, t, r] = await Promise.all([api('/groups'), api('/teachers'), api('/rooms')])
  lists.value = {
    group: g.map(x => ({ id: x.id, name: x.name })),
    teacher: t.map(x => ({ id: x.id, name: x.full_name })),
    room: r.map(x => ({ id: x.id, name: `${x.number} (${x.room_type})` })),
  }
  const saved = Number(sessionGet('entity_' + mode.value))
  entityId.value = entities.value.find(e => e.id === saved)?.id ?? entities.value[0]?.id ?? null
  if (store.versionId) await loadCtx()
})

watch(entityId, v => sessionSet('entity_' + mode.value, v ?? ''))

function setMode(m) {
  mode.value = m
  sessionSet('mode', m)
  const saved = Number(sessionGet('entity_' + m))
  entityId.value = entities.value.find(e => e.id === saved)?.id ?? entities.value[0]?.id ?? null
}

async function loadCtx() {
  ctx.value = await api(`/versions/${store.versionId}/context`)
  const start = parseDate(ctx.value.term.start_date)
  const end = parseDate(ctx.value.term.end_date)
  const now = new Date()
  const savedWeek = sessionGet('week')
  if (savedWeek && parseDate(savedWeek) >= mondayOf(start) && parseDate(savedWeek) <= end) weekStart.value = parseDate(savedWeek)
  else weekStart.value = mondayOf(now >= start && now <= end ? now : start)
  await loadWeek()
}

async function loadWeek() {
  const r = await api(`/versions/${store.versionId}/lessons`, {
    params: { start: iso(weekStart.value), end: iso(addDays(weekStart.value, 6)) },
  })
  lessons.value = r.lessons
  const v = store.versions.find(x => x.id === store.versionId)
  if (v) Object.assign(v, r.version)
}

async function pickVersion(id) {
  setVersion(id)
  await loadCtx()
}
function shift(n) { weekStart.value = addDays(weekStart.value, n); sessionSet('week', iso(weekStart.value)); loadWeek() }
function goto(s) { if (!s) return; weekStart.value = mondayOf(parseDate(s)); sessionSet('week', iso(weekStart.value)); loadWeek() }

/** Быстрая проверка в браузере во время перетаскивания. Окончательно проверяет сервер. */
function checkCell(l, date, n) {
  const out = []
  if (ctx.value.non_working.includes(date)) out.push('Нерабочий день')
  const wd = (parseDate(date).getDay() + 6) % 7
  if ((ctx.value.unavailable[l.teacher_id] || []).some(([d, s]) => d === wd && s === n)) out.push(`${l.teacher} недоступен в это время`)
  if ((ctx.value.days_off[l.teacher_id] || []).includes(date)) out.push(`У ${l.teacher} отгул`)
  if (l.group_ids.some(g => !(ctx.value.group_slots[g] || [n]).includes(n))) out.push('Пара вне смены группы')
  for (const o of lessons.value) {
    // Остальные группы того же потока переезжают вместе с этой парой.
    if (o.unit_id === l.unit_id || o.date !== date || o.slot_number !== n) continue
    if (l.group_ids.includes(o.group_id)) out.push(`У группы ${o.group} уже стоит «${o.subject}»`)
    if (o.teacher_id === l.teacher_id) out.push(`${l.teacher} ведёт пару у ${o.groups}`)
    if (mode.value === 'room' && o.room_id === entityId.value) out.push('Аудитория занята')
  }
  return [...new Set(out)]
}

let lastMove = null
async function onDrop(l, date, n) {
  lastMove = { id: l.id, body: { date, slot_number: n, series: series.value, room_id: mode.value === 'room' ? entityId.value : null } }
  try {
    const r = await api(`/lessons/${l.id}/move`, { method: 'POST', body: lastMove.body })
    if (!r.applied) { pending.value = r; return }
    toast(r.count > 1 ? `Перенесено пар: ${r.count}` : 'Пара перенесена')
    await loadWeek()
  } catch (e) { toast(e.message, 'bad') }
}
async function forceMove() {
  try {
    const r = await api(`/lessons/${lastMove.id}/move`, { method: 'POST', body: { ...lastMove.body, force: true } })
    toast(`Перенесено с конфликтами: ${r.count}`, 'bad')
  } catch (e) { toast(e.message, 'bad') }
  pending.value = null
  await loadWeek()
}

async function openLesson(l) {
  opened.value = l
  roomChoice.value = l.room_id
  freeRooms.value = await api('/rooms/free', {
    params: { version_id: store.versionId, curriculum_id: l.curriculum_id, day: l.date, slot_number: l.slot_number },
  })
}
async function changeRoom() {
  const l = opened.value
  const r = await api(`/lessons/${l.id}/move`, { method: 'POST', body: { date: l.date, slot_number: l.slot_number, room_id: roomChoice.value } })
  if (!r.applied) { lastMove = { id: l.id, body: { date: l.date, slot_number: l.slot_number, room_id: roomChoice.value } }; pending.value = r }
  else toast('Аудитория изменена')
  opened.value = null
  await loadWeek()
}
async function togglePin() {
  const l = opened.value
  await api(`/lessons/${l.id}/pin`, { method: 'POST', body: { pinned: !l.pinned } })
  l.pinned = !l.pinned
}

async function publish() {
  const v = await api(`/versions/${store.versionId}/publish`, { method: 'POST', body: { enabled: true } })
  await loadVersions()
  shareUrl.value = `${location.origin}/p/${v.public_token}`
}
async function unpublish() {
  await api(`/versions/${store.versionId}/publish`, { method: 'POST', body: { enabled: false } })
  await loadVersions()
  shareUrl.value = ''
  toast('Ссылка отключена')
}
async function copy() {
  try { await navigator.clipboard.writeText(shareUrl.value); toast('Скопировано') } catch { toast('Не удалось скопировать', 'bad') }
}
</script>

<style scoped>
.toolbar { padding: 12px 16px; }
.toolbar .row { align-items: flex-end; }
.sub { margin-top: 10px; align-items: center !important; }
.seg { display: inline-flex; border: 1px solid var(--line-strong); border-radius: 6px; overflow: hidden; }
.seg button { border: none; border-radius: 0; border-right: 1px solid var(--line-strong); }
.seg button:last-child { border-right: none; }
.seg button.active { background: var(--accent); color: #fff; }
.week { gap: 4px; flex-wrap: nowrap; }
.legend { margin-top: 10px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.sw { display: inline-block; width: 14px; height: 14px; border-radius: 3px; border: 1px solid var(--line-strong); }
.sw.t-lec { background: var(--lecture); } .sw.t-pr { background: var(--practice); } .sw.t-lab { background: var(--lab); }
.sw.bad { background: var(--bad-soft); border: 2px solid var(--bad); margin-left: 8px; }
.info { display: grid; grid-template-columns: 130px 1fr; gap: 8px 12px; margin: 0 0 12px; }
.info dt { color: var(--muted); }
.info dd { margin: 0; }
</style>
