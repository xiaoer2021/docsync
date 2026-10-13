<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { toastErr, toastOk } from '@/api/client';
import { docSubItems, getDoc, probeDoc, setDocWatch, type DocItem, type DocResolveResult, type SubItem, } from '@/api/dingtalk';
import DocEditDialog from '@/components/DocEditDialog.vue';
import { useAuthStore } from '@/stores/auth';
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const docId = Number(route.params.id);
const doc = ref<DocItem | null>(null);
const items = ref<SubItem[]>([]);
const loading = ref(false);
const probing = ref(false);
const probeFailure = ref<DocResolveResult | null>(null);
const editVisible = ref(false);
const unconfigured = computed(() => items.value.filter((i) => !i.configured));
const configured = computed(() => items.value.filter((i) => i.configured));
async function load() {
    loading.value = true;
    try {
        doc.value = await getDoc(docId);
        items.value = await docSubItems(docId);
    }
    catch (err) {
        toastErr(err, '读取表单失败');
    }
    finally {
        loading.value = false;
    }
}
async function doProbe() {
    probing.value = true;
    probeFailure.value = null;
    try {
        const result = await probeDoc(docId);
        if (result.ok) {
            toastOk(`重新读取完成，${result.sub_items.length} 个子表`);
        }
        else {
            probeFailure.value = result;
        }
        await load();
    }
    catch (err) {
        toastErr(err, '读取失败');
    }
    finally {
        probing.value = false;
    }
}
async function toggleWatch() {
    if (!doc.value)
        return;
    try {
        await setDocWatch(docId, !doc.value.watch_enabled, doc.value.watch_cron);
        toastOk(doc.value.watch_enabled ? '已关闭子表变化检查' : '已开启子表变化检查');
        await load();
    }
    catch (err) {
        toastErr(err, '操作失败');
    }
}
function openEdit() {
    if (!doc.value)
        return;
    editVisible.value = true;
}
function fmt(value: string | null) {
    return value ? value.replace('T', ' ').slice(0, 19) : '—';
}
function createTaskFor(item: SubItem) {
    router.push({
        path: '/tasks/new',
        query: { doc_id: String(docId), sheet_id: item.id, sheet_name: item.name },
    });
}
onMounted(load);
</script>

<template>
  <div v-loading="loading" class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">{{ doc?.name || '' }}</h1>
        <div class="page-sub">
          <el-tag size="small" effect="light">
            {{ doc?.doc_type_label }}
          </el-tag>
          <span class="mono muted"> {{ doc?.node_id }}</span>
        </div>
      </div>
      <div v-if="auth.isAdmin" class="head-actions">
        <el-button :loading="probing" @click="doProbe">重新读取</el-button>
        <el-button @click="openEdit">编辑</el-button>
      </div>
    </div>

    <el-alert
      v-if="doc?.last_probe_ok === false"
      type="error"
      :closable="false"
      show-icon
      title="上一次读取失败"
      :description="doc.last_probe_error || ''"
      style="margin-bottom: 12px"
    />

    <div v-if="probeFailure" class="fail-box">
      <div class="fail-head">
        <span class="dot fail">读不到这份表单</span>
        <span class="fail-msg">{{ probeFailure.error }}</span>
      </div>
      <div v-if="probeFailure.hint" class="fail-hint">{{ probeFailure.hint }}</div>
      <div class="diag">
        <div class="diag-row">
          <span class="diag-key">错误码</span>
          <span class="mono">{{ probeFailure.code || '（未返回）' }}</span>
        </div>
        <div v-if="probeFailure.http_status" class="diag-row">
          <span class="diag-key">HTTP 状态</span>
          <span class="mono">{{ probeFailure.http_status }}</span>
        </div>
        <div class="diag-row">
          <span class="diag-key">用的表单 ID</span>
          <span class="mono">{{ probeFailure.used_node_id || probeFailure.node_id }}</span>
        </div>
        <div class="diag-row">
          <span class="diag-key">以谁的身份读</span>
          <span class="mono">{{ probeFailure.used_operator_union_id || '（没设置操作人）' }}</span>
        </div>
      </div>
      <div v-if="probeFailure.attempts.length" class="attempts">
        <div v-for="a in probeFailure.attempts" :key="a.doc_type" class="attempt">
          <span class="attempt-label">{{ a.label }}</span>
          <span class="mono muted">{{ a.code || '—' }}</span>
          <span class="attempt-msg">{{ a.message }}</span>
        </div>
      </div>
    </div>

    <el-alert
      v-if="doc?.structure_drift"
      type="warning"
      :closable="false"
      show-icon
      title="源表单结构有变化"
      :description="doc.structure_drift"
      style="margin-bottom: 12px"
    />

    <div class="stat-row">
      <div class="stat">
        <div class="stat-num">{{ doc?.sheet_count ?? 0 }}</div>
        <div class="stat-label">子表</div>
      </div>
      <div class="stat">
        <div class="stat-num">{{ configured.length }}</div>
        <div class="stat-label">已配任务</div>
      </div>
      <div class="stat">
        <div class="stat-num warn">{{ unconfigured.length }}</div>
        <div class="stat-label">待配</div>
      </div>
      <div class="stat wide">
        <div class="stat-label">归属应用</div>
        <div class="stat-text">{{ doc?.app_name || '—' }}</div>
      </div>
      <div class="stat wide">
        <div class="stat-label">业务分组</div>
        <div class="stat-text">{{ doc?.group_name || '未分组' }}</div>
      </div>
      <div class="stat wide">
        <div class="stat-label">子表变化检查</div>
        <div class="stat-text">
          <span class="dot" :class="doc?.watch_enabled ? 'ok' : ''">
            {{ doc?.watch_enabled ? '已开启' : '未开启' }}
          </span>
          <a v-if="auth.isAdmin" class="inline-link" @click="toggleWatch">
            {{ doc?.watch_enabled ? '关闭' : '开启' }}
          </a>
          <span v-if="doc?.watch_enabled" class="muted"> 下次 {{ fmt(doc?.next_watch_at ?? null) }}</span>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-head">
        <span class="card-title">子表清单</span>
        <span class="muted">
          {{ configured.length }} 个已配同步任务，{{ unconfigured.length }} 个还没配
        </span>
      </div>

      <el-table :data="items" size="small" style="width: 100%">
        <el-table-column prop="name" label="子表名称" min-width="200" />
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            <span class="muted">{{ row.kind === 'aitable_table' ? '数据表' : '工作表' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="字段数" width="90" align="right">
          <template #default="{ row }">
            <span class="muted">{{ row.field_count ?? '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="同步任务" min-width="240">
          <template #default="{ row }">
            <template v-if="row.configured">
              <span class="dot" :class="row.last_run_status === 'success' ? 'ok' : row.last_run_status === 'partial' ? 'warn' : row.last_run_status ? 'fail' : ''">
                {{ row.task_name }}
              </span>
            </template>
            <span v-else class="muted">还没配</span>
          </template>
        </el-table-column>
        <el-table-column v-if="auth.isAdmin" label="操作" width="170">
          <template #default="{ row }">
            <el-button
              v-if="row.configured"
              link
              type="primary"
              size="small"
              @click="router.push(`/tasks/${row.task_id}`)"
            >
              看任务
            </el-button>
            <el-button
              v-else
              link
              type="primary"
              size="small"
              @click="createTaskFor(row)"
            >
              建任务
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div v-if="!items.length && !loading" class="empty">
        <div class="empty-title">还没有子表信息</div>
        <div>点「重新读取」拉一次。</div>
      </div>
    </div>

    <DocEditDialog v-model="editVisible" :doc="doc" @saved="load" />
  </div>
</template>

<style scoped>
.crumb {
  font-size: var(--fs-label);
  color: var(--text-3);
  margin-bottom: 4px;
}

.crumb a {
  cursor: pointer;
}

.head-actions {
  display: flex;
  gap: 10px;
}

.stat-row {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.stat {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px var(--space-4);
  min-width: 96px;
}

.stat.wide {
  min-width: 170px;
}

.stat-num {
  font-size: 22px;
  font-weight: 600;
  line-height: 1.2;
  color: var(--text-1);
}

.stat-num.warn {
  color: var(--warn);
}

.stat-label {
  font-size: var(--fs-label);
  color: var(--text-3);
}

.stat-text {
  margin-top: 2px;
  color: var(--text-1);
}

.inline-link {
  margin-left: 8px;
  cursor: pointer;
}

.fail-box {
  border: 1px solid var(--danger);
  background: var(--danger-weak);
  border-radius: var(--radius);
  padding: var(--space-4);
  margin-bottom: 12px;

  overflow-wrap: anywhere;
  min-width: 0;
}

.fail-head {
  display: flex;
  gap: 10px;
  align-items: baseline;
  flex-wrap: wrap;
}

.fail-msg {
  font-weight: 600;
  color: var(--danger);

  overflow-wrap: anywhere;
  min-width: 0;
  max-height: 150px;
  overflow-y: auto;
}

.fail-hint {
  margin-top: 8px;
  color: var(--text-2);
  overflow-wrap: anywhere;
  line-height: 1.7;
}

.diag {
  margin-top: 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 8px 12px;
}

.diag-row {
  display: flex;
  gap: 12px;
  padding: 3px 0;
  font-size: var(--fs-label);
}

.diag-key {
  width: 110px;
  flex: none;
  color: var(--text-3);
}

.attempts {
  margin-top: 10px;
}

.attempt {
  display: flex;
  gap: 10px;
  align-items: baseline;
  padding: 4px 0;
  font-size: var(--fs-label);
  border-bottom: 1px dashed var(--border);
}

.attempt:last-child {
  border-bottom: none;
}

.attempt-label {
  width: 76px;
  flex: none;
  font-weight: 600;
}

.attempt-msg {
  color: var(--text-2);
  word-break: break-all;
}
</style>
