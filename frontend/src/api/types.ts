
export interface CurrentUser {
    id: number;
    username: string;
    display_name: string | null;
    role: 'admin' | 'viewer';
    status: string;
    remark: string | null;
    last_login_at: string | null;
    created_at: string | null;
}
export interface LoginResponse {
    token: string;
    expires_in: number;
    user: CurrentUser;
}
export interface HealthInfo {
    status: string;
    version: string;
    env: string;
    database: {
        ok: boolean;
        kind: string;
        error: string | null;
    };
}
