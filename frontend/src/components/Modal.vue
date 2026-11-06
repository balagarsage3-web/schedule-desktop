<template>
  <div class="modal-bg" @mousedown.self="$emit('close')" @keydown.esc="$emit('close')">
    <div class="modal" role="dialog" aria-modal="true" :style="width ? { width } : null">
      <h2 v-if="title">{{ title }}</h2>
      <slot />
      <div v-if="$slots.foot" class="foot"><slot name="foot" /></div>
    </div>
  </div>
</template>

<script setup>
defineProps({ title: String, width: String })
defineEmits(['close'])
</script>
