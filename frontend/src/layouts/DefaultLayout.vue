<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessageBox } from 'element-plus';
import { call } from '@/api/client';
import { getOverview, type Overview } from '@/api/stats';
import AlreadyHereHint from '@/components/AlreadyHereHint.vue';
import SystemSettingsDialog from '@/components/SystemSettingsDialog.vue';
import { useAlreadyHere } from '@/composables/useAlreadyHere';
import { useAuthStore } from '@/stores/auth';
import { useBrandingStore } from '@/stores/branding';
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const branding = useBrandingStore();
const alreadyHere = useAlreadyHere();
const settingsVisible = ref(false);
const navItems = [
    { name: 'dashboard', path: '/dashboard', label: '概览' },
    { name: 'docs', path: '/docs', label: '表单管理', match: ['docs', 'doc-detail'] },
    {
        name: 'tasks',
        path: '/tasks',
        label: '任务调度',
        match: ['tasks', 'task-new', 'task-edit'],
    },
    { name: 'runs', path: '/runs', label: '执行记录', match: ['runs'] },
    { name: 'actions', path: '/actions', label: '后置动作' },
    { name: 'datasources', path: '/datasources', label: '数据账号' },
    { name: 'apps', path: '/apps', label: '应用中心' },
];
const todoItems = ref<Overview['todo']>([]);
const todoDialogVisible = ref(false);
async function loadTodo() {
    try {
        const o = await getOverview();
        todoItems.value = o.todo;
    }
    catch {
    }
}
function goTodo(item: {
    to: string;
    text: string;
}) {
    const path = item.to.split('?')[0];
    if (path === route.path) {
        alreadyHere.note(`todo:${item.to}`, item.text);
        todoDialogVisible.value = false;
        return;
    }
    todoDialogVisible.value = false;
    router.push(item.to);
}
const svc = ref<{
    status: string;
    version: string;
    env: string;
    database: {
        ok: boolean;
        kind: string;
    };
    scheduler: {
        enabled: boolean;
        running: boolean;
    };
} | null>(null);
const svcError = ref(false);
let svcTimer: number | undefined;
async function loadSvc() {
    try {
        svc.value = await call<NonNullable<typeof svc.value>>({ url: '/health', baseURL: '' });
        svcError.value = false;
    }
    catch {
        svcError.value = true;
    }
}
const backTo = computed(() => {
    const base = route.meta.back as {
        path: string;
        label: string;
    } | undefined;
    const from = String(route.query.from || '');
    const map = route.meta.backFrom as Record<string, {
        path: string;
        label: string;
    }> | undefined;
    return (from && map?.[from]) || base;
});
const activeName = computed(() => {
    const current = String(route.name || 'dashboard');
    const hit = navItems.find((item) => item.name === current || (item.match || []).includes(current));
    return hit?.name || current;
});
onMounted(async () => {
    if (!auth.user) {
        try {
            await auth.fetchMe();
        }
        catch {
        }
    }
    loadSvc();
    loadTodo();
    svcTimer = window.setInterval(() => {
        loadSvc();
        loadTodo();
    }, 60000);
});
onBeforeUnmount(() => {
    if (svcTimer)
        window.clearInterval(svcTimer);
});
function onNavClick(item: {
    name: string;
    label: string;
    path: string;
}) {
    if (activeName.value !== item.name)
        return;
    alreadyHere.note(`nav:${item.name}`, item.label);
}
async function onCommand(command: string) {
    if (command === 'users') {
        await router.push({ name: 'users' });
        return;
    }
    if (command === 'settings') {
        settingsVisible.value = true;
        return;
    }
    if (command === 'logout')
        await onLogout();
}
async function onLogout() {
    await ElMessageBox.confirm('确定要退出登录吗？', '退出登录', {
        confirmButtonText: '退出',
        cancelButtonText: '取消',
        type: 'warning',
    })
        .then(async () => {
        await auth.logout();
        await router.replace({ name: 'login' });
    })
        .catch(() => undefined);
}
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="brand">

        <img class="brand-mark" :src="branding.logoUrl" alt="" />
        <span class="brand-text">{{ branding.name }}</span>
      </div>
      <nav class="nav">
        <router-link
          v-for="item in navItems"
          :key="item.name"
          :to="item.path"
          class="nav-item"
          :class="{ active: activeName === item.name }"
          @click="onNavClick(item)"
        >
          {{ item.label }}
        </router-link>
      </nav>

      <div class="svc">
        <div class="svc-row">
          <span class="svc-dot" :class="svcError ? 'fail' : svc?.status === 'ok' ? 'ok' : 'fail'" />
          <span class="svc-text">
            {{ svcError ? '服务连不上' : svc?.status === 'ok' ? '服务正常' : '服务异常' }}
          </span>
        </div>

        <div class="svc-meta">
          <span>v{{ svc?.version || '—' }}</span>
          <span v-if="!svcError">{{ svc?.database.ok ? '数据库已连' : '数据库断开' }}</span>

          <span
            v-if="!svcError && svc?.scheduler.enabled"
            :class="svc.scheduler.running ? '' : 'svc-warn'"
          >
            {{ svc.scheduler.running ? '调度正常' : '调度已停' }}
          </span>
        </div>
      </div>
    </aside>

    <div class="main">
      <header class="topbar">
        <div class="topbar-left">
          <router-link v-if="backTo" :to="backTo.path" class="back-link">
            <span class="back-arrow">←</span>
            {{ backTo.label }}
          </router-link>

        </div>
        <div class="topbar-right">

          <button
            v-if="todoItems.length"
            class="todo-bell"
            :title="`待处理任务 ${todoItems.length} 条`"
            @click="todoDialogVisible = true"
          >
            <svg class="bell" viewBox="0 0 1024 1024" aria-hidden="true">
              <path
                d="M870 730h-68V485.571c0-159.274-86.37-291.349-238.721-315.891 5.532-10.53 8.721-22.897 8.721-36.128C572 95.14 545.137 64 512 64s-60 31.14-60 69.553c0 13.231 3.188 25.598 8.721 36.128C308.37 194.223 222 326.298 222 485.571V730h-68c-33.137 0-60 26.863-60 60s26.863 60 60 60h716c33.137 0 60-26.863 60-60s-26.863-60-60-60zM592 880c0 44.183-35.817 80-80 80s-80-35.817-80-80"
              />
            </svg>
            <span class="todo-text">待处理任务 {{ todoItems.length }} 条</span>
          </button>

          <el-dropdown trigger="click" @command="onCommand">
            <span class="who">

              <svg class="avatar" viewBox="0 0 1026 1024" aria-hidden="true">
                <path
                  fill-rule="evenodd"
                  d="M514.56 75.264C272.896 75.264 76.8 270.848 76.8 513.024s196.096 437.76 437.76 437.76 437.76-196.096 437.76-437.76-196.096-437.76-437.76-437.76z m-16.384 811.52c-148.48-3.584-286.72-120.832-274.432-131.072 19.968-16.384 16.384-50.688 115.712-65.536 99.328-14.848 85.504-68.096 88.576-66.048-0.512-19.968-2.56-48.128-2.56-48.128-24.576-15.36-43.52-38.912-54.272-66.048-18.432-2.56-32.256-18.944-30.72-38.4 0 0-9.728-68.096 11.776-67.072 0 0 12.288 0 8.704-15.36-1.024-26.112-0.512-75.264 1.024-92.672 1.536-17.408 14.336-64.512 50.176-71.168 11.264-2.56 22.016-4.608 33.792-5.12 9.728-5.12 19.968-8.192 30.72-8.704l46.592-7.68c22.528 0 36.864 31.744 48.64 33.28 13.312-2.048 26.624-2.048 39.424-0.512 35.84 7.168 30.72 56.832 32.768 74.24 2.56 27.136 2.048 54.784-0.512 81.92-3.584 15.872 7.168 13.824 7.168 13.824 25.6 0 17.92 67.072 17.92 67.072-4.096 17.92-13.312 19.968-37.376 35.328-9.728 27.136-25.6 51.712-47.104 71.168 0 0-3.584 33.792-3.584 41.472 0.512 3.072-16.896 54.784 82.432 69.632 99.328 14.848 99.84 45.568 116.736 65.536 11.776 12.288-133.632 133.632-281.6 130.048z"
                />
              </svg>
              {{ auth.displayName }}

              <span v-if="auth.isAdmin && auth.displayName !== '管理员'" class="role-tag">
                管理员
              </span>
              <span v-else-if="!auth.isAdmin" class="role-tag readonly">只读</span>
              <span class="caret">▾</span>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-if="auth.isAdmin" command="users">账号管理</el-dropdown-item>
                <el-dropdown-item v-if="auth.isAdmin" command="settings">系统设置</el-dropdown-item>
                <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>
      <section class="content">
        <router-view />
      </section>
    </div>

    <SystemSettingsDialog v-model="settingsVisible" />

    <el-dialog v-model="todoDialogVisible" title="待处理任务" width="580px" append-to-body>
      <div class="todo-items">
        <div v-for="(item, i) in todoItems" :key="i" class="todo-item" :class="item.kind">
          <span class="todo-dot" />
          <span class="todo-item-text">{{ item.text }}</span>

          <el-button v-if="item.to" link type="primary" size="small" @click="goTodo(item)">
            {{ item.action || '去处理' }} →
          </el-button>
        </div>
        <div v-if="!todoItems.length" class="muted">没有待处理的事了。</div>
      </div>
      <template #footer>
        <el-button @click="todoDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <AlreadyHereHint />
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  min-height: 100dvh;
}

.sidebar {
  width: 196px;
  flex: none;
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  position: sticky;
  top: 0;

  height: 100dvh;
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-4) var(--space-4) 12px;
}

.brand-mark {
  width: 26px;
  height: 26px;
  flex: none;
  display: block;
  object-fit: contain;
}

.brand-text {
  font-size: var(--fs-body);
  font-weight: 600;
  color: var(--text-1);
}

.nav {
  padding: 4px 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow-y: auto;
  flex: 1;
}

.svc {
  flex: none;
  border-top: 1px solid var(--border);
  padding: 10px 14px 12px;
}

.svc-row {
  display: flex;
  align-items: center;
  gap: 7px;
}

.svc-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex: none;
  background: var(--text-3);
}

.svc-dot.ok {
  background: var(--ok);
}

.svc-dot.fail {
  background: var(--danger);
}

.svc-text {
  font-size: var(--fs-label);
  color: var(--text-2);
}

.svc-meta {
  margin-top: 3px;
  display: flex;
  flex-wrap: wrap;
  gap: 0 6px;
  font-size: var(--fs-micro);
  color: var(--text-3);
}

.svc-meta > span + span::before {
  content: '·';
  margin-right: 6px;
  color: var(--text-4);
}

.svc-warn {
  color: var(--danger);
  font-weight: 600;
}

.nav-item {
  display: block;
  padding: 7px 10px;
  border-radius: var(--radius-sm);
  color: var(--text-2);
  font-size: var(--fs-body);
  transition:
    background-color var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out);
}

.nav-item:hover {
  background: var(--surface-sunken);
  color: var(--text-1);
}

.nav-item.active {
  background: var(--brand-weak);
  color: var(--brand);
  font-weight: 600;
}

.main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.topbar {
  height: 52px;
  flex: none;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);

  padding: 0 max(var(--space-4), env(safe-area-inset-right)) 0
    max(var(--space-4), env(safe-area-inset-left));
  position: sticky;
  top: 0;
  z-index: 10;
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--fs-label);
  color: var(--text-2);
  white-space: nowrap;
  padding: 5px 12px 5px 9px;
  border-radius: var(--radius-pill);
  background: var(--surface-sunken);
  transition:
    background-color var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out);
}

.back-link:hover {
  background: var(--brand-weak);
  color: var(--brand);
}

.back-arrow {
  font-size: var(--fs-label);
  line-height: 1;
}

.topbar-sep {
  width: 1px;
  height: 14px;
  background: var(--border);
  flex: none;
}

.topbar-title {
  font-size: var(--fs-body);
  font-weight: 600;
  color: var(--text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  font-size: var(--fs-body);
}

.who {
  color: var(--text-2);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;

}

.todo-bell {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: none;
  padding: 3px 10px;
  border: none;
  border-radius: 999px;
  background: var(--warn-weak);
  color: var(--warn);
  font-family: inherit;
  font-size: var(--fs-label);
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
}

.todo-bell:hover {
  filter: brightness(0.97);
}

.bell {
  width: 15px;
  height: 15px;
  flex: none;
  fill: currentColor;
}

.todo-items {
  display: flex;
  flex-direction: column;
  max-height: 420px;
  overflow-y: auto;
}

.todo-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 0;
  border-bottom: 1px solid var(--border);
  font-size: var(--fs-label);
}

.todo-item:last-child {
  border-bottom: none;
}

.todo-item-text {
  flex: 1;
  min-width: 0;
  line-height: 1.5;
}

.todo-dot {
  width: 7px;
  height: 7px;
  flex: none;
  border-radius: 50%;
  background: var(--brand);
}

.todo-item.warn .todo-dot {
  background: var(--warn);
}

.todo-item.error .todo-dot {
  background: var(--danger);
}

.todo-item.error .todo-item-text {
  color: var(--danger);
}

.todo-item.ok .todo-dot {
  background: var(--ok);
}

@media (max-width: 900px) {
  .todo-bell .todo-text {
    display: none;
  }
}

.avatar {
  width: 26px;
  height: 26px;
  flex: none;
  box-sizing: border-box;
  padding: 4px;
  border-radius: 50%;
  background: var(--brand-weak);
  color: var(--brand);
  fill: currentColor;
}

.caret {
  font-size: var(--fs-micro);
  color: var(--text-3);
}

.role-tag {
  font-size: var(--fs-micro);
  color: var(--brand);
  background: var(--brand-weak);
  border-radius: var(--radius-sm);
  padding: 1px 6px;
}

.role-tag.readonly {
  color: var(--text-3);
  background: var(--info-weak);
}

.content {
  flex: 1;
  min-width: 0;
}

@media (max-width: 900px) {
  .layout {
    flex-direction: column;
  }

  .sidebar {
    width: auto;
    height: auto;
    position: static;
    border-right: none;
    border-bottom: 1px solid var(--border);
    flex-direction: row;
    align-items: center;
    gap: var(--space-4);
    padding: 0 var(--space-4);
    overflow-x: auto;
  }

  .brand {
    padding: var(--space-4) 0;
    flex: none;
  }

  .brand-text {
    display: none;
  }

  .nav {
    flex-direction: row;
    padding: 0;
    gap: var(--space-1);
    flex: 1;
    overflow-x: auto;
    scrollbar-width: none;
  }

  .nav::-webkit-scrollbar {
    display: none;
  }

  .nav-item {
    white-space: nowrap;
    flex: none;
  }

  .svc {
    border-top: none;
    border-left: 1px solid var(--border);
    padding: 0 0 0 var(--space-4);
    flex: none;
  }

  .svc-meta {
    display: none;
  }

  .topbar {
    position: static;
  }
}

@media (max-width: 640px) {
  .topbar-title {
    display: none;
  }

  .topbar {
    height: 48px;
  }
}
</style>
