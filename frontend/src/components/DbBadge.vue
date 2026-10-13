<script setup lang="ts">
withDefaults(defineProps<{
    type: string;
    label?: string;
    size?: number;
}>(), { label: '', size: 16 });
const COLORS: Record<string, string> = {
    sqlserver: '#b32b2b',
    mysql: '#00758f',
    postgresql: '#336791',
    oracle: '#c74634',
    sqlite: '#0f80cc',
};
function colorOf(type: string): string {
    return COLORS[type] || 'var(--text-3)';
}
</script>

<template>
  <span class="db-icon" :title="label || type">
    <svg
      :width="size"
      :height="size"
      viewBox="0 0 24 24"
      fill="none"
      :style="{ color: colorOf(type) }"
      aria-hidden="true"
    >

      <ellipse cx="12" cy="6" rx="8" ry="3.2" fill="currentColor" />
      <path
        d="M4 6v12c0 1.77 3.58 3.2 8 3.2s8-1.43 8-3.2V6"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
      />
      <path
        d="M4 12c0 1.77 3.58 3.2 8 3.2s8-1.43 8-3.2"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
      />
    </svg>
    <span v-if="label" class="db-label">{{ label }}</span>
  </span>
</template>

<style scoped>
.db-icon {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  vertical-align: middle;
}

.db-label {
  font-size: var(--fs-label);
  color: var(--text-2);
}
</style>
