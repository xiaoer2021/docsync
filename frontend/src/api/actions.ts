
import { call } from './client';
export interface Channel {
    kind: string;
    config: Record<string, unknown>;
}
export interface Action {
    id: number;
    name: string;
    channels: Channel[];
    kind_label: string;
    enabled: boolean;
    remark: string | null;
    used_by: number;
    created_at: string | null;
}
export interface ActionKindField {
    key: string;
    label: string;
    required?: boolean;
    secret?: boolean;
    type?: 'textarea' | 'select' | 'list' | 'bool' | 'kv';
    options?: string[];
    placeholder?: string;
    hint?: string;
    template?: boolean;
    default?: string;
}
export interface ActionKind {
    kind: string;
    label: string;
    help: string;
    fields: ActionKindField[];
}
export interface ChannelResult {
    kind: string;
    label: string;
    ok: boolean;
    http_status: number | null;
    detail: string;
    error: string | null;
    elapsed_ms: number;
}
export interface ActionTestResult {
    ok: boolean;
    results: ChannelResult[];
}
export const listActions = () => call<Action[]>({ url: '/actions' });
export const listActionKinds = () => call<ActionKind[]>({ url: '/actions/kinds' });
export const listTemplateFields = () => call<string[]>({ url: '/actions/template-fields' });
export const createAction = (data: Record<string, unknown>) => call<Action>({ url: '/actions', method: 'POST', data });
export const updateAction = (id: number, data: Record<string, unknown>) => call<Action>({ url: `/actions/${id}`, method: 'PATCH', data });
export const deleteAction = (id: number) => call({ url: `/actions/${id}`, method: 'DELETE' });
export const testAction = (id: number) => call<ActionTestResult>({ url: `/actions/${id}/test`, method: 'POST' });
export const previewChannel = (kind: string, config: Record<string, unknown>) => call<{
    rendered: string;
}>({ url: '/actions/preview', method: 'POST', data: { kind, config } });
export interface ActionRecord {
    id: number;
    run_id: number;
    task_name: string | null;
    trigger_on: string | null;
    status: string;
    kind: string | null;
    started_at: string | null;
    duration_ms: number | null;
    http_status: number | null;
    error_message: string | null;
}
export const listActionRecords = (id: number) => call<ActionRecord[]>({ url: `/actions/${id}/records` });
export const ON_MODE_OPTIONS = [
    {
        value: 'success',
        label: '成功时',
        hint: '只有完全成功才发。部分成功不算成功，不会发。',
    },
    {
        value: 'partial',
        label: '部分成功时',
        hint: '只有部分成功才发（有脏格子、有行被跳过、列类型被自动改过）。',
    },
    {
        value: 'not_success',
        label: '没完全成功时',
        hint: '部分成功和失败都发。想「不干净就通知我」，用这个。',
    },
    {
        value: 'failure',
        label: '失败时',
        hint: '只有失败、超时、取消才发。部分成功不发。',
    },
    {
        value: 'always',
        label: '每次都做',
        hint: '不管什么结果都发。',
    },
];
