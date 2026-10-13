
import axios, { type AxiosInstance, type AxiosRequestConfig } from 'axios';
import { ElMessage } from 'element-plus';
export const TOKEN_KEY = 'docsync.token';
export interface ApiError {
    status: number;
    message: string;
}
function readToken(): string {
    return localStorage.getItem(TOKEN_KEY) || '';
}
export const http: AxiosInstance = axios.create({
    baseURL: '/api/v1',
    timeout: 120000,
});
http.interceptors.request.use((config) => {
    const token = readToken();
    if (token) {
        config.headers = config.headers ?? {};
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});
function forceLogout() {
    localStorage.removeItem(TOKEN_KEY);
    const { pathname, hash } = window.location;
    if (pathname !== '/login') {
        const redirect = encodeURIComponent(pathname + hash);
        window.location.replace(`/login?redirect=${redirect}`);
    }
}
http.interceptors.response.use((response) => response, (error) => {
    const status = error?.response?.status ?? 0;
    const raw = error?.response?.data?.detail ?? error?.response?.data?.error?.message;
    const detail = Array.isArray(raw) && raw.length
        ? raw
            .map((item: {
            loc?: unknown[];
            msg?: string;
        }) => {
            const field = Array.isArray(item?.loc)
                ? item.loc.filter((part) => part !== 'body').join('.')
                : '';
            const text = String(item?.msg ?? '');
            return field ? `${field}：${text}` : text;
        })
            .filter(Boolean)
            .join('；')
        : raw;
    const message = typeof detail === 'string' && detail
        ? detail
        : status === 0
            ? '连不上服务，请检查后端是否在运行'
            : `请求失败（${status}）`;
    if (status === 401) {
        forceLogout();
    }
    return Promise.reject({ status, message } satisfies ApiError);
});
export async function call<T>(config: AxiosRequestConfig): Promise<T> {
    const res = await http.request<T>(config);
    return res.data;
}
export function toastOk(text: string) {
    ElMessage.success(text);
}
export function toastErr(error: unknown, fallback = '操作失败') {
    const message = (error as ApiError)?.message || fallback;
    ElMessage.error(message);
}
