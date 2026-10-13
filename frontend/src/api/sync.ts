
import { call } from './client';
export interface Datasource {
    id: number;
    name: string;
    db_type: string;
    db_type_label: string;
    host: string;
    port: number;
    database: string;
    username: string;
    password_masked: string;
    extra: Record<string, unknown> | null;
    is_default: boolean;
    enabled: boolean;
    remark: string | null;
    task_count: number;
}
export interface TestResult {
    ok: boolean;
    message: string;
    hint: string | null;
    version: string | null;
    latency_ms: number | null;
}
export interface TableInfo {
    name: string;
    columns: string[];
    column_types: Record<string, string>;
    row_count: number | null;
}
export const listDatasources = () => call<Datasource[]>({ url: '/datasources' });
export function createDatasource(data: Record<string, unknown>) {
    return call<Datasource>({ url: '/datasources', method: 'POST', data });
}
export function updateDatasource(id: number, data: Record<string, unknown>) {
    return call<Datasource>({ url: `/datasources/${id}`, method: 'PATCH', data });
}
export const deleteDatasource = (id: number) => call({ url: `/datasources/${id}`, method: 'DELETE' });
export const testDatasource = (id: number) => call<TestResult>({ url: `/datasources/${id}/test`, method: 'POST' });
export function testDatasourceDraft(data: Record<string, unknown>) {
    return call<TestResult>({ url: '/datasources/test', method: 'POST', data });
}
export function listTables(id: number, keyword?: string) {
    return call<string[]>({ url: `/datasources/${id}/tables`, params: { keyword } });
}
export function inspectTable(id: number, name: string) {
    return call<TableInfo>({ url: `/datasources/${id}/table`, params: { name } });
}
export interface TableRows {
    columns: string[];
    rows: (string | null)[][];
    total: number;
}
export function tableRows(id: number, name: string, params: {
    limit?: number;
    offset?: number;
    order_by?: string;
    desc?: boolean;
    filter_column?: string;
    filter_value?: string;
} = {}) {
    return call<TableRows>({
        url: `/datasources/${id}/table/rows`,
        params: { name, ...params },
    });
}
export interface ColumnMap {
    source: string;
    target: string;
    type: string;
    transform?: string | null;
    required?: boolean;
    default?: unknown;
    length?: number | null;
}
export interface Task {
    id: number;
    code: string;
    name: string;
    doc_id: number;
    doc_name: string | null;
    doc_type: string | null;
    sheet_id: string;
    sheet_name: string | null;
    engine: string;
    group_name: string | null;
    source_config: Record<string, unknown> | null;
    columns: ColumnMap[] | null;
    target: Record<string, unknown> | null;
    post_actions?: {
        action_id: number;
        on: string;
    }[] | null;
    dedupe?: Record<string, unknown> | null;
    target_table: string;
    write_mode: string;
    datasource_name: string | null;
    schedule: Record<string, unknown> | null;
    schedule_label?: string;
    merge_sheet_names?: string[];
    status: string;
    remark: string | null;
    last_run_at: string | null;
    last_run_status: string | null;
    last_success_at: string | null;
    next_run_at: string | null;
    last_summary: Record<string, unknown> | null;
    running: boolean;
}
export interface PlanResult {
    ok: boolean;
    table: string;
    datasource: string;
    will_create: boolean;
    will_add_columns: {
        name: string;
        type: string;
    }[];
    existing_columns: string[];
    statements: string[];
    mapped_columns: {
        source: string;
        target: string;
        type: string;
    }[];
    message: string;
}
export interface CheckResult {
    ok: boolean;
    steps: {
        name: string;
        ok: boolean;
        message: string;
        hint: string | null;
    }[];
}
export interface ColumnStat {
    name: string;
    total: number;
    non_empty: number;
    empty: number;
    empty_ratio: number;
    inferred_type: string;
    suggested_transform: string | null;
    looks_like_media: boolean;
    is_empty_column: boolean;
    suggestion: 'keep' | 'drop';
}
export interface SuggestedLayout {
    orientation: 'vertical' | 'matrix';
    header_row: number;
    data_start_row: number;
    field_col: string;
    date_start_col: string;
    axis_kind: string;
    axis_count: number;
    confidence: 'high' | 'medium' | 'low';
    reasons: string[];
}
export interface PreviewResult {
    ok: boolean;
    header: string[];
    rows: unknown[][];
    suggested?: SuggestedLayout;
    row_numbers?: number[];
    skipped_row_numbers?: number[];
    raw_rows?: unknown[][];
    total_preview: number;
    inferred_header_row: number | null;
    data_start_row?: number;
    suggested_types: string[];
    suggested_transforms?: (string | null)[];
    column_stats?: ColumnStat[];
    raw_grid?: unknown[][];
    raw_origin?: {
        row: number;
        col: string;
    };
    raw_markers?: Record<string, number | string | null>;
    row_sources?: string[];
    sheet_id?: string;
    sheet_name?: string;
    merged_sheet_names?: string[];
    orientation?: string;
    message: string;
    error?: string;
    hint?: string;
}
export const listTasks = (params: {
    doc_id?: number;
    keyword?: string;
} = {}) => call<Task[]>({ url: '/tasks', params });
export const getTask = (id: number) => call<Task>({ url: `/tasks/${id}` });
export const createTask = (data: Record<string, unknown>) => call<Task>({ url: '/tasks', method: 'POST', data });
export const quickCreateTask = (data: Record<string, unknown>) => call<Task>({ url: '/tasks/quick', method: 'POST', data });
export const updateTask = (id: number, data: Record<string, unknown>) => call<Task>({ url: `/tasks/${id}`, method: 'PATCH', data });
export const deleteTask = (id: number) => call({ url: `/tasks/${id}`, method: 'DELETE' });
export const cloneTask = (id: number, data: Record<string, unknown>) => call<Task>({ url: `/tasks/${id}/clone`, method: 'POST', data });
export const runTask = (id: number, params: {
    dry_run?: boolean;
    limit?: number;
} = {}) => call<{
    run_id: number;
    trigger: string;
    dry_run: boolean;
}>({
    url: `/tasks/${id}/run`,
    method: 'POST',
    params,
});
export const planTask = (id: number) => call<PlanResult>({ url: `/tasks/${id}/plan`, method: 'POST' });
export const checkTask = (id: number) => call<CheckResult>({ url: `/tasks/${id}/check`, method: 'POST' });
export const previewSource = (data: Record<string, unknown>) => call<PreviewResult>({ url: '/tasks/preview', method: 'POST', data, timeout: 40000 });
export interface Run {
    id: number;
    task_id: number;
    task_name: string | null;
    trigger_type: string;
    trigger_label: string;
    status: string;
    status_label: string;
    queued_at: string | null;
    started_at: string | null;
    finished_at: string | null;
    duration_ms: number | null;
    rows_read: number;
    rows_written: number;
    rows_inserted: number;
    rows_updated: number;
    rows_unchanged: number;
    rows_failed: number;
    batches: number;
    dry_run: boolean;
    row_limit: number | null;
    error_type: string | null;
    error_message: string | null;
    stats: Record<string, unknown> | null;
}
export interface RunDetail extends Run {
    logs: string[];
    issues: {
        row_no: number | null;
        column: string | null;
        reason: string;
        raw: unknown;
    }[];
}
export interface RunPage {
    total: number;
    offset: number;
    limit: number;
    items: Run[];
}
export const listRuns = (params: {
    task_id?: number;
    status?: string;
    offset?: number;
    limit?: number;
} = {}) => call<RunPage>({ url: '/runs', params });
export const getRun = (id: number) => call<RunDetail>({ url: `/runs/${id}` });
export const cancelRun = (id: number) => call({ url: `/runs/${id}/cancel`, method: 'POST' });
export const PAGE_SIZES = [10, 20, 30, 50, 100];
export function writeModeLabel(mode: string | undefined): string {
    return WRITE_MODE_OPTIONS.find((o) => o.value === mode)?.label || mode || '—';
}
export function writeModeNote(mode: string | undefined): string {
    return WRITE_MODE_OPTIONS.find((o) => o.value === mode)?.hint || '';
}
export const runLogStreamUrl = (id: number) => `/api/v1/runs/${id}/log/stream`;
export const WRITE_MODE_OPTIONS = [
    { value: 'upsert', label: '按主键更新', hint: '存在就更新，不存在就插入。最常用，也最安全。' },
    { value: 'append', label: '只追加', hint: '每次都新增，不判断重复。适合流水日志。' },
    { value: 'replace_partition', label: '按分区覆盖', hint: '先删掉目标表里这个分区的老数据，再写新的。' },
    { value: 'full_replace', label: '整表重写', hint: '清空整张表再写。危险，需要复述任务名确认。' },
];
export const COL_TYPE_OPTIONS = [
    { value: 'text', label: '文本' },
    { value: 'float', label: '数值（double）' },
    { value: 'date', label: '日期' },
    { value: 'datetime', label: '日期时间' },
    { value: 'bool', label: '是否' },
    { value: 'json', label: 'JSON' },
];
export const TRANSFORM_OPTIONS = [
    { value: '', label: '不转换' },
    { value: 'trim', label: '去空格' },
    { value: 'number', label: '去千分位/货币符号' },
    { value: 'strip_unit', label: '去掉单位留数字（5 个 → 5）' },
    { value: 'date', label: '按日期解析' },
    { value: 'percent', label: '百分比转小数' },
    { value: 'bool', label: '是/否转真假' },
    { value: 'fullwidth_to_half', label: '全角转半角' },
];
export interface ScheduleConfig {
    kind: 'manual' | 'interval' | 'cron';
    cron_expr?: string;
    interval_sec?: number;
}
export const SCHEDULE_KIND_OPTIONS = [
    { value: 'manual', label: '手动', hint: '只有你点「运行」才会跑。' },
    {
        value: 'interval',
        label: '按间隔',
        hint: '每隔一段时间跑一次（最短 60 秒）。适合「每天几次」这种简单节奏。',
    },
    {
        value: 'cron',
        label: '按 cron',
        hint: '5 段：分 时 日 月 周。例：0 9 * * * 是每天 9 点；0 */2 * * * 是每 2 小时。',
    },
];
export const CRON_PRESETS = [
    { expr: '0 9 * * *', label: '每天 9:00' },
    { expr: '0 2 * * *', label: '每天 2:00' },
    { expr: '0 */2 * * *', label: '每 2 小时' },
    { expr: '0 9 * * 1', label: '每周一 9:00' },
    { expr: '0 6 1 * *', label: '每月 1 号 6:00' },
];
export const INTERVAL_PRESETS = [
    { sec: 600, label: '每 10 分钟', hint: '每隔 10 分钟跑一次' },
    { sec: 1800, label: '每 30 分钟', hint: '每隔 30 分钟跑一次' },
    { sec: 3600, label: '每 1 小时', hint: '每隔 1 小时跑一次' },
    { sec: 21600, label: '每 6 小时', hint: '每隔 6 小时跑一次' },
    { sec: 86400, label: '每天', hint: '每隔 24 小时跑一次' },
];
export const INTERVAL_NO_CLOCK_NOTE = '这里不指定几点：从「上次跑完」那一刻算起，隔这么久跑下一次。' +
    '想固定在每天某个时间点（比如每天 9:00），请改用「按 cron」。';
