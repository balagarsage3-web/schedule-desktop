<template>
  <!-- Компьютер: сетка «пара × день» -->
  <div v-if="!narrow" class="wg-wrap">
    <table class="wg">
      <thead>
        <tr>
          <th class="slot-col" />
          <th v-for="d in days" :key="iso(d)" :class="{ off: isOff(d), today: iso(d) === todayIso }">
            {{ WEEKDAYS_FULL[(d.getDay() + 6) % 7] }}<span class="date">{{ fmt(d) }}</span>
            <span v-if="isOff(d)" class="off-label">нерабочий</span>
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="s in slots" :key="s.number">
          <th class="slot-col"><strong>{{ s.number }}</strong><span class="muted small">{{ s.time }}</span></th>
          <td v-for="d in days" :key="iso(d)" :class="cellClass(d, s.number)" :title="cellTitle(d, s.number)"
              @dragover.prevent="onOver" @drop.prevent="onDrop(d, s.number)">
            <div v-for="l in at(d, s.number)" :key="l.id" class="lesson" :class="[typeClass(l), { conflict: l.conflicts?.length, dragging: dragId === l.id, pinned: l.pinned }]"
                 :draggable="editable" @dragstart="onStart($event, l)" @dragend="onEnd" @click="$emit('open', l)">
              <div class="subj">{{ l.subject }}</div>
              <div class="meta">{{ l.lesson_type }}<span v-if="l.group_ids?.length > 1" class="stream" :title="'Общая пара: ' + l.groups"> · поток</span></div>
              <div class="meta">{{ second(l) }}</div>
              <div class="meta room">{{ third(l) }}</div>
              <span v-if="l.conflicts?.length" class="warn-dot" :title="l.conflicts.join('\n')">!</span>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <!-- Телефон: список по дням -->
  <div v-else class="wl">
    <section v-for="d in days" :key="iso(d)" class="day" :class="{ off: isOff(d) }">
      <h3>{{ WEEKDAYS_FULL[(d.getDay() + 6) % 7] }}, {{ fmt(d) }} <span v-if="isOff(d)" class="muted small">— нерабочий</span></h3>
      <div v-for="l in dayLessons(d)" :key="l.id" class="lesson row-l" :class="[typeClass(l), { conflict: l.conflicts?.length }]" @click="$emit('open', l)">
        <div class="when"><strong>{{ l.slot_number }}</strong><span class="small">{{ l.time }}</span></div>
        <div>
          <div class="subj">{{ l.subject }} <span class="muted small">· {{ l.lesson_type }}<template v-if="l.group_ids?.length > 1"> · поток</template></span></div>
          <div class="meta">{{ second(l) }} · {{ third(l) }}</div>
        </div>
      </div>
      <p v-if="!dayLessons(d).length" class="muted small">Пар нет</p>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { WEEKDAYS_FULL, fmt, iso } from '../store'

const props = defineProps({
  days: Array,          // Date[]
  slots: Array,         // [{number, time}]
  lessons: Array,
  mode: { type: String, default: 'group' },
  nonWorking: { type: Array, default: () => [] },
  editable: Boolean,
  check: Function,      // (lesson, isoDate, slot) => string[] — причины, по которым сюда нельзя
})
const emit = defineEmits(['open', 'drop'])

const narrow = ref(false)
let mq
const upd = () => { narrow.value = mq.matches }
onMounted(() => { mq = window.matchMedia('(max-width: 700px)'); upd(); mq.addEventListener('change', upd) })
onUnmounted(() => mq?.removeEventListener('change', upd))

const todayIso = iso(new Date())
const offSet = computed(() => new Set(props.nonWorking))
const isOff = d => offSet.value.has(iso(d))
const index = computed(() => {
  const m = new Map()
  props.lessons.forEach(l => {
    const k = `${l.date}|${l.slot_number}`
    if (!m.has(k)) m.set(k, [])
    m.get(k).push(l)
  })
  return m
})
const at = (d, n) => index.value.get(`${iso(d)}|${n}`) || []
const dayLessons = d => props.lessons.filter(l => l.date === iso(d)).sort((a, b) => a.slot_number - b.slot_number)
const typeClass = l => ({ лекция: 't-lec', практика: 't-pr', лаба: 't-lab' }[l.lesson_type] || '')
const second = l => (props.mode === 'group' ? l.teacher : (l.groups || l.group))
const third = l => (props.mode === 'room' ? l.teacher : `ауд. ${l.room}`)

// --- перетаскивание ---
const dragId = ref(null)
const dragLesson = ref(null)
const verdicts = ref(new Map())

function onStart(e, l) {
  dragId.value = l.id
  dragLesson.value = l
  e.dataTransfer.effectAllowed = 'move'
  e.dataTransfer.setData('text/plain', String(l.id))
  const m = new Map()
  if (props.check) {
    props.days.forEach(d => props.slots.forEach(s => {
      m.set(`${iso(d)}|${s.number}`, props.check(l, iso(d), s.number))
    }))
  }
  verdicts.value = m
}
function onEnd() {
  dragId.value = null
  dragLesson.value = null
  verdicts.value = new Map()
}
// В «красную» ячейку бросить тоже можно: сервер перепроверит и покажет причины с выбором «перенести всё равно».
function onOver(e) {
  if (dragLesson.value) e.dataTransfer.dropEffect = 'move'
}
function onDrop(d, n) {
  const l = dragLesson.value
  onEnd()
  if (!l || (l.date === iso(d) && l.slot_number === n)) return
  emit('drop', l, iso(d), n)
}
function cellClass(d, n) {
  const cls = ['cell']
  if (isOff(d)) cls.push('off')
  if (dragLesson.value) {
    const r = verdicts.value.get(`${iso(d)}|${n}`)
    cls.push(r && r.length ? 'drop-bad' : 'drop-ok')
  }
  return cls
}
function cellTitle(d, n) {
  if (!dragLesson.value) return ''
  const r = verdicts.value.get(`${iso(d)}|${n}`)
  return r && r.length ? r.join('\n') : 'Можно перенести'
}
</script>

<style scoped>
.wg-wrap { overflow-x: auto; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); }
.wg { width: 100%; border-collapse: collapse; table-layout: fixed; min-width: 760px; }
.wg th, .wg td { border: 1px solid var(--line); vertical-align: top; }
.wg thead th { background: var(--panel-2); padding: 8px; font-weight: 600; font-size: 13px; text-align: left; }
.wg thead th.today { color: var(--accent); }
.wg thead th .date { display: block; font-weight: 400; color: var(--muted); font-size: 12px; }
.wg thead th .off-label { display: block; color: var(--warn); font-weight: 400; font-size: 11px; }
.slot-col { width: 86px; background: var(--panel-2); padding: 8px; text-align: left; }
.slot-col strong { display: block; font-size: 15px; }
.cell { height: 88px; padding: 4px; transition: background .1s; }
.cell.off { background: repeating-linear-gradient(45deg, var(--panel-2), var(--panel-2) 6px, transparent 6px, transparent 12px); }
.cell.drop-ok { background: var(--ok-soft); }
.cell.drop-bad { background: var(--bad-soft); }
.lesson { position: relative; border-radius: 6px; padding: 5px 7px; font-size: 12px; line-height: 1.3; cursor: pointer; border: 1px solid var(--line);
  background: var(--panel-2); margin-bottom: 3px; }
.lesson[draggable=true] { cursor: grab; }
.lesson.t-lec { background: var(--lecture); }
.lesson.t-pr { background: var(--practice); }
.lesson.t-lab { background: var(--lab); }
.lesson.conflict { border: 2px solid var(--bad); background: var(--bad-soft); }
.lesson.dragging { opacity: .4; }
.lesson.pinned::after { content: '📌'; position: absolute; right: 4px; bottom: 2px; font-size: 10px; }
.subj { font-weight: 600; font-size: 12.5px; }
.stream { color: var(--pref); font-weight: 600; }
.meta { color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.warn-dot { position: absolute; top: 3px; right: 4px; background: var(--bad); color: #fff; border-radius: 50%; width: 16px; height: 16px;
  font-size: 11px; font-weight: 700; display: flex; align-items: center; justify-content: center; }

.wl { display: flex; flex-direction: column; gap: 12px; }
.day { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 12px; }
.day.off { opacity: .7; }
.day h3 { margin-bottom: 8px; }
.row-l { display: grid; grid-template-columns: 64px 1fr; gap: 10px; align-items: center; margin-bottom: 6px; }
.when { display: flex; flex-direction: column; }
.when strong { font-size: 16px; }
.row-l .meta { white-space: normal; }
</style>
