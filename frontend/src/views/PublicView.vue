<template>
  <div class="pub">
    <p v-if="error" class="card empty">{{ error }}</p>
    <template v-else-if="meta">
      <header class="head">
        <div>
          <h1>Расписание</h1>
          <p class="muted small">{{ meta.term.name }} · версия №{{ meta.version.number }} от {{ meta.version.created_at.replace('T', ' ') }}</p>
        </div>
      </header>
      <div class="card row controls">
        <div class="seg">
          <button :class="{ active: mode === 'group' }" @click="setMode('group')">Группа</button>
          <button :class="{ active: mode === 'teacher' }" @click="setMode('teacher')">Преподаватель</button>
        </div>
        <select v-model.number="entityId" @change="remember">
          <option v-for="e in list" :key="e.id" :value="e.id">{{ e.name }}</option>
        </select>
        <div class="row week">
          <button class="sm" aria-label="Предыдущая неделя" @click="shift(-7)">‹</button>
          <span>{{ fmt(weekStart) }} – {{ fmt(addDays(weekStart, meta.term.days_per_week - 1)) }}</span>
          <button class="sm" aria-label="Следующая неделя" @click="shift(7)">›</button>
        </div>
      </div>
      <WeekGrid :days="days" :slots="meta.slots" :lessons="shown" :mode="mode" />
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import WeekGrid from '../components/WeekGrid.vue'
import { api } from '../api'
import { addDays, fmt, iso, mondayOf, parseDate } from '../store'

const route = useRoute()
const token = route.params.token
const meta = ref(null)
const error = ref('')
const lessons = ref([])
const mode = ref('group')
const entityId = ref(null)
const weekStart = ref(mondayOf(new Date()))

const list = computed(() => (mode.value === 'group' ? meta.value.groups : meta.value.teachers))
const days = computed(() => [...Array(meta.value.term.days_per_week).keys()].map(i => addDays(weekStart.value, i)))
const shown = computed(() => {
  const list = lessons.value.filter(l => (mode.value === 'group' ? l.group_id : l.teacher_id) === entityId.value)
  if (mode.value === 'group') return list
  const seen = new Set()  // общая пара потока — одна карточка
  return list.filter(l => {
    const k = `${l.unit_id}|${l.date}|${l.slot_number}`
    return seen.has(k) ? false : seen.add(k)
  })
})

function lsGet(k) { try { return localStorage.getItem(k) } catch { return null } }
function remember() { try { localStorage.setItem(`pub_${mode.value}`, entityId.value) } catch { /* ignore */ } }

function setMode(m) {
  mode.value = m
  const saved = Number(lsGet(`pub_${m}`))
  entityId.value = list.value.find(e => e.id === saved)?.id ?? list.value[0]?.id ?? null
}

async function load() {
  lessons.value = await api(`/public/${token}/lessons`, { params: { start: iso(weekStart.value), end: iso(addDays(weekStart.value, 6)) } })
}
function shift(n) { weekStart.value = addDays(weekStart.value, n); load() }

onMounted(async () => {
  try {
    meta.value = await api(`/public/${token}`)
    document.title = `Расписание — ${meta.value.term.name}`
    const start = parseDate(meta.value.term.start_date)
    const end = parseDate(meta.value.term.end_date)
    const now = new Date()
    weekStart.value = mondayOf(now >= start && now <= end ? now : start)
    setMode('group')
    await load()
  } catch (e) {
    error.value = e.message
  }
})
</script>

<style scoped>
.pub { max-width: 1300px; margin: 0 auto; padding: 16px; }
.head { margin-bottom: 12px; }
.head h1 { margin: 0; }
.controls { padding: 12px; }
.seg { display: inline-flex; border: 1px solid var(--line-strong); border-radius: 6px; overflow: hidden; }
.seg button { border: none; border-radius: 0; }
.seg button.active { background: var(--accent); color: #fff; }
.week { gap: 6px; }
</style>
