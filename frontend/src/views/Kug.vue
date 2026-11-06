<template>
  <div>
    <div class="tabs">
      <button :class="{ active: tab === 'grid' }" @click="tab = 'grid'">Нагрузка по неделям</button>
      <button :class="{ active: tab === 'import' }" @click="tab = 'import'">Импорт КУГ из Excel</button>
    </div>

    <!-- ===== Импорт ===== -->
    <div v-if="tab === 'import'">
      <div class="card">
        <h2>1. Файл графика</h2>
        <p class="muted small">Календарный учебный график в Excel: лист на курс, часы по неделям, «К» — каникулы.
          Номера календарных недель в шапке не важны — даты берутся из чисел месяца.</p>
        <div class="row">
          <input type="file" accept=".xlsx" @change="pickFile" />
          <span v-if="parsing" class="muted">Разбор файла…</span>
        </div>
        <p v-if="parseError" class="badge bad" style="margin-top:8px">{{ parseError }}</p>
        <ul v-if="preview && preview.errors.length" class="issues" style="margin-top:8px">
          <li v-for="(e, i) in preview.errors" :key="i" class="warning">{{ e }}</li>
        </ul>
      </div>

      <template v-if="preview">
        <div class="card">
          <h2>2. Курс (лист) — {{ preview.profession || preview.title }}</h2>
          <div class="seg">
            <button v-for="s in preview.sheets" :key="s.index" :class="{ active: sheetIdx === s.index }" @click="sheetIdx = s.index">
              {{ s.title }} <span class="small">{{ s.year }}</span>
            </button>
          </div>
          <template v-if="sheet">
            <p class="muted small" style="margin-top:10px">
              <template v-for="s in sheet.semesters" :key="s.sem">{{ s.sem }}-е полугодие: {{ fmtFull(s.start) }} – {{ fmtFull(s.end) }}. </template>
              Каникулы: {{ sheet.vacation.map(fmt).join(', ') || 'нет' }}.
            </p>
            <div class="table-wrap rows">
              <table class="data">
                <thead><tr><th>Индекс</th><th>Дисциплина</th><th>Вид</th><th class="num">Часов</th><th class="num">Пар</th><th>Недели</th></tr></thead>
                <tbody>
                  <tr v-for="(r, i) in sheet.rows" :key="i" :class="{ dim: !included(r) }">
                    <td>{{ r.code }}</td><td>{{ r.name }}</td>
                    <td><span class="badge" :class="kindClass(r.kind)">{{ r.kind_label }}</span></td>
                    <td class="num">{{ r.total }}</td><td class="num">{{ Math.floor(r.total / 2) }}</td>
                    <td class="small">{{ fmt(r.first) }} – {{ fmt(r.last) }} ({{ r.weeks }} нед.)</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </template>
        </div>

        <div class="card">
          <h2>3. Группы и параметры</h2>
          <p class="muted small">Выберите группы этого курса и профессии — каждой создадутся строки учебного плана с нагрузкой по неделям.
            Уже назначенные преподаватели сохранятся.</p>
          <div class="groups">
            <label v-for="g in groups" :key="g.id" class="check"><input v-model="groupIds" type="checkbox" :value="g.id" /> {{ g.name }}
              <span class="muted small">{{ g.course }}</span></label>
            <span v-if="!groups.length" class="muted small">Сначала добавьте группы в <router-link to="/directories">Справочниках</router-link>.</span>
          </div>
          <div class="opts">
            <label class="check"><input v-model="includeSelf" type="checkbox" /> Ставить в расписание самостоятельную работу («сам.раб»)</label>
            <label class="check"><input v-model="includePractice" type="checkbox" /> Ставить в расписание учебную практику (УП)</label>
            <label class="check"><input v-model="makeStream" type="checkbox" :disabled="groupIds.length < 2" />
              Сделать занятия общими парами (потоком) для выбранных групп</label>
            <label class="check"><input v-model="createTerms" type="checkbox" /> Создать учебные периоды (полугодия) по датам графика</label>
          </div>
          <p class="muted small">Производственная практика, экзамены по модулю и ГИА в расписание пар не ставятся.</p>
          <button class="primary" :disabled="!groupIds.length || importing" @click="doImport">
            {{ importing ? 'Импорт…' : `Импортировать для групп: ${groupIds.length}` }}</button>
          <ul v-if="result" class="issues" style="margin-top:12px">
            <li class="info">Готово: {{ result.disciplines }} дисциплин; строк плана создано {{ result.created }}, обновлено {{ result.updated }}
              ({{ result.groups.join(', ') }}).
              <template v-if="result.terms_created.length"> Созданы периоды: {{ result.terms_created.join('; ') }} — выберите нужный в шапке.</template>
              Дальше: <router-link to="/curriculum">назначьте преподавателей</router-link> (можно выделить строки и назначить разом).</li>
          </ul>
        </div>
      </template>
    </div>

    <!-- ===== Сетка нагрузки ===== -->
    <div v-else>
      <div class="card row toolbar">
        <label class="field"><span>Группа</span>
          <select v-model.number="gridGroup">
            <option v-for="g in groups" :key="g.id" :value="g.id">{{ g.name }}</option>
          </select>
        </label>
        <span class="muted small">Период — в шапке. Часы из КУГ можно править: щёлкните по ячейке. Под часами — пары (2 часа = 1 пара),
          которые поставит решатель; у строк без КУГ пары рассчитаны из «пар в неделю» и сроков.</span>
      </div>
      <div v-if="!store.termId" class="card empty">Выберите или создайте учебный период.</div>
      <div v-else-if="grid && !grid.rows.length" class="card empty">У группы нет дисциплин в этом периоде.
        <a href="#" @click.prevent="tab = 'import'">Импортировать КУГ</a></div>
      <div v-else-if="grid" class="table-wrap kug">
        <table class="kgrid">
          <thead>
            <tr>
              <th class="name">Дисциплина</th>
              <th v-for="w in grid.weeks" :key="w.monday" :class="{ off: !w.study }" :title="'Неделя с ' + fmtFull(w.monday)">{{ w.label }}</th>
              <th class="sum">Пар</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in grid.rows" :key="r.id">
              <td class="name">
                <div>{{ r.subject }} <span v-if="r.stream" class="small stream">поток</span></div>
                <div class="small" :class="r.teacher_missing ? 'miss' : 'muted'">{{ r.teacher }}</div>
              </td>
              <td v-for="w in grid.weeks" :key="w.monday" :class="['c', { off: !w.study, kug: r.kug, editing: isEditing(r, w) }]"
                  @click="startEdit(r, w)">
                <template v-if="isEditing(r, w)">
                  <input ref="cellInput" v-model="editValue" type="number" min="0" max="60" step="1"
                         @keydown.enter="commit" @keydown.esc="cancel" @blur="commit" />
                </template>
                <template v-else>
                  <div v-if="r.kug && r.hours[w.monday]" class="h">{{ r.hours[w.monday] }}</div>
                  <div v-if="r.pairs[w.monday]" class="p">{{ r.pairs[w.monday] }}</div>
                </template>
              </td>
              <td class="sum">{{ r.total_pairs }}</td>
            </tr>
          </tbody>
          <tfoot>
            <tr>
              <td class="name">Всего пар в неделю <span class="muted small">(макс. {{ grid.capacity }})</span></td>
              <td v-for="w in grid.weeks" :key="w.monday" :class="['c', 'tot', { over: (grid.totals[w.monday] || 0) > grid.capacity, off: !w.study }]">
                {{ grid.totals[w.monday] || '' }}</td>
              <td class="sum">{{ Object.values(grid.totals).reduce((a, b) => a + b, 0) }}</td>
            </tr>
          </tfoot>
        </table>
      </div>
      <p class="muted small legend"><span class="sw kugc" /> часы из КУГ (редактируются) · <span class="sw offc" /> нет учебных дней
        (каникулы, праздники) · <span class="sw overc" /> больше пар, чем слотов в смене группы</p>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { fmt, fmtFull, loadTerms, store, toast } from '../store'

const tab = ref('grid')
const groups = ref([])

// --- импорт ---
const file = ref(null)
const preview = ref(null)
const parsing = ref(false)
const parseError = ref('')
const sheetIdx = ref(0)
const groupIds = ref([])
const includeSelf = ref(false)
const includePractice = ref(false)
const makeStream = ref(false)
const createTerms = ref(true)
const importing = ref(false)
const result = ref(null)
const sheet = computed(() => preview.value?.sheets.find(s => s.index === sheetIdx.value))

const included = r => r.kind === 'class' || (r.kind === 'self' && includeSelf.value) || (r.kind === 'up' && includePractice.value)
const kindClass = k => ({ class: 'ok', self: '', up: 'warn', pp: '', exam: '' }[k])

async function pickFile(e) {
  file.value = e.target.files[0] || null
  preview.value = null
  result.value = null
  parseError.value = ''
  if (!file.value) return
  parsing.value = true
  try {
    const form = new FormData()
    form.append('file', file.value)
    preview.value = await api('/kug/parse', { method: 'POST', form })
    sheetIdx.value = preview.value.sheets[0]?.index ?? 0
  } catch (err) {
    parseError.value = err.message
  } finally {
    parsing.value = false
  }
}

async function doImport() {
  importing.value = true
  try {
    const form = new FormData()
    form.append('file', file.value)
    form.append('sheet', sheetIdx.value)
    form.append('group_ids', groupIds.value.join(','))
    form.append('include_self', includeSelf.value)
    form.append('include_practice', includePractice.value)
    form.append('make_stream', makeStream.value && groupIds.value.length > 1)
    form.append('create_terms', createTerms.value)
    result.value = await api('/kug/import', { method: 'POST', form })
    toast('КУГ импортирован')
    await loadTerms()  // новые периоды появятся в списке в шапке
    gridGroup.value = groupIds.value[0]
  } catch (err) {
    toast(err.message, 'bad')
  } finally {
    importing.value = false
  }
}

// --- сетка ---
const gridGroup = ref(null)
const grid = ref(null)
const editCell = ref(null)
const editValue = ref('')
const cellInput = ref(null)

async function loadGrid() {
  if (!gridGroup.value || !store.termId) { grid.value = null; return }
  grid.value = await api('/kug/grid', { params: { group_id: gridGroup.value, term_id: store.termId } })
}
watch([gridGroup, () => store.termId, tab], () => { if (tab.value === 'grid') loadGrid() })

const isEditing = (r, w) => editCell.value && editCell.value.id === r.id && editCell.value.week === w.monday
function startEdit(r, w) {
  if (!r.kug || isEditing(r, w)) return
  editCell.value = { id: r.id, week: w.monday }
  editValue.value = r.hours[w.monday] ?? ''
  nextTick(() => { const el = Array.isArray(cellInput.value) ? cellInput.value[0] : cellInput.value; el?.focus(); el?.select() })
}
function cancel() { editCell.value = null }
async function commit() {
  const cell = editCell.value
  if (!cell) return
  editCell.value = null
  const row = grid.value.rows.find(r => r.id === cell.id)
  const val = editValue.value === '' ? 0 : Number(editValue.value)
  if ((row.hours[cell.week] ?? 0) === val) return
  try {
    await api(`/curriculum/${cell.id}/weekly`, { method: 'PUT', body: { weekly: { [cell.week]: val } } })
    await loadGrid()
  } catch (err) { toast(err.message, 'bad') }
}

onMounted(async () => {
  groups.value = await api('/groups')
  gridGroup.value = groups.value[0]?.id ?? null
})
</script>

<style scoped>
.seg { display: inline-flex; flex-wrap: wrap; border: 1px solid var(--line-strong); border-radius: 6px; overflow: hidden; }
.seg button { border: none; border-radius: 0; border-right: 1px solid var(--line-strong); }
.seg button.active { background: var(--accent); color: #fff; }
.rows { max-height: 420px; overflow: auto; margin-top: 10px; }
tr.dim td { opacity: .45; }
.groups { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 4px 16px; margin: 8px 0 14px; }
.opts { display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px; }
.toolbar { align-items: flex-end; }
.toolbar .muted { flex: 1; min-width: 260px; }
.kug { max-height: calc(100vh - 260px); }
.kgrid { border-collapse: collapse; font-size: 12px; }
.kgrid th, .kgrid td { border: 1px solid var(--line); padding: 2px 4px; text-align: center; min-width: 38px; }
.kgrid thead th { position: sticky; top: 0; background: var(--panel-2); z-index: 2; font-weight: 600; }
.kgrid .name { position: sticky; left: 0; background: var(--panel); text-align: left; min-width: 220px; max-width: 280px; z-index: 1; }
.kgrid thead .name { z-index: 3; background: var(--panel-2); }
.kgrid .sum { font-weight: 700; background: var(--panel-2); }
.kgrid td.c { cursor: default; height: 38px; }
.kgrid td.kug { cursor: pointer; }
.kgrid td.kug:hover { outline: 2px solid var(--accent); outline-offset: -2px; }
.kgrid .off { background: repeating-linear-gradient(45deg, var(--panel-2), var(--panel-2) 4px, transparent 4px, transparent 8px); }
.kgrid .h { font-weight: 600; }
.kgrid .p { color: var(--accent); font-size: 11px; }
.kgrid td.editing { padding: 0; }
.kgrid td.editing input { width: 46px; min-height: 30px; padding: 2px; text-align: center; }
.kgrid tfoot td { background: var(--panel-2); font-weight: 600; }
.kgrid td.over { background: var(--bad-soft); color: var(--bad); }
.miss { color: var(--bad); font-weight: 600; }
.stream { color: var(--pref); font-weight: 600; }
.legend { margin-top: 8px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.sw { display: inline-block; width: 14px; height: 14px; border: 1px solid var(--line-strong); border-radius: 3px; }
.sw.kugc { outline: 2px solid var(--accent); outline-offset: -2px; }
.sw.offc { background: repeating-linear-gradient(45deg, var(--panel-2), var(--panel-2) 3px, transparent 3px, transparent 6px); }
.sw.overc { background: var(--bad-soft); }
</style>
