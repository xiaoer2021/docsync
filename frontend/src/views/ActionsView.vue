<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { ElMessageBox } from 'element-plus';
import { toastErr, toastOk } from '@/api/client';
import { deleteAction, listActionRecords, listActions, testAction, ON_MODE_OPTIONS, type Action, type ActionRecord, type Channel, type ChannelResult, } from '@/api/actions';
import ActionFormDialog from '@/components/ActionFormDialog.vue';
import { useAuthStore } from '@/stores/auth';
const auth = useAuthStore();
const actions = ref<Action[]>([]);
const loading = ref(false);
const testing = ref<number | null>(null);
const formVisible = ref(false);
const formTarget = ref<Action | null>(null);
const testVisible = ref(false);
const testTarget = ref('');
const testResults = ref<ChannelResult[]>([]);
const testOk = ref(false);
async function load() {
    loading.value = true;
    try {
        actions.value = await listActions();
    }
    catch (err) {
        toastErr(err, '读取后置动作失败');
    }
    finally {
        loading.value = false;
    }
}
function openCreate() {
    formTarget.value = null;
    formVisible.value = true;
}
function openEdit(action: Action) {
    formTarget.value = action;
    formVisible.value = true;
}
async function remove(action: Action) {
    try {
        await ElMessageBox.confirm(`确定删除「${action.name}」吗？`, '删除后置动作', {
            confirmButtonText: '删除',
            cancelButtonText: '取消',
            type: 'warning',
        });
    }
    catch {
        return;
    }
    try {
        await deleteAction(action.id);
        toastOk('已删除');
        await load();
    }
    catch (err) {
        toastErr(err, '删除失败');
    }
}
async function doTest(action: Action) {
    testing.value = action.id;
    testTarget.value = action.name;
    try {
        const result = await testAction(action.id);
        testResults.value = result.results;
        testOk.value = result.ok;
        testVisible.value = true;
    }
    catch (err) {
        toastErr(err, '试发失败');
    }
    finally {
        testing.value = null;
    }
}
const recordVisible = ref(false);
const recordTarget = ref('');
const recordLoading = ref(false);
const records = ref<ActionRecord[]>([]);
async function openRecords(action: Action) {
    recordTarget.value = action.name;
    records.value = [];
    recordVisible.value = true;
    recordLoading.value = true;
    try {
        records.value = await listActionRecords(action.id);
    }
    catch (err) {
        toastErr(err, '读取执行记录失败');
    }
    finally {
        recordLoading.value = false;
    }
}
function onLabel(on: string | null): string {
    return ON_MODE_OPTIONS.find((o) => o.value === on)?.label || on || '—';
}
function fmtTime(value: string | null): string {
    return value ? value.replace('T', ' ').slice(0, 19) : '—';
}
onMounted(load);
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">后置动作</h1>
        <div class="page-sub">
          同步成功（或失败）之后要触发什么。配一次，多个任务可以共用。
        </div>
      </div>
      <div class="head-actions">
        <el-button size="small" @click="load">刷新</el-button>
        <el-button v-if="auth.isAdmin" type="primary" size="small" @click="openCreate">
          新建动作
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="!actions.length && !loading"
      type="info"
      :closable="false"
      show-icon
      title="还没有后置动作"
      description="同步完成后调用下游接口刷新数据，或发送结果通知。一个动作可配置多个请求与通知渠道。"
    />

    <div v-else class="card">
      <el-table v-loading="loading" :data="actions" size="small" style="width: 100%">
        <el-table-column label="名称" min-width="180">
          <template #default="{ row }">
            <div class="name">{{ row.name }}</div>
            <div v-if="row.remark" class="sub">{{ row.remark }}</div>
          </template>
        </el-table-column>
        <el-table-column label="做什么" min-width="220">
          <template #default="{ row }">
            <div class="tag-row">
              <span v-for="c in row.channels" :key="c.kind" class="tag">
                {{ c.kind === 'dingtalk_robot' ? '钉钉机器人' : c.kind === 'interface' ? '接口调度' : 'Webhook 调度' }}
              </span>
            </div>
            <div class="sub mono ellipsis">
              {{
                row.channels
                  .map((c: Channel) => String(c.config.webhook || c.config.url || ''))
                  .filter(Boolean)
                  .join('　')
              }}
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <span class="dot" :class="row.enabled ? 'ok' : ''">
              {{ row.enabled ? '启用' : '停用' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="被几个任务用" width="120">
          <template #default="{ row }">
            <span :class="{ muted: !row.used_by }">{{ row.used_by || '没人用' }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="auth.isAdmin" label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" :loading="testing === row.id" @click="doTest(row)">
              试发
            </el-button>

            <el-button link size="small" @click="openRecords(row)">记录</el-button>
            <el-button link size="small" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <ActionFormDialog v-model="formVisible" :action="formTarget" @saved="load" />

    <el-dialog
      v-model="recordVisible"
      :title="`「${recordTarget}」的执行记录`"
      width="820px"
      top="8vh"
      append-to-body
      class="action-record-dialog"
    >
      <el-table v-loading="recordLoading" :data="records" size="small" style="width: 100%">
        <el-table-column label="时间" width="160">
          <template #default="{ row }">
            <span class="muted">{{ fmtTime(row.started_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="任务" min-width="180">
          <template #default="{ row }">
            <span v-if="row.task_name">{{ row.task_name }}</span>
            <span v-else class="muted">（任务已删除）</span>
          </template>
        </el-table-column>
        <el-table-column label="触发条件" width="120">
          <template #default="{ row }">{{ onLabel(row.trigger_on) }}</template>
        </el-table-column>
        <el-table-column label="结果" width="90">
          <template #default="{ row }">
            <span
              class="dot"
              :class="
                row.status === 'success' ? 'ok' : row.status === 'skipped' ? 'warn' : 'fail'
              "
            >
              {{ row.status === 'success' ? '成功' : row.status === 'skipped' ? '跳过' : '失败' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="80">
          <template #default="{ row }">
            {{ row.duration_ms ? `${(row.duration_ms / 1000).toFixed(1)}s` : '—' }}
          </template>
        </el-table-column>
        <el-table-column label="说明" min-width="200">
          <template #default="{ row }">
            <span v-if="row.error_message" class="record-err" :title="row.error_message">
              {{ row.error_message }}
            </span>
            <span v-else-if="row.http_status" class="muted">HTTP {{ row.http_status }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
      </el-table>

      <div v-if="!records.length && !recordLoading" class="muted pad">
        这个动作还没被触发过。可能是它绑的任务还没跑到那个条件，或者绑的是「成功时」而任务一直没成功。
      </div>

      <template #footer>
        <el-button @click="recordVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="testVisible" :title="`试发：${testTarget}`" width="620px">
      <el-alert
        :type="testOk ? 'success' : 'error'"
        :closable="false"
        show-icon
        :title="testOk ? '全部渠道发送成功' : '有渠道发送失败'"
      />
      <div v-for="(r, i) in testResults" :key="i" class="result" :class="{ bad: !r.ok }">
        <div class="result-head">
          <span class="dot" :class="r.ok ? 'ok' : 'fail'">{{ r.ok ? '成功' : '失败' }}</span>
          <b>{{ r.label }}</b>
          <span class="muted">{{ r.elapsed_ms }} ms</span>
          <span v-if="r.http_status" class="muted">HTTP {{ r.http_status }}</span>
        </div>
        <div v-if="r.error" class="result-error">{{ r.error }}</div>
        <pre v-if="r.detail" class="render-box">{{ r.detail }}</pre>
      </div>
      <div class="field-hint">试发用的是一份样例数据，不会影响任何实际数据，也不会真去同步。</div>
    </el-dialog>
  </div>
</template>

<style scoped>
.head-actions {
  display: flex;
  gap: 8px;
}

.name {
  font-weight: 600;
}

.sub {
  font-size: var(--fs-label);
  color: var(--text-3);
  line-height: 1.5;
}

.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag-row {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 2px;
}

.tag {
  font-size: var(--fs-label);
  padding: 1px 8px;
  border-radius: var(--radius-sm);
  background: var(--brand-weak);
  color: var(--brand);
}

.field-hint {
  font-size: var(--fs-label);
  color: var(--text-3);
  line-height: 1.6;
  margin-top: 4px;
}

.render-box {
  margin-top: 6px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  font-size: var(--fs-label);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow: auto;
}

.result {
  border: 1px solid var(--border);
  border-left: 3px solid var(--ok);
  border-radius: var(--radius-sm);
  padding: var(--space-4);
  margin-top: 10px;
}

.result.bad {
  border-left-color: var(--danger);
}

.result-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.result-error {
  margin-top: 4px;
  font-size: var(--fs-label);
  color: var(--danger);
  word-break: break-all;
}
.pad {
  padding: 12px;
}

.record-err {
  font-size: var(--fs-label);
  color: var(--danger);
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

</style>
