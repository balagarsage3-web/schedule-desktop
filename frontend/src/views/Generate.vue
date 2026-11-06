<template>
  <div v-if="!store.termId" class="card empty">Сначала создайте учебный период в «Параметрах расчёта».</div>
  <div v-else>
    <div class="card">
      <div class="row">
        <h2 style="margin:0">Проверка данных</h2>
        <span class="spacer" />
        <button :disabled="checking" @click="check">{{ checking ? 'Проверка…' : 'Проверить ещё раз' }}</button>
      </div>
      <p v-if="pre" class="muted small" style="margin-top:8px">
        Групп: {{ pre.stats.groups }}, преподавателей: {{ pre.stats.teachers }}, аудиторий: {{ pre.stats.rooms }},
        строк плана: {{ pre.stats.curriculum }}, пар в неделю: {{ pre.stats.weekly_lessons }}.
      </p>
      <ul v-if="pre && pre.issues.length" class="issues">
        <li v-for="(i, k) in pre.issues" :key="k" :class="i.level">{{ i.message }}</li>
      </ul>
      <p v-else-if="pre" class="badge ok">Противоречий не найдено — можно составлять расписание</p>
    </div>

    <div class="card">
      <div class="row end">
        <label class="field" title="Общее время на весь период; делится между разными неделями"><span>Лимит времени на период, с</span><input v-model.number="limit" type="number" min="5" max="1800" style="width:120px" /></label>
        <button class="primary big" :disabled="running || (pre && !pre.ok)" @click="start">Составить расписание</button>
        <button v-if="running" class="danger" @click="stop">Остановить</button>
      </div>

      <div v-if="job" class="job">
        <div class="row">
          <strong>{{ statusText }}</strong>
          <span class="spacer" />
          <span class="muted small">{{ job.elapsed }} с из {{ job.time_limit }}</span>
        </div>
        <div class="progress"><div :style="{ width: job.progress + '%' }" /></div>
        <p v-if="job.weeks_total" class="muted small">Неделя {{ job.weeks_done }} из {{ job.weeks_total }}
          — каждая неделя строится по своей нагрузке (КУГ), одинаковые недели повторяются.</p>
        <p v-if="job.message" :class="['badge', job.status === 'done' ? 'ok' : finished ? 'bad' : '']">{{ job.message }}</p>
        <ul v-if="job.status === 'invalid'" class="issues">
          <li v-for="(i, k) in job.issues.filter(x => x.level === 'error')" :key="k" class="error">{{ i.message }}</li>
        </ul>
        <ul v-if="job.hints.length" class="issues">
          <li v-for="(h, k) in job.hints" :key="k" class="info">{{ h }}</li>
        </ul>
        <div v-if="job.status === 'done'" class="row" style="margin-top:10px">
          <router-link to="/schedule"><button class="primary">Открыть расписание</button></router-link>
          <router-link to="/report"><button>Отчёт о качестве</button></router-link>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="row" style="margin-bottom:12px">
        <h2 style="margin:0">Версии расписания</h2>
        <span class="spacer" />
        <button v-if="store.versions.length > 1" class="danger ghost" @click="removeAll">Удалить все версии</button>
      </div>
      <div class="table-wrap">
        <table class="data">
          <thead><tr><th>№</th><th>Название</th><th>Создана</th><th class="num">Штраф</th><th class="num">Конфликтов</th><th>Ссылка</th><th /></tr></thead>
          <tbody>
            <tr v-for="v in store.versions" :key="v.id">
              <td>{{ v.number }}</td>
              <td>{{ v.name }} <span v-if="v.id === store.versionId" class="badge ok">текущая</span></td>
              <td>{{ v.created_at.replace('T', ' ') }}</td>
              <td class="num">{{ v.score }}</td>
              <td class="num"><span :class="['badge', v.hard_count ? 'bad' : 'ok']">{{ v.hard_count }}</span></td>
              <td><span v-if="v.public_token" class="badge">опубликована</span></td>
              <td class="actions">
                <button class="sm ghost" @click="choose(v)">Выбрать</button>
                <button class="sm ghost" @click="rename(v)">Переименовать</button>
                <button class="sm ghost danger" @click="remove(v)">Удалить</button>
              </td>
            </tr>
            <tr v-if="!store.versions.length"><td colspan="7" class="empty">Пока нет ни одной версии</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api'
import { loadVersions, setVersion, store, toast } from '../store'

const pre = ref(null)
const checking = ref(false)
const job = ref(null)
const limit = ref(60)
let timer = null

const STATUS = {
  queued: 'В очереди…', precheck: 'Проверка данных…', solving: 'Решатель расставляет недели…', saving: 'Сохранение…',
  done: 'Готово', invalid: 'Данные противоречивы', infeasible: 'Решения нет', timeout: 'Время вышло', stopped: 'Остановлено', failed: 'Ошибка',
}
const running = computed(() => job.value && ['queued', 'precheck', 'solving', 'saving'].includes(job.value.status))
const finished = computed(() => job.value && !running.value)
const statusText = computed(() => STATUS[job.value?.status] || job.value?.status)

async function check() {
  checking.value = true
  try { pre.value = await api(`/terms/${store.termId}/precheck`) } catch (e) { toast(e.message, 'bad') } finally { checking.value = false }
}

async function poll() {
  if (!job.value) return
  job.value = await api(`/jobs/${job.value.id}`)
  if (running.value) timer = setTimeout(poll, 700)
  else if (job.value.status === 'done') {
    await loadVersions()
    setVersion(job.value.version_id)
  }
}

async function start() {
  try {
    job.value = await api('/generate', { method: 'POST', body: { term_id: store.termId, time_limit: limit.value } })
    poll()
  } catch (e) { toast(e.message, 'bad') }
}

async function stop() {
  await api(`/jobs/${job.value.id}/stop`, { method: 'POST' })
}

onMounted(async () => {
  const t = store.terms.find(x => x.id === store.termId)
  if (t) limit.value = t.time_limit
  if (!store.termId) return
  await Promise.all([check(), loadVersions()])
  const active = await api('/jobs/active')
  if (active) { job.value = active; poll() }
})
onUnmounted(() => clearTimeout(timer))

function choose(v) { setVersion(v.id); toast(`Выбрана версия ${v.number}`) }
async function rename(v) {
  const name = prompt('Название версии', v.name)
  if (!name) return
  await api(`/versions/${v.id}`, { method: 'PATCH', body: { name } })
  await loadVersions()
}
async function removeAll() {
  if (!confirm(`Удалить все версии расписания этого периода (${store.versions.length})?`)) return
  await api('/bulk-delete/versions', { method: 'POST', body: { ids: store.versions.map(v => v.id) } })
  await loadVersions()
  toast('Версии удалены')
}
async function remove(v) {
  if (!confirm(`Удалить версию ${v.number}?`)) return
  await api(`/versions/${v.id}`, { method: 'DELETE' })
  await loadVersions()
}
</script>

<style scoped>
.big { min-height: 40px; padding: 8px 18px; font-weight: 600; }
.job { margin-top: 16px; display: flex; flex-direction: column; gap: 8px; }
.job p { margin: 0; }
</style>
