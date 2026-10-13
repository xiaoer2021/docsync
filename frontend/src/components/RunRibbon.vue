<script setup lang="ts">
import { computed } from 'vue';
const props = withDefaults(defineProps<{
    inserted: number;
    updated: number;
    unchanged: number;
    failed?: number;
    barOnly?: boolean;
}>(), { failed: 0, barOnly: false });
const parts = computed(() => {
    const raw = [
        { key: 'inserted', label: '新增', value: props.inserted },
        { key: 'updated', label: '更新', value: props.updated },
        { key: 'unchanged', label: '未变', value: props.unchanged },
        { key: 'failed', label: '坏行', value: props.failed },
    ];
    const total = raw.reduce((sum, p) => sum + Math.max(p.value, 0), 0);
    if (!total)
        return [];
    return raw
        .filter((p) => p.value > 0)
        .map((p) => ({ ...p, pct: (Math.max(p.value, 0) / total) * 100 }));
});
const total = computed(() => Math.max(props.inserted, 0) +
    Math.max(props.updated, 0) +
    Math.max(props.unchanged, 0) +
    Math.max(props.failed, 0));
const summary = computed(() => parts.value.map((p) => `${p.label} ${p.value}（${p.pct.toFixed(1)}%）`).join('　'));
</script>

<template>
  <div class="ribbon-wrap" :title="summary">
    <div v-if="parts.length" class="ribbon" role="img" :aria-label="summary">
      <span
        v-for="p in parts"
        :key="p.key"
        class="seg"
        :class="p.key"
        :style="{ width: `${p.pct}%` }"
      />
    </div>
    <div v-else class="ribbon empty-bar" />

    <div v-if="!barOnly" class="legend">
      <span v-for="p in parts" :key="p.key" class="legend-item">
        <i class="swatch" :class="p.key" />
        <span class="legend-label">{{ p.label }}</span>
        <b>{{ p.value }}</b>
      </span>
      <span v-if="!total" class="muted">没有数据</span>
    </div>
  </div>
</template>

<style scoped>
.ribbon-wrap {
  min-width: 0;
}

.ribbon {
  display: flex;
  width: 100%;
  height: 5px;
  border-radius: 999px;
  overflow: hidden;
  background: var(--surface-sunken);

  gap: 1px;
}

.empty-bar {
  display: block;
  height: 5px;
  border-radius: 999px;
  background: var(--surface-sunken);
}

.seg {
  display: block;
  height: 100%;

  min-width: 3px;
}

.seg.inserted {
  background: var(--brand);
}

.seg.updated {
  background: var(--warn);
}

.seg.unchanged {
  background: var(--text-4);
}

.seg.failed {
  background: var(--danger);
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 12px;
  margin-top: 5px;
  font-size: var(--fs-label);
  color: var(--text-2);
  line-height: 1.5;
}

.legend-item {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  white-space: nowrap;
}

.legend-label {
  color: var(--text-3);
}

.legend-item b {
  color: var(--text-1);
  font-weight: 600;
}

.swatch {
  width: 7px;
  height: 7px;
  border-radius: 2px;
  flex: none;
  align-self: center;
}

.swatch.inserted {
  background: var(--brand);
}

.swatch.updated {
  background: var(--warn);
}

.swatch.unchanged {
  background: var(--text-4);
}

.swatch.failed {
  background: var(--danger);
}
</style>
