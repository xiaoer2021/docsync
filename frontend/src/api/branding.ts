
import { call } from './client';
export interface Branding {
    name: string;
    title: string;
    tab_title: string;
    has_logo: boolean;
    logo_updated_at: string | null;
}
export const getBranding = () => call<Branding>({ url: '/settings/branding' });
export function updateBranding(data: Partial<Pick<Branding, 'name' | 'title' | 'tab_title'>>) {
    return call<Branding>({ url: '/settings/branding', method: 'PUT', data });
}
export function uploadLogo(file: File) {
    const form = new FormData();
    form.append('file', file);
    return call<Branding>({ url: '/settings/branding/logo', method: 'POST', data: form });
}
export const resetLogo = () => call<Branding>({ url: '/settings/branding/logo', method: 'DELETE' });
export interface Tuning {
    worker_max_concurrency: number;
    queue_wait_timeout_seconds: number;
    run_timeout_seconds: number;
}
export const getTuning = () => call<Tuning>({ url: '/settings/tuning' });
export function updateTuning(data: Partial<Tuning>) {
    return call<Tuning>({ url: '/settings/tuning', method: 'PUT', data });
}
