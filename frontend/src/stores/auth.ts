
import { computed, ref } from 'vue';
import { defineStore } from 'pinia';
import { call, TOKEN_KEY } from '@/api/client';
import type { CurrentUser, LoginResponse } from '@/api/types';
export const useAuthStore = defineStore('auth', () => {
    const token = ref<string>(localStorage.getItem(TOKEN_KEY) || '');
    const user = ref<CurrentUser | null>(null);
    const loading = ref(false);
    const isLoggedIn = computed(() => Boolean(token.value));
    const isAdmin = computed(() => user.value?.role === 'admin');
    const displayName = computed(() => user.value?.display_name || user.value?.username || '未登录');
    function setToken(value: string) {
        token.value = value;
        if (value) {
            localStorage.setItem(TOKEN_KEY, value);
        }
        else {
            localStorage.removeItem(TOKEN_KEY);
        }
    }
    async function login(username: string, password: string) {
        loading.value = true;
        try {
            const data = await call<LoginResponse>({
                url: '/auth/login',
                method: 'POST',
                data: { username, password },
            });
            setToken(data.token);
            user.value = data.user;
            return data.user;
        }
        finally {
            loading.value = false;
        }
    }
    async function fetchMe() {
        user.value = await call<CurrentUser>({ url: '/auth/me' });
        return user.value;
    }
    async function logout() {
        try {
            await call({ url: '/auth/logout', method: 'POST' });
        }
        catch {
        }
        setToken('');
        user.value = null;
    }
    return { token, user, loading, isLoggedIn, isAdmin, displayName, login, fetchMe, logout, setToken };
});
