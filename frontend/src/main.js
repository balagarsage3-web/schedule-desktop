import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import { auth } from './api'
import './style.css'

import Login from './views/Login.vue'
import Directories from './views/Directories.vue'
import Curriculum from './views/Curriculum.vue'
import Kug from './views/Kug.vue'
import Availability from './views/Availability.vue'
import Params from './views/Params.vue'
import Generate from './views/Generate.vue'
import Schedule from './views/Schedule.vue'
import Report from './views/Report.vue'
import Export from './views/Export.vue'
import PublicView from './views/PublicView.vue'

const routes = [
  { path: '/login', component: Login, meta: { public: true, bare: true } },
  { path: '/p/:token', component: PublicView, meta: { public: true, bare: true } },
  { path: '/', redirect: '/directories' },
  { path: '/directories', component: Directories, meta: { title: 'Справочники' } },
  { path: '/curriculum', component: Curriculum, meta: { title: 'Учебный план' } },
  { path: '/kug', component: Kug, meta: { title: 'Календарный учебный график' } },
  { path: '/availability', component: Availability, meta: { title: 'Доступность преподавателей' } },
  { path: '/params', component: Params, meta: { title: 'Параметры расчёта' } },
  { path: '/generate', component: Generate, meta: { title: 'Генерация' } },
  { path: '/schedule', component: Schedule, meta: { title: 'Расписание' } },
  { path: '/report', component: Report, meta: { title: 'Отчёт о качестве' } },
  { path: '/export', component: Export, meta: { title: 'Экспорт' } },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({ history: createWebHistory(), routes })
router.beforeEach(to => {
  if (!to.meta.public && !auth.token) return '/login'
  document.title = to.meta.title ? `${to.meta.title} — Расписание` : 'Расписание'
})

createApp(App).use(router).mount('#app')
