<template>
  <div class="av">
    <div class="card list">
      <input v-model="q" type="search" placeholder="Найти преподавателя…" />
      <div class="items">
        <button v-for="t in filtered" :key="t.id" class="item" :class="{ active: t.id === teacherId }" @click="select(t.id)">
          {{ t.full_name }}
        </button>
        <div v-if="!teachers.length" class="empty small">Сначала добавьте преподавателей в справочниках</div>
      </div>
    </div>

    <div v-if="teacher" class="right">
      <div class="card">
        <div class="row">
          <h2 style="margin:0">{{ teacher.full_name }}</h2>
          <span class="spacer" />
          <span v-if="dirty" class="badge warn">Есть несохранённые изменения</span>
          <button class="primary" :disabled="!dirty || busy" @click="save">Сохранить</button>
        </div>
        <p class="muted small">Щёлкните по ячейке, чтобы сменить состояние; зажмите кнопку мыши и проведите, чтобы закрасить несколько ячеек.
          Заголовок дня или пары меняет всю строку/столбец.</p>
        <div class="row legend">
          <button v-for="s in states" :key="s.key" class="sm" :class="['cell-btn', s.key, { chosen: brush === s.key }]" @click="brush = s.key">
            {{ s.label }}
          </button>
          <span class="muted small">— кисть для закрашивания</span>
        </div>
        <div class="grid-wrap" @mouseleave="painting = false">
          <table class="avgrid" @mouseup="painting = false">
            <thead>
              <tr>
                <th />
                <th v-for="d in days" :key="d"><button class="ghost sm" @click="fillDay(d)">{{ WEEKDAYS[d] }}</button></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in slots" :key="s.number">
                <th><button class="ghost sm slot-h" @click="fillSlot(s.number)">{{ s.number }}<span class="muted small"> {{ s.start.slice(0, 5) }}</span></button></th>
                <td v-for="d in days" :key="d" :class="['cell', grid[key(d, s.number)] || 'available']"
                    @mousedown.prevent="startPaint(d, s.number)" @mouseenter="paint(d, s.number)">
                  {{ label(grid[key(d, s.number)]) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="muted small">Свободно {{ freeCount }} из {{ days.length * slots.length }} слотов, желательно {{ prefCount }}.
          Нагрузка по плану: {{ load }} пар в неделю (максимум {{ teacher.max_per_week }}).</p>
      </div>

      <div class="card">
        <h3>Разовые отгулы по датам</h3>
        <form class="row end" @submit.prevent="addOff">
          <label class="field"><span>Дата</span><input v-model="offDate" type="date" required /></label>
          <label class="field grow"><span>Причина</span><input v-model="offReason" type="text" placeholder="Например, конференция" /></label>
          <button class="primary">Добавить</button>
        </form>
        <ul class="offs">
          <li v-for="o in daysOff" :key="o.id">
            <strong>{{ fmtFull(o.date) }}</strong> <span class="muted">{{ o.reason }}</span>
            <button class="sm ghost danger" @click="delOff(o)">Удалить</button>
          </li>
          <li v-if="!daysOff.length" class="muted small">Отгулов нет</li>
        </ul>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { api } from '../api'
import { WEEKDAYS, fmtFull, store, toast } from '../store'

const states = [
  { key: 'available', label: 'Доступен' },
  { key: 'unavailable', label: 'Недоступен' },
  { key: 'preferred', label: 'Желательно' },
]
const teachers = ref([])
const slots = ref([])
const curriculum = ref([])
const teacherId = ref(null)
const grid = ref({})
const dirty = ref(false)
const busy = ref(false)
const q = ref('')
const brush = ref('unavailable')
const painting = ref(false)
const daysOff = ref([])
const offDate = ref('')
const offReason = ref('')

const term = computed(() => store.terms.find(t => t.id === store.termId))
const days = computed(() => [...Array(term.value?.days_per_week || 6).keys()])
const teacher = computed(() => teachers.value.find(t => t.id === teacherId.value))
const filtered = computed(() => teachers.value.filter(t => t.full_name.toLowerCase().includes(q.value.toLowerCase())))
const key = (d, n) => `${d}:${n}`
const label = s => (s === 'unavailable' ? '✕' : s === 'preferred' ? '★' : '')
const freeCount = computed(() => days.value.length * slots.value.length -
  Object.entries(grid.value).filter(([k, v]) => v === 'unavailable' && days.value.includes(Number(k.split(':')[0]))).length)
const prefCount = computed(() => Object.values(grid.value).filter(v => v === 'preferred').length)
const load = computed(() => curriculum.value.filter(c => c.teacher_id === teacherId.value).reduce((s, c) => s + c.per_week, 0))

onMounted(async () => {
  [teachers.value, slots.value, curriculum.value] = await Promise.all([api('/teachers'), api('/time-slots'), api('/curriculum')])
  if (teachers.value.length) select(teachers.value[0].id)
})

onBeforeRouteLeave(() => !dirty.value || confirm('Изменения доступности не сохранены. Уйти со страницы?'))

async function select(id) {
  if (dirty.value && !confirm('Изменения не сохранены. Переключиться без сохранения?')) return
  teacherId.value = id
  const cells = await api(`/teachers/${id}/availability`)
  const g = {}
  cells.forEach(c => { g[key(c.weekday, c.slot_number)] = c.status })
  grid.value = g
  dirty.value = false
  daysOff.value = await api(`/teachers/${id}/days-off`)
}

function set(d, n, st) {
  grid.value = { ...grid.value, [key(d, n)]: st }
  dirty.value = true
}
function cycle(cur) {
  const order = ['available', 'unavailable', 'preferred']
  return order[(order.indexOf(cur || 'available') + 1) % 3]
}
function startPaint(d, n) {
  const next = cycle(grid.value[key(d, n)])
  brush.value = next
  painting.value = true
  set(d, n, next)
}
function paint(d, n) {
  if (painting.value) set(d, n, brush.value)
}
function fillDay(d) {
  const next = cycle(grid.value[key(d, slots.value[0]?.number)])
  slots.value.forEach(s => set(d, s.number, next))
}
function fillSlot(n) {
  const next = cycle(grid.value[key(days.value[0], n)])
  days.value.forEach(d => set(d, n, next))
}

async function save() {
  busy.value = true
  try {
    const cells = Object.entries(grid.value).map(([k, status]) => {
      const [weekday, slot_number] = k.split(':').map(Number)
      return { weekday, slot_number, status }
    })
    await api(`/teachers/${teacherId.value}/availability`, { method: 'PUT', body: cells })
    dirty.value = false
    toast('Доступность сохранена')
  } catch (e) {
    toast(e.message, 'bad')
  } finally {
    busy.value = false
  }
}

async function addOff() {
  try {
    await api(`/teachers/${teacherId.value}/days-off`, { method: 'POST', body: { date: offDate.value, reason: offReason.value } })
    offDate.value = ''
    offReason.value = ''
    daysOff.value = await api(`/teachers/${teacherId.value}/days-off`)
  } catch (e) { toast(e.message, 'bad') }
}
async function delOff(o) {
  await api(`/days-off/${o.id}`, { method: 'DELETE' })
  daysOff.value = daysOff.value.filter(x => x.id !== o.id)
}
</script>

<style scoped>
.av { display: grid; grid-template-columns: 260px 1fr; gap: 16px; align-items: start; }
.list { padding: 10px; position: sticky; top: 70px; }
.list input { width: 100%; margin-bottom: 8px; }
.items { display: flex; flex-direction: column; max-height: calc(100vh - 180px); overflow: auto; }
.item { text-align: left; border: none; background: transparent; border-radius: 6px; white-space: normal; }
.item.active { background: var(--accent-soft); color: var(--accent); font-weight: 600; }
.right { min-width: 0; }
.legend { margin: 8px 0 12px; }
.cell-btn.available { background: var(--ok-soft); }
.cell-btn.unavailable { background: var(--bad-soft); }
.cell-btn.preferred { background: var(--pref-soft); }
.cell-btn.chosen { outline: 2px solid var(--accent); }
.grid-wrap { overflow-x: auto; }
.avgrid { border-collapse: separate; border-spacing: 4px; user-select: none; }
.avgrid th { font-weight: 600; }
.slot-h { min-width: 80px; text-align: left; }
.cell { width: 76px; height: 40px; border-radius: 6px; text-align: center; cursor: pointer; font-size: 16px; border: 1px solid var(--line); }
.cell.available { background: var(--ok-soft); }
.cell.unavailable { background: var(--bad-soft); color: var(--bad); }
.cell.preferred { background: var(--pref-soft); color: var(--pref); }
.grow { flex: 1; min-width: 200px; }
.offs { list-style: none; padding: 0; margin: 12px 0 0; display: flex; flex-direction: column; gap: 4px; }
.offs li { display: flex; gap: 10px; align-items: center; }
@media (max-width: 800px) {
  .av { grid-template-columns: 1fr; }
  .list { position: static; }
  .items { max-height: 200px; }
  .cell { width: 48px; }
}
</style>
