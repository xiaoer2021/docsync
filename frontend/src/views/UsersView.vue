<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessageBox } from 'element-plus';
import { call, toastErr, toastOk } from '@/api/client';
import type { CurrentUser } from '@/api/types';
import { useAuthStore } from '@/stores/auth';
const auth = useAuthStore();
const users = ref<CurrentUser[]>([]);
const loading = ref(false);
const dialogVisible = ref(false);
const submitting = ref(false);
const editing = ref<CurrentUser | null>(null);
const form = reactive({ username: '', password: '', display_name: '', role: 'viewer' });
const isEdit = computed(() => Boolean(editing.value));
const title = computed(() => (isEdit.value ? '编辑账号' : '新建账号'));
async function load() {
    loading.value = true;
    try {
        users.value = await call<CurrentUser[]>({ url: '/users' });
    }
    catch (err) {
        toastErr(err, '读取账号失败');
    }
    finally {
        loading.value = false;
    }
}
function openCreate() {
    editing.value = null;
    Object.assign(form, { username: '', password: '', display_name: '', role: 'viewer' });
    dialogVisible.value = true;
}
function openEdit(user: CurrentUser) {
    editing.value = user;
    Object.assign(form, {
        username: user.username,
        password: '',
        display_name: user.display_name || '',
        role: user.role,
    });
    dialogVisible.value = true;
}
async function submit() {
    submitting.value = true;
    try {
        if (isEdit.value && editing.value) {
            await call({
                url: `/users/${editing.value.id}`,
                method: 'PATCH',
                data: { display_name: form.display_name, role: form.role },
            });
            if (form.password) {
                await call({
                    url: `/users/${editing.value.id}/password`,
                    method: 'POST',
                    data: { new_password: form.password },
                });
            }
            toastOk('账号已更新');
        }
        else {
            await call({
                url: '/users',
                method: 'POST',
                data: {
                    username: form.username,
                    password: form.password,
                    display_name: form.display_name || form.username,
                    role: form.role,
                },
            });
            toastOk('账号已创建');
        }
        dialogVisible.value = false;
        await load();
    }
    catch (err) {
        toastErr(err, isEdit.value ? '更新失败' : '创建失败');
    }
    finally {
        submitting.value = false;
    }
}
async function toggleStatus(user: CurrentUser) {
    const next = user.status === 'enabled' ? 'disabled' : 'enabled';
    try {
        await call({ url: `/users/${user.id}`, method: 'PATCH', data: { status: next } });
        toastOk(next === 'enabled' ? '已启用' : '已停用');
        await load();
    }
    catch (err) {
        toastErr(err, '操作失败');
    }
}
async function remove(user: CurrentUser) {
    try {
        await ElMessageBox.confirm(`确定删除账号「${user.username}」吗？`, '删除账号', {
            confirmButtonText: '删除',
            cancelButtonText: '取消',
            type: 'warning',
        });
    }
    catch {
        return;
    }
    try {
        await call({ url: `/users/${user.id}`, method: 'DELETE' });
        toastOk('账号已删除');
        await load();
    }
    catch (err) {
        toastErr(err, '删除失败');
    }
}
onMounted(load);
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">账号</h1>
        <div class="page-sub">
          管理员能改配置和跑任务；只读账号只能看列表、日志和执行历史。
        </div>
      </div>
      <el-button v-if="auth.isAdmin" type="primary" @click="openCreate">新建账号</el-button>
    </div>

    <div class="card">
      <el-table v-loading="loading" :data="users" size="small" style="width: 100%">
        <el-table-column prop="username" label="用户名" min-width="140" />
        <el-table-column prop="display_name" label="显示名" min-width="140" />
        <el-table-column label="角色" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.role === 'admin'" type="primary" size="small" effect="light">
              管理员
            </el-tag>
            <el-tag v-else size="small" type="info" effect="light">只读</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <span class="dot" :class="row.status === 'enabled' ? 'ok' : 'warn'">
              {{ row.status === 'enabled' ? '启用' : '停用' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="最近登录" width="170">
          <template #default="{ row }">
            <span class="muted">{{ row.last_login_at ? row.last_login_at.replace('T', ' ').slice(0, 19) : '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="auth.isAdmin" label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button link size="small" @click="toggleStatus(row)">
              {{ row.status === 'enabled' ? '停用' : '启用' }}
            </el-button>
            <el-button
              link
              type="danger"
              size="small"
              :disabled="row.id === auth.user?.id"
              @click="remove(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialogVisible" :title="title" width="440px">
      <el-form label-width="80px" label-position="right">
        <el-form-item label="用户名">
          <el-input v-model="form.username" :disabled="isEdit" placeholder="登录用，字母数字" />
        </el-form-item>
        <el-form-item label="显示名">
          <el-input v-model="form.display_name" placeholder="界面上显示的名字" />
        </el-form-item>
        <el-form-item :label="isEdit ? '重置口令' : '口令'">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            :placeholder="isEdit ? '留空表示不改' : '至少 8 位'"
          />
        </el-form-item>
        <el-form-item label="角色">
          <el-radio-group v-model="form.role">
            <el-radio value="admin">管理员</el-radio>
            <el-radio value="viewer">只读</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
