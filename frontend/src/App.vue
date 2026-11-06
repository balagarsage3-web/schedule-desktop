<template>
  <router-view v-if="$route.meta.bare" />
  <div v-else class="layout" :class="{ open: menuOpen }">
    <aside class="side">
      <div class="brand">
        <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden="true">
          <rect x="3" y="5" width="26" height="24" rx="4" fill="currentColor" opacity=".9" />
          <g fill="var(--panel)"><rect x="7" y="15" width="5" height="4" rx="1" /><rect x="14" y="15" width="5" height="4" rx="1" />
            <rect x="21" y="15" width="5" height="4" rx="1" /><rect x="7" y="21" width="5" height="4" rx="1" /><rect x="14" y="21" width="5" height="4" rx="1" /></g>
        </svg>
        <span>Расписание</span>
      </div>
      <nav @click="menuOpen = false">
        <div class="nav-group">Данные</div>
        <router-link to="/directories">Справочники</router-link>
        <router-link to="/kug">КУГ</router-link>
        <router-link to="/curriculum">Учебный план</router-link>
        <router-link to="/availability">Доступность</router-link>
        <router-link to="/params">Параметры расчёта</router-link>
        <div class="nav-group">Расписание</div>
        <router-link to="/generate">Генерация</router-link>
        <router-link to="/schedule">Сетка расписания</router-link>
        <router-link to="/report">Отчёт о качестве</router-link>
        <router-link to="/export">Экспорт</router-link>
      </nav>
      <div class="side-foot">
        <span class="muted small">{{ auth.login || 'методист' }}</span>
        <button class="sm ghost" @click="logout">Выйти</button>
      </div>
    </aside>
    <div class="main">
      <header class="top">
        <button class="ghost burger" aria-label="Меню" @click="menuOpen = !menuOpen">☰</button>
        <strong class="title">{{ $route.meta.title }}</strong>
        <span class="spacer" />
        <label class="term-pick">
          <span class="muted small">Период</span>
          <select :value="store.termId" @change="onTerm($event.target.value)">
            <option v-if="!store.terms.length" :value="null">— нет периодов —</option>
            <option v-for="t in store.terms" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select>
        </label>
      </header>
      <main class="content">
        <router-view :key="store.termId" />
      </main>
    </div>
    <div class="scrim" @click="menuOpen = false" />
  </div>
  <div class="toasts">
    <div v-for="t in store.toasts" :key="t.id" class="toast" :class="t.kind">{{ t.text }}</div>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api, auth, setToken } from './api'
import { loadTerms, setTerm, store } from './store'

const router = useRouter()
const menuOpen = ref(false)

async function init() {
  if (!auth.token) return
  try {
    const me = await api('/auth/me')
    auth.login = me.login
    await loadTerms()
  } catch { /* 401 обработан в api */ }
}
onMounted(init)
watch(() => auth.token, t => { if (t) init() })

function onTerm(v) {
  setTerm(Number(v) || null)
}

function logout() {
  setToken('')
  router.push('/login')
}
</script>

<style scoped>
.layout { display: grid; grid-template-columns: 220px 1fr; min-height: 100vh; }
.side { background: var(--panel); border-right: 1px solid var(--line); display: flex; flex-direction: column; position: sticky; top: 0; height: 100vh; }
.brand { display: flex; align-items: center; gap: 10px; padding: 16px; font-weight: 700; font-size: 16px; color: var(--accent); }
.brand span { color: var(--text); }
nav { display: flex; flex-direction: column; padding: 0 8px; gap: 1px; flex: 1; overflow-y: auto; }
.nav-group { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); padding: 14px 10px 6px; }
nav a { padding: 7px 10px; border-radius: 6px; color: var(--text); text-decoration: none; }
nav a:hover { background: var(--panel-2); }
nav a.router-link-active { background: var(--accent-soft); color: var(--accent); font-weight: 600; }
.side-foot { padding: 12px 16px; border-top: 1px solid var(--line); display: flex; align-items: center; justify-content: space-between; }
.main { min-width: 0; display: flex; flex-direction: column; }
.top { display: flex; align-items: center; gap: 12px; padding: 10px 20px; background: var(--panel); border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 10; }
.top .title { font-size: 15px; }
.term-pick { display: flex; align-items: center; gap: 8px; }
.term-pick select { max-width: 240px; }
.content { padding: 20px; max-width: 1500px; width: 100%; }
.burger { display: none; font-size: 18px; }
.scrim { display: none; }

@media (max-width: 860px) {
  .layout { grid-template-columns: 1fr; }
  .side { position: fixed; left: 0; top: 0; bottom: 0; width: 240px; z-index: 40; transform: translateX(-100%); transition: transform .2s; }
  .layout.open .side { transform: none; }
  .layout.open .scrim { display: block; position: fixed; inset: 0; background: rgba(0, 0, 0, .35); z-index: 30; }
  .burger { display: inline-block; }
  .content { padding: 16px; }
  .top { padding: 8px 16px; }
  .term-pick .muted { display: none; }
  .term-pick select { max-width: 150px; }
}
</style>
