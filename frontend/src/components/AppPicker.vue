<script setup lang="ts">
import { platformOf } from '@/branding';
import PlatformIcon from '@/components/PlatformIcon.vue';
export interface PickableApp {
    id: number;
    name: string;
    platform?: string;
}
defineProps<{
    modelValue: number | null | undefined;
    apps: PickableApp[];
    placeholder?: string;
}>();
const emit = defineEmits<{
    (e: 'update:modelValue', value: number): void;
}>();
</script>

<template>
  <div class="app-tiles">
    <button
      v-for="app in apps"
      :key="app.id"
      type="button"
      class="app-tile"
      :class="{ on: app.id === modelValue }"
      :title="platformOf(app.platform).label"
      @click="emit('update:modelValue', app.id)"
    >
      <PlatformIcon :platform="app.platform" :size="30" />
      <span class="tile-name">{{ app.name }}</span>
      <span class="tile-platform">{{ platformOf(app.platform).label }}</span>
    </button>
    <div v-if="!apps.length" class="app-tile-empty">
      {{ placeholder || '还没有应用，先去「应用中心」接入一个。' }}
    </div>
  </div>
</template>

<style scoped>

.app-tiles {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 10px;
  width: 100%;
}

.app-tile {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 92px;
  padding: 12px 10px;
  background: #fff;
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  cursor: pointer;
  font: inherit;
  color: #303133;
  text-align: center;
  transition: border-color 0.15s, background 0.15s;
}

.app-tile:hover {
  border-color: #c0c4cc;
  background: #f7f9fc;
}

.app-tile.on {
  border-color: #409eff;
  background: #ecf5ff;
  color: #1f6fd0;
}

.tile-name {
  font-size: 13px;
  line-height: 1.35;
  word-break: break-word;
}

.tile-platform {
  font-size: 11px;
  color: #909399;
}

.app-tile.on .tile-platform {
  color: #1f6fd0;
}

.app-tile-empty {
  padding: 12px;
  color: #909399;
  font-size: 13px;
  background: #f5f7fa;
  border-radius: 8px;
}
</style>
