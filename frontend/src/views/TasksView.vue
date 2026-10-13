<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { ElMessageBox } from 'element-plus';
import { toastErr, toastOk } from '@/api/client';
import { deleteTask, getRun, listTasks, runTask, updateTask, writeModeLabel, writeModeNote, type Run, type Task, } from '@/api/sync';
import { useAuthStore } from '@/stores/auth';
import RunRibbon from '@/components/RunRibbon.vue';
import TaskSummaryDialog from '@/components/TaskSummaryDialog.vue';
const route = useRoute();
const auth = useAuthStore();
const tasks = ref<Task[]>([]);
const loading = ref(false);
const keyword = ref('');
const busy = ref<number | null>(null);
const pickedTask = ref<number | null>(null);
const taskDialog = ref(false);
const testResult = ref<Run | null>(null);
const testTask = ref<Task | null>(null);
const confirmVisible = ref(false);
const testStage = ref('');
const testLogs = ref<string[]>([]);
let poll: number | undefined;
async function load() {
    loading.value = true;
    try {
        tasks.value = await listTasks({ keyword: keyword.value || undefined });
    }
    catch (err) {
        toastErr(err, '读取任务失败');
    }
    finally {
        loading.value = false;
    }
}
function statusOf(task: Task) {
    if (task.running)
        return { cls: 'run', text: '运行中' };
    if (task.status !== 'enabled')
        return { cls: 'warn', text: '已停用' };
    const last = task.last_run_status;
    if (!last)
        return { cls: '', text: '未跑过' };
    if (last === 'success')
        return { cls: 'ok', text: '成功' };
    if (last === 'partial')
        return { cls: 'warn', text: '部分成功' };
    return { cls: 'fail', text: '失败' };
}
function openTask(task: Task) {
    pickedTask.value = task.id;
    taskDialog.value = true;
}
async function waitFor(runId: number, timeoutMs = 300000): Promise<Run> {
    const started = Date.now();
    for (;;) {
        const run = await getRun(runId);
        testLogs.value = run.logs || [];
        await nextTick();
        const logBox = document.getElementById('run-progress-log');
        if (logBox)
            logBox.scrollTop = logBox.scrollHeight;
        if (!['queued', 'running'].includes(run.status))
            return run;
        if (Date.now() - started > timeoutMs)
            return run;
        await new Promise((r) => setTimeout(r, 1500));
        testStage.value = `已等 ${Math.round((Date.now() - started) / 1000)} 秒`;
    }
}
async function manualRun(task: Task) {
    busy.value = task.id;
    testStage.value = '';
    testLogs.value = [];
    try {
        const started = await runTask(task.id, { dry_run: true });
        testStage.value = '正在测试运行…';
        const run = await waitFor(started.run_id);
        if (run.status !== 'success' && run.status !== 'partial') {
            toastErr(new Error(run.error_message || '测试运行失败'), '先修好再跑');
            await load();
            return;
        }
        testResult.value = run;
        testTask.value = task;
        confirmVisible.value = true;
        testStage.value = '';
    }
    catch (err) {
        toastErr(err, '启动失败');
    }
    finally {
        busy.value = null;
        testStage.value = '';
    }
}
async function confirmRun() {
    if (!testTask.value)
        return;
    const task = testTask.value;
    confirmVisible.value = false;
    busy.value = task.id;
    testStage.value = '正在正式同步…';
    testLogs.value = [];
    try {
        const res = await runTask(task.id, {});
        const result = await waitFor(res.run_id, 3600000);
        if (result.status === 'success')
            toastOk(`正式运行完成（#${res.run_id}）`);
        else if (result.status === 'partial')
            ElMessageBox.alert('运行已完成，但有异常数据。请在执行日志中查看。', `执行 #${res.run_id}`);
        else
            toastErr(new Error(result.error_message || '运行未成功'), `执行 #${res.run_id}`);
        await load();
    }
    catch (err) {
        toastErr(err, '启动失败');
    }
    finally {
        busy.value = null;
        testStage.value = '';
    }
}
async function toggleStatus(task: Task) {
    try {
        await updateTask(task.id, { status: task.status === 'enabled' ? 'paused' : 'enabled' });
        toastOk(task.status === 'enabled' ? '已停用' : '已启用');
        await load();
    }
    catch (err) {
        toastErr(err, '操作失败');
    }
}
async function remove(task: Task) {
    try {
        await ElMessageBox.confirm(`确定删除「${task.name}」吗？`, '删除任务', {
            confirmButtonText: '删除',
            cancelButtonText: '取消',
            type: 'warning',
        });
    }
    catch {
        return;
    }
    try {
        await deleteTask(task.id);
        toastOk('已删除');
        await load();
    }
    catch (err) {
        toastErr(err, '删除失败');
    }
}
function fmt(value: string | null) {
    return value ? value.replace('T', ' ').slice(0, 19) : '—';
}
function hasSummary(row: Task) {
    const s = row.last_summary;
    if (!s)
        return false;
    return (Number(s.inserted ?? 0) + Number(s.updated ?? 0) + Number(s.unchanged ?? 0) > 0);
}
onMounted(async () => {
    await load();
    const open = Number(route.query.open);
    if (open) {
        pickedTask.value = open;
        taskDialog.value = true;
    }
    poll = window.setInterval(async () => {
        if (tasks.value.some((t) => t.running))
            await load();
    }, 5000);
    window.setTimeout(() => {
        if (poll)
            window.clearInterval(poll);
    }, 10 * 60 * 1000);
});
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">任务调度</h1>
        <div class="page-sub">一条任务 = 一个子表 → 一张目标表。改配置去「表单管理」里展开子表。</div>
      </div>
      <div class="head-actions">
        <el-input
          v-model="keyword"
          placeholder="搜任务名"
          size="small"
          style="width: 180px"
          clearable
          @change="load"
        />
        <el-button size="small" @click="load">刷新</el-button>
      </div>
    </div>

    <el-alert
      v-if="!tasks.length && !loading"
      type="info"
      :closable="false"
      show-icon
      title="还没有任务调度"
      description="去「表单管理」展开一份表单，在子表清单里点「建任务」—— 向导会带你选列、选目标表、试跑。"
    />

    <div v-else class="card">
      <el-table v-loading="loading" :data="tasks" size="small" style="width: 100%">
        <el-table-column label="任务" min-width="240">
          <template #default="{ row }">
            <span class="link" @click="openTask(row)">{{ row.name }}</span>
            <div class="sub">{{ row.doc_name }} · {{ row.sheet_name || row.sheet_id }}</div>

            <div
              v-if="row.merge_sheet_names?.length"
              class="merge-tag"
              :title="`合并 ${row.merge_sheet_names.length + 1} 个子表：${row.sheet_name}、${row.merge_sheet_names.join('、')}`"
            >
              合并 {{ row.merge_sheet_names.length + 1 }} 个子表
            </div>
          </template>
        </el-table-column>
        <el-table-column label="目标表" min-width="190">
          <template #default="{ row }">
            <span class="mono">{{ row.target_table || '—' }}</span>
            <div class="sub">{{ row.datasource_name || '未选库' }} · {{ row.write_mode }}</div>
          </template>
        </el-table-column>
        <el-table-column label="运行方式" min-width="130">
          <template #default="{ row }">
            <span :class="{ 'sched-on': row.schedule_label && row.schedule_label !== '手动' }">
              {{ row.schedule_label || '手动' }}
            </span>
            <div v-if="row.next_run_at" class="sub">下次 {{ fmt(row.next_run_at) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="写入策略" min-width="170">
          <template #default="{ row }">

            {{ writeModeLabel(row.write_mode) }}
            <div class="sub">{{ writeModeNote(row.write_mode) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <span class="dot" :class="statusOf(row).cls">{{ statusOf(row).text }}</span>
          </template>
        </el-table-column>
        <el-table-column label="上次结果" min-width="210">
          <template #default="{ row }">
            <RunRibbon
              v-if="hasSummary(row)"
              :inserted="Number(row.last_summary?.inserted ?? 0)"
              :updated="Number(row.last_summary?.updated ?? 0)"
              :unchanged="Number(row.last_summary?.unchanged ?? 0)"
              :failed="Number(row.last_summary?.failed ?? 0)"
            />

            <span v-else-if="row.last_run_status === 'failed'" class="dot fail">上次失败</span>
            <span v-else-if="row.last_run_status" class="muted">试跑过，还没正式同步</span>
            <span v-else class="muted">还没跑过</span>
            <div class="sub">{{ fmt(row.last_run_at) }}</div>
          </template>
        </el-table-column>
        <el-table-column v-if="auth.isAdmin" label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <div class="act-row">
              <el-button
                type="primary"
                link
                size="small"
                :loading="busy === row.id"
                @click="manualRun(row)"
              >
                手动运行
              </el-button>
              <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
            </div>

            <div class="act-row act-second">
              <span class="act-label">启用</span>
              <el-switch
                :model-value="row.status === 'enabled'"
                size="small"
                @change="() => toggleStatus(row)"
              />
              <span class="act-state">{{ row.status === 'enabled' ? '已启用' : '已停用' }}</span>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <TaskSummaryDialog v-model="taskDialog" :task-id="pickedTask" />

    <el-dialog v-model="confirmVisible" title="测试运行完成" width="560px">
      <el-alert
        :type="testResult?.status === 'partial' ? 'warning' : 'success'"
        :closable="false"
        show-icon
        :title="testResult?.status === 'partial' ? '发现异常数据，请先核对' : '检查通过，可以正式运行'"
        :description="testResult?.status === 'partial' ? '部分字段会自动调整类型或留下原文，正常业务列可能为空。请查看执行详情。' : '正式运行会把数据真正写进目标表。'"
      />
      <el-descriptions v-if="testResult" :column="2" border size="small" style="margin-top: 12px">
        <el-descriptions-item label="读到">{{ testResult.rows_read }} 行</el-descriptions-item>
        <el-descriptions-item label="跳过行">{{ testResult.rows_failed }} 行</el-descriptions-item>
        <el-descriptions-item label="异常格">
          {{ Number((testResult.stats?.quality as Record<string, unknown> | undefined)?.invalid_cells || 0) }} 个
        </el-descriptions-item>
        <el-descriptions-item label="调整类型">
          {{ Number((testResult.stats?.quality as Record<string, unknown> | undefined)?.adjusted_columns || 0) }} 列
        </el-descriptions-item>
        <el-descriptions-item label="预计新增">
          {{ (testResult.stats as Record<string, unknown>)?.to_insert ?? '—' }}
        </el-descriptions-item>
        <el-descriptions-item label="预计更新">
          {{ (testResult.stats as Record<string, unknown>)?.to_update ?? '—' }}
        </el-descriptions-item>
      </el-descriptions>
      <div class="field-hint">
        测试运行只读不写，目标库一点没动。想细看日志就去概览的「执行日志」点这一条。
      </div>
      <template #footer>
        <el-button size="small" @click="confirmVisible = false">先不跑</el-button>
        <el-button type="primary" size="small" @click="confirmRun">正式运行</el-button>
      </template>
    </el-dialog>

    <el-dialog
      :model-value="!!testStage"
      :show-close="false"
      :close-on-click-modal="false"
      width="720px"
      top="8vh"
      append-to-body
      class="run-progress-dialog"
    >
      <div class="running-box">
        <div class="running-title">{{ testStage }}</div>
        <div class="field-hint">测试运行会读全量数据，子表多的时候要等一会儿。跑完会问你。</div>

        <pre v-if="testLogs.length" id="run-progress-log" class="progress-log">{{
          testLogs.slice(-40).join('\n')
        }}</pre>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.head-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

.sub {
  font-size: var(--fs-label);
  color: var(--text-3);
  line-height: 1.5;
}

.merge-tag {
  margin-top: 3px;
  font-size: var(--fs-label);
  color: var(--brand);
  background: var(--brand-weak);
  border-radius: var(--radius-sm);
  padding: 2px 6px;
  display: inline-block;
  line-height: 1.4;
}

.link {
  font-weight: 600;
  color: var(--brand);
  cursor: pointer;
}

.sched-on {
  color: var(--brand);
  font-weight: 600;
}

.act-row {
  display: flex;
  align-items: center;
  gap: 8px;
  line-height: 22px;
}

.act-second {
  margin-top: 2px;
}

.act-label {
  font-size: var(--fs-label);
  color: var(--text-3);
}

.act-state {
  font-size: var(--fs-label);
  color: var(--text-2);
  min-width: 42px;
}

.field-hint {
  font-size: var(--fs-label);
  color: var(--text-3);
  line-height: 1.6;
  margin-top: 8px;
}

.running-box {
  text-align: center;
  padding: 6px 0;
}

.running-title {
  font-size: var(--fs-body);
  font-weight: 600;
  color: var(--text-1);
}

.progress-log {
  margin: var(--space-4) 0 0;
  padding: 10px var(--space-4);
  background: var(--surface-sunken);
  border-radius: var(--radius-sm);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: var(--fs-label);
  line-height: 1.7;
  color: var(--text-2);
  text-align: left;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 260px;
  overflow: auto;
}
</style>
