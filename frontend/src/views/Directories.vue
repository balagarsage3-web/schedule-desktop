<template>
  <div>
    <div class="tabs">
      <button v-for="t in tabs" :key="t.key" :class="{ active: tab === t.key }" @click="tab = t.key">{{ t.label }}</button>
    </div>
    <EntityTable v-if="tab === 'groups'" endpoint="/groups" title="Группы" import-entity="groups" bulk-entity="groups" :fields="[
      { key: 'name', label: 'Название' },
      { key: 'course', label: 'Курс / направление', required: false },
      { key: 'size', label: 'Студентов', type: 'number', min: 1, default: 25 },
      { key: 'shift', label: 'Смена', type: 'select', options: toOpts(meta.shifts) },
    ]" />
    <EntityTable v-if="tab === 'subjects'" endpoint="/subjects" title="Дисциплины" import-entity="subjects" bulk-entity="subjects"
      :fields="[
        { key: 'name', label: 'Название' },
        { key: 'lesson_type', label: 'Тип занятий', type: 'select', options: toOpts(meta.lesson_types) },
        { key: 'room_type', label: 'Нужная аудитория', type: 'select', options: toOpts(meta.room_types) },
      ]" @changed="r => (subjects = r)" />
    <EntityTable v-if="tab === 'teachers'" endpoint="/teachers" title="Преподаватели" import-entity="teachers" bulk-entity="teachers" :fields="[
      { key: 'full_name', label: 'ФИО' },
      { key: 'subject_ids', label: 'Дисциплины', type: 'multi', options: subjectOpts },
      { key: 'max_per_day', label: 'Макс. пар в день', type: 'number', min: 1, max: 12, default: 4 },
      { key: 'max_per_week', label: 'Макс. пар в неделю', type: 'number', min: 1, max: 60, default: 18 },
    ]" />
    <EntityTable v-if="tab === 'rooms'" endpoint="/rooms" title="Аудитории" import-entity="rooms" bulk-entity="rooms" :fields="[
      { key: 'number', label: 'Номер' },
      { key: 'capacity', label: 'Вместимость', type: 'number', min: 1, default: 30 },
      { key: 'room_type', label: 'Тип', type: 'select', options: toOpts(meta.room_types) },
      { key: 'active', label: 'Доступна', type: 'bool' },
    ]" />
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import EntityTable from '../components/EntityTable.vue'
import { api } from '../api'

const tabs = [
  { key: 'groups', label: 'Группы' },
  { key: 'subjects', label: 'Дисциплины' },
  { key: 'teachers', label: 'Преподаватели' },
  { key: 'rooms', label: 'Аудитории' },
]
const tab = ref('groups')
const meta = reactive({ shifts: [], lesson_types: [], room_types: [] })
const subjects = ref([])
const toOpts = list => list.map(x => ({ value: x, label: x }))
const subjectOpts = () => subjects.value.map(s => ({ value: s.id, label: `${s.name} (${s.lesson_type})` }))

onMounted(async () => {
  Object.assign(meta, await api('/meta'))
  subjects.value = await api('/subjects')
})
</script>
