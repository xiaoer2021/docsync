<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useAlreadyHere } from '@/composables/useAlreadyHere';
const ah = useAlreadyHere();
const box = ref({ top: 0, left: 0, width: 0, height: 0 });
const missing = ref(false);
function measure() {
    if (!ah.isOpen.value)
        return;
    const el = document.querySelector(ah.selector.value);
    if (!el) {
        missing.value = true;
        return;
    }
    missing.value = false;
    const r = el.getBoundingClientRect();
    box.value = {
        top: Math.max(r.top - 6, 4),
        left: Math.max(r.left - 6, 4),
        width: r.width + 12,
        height: r.height + 12,
    };
}
watch([() => ah.isOpen.value, () => ah.selector.value], async () => {
    if (!ah.isOpen.value)
        return;
    await nextTick();
    measure();
});
function onKey(event: KeyboardEvent) {
    if (event.key === 'Escape')
        ah.dismiss();
}
onMounted(() => {
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, true);
    window.addEventListener('keydown', onKey);
});
onBeforeUnmount(() => {
    window.removeEventListener('resize', measure);
    window.removeEventListener('scroll', measure, true);
    window.removeEventListener('keydown', onKey);
});
</script>

<template>
  <div v-if="ah.isOpen.value" class="here-layer" @click="ah.dismiss()">
    <div
      v-if="!missing"
      class="here-box"
      :style="{
        top: `${box.top}px`,
        left: `${box.left}px`,
        width: `${box.width}px`,
        height: `${box.height}px`,
      }"
    />

    <div
      class="here-tip"
      :style="{ top: `${Math.max(box.top + box.height + 12, 80)}px` }"
      @click.stop
    >
      <span class="here-tip-text">
        这个入口指的就是当前这一页 ——
        <b>{{ ah.label.value }}</b>
      </span>
      <el-button size="small" type="primary" @click="ah.dismiss()">知道了</el-button>
    </div>
  </div>
</template>

<style scoped>

.here-layer {
  position: fixed;
  inset: 0;
  z-index: 1990;
}

.here-box {
  position: absolute;
  border: 2px solid var(--brand);
  border-radius: var(--radius);
  box-shadow: 0 0 0 9999px rgb(15 23 42 / 22%);
  pointer-events: none;
  animation: here-pulse 1.4s var(--ease-out) 2;
}

@keyframes here-pulse {
  0%,
  100% {
    border-color: var(--brand);
  }
  50% {
    border-color: transparent;
  }
}

.here-tip {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 14px;
  background: var(--surface);
  border: 1px solid var(--brand);
  border-radius: var(--radius);
  box-shadow: var(--shadow-pop);
  white-space: nowrap;
}

.here-tip-text {
  font-size: var(--fs-body);
  color: var(--text-1);
}

.here-tip-text b {
  color: var(--brand);
}
</style>
