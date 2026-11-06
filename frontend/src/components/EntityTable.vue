<template>
  <div>
    <div class="row toolbar">
      <input v-model="q" type="search" placeholder="Поиск…" class="search" />
      <slot name="filters" />
      <span class="muted small">{{ filtered.length }} из {{ rows.length }}</span>
      <span class="spacer" />
      <template v-if="bulkEntity">
        <slot v-if="selected.size" name="bulk" :ids="[...selected]" :reload="load" />
        <button v-if="selected.size" class="danger" @click="removeSelected">Удалить выбранные ({{ selected.size }})</button>
        <button v-if="rows.length" class="danger ghost" @click="removeAll">Удалить все</button>
      </template>
      <button v-if="importEntity" @click="showImport = true">Импорт из Excel</button>
      <button class="primary" @click="openEdit(null)">Добавить</button>
    </div>
    <div class="table-wrap">
      <table class="data">
        <thead>
          <tr>
            <th v-if="bulkEntity" class="sel">
              <input type="checkbox" :checked="allChecked" :indeterminate.prop="someChecked" title="Выбрать все найденные" @change="toggleAll($event.target.checked)" />
            </th>
            <th v-for="f in fields" :key="f.key" :class="{ num: f.type === 'number' }">{{ f.label }}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in filtered" :key="r.id" :class="[{ picked: selected.has(r.id) }, rowClass ? rowClass(r) : '']">
            <td v-if="bulkEntity" class="sel"><input type="checkbox" :checked="selected.has(r.id)" @change="toggle(r.id, $event.target.checked)" /></td>
            <td v-for="f in fields" :key="f.key" :class="[{ num: f.type === 'number' }, f.cellClass ? f.cellClass(r) : '']"
                :title="f.title ? f.title(r) : null">{{ show(r, f) }}</td>
            <td class="actions">
              <button class="sm ghost" @click="openEdit(r)">Изменить</button>
              <button class="sm ghost danger" @click="remove(r)">Удалить</button>
            </td>
          </tr>
          <tr v-if="!filtered.length"><td :colspan="fields.length + (bulkEntity ? 2 : 1)" class="empty">{{ rows.length ? 'Ничего не найдено' : 'Пока пусто — добавьте запись или импортируйте файл' }}</td></tr>
        </tbody>
      </table>
    </div>

    <Modal v-if="editing" :title="editing.id ? 'Изменить' : 'Добавить'" @close="editing = null">
      <form class="form" @submit.prevent="save">
        <label v-for="f in formFields" :key="f.key" :class="f.type === 'bool' ? 'check' : 'field'">
          <template v-if="f.type === 'bool'">
            <input v-model="editing[f.key]" type="checkbox" /> {{ f.label }}
          </template>
          <template v-else-if="f.lockedIf && f.lockedIf(editing)">
            <span>{{ f.label }}</span>
            <span class="locked">{{ f.lockedText || 'задаётся автоматически' }}</span>
          </template>
          <template v-else>
            <span>{{ f.label }}</span>
            <select v-if="f.type === 'select'" v-model="editing[f.key]" :required="!f.nullable">
              <option v-if="f.nullable" :value="null">{{ f.nullLabel || '— не выбрано —' }}</option>
              <option v-for="o in opts(f)" :key="o.value" :value="o.value">{{ o.label }}</option>
            </select>
            <div v-else-if="f.type === 'multi'" class="multi">
              <label v-for="o in opts(f)" :key="o.value" class="check">
                <input v-model="editing[f.key]" type="checkbox" :value="o.value" /> {{ o.label }}
              </label>
              <span v-if="!opts(f).length" class="muted small">Справочник пуст</span>
            </div>
            <input v-else v-model="editing[f.key]" :type="['number', 'time', 'date'].includes(f.type) ? f.type : 'text'"
                   :min="f.min" :max="f.max" :required="f.required !== false" />
            <span v-if="f.help" class="muted small">{{ f.help }}</span>
          </template>
        </label>
        <p v-if="error" class="badge bad">{{ error }}</p>
        <div class="foot">
          <button type="button" @click="editing = null">Отмена</button>
          <button class="primary" :disabled="busy">Сохранить</button>
        </div>
      </form>
    </Modal>

    <ImportDialog v-if="showImport" :entity="importEntity" :title="title" @close="showImport = false" @done="load" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import Modal from './Modal.vue'
import ImportDialog from './ImportDialog.vue'
import { api } from '../api'
import { toast } from '../store'

const props = defineProps({
  endpoint: String,
  fields: Array,
  title: String,
  importEntity: String,
  bulkEntity: String,   // имя справочника для массового удаления (/bulk-delete/{bulkEntity})
  defaults: { type: Object, default: () => ({}) },
  filter: Function,     // дополнительный фильтр строк (row) => bool
  rowClass: Function,
})
const emit = defineEmits(['changed'])

const rows = ref([])
const q = ref('')
const editing = ref(null)
const error = ref('')
const busy = ref(false)
const showImport = ref(false)

const opts = f => (typeof f.options === 'function' ? f.options() : f.options) || []

function show(r, f) {
  if (f.format) return f.format(r)
  const v = r[f.key]
  if (f.type === 'bool') return v ? 'да' : 'нет'
  if (f.type === 'time') return String(v || '').slice(0, 5)
  if (f.type === 'date') return v ? new Date(v + 'T00:00').toLocaleDateString('ru-RU') : ''
  if (f.type === 'select') return v == null ? (f.nullLabel || '—') : (opts(f).find(o => o.value === v)?.label ?? v)
  if (f.type === 'multi') return (v || []).map(x => opts(f).find(o => o.value === x)?.label ?? x).join(', ')
  return v
}

const formFields = computed(() => props.fields.filter(f => f.form !== false))

const filtered = computed(() => {
  const s = q.value.trim().toLowerCase()
  const base = props.filter ? rows.value.filter(props.filter) : rows.value
  if (!s) return base
  return base.filter(r => props.fields.some(f => String(show(r, f) ?? '').toLowerCase().includes(s)))
})

async function load() {
  rows.value = await api(props.endpoint)
  const ids = new Set(rows.value.map(r => r.id))
  selected.value = new Set([...selected.value].filter(id => ids.has(id)))
  emit('changed', rows.value)
}

// --- выбор и массовое удаление ---
const selected = ref(new Set())
const allChecked = computed(() => filtered.value.length > 0 && filtered.value.every(r => selected.value.has(r.id)))
const someChecked = computed(() => !allChecked.value && filtered.value.some(r => selected.value.has(r.id)))
function toggle(id, on) {
  const s = new Set(selected.value)
  on ? s.add(id) : s.delete(id)
  selected.value = s
}
function toggleAll(on) {
  const s = new Set(selected.value)
  filtered.value.forEach(r => (on ? s.add(r.id) : s.delete(r.id)))
  selected.value = s
}
async function bulk(body, question) {
  if (!confirm(question + '\nСвязанные строки учебного плана и пары расписания тоже будут удалены.')) return
  try {
    const r = await api(`/bulk-delete/${props.bulkEntity}`, { method: 'POST', body })
    toast(`Удалено: ${r.deleted}`)
    selected.value = new Set()
    await load()
  } catch (e) { toast(e.message, 'bad') }
}
const removeSelected = () => bulk({ ids: [...selected.value] }, `Удалить выбранные записи (${selected.value.size})?`)
const removeAll = () => bulk({ all: true }, `Удалить ВСЕ записи «${props.title}» (${rows.value.length})?`)
onMounted(load)
defineExpose({ load })

function openEdit(r) {
  error.value = ''
  if (r) editing.value = JSON.parse(JSON.stringify(r))
  else {
    const d = {}
    formFields.value.forEach(f => {
      d[f.key] = f.type === 'multi' ? [] : f.type === 'bool' ? true
        : (f.default ?? (f.type === 'select' ? (f.nullable ? null : opts(f)[0]?.value) : f.type === 'date' ? null : ''))
    })
    editing.value = { ...d, ...props.defaults }
  }
}

async function save() {
  busy.value = true
  error.value = ''
  try {
    const body = { ...editing.value }
    formFields.value.forEach(f => {
      if (f.type === 'number') body[f.key] = Number(body[f.key])
      if (f.type === 'date' && !body[f.key]) body[f.key] = null
    })
    if (body.id) await api(`${props.endpoint}/${body.id}`, { method: 'PUT', body })
    else await api(props.endpoint, { method: 'POST', body })
    editing.value = null
    toast('Сохранено')
    await load()
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

async function remove(r) {
  if (!confirm('Удалить запись? Связанные строки учебного плана и пары расписания тоже будут удалены.')) return
  try {
    await api(`${props.endpoint}/${r.id}`, { method: 'DELETE' })
    toast('Удалено')
    await load()
  } catch (e) {
    toast(e.message, 'bad')
  }
}
</script>

<style scoped>
.toolbar { margin-bottom: 12px; }
.search { width: 260px; }
.sel { width: 36px; text-align: center; }
.sel input { width: 16px; height: 16px; cursor: pointer; }
tr.picked td { background: var(--accent-soft); }
.locked { color: var(--text); padding: 6px 0; }
td.missing { color: var(--bad); font-weight: 600; }
.form { display: flex; flex-direction: column; gap: 12px; }
.foot { display: flex; justify-content: flex-end; gap: 8px; }
.multi { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 4px 12px; max-height: 220px; overflow: auto;
  border: 1px solid var(--line); border-radius: 6px; padding: 8px; color: var(--text); }
@media (max-width: 600px) { .search { width: 100%; } }
</style>
