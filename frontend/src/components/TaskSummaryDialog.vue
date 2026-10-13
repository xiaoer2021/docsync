<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessageBox } from 'element-plus';
import { toastErr, toastOk } from '@/api/client';
import { getTask, runTask, updateTask, type Task } from '@/api/sync';
import RunLogTable from '@/components/RunLogTable.vue';
const props = defineProps<{
    taskId: number | null;
}>();
const emit = defineEmits<{
    (e: 'close'): void;
}>();
const router = useRouter();
const visible = defineModel<boolean>({ default: false });
const task = ref<Task | null>(null);
const loading = ref(false);
const busy = ref(false);
const runLog = ref<InstanceType<typeof RunLogTable> | null>(null);
const target = computed(() => (task.value?.target || {}) as Record<string, unknown>);
const keyColumns = computed(() => (target.value.key_columns as string[]) || []);
const mergeNames = computed(() => task.value?.merge_sheet_names || []);
const scheduled = computed(() => (task.value?.schedule_label || '手动') !== '手动');
async function load() {
    if (!props.taskId)
        return;
    loading.value = true;
    try {
        task.value = await getTask(props.taskId);
    }
    catch (err) {
        toastErr(err, '读取任务失败');
    }
    finally {
        loading.value = false;
    }
}
async function manualRun() {
    if (!task.value)
        return;
    busy.value = true;
    try {
        const res = await runTask(task.value.id, { dry_run: true });
        await runLog.value?.openRunById(res.run_id);
        toastOk(`测试运行已开始（#${res.run_id}），日志会实时更新`);
    }
    catch (err) {
        toastErr(err, '启动失败');
    }
    finally {
        busy.value = false;
    }
}
async function toggleStatus() {
    if (!task.value)
        return;
    try {
        await updateTask(task.value.id, {
            status: task.value.status === 'enabled' ? 'paused' : 'enabled',
        });
        toastOk(task.value.status === 'enabled' ? '已停用' : '已启用');
        await load();
    }
    catch (err) {
        toastErr(err, '操作失败');
    }
}
async function remove() {
    if (!task.value)
        return;
    try {
        await ElMessageBox.confirm(`确定删除任务「${task.value.name}」吗？`, '删除任务', {
            confirmButtonText: '删除',
            cancelButtonText: '取消',
            type: 'warning',
        });
    }
    catch {
        return;
    }
    try {
        await updateTask(task.value.id, {});
        toastErr(new Error('删除请到表单管理里操作'), '这里不提供删除');
    }
    catch {
    }
}
watch(() => [props.taskId, visible.value] as const, ([id, open]) => {
    if (id && open)
        load();
}, { immediate: true });
</script>

<template>
  <el-dialog v-model="visible" :title="task?.name || '任务'" width="880px" top="5vh" @close="emit('close')">
    <div v-loading="loading">
      <template v-if="task">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="编号">
            <span class="mono">{{ task.code }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <span :class="task.status === 'enabled' ? 'ok-text' : 'muted'">
              {{ task.status === 'enabled' ? '启用中' : '已停用' }}
            </span>
          </el-descriptions-item>
          <el-descriptions-item label="表单">
            <a class="link" @click="router.push(`/docs/${task.doc_id}`)">{{ task.doc_name }}</a>
          </el-descriptions-item>
          <el-descriptions-item label="目标表">
            <span class="mono">{{ task.target_table || '未填' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="目标库">{{ task.datasource_name || '未选' }}</el-descriptions-item>
          <el-descriptions-item label="写入方式">{{ task.write_mode }}</el-descriptions-item>
          <el-descriptions-item label="主键列">
            <span v-if="keyColumns.length" class="mono">{{ keyColumns.join('、') }}</span>
            <span v-else class="muted">没设</span>
          </el-descriptions-item>
          <el-descriptions-item label="字段数">{{ task.columns?.length || 0 }} 列</el-descriptions-item>
          <el-descriptions-item label="运行方式">
            <span :class="scheduled ? 'ok-text' : 'muted'">{{ task.schedule_label || '手动' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="下次运行">
            <span v-if="task.next_run_at">{{ task.next_run_at.replace('T', ' ').slice(0, 19) }}</span>
            <span v-else class="muted">不会自动跑</span>
          </el-descriptions-item>
        </el-descriptions>

        <div v-if="mergeNames.length" class="merge-box">
          <div class="merge-title">合并了 {{ mergeNames.length + 1 }} 个子表</div>

          <div class="merge-list">
            <span class="merge-chip main">{{ task.sheet_name }}<em>主表</em></span>
            <span v-for="n in mergeNames" :key="n" class="merge-chip">{{ n }}<em>合并</em></span>
          </div>
        </div>

        <div class="dialog-actions">
          <el-button type="primary" size="small" :loading="busy" @click="manualRun">
            手动运行
          </el-button>
          <el-button size="small" @click="router.push(`/tasks/${task.id}/edit`)">
            编辑任务
          </el-button>
          <el-button size="small" @click="toggleStatus">
            {{ task.status === 'enabled' ? '停用' : '启用' }}
          </el-button>
          <el-button size="small" @click="remove">删除</el-button>
        </div>

        <div class="section-title">执行记录</div>

        <RunLogTable ref="runLog" :task-id="task.id" />
      </template>
    </div>
  </el-dialog>
</template>

<style scoped>
.link {
  color: var(--brand);
  cursor: pointer;
}

.mono {
  font-family: var(--font-mono, monospace);
}

.ok-text {
  color: var(--brand);
  font-weight: 600;
}

.muted {
  color: var(--text-3);
}

.merge-box {
  margin-top: 12px;
  padding: var(--space-4);
  background: var(--brand-weak);
  border-radius: var(--radius-sm);
}

.merge-title {
  font-size: var(--fs-body);
  font-weight: 600;
  color: var(--brand);
  margin-bottom: 6px;
}

.merge-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.merge-chip {
  font-size: var(--fs-label);
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text-2);
  border: 1px solid var(--border);
}

.merge-chip.main {
  color: var(--brand);
  border-color: var(--brand);
}

.merge-chip em {
  font-style: normal;
  margin-left: 6px;
  padding: 0 4px;
  border-radius: 3px;
  font-size: 11px;
  background: var(--surface-sunken);
  color: var(--text-3);
}

.merge-chip.main em {
  color: var(--brand);
}

.dialog-actions {
  display: flex;
  gap: 8px;
  margin-top: 14px;
}

.section-title {
  margin: 16px 0 8px;
  font-size: var(--fs-body);
  font-weight: 600;
  color: var(--text-1);
}
</style>
