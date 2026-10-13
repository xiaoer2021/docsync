<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import { toastErr, toastOk } from '@/api/client';
import { platformOf } from '@/branding';
import { getDoc, docSubItems, type DocItem, type SubItem } from '@/api/dingtalk';
import ActionFormDialog from '@/components/ActionFormDialog.vue';
import { listActions, ON_MODE_OPTIONS, type Action } from '@/api/actions';
import { COL_TYPE_OPTIONS, CRON_PRESETS, INTERVAL_NO_CLOCK_NOTE, INTERVAL_PRESETS, SCHEDULE_KIND_OPTIONS, TRANSFORM_OPTIONS, WRITE_MODE_OPTIONS, createTask, getRun, getTask, listDatasources, planTask, previewSource, runTask, updateTask, type ColumnMap, type Datasource, type PlanResult, type PreviewResult, type Run, type Task, } from '@/api/sync';
const route = useRoute();
const router = useRouter();
const taskId = computed(() => (route.params.id ? Number(route.params.id) : null));
const isEdit = computed(() => taskId.value !== null);
const step = ref(0);
const STEP_TITLES = ['读数据', '字段映射', '写入目标', '定时与通知', '测试运行'];
const viewSheetId = ref('');
const viewTabs = computed(() => {
    const main = sheet.value;
    const others = allSheets.value.filter((s) => mergeSheetIds.value.includes(s.id));
    return [
        ...(main ? [{ id: main.id, name: main.name, main: true }] : []),
        ...others.map((s) => ({ id: s.id, name: s.name, main: false })),
    ];
});
const viewingSheet = computed(() => viewTabs.value.find((t) => t.id === viewSheetId.value) || viewTabs.value[0]);
async function viewSheet(id: string) {
    if (viewSheetId.value === id)
        return;
    viewSheetId.value = id;
    await rePreview();
}
const loading = ref(false);
const booting = ref(true);
const saving = ref(false);
const planning = ref(false);
const running = ref(false);
const previewing = ref(false);
const headerLocked = ref(false);
const previewElapsed = ref(0);
let previewSeq = 0;
let previewTimer: number | undefined;
function startElapsed() {
    previewElapsed.value = 0;
    if (previewTimer)
        window.clearInterval(previewTimer);
    previewTimer = window.setInterval(() => {
        previewElapsed.value += 1;
    }, 1000);
}
function stopElapsed() {
    if (previewTimer) {
        window.clearInterval(previewTimer);
        previewTimer = undefined;
    }
}
const doc = ref<DocItem | null>(null);
const sheet = ref<SubItem | null>(null);
const allSheets = ref<SubItem[]>([]);
const mergeSheetIds = ref<string[]>([]);
const datasources = ref<Datasource[]>([]);
const preview = ref<PreviewResult | null>(null);
const docPlatformLabel = computed(() => platformOf((doc.value as {
    platform?: string;
} | null)?.platform).label);
const plan = ref<PlanResult | null>(null);
const savedTask = ref<Task | null>(null);
const picked = ref<Record<string, boolean>>({});
const rejectReasons = ref<Record<string, string>>({});
const form = reactive({
    name: '',
    orientation: 'vertical' as 'vertical' | 'horizontal' | 'matrix',
    header_row: 1,
    data_start_row: 2,
    col_start: 'A',
    col_end: 'Z',
    field_col: 'A',
    field_start_row: 0,
    field_end_row: 0,
    data_start_col: 'B',
    data_end_col: '',
    record_name_row: 0,
    matrix_header_row: 3,
    matrix_data_start_row: 4,
    matrix_field_col: 'C',
    matrix_date_start_col: 'E',
    auto_detect: true,
});
const sourceRest = ref<Record<string, unknown>>({});
function buildSourceConfig(): Record<string, unknown> {
    const dataRulesCfg = dataRules.value.map((rule) => ({
        column: rule.column,
        match: rule.match,
        action: rule.action,
        value: rule.value,
    }));
    if (form.orientation === 'horizontal') {
        return {
            ...sourceRest.value,
            skip_rows: skipRows.value,
            rules: dataRulesCfg,
            orientation: 'horizontal',
            field_col: form.field_col,
            field_start_row: form.field_start_row,
            field_end_row: form.field_end_row || 0,
            data_start_col: form.data_start_col,
            data_end_col: form.data_end_col || '',
            record_name_row: form.record_name_row || 0,
            merge_sheet_ids: mergeSheetIds.value,
        };
    }
    if (form.orientation === 'matrix') {
        return {
            ...sourceRest.value,
            skip_rows: skipRows.value,
            rules: dataRulesCfg,
            orientation: 'matrix',
            matrix_header_row: form.matrix_header_row,
            matrix_data_start_row: form.matrix_data_start_row,
            matrix_field_col: form.matrix_field_col,
            matrix_date_start_col: form.matrix_date_start_col,
            merge_sheet_ids: mergeSheetIds.value,
        };
    }
    return {
        ...sourceRest.value,
        skip_rows: skipRows.value,
        rules: dataRulesCfg,
        orientation: 'vertical',
        header_row: form.header_row,
        data_start_row: form.data_start_row,
        ...(headerSegments.value.length ? { header_rows: headerSegments.value } : {}),
        col_start: form.col_start,
        col_end: form.col_end,
        merge_sheet_ids: mergeSheetIds.value,
    };
}
function splitWords(text: string): string[] {
    return String(text || '')
        .split(/[,，、;；\s]+/)
        .map((word) => word.trim())
        .filter(Boolean);
}
function wordsToRules(words: unknown): DataRule[] {
    return splitWords(String(Array.isArray(words) ? words.join('、') : words || ''))
        .map((word) => ({ column: '', match: word, action: 'skip' as const, value: '' }));
}
const skipRows = ref<number[]>([]);
type DataRule = {
    column: string;
    match: string;
    action: 'skip' | 'replace';
    value: string;
};
const dataRules = ref<DataRule[]>([]);
function addRule() {
    dataRules.value.push({ column: '', match: '', action: 'skip', value: '' });
    onLayoutChange();
}
function removeRule(index: number) {
    dataRules.value.splice(index, 1);
    onLayoutChange();
}
const headerSegments = ref<{
    col_start: string;
    col_end: string;
    row: number;
}[]>([]);
function syncDataRow(headerKey: 'header_row' | 'matrix_header_row', dataKey: 'data_start_row' | 'matrix_data_start_row') {
    const header = Number(form[headerKey]) || 1;
    if (!form[dataKey] || Number(form[dataKey]) <= header) {
        form[dataKey] = header + 1;
    }
    onLayoutChange();
}
function addSegment() {
    const last = headerSegments.value[headerSegments.value.length - 1];
    headerSegments.value.push({
        col_start: last ? nextCol(last.col_end || last.col_start) : form.col_start,
        col_end: '',
        row: (last?.row || form.header_row) + 1,
    });
    onLayoutChange();
}
function removeSegment(index: number) {
    headerSegments.value.splice(index, 1);
    onLayoutChange();
}
function nextCol(letter: string): string {
    const text = String(letter || '').toUpperCase();
    if (!text)
        return '';
    let index = 0;
    for (const ch of text) {
        if (ch < 'A' || ch > 'Z')
            return text;
        index = index * 26 + (ord(ch) - 64);
    }
    let out = '';
    let n = index + 1;
    while (n > 0) {
        const rem = (n - 1) % 26;
        out = String.fromCharCode(65 + rem) + out;
        n = Math.floor((n - 1) / 26);
    }
    return out;
}
const skippedByWords = ref<number[]>([]);
function rowWillSkip(rowNo: number | null | undefined): boolean {
    if (rowNo === null || rowNo === undefined)
        return false;
    return skipRows.value.includes(rowNo) || skippedByWords.value.includes(rowNo);
}
function toggleSkipRow(rowNo: number | null | undefined) {
    if (rowNo === null || rowNo === undefined)
        return;
    const at = skipRows.value.indexOf(rowNo);
    if (at >= 0)
        skipRows.value.splice(at, 1);
    else
        skipRows.value.push(rowNo);
    void rePreview();
}
const willWriteCount = computed(() => {
    const total = preview.value?.rows?.length || 0;
    const numbers = preview.value?.row_numbers || [];
    return (preview.value?.rows || []).filter((_, i) => !rowWillSkip(numbers[i])).length ?? total;
});
const rowNumbers = computed(() => preview.value?.row_numbers || []);
function previewRowClass({ rowIndex }: {
    rowIndex: number;
}): string {
    return rowWillSkip(rowNumbers.value[rowIndex]) ? 'row-skipped' : '';
}
const headerNames = computed<string[]>(() => preview.value?.header || []);
const keptColumns = computed(() => (preview.value?.header || [])
    .map((name, index) => ({ name, index }))
    .filter((col) => picked.value[col.name] !== false));
let layoutTimer: ReturnType<typeof setTimeout> | null = null;
function onLayoutChange() {
    if (layoutTimer)
        clearTimeout(layoutTimer);
    layoutTimer = setTimeout(() => {
        layoutTimer = null;
        void rePreview();
    }, 400);
}
const columns = ref<ColumnMap[]>([]);
const targetRest = ref<Record<string, unknown>>({});
const target = reactive({
    datasource_id: undefined as number | undefined,
    table_name: '',
    write_mode: 'upsert',
    key_columns: [] as string[],
    quality_block_columns: [] as string[],
    numeric_note_columns: [] as string[],
    note_column: '备注',
    minimum_row_percent: 50,
    partition_column: '',
    auto_create: true,
    on_missing: 'keep',
    deleted_flag_column: '__is_deleted__',
});
const isSheet = computed(() => (doc.value?.doc_type ?? 'sheet') === 'sheet');
const isWeb = computed(() => doc.value?.doc_type === 'webpage');
const hasLayout = computed(() => isSheet.value || isWeb.value);
const targetColumns = computed(() => columns.value.map((c) => c.target).filter(Boolean));
const pickedCount = computed(() => Object.values(picked.value).filter(Boolean).length);
const scheduleCfg = reactive({
    kind: 'manual' as 'manual' | 'interval' | 'cron',
    cron_expr: '0 9 * * *',
    interval_sec: 3600,
});
const scheduleHint = computed(() => {
    if (scheduleCfg.kind === 'manual')
        return '只有你点「运行」才会跑。';
    if (scheduleCfg.kind === 'interval') {
        const hit = INTERVAL_PRESETS.find((p) => p.sec === scheduleCfg.interval_sec);
        return hit ? `${hit.hint}。` : `每 ${scheduleCfg.interval_sec} 秒跑一次。`;
    }
    return `按 cron「${scheduleCfg.cron_expr}」跑。`;
});
const availableActions = ref<Action[]>([]);
const postActions = ref<{
    action_id: number;
    on: string;
}[]>([]);
function onModeHint(on: string) {
    return ON_MODE_OPTIONS.find((o) => o.value === on)?.hint || '';
}
function postActionName(id: number) {
    return availableActions.value.find((a) => a.id === id)?.name || `（动作 ${id} 已删除）`;
}
const actionFormVisible = ref(false);
const backTarget = computed(() => {
    if (String(route.query.from || '') === 'docs') {
        return {
            path: '/docs',
            label: '返回表单管理',
            query: doc.value ? { expand: String(doc.value.id) } : {},
        };
    }
    return { path: '/tasks', label: '返回任务调度', query: {} };
});
function goBack() {
    router.push(backTarget.value);
}
function openActionForm() {
    actionFormVisible.value = true;
}
async function onActionCreated(action: Action) {
    try {
        availableActions.value = await listActions();
    }
    catch {
        availableActions.value = [action];
    }
    postActions.value.push({ action_id: action.id, on: 'not_success' });
}
function addPostAction() {
    const used = new Set(postActions.value.map((p) => p.action_id));
    const first = availableActions.value.find((a) => !used.has(a.id));
    if (!first)
        return;
    postActions.value.push({ action_id: first.id, on: 'success' });
}
const gridColumns = computed(() => {
    const origin = (preview.value?.raw_origin?.col || 'A').toUpperCase();
    let index = 0;
    for (const ch of origin)
        index = index * 26 + (ord(ch) - 64);
    const out: {
        letter: string;
        index: number;
    }[] = [];
    const width = Math.max(...(preview.value?.raw_grid || [[]]).map((r) => r.length), 0);
    for (let i = 0; i < width; i += 1) {
        let n = index + i;
        let letters = '';
        while (n > 0) {
            const rem = (n - 1) % 26;
            letters = String.fromCharCode(65 + rem) + letters;
            n = Math.floor((n - 1) / 26);
        }
        out.push({ letter: letters, index: i });
    }
    return out;
});
const gridRows = computed(() => {
    const start = preview.value?.raw_origin?.row || 1;
    return (preview.value?.raw_grid || []).map((cells, offset) => ({
        no: start + offset,
        cells,
    }));
});
function setHeaderRow(rowNo: number) {
    const next = rowNo + 1;
    if (form.orientation === 'matrix') {
        form.matrix_header_row = rowNo;
        if (form.matrix_data_start_row < next)
            form.matrix_data_start_row = next;
    }
    else {
        form.header_row = rowNo;
        if (form.data_start_row < next)
            form.data_start_row = next;
    }
    void rePreview();
}
function ord(ch: string) {
    return ch.charCodeAt(0);
}
function rowMark(rowNo: number): string {
    const markers = preview.value?.raw_markers || {};
    if (markers.header_row === rowNo)
        return '表头行';
    if (markers.data_start_row === rowNo)
        return '数据从这里开始';
    if (markers.field_row === rowNo)
        return '字段名从这里开始';
    if (markers.extent_row === rowNo)
        return '按这行判断数据范围';
    return '';
}
async function bootstrap() {
    loading.value = true;
    try {
        datasources.value = await listDatasources();
        try {
            availableActions.value = await listActions();
        }
        catch {
            availableActions.value = [];
        }
        if (isEdit.value) {
            const task = await getTask(taskId.value as number);
            savedTask.value = task;
            doc.value = await getDoc(task.doc_id);
            const subs = await docSubItems(task.doc_id);
            allSheets.value = subs;
            sheet.value = subs.find((s) => s.id === task.sheet_id) || null;
            form.name = task.name;
            const cfg = (task.source_config || {}) as Record<string, unknown>;
            sourceRest.value = { ...cfg };
            form.orientation = cfg.orientation === 'horizontal' || cfg.orientation === 'matrix' ? cfg.orientation : 'vertical';
            form.header_row = Number(cfg.header_row ?? 1);
            form.data_start_row = Number(cfg.data_start_row ?? form.header_row + 1);
            form.col_start = String(cfg.col_start ?? 'A');
            form.col_end = String(cfg.col_end ?? 'Z');
            form.field_col = String(cfg.field_col ?? 'A');
            form.field_start_row = Number(cfg.field_start_row ?? 0);
            form.field_end_row = Number(cfg.field_end_row ?? 0);
            form.data_start_col = String(cfg.data_start_col ?? 'B');
            form.data_end_col = String(cfg.data_end_col ?? '');
            form.record_name_row = Number(cfg.record_name_row ?? 0);
            form.matrix_header_row = Number(cfg.matrix_header_row ?? 3);
            form.matrix_data_start_row = Number(cfg.matrix_data_start_row ?? 4);
            form.matrix_field_col = String(cfg.matrix_field_col ?? 'C');
            form.matrix_date_start_col = String(cfg.matrix_date_start_col ?? 'E');
            mergeSheetIds.value = ((cfg.merge_sheet_ids as string[]) || []).filter((id) => id !== task.sheet_id);
            columns.value = ((task.columns as ColumnMap[]) || []).map((column) => ({
                ...column,
                type: column.type === 'int' || column.type === 'decimal' ? 'float' : column.type,
            }));
            const t = (task.target || {}) as Record<string, unknown>;
            targetRest.value = { ...t };
            target.datasource_id = t.datasource_id ? Number(t.datasource_id) : undefined;
            target.table_name = String(t.table_name || '');
            target.write_mode = String(t.write_mode || 'upsert');
            target.key_columns = (t.key_columns as string[]) || [];
            target.quality_block_columns = (t.quality_block_columns as string[]) || [];
            target.numeric_note_columns = (t.numeric_note_columns as string[]) || [];
            target.note_column = String(t.note_column || '备注');
            target.minimum_row_percent = Math.round(Number(t.minimum_row_ratio ?? 0.5) * 100);
            target.partition_column = String(t.partition_column || '');
            target.auto_create = t.auto_create !== false;
            target.on_missing = String(t.on_missing || 'keep');
            target.deleted_flag_column = String(t.deleted_flag_column || '__is_deleted__');
            skipRows.value = ((cfg.skip_rows as number[]) || []).map(Number);
            dataRules.value = [
                ...wordsToRules(cfg.skip_words),
                ...(((cfg.rules as DataRule[]) || []).map((rule) => ({
                    column: String(rule.column || ''),
                    match: String(rule.match || ''),
                    action: rule.action === 'replace' ? ('replace' as const) : ('skip' as const),
                    value: String(rule.value || ''),
                }))),
            ];
            headerSegments.value = ((cfg.header_rows as {
                col_start?: string;
                col_end?: string;
                row?: number;
            }[]) || []).map((seg) => ({
                col_start: String(seg.col_start || 'A'),
                col_end: String(seg.col_end || ''),
                row: Number(seg.row || 1),
            }));
            const sch = (task.schedule || {}) as Record<string, unknown>;
            scheduleCfg.kind = (String(sch.kind || 'manual') as 'manual' | 'interval' | 'cron') || 'manual';
            scheduleCfg.cron_expr = String(sch.cron_expr || '0 9 * * *');
            scheduleCfg.interval_sec = Number(sch.interval_sec || 3600);
            postActions.value = ((task.post_actions as {
                action_id: number;
                on: string;
            }[]) || []).map((p) => ({ action_id: Number(p.action_id), on: String(p.on || 'success') }));
        }
        else {
            const docId = Number(route.query.doc_id);
            const sheetId = String(route.query.sheet_id || '');
            if (!docId || !sheetId) {
                ElMessage.warning('从表单详情页的子表点「建任务」进来');
                router.replace('/docs');
                return;
            }
            doc.value = await getDoc(docId);
            const subs = await docSubItems(docId);
            allSheets.value = subs;
            sheet.value = subs.find((s) => s.id === sheetId) || null;
            form.name = `${doc.value.name} - ${sheet.value?.name || sheetId}`;
            if (datasources.value.length === 1)
                target.datasource_id = datasources.value[0].id;
        }
    }
    catch (err) {
        toastErr(err, '加载失败');
    }
    finally {
        loading.value = false;
        booting.value = false;
    }
    if (doc.value && sheet.value)
        void rePreview();
}
async function loadPreview(force = false) {
    if (!doc.value || !sheet.value)
        return;
    const seq = ++previewSeq;
    previewing.value = true;
    startElapsed();
    const viewing = viewSheetId.value || sheet.value.id;
    const isMain = viewing === sheet.value.id;
    try {
        const result = await previewSource({
            doc_id: doc.value.id,
            sheet_id: viewing,
            merge_sheet_ids: isMain ? mergeSheetIds.value : [],
            source_config: buildSourceConfig(),
            rows: 200,
            refresh: force,
        });
        if (seq !== previewSeq)
            return;
        preview.value = result;
        skippedByWords.value = (result as {
            skipped_row_numbers?: number[];
        }).skipped_row_numbers || [];
    }
    catch (err) {
        if (seq === previewSeq) {
            preview.value = {
                ok: false,
                header: [],
                rows: [],
                total_preview: 0,
                inferred_header_row: null,
                suggested_types: [],
                message: '',
                error: (err as {
                    message?: string;
                })?.message || `读${docPlatformLabel.value}失败了`,
            } as never;
        }
    }
    finally {
        if (seq === previewSeq) {
            previewing.value = false;
            stopElapsed();
        }
    }
    if (!preview.value?.ok)
        return;
    if (preview.value.inferred_header_row && form.auto_detect && !headerLocked.value) {
        form.header_row = preview.value.inferred_header_row;
        form.data_start_row = preview.value.inferred_header_row + 1;
    }
    headerLocked.value = true;
    const next: Record<string, boolean> = {};
    const reasons: Record<string, string> = {};
    for (const stat of preview.value.column_stats || []) {
        next[stat.name] = stat.suggestion !== 'drop';
        if (stat.is_empty_column)
            reasons[stat.name] = '样例里整列是空的';
        else if (stat.empty_ratio >= 0.9)
            reasons[stat.name] = `样例里 ${stat.empty} 行是空的`;
        else if (stat.looks_like_media)
            reasons[stat.name] = '看起来是图片/附件列，取不到文本';
    }
    if (isEdit.value && columns.value.length) {
        const savedSources = new Set(columns.value.map((c) => c.source).filter(Boolean));
        for (const name of Object.keys(next)) {
            if (savedSources.has(name))
                next[name] = true;
        }
        picked.value = next;
        rejectReasons.value = reasons;
        return;
    }
    picked.value = next;
    rejectReasons.value = reasons;
    applyAutoMapping();
}
async function rePreview(force = false) {
    try {
        await loadPreview(force);
    }
    catch (err) {
        toastErr(err, '预览失败');
    }
}
function applyAutoMapping() {
    if (!preview.value)
        return;
    const stats = preview.value.column_stats || [];
    columns.value = preview.value.header
        .map((name, index) => ({ name, index }))
        .filter(({ name }) => picked.value[name] !== false)
        .map(({ name, index }) => ({
        source: name,
        target: name,
        type: stats.find((s) => s.name === name)?.inferred_type ||
            preview.value?.suggested_types?.[index] ||
            'text',
        transform: stats.find((s) => s.name === name)?.suggested_transform ??
            preview.value?.suggested_transforms?.[index] ??
            null,
    }));
}
function toggleColumn(name: string) {
    picked.value[name] = picked.value[name] === false;
    applyAutoMapping();
}
function selectAllColumns(value: boolean) {
    for (const name of preview.value?.header || [])
        picked.value[name] = value;
    applyAutoMapping();
}
function dropSuggestedColumns() {
    for (const stat of preview.value?.column_stats || []) {
        picked.value[stat.name] = stat.suggestion !== 'drop';
    }
    applyAutoMapping();
    toastOk('已按建议调整，可用的列留下了');
}
function removeColumn(index: number) {
    columns.value.splice(index, 1);
}
function addConstantColumn() {
    columns.value.push({
        source: '',
        target: '',
        type: 'text',
        transform: null,
        required: false,
        default: '',
    } as ColumnMap);
}
function buildPayload() {
    return {
        name: form.name,
        doc_id: doc.value?.id,
        sheet_id: sheet.value?.id,
        sheet_name: sheet.value?.name,
        engine: doc.value?.doc_type,
        source_config: buildSourceConfig(),
        columns: columns.value.filter((c) => c.target),
        target: {
            ...targetRest.value,
            datasource_id: target.datasource_id,
            table_name: target.table_name,
            write_mode: target.write_mode,
            key_columns: target.key_columns,
            quality_block_columns: target.quality_block_columns,
            numeric_note_columns: target.numeric_note_columns,
            note_column: target.note_column.trim() || '备注',
            minimum_row_ratio: target.minimum_row_percent / 100,
            partition_column: target.partition_column || null,
            auto_create: target.auto_create,
            on_missing: target.on_missing,
            deleted_flag_column: target.deleted_flag_column || '__is_deleted__',
        },
        schedule: scheduleCfg.kind === 'manual'
            ? { kind: 'manual' }
            : scheduleCfg.kind === 'interval'
                ? { kind: 'interval', interval_sec: scheduleCfg.interval_sec }
                : { kind: 'cron', cron_expr: scheduleCfg.cron_expr.trim() },
        post_actions: postActions.value,
    };
}
async function save(): Promise<number | null> {
    if (!form.name.trim()) {
        ElMessage.warning('给任务起个名字');
        return null;
    }
    if (!columns.value.filter((c) => c.target).length) {
        ElMessage.warning('至少映射一列');
        return null;
    }
    if (!target.datasource_id || !target.table_name.trim()) {
        ElMessage.warning('要选目标库、填目标表名');
        return null;
    }
    if (target.write_mode === 'upsert' && !target.key_columns.length) {
        ElMessage.warning('按主键更新必须先选主键列');
        return null;
    }
    if (target.write_mode === 'full_replace') {
        try {
            await ElMessageBox.confirm(`「整表重写」会先清空 ${target.table_name} 再写入。确认请输入任务名。`, '危险操作确认', { confirmButtonText: '我已确认', cancelButtonText: '取消', type: 'warning' });
        }
        catch {
            return null;
        }
    }
    saving.value = true;
    try {
        const payload = buildPayload();
        const task = isEdit.value
            ? await updateTask(taskId.value as number, payload)
            : await createTask(payload);
        savedTask.value = task;
        toastOk('已保存');
        if (!isEdit.value)
            router.replace(`/tasks/${task.id}`);
        return task.id;
    }
    catch (err) {
        toastErr(err, '保存失败');
        return null;
    }
    finally {
        saving.value = false;
    }
}
async function doPlan() {
    const id = savedTask.value?.id ?? (await save());
    if (!id)
        return;
    planning.value = true;
    try {
        plan.value = await planTask(id);
        if (!plan.value.ok)
            ElMessage.warning(plan.value.message);
    }
    catch (err) {
        toastErr(err, '预览 DDL 失败');
    }
    finally {
        planning.value = false;
    }
}
const tested = ref(false);
const testedSnapshot = ref('');
const isTestCurrent = computed(() => tested.value && testedSnapshot.value === JSON.stringify(buildPayload()));
const testOutcome = ref<Run | null>(null);
const testStage = ref('');
const testLogs = ref<string[]>([]);
async function waitFor(runId: number, timeoutMs = 300000): Promise<Run> {
    const started = Date.now();
    for (;;) {
        const run = await getRun(runId);
        testLogs.value = run.logs || [];
        await nextTick();
        const logBox = document.getElementById('wizard-progress-log');
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
async function doRun(dryRun: boolean) {
    if (!dryRun && !isTestCurrent.value) {
        ElMessage.warning('配置已变化，请重新测试运行');
        return;
    }
    const id = dryRun ? await save() : savedTask.value?.id;
    if (!id)
        return;
    running.value = true;
    testStage.value = dryRun ? '正在测试运行…' : '正在正式同步…';
    testLogs.value = [];
    try {
        const res = await runTask(id, dryRun ? { dry_run: true } : {});
        if (!dryRun) {
            const result = await waitFor(res.run_id, 3600000);
            if (result.status === 'success')
                toastOk(`正式同步完成（#${res.run_id}）`);
            else if (result.status === 'partial')
                ElMessage.warning(`正式同步 #${res.run_id} 有异常，请查看执行记录`);
            else
                toastErr(new Error(result.error_message || '运行未成功'), `执行 #${res.run_id}`);
            return;
        }
        const run = await waitFor(res.run_id);
        testOutcome.value = run;
        if (run.status === 'success' || run.status === 'partial') {
            const safeToWrite = (run.stats?.safety as Record<string, unknown> | undefined)?.can_write !== false;
            tested.value = safeToWrite;
            testedSnapshot.value = safeToWrite ? JSON.stringify(buildPayload()) : '';
            if (!safeToWrite) {
                ElMessage.error('测试运行发现覆盖风险，正式同步已锁定；请查看下方原因');
            }
            else if (run.status === 'partial') {
                ElMessage.warning('试跑发现异常格；请查看下方数量和执行记录，确认后再正式同步');
            }
            else {
                toastOk('测试运行通过，可以正式同步了');
            }
        }
        else {
            tested.value = false;
            testedSnapshot.value = '';
            toastErr(new Error(run.error_message || '测试运行失败'), '先修好再跑');
        }
    }
    catch (err) {
        toastErr(err, '启动失败');
    }
    finally {
        running.value = false;
        testStage.value = '';
    }
}
onMounted(bootstrap);
</script>

<template>
  <div
    v-loading="booting"
    element-loading-text="正在载入任务配置…"
    class="page"
  >
    <el-dialog :model-value="!!testStage" :show-close="false" width="720px" align-center>
      <div class="running-box">
        <div class="running-title">{{ testStage }}</div>
        <div class="field-hint">测试运行会读全量数据，子表多的时候要等一会儿。</div>
        <pre v-if="testLogs.length" id="wizard-progress-log" class="progress-log">{{ testLogs.slice(-80).join('\n') }}</pre>
      </div>
    </el-dialog>
    <div class="page-head">
      <div>
        <h1 class="page-title">{{ form.name || '新建任务调度' }}</h1>
        <div class="page-sub">
          <a class="doc-link" @click="router.push(`/docs/${doc?.id}`)">{{ doc?.name }}</a>
          <el-tag size="small" effect="light">
            {{ doc?.doc_type_label || (doc?.doc_type === 'aitable' ? '多维表' : `${docPlatformLabel}表格`) }}
          </el-tag>
        </div>
      </div>
    </div>

    <el-steps :active="step" simple style="margin-bottom: 16px">
      <el-step
        v-for="(title, i) in STEP_TITLES"
        :key="title"
        class="click-step"
        :title="title"
        @click="step = i"
      />
    </el-steps>

    <div v-show="step === 0" class="card">
      <div class="card-head">
        <span class="card-title">读数据</span>
        <div class="head-actions">

          <el-button :loading="previewing" @click="rePreview(true)">重新读取</el-button>
        </div>
      </div>
      <div class="card-body">
        <el-form inline>

          <div class="form-row">
            <el-form-item label="任务名">
              <el-input v-model="form.name" style="width: 260px" />
            </el-form-item>
            <template v-if="hasLayout">
              <el-form-item v-if="!isWeb" label="表格摆法">
                <el-radio-group v-model="form.orientation" :disabled="previewing" @change="onLayoutChange">
                  <el-radio-button value="vertical">纵向（一行一条记录）</el-radio-button>
                  <el-radio-button value="horizontal">横向（一列一条记录）</el-radio-button>
                  <el-radio-button value="matrix">日期交叉表（科目 × 日期）</el-radio-button>
                </el-radio-group>
                <div class="field-hint">
                  纵向：一行一条数据。横向：一列一条数据。日期交叉表：左侧是科目，右侧按日期展开。
                </div>
              </el-form-item>
            </template>
          </div>

          <template v-if="hasLayout">
            <template v-if="form.orientation === 'vertical'">

              <el-form-item label="表头在第几行">
                <el-input-number
                  v-model="form.header_row"
                  :min="1"
                  :max="100"
                  size="small"
                  @change="syncDataRow('header_row', 'data_start_row')"
                />
              </el-form-item>
              <el-form-item label="数据从第几行">
                <el-input-number
                  v-model="form.data_start_row"
                  :min="1"
                  :max="100000"
                  size="small"
                  @change="onLayoutChange"
                />
              </el-form-item>
              <el-form-item v-if="!isWeb" label="列范围">
                <el-input
                  v-model="form.col_start"
                  size="small"
                  style="width: 60px"
                  @change="onLayoutChange"
                />
                <span class="muted" style="margin: 0 4px">到</span>
                <el-input
                  v-model="form.col_end"
                  size="small"
                  style="width: 60px"
                  @change="onLayoutChange"
                />
              </el-form-item>

              <el-form-item v-if="!isWeb" label="表头分段">
                <div class="seg-box">
                  <div v-for="(seg, i) in headerSegments" :key="i" class="seg-row">
                    <el-input v-model="seg.col_start" size="small" class="seg-col" placeholder="A" @change="onLayoutChange" />
                    <span class="muted">～</span>
                    <el-input v-model="seg.col_end" size="small" class="seg-col" placeholder="末尾" @change="onLayoutChange" />
                    <span class="muted">取第</span>
                    <el-input-number
                      v-model="seg.row"
                      :min="1"
                      :max="10000"
                      size="small"
                      controls-position="right"
                      class="seg-row-no"
                      @change="onLayoutChange"
                    />
                    <span class="muted">行</span>
                    <el-button size="small" text @click="removeSegment(i)">✕</el-button>
                  </div>
                  <div class="seg-foot">
                    <el-button size="small" type="primary" plain @click="addSegment">＋ 加一段</el-button>
                    <span class="muted">不填就是整个表头在同一行</span>
                  </div>
                </div>
              </el-form-item>

              <el-form-item label="数据规则">
                <div class="rule-box">
                  <div v-for="(rule, i) in dataRules" :key="i" class="rule-row">
                    <el-select
                      v-model="rule.column"
                      size="small"
                      class="rule-col"
                      placeholder="任意列"
                      clearable
                      @change="onLayoutChange"
                    >
                      <el-option v-for="h in headerNames" :key="h" :label="h" :value="h" />
                    </el-select>
                    <el-input
                      v-model="rule.match"
                      size="small"
                      class="rule-match"
                      placeholder="含这个内容"
                      @change="onLayoutChange"
                    />
                    <el-select
                      v-model="rule.action"
                      size="small"
                      class="rule-action"
                      @change="onLayoutChange"
                    >
                      <el-option label="跳过这一行" value="skip" />
                      <el-option label="替换成" value="replace" />
                    </el-select>
                    <el-input
                      v-if="rule.action === 'replace'"
                      v-model="rule.value"
                      size="small"
                      class="rule-value"
                      placeholder="0"
                      @change="onLayoutChange"
                    />
                    <el-button size="small" text @click="removeRule(i)">✕</el-button>
                  </div>
                  <div class="seg-foot">
                    <el-button size="small" type="primary" plain @click="addRule">＋ 加一条</el-button>
                    <span class="muted">列不选 = 任意列；匹配是包含关系（「月度总计」也能命中）</span>
                  </div>
                </div>
              </el-form-item>
            </template>

            <template v-else-if="form.orientation === 'horizontal'">
              <el-form-item label="字段名在哪一列">
                <el-input v-model="form.field_col" size="small" style="width: 70px" @change="onLayoutChange" />
                <span class="muted" style="margin: 0 8px">从第</span>
                <el-input-number v-model="form.field_start_row" :min="0" :max="10000" size="small" @change="onLayoutChange" />
                <span class="muted" style="margin: 0 8px">行开始（0 = 自动），到第</span>
                <el-input-number v-model="form.field_end_row" :min="0" :max="10000" size="small" @change="onLayoutChange" />
                <span class="muted" style="margin-left: 8px">行（0 = 自动）</span>
                <div class="field-hint">
                  「自动」会先跳过开头的空行、再往下扫到连续若干空行。第 1 行就是字段名时也能认出来。
                </div>
              </el-form-item>
              <el-form-item label="数据在哪几列">
                <el-input v-model="form.data_start_col" size="small" style="width: 60px" />
                <span class="muted" style="margin: 0 4px">到</span>
                <el-input v-model="form.data_end_col" size="small" style="width: 60px" placeholder="留空=自动" />
                <div class="field-hint">一列算一条记录。留空的话往右扫，连续若干空列就停。</div>
              </el-form-item>
              <el-form-item label="记录名在第几行">
                <el-input-number v-model="form.record_name_row" :min="0" :max="10000" size="small" />
                <div class="field-hint">
                  0 = 不用。填了的话，这一行的值会变成每条记录的名字（比如 1月 / 2月）；
                  不填就用列号（B、C、D）当名字。
                </div>
              </el-form-item>
            </template>
            <template v-else>
              <el-form-item label="日期表头在第几行">
                <el-input-number v-model="form.matrix_header_row" :min="1" :max="10000" size="small" @change="onLayoutChange" />
              </el-form-item>
              <el-form-item label="数据从第几行">
                <el-input-number v-model="form.matrix_data_start_row" :min="2" :max="100000" size="small" @change="onLayoutChange" />
              </el-form-item>
              <el-form-item label="科目列 / 日期起始列">
                <el-input v-model="form.matrix_field_col" size="small" style="width: 60px" @change="onLayoutChange" />
                <span class="muted" style="margin: 0 8px">/</span>
                <el-input v-model="form.matrix_date_start_col" size="small" style="width: 60px" @change="onLayoutChange" />
                <div class="field-hint">独立站月表可填第 3 行、从第 4 行、科目 C 列、日期 E 列。D 列月度汇总不会重复写入每日数据。</div>
              </el-form-item>
            </template>

            <el-form-item v-if="allSheets.length > 1 && !isWeb" label="合并其它子表">
              <el-select
                v-model="mergeSheetIds"
                multiple
                clearable
                size="small"
                placeholder="把同结构的其它 sheet 一起汇总到这张表"
                style="width: 100%; min-width: 320px"
                @change="rePreview"
              >
                <el-option
                  v-for="s in allSheets.filter((x) => x.id !== sheet?.id)"
                  :key="s.id"
                  :label="s.name"
                  :value="s.id"
                />
              </el-select>
              <div class="field-hint">
                表头一致的子表才能合并；平台会在读取时逐个核对，不一致会直接报出来。
                合并后每行会带上「来源工作表」以便区分。
              </div>
            </el-form-item>
          </template>
        </el-form>

        <div v-loading="previewing" element-loading-text="正在读数据…" class="preview-zone">
          <el-alert
            v-if="preview && !preview.ok"
            type="error"
            :closable="false"
            show-icon
            :title="preview.error || '读不到数据'"
            :description="preview.hint || ''"
          />
          <template v-else-if="preview">
          <div class="preview-note">{{ preview.message }}</div>

          <div v-if="viewTabs.length > 1" class="sheet-tabs">
            <button
              v-for="t in viewTabs"
              :key="t.id"
              class="sheet-tab"
              :class="{ active: viewingSheet?.id === t.id }"
              @click="viewSheet(t.id)"
            >
              {{ t.name }}
              <span v-if="t.main" class="sheet-tag">主表</span>
              <span v-else class="sheet-tag merged">合并</span>
            </button>
            <span class="sheet-hint">
              只切换预览。任务同步哪几张表由下面的「合并其它子表」决定。
            </span>
          </div>

          <div v-if="preview.raw_grid?.length" class="grid-wrap">
            <div class="grid-title">
              源表单长这样
              <span class="muted">
                （{{ preview.sheet_name || '当前子表' }}
                <template v-if="preview.merged_sheet_names?.length">
                  ；还要合并：{{ preview.merged_sheet_names.join('、') }}
                </template>
                ）A1 这种合并标题只有第一格有值，所以后面是空的。
                <b>点左侧行号可以把那一行设为表头</b> —— 标出来的那行就是现在认的。
              </span>
            </div>
            <div class="grid-scroll">
              <table class="grid">
                <thead>
                  <tr>
                    <th class="corner"></th>
                    <th v-for="c in gridColumns" :key="c.letter" class="colhead">{{ c.letter }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in gridRows" :key="row.no" :class="{ marked: rowMark(row.no) }">

                    <th
                      class="rowhead"
                      :title="`把第 ${row.no} 行设为表头行`"
                      @click="setHeaderRow(row.no)"
                    >
                      {{ row.no }}
                    </th>
                    <td v-for="c in gridColumns" :key="c.letter" :title="String(row.cells[c.index] ?? '')">
                      {{ row.cells[c.index] ?? '' }}
                    </td>
                    <td v-if="rowMark(row.no)" class="mark">{{ rowMark(row.no) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div class="col-picker">
            <div class="picker-head">
              <span>
                要用哪几列（点一下就切换）
                <b class="muted">已选 {{ pickedCount }} / {{ preview.header.length }}</b>
              </span>
              <div class="picker-actions">
                <el-button size="small" @click="dropSuggestedColumns">只留能用的</el-button>
                <el-button size="small" @click="selectAllColumns(true)">全选</el-button>
                <el-button size="small" @click="selectAllColumns(false)">全不选</el-button>
              </div>
            </div>
            <div class="picker-body">
              <label
                v-for="(h, i) in preview.header"
                :key="i"
                class="pick"
                :class="{ off: picked[h] === false }"
                @click="toggleColumn(h)"
              >
                <span class="pick-mark" :class="{ on: picked[h] !== false }">
                  {{ picked[h] !== false ? '✓' : '' }}
                </span>
                <span class="pick-main">
                  <span class="pick-name">{{ h }}</span>
                  <span class="pick-meta">
                    <em class="mono">{{ preview.suggested_types[i] || 'text' }}</em>
                    <em v-if="preview.column_stats?.[i]">
                      空 {{ preview.column_stats[i].empty }}/{{ preview.column_stats[i].total }}
                    </em>
                  </span>
                  <span v-if="rejectReasons[h]" class="pick-warn">{{ rejectReasons[h] }}</span>
                </span>
              </label>
            </div>
          </div>

          <div class="grid-title">
            落库会存成这样
            <span class="muted">
              （日期已转成日期、金额已去千分位；**只列勾选了要用的列**，
              共 {{ preview.rows.length }} 行，
              <b v-if="willWriteCount !== preview.rows.length">
                其中 {{ preview.rows.length - willWriteCount }} 行不写
              </b>
              <template v-if="preview.merged_sheet_names?.length">，已按子表合并</template>）
            </span>
          </div>
          <el-table
            :data="preview.rows.slice(0, 200)"
            size="small"
            border
            height="440"
            style="width: 100%"
            :row-class-name="previewRowClass"
          >

            <el-table-column label="行" width="72" fixed>
              <template #default="{ $index }">
                <span
                  class="row-no"
                  :class="{ skipped: rowWillSkip(rowNumbers[$index]) }"
                  @click="toggleSkipRow(rowNumbers[$index])"
                >
                  {{ rowNumbers[$index] ?? '' }}
                </span>
              </template>
            </el-table-column>
            <el-table-column
              v-if="preview.merged_sheet_names?.length"
              label="来源子表"
              width="150"
              fixed
            >
              <template #default="{ $index }">
                <span class="cell muted">{{ preview.row_sources?.[$index] || '' }}</span>
              </template>
            </el-table-column>

            <el-table-column
              v-for="col in keptColumns"
              :key="col.index"
              min-width="130"
            >
              <template #header>
                <div class="head-cell" @click="toggleColumn(col.name)">
                  <span>{{ col.name }}</span>
                  <em class="mono">{{ preview.suggested_types[col.index] || 'text' }}</em>
                </div>
              </template>
              <template #default="{ row }">
                <span class="cell">{{ row[col.index] ?? '' }}</span>
              </template>
            </el-table-column>
          </el-table>
          </template>
        </div>
      </div>
    </div>

    <div v-show="step === 1" class="card">
      <div class="card-head">
        <span class="card-title">字段映射</span>
        <el-button size="small" @click="applyAutoMapping">按表头同名映射</el-button>
        <el-button size="small" type="primary" plain @click="addConstantColumn">
          加一列（批次号 / 固定值）
        </el-button>
      </div>
      <div class="card-body">
        <el-table :data="columns" size="small" style="width: 100%">
          <el-table-column label="源列" min-width="170">
            <template #default="{ row }">
              <el-input v-model="row.source" size="small" />
            </template>
          </el-table-column>
          <el-table-column label="写入哪一列" min-width="170">
            <template #default="{ row }">
              <el-input v-model="row.target" size="small" />
            </template>
          </el-table-column>
          <el-table-column label="类型" width="130">
            <template #default="{ row }">
              <el-select v-model="row.type" size="small">
                <el-option v-for="o in COL_TYPE_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="值转换" width="180">
            <template #default="{ row }">
              <el-select v-model="row.transform" size="small">
                <el-option v-for="o in TRANSFORM_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="空值填" width="120">
            <template #header>
              <span>
                空值填
                <el-tooltip
                  content="源里这一格是空的时，写什么进去。金额列填 0 最常用；留空就写 NULL。"
                  placement="top"
                >
                  <span class="muted">?</span>
                </el-tooltip>
              </span>
            </template>
            <template #default="{ row }">
              <el-input
                v-model="row.default"
                size="small"
                :placeholder="row.type === 'text' ? '留空为 NULL' : '如 0'"
              />
            </template>
          </el-table-column>

          <el-table-column label="必填" width="86">
            <template #default="{ row }">
              <el-checkbox v-model="row.required">必填</el-checkbox>
            </template>
          </el-table-column>
          <el-table-column label="" width="60">
            <template #default="{ $index }">
              <el-button link type="danger" size="small" @click="removeColumn($index)">移除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <div v-show="step === 2" class="card">
      <div class="card-head">
        <span class="card-title">写入目标</span>
      </div>
      <div class="card-body">
        <el-form label-width="110px">
          <el-form-item label="目标库" required>
            <el-select v-model="target.datasource_id" placeholder="选一个目标库" style="width: 100%">
              <el-option v-for="d in datasources" :key="d.id" :label="`${d.name}（${d.db_type_label}）`" :value="d.id" />
            </el-select>
            <div v-if="!datasources.length" class="field-hint">
              还没有目标库，先去「目标库」页加一个。
            </div>
          </el-form-item>
          <el-form-item label="目标表名" required>
            <el-input v-model="target.table_name" placeholder="例如 经营分析_Coupang_平台货品" />
            <div class="field-hint">表不存在会自动建；已存在只会补缺失的列，不会删列改类型。</div>
          </el-form-item>
          <el-form-item label="写入策略" required>
            <el-radio-group v-model="target.write_mode">
              <el-radio v-for="o in WRITE_MODE_OPTIONS" :key="o.value" :value="o.value">
                {{ o.label }}
              </el-radio>
            </el-radio-group>
            <div class="field-hint">
              {{ WRITE_MODE_OPTIONS.find((o) => o.value === target.write_mode)?.hint }}
            </div>
          </el-form-item>
          <el-form-item v-if="target.write_mode === 'upsert'" label="主键列" required>
            <el-select v-model="target.key_columns" multiple placeholder="用哪几列判断是不是同一行" style="width: 100%">
              <el-option v-for="c in targetColumns" :key="c" :label="c" :value="c" />
            </el-select>
            <div class="field-hint">
              平台会自动加一列「来源行号」和「数据指纹」，指纹没变就跳过更新。
              如果你想按来源行定位，把「来源行号」也选进主键。
            </div>
          </el-form-item>
          <el-form-item label="关键数据列">
            <el-select v-model="target.quality_block_columns" multiple clearable placeholder="选中后，异常值会阻止写库" style="width: 100%">
              <el-option v-for="c in targetColumns" :key="c" :label="c" :value="c" />
            </el-select>
            <div class="field-hint">金额、日期等不能留空的业务列可在这里选择。主键列和勾选“必填”的列会自动拦截异常；其他列保留原文并标记“部分成功”。</div>
          </el-form-item>
          <el-form-item label="金额说明列">
            <el-select v-model="target.numeric_note_columns" multiple clearable placeholder="选择允许将文字转入备注的数值列" style="width: 100%">
              <el-option v-for="c in columns.filter((item) => item.type === 'float' && item.target)" :key="c.target" :label="c.target" :value="c.target" />
            </el-select>
            <div class="field-hint">所选列遇到非数字内容时写 0，原文写入备注；其余数值列仍按异常格处理。</div>
          </el-form-item>
          <el-form-item v-if="target.numeric_note_columns.length" label="备注列名">
            <el-input v-model="target.note_column" placeholder="备注" />
          </el-form-item>
          <el-form-item v-if="target.write_mode === 'full_replace'" label="行数保护">
            <el-input-number v-model="target.minimum_row_percent" :min="0" :max="100" :step="10" />
            <span class="field-hint">%：本次行数低于旧表的该比例时停止覆盖；0 表示关闭此项保护。</span>
          </el-form-item>
          <el-form-item v-if="target.write_mode === 'replace_partition'" label="分区列" required>
            <el-select v-model="target.partition_column" placeholder="按哪一列分区" style="width: 100%">
              <el-option v-for="c in targetColumns" :key="c" :label="c" :value="c" />
            </el-select>
          </el-form-item>

          <el-form-item v-if="target.write_mode === 'upsert'" label="源里没有的行">
            <el-radio-group v-model="target.on_missing">
              <el-radio value="keep">不动</el-radio>
              <el-radio value="delete">从目标表删掉</el-radio>
              <el-radio value="mark">标记为已删除</el-radio>
            </el-radio-group>
            <div class="field-hint">
              源表里删掉的行，目标表里还留着的话，BI 上的数据只增不减。
              选「删掉」或「标记」，每次同步完会拿本次读到的跟目标表比一遍，
              把没读到的清掉。<b>只影响本任务写进去的行</b>（按「来源工作表」圈定），
              别的任务/别的子表的数据不会碰。
            </div>
            <el-input
              v-if="target.on_missing === 'mark'"
              v-model="target.deleted_flag_column"
              size="small"
              style="margin-top: 8px; max-width: 240px"
              placeholder="标记列名，默认 __is_deleted__"
            />
          </el-form-item>
        </el-form>

        <div class="plan-actions">
          <el-button :loading="planning" @click="doPlan">预览要执行的 DDL</el-button>
        </div>

        <div v-if="plan" class="plan">
          <div class="plan-head">
            <span class="dot" :class="plan.ok ? 'ok' : 'fail'">{{ plan.ok ? '结构检查完成' : '检查失败' }}</span>
            <span class="muted">{{ plan.message }}</span>
          </div>
          <div class="plan-detail">
            <div>目标：<span class="mono">{{ plan.datasource }}</span></div>
            <div>表：<span class="mono">{{ plan.table }}</span></div>
            <div v-if="plan.existing_columns.length">
              已有 {{ plan.existing_columns.length }} 列
            </div>
          </div>
          <pre v-if="plan.statements.length" class="ddl">{{ plan.statements.join('\n') }}</pre>
          <div v-else-if="plan.ok" class="muted">表结构已就绪，不需要变更。</div>
        </div>
      </div>
    </div>

    <div v-show="step === 3">
      <div class="card">
        <div class="card-head">
          <span class="card-title">定时调度</span>
          <span class="muted">不配就只有你点「运行」才会跑</span>
        </div>
        <div class="card-body">
          <el-form label-width="110px">
            <el-form-item label="怎么跑">
              <el-radio-group v-model="scheduleCfg.kind">
                <el-radio-button
                  v-for="o in SCHEDULE_KIND_OPTIONS"
                  :key="o.value"
                  :value="o.value"
                >
                  {{ o.label }}
                </el-radio-button>
              </el-radio-group>
              <div class="field-hint">
                {{ SCHEDULE_KIND_OPTIONS.find((o) => o.value === scheduleCfg.kind)?.hint }}
              </div>
            </el-form-item>

            <el-form-item v-if="scheduleCfg.kind === 'interval'" label="多久一次">
              <el-select v-model="scheduleCfg.interval_sec" size="small" style="width: 220px">
                <el-option v-for="p in INTERVAL_PRESETS" :key="p.sec" :label="p.label" :value="p.sec" />
              </el-select>
              <div class="field-hint">{{ INTERVAL_NO_CLOCK_NOTE }}</div>
            </el-form-item>

            <el-form-item v-if="scheduleCfg.kind === 'cron'" label="cron 表达式">
              <el-input
                v-model="scheduleCfg.cron_expr"
                size="small"
                style="width: 220px"
                placeholder="0 9 * * *"
              />
              <div class="presets">
                <el-tag
                  v-for="p in CRON_PRESETS"
                  :key="p.expr"
                  size="small"
                  class="clickable"
                  @click="scheduleCfg.cron_expr = p.expr"
                >
                  {{ p.label }}（{{ p.expr }}）
                </el-tag>
              </div>
            </el-form-item>

            <el-form-item label="效果">
              <span class="preview-line">{{ scheduleHint }}</span>
            </el-form-item>
          </el-form>
          <div class="field-hint">
            保存后「下次运行时间」会立刻算出来，在任务详情页能看到。定时跑出来的执行，
            触发方式会标成「定时」，跟手动跑区分得开。
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-head">
          <span class="card-title">后置动作</span>

          <el-button size="small" type="primary" plain @click="openActionForm">新建动作</el-button>
          <el-button size="small" @click="addPostAction">从已有里选</el-button>
        </div>
        <div class="card-body">
          <div v-if="!postActions.length" class="muted-only">
            还没配。同步完自动刷观远数据集、或者往钉钉群发条消息，都在这里配 ——
            也可以先跳过，以后再来加。
          </div>
          <div v-else>
            <div v-for="(item, i) in postActions" :key="i" class="post-row">
              <el-select v-model="item.action_id" size="small" style="width: 260px">
                <el-option v-for="a in availableActions" :key="a.id" :label="a.name" :value="a.id" />
              </el-select>
              <div class="post-on">
                <el-select v-model="item.on" size="small" style="width: 150px">
                  <el-option v-for="o in ON_MODE_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
                </el-select>
                <div class="field-hint">{{ onModeHint(item.on) }}</div>
              </div>
              <span class="muted post-desc">{{ postActionName(item.action_id) }}</span>
              <el-button link type="danger" size="small" @click="postActions.splice(i, 1)">移除</el-button>
            </div>
          </div>
          <div v-if="!availableActions.length" class="field-hint">
            还没有可用的后置动作，先去「后置动作」页建一个（比如钉钉机器人）。
          </div>
          <div v-else class="field-hint">
            这一块跟上面的定时**互不影响**：定时决定「什么时候跑」，
            后置动作决定「跑完之后通知谁」。动作失败不会把这次同步标成失败。
          </div>
        </div>
      </div>
    </div>

    <ActionFormDialog v-model="actionFormVisible" @saved="onActionCreated" />

    <div v-show="step === 4" class="card">
      <div class="card-head">
        <span class="card-title">测试运行</span>
        <span class="muted">先测，通过了再正式跑</span>
      </div>
      <div class="card-body">
        <p class="run-tip">
          <b>测试运行</b>：把源数据完整读一遍、跟目标表按主键比一遍，告诉你
          <b>会新增多少、更新多少、源里已经删了多少</b> —— 但一个字都不写。
          确认没问题再点「正式同步」。这一步不该跳过：列选错、表头猜错这类问题，
          写进库之后才发现，回滚的代价比这儿等几十秒高得多。
        </p>
        <div class="run-actions">
          <el-button :loading="running" @click="doRun(true)">测试运行（不写库）</el-button>
          <el-button type="primary" :loading="running" :disabled="!isTestCurrent" @click="doRun(false)">
            正式同步
          </el-button>
        </div>
        <div v-if="testOutcome" class="test-outcome">
          <el-descriptions :column="3" border size="small">
            <el-descriptions-item label="读到">{{ testOutcome.rows_read }} 行</el-descriptions-item>
            <el-descriptions-item label="跳过行">{{ testOutcome.rows_failed }} 行</el-descriptions-item>
            <el-descriptions-item label="异常格">{{ Number((testOutcome.stats?.quality as Record<string, unknown> | undefined)?.invalid_cells || 0) }} 个</el-descriptions-item>
            <el-descriptions-item label="关键列异常">{{ Number((testOutcome.stats?.quality as Record<string, unknown> | undefined)?.critical_cells || 0) }} 个</el-descriptions-item>
            <el-descriptions-item label="耗时">
              {{ testOutcome.duration_ms ? `${(testOutcome.duration_ms / 1000).toFixed(1)} s` : '—' }}
            </el-descriptions-item>
          </el-descriptions>
          <el-alert
            v-if="((testOutcome.stats?.safety as Record<string, unknown> | undefined)?.blockers as string[] | undefined)?.length"
            :title="'正式写入会被拦截：' + (((testOutcome.stats?.safety as Record<string, unknown>)?.blockers as string[]).join('；'))"
            type="warning"
            :closable="false"
            show-icon
          />
        </div>
        <div v-if="!tested && savedTask" class="field-hint">
          先跑一次测试运行，没问题了「正式同步」才会亮起来。
        </div>
      </div>
    </div>

    <div class="footer-actions">
      <el-button v-if="step > 0" @click="step -= 1">上一步</el-button>
      <el-button v-if="step < STEP_TITLES.length - 1" type="primary" @click="step += 1">
        下一步
      </el-button>
      <el-button :loading="saving" @click="save">保存</el-button>
      <el-button @click="goBack">{{ backTarget.label }}</el-button>
    </div>
  </div>
</template>

<style scoped>

.form-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  width: 100%;
}

:deep(.el-form--inline .el-form-item) {
  align-items: center;
  margin-right: 18px;
}

.rule-box {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.rule-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.rule-col {
  width: 136px;
}

.rule-match {
  width: 150px;
}

.rule-action {
  width: 124px;
}

.rule-value {
  width: 90px;
}

.seg-box {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.seg-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.seg-col {
  width: 56px;
}

.seg-row-no {
  width: 92px;
}

.seg-foot {
  display: flex;
  align-items: center;
  gap: 8px;
}

.grid .rowhead {
  cursor: pointer;
}

.grid .rowhead:hover {
  background: #ecf5ff;
  color: #409eff;
}

.row-skipped {
  opacity: 0.45;
  text-decoration: line-through;
}

.row-no {
  cursor: pointer;
  user-select: none;
}

.row-no.skipped {
  color: #c45656;
  text-decoration: line-through;
}

.sheet-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  padding: 8px 10px;
  background: var(--surface-sunken);
  border-radius: var(--radius-sm);
  margin-bottom: 12px;
}

.sheet-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border: 1px solid var(--border);
  border-bottom: none;
  border-radius: var(--radius-sm) var(--radius-sm) 0 0;
  background: var(--surface);
  color: var(--text-2);
  font-size: var(--fs-body);
  cursor: pointer;
  transition: all 0.12s ease;
}

.sheet-tab:hover {
  color: var(--brand);
}

.sheet-tab.active {
  background: var(--brand-weak);
  color: var(--brand);
  font-weight: 600;
  border-color: var(--brand);
}

.sheet-tag {
  font-size: 10px;
  padding: 0 5px;
  border-radius: 999px;
  background: var(--brand);
  color: #fff;
  line-height: 15px;
}

.sheet-tag.merged {
  background: var(--text-3);
}

.sheet-hint {
  margin-left: auto;
  font-size: var(--fs-label);
  color: var(--text-3);
}

.running-box {
  text-align: center;
  padding: 6px 0;
}

.running-title {
  font-size: 14px;
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
  max-height: 300px;
  overflow: auto;
}

.test-outcome {
  margin-top: 12px;
}

.click-step {
  cursor: pointer;
}

.doc-link {
  cursor: pointer;
  color: var(--brand);
}

.field-hint {
  font-size: var(--fs-label);
  color: var(--text-3);
  line-height: 1.6;
  margin-top: 4px;
}

.preview-line {
  font-size: var(--fs-body);
  color: var(--text-1);
}

.presets {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}

.clickable {
  cursor: pointer;
}

.post-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid var(--border);
}

.post-on {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.post-on .field-hint {
  margin: 0;
}

.post-row:last-child {
  border-bottom: none;
}

.post-desc {
  flex: 1;
  font-size: var(--fs-label);
}

.muted-only {
  color: var(--text-3);
  font-size: var(--fs-body);
}

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

.preview-note {
  font-size: var(--fs-label);
  color: var(--text-3);
  margin-bottom: 10px;
}

.grid-wrap {
  margin-bottom: 14px;
}

.grid-title {
  font-size: var(--fs-body);
  font-weight: 600;
  margin-bottom: 6px;
}

.grid-scroll {
  max-height: 260px;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
}

.grid {
  border-collapse: collapse;
  font-size: var(--fs-label);
  white-space: nowrap;
}

.grid th,
.grid td {
  border: 1px solid var(--border);
  padding: 3px 8px;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.grid thead th {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--surface-sunken);
  color: var(--text-3);
  font-weight: 600;
  text-align: center;
  min-width: 60px;
}

.grid .corner,
.grid .rowhead {
  position: sticky;
  left: 0;
  z-index: 1;
  background: var(--surface-sunken);
  color: var(--text-3);
  font-weight: 600;
  text-align: center;
  min-width: 38px;
}

.grid thead .corner {
  z-index: 3;
}

.grid tr.marked td,
.grid tr.marked .rowhead {
  background: var(--brand-weak);
}

.grid .mark {
  color: var(--brand);
  font-size: var(--fs-micro);
  white-space: nowrap;
  background: var(--brand-weak);
}

.pick-mark {
  width: 15px;
  height: 15px;
  flex: none;
  border: 1px solid var(--border-strong);
  border-radius: 3px;
  font-size: var(--fs-micro);
  line-height: 13px;
  text-align: center;
  color: #fff;
  margin-top: 1px;
}

.pick-mark.on {
  background: var(--brand);
  border-color: var(--brand);
}

.head-cell {
  cursor: pointer;
  line-height: 1.4;
}

.head-cell em {
  display: block;
  font-style: normal;
  font-size: var(--fs-micro);
  color: var(--brand);
  font-weight: 400;
}

.head-cell:hover span {
  color: var(--brand);
}

.col-picker {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-sunken);
  margin-bottom: 12px;
}

.picker-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  font-size: var(--fs-body);
}

.picker-actions {
  display: flex;
  gap: 8px;
}

.picker-body {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  padding: var(--space-4);
  max-height: 190px;
  overflow-y: auto;
}

.pick {
  display: flex;
  align-items: flex-start;
  gap: 4px;
  width: 210px;
  cursor: pointer;
  padding: 3px 0;
}

.pick.off {
  opacity: 0.5;
}

.pick-main {
  min-width: 0;
  line-height: 1.4;
}

.pick-name {
  display: block;
  font-size: var(--fs-label);
  font-weight: 600;
  word-break: break-all;
}

.pick-meta {
  display: flex;
  gap: 8px;
  font-size: var(--fs-micro);
  color: var(--text-3);
}

.pick-meta em {
  font-style: normal;
}

.pick-warn {
  display: block;
  font-size: var(--fs-micro);
  color: var(--warn);
}

.col-off {
  opacity: 0.4;
}

.head-off {
  text-decoration: line-through;
  color: var(--text-3);
}

.col-type {
  font-size: var(--fs-micro);
  color: var(--brand);
  font-weight: 400;
}

.cell {
  display: inline-block;
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.field-hint {
  font-size: var(--fs-label);
  color: var(--text-3);
  line-height: 1.6;
}

.plan-actions {
  margin-top: 6px;
}

.plan {
  margin-top: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: var(--space-4);
  background: var(--surface-sunken);
}

.plan-head {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 8px;
}

.plan-detail {
  font-size: var(--fs-label);
  color: var(--text-2);
  line-height: 1.8;
}

.ddl {
  margin: 10px 0 0;
  padding: 10px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: var(--fs-label);
  line-height: 1.7;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

.run-tip {
  color: var(--text-2);
  line-height: 1.9;
  margin: 0 0 14px;
}

.run-actions {
  display: flex;
  gap: 12px;
}

.footer-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
