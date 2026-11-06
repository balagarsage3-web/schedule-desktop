<template>
  <div>
    <div v-if="!store.terms.length" class="card intro">
      <h2>С чего начать</h2>
      <p>Создайте учебный период ниже или загрузите демонстрационный набор данных (колледж из 12 групп), чтобы сразу посмотреть, как работает генерация.</p>
      <button class="primary" :disabled="busy" @click="demo">Загрузить демо-данные</button>
    </div>

    <div class="card">
      <div class="row">
        <h2 style="margin:0">Учебный период</h2>
        <span class="spacer" />
        <button @click="newTerm">Новый период</button>
        <button v-if="form.id" class="danger" @click="delTerm">Удалить период</button>
      </div>
      <form class="grid-form" style="margin-top:12px" @submit.prevent="saveTerm">
        <label class="field"><span>Название</span><input v-model="form.name" type="text" required /></label>
        <label class="field"><span>Начало</span><input v-model="form.start_date" type="date" required /></label>
        <label class="field"><span>Конец</span><input v-model="form.end_date" type="date" required /></label>
        <label class="field"><span>Учебных дней в неделе</span>
          <select v-model.number="form.days_per_week"><option :value="5">5 (пн–пт)</option><option :value="6">6 (пн–сб)</option></select>
        </label>
        <label class="field"><span>Лимит времени расчёта, с</span><input v-model.number="form.time_limit" type="number" min="5" max="1800" /></label>
        <label class="field"><span>Желательно не более пар в день у группы</span><input v-model.number="form.group_day_limit" type="number" min="1" max="12" /></label>
      </form>

      <h3 style="margin-top:20px">Веса мягких правил</h3>
      <p class="muted small">0 — правило не учитывается. Чем больше вес, тем сильнее решатель старается его выполнить.</p>
      <div class="weights">
        <label v-for="w in weightDefs" :key="w.key" class="weight">
          <span>{{ w.label }}</span>
          <input v-model.number="form.weights[w.key]" type="range" min="0" max="40" />
          <strong>{{ form.weights[w.key] }}</strong>
        </label>
      </div>

      <h3 style="margin-top:20px">Пары по сменам</h3>
      <p class="muted small">В какие пары могут стоять занятия у групп каждой смены.</p>
      <div class="table-wrap" style="max-width:640px">
        <table class="data shifts">
          <thead><tr><th>Смена</th><th v-for="s in slots" :key="s.id" class="c">{{ s.number }}</th></tr></thead>
          <tbody>
            <tr v-for="sh in shifts" :key="sh">
              <td>{{ sh }}</td>
              <td v-for="s in slots" :key="s.id" class="c">
                <input type="checkbox" :checked="(form.shift_slots[sh] || []).includes(s.number)" @change="toggleShift(sh, s.number, $event.target.checked)" />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="row" style="margin-top:16px">
        <button class="primary" :disabled="busy" @click="saveTerm">{{ form.id ? 'Сохранить параметры' : 'Создать период' }}</button>
      </div>
    </div>

    <div class="two">
      <div class="card">
        <h2>Расписание звонков</h2>
        <EntityTable endpoint="/time-slots" title="Пары" bulk-entity="time-slots" :fields="[
          { key: 'number', label: '№ пары', type: 'number', min: 1, max: 12 },
          { key: 'start', label: 'Начало', type: 'time' },
          { key: 'end', label: 'Конец', type: 'time' },
        ]" @changed="r => (slots = r)" />
      </div>
      <div v-if="form.id" class="card">
        <h2>Праздники и нерабочие дни</h2>
        <form class="row end" @submit.prevent="addHoliday">
          <label class="field"><span>Дата</span><input v-model="hDate" type="date" required /></label>
          <label class="field" style="flex:1;min-width:160px"><span>Причина</span><input v-model="hReason" type="text" /></label>
          <button class="primary">Добавить</button>
        </form>
        <ul class="list">
          <li v-for="h in holidays" :key="h.id">
            <strong>{{ fmtFull(h.date) }}</strong> <span class="muted">{{ h.reason }}</span>
            <button class="sm ghost danger" @click="delHoliday(h)">Удалить</button>
          </li>
          <li v-if="!holidays.length" class="muted small">Нерабочих дней нет</li>
        </ul>
      </div>
    </div>

    <div class="card">
      <h2>Служебное</h2>
      <div class="row">
        <button :disabled="busy" @click="demo">Заменить все данные демо-набором</button>
        <label class="row small">групп: <input v-model.number="demoGroups" type="number" min="3" max="60" style="width:80px" /></label>
      </div>
      <form class="row end" style="margin-top:14px" @submit.prevent="changePassword">
        <label class="field"><span>Текущий пароль</span><input v-model="pwOld" type="password" required autocomplete="current-password" /></label>
        <label class="field"><span>Новый пароль</span><input v-model="pwNew" type="password" required minlength="6" autocomplete="new-password" /></label>
        <button>Сменить пароль</button>
      </form>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import EntityTable from '../components/EntityTable.vue'
import { api } from '../api'
import { fmtFull, loadTerms, setTerm, store, toast } from '../store'

const weightDefs = [
  { key: 'gaps', label: 'Без «окон» между парами у группы' },
  { key: 'teacher_gaps', label: 'Без «окон» между парами у преподавателя' },
  { key: 'group_day_limit', label: 'Не больше заданного числа пар в день у группы' },
  { key: 'even_days', label: 'Равномерное распределение по дням недели' },
  { key: 'same_slot', label: 'Дисциплина не в один и тот же слот каждый день' },
  { key: 'teacher_pref', label: 'Пожелания преподавателей (желательное время)' },
  { key: 'room_changes', label: 'Минимум смен аудитории у группы за день' },
  { key: 'lecture_morning', label: 'Лекции в первой половине дня' },
  { key: 'stability', label: 'Пары на тех же местах, что и на прошлой неделе' },
]
const shifts = ['утро', 'день', 'вечер']
const blank = () => ({
  id: null, name: 'Новый семестр', start_date: '', end_date: '', days_per_week: 5, time_limit: 60, group_day_limit: 4,
  weights: { gaps: 20, teacher_gaps: 5, group_day_limit: 10, even_days: 5, same_slot: 5, teacher_pref: 5, room_changes: 1, lecture_morning: 1, stability: 3 },
  shift_slots: { утро: [1, 2, 3, 4], день: [3, 4, 5, 6], вечер: [5, 6, 7, 8] },
})
const form = reactive(blank())
const slots = ref([])
const holidays = ref([])
const hDate = ref('')
const hReason = ref('')
const busy = ref(false)
const demoGroups = ref(12)
const pwOld = ref('')
const pwNew = ref('')

function fill() {
  const t = store.terms.find(x => x.id === store.termId)
  Object.assign(form, blank(), t ? JSON.parse(JSON.stringify(t)) : {})
  if (t) form.weights = { ...blank().weights, ...t.weights }
}

async function loadHolidays() {
  holidays.value = form.id ? await api(`/terms/${form.id}/non-working-days`) : []
}

onMounted(async () => {
  await loadTerms()
  fill()
  await loadHolidays()
})

function newTerm() {
  Object.assign(form, blank())
  holidays.value = []
}

function toggleShift(sh, n, on) {
  const cur = new Set(form.shift_slots[sh] || [])
  on ? cur.add(n) : cur.delete(n)
  form.shift_slots = { ...form.shift_slots, [sh]: [...cur].sort((a, b) => a - b) }
}

async function saveTerm() {
  busy.value = true
  try {
    const body = { ...form }
    delete body.id
    const t = form.id ? await api(`/terms/${form.id}`, { method: 'PUT', body }) : await api('/terms', { method: 'POST', body })
    await loadTerms()
    setTerm(t.id)
    fill()
    await loadHolidays()
    toast('Параметры сохранены')
  } catch (e) { toast(e.message, 'bad') } finally { busy.value = false }
}

async function delTerm() {
  if (!confirm('Удалить период вместе со всеми версиями расписания?')) return
  await api(`/terms/${form.id}`, { method: 'DELETE' })
  await loadTerms()
  fill()
  await loadHolidays()
}

async function addHoliday() {
  try {
    await api(`/terms/${form.id}/non-working-days`, { method: 'POST', body: { date: hDate.value, reason: hReason.value } })
    hDate.value = ''
    hReason.value = ''
    await loadHolidays()
  } catch (e) { toast(e.message, 'bad') }
}
async function delHoliday(h) {
  await api(`/non-working-days/${h.id}`, { method: 'DELETE' })
  await loadHolidays()
}

async function demo() {
  if (store.terms.length && !confirm('Все текущие данные и версии расписания будут удалены и заменены демо-набором. Продолжить?')) return
  busy.value = true
  try {
    const r = await api('/demo', { method: 'POST', body: { groups: demoGroups.value } })
    await loadTerms()
    setTerm(r.term_id)
    location.reload()
  } catch (e) { toast(e.message, 'bad') } finally { busy.value = false }
}

async function changePassword() {
  try {
    await api('/auth/password', { method: 'POST', body: { old: pwOld.value, new: pwNew.value } })
    pwOld.value = ''
    pwNew.value = ''
    toast('Пароль изменён')
  } catch (e) { toast(e.message, 'bad') }
}
</script>

<style scoped>
.intro { border-color: var(--accent); background: var(--accent-soft); }
.weights { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 8px 24px; }
.weight { display: grid; grid-template-columns: 1fr 120px 28px; align-items: center; gap: 10px; font-size: 13px; }
.weight strong { text-align: right; font-variant-numeric: tabular-nums; }
.shifts .c { text-align: center; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.two .card { margin-bottom: 16px; }
.list { list-style: none; padding: 0; margin: 12px 0 0; display: flex; flex-direction: column; gap: 4px; }
.list li { display: flex; gap: 10px; align-items: center; }
@media (max-width: 900px) { .two { grid-template-columns: 1fr; } .weight { grid-template-columns: 1fr 90px 24px; } }
</style>
