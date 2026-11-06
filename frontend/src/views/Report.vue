<template>
  <div v-if="!store.versionId && loaded" class="card empty">Нет версии расписания. <router-link to="/generate">Составить</router-link></div>
  <div v-else-if="rep">
    <div class="row" style="margin-bottom:14px">
      <select :value="store.versionId" @change="pick(Number($event.target.value))">
        <option v-for="v in store.versions" :key="v.id" :value="v.id">№{{ v.number }} · {{ v.name }}</option>
      </select>
      <span class="muted small">Пересчитывается по текущему состоянию — с учётом ручных правок.</span>
    </div>

    <div class="kpis">
      <div class="card kpi"><div class="muted small">Итоговый штраф</div><div class="big">{{ rep.soft.score }}</div><div class="muted small">чем меньше, тем лучше</div></div>
      <div class="card kpi" :class="rep.hard.count ? 'bad' : 'ok'"><div class="muted small">Нарушений жёстких правил</div><div class="big">{{ rep.hard.count }}</div>
        <div class="muted small">{{ rep.hard.count ? 'нужно исправить' : 'расписание корректно' }}</div></div>
      <div class="card kpi"><div class="muted small">Пар за период</div><div class="big">{{ rep.lessons }}</div><div class="muted small">учебных недель: {{ rep.load.weeks }}</div></div>
      <div class="card kpi"><div class="muted small">Решатель</div><div class="big sm">{{ solverText }}</div>
        <div class="muted small"><template v-if="rep.solver.solver_time != null">за {{ rep.solver.solver_time }} с</template>
          <template v-if="rep.solver.weeks">, недель {{ rep.solver.weeks }} (оптимально {{ rep.solver.weeks_optimal }} из {{ rep.solver.weeks_solved }} разных)</template></div></div>
    </div>

    <div class="card">
      <h2>Мягкие правила</h2>
      <div class="table-wrap">
        <table class="data">
          <thead><tr><th>Правило</th><th class="num">Нарушений за период</th><th class="num">Вес</th><th class="num">Штраф</th></tr></thead>
          <tbody>
            <tr v-for="i in rep.soft.items" :key="i.key">
              <td>{{ i.label }}</td><td class="num">{{ i.count }}</td><td class="num">{{ i.weight }}</td>
              <td class="num"><strong>{{ i.penalty }}</strong></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="rep.hard.count || rep.expand_problems.length" class="card">
      <h2>Жёсткие правила — что исправить</h2>
      <ul class="issues">
        <li v-for="(p, i) in rep.expand_problems" :key="'e' + i" class="warning">{{ p }}</li>
        <li v-for="(h, i) in rep.hard.items" :key="i" class="error">{{ h }}</li>
      </ul>
    </div>

    <div class="two">
      <div class="card">
        <h2>Загрузка преподавателей</h2>
        <p class="muted small">Среднее число пар в неделю / максимум.</p>
        <div v-for="t in rep.load.teachers" :key="t.name" class="bar-row">
          <span class="name" :title="t.name">{{ t.name }}</span>
          <span class="bar"><span :style="{ width: Math.min(100, t.per_week / t.max_per_week * 100) + '%' }" /></span>
          <span class="num">{{ t.per_week }} / {{ t.max_per_week }}</span>
        </div>
      </div>
      <div class="card">
        <h2>Загрузка аудиторий</h2>
        <p class="muted small">Доля занятых слотов в неделю.</p>
        <div v-for="r in rep.load.rooms" :key="r.name" class="bar-row">
          <span class="name" :title="r.type">{{ r.name }} <span class="muted small">{{ r.type }}</span></span>
          <span class="bar"><span :style="{ width: r.utilization + '%' }" /></span>
          <span class="num">{{ r.utilization }}%</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import { loadVersions, setVersion, store } from '../store'

const rep = ref(null)
const loaded = ref(false)
const solverText = computed(() => ({ optimal: 'оптимум', feasible: 'лучшее найденное', stopped: 'остановлен' })[rep.value?.solver.solver_status] || '—')

async function load() {
  rep.value = store.versionId ? await api(`/versions/${store.versionId}/report`) : null
}
onMounted(async () => {
  await loadVersions()
  loaded.value = true
  await load()
})
async function pick(id) { setVersion(id); await load() }
</script>

<style scoped>
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
.kpi .big { font-size: 30px; font-weight: 700; font-variant-numeric: tabular-nums; }
.kpi .big.sm { font-size: 20px; padding: 6px 0; }
.kpi.ok .big { color: var(--ok); }
.kpi.bad .big { color: var(--bad); }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.bar-row { display: grid; grid-template-columns: 170px 1fr 70px; gap: 8px; align-items: center; padding: 2px 0; font-size: 13px; }
.bar-row .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar { height: 8px; background: var(--panel-2); border-radius: 999px; overflow: hidden; border: 1px solid var(--line); }
.bar > span { display: block; height: 100%; background: var(--accent); }
.num { text-align: right; font-variant-numeric: tabular-nums; }
@media (max-width: 900px) { .kpis { grid-template-columns: 1fr 1fr; } .two { grid-template-columns: 1fr; } }
</style>
