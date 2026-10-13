<script setup lang="ts">
import { reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import { toastErr } from '@/api/client';
import { useAuthStore } from '@/stores/auth';
import { useBrandingStore } from '@/stores/branding';
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const branding = useBrandingStore();
const form = reactive({ username: '', password: '' });
const error = ref('');
async function onSubmit() {
    error.value = '';
    if (!form.username || !form.password) {
        error.value = '请填写用户名和口令';
        return;
    }
    try {
        await auth.login(form.username, form.password);
        ElMessage.success('登录成功');
        const redirect = (route.query.redirect as string) || '/dashboard';
        await router.replace(redirect);
    }
    catch (err) {
        toastErr(err, '登录失败');
    }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-brand">
        <img class="brand-mark" :src="branding.logoUrl" alt="" />
        <div>
          <div class="brand-title">{{ branding.title }}</div>
          <div class="brand-sub">快速同步在线表单至数据库</div>
        </div>
      </div>

      <el-form label-position="top" @submit.prevent="onSubmit">
        <el-form-item label="用户名">
          <el-input
            v-model="form.username"
            size="large"
            placeholder="请输入用户名"
            autocomplete="username"
            @keyup.enter="onSubmit"
          />
        </el-form-item>
        <el-form-item label="口令">
          <el-input
            v-model="form.password"
            type="password"
            size="large"
            show-password
            placeholder="请输入口令"
            autocomplete="current-password"
            @keyup.enter="onSubmit"
          />
        </el-form-item>

        <div v-if="error" class="login-error">{{ error }}</div>

        <el-button
          type="primary"
          size="large"
          class="login-submit"
          :loading="auth.loading"
          @click="onSubmit"
        >
          登录
        </el-button>
      </el-form>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  background: var(--canvas);
  padding: 24px;
}

.login-card {
  width: 360px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-pop);
  padding: 28px 26px 24px;
}

.login-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 22px;
}

.brand-mark {
  width: 34px;
  height: 34px;
  flex: none;
  display: block;
  object-fit: contain;
}

.brand-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-1);
}

.brand-sub {
  font-size: var(--fs-label);
  color: var(--text-3);
  line-height: 1.4;
}

.login-error {
  margin: -4px 0 12px;
  padding: 7px 10px;
  background: var(--danger-weak);
  color: var(--danger);
  border-radius: var(--radius-sm);
  font-size: var(--fs-label);
}

.login-submit {
  width: 100%;
}
</style>
