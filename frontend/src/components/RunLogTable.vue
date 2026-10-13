<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { toastErr } from '@/api/client';
import { PAGE_SIZES, getRun, listRuns, type Run, type RunDetail } from '@/api/sync';
import RunRibbon from '@/components/RunRibbon.vue';
const props = withDefaults(defineProps<{
    taskId?: number | null;
    compact?: boolean;
}>(), { taskId: null, compact: false });
const emit = defineEmits<{
    (e: 'pick-task', taskId: number): void;
}>();
const expandedId = ref<number | null>(null);
const expandedLog = ref('');
const expandedIssues = ref<RunDetail['issues']>([]);
const expandedLoading = ref(false);
const rows = ref<Run[]>([]);
const total = ref(0);
const offset = ref(0);
const limit = ref(10);
const loading = ref(false);
const statusFilter = ref('');
const detailVisible = ref(false);
const detail = ref<RunDetail | null>(null);
const detailLoading = ref(false);
const logBox = ref<HTMLElement | null>(null);
let detailTimer: number | undefined;
let detailGeneration = 0;
function stopDetailUpdates() {
    detailGeneration += 1;
    if (detailTimer !== undefined)
        window.clearTimeout(detailTimer);
    detailTimer = undefined;
}
async function refreshDetail(runId: number, generation: number, initial = false) {
    const box = logBox.value;
    const followTail = initial || !box || box.scrollHeight - box.scrollTop - box.clientHeight < 36;
    try {
        const latest = await getRun(runId);
        if (generation !== detailGeneration || !detailVisible.value)
            return;
        const wasRunning = detail.value && ['queued', 'running'].includes(detail.value.status);
        detail.value = latest;
        await nextTick();
        if (followTail && logBox.value)
            logBox.value.scrollTop = logBox.value.scrollHeight;
        if (wasRunning && !['queued', 'running'].includes(latest.status))
            load();
        if (['queued', 'running'].includes(latest.status)) {
            detailTimer = window.setTimeout(() => refreshDetail(runId, generation), 1000);
        }
    }
    catch (err) {
        if (generation === detailGeneration && detailVisible.value) {
            if (initial)
                toastErr(err, '读取执行详情失败');
            detailTimer = window.setTimeout(() => refreshDetail(runId, generation), 2000);
        }
    }
    finally {
        if (generation === detailGeneration)
            detailLoading.value = false;
    }
}
async function load() {
    loading.value = true;
    try {
        const page = await listRuns({
            task_id: props.taskId ?? undefined,
            status: statusFilter.value || undefined,
            offset: offset.value,
            limit: limit.value,
        });
        rows.value = page.items;
        total.value = page.total;
    }
    catch (err) {
        toastErr(err, '读取执行记录失败');
    }
    finally {
        loading.value = false;
    }
}
function onPage(page: number) {
    offset.value = (page - 1) * limit.value;
    load();
}
function onSize(size: number) {
    limit.value = size;
    offset.value = 0;
    load();
}
async function onExpandChange(row: Run, expanded: Run[]) {
    const opened = expanded.some((item) => item.id === row.id);
    if (!opened) {
        if (expandedId.value === row.id)
            expandedId.value = null;
        return;
    }
    expandedId.value = row.id;
    expandedLog.value = '';
    expandedIssues.value = [];
    expandedLoading.value = true;
    try {
        const detail = await getRun(row.id);
        if (expandedId.value !== row.id)
            return;
        expandedLog.value = detail.logs.join('\n') || '（没有日志）';
        expandedIssues.value = detail.issues;
    }
    catch (err) {
        toastErr(err, '读取日志失败');
    }
    finally {
        if (expandedId.value === row.id)
            expandedLoading.value = false;
    }
}
async function openRun(run: Run) {
    await openRunById(run.id);
}
async function openRunById(runId: number) {
    stopDetailUpdates();
    detailVisible.value = true;
    detailLoading.value = true;
    detail.value = null;
    await refreshDetail(runId, detailGeneration, true);
}
defineExpose({ reload: load, openRunById });
watch(detailVisible, (visible) => {
    if (!visible)
        stopDetailUpdates();
});
onUnmounted(stopDetailUpdates);
watch(() => props.taskId, () => {
    offset.value = 0;
    load();
});
onMounted(load);
</script>

<template>
  <div class="run-log">
    <div class="bar">
      <el-select
        v-model="statusFilter"
        size="small"
        style="width: 130px"
        placeholder="全部状态"
        clearable
        @change="onPage(1)"
      >
        <el-option label="只看成功" value="success" />
        <el-option label="只看失败" value="failed" />
        <el-option label="只看部分成功" value="partial" />
        <el-option label="只看运行中" value="running" />
      </el-select>
      <span class="muted">共 {{ total }} 条</span>
      <el-button size="small" @click="load">刷新</el-button>
    </div>

    <el-table
      v-loading="loading"
      :data="rows"
      size="small"
      border
      style="width: 100%"
      row-class-name="row-clickable"
      @row-click="openRun"
      @expand-change="onExpandChange"
    >

      <el-table-column v-if="!compact" type="expand" width="44">
        <template #default="{ row }">
          <div v-loading="expandedLoading && expandedId === row.id" class="expand-box">
            <pre class="log-box">{{ expandedLog || '（没有日志）' }}</pre>
            <template v-if="expandedIssues.length">
              <div class="section-title">坏行留证（前 {{ expandedIssues.length }} 条）</div>
              <el-table :data="expandedIssues" size="small" border max-height="200">
                <el-table-column label="行号" width="80">
                  <template #default="{ row: issue }">{{ issue.row_no ?? '—' }}</template>
                </el-table-column>
                <el-table-column label="列" width="160">
                  <template #default="{ row: issue }">{{ issue.column }}</template>
                </el-table-column>
                <el-table-column label="原因" min-width="200">
                  <template #default="{ row: issue }">{{ issue.reason }}</template>
                </el-table-column>
              </el-table>
            </template>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="#" width="76">
        <template #default="{ row }">
          <span class="link">#{{ row.id }}</span>
        </template>
      </el-table-column>
      <el-table-column v-if="!taskId" label="任务" min-width="180">
        <template #default="{ row }">
          <span class="link" @click.stop="emit('pick-task', row.task_id)">
            {{ row.task_name }}
          </span>
        </template>
      </el-table-column>

      <el-table-column label="状态" min-width="220">
        <template #default="{ row }">
          <span
            class="dot"
            :class="
              row.status === 'success'
                ? 'ok'
                : row.status === 'partial'
                  ? 'warn'
                  : row.status === 'running'
                    ? 'run'
                    : 'fail'
            "
            >{{ row.status_label }}</span
          >
          <span v-if="row.error_message" class="err" :title="row.error_message">
            {{ row.error_message }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="运行方式" width="100">
        <template #default="{ row }">{{ row.trigger_label }}</template>
      </el-table-column>
      <el-table-column v-if="!compact" label="这次做了什么" min-width="230">
        <template #default="{ row }">
          <RunRibbon
            :inserted="row.rows_inserted"
            :updated="row.rows_updated"
            :unchanged="row.rows_unchanged"
            :failed="row.rows_failed"
          />
        </template>
      </el-table-column>
      <el-table-column v-if="!compact" label="耗时" width="86">
        <template #default="{ row }">
          {{ row.duration_ms ? `${(row.duration_ms / 1000).toFixed(1)} s` : '—' }}
        </template>
      </el-table-column>
      <el-table-column label="时间" width="160">
        <template #default="{ row }">
          {{ (row.finished_at || row.started_at || '').replace('T', ' ').slice(0, 19) || '—' }}
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination
        :current-page="Math.floor(offset / limit) + 1"
        :page-size="limit"
        :total="total"
        :page-sizes="PAGE_SIZES"
        layout="total, sizes, prev, pager, next, jumper"
        background
        small
        @current-change="onPage"
        @size-change="onSize"
      />
    </div>

    <el-dialog
      v-model="detailVisible"
      :title="`执行 #${detail?.id ?? ''}`"
      width="760px"
      top="6vh"
      append-to-body
      class="run-detail-dialog"
    >
      <div v-loading="detailLoading">
        <template v-if="detail">
          <el-descriptions :column="3" border size="small">
            <el-descriptions-item label="任务">{{ detail.task_name }}</el-descriptions-item>
            <el-descriptions-item label="状态">
              <span class="dot" :class="detail.status === 'success' ? 'ok' : detail.status === 'partial' ? 'warn' : 'fail'">
                {{ detail.status_label }}
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="运行方式">{{ detail.trigger_label }}</el-descriptions-item>
            <el-descriptions-item label="读到">{{ detail.rows_read }}</el-descriptions-item>
            <el-descriptions-item label="写入">{{ detail.rows_written }}</el-descriptions-item>
          <el-descriptions-item label="异常格">
            {{ Number((detail.stats?.quality as Record<string, unknown> | undefined)?.invalid_cells || 0) }}
          </el-descriptions-item>
          <el-descriptions-item label="关键列异常">
            {{ Number((detail.stats?.quality as Record<string, unknown> | undefined)?.critical_cells || 0) }}
          </el-descriptions-item>
            <el-descriptions-item label="耗时">
              {{ detail.duration_ms ? `${(detail.duration_ms / 1000).toFixed(1)} s` : '—' }}
            </el-descriptions-item>
          </el-descriptions>

          <div v-if="detail.error_message" class="err-box">{{ detail.error_message }}</div>

          <div class="section-title">日志</div>
          <pre ref="logBox" class="log-box">{{ detail.logs.join('\n') || '（没有日志）' }}</pre>

          <template v-if="detail.issues.length">
            <div class="section-title">坏行留证（前 {{ detail.issues.length }} 条）</div>
            <el-table :data="detail.issues" size="small" border max-height="240">
              <el-table-column label="行号" width="80">
                <template #default="{ row }">{{ row.row_no ?? '—' }}</template>
              </el-table-column>
              <el-table-column label="列" width="160">
                <template #default="{ row }">{{ row.column }}</template>
              </el-table-column>
              <el-table-column label="原因" min-width="200">
                <template #default="{ row }">{{ row.reason }}</template>
              </el-table-column>
            </el-table>
          </template>
        </template>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.pager {
  margin-top: 10px;
  display: flex;
  justify-content: flex-end;
}

.expand-box {
  padding: 4px 8px 8px;
}

.link {
  color: var(--brand);
  cursor: pointer;
}

.err {
  margin-left: 8px;
  font-size: var(--fs-label);
  color: var(--danger);
  display: inline-block;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}

.section-title {
  margin: 14px 0 6px;
  font-size: var(--fs-body);
  font-weight: 600;
  color: var(--text-1);
}

.log-box {
  background: var(--surface-sunken);
  border-radius: var(--radius-sm);
  padding: var(--space-4);
  font-size: var(--fs-label);
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 320px;
  overflow: auto;
  margin: 0;
}

.err-box {
  margin-top: 12px;
  padding: 8px 10px;
  background: var(--danger-weak);
  color: var(--danger);
  border-radius: var(--radius-sm);
  font-size: var(--fs-label);
  word-break: break-all;
}
</style>
