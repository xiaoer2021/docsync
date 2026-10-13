
import { call } from './client';
export interface WpsAccount {
    i: number;
    checked: boolean;
    name: string;
    avatar: string;
}
export interface WpsLoginState {
    status: 'waiting' | 'ok' | 'expired';
    image?: string;
    view?: {
        w: number;
        h: number;
        x?: number;
        y?: number;
    };
    mode?: 'qr' | 'mobile' | 'exclusive' | 'pick' | 'unknown';
    qr?: string;
    accounts?: WpsAccount[];
    buttons?: {
        i: number;
        text: string;
    }[];
    title?: string;
    texts?: string[];
    fields?: {
        phone?: string;
        code?: string;
        name?: string;
    };
    source?: 'default' | 'recipe' | 'mixed';
}
export const startWpsLogin = (appId: number) => call<WpsLoginState>({ url: `/apps/${appId}/wps-login`, method: 'post' });
export const pollWpsLogin = (appId: number) => call<WpsLoginState>({ url: `/apps/${appId}/wps-login` });
export const clickWpsLogin = (appId: number, x: number, y: number) => call<WpsLoginState>({ url: `/apps/${appId}/wps-login/click`, method: 'post', data: { x, y } });
export const typeWpsLogin = (appId: number, text: string) => call<WpsLoginState>({ url: `/apps/${appId}/wps-login/type`, method: 'post', data: { text } });
export const keyWpsLogin = (appId: number, key: string) => call<WpsLoginState>({ url: `/apps/${appId}/wps-login/key`, method: 'post', data: { key } });
export const wpsLoginMode = (appId: number, mode: string) => call<WpsLoginState>({ url: `/apps/${appId}/wps-login/mode`, method: 'post', data: { mode } });
export const wpsLoginFill = (appId: number, field: string, text: string) => call<WpsLoginState>({ url: `/apps/${appId}/wps-login/fill`, method: 'post', data: { field, text } });
export const wpsLoginTap = (appId: number, action: string) => call<WpsLoginState>({ url: `/apps/${appId}/wps-login/tap`, method: 'post', data: { action } });
export const wpsLoginAccounts = (appId: number, indexes: number[], submit?: number) => call<WpsLoginState>({
    url: `/apps/${appId}/wps-login/accounts`,
    method: 'post',
    data: { indexes, submit },
});
export const wpsLoginButton = (appId: number, index: number) => call<WpsLoginState>({
    url: `/apps/${appId}/wps-login/button`,
    method: 'post',
    data: { index },
});
export const cancelWpsLogin = (appId: number) => call<{
    status: string;
}>({ url: `/apps/${appId}/wps-login`, method: 'delete' });
export interface AppRecipe {
    elements?: Record<string, string>;
    steps?: Record<string, unknown>[];
    access?: 'public' | 'private';
}
export interface DingApp {
    id: number;
    platform: string;
    name: string;
    app_key: string;
    app_key_masked?: string;
    app_secret_masked: string;
    has_secret: boolean;
    default_operator_union_id: string | null;
    default_operator_name: string | null;
    token_expires_at: string | null;
    last_token_at: string | null;
    last_token_error: string | null;
    recipe?: AppRecipe | null;
    status: string;
    remark: string | null;
    doc_count: number;
    created_at: string | null;
}
export interface TestStep {
    name: string;
    ok: boolean;
    message: string;
    hint: string | null;
}
export interface TestStep {
    name: string;
    ok: boolean;
    message: string;
    hint: string | null;
    optional?: boolean;
}
export interface AppTestResult {
    ok: boolean;
    steps: TestStep[];
}
export interface ScopeInfo {
    scope: string;
    name: string;
    used_for: string;
    when: string;
}
export interface ScopeGuide {
    scopes: ScopeInfo[];
    author_guide: string;
}
export interface Contact {
    user_id: string | null;
    union_id: string | null;
    name: string | null;
    mobile: string | null;
    dept: string | null;
    from_cache: boolean;
}
export interface Group {
    id: number;
    name: string;
    sort_order: number;
    remark: string | null;
    doc_count: number;
    task_count: number;
}
export interface SubItem {
    id: string;
    name: string;
    kind: string;
    field_count: number | null;
    task_id: number | null;
    task_name: string | null;
    task_status: string | null;
    last_run_status: string | null;
    last_run_at: string | null;
    configured: boolean;
    schedule_label: string | null;
    post_actions_label: string | null;
    auto_column_check: boolean;
    column_drift: string | null;
}
export function setSheetColumnCheck(docId: number, sheetId: string, enabled: boolean) {
    return call<{
        status: string;
        auto_column_check: boolean;
    }>({
        url: `/docs/${docId}/sheets/${sheetId}/column-check`,
        method: 'PATCH',
        data: { enabled },
    });
}
export interface ColumnCheckSheet {
    sheet_id: string;
    sheet_name: string;
    first_check: boolean;
    column_count: number;
    added: string[];
    removed: string[];
}
export interface ColumnCheckResult {
    ok: boolean;
    checked: number;
    changed: number;
    sheets: ColumnCheckSheet[];
    changed_sheets: ColumnCheckSheet[];
    errors: string[];
    error: string | null;
}
export function checkDocColumns(docId: number) {
    return call<ColumnCheckResult>({
        url: `/docs/${docId}/check-columns`,
        method: 'POST',
        timeout: 120000,
    });
}
export interface DocItem {
    id: number;
    name: string;
    doc_type: string;
    doc_type_label: string;
    platform: string;
    node_id: string;
    source_url: string | null;
    app_id: number;
    app_name: string | null;
    operator_union_id: string | null;
    group_id: number | null;
    group_name: string | null;
    group_ids: number[];
    group_names: string[];
    status: string;
    remark: string | null;
    watch_enabled: boolean;
    watch_cron: string | null;
    next_watch_at: string | null;
    last_probe_at: string | null;
    last_probe_ok: boolean | null;
    last_probe_error: string | null;
    structure_drift: string | null;
    sheet_count: number;
    task_count: number;
    unconfigured_count: number;
    created_at: string | null;
    updated_at: string | null;
}
export interface DocSearchHit {
    uuid: string;
    name: string;
    creator: string | null;
    modifier: string | null;
    registered_doc_id: number | null;
    registered_name: string | null;
}
export interface DocSearchResult {
    items: DocSearchHit[];
    next_token: string | null;
    keyword: string;
}
export interface ProbeAttempt {
    doc_type: string;
    label: string;
    code: string;
    message: string;
}
export interface DocResolveResult {
    node_id: string;
    source_url: string | null;
    doc_type: string | null;
    sub_items: SubItem[];
    sub_id_hint: string | null;
    ok: boolean;
    error: string | null;
    hint: string | null;
    code: string | null;
    http_status: number | null;
    attempts: ProbeAttempt[];
    used_node_id: string | null;
    used_operator_union_id: string | null;
}
export interface DocBatchItem {
    ref: string;
    ok: boolean;
    doc_id: number | null;
    node_id: string | null;
    name: string | null;
    doc_type: string | null;
    sub_item_count: number;
    error: string | null;
    hint: string | null;
    skipped: boolean;
}
export interface DocBatchResult {
    total: number;
    ok_count: number;
    failed_count: number;
    skipped_count: number;
    items: DocBatchItem[];
}
export const listApps = () => call<DingApp[]>({ url: '/apps' });
export const getApp = (id: number) => call<DingApp>({ url: `/apps/${id}` });
export const scopeGuide = () => call<ScopeGuide>({ url: '/apps/scopes' });
export const testApp = (id: number) => call<AppTestResult>({ url: `/apps/${id}/test`, method: 'POST' });
export function createApp(data: Record<string, unknown>) {
    return call<DingApp>({ url: '/apps', method: 'POST', data });
}
export function updateApp(id: number, data: Record<string, unknown>) {
    return call<DingApp>({ url: `/apps/${id}`, method: 'PATCH', data });
}
export const deleteApp = (id: number) => call({ url: `/apps/${id}`, method: 'DELETE' });
export function resolveContact(appId: number, mobile: string) {
    return call<Contact>({ url: '/contacts/resolve', params: { app_id: appId, mobile } });
}
export function searchContacts(appId: number, keyword: string, deptId = 1) {
    return call<Contact[]>({
        url: '/contacts/search',
        params: { app_id: appId, keyword: keyword || undefined, dept_id: deptId },
    });
}
export function cachedContacts(appId: number, keyword?: string) {
    return call<Contact[]>({ url: '/contacts', params: { app_id: appId, keyword } });
}
export const listGroups = () => call<Group[]>({ url: '/groups' });
export const createGroup = (name: string) => call<Group>({ url: '/groups', method: 'POST', data: { name } });
export const updateGroup = (id: number, data: Partial<Pick<Group, 'name' | 'sort_order' | 'remark'>>) => call<Group>({ url: `/groups/${id}`, method: 'PATCH', data });
export const deleteGroup = (id: number) => call({ url: `/groups/${id}`, method: 'DELETE' });
export function listDocs(params: {
    group_id?: number;
    app_id?: number;
    keyword?: string;
    drift_only?: boolean;
}) {
    return call<DocItem[]>({ url: '/docs', params });
}
export const getDoc = (id: number) => call<DocItem>({ url: `/docs/${id}` });
export const docSubItems = (id: number) => call<SubItem[]>({ url: `/docs/${id}/subitems` });
export const probeDoc = (id: number) => call<DocResolveResult>({ url: `/docs/${id}/probe`, method: 'POST' });
export function searchDocs(appId: number, keyword: string, nextToken?: string | null) {
    return call<DocSearchResult>({
        url: '/docs/search',
        params: { app_id: appId, keyword, next_token: nextToken || undefined },
    });
}
export function resolveDoc(ref: string, appId: number, operatorUnionId?: string, docType?: string | null) {
    return call<DocResolveResult>({
        url: '/docs/resolve',
        method: 'POST',
        data: {
            ref,
            app_id: appId,
            operator_union_id: operatorUnionId || null,
            doc_type: docType || null,
        },
    });
}
export function createDoc(data: Record<string, unknown>) {
    return call<DocItem>({ url: '/docs', method: 'POST', data });
}
export function batchCreateDocs(appId: number, refs: string[], groupId?: number | null) {
    return call<DocBatchResult>({
        url: '/docs/batch',
        method: 'POST',
        data: { app_id: appId, refs, group_id: groupId ?? null },
    });
}
export function updateDoc(id: number, data: Record<string, unknown>) {
    return call<DocItem>({ url: `/docs/${id}`, method: 'PATCH', data });
}
export const deleteDoc = (id: number) => call({ url: `/docs/${id}`, method: 'DELETE' });
export function setDocWatch(id: number, enabled: boolean, cron?: string | null) {
    return call<DocItem>({
        url: `/docs/${id}/watch`,
        method: 'POST',
        data: { watch_enabled: enabled, watch_cron: cron ?? null },
    });
}
