
import { call } from './client';
export interface UpcomingTask {
    task_id: number;
    name: string;
    schedule_label: string;
    next_run_at: string;
    target_table: string;
    write_mode: string;
}
export interface OverviewRun {
    id: number;
    task_id: number;
    task_name: string;
    status: string;
    status_label: string;
    trigger_type: string;
    trigger_label: string;
    started_at: string | null;
    finished_at: string | null;
    duration_ms: number | null;
    rows_read: number;
    rows_written: number;
    rows_inserted: number;
    rows_updated: number;
    rows_unchanged: number;
    rows_failed: number;
    error_message: string | null;
}
export interface OverviewFailure {
    id: number;
    task_id: number;
    task_name: string;
    finished_at: string | null;
    error_type: string | null;
    error_message: string | null;
}
export interface Overview {
    counts: {
        docs: number;
        sheets: number;
        tasks: number;
        tasks_enabled: number;
        actions: number;
        sheets_without_task: number;
        scheduled_tasks: number;
        runs_running: number;
    };
    window: {
        days: number;
        runs: number;
        success: number;
        failed: number;
        rows_written: number;
        success_rate: number | null;
    };
    upcoming: UpcomingTask[];
    recent_runs: OverviewRun[];
    failures: OverviewFailure[];
    todo: {
        kind: string;
        text: string;
        to: string;
        action: string;
    }[];
}
export const getOverview = () => call<Overview>({ url: '/stats/overview' });
