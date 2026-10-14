<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { ElMessageBox } from 'element-plus';
import { toastErr, toastOk } from '@/api/client';
import { createGroup, deleteGroup, listGroups, updateGroup, type Group } from '@/api/dingtalk';
import { useAuthStore } from '@/stores/auth';
const auth = useAuthStore();
const visible = defineModel<boolean>({ default: false });
const emit = defineEmits<{
    (e: 'changed'): void;
}>();
const groups = ref<Group[]>([]);
const loading = ref(false);
const name = ref('');
const editing = ref<Group | null>(null);
const editName = ref('');
const editVisible = ref(false);
const renaming = ref(false);
async function load() {
    loading.value = true;
    try {
        groups.value = await listGroups();
    }
    catch (err) {
        toastErr(err, '读取分组失败');
    }
    finally {
        loading.value = false;
    }
}
async function add() {
    const text = name.value.trim();
    if (!text)
        return;
    try {
        await createGroup(text);
        toastOk('已新增');
        name.value = '';
        await load();
        emit('changed');
    }
    catch (err) {
        toastErr(err, '新增失败');
    }
}
function openRename(group: Group) {
    editing.value = group;
    editName.value = group.name;
    editVisible.value = true;
}
async function submitRename() {
    const text = editName.value.trim();
    if (!text || !editing.value)
        return;
    renaming.value = true;
    try {
        await updateGroup(editing.value.id, { name: text });
        toastOk('已改名');
        editVisible.value = false;
        await load();
        emit('changed');
    }
    catch (err) {
        toastErr(err, '改名失败');
    }
    finally {
        renaming.value = false;
    }
}
async function remove(group: Group) {
    try {
        await ElMessageBox.confirm(`确定删除分组「${group.name}」吗？分组里的表单和任务不会被删，只是变回「未分组」。`, '删除分组', { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' });
    }
    catch {
        return;
    }
    try {
        await deleteGroup(group.id);
        toastOk('已删除');
        await load();
        emit('changed');
    }
    catch (err) {
        toastErr(err, '删除失败');
    }
}
onMounted(load);
defineExpose({ reload: load });
</script>

<template>
  <el-dialog v-model="visible" title="业务分组" width="620px" append-to-body @open="load">
    <div class="sub">
      按业务用途对表单和任务分组，例如销售、库存、项目管理。分组为可选配置，不影响同步。
    </div>

    <div v-if="auth.isAdmin" class="add-row">
      <el-input v-model="name" placeholder="新分组名称" @keyup.enter="add" />
      <el-button type="primary" :loading="loading" @click="add">新增</el-button>
    </div>

    <el-table v-loading="loading" :data="groups" size="small" style="width: 100%">
      <el-table-column prop="name" label="分组" min-width="160" />
      <el-table-column label="表单数" width="90" align="right">
        <template #default="{ row }">{{ row.doc_count }}</template>
      </el-table-column>
      <el-table-column label="任务数" width="90" align="right">
        <template #default="{ row }">{{ row.task_count }}</template>
      </el-table-column>
      <el-table-column v-if="auth.isAdmin" label="操作" width="130">
        <template #default="{ row }">
          <el-button link size="small" @click="openRename(row)">改名</el-button>
          <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div v-if="!groups.length && !loading" class="muted pad">还没有分组。</div>

    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
    </template>

    <el-dialog v-model="editVisible" title="改分组名" width="420px" append-to-body>
      <el-form label-width="80px">
        <el-form-item label="分组名">
          <el-input v-model="editName" @keyup.enter="submitRename" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="renaming" @click="submitRename">保存</el-button>
      </template>
    </el-dialog>
  </el-dialog>
</template>

<style scoped>
.sub {
  font-size: var(--fs-label);
  color: var(--text-3);
  line-height: 1.6;
  margin-bottom: 12px;
}

.add-row {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}

.pad {
  padding: 10px;
}
</style>
