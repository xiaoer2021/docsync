<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { toastErr, toastOk } from '@/api/client';
import DbBadge from '@/components/DbBadge.vue';
import { createDatasource, deleteDatasource, inspectTable, listDatasources, listTables, listTasks, tableRows, testDatasourceDraft, updateDatasource, type Datasource, type TableInfo, type Task, type TestResult, } from '@/api/sync';
import { useAuthStore } from '@/stores/auth';
const auth = useAuthStore();
const items = ref<Datasource[]>([]);
const loading = ref(false);
const tasks = ref<Task[]>([]);
const dialogVisible = ref(false);
const saving = ref(false);
const editingId = ref<number | null>(null);
const form = reactive({
    name: '',
    db_type: 'sqlserver',
    host: '',
    port: 1433,
    database: '',
    username: '',
    password: '',
    remark: '',
});
const connTest = ref<TestResult | null>(null);
const testingConn = ref(false);
const connSignature = computed(() => [form.db_type, form.host, form.port, form.database, form.username, form.password].join('\u0000'));
const testedSignature = ref('');
const testPassed = computed(() => Boolean(connTest.value?.ok) && testedSignature.value === connSignature.value);
async function testConnection() {
    if (!form.host || !form.database || !form.username) {
        ElMessage.warning('先把主机、库名、账号填上');
        return;
    }
    testingConn.value = true;
    connTest.value = null;
    try {
        const result = await testDatasourceDraft({
            db_type: form.db_type,
            host: form.host,
            port: form.port,
            database: form.database,
            username: form.username,
            ...(form.password ? { password: form.password } : {}),
            ...(editingId.value ? { ds_id: editingId.value } : {}),
        });
        connTest.value = result;
        testedSignature.value = connSignature.value;
    }
    catch (err) {
        toastErr(err, '测试失败');
    }
    finally {
        testingConn.value = false;
    }
}
function maskMiddle(value: string): string {
    if (!value)
        return '—';
    if (value.length <= 4)
        return `${value[0]}***${value[value.length - 1]}`;
    const head = Math.ceil(value.length * 0.3);
    const tail = Math.max(2, Math.floor(value.length * 0.25));
    return `${value.slice(0, head)}***${value.slice(value.length - tail)}`;
}
async function load() {
    loading.value = true;
    try {
        items.value = await listDatasources();
    }
    catch (err) {
        toastErr(err, '读取数据账号失败');
    }
    finally {
        loading.value = false;
    }
}
async function loadTasks() {
    try {
        tasks.value = await listTasks();
    }
    catch {
        tasks.value = [];
    }
}
function tasksOf(ds: Datasource): Task[] {
    return tasks.value.filter((t) => Number(t.target?.datasource_id) === ds.id);
}
function openCreate() {
    editingId.value = null;
    Object.assign(form, {
        name: '',
        db_type: 'sqlserver',
        host: '',
        port: 1433,
        database: '',
        username: '',
        password: '',
        remark: '',
    });
    connTest.value = null;
    testedSignature.value = '';
    dialogVisible.value = true;
}
function openEdit(ds: Datasource) {
    editingId.value = ds.id;
    Object.assign(form, {
        name: ds.name,
        db_type: ds.db_type,
        host: ds.host,
        port: ds.port,
        database: ds.database,
        username: ds.username,
        password: '',
        remark: ds.remark || '',
    });
    connTest.value = null;
    testedSignature.value = '';
    dialogVisible.value = true;
}
async function submit() {
    if (!form.name || !form.host || !form.database || !form.username) {
        ElMessage.warning('名称、主机、库名、账号都要填');
        return;
    }
    if (!testPassed.value) {
        ElMessage.warning('先测一下连通性，通了才能保存');
        return;
    }
    saving.value = true;
    try {
        const payload: Record<string, unknown> = {
            name: form.name,
            db_type: form.db_type,
            host: form.host,
            port: form.port,
            database: form.database,
            username: form.username,
            remark: form.remark,
        };
        if (form.password)
            payload.password = form.password;
        if (editingId.value) {
            await updateDatasource(editingId.value, payload);
            toastOk('已保存');
        }
        else {
            await createDatasource(payload);
            toastOk('已新增');
        }
        dialogVisible.value = false;
        await load();
    }
    catch (err) {
        toastErr(err, '保存失败');
    }
    finally {
        saving.value = false;
    }
}
async function remove(ds: Datasource) {
    const used = tasksOf(ds).length;
    const extra = used ? `\n还有 ${used} 个同步任务在用这个账号。` : '';
    try {
        await ElMessageBox.confirm(`确定删除数据账号「${ds.name}」吗？${extra}`, '删除', {
            confirmButtonText: '删除',
            cancelButtonText: '取消',
            type: 'warning',
        });
    }
    catch {
        return;
    }
    try {
        await deleteDatasource(ds.id);
        toastOk('已删除');
        await load();
    }
    catch (err) {
        toastErr(err, '删除失败');
    }
}
const useVisible = ref(false);
const useDs = ref<Datasource | null>(null);
function openUsage(ds: Datasource) {
    useDs.value = ds;
    useVisible.value = true;
}
const browserVisible = ref(false);
const browserDs = ref<Datasource | null>(null);
const tables = ref<string[]>([]);
const tableKeyword = ref('');
const loadingTables = ref(false);
const tableInfo = ref<TableInfo | null>(null);
const PAGE_SIZE = 100;
const viewMode = ref<'data' | 'columns'>('data');
const loadingRows = ref(false);
const sortColumn = ref('');
const sortDesc = ref(true);
const rows = reactive({
    columns: [] as string[],
    rows: [] as (string | null)[][],
    total: 0,
    offset: 0,
    limit: PAGE_SIZE,
});
const filters = reactive<Record<string, string>>({});
async function applyFilter() {
    if (!tableInfo.value)
        return;
    await loadRows(tableInfo.value.name, 0);
}
function clearFilters() {
    for (const key of Object.keys(filters))
        delete filters[key];
}
const ourTables = computed(() => {
    const dsId = browserDs.value?.id;
    if (!dsId)
        return new Set<string>();
    return new Set(tasks.value
        .filter((t) => t.target?.datasource_id === dsId && t.target_table)
        .map((t) => String(t.target_table).toLowerCase()));
});
const visibleTables = computed(() => tables.value.filter((name) => ourTables.value.has(name.toLowerCase())));
const ownerTask = computed(() => {
    if (!tableInfo.value || !browserDs.value)
        return null;
    return (tasks.value.find((t) => t.target?.datasource_id === browserDs.value?.id &&
        String(t.target_table || '').toLowerCase() === tableInfo.value?.name.toLowerCase()) || null);
});
const ourColumns = computed<Set<string>>(() => {
    const t = ownerTask.value;
    if (!t)
        return new Set();
    const names = (t.columns || []).map((c) => String(c.target || '')).filter(Boolean);
    return new Set(names);
});
function hasColumnInfo(): boolean {
    return ourColumns.value.size > 0;
}
const visibleIndexes = computed(() => {
    if (!hasColumnInfo()) {
        return rows.columns.map((_, i) => i);
    }
    const idx: number[] = [];
    rows.columns.forEach((c, i) => {
        if (ourColumns.value.has(c))
            idx.push(i);
    });
    return idx.length ? idx : rows.columns.map((_, i) => i);
});
const visibleColumns = computed(() => visibleIndexes.value.map((i) => rows.columns[i]));
const visibleRows = computed(() => rows.rows.map((r) => visibleIndexes.value.map((i) => r[i] ?? null)));
async function openBrowser(ds: Datasource) {
    browserDs.value = ds;
    browserVisible.value = true;
    tableInfo.value = null;
    tableKeyword.value = '';
    viewMode.value = 'data';
    await loadTables();
}
async function loadTables() {
    if (!browserDs.value)
        return;
    loadingTables.value = true;
    try {
        tables.value = await listTables(browserDs.value.id, tableKeyword.value || undefined);
    }
    catch (err) {
        toastErr(err, '读表清单失败');
    }
    finally {
        loadingTables.value = false;
    }
}
async function pickTable(name: string) {
    if (!browserDs.value)
        return;
    try {
        tableInfo.value = await inspectTable(browserDs.value.id, name);
    }
    catch (err) {
        toastErr(err, '读表结构失败');
        return;
    }
    sortColumn.value = '';
    clearFilters();
    await loadRows(name, 0);
}
async function loadRows(name: string, offset: number) {
    if (!browserDs.value)
        return;
    loadingRows.value = true;
    try {
        const active = Object.entries(filters).find(([, v]) => v.trim());
        const result = await tableRows(browserDs.value.id, name, {
            limit: PAGE_SIZE,
            offset,
            order_by: sortColumn.value || undefined,
            desc: sortDesc.value,
            filter_column: active?.[0],
            filter_value: active?.[1].trim() || undefined,
        });
        rows.columns = result.columns;
        rows.rows = result.rows;
        rows.total = result.total;
        rows.offset = offset;
    }
    catch (err) {
        toastErr(err, '读表数据失败');
    }
    finally {
        loadingRows.value = false;
    }
}
async function pageRows(offset: number) {
    if (!tableInfo.value)
        return;
    await loadRows(tableInfo.value.name, Math.max(offset, 0));
}
async function sortBy(column: string) {
    if (!tableInfo.value)
        return;
    if (sortColumn.value === column)
        sortDesc.value = !sortDesc.value;
    else {
        sortColumn.value = column;
        sortDesc.value = true;
    }
    await loadRows(tableInfo.value.name, 0);
}
onMounted(async () => {
    await load();
    await loadTasks();
});
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">数据账号</h1>
        <div class="page-sub">数据最终要写进去的那个库。配一次，所有同步任务共用。</div>
      </div>
      <el-button v-if="auth.isAdmin" type="primary" @click="openCreate">新增数据账号</el-button>
    </div>

    <el-alert
      v-if="!items.length && !loading"
      type="info"
      :closable="false"
      show-icon
      title="还没有配数据账号"
      description="点右上角「新增数据账号」，填 SQL Server 或 MySQL 的连接信息。保存前会先测一次连通性，连不上不给保存。"
    />

    <div v-else class="card">
      <el-table v-loading="loading" :data="items" size="small" style="width: 100%">
        <el-table-column prop="name" label="名称" min-width="130" />
        <el-table-column label="类型" width="140">
          <template #default="{ row }">
            <DbBadge :type="row.db_type" :label="row.db_type_label" />
          </template>
        </el-table-column>
        <el-table-column label="地址" min-width="230">
          <template #default="{ row }">
            <span class="mono" :title="`${row.host}:${row.port}/${row.database}`">
              {{ maskMiddle(`${row.host}:${row.port}`) }}/{{ row.database }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="账号" width="130">
          <template #default="{ row }">
            <span class="mono">{{ maskMiddle(row.username) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="被任务使用" width="120">
          <template #default="{ row }">
            <span v-if="tasksOf(row).length" class="link" @click="openUsage(row)">
              {{ tasksOf(row).length }} 个任务
            </span>
            <span v-else class="muted">没人用</span>
          </template>
        </el-table-column>

        <el-table-column v-if="auth.isAdmin" label="操作" width="210" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openBrowser(row)">预览</el-button>
            <el-button link size="small" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑数据账号' : '新增数据账号'" width="560px">
      <el-form label-width="90px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="自己认得出就行，例如 BI生产库" />
        </el-form-item>
        <el-form-item label="类型" required>
          <el-radio-group v-model="form.db_type" @change="(v: string) => (form.port = v === 'mysql' ? 3306 : 1433)">
            <el-radio-button value="sqlserver">SQL Server</el-radio-button>
            <el-radio-button value="mysql">MySQL</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="主机" required>
          <el-input v-model="form.host" placeholder="IP 或域名" />
        </el-form-item>
        <el-form-item label="端口">
          <el-input-number v-model="form.port" :min="1" :max="65535" controls-position="right" />
        </el-form-item>
        <el-form-item label="库名" required>
          <el-input v-model="form.database" placeholder="例如 BI" />
        </el-form-item>
        <el-form-item label="账号" required>
          <el-input v-model="form.username" />
        </el-form-item>
        <el-form-item :label="editingId ? '密码（留空不改）' : '密码'" :required="!editingId">
          <el-input v-model="form.password" type="password" show-password />
          <div class="field-hint">密码加密入库，任何接口都不会回显明文。</div>

          <div class="conn-row">
            <el-button size="small" :loading="testingConn" @click="testConnection">
              测试连通
            </el-button>
            <span v-if="testPassed" class="dot ok">
              连通正常
              <em v-if="connTest?.latency_ms">· {{ connTest.latency_ms }}ms</em>
            </span>
            <span v-else-if="connTest" class="dot fail">连不上</span>
            <span v-else class="muted">保存前必须先测通</span>
          </div>
          <div v-if="connTest?.version" class="field-hint">{{ connTest.version }}</div>
          <div v-if="connTest && !connTest.ok" class="conn-err">
            {{ connTest.message }}
            <div v-if="connTest.hint" class="field-hint">{{ connTest.hint }}</div>
          </div>
          <div v-else-if="connTest?.ok && !testPassed" class="field-hint warn-text">
            连接参数改过了，请重新测一次。
          </div>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="saving"
          :disabled="!testPassed"
          :title="testPassed ? '' : '先测通连通性才能保存'"
          @click="submit"
        >
          保存
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="useVisible" :title="`「${useDs?.name || ''}」被这些任务使用`" width="620px">
      <el-table :data="useDs ? tasksOf(useDs) : []" size="small" style="width: 100%">
        <el-table-column label="任务" min-width="200">
          <template #default="{ row }">{{ row.name }}</template>
        </el-table-column>
        <el-table-column label="写入的表" min-width="180">
          <template #default="{ row }">
            <span class="mono">{{ row.target_table || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <span class="dot" :class="row.status === 'enabled' ? 'ok' : ''">
              {{ row.status === 'enabled' ? '启用' : '停用' }}
            </span>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="useDs && !tasksOf(useDs).length" class="muted pad">没有任务在用这个账号。</div>
    </el-dialog>

    <el-dialog
      v-model="browserVisible"
      fullscreen
      :title="`${browserDs?.name || ''} · 数据预览`"
      class="preview-dialog"
    >
      <div class="preview">

        <aside class="preview-side">
          <div class="side-head">
            <el-input
              v-model="tableKeyword"
              size="small"
              placeholder="搜表名"
              clearable
              @keyup.enter="loadTables"
            />
            <el-button size="small" :loading="loadingTables" @click="loadTables">搜索</el-button>
          </div>
          <div class="side-list">
            <div
              v-for="t in visibleTables"
              :key="t"
              class="side-item"
              :class="{ active: tableInfo?.name === t }"
              @click="pickTable(t)"
            >
              {{ t }}
            </div>
            <div v-if="!visibleTables.length && !loadingTables" class="muted pad">
              <template v-if="tables.length">
                这台库里没有本平台建的表。这里只显示有同步任务写过去的表 ——
                其他表不属于我们，看它没意义。
              </template>
              <template v-else>没读到表</template>
            </div>
          </div>
        </aside>

        <section class="preview-main">
          <header class="preview-head">
            <div class="preview-title">
              <b>{{ tableInfo?.name || '选一张表' }}</b>
              <span v-if="tableInfo" class="muted">
                {{ rows.total || tableInfo.row_count || 0 }} 行 · {{ tableInfo.columns.length }} 列
              </span>
            </div>
            <div class="preview-tools">
              <el-radio-group v-model="viewMode" size="small">
                <el-radio-button value="data">预览数据</el-radio-button>
                <el-radio-button value="columns">预览列名</el-radio-button>
              </el-radio-group>

              <span v-if="hasColumnInfo() && viewMode === 'data'" class="muted">
                只显示本平台建的 {{ ourColumns.size }} 列
              </span>
            </div>
          </header>

          <div v-if="!tableInfo" class="preview-empty muted">从左边选一张表</div>

          <template v-else-if="viewMode === 'data'">
            <el-table
              v-loading="loadingRows"
              :data="visibleRows"
              size="small"
              border
              class="preview-table"
              show-overflow-tooltip
            >
              <el-table-column label="#" width="70" fixed>
                <template #default="{ $index }">{{ rows.offset + $index + 1 }}</template>
              </el-table-column>
              <el-table-column
                v-for="(c, i) in visibleColumns"
                :key="c"
                :label="c"
                min-width="150"
                show-overflow-tooltip
              >
                <template #header>
                  <div class="col-head">
                    <span class="sortable-head" @click="sortBy(c)">
                      {{ c }}
                      <em v-if="sortColumn === c">{{ sortDesc ? '↓' : '↑' }}</em>
                    </span>

                    <el-input
                      v-model="filters[c]"
                      size="small"
                      placeholder="筛选"
                      clearable
                      @keyup.enter="applyFilter"
                      @change="applyFilter"
                    />
                  </div>
                </template>
                <template #default="{ row }">{{ row[i] ?? '' }}</template>
              </el-table-column>
            </el-table>

            <footer class="preview-foot">
              <el-button
                size="small"
                :disabled="rows.offset <= 0"
                @click="pageRows(rows.offset - rows.limit)"
              >
                上一页
              </el-button>
              <span class="muted">
                第 {{ Math.floor(rows.offset / rows.limit) + 1 }} 页 · 本页 {{ rows.rows.length }} 行
              </span>
              <el-button
                size="small"
                :disabled="rows.offset + rows.limit >= (rows.total || 0)"
                @click="pageRows(rows.offset + rows.limit)"
              >
                下一页
              </el-button>
              <span class="muted spacer">点列名排序</span>
            </footer>
          </template>

          <template v-else>
            <div class="cols">
              <span
                v-for="(typ, name) in tableInfo.column_types"
                :key="name"
                class="col-chip"
                :class="{ ours: ourColumns.has(String(name)) }"
              >
                {{ name }}<em>{{ typ }}</em>
                <b v-if="ourColumns.has(String(name))">本平台</b>
              </span>
            </div>
          </template>
        </section>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>

.field-hint {
  font-size: var(--fs-label);
  color: var(--text-3);
  line-height: 1.6;
  width: 100%;
}

.conn-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
  width: 100%;
}

.conn-err {
  margin-top: 6px;
  font-size: var(--fs-label);
  color: var(--danger);
  word-break: break-all;
  line-height: 1.6;
  width: 100%;
}

.warn-text {
  color: var(--warn);
}

.link {
  color: var(--brand);
  cursor: pointer;
}

.pad {
  padding: 10px;
}

.preview {
  display: flex;
  gap: 14px;
  height: calc(100vh - 130px);
}

.preview-side {
  width: 260px;
  flex: none;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
}

.side-head {
  display: flex;
  gap: 8px;
}

.side-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
}

.side-item {
  padding: 8px 10px;
  cursor: pointer;
  border-bottom: 1px solid var(--border);
  font-size: var(--fs-label);
  word-break: break-all;
}

.side-item:hover {
  background: var(--brand-weak-2);
}

.side-item.active {
  background: var(--brand-weak);
  color: var(--brand);
  font-weight: 600;
}

.preview-main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.preview-head {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.preview-title {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.preview-tools {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 14px;
}

.preview-table {
  flex: 1;
  min-height: 0;
}

.preview-empty {
  flex: 1;
  display: grid;
  place-items: center;
}

.preview-foot {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: none;
}

.spacer {
  margin-left: auto;
}

.sortable-head {
  cursor: pointer;
  user-select: none;
}

.sortable-head em {
  font-style: normal;
  color: var(--brand);
}

.col-head {
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: flex-start;
}

.col-head :deep(.el-input__wrapper) {
  padding: 0 6px;
  box-shadow: 0 0 0 1px var(--border) inset;
}

.preview-foot {
  justify-content: center;
}

.preview-foot .spacer {
  margin-left: 0;
}

.cols {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  overflow-y: auto;
  align-content: flex-start;
}

.col-chip {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 3px 8px;
  font-size: var(--fs-label);
}

.col-chip.ours {
  border-color: var(--brand);
}

.col-chip em {
  font-style: normal;
  color: var(--text-3);
  margin-left: 5px;
}

.col-chip b {
  margin-left: 6px;
  font-size: var(--fs-micro);
  color: var(--brand);
}
</style>
