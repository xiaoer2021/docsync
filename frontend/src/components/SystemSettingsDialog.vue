<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { toastErr, toastOk } from '@/api/client';
import { getTuning, resetLogo, updateBranding, updateTuning, uploadLogo, type Tuning, } from '@/api/branding';
import { useBrandingStore } from '@/stores/branding';
const branding = useBrandingStore();
const visible = defineModel<boolean>({ default: false });
const SECTION_BRAND = 'brand';
const SECTION_SCHEDULE = 'schedule';
const section = ref(SECTION_BRAND);
const saving = ref(false);
const uploading = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);
const form = reactive({ name: '', title: '', tab_title: '' });
const tuning = ref<Tuning>({
    worker_max_concurrency: 6,
    queue_wait_timeout_seconds: 300,
    run_timeout_seconds: 1800,
});
watch(visible, async (open) => {
    if (!open)
        return;
    section.value = SECTION_BRAND;
    form.name = branding.name;
    form.title = branding.title;
    form.tab_title = branding.tabTitle;
    try {
        tuning.value = await getTuning();
    }
    catch {
    }
});
const nameTooLong = computed(() => form.name.length > 14);
function human(seconds: number): string {
    if (seconds % 3600 === 0)
        return `${seconds / 3600} 小时`;
    if (seconds % 60 === 0)
        return `${seconds / 60} 分钟`;
    return `${seconds} 秒`;
}
async function save() {
    saving.value = true;
    try {
        branding.apply(await updateBranding({
            name: form.name,
            title: form.title,
            tab_title: form.tab_title,
        }));
        tuning.value = await updateTuning({ ...tuning.value });
        toastOk('已保存');
        visible.value = false;
    }
    catch (err) {
        toastErr(err, '保存失败');
    }
    finally {
        saving.value = false;
    }
}
function pickFile() {
    fileInput.value?.click();
}
async function onFile(event: Event) {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file)
        return;
    if (file.size > 2 * 1024 * 1024) {
        ElMessage.warning('图片太大了，请控制在 2MB 以内');
        return;
    }
    uploading.value = true;
    try {
        branding.apply(await uploadLogo(file));
        toastOk('logo 已更换');
    }
    catch (err) {
        toastErr(err, '上传失败');
    }
    finally {
        uploading.value = false;
    }
}
async function restoreLogo() {
    try {
        await ElMessageBox.confirm('恢复成内置的默认 logo？', '恢复默认 logo', {
            confirmButtonText: '恢复',
            cancelButtonText: '取消',
            type: 'warning',
        });
    }
    catch {
        return;
    }
    try {
        branding.apply(await resetLogo());
        toastOk('已恢复默认 logo');
    }
    catch (err) {
        toastErr(err, '恢复失败');
    }
}
</script>

<template>
  <el-dialog v-model="visible" title="系统设置" width="760px" top="6vh" append-to-body>
    <div class="settings">

      <nav class="settings-nav">
        <button
          class="nav-item"
          :class="{ active: section === SECTION_BRAND }"
          @click="section = SECTION_BRAND"
        >
          品牌
          <span class="nav-sub">logo、名称、标题</span>
        </button>
        <button
          class="nav-item"
          :class="{ active: section === SECTION_SCHEDULE }"
          @click="section = SECTION_SCHEDULE"
        >
          调度
          <span class="nav-sub">并发、超时</span>
        </button>
      </nav>

      <section class="settings-body">

        <template v-if="section === SECTION_BRAND">
          <el-form label-width="100px">
            <el-form-item label="Logo">
              <div class="logo-row">
                <img class="logo-preview" :src="branding.logoUrl" alt="" />
                <div class="logo-actions">
                  <div>
                    <el-button size="small" :loading="uploading" @click="pickFile">
                      上传新 logo
                    </el-button>
                    <el-button v-if="branding.hasLogo" size="small" @click="restoreLogo">
                      恢复默认
                    </el-button>
                  </div>
                  <div class="field-hint">
                    建议正方形、透明底，png / jpg / svg / webp，2MB 以内。
                    侧边栏和登录页都会用它，浏览器标签页的图标也跟着换。
                  </div>
                </div>
              </div>
              <input
                ref="fileInput"
                type="file"
                accept="image/png,image/jpeg,image/svg+xml,image/webp"
                style="display: none"
                @change="onFile"
              />
            </el-form-item>

            <el-form-item label="侧边栏名称">
              <el-input v-model="form.name" placeholder="显示在左侧导航顶部" />
              <div class="field-hint" :class="{ warn: nameTooLong }">
                只出现在左侧导航栏顶部（logo 旁边）。那一格放不下太长的名字，建议 14 字以内。
              </div>
            </el-form-item>

            <el-form-item label="登录页标题">
              <el-input v-model="form.title" placeholder="登录页上的大标题" />
              <div class="field-hint">
                只出现在登录页的那行大标题上。登录之后就看不到那一页了，
                改动要下次回到登录页才看得出来。
              </div>
            </el-form-item>

            <el-form-item label="网页标题">
              <el-input v-model="form.tab_title" placeholder="浏览器标签页上显示的文字" />
              <div class="field-hint">
                浏览器标签页上那段文字。完整写法是「当前页面 · 网页标题」，
                在「表单管理」页会显示成「表单管理 · {{ form.tab_title || '在线表格同步' }}」。
              </div>
            </el-form-item>

            <el-form-item label="效果">
              <div class="preview-stack">
                <div class="preview-row">
                  <span class="preview-cap">侧边栏</span>
                  <div class="mock">
                    <img class="mock-logo" :src="branding.logoUrl" alt="" />
                    <span class="mock-name">{{ form.name || '在线表格同步' }}</span>
                  </div>
                </div>
                <div class="preview-row">
                  <span class="preview-cap">登录页</span>
                  <div class="mock">
                    <img class="mock-logo lg" :src="branding.logoUrl" alt="" />
                    <div>
                      <div class="mock-title">{{ form.title || '在线表格同步' }}</div>
                      <div class="mock-sub">快速同步在线表单至数据库</div>
                    </div>
                  </div>
                </div>
                <div class="preview-row">
                  <span class="preview-cap">标签页</span>
                  <span class="mock-tab">表单管理 · {{ form.tab_title || '在线表格同步' }}</span>
                </div>
              </div>
            </el-form-item>
          </el-form>
        </template>

        <template v-else>
          <el-form label-width="160px">
            <el-form-item label="同时执行的个数">
              <el-input-number
                v-model="tuning.worker_max_concurrency"
                :min="1"
                :max="32"
                controls-position="right"
              />
              <div class="field-hint">
                定时任务经常在同一分钟一起触发。这个数小了，后面的就得排队等着。
                每个执行都要占数据库连接、还要往返钉钉，所以不能开太大 ——
                <b>6~8 对这套系统是安全的</b>。
              </div>
            </el-form-item>

            <el-form-item label="排队最多等多久">
              <el-input-number
                v-model="tuning.queue_wait_timeout_seconds"
                :min="30"
                :max="86400"
                :step="60"
                controls-position="right"
              />
              <span class="unit">秒（{{ human(tuning.queue_wait_timeout_seconds) }}）</span>
              <div class="field-hint">
                等超过这个时间说明名额被卡住了。与其无限期挂在「排队中」
                （界面上看不出为什么），不如标成超时并写明原因。
              </div>
            </el-form-item>

            <el-form-item label="单次执行超时">
              <el-input-number
                v-model="tuning.run_timeout_seconds"
                :min="60"
                :max="86400"
                :step="60"
                controls-position="right"
              />
              <span class="unit">秒（{{ human(tuning.run_timeout_seconds) }}）</span>
              <div class="field-hint">
                一次执行跑超过这个时间就强制中止，并把名额让出来。
                <b>没有这个上限的话，一个卡住的执行会永远占着名额</b>，
                后面的任务就一直排队。
              </div>
            </el-form-item>

            <el-form-item label="当前队列">
              <span class="muted">
                上限 {{ tuning.worker_max_concurrency }} 个 ·
                改完保存即刻生效，不用重启
              </span>
            </el-form-item>
          </el-form>
        </template>
      </section>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.settings {
  display: flex;
  gap: 16px;
  min-height: 380px;
}

.settings-nav {
  width: 150px;
  flex: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
  border-right: 1px solid var(--border);
  padding-right: 12px;
}

.nav-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  align-items: flex-start;
  padding: 8px 10px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-1);
  font-family: inherit;
  font-size: var(--fs-body);
  font-weight: 600;
  cursor: pointer;
  text-align: left;
}

.nav-item:hover {
  background: var(--brand-weak-2);
}

.nav-item.active {
  background: var(--brand-weak);
  color: var(--brand);
}

.nav-sub {
  font-size: var(--fs-micro);
  font-weight: 400;
  color: var(--text-3);
}

.settings-body {
  flex: 1;
  min-width: 0;
}

.field-hint {
  font-size: var(--fs-label);
  color: var(--text-3);
  line-height: 1.6;
  margin-top: 4px;
  width: 100%;
}

.field-hint.warn {
  color: var(--warn);
}

.unit {
  margin-left: 8px;
  font-size: var(--fs-label);
  color: var(--text-3);
}

.logo-row {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  width: 100%;
}

.logo-preview {
  width: 56px;
  height: 56px;
  flex: none;
  object-fit: contain;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-sunken);
  padding: 4px;
}

.logo-actions {
  flex: 1;
  min-width: 0;
}

.preview-stack {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.preview-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.preview-cap {
  width: 52px;
  flex: none;
  font-size: var(--fs-label);
  color: var(--text-3);
}

.mock {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: var(--surface-sunken);
  border-radius: var(--radius-sm);
  min-width: 0;
}

.mock-logo {
  width: 20px;
  height: 20px;
  flex: none;
  object-fit: contain;
}

.mock-logo.lg {
  width: 34px;
  height: 34px;
}

.mock-name {
  font-weight: 600;
  color: var(--text-1);
}

.mock-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-1);
}

.mock-sub {
  font-size: var(--fs-micro);
  color: var(--text-3);
}

.mock-tab {
  font-size: var(--fs-label);
  color: var(--text-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm) var(--radius-sm) 0 0;
  padding: 3px 10px;
  background: var(--surface);
}
</style>
