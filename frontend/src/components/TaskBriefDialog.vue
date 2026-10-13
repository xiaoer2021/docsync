<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { toastErr } from '@/api/client';
import { getTask, WRITE_MODE_OPTIONS, type Task } from '@/api/sync';
const props = defineProps<{
    taskId: number | null;
}>();
const visible = defineModel<boolean>({ default: false });
const task = ref<Task | null>(null);
const loading = ref(false);
const keyColumns = computed(() => (task.value?.target?.key_columns as string[]) || []);
watch(() => [props.taskId, visible.value] as const, async ([id, open]) => {
    if (!id || !open)
        return;
    loading.value = true;
    task.value = null;
    try {
        task.value = await getTask(id);
    }
    catch (err) {
        toastErr(err, '读取任务失败');
    }
    finally {
        loading.value = false;
    }
}, { immediate: true });
function writeModeLabel(mode: string | undefined): string {
    return WRITE_MODE_OPTIONS.find((o) => o.value === mode)?.label || mode || '—';
}
function fmt(value: string | null | undefined): string {
    return value ? value.replace('T', ' ').slice(0, 19) : '—';
}
</script>

<template>
  <el-dialog v-model="visible" title="任务简报" width="620px" top="10vh" append-to-body>
    <div v-loading="loading">
      <template v-if="task">
        <div class="brief-head">
          <span class="brief-name">{{ task.name }}</span>
          <span class="dot" :class="task.status === 'enabled' ? 'ok' : ''">
            {{ task.status === 'enabled' ? '启用中' : '已停用' }}
          </span>
        </div>

        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="来源表单">{{ task.doc_name }}</el-descriptions-item>
          <el-descriptions-item label="子表">{{ task.sheet_name || task.sheet_id }}</el-descriptions-item>
          <el-descriptions-item label="目标表">
            <span class="mono">{{ task.target_table || '未填' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="目标库">{{ task.datasource_name || '未选' }}</el-descriptions-item>

          <el-descriptions-item label="写入策略">{{ writeModeLabel(task.write_mode) }}</el-descriptions-item>
          <el-descriptions-item label="字段数">{{ task.columns?.length || 0 }} 列</el-descriptions-item>

          <el-descriptions-item label="主键列">
            <span v-if="keyColumns.length" class="mono">{{ keyColumns.join('、') }}</span>
            <span v-else class="muted">没设</span>
          </el-descriptions-item>
          <el-descriptions-item label="后置动作">
            {{ task.post_actions?.length || 0 }} 个
          </el-descriptions-item>

          <el-descriptions-item label="运行方式">{{ task.schedule_label || '手动' }}</el-descriptions-item>
          <el-descriptions-item label="下次运行">{{ fmt(task.next_run_at) }}</el-descriptions-item>
          <el-descriptions-item label="上次运行">{{ fmt(task.last_run_at) }}</el-descriptions-item>
          <el-descriptions-item label="上次结果">
            <span v-if="task.last_run_status">{{ task.last_run_status }}</span>
            <span v-else class="muted">还没跑过</span>
          </el-descriptions-item>
        </el-descriptions>

        <div class="field-hint">
          这里是只读简报。要运行、改配置、停用或删除，去「任务调度」页。
        </div>
      </template>
    </div>

    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.brief-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.brief-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-1);
}

.mono {
  font-family: var(--font-mono, monospace);
}

.field-hint {
  margin-top: 12px;
  font-size: var(--fs-label);
  color: var(--text-3);
  line-height: 1.6;
}
</style>
