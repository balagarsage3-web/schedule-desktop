<template>
  <div class="wrap">
    <form class="card box" @submit.prevent="submit">
      <h1>Вход для методиста</h1>
      <p class="muted">Сервис автоматического составления расписания</p>
      <label class="field"><span>Логин</span><input v-model="login" type="text" autocomplete="username" required autofocus /></label>
      <label class="field"><span>Пароль</span><input v-model="password" type="password" autocomplete="current-password" required /></label>
      <p v-if="error" class="err">{{ error }}</p>
      <button class="primary" :disabled="busy">{{ busy ? 'Вход…' : 'Войти' }}</button>
    </form>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, setToken } from '../api'

const router = useRouter()
const login = ref('')
const password = ref('')
const error = ref('')
const busy = ref(false)

async function submit() {
  busy.value = true
  error.value = ''
  try {
    const r = await api('/auth/login', { method: 'POST', body: { login: login.value, password: password.value } })
    setToken(r.token, r.login)
    router.push('/')
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.wrap { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 16px; }
.box { width: min(380px, 100%); display: flex; flex-direction: column; gap: 14px; padding: 28px; }
.box h1 { margin: 0; }
.err { color: var(--bad); margin: 0; }
</style>
