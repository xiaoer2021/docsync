
import { createRouter, createWebHistory } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import { useBrandingStore } from '@/stores/branding';
const router = createRouter({
    history: createWebHistory(),
    routes: [
        {
            path: '/login',
            name: 'login',
            component: () => import('@/views/LoginView.vue'),
            meta: { public: true, title: '登录' },
        },
        {
            path: '/',
            component: () => import('@/layouts/DefaultLayout.vue'),
            redirect: '/dashboard',
            children: [
                {
                    path: 'dashboard',
                    name: 'dashboard',
                    component: () => import('@/views/DashboardView.vue'),
                    meta: { title: '概览' },
                },
                {
                    path: 'docs',
                    name: 'docs',
                    component: () => import('@/views/DocsView.vue'),
                    meta: { title: '表单管理' },
                },
                {
                    path: 'docs/:id',
                    name: 'doc-detail',
                    component: () => import('@/views/DocDetailView.vue'),
                    meta: { title: '表单详情', back: { path: '/docs', label: '返回表单管理' } },
                },
                {
                    path: 'tasks/new',
                    name: 'task-new',
                    component: () => import('@/views/TaskWizardView.vue'),
                    meta: {
                        title: '新建任务',
                        back: { path: '/tasks', label: '返回任务列表' },
                        backFrom: { docs: { path: '/docs', label: '返回表单管理' } },
                    },
                },
                {
                    path: 'tasks',
                    name: 'tasks',
                    component: () => import('@/views/TasksView.vue'),
                    meta: { title: '任务调度' },
                },
                {
                    path: 'tasks/:id',
                    redirect: (to) => ({ path: '/tasks', query: { open: String(to.params.id) } }),
                },
                {
                    path: 'tasks/:id/edit',
                    name: 'task-edit',
                    component: () => import('@/views/TaskWizardView.vue'),
                    meta: {
                        title: '编辑任务',
                        back: { path: '/tasks', label: '返回任务列表' },
                        backFrom: { docs: { path: '/docs', label: '返回表单管理' } },
                    },
                },
                {
                    path: 'runs',
                    name: 'runs',
                    component: () => import('@/views/RunsView.vue'),
                    meta: { title: '执行记录' },
                },
                {
                    path: 'runs/:id',
                    redirect: '/dashboard',
                },
                {
                    path: 'actions',
                    name: 'actions',
                    component: () => import('@/views/ActionsView.vue'),
                    meta: { title: '后置动作' },
                },
                {
                    path: 'datasources',
                    name: 'datasources',
                    component: () => import('@/views/DataSourcesView.vue'),
                    meta: { title: '数据账号' },
                },
                {
                    path: 'apps',
                    name: 'apps',
                    component: () => import('@/views/AppsView.vue'),
                    meta: { title: '应用中心' },
                },
                {
                    path: 'users',
                    name: 'users',
                    component: () => import('@/views/UsersView.vue'),
                    meta: { title: '账号管理', back: { path: '/dashboard', label: '返回概览' } },
                },
            ],
        },
        { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
    ],
});
router.beforeEach((to) => {
    const auth = useAuthStore();
    if (!to.meta.public && !auth.isLoggedIn) {
        return { name: 'login', query: { redirect: to.fullPath } };
    }
    if (to.name === 'login' && auth.isLoggedIn) {
        return { name: 'dashboard' };
    }
    return true;
});
router.afterEach((to) => {
    const page = to.meta.title as string | undefined;
    const brand = useBrandingStore();
    document.title = page && page !== brand.tabTitle ? `${page} · ${brand.tabTitle}` : brand.tabTitle;
});
export default router;
