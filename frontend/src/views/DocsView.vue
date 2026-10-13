<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import { toastErr, toastOk } from '@/api/client';
import { checkDocColumns, createDoc, deleteDoc, docSubItems, listApps, listDocs, listGroups, probeDoc, resolveDoc, searchDocs, setSheetColumnCheck, updateDoc, type ColumnCheckResult, type DingApp, type DocItem, type DocResolveResult, type DocSearchHit, type Group, type SubItem, } from '@/api/dingtalk';
import DocEditDialog from '@/components/DocEditDialog.vue';
import GroupManagerDialog from '@/components/GroupManagerDialog.vue';
import GroupSelect from '@/components/GroupSelect.vue';
import { platformOf } from '@/branding';
import AppPicker from '@/components/AppPicker.vue';
import PlatformIcon from '@/components/PlatformIcon.vue';
import { useAuthStore } from '@/stores/auth';
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const docs = ref<DocItem[]>([]);
const apps = ref<DingApp[]>([]);
const groups = ref<Group[]>([]);
const loading = ref(false);
const filters = reactive({
    group_id: undefined as number | undefined,
    app_id: undefined as number | undefined,
    keyword: '',
    drift_only: false,
});
const addVisible = ref(false);
const resolving = ref(false);
const saving = ref(false);
const resolved = ref<DocResolveResult | null>(null);
const addForm = reactive({
    ref: '',
    app_id: undefined as number | undefined,
    name: '',
    doc_type: '',
    group_ids: [] as number[],
});
const addPlatform = computed(() => {
    const app = apps.value.find((a) => a.id === addForm.app_id);
    return app ? platformOf(app.platform).key : 'dingtalk';
});
watch(addPlatform, (platform) => {
    pickMode.value = platform === 'wps' ? 'ref' : 'search';
});
const applyUrl = computed(() => {
    const text = resolved.value?.error || '';
    const found = /https:\/\/open\.feishu\.cn\/\S+/.exec(text);
    return found ? found[0].replace(/[）,。；：]+$/, '') : '';
});
const pickMode = ref<'search' | 'ref'>('search');
const searchKeyword = ref('');
const searching = ref(false);
const searched = ref(false);
const searchHits = ref<DocSearchHit[]>([]);
const searchToken = ref<string | null>(null);
async function load() {
    loading.value = true;
    try {
        docs.value = await listDocs({
            group_id: filters.group_id,
            app_id: filters.app_id,
            keyword: filters.keyword || undefined,
            drift_only: filters.drift_only || undefined,
        });
    }
    catch (err) {
        toastErr(err, '读取表单失败');
    }
    finally {
        loading.value = false;
    }
}
function openAdd() {
    resolved.value = null;
    searched.value = false;
    searchHits.value = [];
    searchToken.value = null;
    searchKeyword.value = '';
    pickMode.value = 'search';
    Object.assign(addForm, {
        ref: '',
        app_id: apps.value[0]?.id,
        name: '',
        doc_type: '',
        group_id: filters.group_id,
    });
    addVisible.value = true;
}
async function doSearch(loadMore: boolean) {
    const keyword = searchKeyword.value.trim();
    if (!addForm.app_id) {
        ElMessage.warning('先选应用');
        return;
    }
    if (!keyword) {
        ElMessage.warning('输个关键词');
        return;
    }
    searching.value = true;
    try {
        const res = await searchDocs(addForm.app_id, keyword, loadMore ? searchToken.value : null);
        searchHits.value = loadMore ? [...searchHits.value, ...res.items] : res.items;
        searchToken.value = res.next_token;
        searched.value = true;
    }
    catch (err) {
        toastErr(err, '搜索失败');
    }
    finally {
        searching.value = false;
    }
}
async function pickHit(hit: DocSearchHit) {
    if (hit.registered_doc_id) {
        ElMessage.info(`「${hit.name}」已经登记过了（别名：${hit.registered_name}）`);
        return;
    }
    pickMode.value = 'ref';
    addForm.ref = hit.uuid;
    if (!addForm.name && hit.name)
        addForm.name = hit.name;
    await doResolve();
}
function suggestName(text: string): string {
    const s = (text || '')
        .replace(/https?:\/\/\S+/g, ' ')
        .replace(/[【\[［][^】\]］]*[】\]］]/g, ' ');
    const parts = s
        .split(/[#\n\r\t|｜]+/)
        .map((p) => p.trim())
        .filter((p) => p.length > 3)
        .filter((p) => !/^\d+$/.test(p))
        .filter((p) => !/^\d{4}[-/.]\d{1,2}([-/.]\d{1,2})?$/.test(p))
        .filter((p) => !/^[A-Za-z]{1,4}\d*$/.test(p));
    if (!parts.length)
        return '';
    return parts.reduce((a, b) => (b.length > a.length ? b : a)).slice(0, 80);
}
function onRefChange() {
    if (addForm.name.trim())
        return;
    const guess = suggestName(addForm.ref);
    if (guess)
        addForm.name = guess;
}
async function doResolve() {
    if (!addForm.ref.trim() || !addForm.app_id) {
        ElMessage.warning('先选应用，再粘链接');
        return;
    }
    resolving.value = true;
    resolved.value = null;
    try {
        resolved.value = await resolveDoc(addForm.ref.trim(), addForm.app_id, undefined, addForm.doc_type);
        if (resolved.value?.ok)
            onRefChange();
    }
    catch (err) {
        toastErr(err, '解析失败');
    }
    finally {
        resolving.value = false;
    }
}
async function submitAdd() {
    if (!resolved.value?.ok || !addForm.app_id)
        return;
    saving.value = true;
    try {
        const doc = await createDoc({
            ref: addForm.ref.trim(),
            app_id: addForm.app_id,
            name: addForm.name || undefined,
            doc_type: resolved.value.doc_type || undefined,
            group_ids: addForm.group_ids,
        });
        toastOk(`已登记「${doc.name}」，读到 ${doc.sheet_count} 个子表`);
        addVisible.value = false;
        await load();
    }
    catch (err) {
        toastErr(err, '登记失败');
    }
    finally {
        saving.value = false;
    }
}
const probingId = ref<number | null>(null);
async function reprobe(doc: DocItem) {
    if (probingId.value !== null)
        return;
    probingId.value = doc.id;
    try {
        const result = await probeDoc(doc.id);
        if (result.ok) {
            toastOk(`重新探测完成，${result.sub_items.length} 个子表`);
        }
        else {
            toastErr({ message: result.error || '探测失败' }, '探测失败');
        }
        await load();
    }
    catch (err) {
        toastErr(err, '探测失败');
    }
    finally {
        probingId.value = null;
    }
}
async function toggleWatch(doc: DocItem) {
    try {
        await updateDoc(doc.id, { watch_enabled: !doc.watch_enabled });
        toastOk(doc.watch_enabled ? '已关闭子表变化检查' : '已开启子表变化检查');
        await load();
    }
    catch (err) {
        toastErr(err, '操作失败');
    }
}
const sheetCache = reactive<Record<number, SubItem[]>>({});
const sheetLoading = reactive<Record<number, boolean>>({});
const tableRef = ref();
const expanded = ref<DocItem[]>([]);
async function loadSheets(doc: DocItem) {
    if (sheetCache[doc.id] || sheetLoading[doc.id])
        return;
    sheetLoading[doc.id] = true;
    try {
        sheetCache[doc.id] = await docSubItems(doc.id);
    }
    catch (err) {
        toastErr(err, '读子表失败');
        sheetCache[doc.id] = [];
    }
    finally {
        sheetLoading[doc.id] = false;
    }
}
function onExpand(row: DocItem, expandedRows: DocItem[]) {
    expanded.value = expandedRows;
    if (expandedRows.some((d) => d.id === row.id))
        loadSheets(row);
}
function toggleExpand(doc: DocItem) {
    if (!tableRef.value)
        return;
    loadSheets(doc);
    tableRef.value.toggleRowExpansion(doc, !expanded.value.some((d) => d.id === doc.id));
}
function buildTask(doc: DocItem, sheet: SubItem) {
    router.push({
        name: 'task-new',
        query: { doc_id: String(doc.id), sheet_id: sheet.id, from: 'docs', expand: String(doc.id) },
    });
}
async function expandFromQuery() {
    const id = Number(route.query.expand);
    if (!id)
        return;
    router.replace({ path: '/docs', query: {} });
    const doc = docs.value.find((d) => d.id === id);
    if (!doc)
        return;
    await loadSheets(doc);
    tableRef.value?.toggleRowExpansion(doc, true);
}
function onDocCheck() {
    const doc = docEditTarget.value;
    docEditVisible.value = false;
    if (doc)
        void checkColumns(doc);
}
const docEditVisible = ref(false);
const docEditTarget = ref<DocItem | null>(null);
const groupVisible = ref(false);
function openDocEdit(doc: DocItem) {
    docEditTarget.value = doc;
    docEditVisible.value = true;
}
interface TaskPickRow {
    task_id: number;
    task_name: string;
    sheets: string[];
    status: string | null;
}
const taskPickVisible = ref(false);
const taskPickRows = ref<TaskPickRow[]>([]);
const taskPickDoc = ref<DocItem | null>(null);
function gotoTask(taskId: number, doc: DocItem) {
    router.push({
        path: `/tasks/${taskId}/edit`,
        query: { from: 'docs', expand: String(doc.id) },
    });
}
async function editTaskOf(doc: DocItem) {
    await loadSheets(doc);
    const byTask = new Map<number, TaskPickRow>();
    for (const s of sheetCache[doc.id] || []) {
        if (!s.task_id)
            continue;
        const hit = byTask.get(s.task_id);
        if (hit)
            hit.sheets.push(s.name);
        else
            byTask.set(s.task_id, {
                task_id: s.task_id,
                task_name: (s.task_name || '').replace('（合并进这个任务）', ''),
                sheets: [s.name],
                status: s.task_status,
            });
    }
    const tasks = [...byTask.values()];
    if (!tasks.length) {
        ElMessage.info('这个表单还没有同步任务 —— 展开子表后可以逐个「建任务」。');
        return;
    }
    if (tasks.length === 1) {
        gotoTask(tasks[0].task_id, doc);
        return;
    }
    taskPickDoc.value = doc;
    taskPickRows.value = tasks;
    taskPickVisible.value = true;
}
function goTask(taskId: number) {
    taskPickVisible.value = false;
    const doc = taskPickDoc.value;
    if (doc)
        gotoTask(taskId, doc);
}
function subStatusText(s: SubItem) {
    if (s.task_status !== 'enabled')
        return '已停用';
    if (s.last_run_status === 'success')
        return '上次成功';
    if (s.last_run_status === 'partial')
        return '部分成功';
    if (s.last_run_status)
        return '上次失败';
    return '没跑过';
}
function subStatusClass(s: SubItem) {
    if (s.task_status !== 'enabled')
        return '';
    if (s.last_run_status === 'success')
        return 'ok';
    if (s.last_run_status === 'partial')
        return 'warn';
    if (s.last_run_status)
        return 'fail';
    return '';
}
const columnCheckVisible = ref(false);
const columnChecking = ref(false);
const columnCheckDoc = ref('');
const columnCheck = ref<ColumnCheckResult | null>(null);
async function toggleColumnCheck(doc: DocItem, sheet: SubItem, enabled: boolean) {
    try {
        await setSheetColumnCheck(doc.id, sheet.id, enabled);
        sheet.auto_column_check = enabled;
        if (!enabled)
            sheet.column_drift = null;
        toastOk(enabled ? `「${sheet.name}」已开启自动检测新增列` : `「${sheet.name}」已关闭`);
    }
    catch (err) {
        toastErr(err, '操作失败');
    }
}
async function checkColumns(doc: DocItem) {
    columnCheckDoc.value = doc.name;
    columnCheck.value = null;
    columnCheckVisible.value = true;
    columnChecking.value = true;
    try {
        columnCheck.value = await checkDocColumns(doc.id);
    }
    catch (err) {
        toastErr(err, '列检查失败');
    }
    finally {
        columnChecking.value = false;
    }
}
async function remove(doc: DocItem) {
    try {
        await deleteDoc(doc.id);
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
onMounted(async () => {
    await load();
    await expandFromQuery();
    try {
        apps.value = await listApps();
        groups.value = await listGroups();
    }
    catch {
    }
});
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">表单管理</h1>
        <div class="page-sub">
          粘贴在线表格的链接或 ID 就能登记，平台自动识别是表格还是多维表并拉出子表清单。
        </div>
      </div>
      <div v-if="auth.isAdmin" class="head-actions">

        <el-button @click="groupVisible = true">业务分组</el-button>
        <el-button type="primary" @click="openAdd">新增在线表</el-button>
      </div>
    </div>

    <div class="card">
      <div class="card-head">

        <div class="filters">
          <el-input
            v-model="filters.keyword"
            placeholder="搜表单名或 ID"
            size="small"
            style="width: 200px"
            clearable
            @change="load"
          />
          <el-select v-model="filters.app_id" placeholder="全部应用" size="small" clearable style="width: 150px" @change="load">
            <el-option v-for="a in apps" :key="a.id" :label="a.name" :value="a.id" />
          </el-select>
          <el-select v-model="filters.group_id" placeholder="全部分组" size="small" clearable style="width: 140px" @change="load">
            <el-option v-for="g in groups" :key="g.id" :label="g.name" :value="g.id" />
          </el-select>
          <span class="filter-gap" />
          <el-checkbox v-model="filters.drift_only" size="small" @change="load">只看结构有变化</el-checkbox>
          <el-button size="small" @click="load">刷新</el-button>
        </div>
      </div>

      <el-table
        ref="tableRef"
        v-loading="loading || probingId !== null"
        :element-loading-text="probingId !== null ? '正在打开网页读表…（要几秒，别关页面）' : '正在加载…'"
        :data="docs"
        size="small"
        style="width: 100%"
        row-key="id"
        @expand-change="onExpand"
      >

        <el-table-column type="expand">
          <template #default="{ row }">
            <div v-loading="sheetLoading[row.id]" class="sub-panel">
              <div class="sub-head">
                <span>「{{ row.name }}」下的子表</span>
                <span class="muted">{{ (sheetCache[row.id] || []).length }} 个</span>
              </div>
              <el-table v-if="sheetCache[row.id]?.length" :data="sheetCache[row.id]" size="small">
                <el-table-column label="子表" min-width="200">
                  <template #default="{ row: s }">
                    <span>{{ s.name }}</span>
                    <span v-if="s.field_count" class="muted">（{{ s.field_count }} 列）</span>
                  </template>
                </el-table-column>
                <el-table-column label="状态" width="120">
                  <template #default="{ row: s }">
                    <span v-if="s.task_id" class="dot" :class="subStatusClass(s)">
                      {{ subStatusText(s) }}
                    </span>
                    <span v-else class="todo">待配任务</span>
                  </template>
                </el-table-column>
                <el-table-column label="任务" min-width="170">
                  <template #default="{ row: s }">
                    <a v-if="s.task_id" @click="router.push(`/tasks/${s.task_id}`)">
                      {{ s.task_name }}
                    </a>
                    <span v-else class="muted">—</span>
                  </template>
                </el-table-column>

                <el-table-column label="定时" width="130">
                  <template #default="{ row: s }">
                    <span
                      v-if="s.schedule_label && s.schedule_label !== '手动'"
                      class="sched-on"
                    >
                      {{ s.schedule_label }}
                    </span>
                    <span v-else-if="s.task_id" class="muted">手动</span>
                    <span v-else class="muted">—</span>
                  </template>
                </el-table-column>
                <el-table-column label="后置动作" width="110">
                  <template #default="{ row: s }">
                    <span v-if="s.post_actions_label === '无'" class="muted">无</span>
                    <span v-else-if="s.post_actions_label">{{ s.post_actions_label }}</span>
                    <span v-else class="muted">—</span>
                  </template>
                </el-table-column>
                <el-table-column label="最近一次" width="160">
                  <template #default="{ row: s }">
                    <span v-if="s.last_run_at" class="muted">{{ fmt(s.last_run_at) }}</span>
                    <span v-else class="muted">—</span>
                    <div v-if="s.column_drift" class="drift">{{ s.column_drift }}</div>
                  </template>
                </el-table-column>

                <el-table-column v-if="auth.isAdmin" label="自动检测" width="170">
                  <template #default="{ row: s }">
                    <el-checkbox
                      v-if="s.task_id"
                      :model-value="s.auto_column_check"
                      title="盯着**这一张子表**的列名有没有变（多了列、少了列、改了名），发现就提醒你"
                      @change="(v: boolean) => toggleColumnCheck(row, s, v)"
                    >
                      新增列
                    </el-checkbox>
                    <span v-else class="muted">没配任务，不用管</span>
                  </template>
                </el-table-column>
                <el-table-column v-if="auth.isAdmin" label="操作" width="150">
                  <template #default="{ row: s }">
                    <template v-if="s.task_id">
                      <el-button link size="small" @click="router.push(`/tasks/${s.task_id}/edit`)">
                        编辑任务
                      </el-button>
                    </template>
                    <el-button
                      v-else
                      link
                      type="primary"
                      size="small"
                      @click="buildTask(row, s)"
                    >
                      建任务
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>
              <div v-else class="muted pad">这个表单下没读到子表。</div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="表单" min-width="240">
          <template #default="{ row }">

            <a class="doc-name" @click="toggleExpand(row)">{{ row.name }}</a>
            <div class="sub">
              {{ row.app_name || '—' }}
              <span class="sep">·</span>
              {{ row.group_names?.length ? row.group_names.join('、') : '未分组' }}
            </div>
            <div v-if="row.structure_drift" class="drift">{{ row.structure_drift }}</div>
          </template>
        </el-table-column>
        <el-table-column label="自动检测" width="150">
          <template #default="{ row }">

            <el-checkbox
              :model-value="row.watch_enabled"
              :disabled="!auth.isAdmin"
              title="盯着这个表单里有没有**新加的子表**（比如下个月新出现的「11月」），发现就提醒你"
              @change="() => toggleWatch(row)"
            >
              新增子表
            </el-checkbox>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="150">
          <template #default="{ row }">

            <span class="type-cell">
              <PlatformIcon :platform="row.platform" :size="18" />
              <span>{{ row.doc_type_label }}</span>
            </span>
          </template>
        </el-table-column>

        <el-table-column label="子表" width="150">
          <template #default="{ row }">
            <span class="sheet-count">{{ row.sheet_count }}</span>
            <span v-if="row.unconfigured_count > 0" class="todo">待配 {{ row.unconfigured_count }}</span>
          </template>
        </el-table-column>
        <el-table-column label="最近读取" width="144">
          <template #default="{ row }">
            <span v-if="row.last_probe_ok === false" class="dot fail">失败</span>
            <span v-else class="muted">{{ fmt(row.last_probe_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="auth.isAdmin" label="操作" width="330" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="editTaskOf(row)">
              编辑任务
            </el-button>
            <el-button link size="small" @click="openDocEdit(row)">管理表单</el-button>
            <el-button
              link
              size="small"
              :loading="probingId === row.id"
              :disabled="probingId !== null && probingId !== row.id"
              @click="reprobe(row)"
            >
              {{ probingId === row.id ? '读取中…' : '重新读取' }}
            </el-button>
            <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div v-if="!docs.length && !loading" class="empty">
        <div class="empty-title">还没有登记表单</div>
        <div>点「新增表单」，搜表单名点一下，或者把链接/ID 粘进来。</div>
      </div>
    </div>

    <el-dialog v-model="addVisible" title="登记在线表格" width="700px" top="7vh">
      <el-form label-width="90px">

        <el-form-item label="归属应用" required>
          <AppPicker v-model="addForm.app_id" :apps="apps" />
        </el-form-item>

        <el-form-item label="业务分组">
          <GroupSelect v-model="addForm.group_ids" />
        </el-form-item>
      </el-form>

      <el-tabs v-model="pickMode" class="pick-tabs">

        <el-tab-pane v-if="addPlatform !== 'wps'" name="search">
          <template #label>
            搜表单<span class="tab-badge">推荐</span>
          </template>

          <div class="search-row">
            <el-input
              v-model="searchKeyword"
              placeholder="输入表单名里的关键词，例如 Coupang、营销单"
              clearable
              @keyup.enter="doSearch(false)"
            />
            <el-button type="primary" :loading="searching" @click="doSearch(false)">搜索</el-button>
          </div>
          <div class="field-hint block">
            搜到直接点一条就行，不用去平台复制链接。需要应用开通「文件搜索权限」。
          </div>

          <div v-if="searchHits.length" class="hit-list">
            <div
              v-for="hit in searchHits"
              :key="hit.uuid"
              class="hit"
              :class="{ taken: hit.registered_doc_id }"
              @click="pickHit(hit)"
            >
              <div class="hit-main">
                <span class="hit-name">{{ hit.name || '(未命名表单)' }}</span>
                <el-tag v-if="hit.registered_doc_id" size="small" type="info" effect="light">
                  已登记
                </el-tag>
              </div>
              <div class="hit-sub">
                <span v-if="hit.registered_name" class="muted">
                  别名：{{ hit.registered_name }} ·
                </span>
                <span v-if="hit.modifier" class="muted">最近改：{{ hit.modifier }} · </span>
                <span class="mono muted">{{ hit.uuid }}</span>
              </div>
            </div>
            <div v-if="searchToken" class="more">
              <el-button link type="primary" :loading="searching" @click="doSearch(true)">
                加载更多
              </el-button>
            </div>
          </div>
          <div v-else-if="searched && !searching" class="empty small">
            <div>没搜到。换个关键词，或者切到「粘链接 / ID」。</div>
          </div>
        </el-tab-pane>

        <el-tab-pane :label="addPlatform === 'wps' ? '粘贴金山分享链接' : '粘链接 / ID'" name="ref">
          <el-input
            v-model="addForm.ref"
            type="textarea"
            :rows="2"
            :placeholder="addPlatform === 'wps'
              ? '把金山文档「复制共享链接」出来的那段整条粘进来（带抬头、日期也行）'
              : '整条链接、或只填表单 ID 都行，例如 oP0MAxxxxxxYmDO'"
            @change="onRefChange"
            @blur="onRefChange"
          />
          <div class="field-hint block">
            <template v-if="addPlatform === 'wps'">
              整段粘也行 —— 后端会把里面的网址抠出来。保存时会**当场试读**：
              读得到才登记（所以这个应用得先「扫码 / 手机号登录」过）。
            </template>
            <template v-else>
              三种都认：完整链接、只填表单 ID、或者链接里带一堆参数的那种。
            </template>
          </div>
          <div class="ref-actions">

            <el-radio-group v-if="addPlatform !== 'wps'" v-model="addForm.doc_type" size="small">
              <el-radio-button value="">自动判断</el-radio-button>
              <el-radio-button value="sheet">在线表格</el-radio-button>
              <el-radio-button value="aitable">多维表</el-radio-button>
            </el-radio-group>
            <el-button type="primary" :loading="resolving" @click="doResolve">解析</el-button>
          </div>
          <div v-if="addPlatform !== 'wps'" class="field-hint block">
            自动判断会两种都试一遍；已知是哪种就直接选，少一次试错。
          </div>
        </el-tab-pane>
      </el-tabs>

      <div v-if="resolved">

        <div v-if="!resolved.ok" class="fail-box">
          <div class="fail-head">
            <span class="dot fail">解析失败</span>
            <span class="fail-msg">{{ resolved.error }}</span>
          </div>
          <div v-if="resolved.hint" class="fail-hint">{{ resolved.hint }}</div>

          <div class="diag">
            <div class="diag-row">
              <span class="diag-key">错误码</span>
              <span class="mono">{{ resolved.code || '（未返回）' }}</span>
            </div>
            <div v-if="resolved.http_status" class="diag-row">
              <span class="diag-key">HTTP 状态</span>
              <span class="mono">{{ resolved.http_status }}</span>
            </div>
            <div class="diag-row">
              <span class="diag-key">用的表单 ID</span>
              <span class="mono">{{ resolved.used_node_id || resolved.node_id }}</span>
            </div>

            <div v-if="resolved.used_operator_union_id" class="diag-row">
              <span class="diag-key">以谁的身份读</span>
              <span class="mono">{{ resolved.used_operator_union_id }}</span>
            </div>
          </div>

          <div v-if="applyUrl" class="apply-box">
            <el-button type="primary" size="small" tag="a" :href="applyUrl" target="_blank">
              去飞书申请这个权限
            </el-button>
            <span class="apply-note">
              ⚠ 申请完还要在开发者后台「创建版本并发布」才生效
            </span>
          </div>

          <div v-if="resolved.attempts.length" class="attempts">
            <div v-for="a in resolved.attempts" :key="a.doc_type" class="attempt">
              <span class="attempt-label">{{ a.label }}</span>
              <span class="mono muted">{{ a.code || '—' }}</span>
              <span class="attempt-msg">{{ a.message }}</span>
            </div>
          </div>

          <div class="fail-tips">
            <template v-if="addPlatform === 'feishu'">
              对照检查：① 这份表单的 ID 是不是 <span class="mono">{{ resolved.used_node_id }}</span>
              ② 应用有没有被加进这份文档的「分享」协作者里
              <b>（文档在知识库里的话，还要把应用加进知识库成员，光有文件分享不够）</b>
              ③ 开发者后台里权限勾完之后，有没有「创建版本并发布」
              ④ App ID / App Secret 是不是这个应用的（在「凭证与基础信息」里）
            </template>
            <template v-else>
              对照检查：① 这份表单的 ID 是不是 <span class="mono">{{ resolved.used_node_id }}</span>
              ② 那个 ID 是不是这份表单的（不是同一个表单里别的节点）
              ③ 应用和操作人有没有被加进这份表单的「分享」协作者里
              ④ AppKey 是不是这个组织的应用
            </template>
          </div>
        </div>

        <div v-else class="resolved-box">
          <div class="resolved-head">
            <span class="dot ok">解析成功</span>
            <el-tag size="small" effect="light">
              {{ resolved.doc_type === 'aitable' ? '多维表' : '在线表格' }}
            </el-tag>
            <span class="muted">表单 ID：<span class="mono">{{ resolved.node_id }}</span></span>
          </div>

          <el-form label-width="90px" style="margin-top: 12px">
            <el-form-item label="表单别名" required>
              <el-input v-model="addForm.name" placeholder="自己认得出就行，例如「Coupang平台货品」" />
              <div class="field-hint">
                从你粘的那段里**自己认出来的**（金山抬头里那个名字），认错了直接改。
              </div>
            </el-form-item>
          </el-form>

          <div class="sub-title">
            读到 {{ resolved.sub_items.length }} 个子表
            <span class="muted">（登记后在详情页可以逐个配同步任务）</span>
          </div>
          <div class="sub-list">
            <span v-for="item in resolved.sub_items" :key="item.id" class="sub-chip">
              {{ item.name }}
              <em v-if="item.field_count"> · {{ item.field_count }} 字段</em>
            </span>
          </div>
        </div>
      </div>

      <template #footer>
        <el-button @click="addVisible = false">取消</el-button>
        <el-button
          type="primary"
          :disabled="!resolved?.ok || !addForm.name"
          :loading="saving"
          @click="submitAdd"
        >
          登记
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="columnCheckVisible"
      :title="`列变化检查：${columnCheckDoc}`"
      width="820px"
      top="6vh"
    >
      <div v-if="columnChecking" class="muted pad">
        正在逐个读取子表的表头…（子表多的时候要等一会儿）
      </div>
      <template v-else-if="columnCheck">
        <el-alert
          v-if="columnCheck.error"
          type="error"
          :closable="false"
          show-icon
          :title="columnCheck.error"
        />
        <template v-else>
          <el-alert
            :type="columnCheck.changed ? 'warning' : 'success'"
            :closable="false"
            show-icon
            :title="
              columnCheck.changed
                ? `查了 ${columnCheck.checked} 个子表，${columnCheck.changed} 个有变化`
                : `查了 ${columnCheck.checked} 个子表，列都没变`
            "
            :description="
              columnCheck.changed
                ? '下面列出的这些列变了。如果目标表还没这些列，正式同步时会自动补列（只加不删）。'
                : ''
            "
          />

          <div v-for="s in columnCheck.changed_sheets" :key="s.sheet_id" class="col-change">
            <b>{{ s.sheet_name }}</b>
            <span v-if="s.first_check" class="muted">第一次检查，只记了个快照</span>
            <template v-else>
              <span v-for="c in s.added" :key="'a' + c" class="col-add">+ {{ c }}</span>
              <span v-for="c in s.removed" :key="'r' + c" class="col-del">− {{ c }}</span>
            </template>
          </div>

          <div v-if="!columnCheck.changed_sheets.length" class="muted pad">
            没有任何子表的列发生变化。
          </div>

          <div v-if="columnCheck.errors.length" class="err-box">
            <div v-for="(e, i) in columnCheck.errors" :key="i">{{ e }}</div>
          </div>
        </template>
      </template>
    </el-dialog>

    <DocEditDialog v-model="docEditVisible" :doc="docEditTarget" @saved="load" @check="onDocCheck" />

    <GroupManagerDialog v-model="groupVisible" @changed="load" />

    <el-dialog v-model="taskPickVisible" title="这个表单下有多个任务，改哪一个？" width="640px">
      <el-table
        :data="taskPickRows"
        size="small"
        style="width: 100%"
        row-class-name="row-clickable"
        @row-click="(row: TaskPickRow) => goTask(row.task_id)"
      >
        <el-table-column label="任务" min-width="200">
          <template #default="{ row }">
            <span class="link">{{ row.task_name }}</span>
            <div class="sub mono">#{{ row.task_id }}</div>
          </template>
        </el-table-column>
        <el-table-column label="管哪些子表" min-width="240">
          <template #default="{ row }">
            <span v-if="row.sheets.length === 1">{{ row.sheets[0] }}</span>
            <span v-else class="muted">
              合并 {{ row.sheets.length }} 张：{{ row.sheets.join('、') }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <span class="dot" :class="row.status === 'enabled' ? 'ok' : ''">
              {{ row.status === 'enabled' ? '启用' : '停用' }}
            </span>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="taskPickVisible = false">取消</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>

.type-cell {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.type-cell span {
  line-height: 1.4;
}
.head-actions {
  display: flex;
  gap: 10px;
}

.filters {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;

  width: 100%;
  padding-bottom: 12px;
}

.filter-gap {
  flex: 1;
  min-width: 12px;
}

.doc-name {
  font-weight: 600;
  cursor: pointer;
  color: var(--brand);
}

.drift {
  margin-top: 2px;
  font-size: var(--fs-label);
  color: var(--warn);
}

.todo {
  margin-left: var(--space-1);
  font-size: var(--fs-micro);
  color: var(--warn);
  background: var(--warn-weak);
  border-radius: var(--radius-sm);
  padding: 1px 6px;
  font-weight: 500;
}

.sheet-count {
  font-weight: 600;
  color: var(--text-1);
}

.sub {
  font-size: var(--fs-label);
  color: var(--text-3);
  line-height: 1.5;
}

.sep {
  margin: 0 var(--space-1);
  color: var(--text-4);
}

.sub-panel {
  padding: 8px 16px 12px 48px;
  background: var(--surface-sunken);
}

.caret {
  display: inline-block;
  width: 12px;
  color: var(--text-3);
  font-size: var(--fs-micro);
}

.col-check {
  margin-left: 8px;
}

.sched-on {
  color: var(--brand);
  font-weight: 600;
}

.col-change {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid var(--border);
}

.col-change:last-child {
  border-bottom: none;
}

.col-add {
  color: var(--ok);
}

.col-del {
  color: var(--danger);
}

.err-box {
  margin-top: 12px;
  padding: 8px 10px;
  background: var(--warn-weak);
  border-radius: var(--radius-sm);
  font-size: var(--fs-label);
  color: var(--warn);
  line-height: 1.7;
}

.sub-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  font-size: var(--fs-body);
  font-weight: 600;
  color: var(--text-1);
  margin-bottom: 8px;
}

.pad {
  padding: 12px 0;
}

.field-hint {
  margin-left: 10px;
  font-size: var(--fs-label);
  color: var(--text-3);
}

.field-hint.block {
  display: block;
  margin: 6px 0 0;
  line-height: 1.6;
}

.pick-tabs {
  margin-top: -4px;
}

.tab-badge {
  margin-left: 6px;
  font-size: var(--fs-micro);
  color: var(--brand);
  background: var(--brand-weak);
  border-radius: var(--radius-sm);
  padding: 1px 5px;
}

.search-row {
  display: flex;
  gap: 10px;
}

.hit-list {
  margin-top: 12px;
  max-height: 260px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
}

.hit {
  padding: 9px 12px;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  transition: background 0.12s ease;
}

.hit:last-child {
  border-bottom: none;
}

.hit:hover {
  background: var(--brand-weak-2);
}

.hit.taken {
  cursor: default;
  opacity: 0.6;
}

.hit.taken:hover {
  background: transparent;
}

.hit-main {
  display: flex;
  align-items: center;
  gap: 8px;
}

.hit-name {
  font-weight: 600;
  color: var(--text-1);
}

.hit-sub {
  margin-top: 2px;
  font-size: var(--fs-label);
  line-height: 1.6;
}

.more {
  padding: 6px 12px;
  text-align: center;
  background: var(--surface-sunken);
}

.empty.small {
  padding: 22px 16px;
  font-size: var(--fs-label);
}

.ref-actions {
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
  margin-top: 10px;
}

.fail-box {
  border: 1px solid var(--danger);
  background: var(--danger-weak);
  border-radius: var(--radius);
  padding: var(--space-4);

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
  line-height: 1.7;
  overflow-wrap: anywhere;
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

.fail-tips {
  margin-top: 12px;
  font-size: var(--fs-label);
  color: var(--text-2);
  line-height: 1.9;
}

.apply-box {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 12px;
}

.apply-note {
  font-size: var(--fs-label);
  color: var(--text-2);
}

.resolved-box {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: var(--space-4);
  background: var(--surface-sunken);
}

.resolved-head {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}

.sub-title {
  font-size: var(--fs-body);
  font-weight: 600;
  margin: 12px 0 8px;
}

.sub-list {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  max-height: 160px;
  overflow-y: auto;
}

.sub-chip {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 3px 9px;
  font-size: var(--fs-label);
}

.sub-chip em {
  font-style: normal;
  color: var(--text-3);
}

.batch-summary {
  display: flex;
  gap: 16px;
  margin: 4px 0 10px;
}

.row-hint {
  font-size: var(--fs-label);
  color: var(--warn);
  line-height: 1.5;
}
</style>
