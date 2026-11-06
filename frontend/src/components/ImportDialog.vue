<template>
  <Modal :title="`Импорт: ${title}`" @close="$emit('close')">
    <ol class="steps">
      <li>Скачайте шаблон и заполните его (первая строка — заголовок).
        <button class="sm" @click="template">Скачать шаблон .xlsx</button></li>
      <li>Загрузите файл Excel (.xlsx) или CSV (разделитель «;» или «,»).</li>
    </ol>
    <p class="muted small">Записи с тем же названием обновятся. Если в файле есть ошибки — ничего не сохранится, а ниже появится список строк с причинами.</p>
    <input ref="fileInput" type="file" accept=".xlsx,.csv" @change="pick" />
    <div v-if="result" class="result">
      <p v-if="result.ok" class="badge ok">Готово: добавлено {{ result.created }}, обновлено {{ result.updated }}</p>
      <template v-else>
        <p class="badge bad">Найдено ошибок: {{ result.errors.length }}. Ничего не сохранено.</p>
        <div class="table-wrap errs">
          <table class="data">
            <thead><tr><th class="num">Строка</th><th>Причина</th></tr></thead>
            <tbody><tr v-for="(e, i) in result.errors" :key="i"><td class="num">{{ e.row }}</td><td>{{ e.message }}</td></tr></tbody>
          </table>
        </div>
      </template>
    </div>
    <p v-if="error" class="badge bad">{{ error }}</p>
    <template #foot>
      <button @click="$emit('close')">Закрыть</button>
      <button class="primary" :disabled="!file || busy" @click="upload">{{ busy ? 'Загрузка…' : 'Загрузить' }}</button>
    </template>
  </Modal>
</template>

<script setup>
import { ref } from 'vue'
import Modal from './Modal.vue'
import { api, download } from '../api'

const props = defineProps({ entity: String, title: String })
const emit = defineEmits(['close', 'done'])
const file = ref(null)
const result = ref(null)
const error = ref('')
const busy = ref(false)

function pick(e) {
  file.value = e.target.files[0] || null
  result.value = null
  error.value = ''
}

async function template() {
  try { await download(`/import/template/${props.entity}`, null, `template_${props.entity}.xlsx`) } catch (e) { error.value = e.message }
}

async function upload() {
  busy.value = true
  error.value = ''
  try {
    const form = new FormData()
    form.append('file', file.value)
    result.value = await api(`/import/${props.entity}`, { method: 'POST', form })
    if (result.value.ok) emit('done')
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.steps { padding-left: 20px; display: flex; flex-direction: column; gap: 8px; margin: 0 0 10px; }
.steps button { margin-left: 6px; }
.result { margin-top: 12px; }
.errs { max-height: 280px; overflow: auto; margin-top: 8px; }
</style>
