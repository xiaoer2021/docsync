<script setup lang="ts">
import { onMounted, ref, watch } from 'vue';
import { toastErr, toastOk } from '@/api/client';
import { createGroup, listGroups, type Group } from '@/api/dingtalk';
import { useAuthStore } from '@/stores/auth';
withDefaults(defineProps<{
    placeholder?: string;
    allowCreate?: boolean;
}>(), { placeholder: '可留空', allowCreate: true });
const model = defineModel<number[]>({ default: () => [] });
const auth = useAuthStore();
const groups = ref<Group[]>([]);
const adding = ref(false);
const newName = ref('');
const creating = ref(false);
async function load() {
    try {
        groups.value = await listGroups();
    }
    catch {
    }
}
function startAdd() {
    adding.value = true;
    newName.value = '';
}
function cancelAdd() {
    adding.value = false;
    newName.value = '';
}
async function doCreate() {
    const name = newName.value.trim();
    if (!name)
        return;
    creating.value = true;
    try {
        const created = await createGroup(name);
        toastOk(`已新建分组「${created.name}」`);
        newName.value = '';
        adding.value = false;
        await load();
        const current = model.value || [];
        if (!current.includes(created.id))
            model.value = [...current, created.id];
    }
    catch (err) {
        toastErr(err, '新建分组失败');
    }
    finally {
        creating.value = false;
    }
}
watch(() => model.value, (ids) => {
    if ((ids || []).some((id) => !groups.value.some((g) => g.id === id)))
        void load();
});
onMounted(load);
defineExpose({ reload: load });
</script>

<template>
  <div class="group-pick">
    <el-select
      v-model="model"
      :placeholder="placeholder"
      multiple
      collapse-tags
      collapse-tags-tooltip
      clearable
      filterable
      class="group-select"
    >
      <el-option v-for="g in groups" :key="g.id" :label="g.name" :value="g.id" />

      <template v-if="allowCreate && auth.isAdmin" #footer>
        <div v-if="!adding" class="group-add" @click.stop="startAdd">＋ 新建分组</div>
        <div v-else class="group-add-form" @click.stop>
          <el-input
            v-model="newName"
            size="small"
            placeholder="新分组名称，例如 Coupang"
            autofocus
            @keyup.enter="doCreate"
            @keyup.esc="cancelAdd"
          />
          <el-button size="small" type="primary" :loading="creating" @click="doCreate">
            建好
          </el-button>
        </div>
      </template>
    </el-select>

    <div v-if="allowCreate && !groups.length && !adding" class="field-hint">
      还没有分组。分组只是给你自己分类用的，可以留空，也可以在下拉里新建。
    </div>
  </div>
</template>

<style scoped>
.group-pick {
  width: 100%;
}

.group-select {
  width: 100%;
}

.group-add-form {
  display: flex;
  gap: 6px;
  align-items: center;
  width: 100%;
  padding: 4px 0;
}

.group-add {
  padding: 6px 12px;
  cursor: pointer;
  color: var(--brand);
  font-size: var(--fs-label);
  border-top: 1px solid var(--border);
}

.group-add:hover {
  background: var(--brand-weak-2);
}

.field-hint {
  font-size: var(--fs-label);
  color: var(--text-3);
  line-height: 1.6;
  margin-top: 4px;
  width: 100%;
}
</style>
