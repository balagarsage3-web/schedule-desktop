<template>
  <div>
    <p class="muted">Какие дисциплины изучает каждая группа, кто их ведёт и сколько пар нужно поставить.
      Строки из <router-link to="/kug">КУГ</router-link> берут нагрузку по неделям из графика; для остальных — «пар в неделю», «всего» и необязательные сроки.</p>
    <details class="muted small help">
      <summary>Потоки и дисциплины, идущие друг за другом</summary>
      <p><strong>Общие пары (потоки):</strong> укажите одинаковое название потока в строках нескольких групп, например «История, 1 курс».
        Такие строки станут одной парой: в одно время, у одного преподавателя, в одной аудитории на всех.</p>
      <p><strong>Дисциплины одна за другой:</strong> задайте «Начало» и «Окончание» — например, Химия до 25.10, Биология с 26.10.
        Пары дисциплины ставятся только в её сроки; если не задано — весь период.</p>
    </details>
    <EntityTable v-if="ready" endpoint="/curriculum" title="Учебный план" import-entity="curriculum" bulk-entity="curriculum"
      :filter="rowFilter" :row-class="r => (r.teacher_id ? '' : 'no-teacher')" :fields="[
      { key: 'group_id', label: 'Группа', type: 'select', options: groupOpts },
      { key: 'subject_id', label: 'Дисциплина', type: 'select', options: subjectOpts },
      { key: 'teacher_id', label: 'Преподаватель', type: 'select', options: teacherOpts, nullable: true, nullLabel: '— не назначен —',
        cellClass: r => (r.teacher_id ? '' : 'missing') },
      { key: 'total', label: 'Пар всего', type: 'number', min: 1, default: 36,
        lockedIf: r => r.has_kug, lockedText: 'по КУГ', format: r => r.total },
      { key: 'per_week', label: 'Пар в неделю', type: 'number', min: 1, max: 40, default: 2,
        lockedIf: r => r.has_kug, lockedText: 'по КУГ — меняется по неделям',
        format: r => (r.has_kug ? `до ${r.per_week}` : r.per_week) },
      { key: 'start_date', label: 'Начало', type: 'date', required: false, lockedIf: r => r.has_kug, lockedText: 'по КУГ',
        help: 'Необязательно. Пары ставятся только в сроки дисциплины.' },
      { key: 'end_date', label: 'Окончание', type: 'date', required: false, lockedIf: r => r.has_kug, lockedText: 'по КУГ' },
      { key: 'stream', label: 'Поток (общая пара)', required: false },
      { key: 'kug_ref', label: 'Источник', form: false, format: r => (r.has_kug ? 'КУГ' : 'вручную'), title: r => r.kug_ref || null },
    ]" @changed="r => (rows = r)">
      <template #filters>
        <select v-model="groupFilter" title="Группа">
          <option :value="null">Все группы</option>
          <option v-for="g in groups" :key="g.id" :value="g.id">{{ g.name }}</option>
        </select>
        <label class="check small"><input v-model="onlyMissing" type="checkbox" /> без преподавателя
          <span v-if="missingCount" class="badge bad">{{ missingCount }}</span></label>
      </template>
      <template #bulk="{ ids, reload }">
        <select v-model="bulkTeacher" title="Назначить преподавателя выбранным строкам">
          <option :value="undefined" disabled>Назначить преподавателя…</option>
          <option :value="null">— снять преподавателя —</option>
          <option v-for="t in teachers" :key="t.id" :value="t.id">{{ t.full_name }}</option>
        </select>
        <button class="primary" :disabled="bulkTeacher === undefined" @click="assign(ids, reload)">Назначить ({{ ids.length }})</button>
      </template>
    </EntityTable>

    <div v-if="loads.length" class="card summary">
      <h3>Нагрузка в неделю</h3>
      <p class="muted small">Для строк из КУГ взята самая нагруженная неделя; подробно по неделям — на экране «КУГ».</p>
      <div class="cols">
        <div>
          <div class="muted small">Группы</div>
          <div v-for="g in loads" :key="g.name" class="bar-row">
            <span class="name">{{ g.name }}</span>
            <span class="bar"><span :style="{ width: Math.min(100, g.load / maxLoad * 100) + '%' }" /></span>
            <span class="num">{{ g.load }}</span>
          </div>
        </div>
        <div>
          <div class="muted small">Преподаватели (нагрузка / максимум)</div>
          <div v-for="t in tLoads" :key="t.name" class="bar-row">
            <span class="name">{{ t.name }}</span>
            <span class="bar" :class="{ over: t.load > t.max }"><span :style="{ width: Math.min(100, t.load / t.max * 100) + '%' }" /></span>
            <span class="num">{{ t.load }} / {{ t.max }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import EntityTable from '../components/EntityTable.vue'
import { api } from '../api'
import { toast } from '../store'

const groups = ref([])
const subjects = ref([])
const teachers = ref([])
const rows = ref([])
const ready = ref(false)

const groupOpts = () => groups.value.map(g => ({ value: g.id, label: g.name }))
const subjectOpts = () => subjects.value.map(s => ({ value: s.id, label: `${s.name} (${s.lesson_type})` }))
const teacherOpts = () => teachers.value.map(t => ({ value: t.id, label: t.full_name }))

onMounted(async () => {
  [groups.value, subjects.value, teachers.value] = await Promise.all([api('/groups'), api('/subjects'), api('/teachers')])
  ready.value = true
})

// --- фильтры и массовое назначение преподавателя ---
const groupFilter = ref(null)
const onlyMissing = ref(false)
const bulkTeacher = ref(undefined)
const missingCount = computed(() => rows.value.filter(r => !r.teacher_id).length)
const rowFilter = r => (groupFilter.value == null || r.group_id === groupFilter.value) && (!onlyMissing.value || !r.teacher_id)

async function assign(ids, reload) {
  try {
    const r = await api('/curriculum/assign-teacher', { method: 'POST', body: { ids, teacher_id: bulkTeacher.value } })
    toast(`Назначено строк: ${r.updated}`)
    bulkTeacher.value = undefined
    teachers.value = await api('/teachers')
    await reload()
  } catch (e) { toast(e.message, 'bad') }
}

const loads = computed(() => {
  const m = new Map()
  rows.value.forEach(r => m.set(r.group_name, (m.get(r.group_name) || 0) + r.per_week))
  return [...m].map(([name, load]) => ({ name, load })).sort((a, b) => a.name.localeCompare(b.name))
})
const maxLoad = computed(() => Math.max(1, ...loads.value.map(x => x.load)))
const tLoads = computed(() => {
  const m = new Map()
  const seen = new Set()
  rows.value.forEach(r => {
    if (r.stream) {  // поток — одна пара для преподавателя, сколько бы групп в нём ни было
      if (seen.has(r.stream)) return
      seen.add(r.stream)
    }
    m.set(r.teacher_id, (m.get(r.teacher_id) || 0) + r.per_week)
  })
  return [...m].map(([id, load]) => {
    const t = teachers.value.find(x => x.id === id)
    return { name: t?.full_name || id, load, max: t?.max_per_week || 1 }
  }).sort((a, b) => b.load / b.max - a.load / a.max)
})
</script>

<style scoped>
.help { margin: 0 0 12px; }
.help summary { cursor: pointer; color: var(--accent); }
.help p { margin: 6px 0 0; }
:deep(tr.no-teacher td:not(.sel)) { background: var(--warn-soft); }
.summary { margin-top: 16px; }
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
.bar-row { display: grid; grid-template-columns: 150px 1fr 60px; gap: 8px; align-items: center; padding: 2px 0; font-size: 13px; }
.bar-row .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar { height: 8px; background: var(--panel-2); border-radius: 999px; overflow: hidden; border: 1px solid var(--line); }
.bar > span { display: block; height: 100%; background: var(--accent); }
.bar.over > span { background: var(--bad); }
.num { text-align: right; font-variant-numeric: tabular-nums; }
@media (max-width: 800px) { .cols { grid-template-columns: 1fr; } }
</style>
