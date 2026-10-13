<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue';
import { call } from '@/api/client';
import type { Overview } from '@/api/stats';
import { writeModeLabel } from '@/api/sync';
import TaskBriefDialog from '@/components/TaskBriefDialog.vue';
const overview = ref<Overview | null>(null);
const error = ref('');
const updatedAt = ref('');
const autoRefresh = ref(true);
let timer: number | undefined;
const briefTask = ref<number | null>(null);
const briefVisible = ref(false);
async function load() {
    try {
        overview.value = await call<Overview>({ url: '/stats/overview' });
        error.value = '';
    }
    catch (err) {
        error.value = (err as {
            message?: string;
        })?.message || '读取失败';
    }
    finally {
        updatedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false });
    }
}
function restartTimer() {
    if (timer)
        window.clearInterval(timer);
    if (autoRefresh.value)
        timer = window.setInterval(load, 30000);
}
function openBrief(taskId: number) {
    briefTask.value = taskId;
    briefVisible.value = true;
}
onMounted(() => {
    load();
    restartTimer();
});
onBeforeUnmount(() => {
    if (timer)
        window.clearInterval(timer);
});
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">概览</h1>
        <div class="page-sub">同步跑得怎么样、接下来该做什么</div>
      </div>
      <div class="refresh">
        <span class="muted">更新于 {{ updatedAt || '—' }}</span>
        <el-switch v-model="autoRefresh" size="small" active-text="自动刷新" @change="restartTimer" />
        <el-button size="small" @click="load">立即刷新</el-button>
      </div>
    </div>

    <el-alert v-if="error" type="error" :closable="false" show-icon :title="error" />

    <template v-if="overview">

      <div class="card rise-in">
        <div class="card-head">
          <span class="card-title">规模与运行</span>
        </div>
        <div class="stat-cards">
          <div class="stat">
            <b>{{ overview.counts.docs }}</b><span>表单</span>
          </div>
          <div class="stat">
            <b>{{ overview.counts.sheets }}</b><span>Sheet 表</span>
          </div>
          <div class="stat" :class="{ warn: overview.counts.sheets_without_task > 0 }">
            <b>{{ overview.counts.sheets_without_task }}</b><span>未使用 Sheet</span>
          </div>
          <div class="stat">
            <b>{{ overview.counts.tasks }}</b><span>总任务</span>
          </div>
          <div class="stat">
            <b>{{ overview.counts.tasks_enabled }}</b><span>启用中</span>
          </div>
          <div class="stat" :class="{ ok: overview.counts.scheduled_tasks > 0 }">
            <b>{{ overview.counts.scheduled_tasks }}</b><span>定时任务</span>
          </div>
          <div class="stat">
            <b>{{ overview.counts.actions }}</b><span>后置动作</span>
          </div>
          <div class="stat" :class="{ ok: overview.counts.runs_running > 0 }">
            <b>{{ overview.counts.runs_running }}</b><span>正在跑</span>
          </div>
          <div class="stat">
            <b>{{ overview.window.runs }}</b><span>近 {{ overview.window.days }} 天执行</span>
          </div>
          <div class="stat" :class="{ bad: overview.window.failed > 0 }">
            <b>{{ overview.window.failed }}</b><span>失败</span>
          </div>
          <div class="stat">
            <b>{{ overview.window.rows_written.toLocaleString() }}</b><span>写入行数</span>
          </div>
          <div
            class="stat"
            :class="{
              bad: overview.window.success_rate !== null && overview.window.success_rate < 90,
              ok: overview.window.success_rate !== null && overview.window.success_rate >= 90,
            }"
          >
            <b>{{ overview.window.success_rate === null ? '—' : `${overview.window.success_rate}%` }}</b>
            <span>成功率</span>
          </div>
        </div>
      </div>

      <div v-if="overview.upcoming.length" class="card rise-in">
        <div class="card-head"><span class="card-title">接下来会自动跑</span></div>
        <div class="card-body">
          <el-table :data="overview.upcoming" size="small" style="width: 100%">
            <el-table-column label="任务" min-width="200">
              <template #default="{ row }">
                <span class="link" @click="openBrief(row.task_id)">{{ row.name }}</span>
                <div class="sub mono">{{ row.target_table }}</div>
              </template>
            </el-table-column>
            <el-table-column label="运行方式" min-width="130">
              <template #default="{ row }">{{ row.schedule_label }}</template>
            </el-table-column>
            <el-table-column label="写入策略" min-width="110">
              <template #default="{ row }">{{ writeModeLabel(row.write_mode) }}</template>
            </el-table-column>
            <el-table-column label="下次运行" min-width="160">
              <template #default="{ row }">
                {{ (row.next_run_at || '').replace('T', ' ').slice(0, 19) }}
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>

    </template>

    <TaskBriefDialog v-model="briefVisible" :task-id="briefTask" />
  </div>
</template>

<style scoped>
.refresh {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  font-size: var(--fs-label);
}

.stat-cards {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 0 var(--space-4) var(--space-4);
}

.stat {
  display: flex;
  align-items: baseline;
  gap: 7px;
  padding: 5px 11px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-sunken);
}

.stat b {
  font-size: 17px;
  font-weight: 700;
  color: var(--text-1);
  font-variant-numeric: tabular-nums;
}

.stat span {
  font-size: var(--fs-label);
  color: var(--text-3);
}

.stat.warn b {
  color: var(--warn);
}

.stat.bad b {
  color: var(--danger);
}

.stat.ok b {
  color: var(--ok);
}

.facts {
  display: flex;
  flex-wrap: wrap;
  gap: 10px var(--space-9);
  padding: var(--space-1) var(--space-4) var(--space-4);
}

.fact {
  font-size: var(--fs-body);
  color: var(--text-2);
}

.fact b {
  color: var(--text-1);
  font-size: var(--fs-title);
  font-weight: 600;
  margin-left: 6px;
  font-variant-numeric: tabular-nums;
}

.fact.warn b {
  color: var(--warn);
}

.fact.bad b {
  color: var(--danger);
}

.fact.on b {
  color: var(--brand);
}

.log-section {
  margin-top: var(--space-9);
}

.section-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: 12px;
}

.section-title {
  font-size: var(--fs-title);
  font-weight: 600;
  color: var(--text-1);
  margin: 0;
  line-height: var(--lh-tight);
}

.link {
  color: var(--brand);
  cursor: pointer;
  font-weight: 500;
}

.sub {
  font-size: var(--fs-label);
  color: var(--text-3);
  line-height: var(--lh-body);
}
</style>
