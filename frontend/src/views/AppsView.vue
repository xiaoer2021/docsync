<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { toastErr, toastOk } from '@/api/client';
import { cancelWpsLogin, clickWpsLogin, createApp, deleteApp, keyWpsLogin, listApps, pollWpsLogin, scopeGuide, searchContacts, startWpsLogin, testApp, typeWpsLogin, updateApp, resolveContact, type AppTestResult, type Contact, type DingApp, type ScopeGuide, type AppRecipe, type WpsLoginState, createDoc, } from '@/api/dingtalk';
import { useAuthStore } from '@/stores/auth';
import { PLATFORMS, isPending, platformOf } from '@/branding';
import PlatformIcon from '@/components/PlatformIcon.vue';
const auth = useAuthStore();
const apps = ref<DingApp[]>([]);
const guide = ref<ScopeGuide | null>(null);
const loading = ref(false);
const testing = ref<number | null>(null);
const loginVisible = ref(false);
const loginLoading = ref(false);
const loginAppId = ref<number | null>(null);
const loginState = ref<WpsLoginState | null>(null);
const loginImg = ref<HTMLImageElement>();
const loginOk = ref(false);
let loginTimer: number | undefined;
const loginSourceLabel = computed(() => {
    const src = loginState.value?.source;
    if (src === 'recipe')
        return '映射（兜底）';
    if (src === 'mixed')
        return '内置 + 部分映射';
    return '内置定位（正常）';
});
function stopLoginPoll() {
    if (loginTimer) {
        window.clearInterval(loginTimer);
        loginTimer = undefined;
    }
}
function applyLogin(state: WpsLoginState) {
    if (state.status === 'ok') {
        stopLoginPoll();
        loginOk.value = true;
        loginVisible.value = false;
        toastOk('WPS 登录成功，登录态已保存');
        void load();
        return;
    }
    if (state.status === 'expired') {
        stopLoginPoll();
        loginState.value = null;
        return;
    }
    loginState.value = state;
    if (!loginTimer) {
        loginTimer = window.setInterval(async () => {
            if (loginAppId.value === null)
                return;
            try {
                applyLogin(await pollWpsLogin(loginAppId.value));
            }
            catch {
                stopLoginPoll();
            }
        }, 1200);
    }
}
async function loginCall(fn: (id: number) => Promise<WpsLoginState>, fail: string) {
    if (loginAppId.value === null)
        return;
    loginLoading.value = true;
    try {
        applyLogin(await fn(loginAppId.value));
    }
    catch (err) {
        toastErr(err, fail);
    }
    finally {
        loginLoading.value = false;
    }
}
async function onMirrorClick(event: MouseEvent) {
    const el = loginImg.value;
    const view = loginState.value?.view;
    if (!el || !view)
        return;
    const rect = el.getBoundingClientRect();
    if (!rect.width || !rect.height)
        return;
    const x = (view.x || 0) + ((event.clientX - rect.left) / rect.width) * view.w;
    const y = (view.y || 0) + ((event.clientY - rect.top) / rect.height) * view.h;
    await loginCall((id) => clickWpsLogin(id, x, y), '那一下没点进去');
}
async function onMirrorKey(event: KeyboardEvent) {
    if (loginAppId.value === null)
        return;
    const special = ['Backspace', 'Enter', 'Tab', 'Delete', 'ArrowLeft', 'ArrowUp', 'ArrowRight', 'ArrowDown'];
    if (special.includes(event.key)) {
        event.preventDefault();
        await loginCall((id) => keyWpsLogin(id, event.key), '那个键没敲进去');
        return;
    }
    if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        await loginCall((id) => typeWpsLogin(id, event.key), '字没打进去');
    }
}
const refreshLogin = () => loginCall((id) => startWpsLogin(id), '拿不到登录页');
async function checkValidity() {
    if (loginAppId.value === null)
        return;
    loginLoading.value = true;
    try {
        const res = await testApp(loginAppId.value);
        const msg = res.steps.map((s) => `${s.ok ? '✅' : '❌'} ${s.name}：${s.message}`).join('；');
        if (res.ok)
            toastOk(`登录还有效 —— ${msg}`);
        else
            ElMessage.warning(`登录可能已失效 —— ${msg}`);
    }
    catch (err) {
        toastErr(err, '检查失败');
    }
    finally {
        loginLoading.value = false;
    }
}
async function ensureApp() {
    if (currentAppId.value !== null || !form.name.trim())
        return;
    saving.value = true;
    try {
        const created = await createApp({
            platform: 'wps',
            name: form.name.trim(),
            recipe: recipePayload(),
            remark: form.remark,
        } as never);
        currentAppId.value = created.id;
        editingId.value = created.id;
        await load();
    }
    catch (err) {
        toastErr(err, '创建应用失败');
    }
    finally {
        saving.value = false;
    }
}
async function startWpsSignIn() {
    if (!form.name.trim()) {
        ElMessage.warning('先填应用名称');
        return;
    }
    await ensureApp();
    if (currentAppId.value === null)
        return;
    loginAppId.value = currentAppId.value;
    loginOk.value = false;
    await refreshLogin();
}
function openLogin(row: DingApp) {
    loginAppId.value = row.id;
    loginState.value = null;
    stopLoginPoll();
    loginVisible.value = true;
    void refreshLogin();
}
async function onLoginClosed() {
    stopLoginPoll();
    if (loginAppId.value !== null) {
        try {
            await cancelWpsLogin(loginAppId.value);
        }
        catch {
        }
    }
    loginAppId.value = null;
    loginState.value = null;
}
const wizardVisible = ref(false);
const step = ref(0);
const saving = ref(false);
const editingId = ref<number | null>(null);
const currentAppId = ref<number | null>(null);
const form = reactive({
    name: '',
    app_key: '',
    app_secret: '',
    default_operator_union_id: '',
    default_operator_name: '',
    remark: '',
});
const operatorMode = ref<'mobile' | 'name' | 'manual'>('mobile');
const mobile = ref('');
const keyword = ref('');
const resolving = ref(false);
const candidates = ref<Contact[]>([]);
const picked = ref<Contact | null>(null);
const testResult = ref<AppTestResult | null>(null);
const isEdit = computed(() => editingId.value !== null);
const wizardTitle = computed(() => (isEdit.value ? '编辑数据应用' : '接入数据应用'));
const platform = ref('dingtalk');
const currentPlatform = computed(() => platformOf(platform.value));
function openCreate() {
    editingId.value = null;
    platform.value = 'dingtalk';
    currentAppId.value = null;
    step.value = 0;
    testResult.value = null;
    picked.value = null;
    candidates.value = [];
    Object.assign(form, {
        name: '',
        app_key: '',
        app_secret: '',
        default_operator_union_id: '',
        default_operator_name: '',
        remark: '',
    });
    wizardVisible.value = true;
}
function openEdit(app: DingApp) {
    editingId.value = app.id;
    platform.value = app.platform || 'dingtalk';
    currentAppId.value = app.id;
    loadRecipe(app);
    step.value = 0;
    testResult.value = null;
    picked.value = null;
    candidates.value = [];
    Object.assign(form, {
        name: app.name,
        app_key: app.app_key,
        app_secret: '',
        default_operator_union_id: app.default_operator_union_id || '',
        default_operator_name: app.default_operator_name || '',
        remark: app.remark || '',
    });
    mobile.value = '';
    keyword.value = '';
    wizardVisible.value = true;
}
async function load() {
    loading.value = true;
    try {
        apps.value = await listApps();
    }
    catch (err) {
        toastErr(err, '读取应用失败');
    }
    finally {
        loading.value = false;
    }
}
function goBack() {
    if (step.value === 2 && !currentPlatform.value.needsOperator) {
        step.value = 0;
        return;
    }
    step.value -= 1;
}
async function submitBasics() {
    if (!form.name) {
        ElMessage.warning('应用名称要填');
        return;
    }
    if (currentPlatform.value.needsCredentials !== false) {
        if (!form.app_key) {
            ElMessage.warning(`应用名称和 ${currentPlatform.value.keyLabel} 都要填`);
            return;
        }
        if (!isEdit.value && !form.app_secret) {
            ElMessage.warning(`${currentPlatform.value.secretLabel} 要填`);
            return;
        }
    }
    saving.value = true;
    try {
        if (isEdit.value && editingId.value) {
            const payload: Record<string, unknown> = {
                name: form.name,
                app_key: form.app_key,
                remark: form.remark,
            };
            if (form.app_secret)
                payload.app_secret = form.app_secret;
            if (platform.value === 'wps')
                payload.recipe = recipePayload();
            const updated = await updateApp(editingId.value, payload);
            currentAppId.value = updated.id;
            form.app_secret = '';
        }
        else {
            const created = await createApp({
                platform: platform.value,
                name: form.name,
                app_key: form.app_key,
                app_secret: form.app_secret,
                remark: form.remark,
                ...(platform.value === 'wps' ? { recipe: recipePayload() } : {}),
            });
            currentAppId.value = created.id;
            editingId.value = created.id;
            form.app_secret = '';
        }
        toastOk('基本信息已保存');
        if (currentAppId.value && platform.value === 'wps') {
            await addDocNow(currentAppId.value);
        }
        await load();
        loadRecipe(apps.value.find((a) => a.id === currentAppId.value));
        step.value = currentPlatform.value.needsOperator ? 1 : 2;
    }
    catch (err) {
        toastErr(err, '保存失败');
    }
    finally {
        saving.value = false;
    }
}
const savingRecipe = ref(false);
function firstUrl(text: string): string {
    const m = /https?:\/\/\S+/.exec(text || '');
    return m ? m[0].replace(/[，。,.\s]+$/, '') : '';
}
function suggestDocName(text: string): string {
    const lines = String(text || '')
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean);
    const head = lines.find((line) => !/^https?:\/\//i.test(line));
    if (!head)
        return '';
    return head
        .replace(/^【[^】]*】\s*/, '')
        .replace(/\s*\d{4}[-/年][\d\-_/.月日:：]*.*$/, '')
        .trim();
}
const docRef = ref('');
const docName = ref('');
const addingDoc = ref(false);
const addedDocs = ref<{
    id: number;
    name: string;
}[]>([]);
function onDocRefChange() {
    if (!docName.value.trim())
        docName.value = suggestDocName(docRef.value);
}
async function addDocNow(appId: number): Promise<boolean> {
    const ref = docRef.value.trim();
    if (!ref)
        return false;
    addingDoc.value = true;
    try {
        const doc = await createDoc({
            ref,
            app_id: appId,
            name: docName.value.trim() || undefined,
        } as never);
        addedDocs.value.push({ id: doc.id, name: doc.name });
        docRef.value = '';
        docName.value = '';
        toastOk('链接测通了，已登记 —— 表单管理里能看到');
        return true;
    }
    catch (err) {
        toastErr(err, '这个链接读不到');
        return false;
    }
    finally {
        addingDoc.value = false;
    }
}
const recipe = reactive<{
    elements: {
        name: string;
        xpath: string;
    }[];
    access: 'public' | 'private';
}>({ elements: [], access: 'public' });
function loadRecipe(app: DingApp | null | undefined) {
    const stored = (app?.recipe || null) as AppRecipe | null;
    const elements = (stored?.elements || {}) as Record<string, string>;
    recipe.elements = Object.entries(elements).map(([name, xpath]) => ({ name, xpath }));
    recipe.access = stored?.access === 'private' ? 'private' : 'public';
}
function recipePayload(): AppRecipe {
    const elements: Record<string, string> = {};
    for (const item of recipe.elements) {
        if (item.name.trim())
            elements[item.name.trim()] = item.xpath.trim();
    }
    return { access: recipe.access, elements };
}
async function saveRecipe() {
    if (!currentAppId.value)
        return;
    savingRecipe.value = true;
    try {
        const updated = await updateApp(currentAppId.value, { recipe: recipePayload() } as never);
        loadRecipe(updated);
        toastOk('已保存');
    }
    catch (err) {
        toastErr(err, '保存失败');
    }
    finally {
        savingRecipe.value = false;
    }
}
async function doResolveByMobile() {
    if (!currentAppId.value || !mobile.value)
        return;
    resolving.value = true;
    picked.value = null;
    try {
        const found = await resolveContact(currentAppId.value, mobile.value);
        picked.value = found;
    }
    catch (err) {
        toastErr(err, '没解析出这个人');
    }
    finally {
        resolving.value = false;
    }
}
async function doSearchByName() {
    if (!currentAppId.value)
        return;
    resolving.value = true;
    candidates.value = [];
    try {
        candidates.value = await searchContacts(currentAppId.value, keyword.value);
        if (!candidates.value.length) {
            ElMessage.info('没找到人。试试直接填手机号，或者手动粘贴 unionId');
        }
    }
    catch (err) {
        toastErr(err, '通讯录查询失败');
    }
    finally {
        resolving.value = false;
    }
}
function pickContact(c: Contact) {
    picked.value = c;
    candidates.value = [];
}
async function submitOperator() {
    if (!currentAppId.value)
        return;
    const unionId = picked.value?.union_id || form.default_operator_union_id;
    if (!unionId) {
        ElMessage.warning('还没确定操作人');
        return;
    }
    saving.value = true;
    try {
        const updated = await updateApp(currentAppId.value, {
            default_operator_union_id: unionId,
            default_operator_name: picked.value?.name || form.default_operator_name || null,
        });
        form.default_operator_union_id = updated.default_operator_union_id || '';
        form.default_operator_name = updated.default_operator_name || '';
        toastOk('操作人已保存');
        await load();
        step.value = 2;
    }
    catch (err) {
        toastErr(err, '保存失败');
    }
    finally {
        saving.value = false;
    }
}
async function runTest() {
    if (!currentAppId.value)
        return;
    testing.value = currentAppId.value;
    try {
        testResult.value = await testApp(currentAppId.value);
        await load();
    }
    catch (err) {
        toastErr(err, '验证失败');
    }
    finally {
        testing.value = null;
    }
}
function testFromRow(app: DingApp) {
    openEdit(app);
    step.value = 2;
    testResult.value = null;
    runTest();
}
async function remove(app: DingApp) {
    try {
        await ElMessageBox.confirm(`确定删除应用「${app.name}」吗？`, '删除应用', {
            confirmButtonText: '删除',
            cancelButtonText: '取消',
            type: 'warning',
        });
    }
    catch {
        return;
    }
    try {
        await deleteApp(app.id);
        toastOk('已删除');
        await load();
    }
    catch (err) {
        toastErr(err, '删除失败');
    }
}
function fmt(value: string | null) {
    return value ? value.replace('T', ' ').slice(0, 19) : '—';
}
function shortId(value: string | null) {
    if (!value)
        return '';
    return value.length <= 14 ? value : `${value.slice(0, 6)}…${value.slice(-4)}`;
}
onMounted(async () => {
    await load();
    try {
        guide.value = await scopeGuide();
    }
    catch {
        guide.value = null;
    }
});
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">应用中心</h1>
        <div class="page-sub">
          应用是读在线表格的钥匙。选平台、填凭证、定操作人，之后所有表单都复用它。
          支持钉钉、飞书和 WPS 个人文档；Google Sheets 与 WPS 开发者 API 暂未接入。
        </div>
      </div>
      <el-button v-if="auth.isAdmin" type="primary" @click="openCreate">接入应用</el-button>
    </div>

    <el-alert
      v-if="!apps.length && !loading"
      type="info"
      :closable="false"
      show-icon
      title="还没有接入任何应用"
      description="点右上角「接入应用」，向导会带你填凭证、开权限、拿操作人并当场验证。"
    />

    <div v-else class="card">
      <el-table v-loading="loading" :data="apps" size="small" style="width: 100%">
        <el-table-column prop="name" label="应用名称" min-width="150" />
        <el-table-column label="AppKey" min-width="170">
          <template #default="{ row }">
            <span class="mono">{{ row.app_key }}</span>
            <div class="sub">打码显示</div>
          </template>
        </el-table-column>
        <el-table-column label="AppSecret" width="120">
          <template #default="{ row }">
            <span class="mono muted">{{ row.app_secret_masked || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作人" min-width="160">
          <template #default="{ row }">

            <span v-if="row.default_operator_name" class="op-name">
              {{ row.default_operator_name }}
            </span>
            <span v-else-if="row.default_operator_union_id" class="mono">
              {{ shortId(row.default_operator_union_id) }}
            </span>
            <el-tag v-else size="small" type="warning" effect="light">未设置</el-tag>
            <div v-if="row.default_operator_union_id" class="sub mono">
              {{ shortId(row.default_operator_union_id) }}
            </div>
          </template>
        </el-table-column>
        <el-table-column label="文档数" width="80" align="right">
          <template #default="{ row }">{{ row.doc_count }}</template>
        </el-table-column>
        <el-table-column label="最近换凭证" width="160">
          <template #default="{ row }">
            <span class="muted">{{ fmt(row.last_token_at) }}</span>
          </template>
        </el-table-column>

        <el-table-column v-if="auth.isAdmin" label="操作" width="300" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" :loading="testing === row.id" @click="testFromRow(row)">
              验证
            </el-button>
            <el-button v-if="row.platform === 'wps'" link size="small" @click="openLogin(row)">
              扫码登录
            </el-button>
            <el-button link size="small" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog
      v-model="loginVisible"
      title="WPS 登录（金山文档授权）"
      width="420px"
      :close-on-click-modal="false"
      @closed="onLoginClosed"
    >
      <div class="login-src">定位：{{ loginSourceLabel }}</div>

      <img
        v-if="loginState?.image"
        ref="loginImg"
        class="login-shot"
        :src="`data:image/png;base64,${loginState.image}`"
        alt="WPS 登录页"
        tabindex="0"
        @click="onMirrorClick"
        @keydown="onMirrorKey"
      />
      <div v-else class="login-hint">正在打开登录页…</div>

      <div class="login-hint">
        用<b>金山文档 / 微信</b>扫上面这个二维码就能登（只支持扫码，不用输账号密码）。
      </div>

      <template #footer>
        <el-button :loading="loginLoading" @click="checkValidity">检查有效期</el-button>
        <el-button :loading="loginLoading" @click="refreshLogin">重新开始</el-button>
        <el-button @click="loginVisible = false">取消</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="wizardVisible" :title="wizardTitle" width="720px" top="6vh">
      <el-steps :active="step" simple style="margin-bottom: 18px">
        <el-step :title="currentPlatform.needsCredentials === false ? '选平台' : '凭证与权限'" />

        <el-step v-if="currentPlatform.needsOperator" title="确定操作人" />
        <el-step title="验证" />
      </el-steps>

      <el-alert
        v-if="isPending(platform)"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 14px"
      >
        <template #title>{{ currentPlatform.label }}的对接还在接入中</template>
        现在可以建应用、把凭证存下来；读数据和同步还没打通，点「验证」会提示未接入。
        接入完成之后这里就不会再提示了。
      </el-alert>

      <div v-show="step === 0">

        <el-form label-width="110px" style="margin-bottom: 4px">
          <el-form-item label="对接平台" required>

            <div class="plat-tiles">
              <button
                v-for="p in PLATFORMS"
                :key="p.key"
                type="button"
                class="plat-tile"
                :class="{ on: platform === p.key, off: !p.enabled || isEdit }"
                :disabled="!p.enabled || isEdit"
                @click="platform = p.key"
              >
                <PlatformIcon :platform="p.key" :size="20" />
                <span class="plat-name">{{ p.label }}</span>
                <span v-if="p.note" class="soon">{{ p.note }}</span>
              </button>
            </div>
            <div class="field-hint">
              <template v-if="isEdit">
                平台建好之后**不能改** —— 换了平台等于换了另一套凭证。
                要接另一个平台，新建一个应用。
              </template>
              <template v-else>
                选哪一家，下面要填的凭证和验证方式就跟着变。
              </template>
            </div>
          </el-form-item>

          <el-form-item v-if="platform === 'wps'" label="登录要求">
            <el-tag type="warning" effect="light">必须登录</el-tag>
            <div class="field-hint">
              建好之后点「扫码登录」：可以**扫码**，也可以切**手机号（短信验证码）**或
              **专属账号**登录。登录态存在服务器上这个应用自己的档案目录里，
              之后读文档一直用它。
            </div>
          </el-form-item>

          <el-form-item v-if="platform === 'wps'" label="应用名称" required>
            <el-input
              v-model="form.name"
              placeholder="自己认得出就行，例如「WPS 取数应用」"
              style="width: 300px"
            />
          </el-form-item>

          <el-form-item v-if="platform === 'wps'" label="登录">
            <div class="wps-signin">
              <img
                v-if="loginState?.image"
                ref="loginImg"
                class="login-shot"
                :src="`data:image/png;base64,${loginState.image}`"
                alt="WPS 登录页"
                tabindex="0"
                @click="onMirrorClick"
                @keydown="onMirrorKey"
              />
              <template v-else>
                <el-button :loading="loginLoading || saving" @click="startWpsSignIn">
                  开始登录
                </el-button>
                <div class="field-hint">
                  点它会先把上面的应用名称创建成一个应用（WPS 一律要登录，
                  登录态存在这个应用自己的档案目录里），然后在下面这张
                  **金山登录页**上**扫码**登录（只留二维码，别的登录方式已隐藏）。
                </div>
              </template>

              <div v-if="loginOk" class="wps-signin-done">
                <el-tag type="success" effect="light">✅ 已获取登录</el-tag>
                <el-button size="small" :loading="loginLoading" @click="checkValidity">
                  检查有效期
                </el-button>
              </div>
              <div v-else-if="loginState?.image" class="field-hint">
                点哪儿就是点哪儿；点一下输入框后直接打字。登完这里会出现「已获取登录」。
              </div>
            </div>
          </el-form-item>

          <el-form-item v-if="platform === 'wps'" label="文档链接">
            <el-input
              v-model="docRef"
              type="textarea"
              :rows="2"
              style="width: 430px"
              placeholder="可选：从金山文档「复制共享链接」整段粘进来（保存时当场试读并登记）"
              @change="onDocRefChange"
              @blur="onDocRefChange"
            />
            <div v-if="firstUrl(docRef)" class="field-hint">
              识别到的链接：<span class="mono">{{ firstUrl(docRef) }}</span>
            </div>
          </el-form-item>

          <el-form-item v-if="platform === 'wps' && docRef.trim()" label="文档名">
            <el-input v-model="docName" style="width: 300px" placeholder="自动从链接里认，可改" />
            <div class="field-hint">它只是「表单管理」里显示的名字，不影响读哪份文档。</div>
          </el-form-item>

          <el-form-item v-if="platform === 'wps' && addedDocs.length" label="本次已添加">
            <div class="added-docs">
              <el-tag v-for="d in addedDocs" :key="d.id" size="small" effect="light">
                {{ d.name }}
              </el-tag>
            </div>
          </el-form-item>
        </el-form>

        <el-alert
          v-if="currentPlatform.needsCredentials !== false"
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 14px"
        >
          <template #title>{{ currentPlatform.keyLabel }} / {{ currentPlatform.secretLabel }} 在哪拿</template>
          {{ currentPlatform.credentialHint }}
        </el-alert>
        <el-form label-width="110px">

          <el-form-item v-if="platform !== 'wps'" label="应用名称" required>
            <el-input v-model="form.name" placeholder="自己认得出就行，例如「BI 取数应用」" />
          </el-form-item>

          <template v-if="currentPlatform.needsCredentials !== false">
            <el-form-item :label="currentPlatform.keyLabel" required>
              <el-input v-model="form.app_key" :placeholder="currentPlatform.keyPlaceholder" />
            </el-form-item>
            <el-form-item
              :label="isEdit ? `${currentPlatform.secretLabel}（留空不改）` : currentPlatform.secretLabel"
              :required="!isEdit"
            >
              <el-input
                v-model="form.app_secret"
                type="password"
                show-password
                :placeholder="isEdit ? '不改就别动' : '创建应用时给的那串密钥'"
              />
            </el-form-item>
          </template>
          <el-form-item label="备注">
            <el-input v-model="form.remark" placeholder="可选" />
          </el-form-item>
        </el-form>

        <el-alert
          v-if="currentPlatform.needsCredentials === false"
          type="success"
          :closable="false"
          show-icon
          style="margin-bottom: 14px"
        >
          <template #title>这个平台不需要凭证</template>
          拿无头浏览器打开网页、把表格复制出来，所以不用 AppKey/AppSecret。
          建好之后到「表单管理」粘一个网页地址就能开始读 —— 公开的分享链接连登录都不用。
        </el-alert>

        <div v-if="platform === 'dingtalk' && guide" class="scope-box">
          <div class="scope-head">
            <b>这个平台要开哪些权限</b>
            <span class="muted">在钉钉开放平台给应用勾上，勾完记得发布版本</span>
          </div>
          <el-table :data="guide.scopes" size="small" style="width: 100%" max-height="220">
            <el-table-column prop="name" label="权限" width="140" />
            <el-table-column prop="scope" label="权限点" min-width="200">
              <template #default="{ row }">
                <span class="mono">{{ row.scope }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="used_for" label="用来做什么" min-width="200" />
          </el-table>
          <div class="guide-note">{{ guide.author_guide }}</div>
        </div>
      </div>

      <div v-show="step === 1">
        <el-alert type="warning" :closable="false" show-icon style="margin-bottom: 14px">
          <template #title>操作人（operatorId）是必填的</template>
          钉钉要求每个读文档的请求都说明「以谁的身份读」，这个值是 unionId 不是姓名也不是手机号。
          填错了接口会报没权限，所以这里帮你自动查。
        </el-alert>

        <el-radio-group v-model="operatorMode" style="margin-bottom: 14px">
          <el-radio-button value="mobile">手机号解析</el-radio-button>
          <el-radio-button value="name">按姓名选人</el-radio-button>
          <el-radio-button value="manual">手动粘贴</el-radio-button>
        </el-radio-group>

        <div v-if="operatorMode === 'mobile'" class="op-pane">
          <div class="op-row">
            <el-input v-model="mobile" placeholder="输入手机号，例如 13800000000" style="max-width: 260px" />
            <el-button type="primary" :loading="resolving" @click="doResolveByMobile">解析</el-button>
          </div>
          <div class="op-hint">
            需要应用开通通讯录读权限；没开通就用「手动粘贴」。
          </div>
        </div>

        <div v-else-if="operatorMode === 'name'" class="op-pane">
          <div class="op-row">
            <el-input v-model="keyword" placeholder="输入姓名关键字" style="max-width: 260px" @keyup.enter="doSearchByName" />
            <el-button type="primary" :loading="resolving" @click="doSearchByName">查人</el-button>
          </div>
          <div v-if="candidates.length" class="op-list">
            <div
              v-for="(c, index) in candidates"
              :key="c.union_id || c.user_id || index"
              class="op-item"
              @click="pickContact(c)"
            >
              <span class="op-name">{{ c.name || c.user_id }}</span>
              <span class="muted">{{ c.dept || '' }}</span>
              <span class="mono muted">{{ c.union_id }}</span>
            </div>
          </div>
          <div class="op-hint">只查根部门一级成员，大组织里的人不一定能搜到 —— 知道手机号就直接用第一种。</div>
        </div>

        <div v-else class="op-pane">
          <el-input
            v-model="form.default_operator_union_id"
            placeholder="粘贴 unionId"
            style="max-width: 420px"
          />
          <div class="op-hint">
            从哪儿拿：开放平台后台的人员详情、同事提供，或者旧脚本里那个 OPERATOR_ID。
          </div>
        </div>

        <div v-if="picked" class="picked">
          <span class="dot ok">已选中</span>
          <b>{{ picked.name || '（无名）' }}</b>
          <span class="muted">{{ picked.dept || '' }}</span>
          <span class="mono muted">{{ picked.union_id }}</span>
        </div>
        <div v-else-if="form.default_operator_union_id && operatorMode === 'manual'" class="picked">
          <span class="dot ok">已填</span>
          <span class="mono">{{ form.default_operator_union_id }}</span>
        </div>
      </div>

      <div v-show="step === 2">

        <el-collapse v-if="platform === 'wps'" class="recipe-collapse">
          <el-collapse-item name="recipe">
            <template #title>
              <span class="recipe-collapse-title">
                取数配方（元素库）
                <span class="muted">网页改版、读不到数据时才需要动</span>
              </span>
            </template>
            <div class="recipe-hint">
              下面是「页面上每个部件怎么找」。**平时不用管**；哪天页面改版、
              读不到数据了，来这儿按 F12 抄一遍新的填上，保存后点验证即可 ——
              不用改代码、不用发版。
            </div>
            <div v-for="(item, i) in recipe.elements" :key="i" class="recipe-row">
              <el-input v-model="item.name" size="small" class="rl-name" placeholder="名称" />
              <el-input v-model="item.xpath" size="small" placeholder="XPath" />
              <el-button size="small" text @click="recipe.elements.splice(i, 1)">✕</el-button>
            </div>
            <div class="seg-foot">
              <el-button
                size="small"
                type="primary"
                plain
                @click="recipe.elements.push({ name: '', xpath: '' })"
              >
                ＋ 加一个元素
              </el-button>
              <el-button size="small" :loading="savingRecipe" @click="saveRecipe">保存配方</el-button>
            </div>
          </el-collapse-item>
        </el-collapse>

        <div class="test-head">
          <el-button type="primary" :loading="testing === currentAppId" @click="runTest">
            开始验证
          </el-button>

          <span class="muted">
            <template v-if="platform === 'wps'">
              拿这个应用的登录档案打开一份已登记的文档，看还读不读得到表格
            </template>
            <template v-else>
              依次检查：换访问凭证 → 文件搜索权限 → 通讯录读权限 → 已登记的在线表格能不能读
            </template>
          </span>
        </div>

        <div v-if="testResult" class="steps">
          <div
            v-for="(s, i) in testResult.steps"
            :key="i"
            class="step-item"
            :class="{ bad: !s.ok && !s.optional, warn: !s.ok && s.optional }"
          >

            <span class="dot" :class="s.ok ? 'ok' : s.optional ? 'warn' : 'fail'">
              {{ s.ok ? '通过' : s.optional ? '提醒' : '失败' }}
            </span>
            <div class="step-body">
              <div class="step-name">
                {{ s.name }}
                <span v-if="s.optional" class="optional-tag">可选</span>
              </div>
              <div class="step-msg">{{ s.message }}</div>
              <div v-if="s.hint" class="step-hint">怎么办：{{ s.hint }}</div>
            </div>
          </div>
        </div>
      </div>

      <template #footer>
        <el-button v-if="step > 0" :disabled="saving" @click="goBack">上一步</el-button>
        <el-button v-if="step === 0" type="primary" :loading="saving" @click="submitBasics">
          {{ isEdit ? '保存并继续' : '创建并继续' }}
        </el-button>
        <el-button v-else-if="step === 1" type="primary" :loading="saving" @click="submitOperator">
          保存并继续
        </el-button>
        <el-button v-else type="primary" @click="wizardVisible = false">完成</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.guide-note {
  margin-top: 12px;
  padding: var(--space-4);
  background: var(--brand-weak);
  border-radius: var(--radius-sm);
  color: var(--text-2);
  line-height: 1.7;
}

.scope-box {
  margin-top: 6px;
  padding: var(--space-4);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-sunken);
}

.scope-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 8px;
}

.op-pane {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--space-4);
  background: var(--surface-sunken);
}

.op-row {
  display: flex;
  gap: 10px;
  align-items: center;
}

.op-hint {
  margin-top: 8px;
  font-size: var(--fs-label);
  color: var(--text-3);
}

.op-list {
  margin-top: 10px;
  max-height: 200px;
  overflow-y: auto;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}

.op-item {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 7px 10px;
  cursor: pointer;
  border-bottom: 1px solid var(--border);
  font-size: var(--fs-label);
}

.op-item:last-child {
  border-bottom: none;
}

.op-item:hover {
  background: var(--brand-weak-2);
}

.op-name {
  font-weight: 600;
  min-width: 70px;
}

.picked {
  margin-top: 12px;
  padding: var(--space-4);
  background: var(--ok-weak);
  border-radius: var(--radius-sm);
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.test-head {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 14px;
  flex-wrap: wrap;
}

.steps {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.step-item {
  display: flex;
  gap: 10px;
  padding: var(--space-4);
  border: 1px solid var(--border);
  border-left: 3px solid var(--ok);
  border-radius: var(--radius-sm);
  background: var(--surface-sunken);
}

.step-item.bad {
  border-left-color: var(--danger);
}

.step-item.warn {
  border-left-color: var(--warn);
}

.optional-tag {
  margin-left: 6px;
  padding: 0 5px;
  border-radius: 3px;
  font-size: var(--fs-micro);
  font-weight: 400;
  color: var(--text-3);
  background: var(--surface-sunken);
}

.step-body {
  min-width: 0;
}

.step-name {
  font-weight: 600;
  color: var(--text-1);
}

.step-msg {
  color: var(--text-2);
  font-size: var(--fs-label);
  word-break: break-all;
}

.step-hint {
  margin-top: 4px;
  font-size: var(--fs-label);
  color: var(--warn);
  line-height: 1.6;
}

.op-name {
  font-weight: 600;
  color: var(--text-1);
}

.sub {
  font-size: var(--fs-label);
  color: var(--text-3);
  line-height: 1.5;
}
.soon {
  margin-left: 4px;
  color: #e6a23c;
  font-size: 12px;
}

.added-docs {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}

.recipe-collapse {
  margin-bottom: 14px;
}

.recipe-collapse-title .muted {
  margin-left: 8px;
  font-weight: 400;
  font-size: 12px;
}

.recipe-hint {
  margin-bottom: 8px;
  font-size: 12px;
  color: var(--text-3, #909399);
  line-height: 1.7;
}

.recipe-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.rl-name {
  width: 180px;
  flex: none;
}

.plat-tiles {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.plat-tile {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px 5px 8px;
  background: #fff;
  border: 1px solid #dcdfe6;
  border-radius: 6px;
  cursor: pointer;
  font: inherit;
  font-size: 13px;
  color: #303133;
  transition: border-color 0.15s, background 0.15s;
}

.plat-tile:hover:not(:disabled) {
  border-color: #c0c4cc;
  background: #f7f9fc;
}

.plat-tile.on {
  border-color: #409eff;
  background: #ecf5ff;
  color: #1f6fd0;
}

.plat-tile.off {
  cursor: not-allowed;
  opacity: 0.55;
  background: #fafafa;
}

.plat-name {
  line-height: 1.4;
}

.plat-check {
  position: absolute;
  right: 0;
  bottom: 0;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #409eff;
  color: #fff;
  font-size: 12px;
  border-radius: 8px 0 8px 0;
}

.field-hint {
  font-size: var(--fs-label);
  color: var(--text-3);
  line-height: 1.6;
}

.login-shot {
  display: block;
  width: auto;
  max-width: 100%;
  height: auto;

  max-height: 420px;

  margin: 0 auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: #fff;
  cursor: pointer;
}

.login-shot:focus,
.login-shot:focus-visible {
  outline: none;
}

.wps-signin {
  display: block;
  width: 100%;
  max-width: 520px;
}

.wps-signin-done {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
}

.login-src {
  font-size: var(--fs-label);
  color: var(--text-3);
  margin-bottom: 10px;
}

.login-tabs {
  margin-bottom: 14px;
}

.login-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  align-items: center;
}

.login-qr {
  width: 200px;
  height: 200px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: #fff;
}

.login-row {
  display: flex;
  gap: 8px;
  width: 100%;
}

.login-wide {
  width: 100%;
}

.login-hint {
  font-size: var(--fs-label);
  color: var(--text-3);
  line-height: 1.7;
  text-align: center;
}

.login-page-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: center;
  width: 100%;
}

.login-accounts {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 100%;
}

.login-account {
  display: flex;
  align-items: center;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
}

.login-avatar {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  vertical-align: middle;
  margin-right: 6px;
}

.login-account-name {
  font-size: var(--fs-body);
}
</style>
