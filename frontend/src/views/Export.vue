<template>
  <div v-if="!store.versionId && loaded" class="card empty">Нет версии расписания. <router-link to="/generate">Составить</router-link></div>
  <div v-else class="card">
    <div class="grid-form">
      <label class="field"><span>Версия</span>
        <select :value="store.versionId" @change="setVersion(Number($event.target.value))">
          <option v-for="v in store.versions" :key="v.id" :value="v.id">№{{ v.number }} · {{ v.name }}</option>
        </select>
      </label>
      <label class="field"><span>Формат</span>
        <select v-model="format">
          <option value="xlsx">Excel (.xlsx) — таблица, лист на каждого</option>
          <option value="pdf">PDF — печатная недельная сетка</option>
          <option value="ics">iCal (.ics) — календарь</option>
        </select>
      </label>
      <label class="field"><span>Разрез</span>
        <select v-model="mode"><option value="group">По группам</option><option value="teacher">По преподавателям</option></select>
      </label>
      <label class="field"><span>Фильтр</span>
        <select v-model="entity">
          <option v-if="format !== 'ics'" :value="null">{{ mode === 'group' ? 'Все группы (вся организация)' : 'Все преподаватели' }}</option>
          <option v-for="e in list" :key="e.id" :value="e.id">{{ e.name }}</option>
        </select>
      </label>
      <label v-if="format === 'pdf'" class="field"><span>Неделя (любой день)</span><input v-model="week" type="date" /></label>
    </div>
    <p class="muted small" style="margin-top:12px">{{ hint }}</p>
    <button class="primary" :disabled="busy || (format === 'ics' && !entity)" @click="go">{{ busy ? 'Формирование…' : 'Скачать' }}</button>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api, download } from '../api'
import { loadVersions, setVersion, store, toast } from '../store'

const format = ref('xlsx')
const mode = ref('group')
const entity = ref(null)
const week = ref('')
const busy = ref(false)
const loaded = ref(false)
const groups = ref([])
const teachers = ref([])
const list = computed(() => (mode.value === 'group' ? groups.value : teachers.value))
const hint = computed(() => ({
  xlsx: 'Все пары за период списком: дата, день, пара, время, дисциплина, преподаватель/группа, аудитория. В шапке — период, версия и дата формирования.',
  pdf: 'Сетка «пара × день» на выбранную неделю; при выборе «все» — по странице на каждую группу или преподавателя.',
  ics: 'Файл календаря для Google Calendar, Яндекс.Календаря, Outlook. Выберите одну группу или преподавателя.',
})[format.value])

watch([mode, format], () => { if (format.value === 'ics' && !entity.value) entity.value = list.value[0]?.id ?? null })
watch(mode, () => { entity.value = format.value === 'ics' ? list.value[0]?.id ?? null : null })

onMounted(async () => {
  await loadVersions()
  loaded.value = true
  const [g, t] = await Promise.all([api('/groups'), api('/teachers')])
  groups.value = g.map(x => ({ id: x.id, name: x.name }))
  teachers.value = t.map(x => ({ id: x.id, name: x.full_name }))
  const term = store.terms.find(x => x.id === store.termId)
  if (term) week.value = term.start_date
})

async function go() {
  busy.value = true
  try {
    await download(`/export/${store.versionId}/${format.value}`, { mode: mode.value, entity_id: entity.value, week: format.value === 'pdf' ? week.value : null },
      `schedule.${format.value}`)
  } catch (e) { toast(e.message, 'bad') } finally { busy.value = false }
}
</script>
