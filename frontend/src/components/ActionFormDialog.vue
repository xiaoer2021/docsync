<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { toastErr, toastOk } from '@/api/client';
import { createAction, listActionKinds, listTemplateFields, previewChannel, testAction, updateAction, type Action, type ActionKind, type Channel, type ChannelResult, } from '@/api/actions';
const props = withDefaults(defineProps<{
    action?: Action | null;
}>(), { action: null });
const visible = defineModel<boolean>({ default: false });
const emit = defineEmits<{
    (e: 'saved', action: Action): void;
}>();
const kinds = ref<ActionKind[]>([]);
const variables = ref<string[]>([]);
const metaLoaded = ref(false);
const saving = ref(false);
const testing = ref(false);
const form = reactive({
    name: '',
    enabled: true,
    remark: '',
    channels: [] as Channel[],
});
const renders = reactive<Record<number, string>>({});
const rendering = ref<number | null>(null);
const testVisible = ref(false);
const testResults = ref<ChannelResult[]>([]);
const testOk = ref(false);
const isEdit = computed(() => Boolean(props.action));
const title = computed(() => (isEdit.value ? '编辑后置动作' : '新建后置动作'));
const VARIABLE_GROUPS: {
    label: string;
    fields: string[];
}[] = [
    { label: '任务', fields: ['task_name', 'task_code', 'target_table', 'datasource'] },
    { label: '结果', fields: ['status_label', 'inserted', 'updated', 'unchanged', 'failed', 'read'] },
    { label: '时间', fields: ['duration_sec', 'started_at', 'finished_at'] },
    { label: '其它', fields: ['error', 'run_id'] },
];
const variableHints: Record<string, string> = {
    task_name: '任务名',
    task_code: '任务编号',
    target_table: '目标表名',
    datasource: '目标库',
    status_label: '成功 / 失败 / 部分成功',
    inserted: '新增行数',
    updated: '更新行数',
    unchanged: '未变化行数',
    failed: '失败行数',
    read: '读到行数',
    duration_sec: '耗时（秒）',
    started_at: '开始时间',
    finished_at: '结束时间',
    error: '错误信息（成功时为空）',
    run_id: '执行编号',
};
function kindOf(kind: string): ActionKind | undefined {
    return kinds.value.find((k) => k.kind === kind);
}
function blankConfig(kind: string): Record<string, unknown> {
    const def = kindOf(kind);
    const out: Record<string, unknown> = {};
    for (const field of def?.fields || []) {
        if (field.type === 'bool')
            out[field.key] = false;
        else if (field.type === 'list')
            out[field.key] = [];
        else if (field.type === 'kv')
            out[field.key] = null;
        else
            out[field.key] = field.default || '';
    }
    return out;
}
function rendersClear() {
    for (const key of Object.keys(renders))
        delete renders[Number(key)];
}
async function ensureMeta() {
    if (metaLoaded.value || kinds.value.length)
        return;
    try {
        kinds.value = await listActionKinds();
        variables.value = await listTemplateFields();
        metaLoaded.value = true;
    }
    catch {
    }
}
function reset() {
    rendersClear();
    testResults.value = [];
    const target = props.action;
    if (target) {
        form.name = target.name;
        form.enabled = target.enabled;
        form.remark = target.remark || '';
        form.channels = target.channels.map((c) => ({
            kind: c.kind,
            config: { ...blankConfig(c.kind), ...c.config },
        }));
        return;
    }
    form.name = '';
    form.enabled = true;
    form.remark = '';
    form.channels = kinds.value.length
        ? [{ kind: kinds.value[0].kind, config: blankConfig(kinds.value[0].kind) }]
        : [];
}
watch(visible, async (open) => {
    if (!open)
        return;
    await ensureMeta();
    reset();
});
function addChannel() {
    const used = new Set(form.channels.map((c) => c.kind));
    const next = kinds.value.find((k) => !used.has(k.kind)) || kinds.value[0];
    if (!next)
        return;
    form.channels.push({ kind: next.kind, config: blankConfig(next.kind) });
}
function onChannelKind(index: number, kind: string) {
    form.channels[index] = { kind, config: blankConfig(kind) };
    delete renders[index];
}
function insertVariable(index: number, key: string, field: string) {
    const current = String(form.channels[index].config[field] ?? '');
    form.channels[index].config[field] = `${current}{${key}}`;
}
async function doRender(index: number) {
    const channel = form.channels[index];
    const target = (kindOf(channel.kind)?.fields || []).find((f) => f.template && f.type === 'textarea');
    rendering.value = index;
    try {
        const built = { ...channel.config };
        if (target && built[target.key] === '')
            delete built[target.key];
        renders[index] = (await previewChannel(channel.kind, built)).rendered;
    }
    catch (err) {
        toastErr(err, '预览失败');
    }
    finally {
        rendering.value = null;
    }
}
async function save() {
    if (!form.name.trim()) {
        toastErr(new Error('请填个名字'), '保存失败');
        return;
    }
    if (!form.channels.length) {
        toastErr(new Error('至少要配一个类型'), '保存失败');
        return;
    }
    const payload = {
        name: form.name.trim(),
        enabled: form.enabled,
        remark: form.remark || null,
        channels: form.channels,
    };
    saving.value = true;
    try {
        const saved = props.action
            ? await updateAction(props.action.id, payload)
            : await createAction(payload);
        toastOk(props.action ? '已保存' : '已新建');
        visible.value = false;
        emit('saved', saved);
    }
    catch (err) {
        toastErr(err, '保存失败');
    }
    finally {
        saving.value = false;
    }
}
async function doTest() {
    if (!props.action)
        return;
    testing.value = true;
    try {
        const result = await testAction(props.action.id);
        testResults.value = result.results;
        testOk.value = result.ok;
        testVisible.value = true;
    }
    catch (err) {
        toastErr(err, '试发失败');
    }
    finally {
        testing.value = false;
    }
}
</script>

<template>
  <el-dialog v-model="visible" :title="title" width="760px" top="5vh" append-to-body>
    <el-form label-width="100px">
      <el-form-item label="名称" required>
        <el-input v-model="form.name" size="small" placeholder="如：同步完成通知" />
      </el-form-item>

      <el-form-item label="做什么" required>
        <div class="channel-list">
          <div v-for="(channel, i) in form.channels" :key="i" class="channel">
            <div class="channel-head">
              <el-select
                :model-value="channel.kind"
                size="small"
                style="width: 180px"
                @change="(v: string) => onChannelKind(i, v)"
              >
                <el-option v-for="k in kinds" :key="k.kind" :label="k.label" :value="k.kind" />
              </el-select>
              <span class="channel-help">{{ kindOf(channel.kind)?.help }}</span>
              <el-button
                v-if="form.channels.length > 1"
                link
                type="danger"
                size="small"
                @click="form.channels.splice(i, 1)"
              >
                去掉
              </el-button>
            </div>

            <div v-for="field in kindOf(channel.kind)?.fields || []" :key="field.key" class="field">
              <div class="field-label">
                {{ field.label }}
                <span v-if="field.required" class="req">*</span>
              </div>
              <el-switch
                v-if="field.type === 'bool'"
                v-model="channel.config[field.key] as boolean"
                size="small"
              />
              <el-select
                v-else-if="field.type === 'select'"
                v-model="channel.config[field.key] as string"
                size="small"
                style="width: 180px"
              >
                <el-option v-for="o in field.options || []" :key="o" :label="o" :value="o" />
              </el-select>
              <el-input
                v-else
                v-model="channel.config[field.key] as string"
                :type="field.type === 'textarea' ? 'textarea' : 'text'"
                :rows="field.type === 'textarea' ? 5 : undefined"
                size="small"
                :placeholder="field.placeholder"
              />

              <div v-if="field.template" class="vars">
                <span class="vars-hint">点一下插到光标末尾：</span>
                <template v-for="group in VARIABLE_GROUPS" :key="group.label">
                  <span class="vars-group">{{ group.label }}</span>
                  <el-tag
                    v-for="key in group.fields"
                    :key="key"
                    size="small"
                    class="var-tag"
                    :title="variableHints[key]"
                    @click="insertVariable(i, key, field.key)"
                  >
                    {{ variableHints[key] || key }}
                  </el-tag>
                </template>
              </div>

              <div v-if="field.hint" class="field-hint">{{ field.hint }}</div>
              <div v-if="field.secret" class="field-hint">
                只显示打码值。留空或不改这一栏 = 保持原来的密钥不变。
              </div>

              <div v-if="field.template" class="render-row">
                <el-button size="small" :loading="rendering === i" @click="doRender(i)">
                  看看发出去长什么样
                </el-button>
                <pre v-if="renders[i]" class="render-box">{{ renders[i] }}</pre>
              </div>
            </div>
          </div>

          <el-button size="small" plain @click="addChannel">再加一个类型</el-button>
          <div class="field-hint">
            一个动作可以同时做几件事。每个类型各自记账，哪个失败了一眼看得出来。
          </div>
        </div>
      </el-form-item>

      <el-form-item label="启用">
        <el-switch v-model="form.enabled" />
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="form.remark" size="small" />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button size="small" @click="visible = false">取消</el-button>
      <el-button size="small" type="primary" :loading="saving" @click="save">保存</el-button>
      <el-button v-if="isEdit" size="small" :loading="testing" @click="doTest">试发一次</el-button>
    </template>

    <el-dialog v-model="testVisible" :title="`试发：${props.action?.name}`" width="620px" append-to-body>
      <el-alert
        :type="testOk ? 'success' : 'error'"
        :closable="false"
        show-icon
        :title="testOk ? '全部渠道发送成功' : '有渠道发送失败'"
      />
      <div v-for="(r, i) in testResults" :key="i" class="result" :class="{ bad: !r.ok }">
        <div class="result-head">
          <span class="dot" :class="r.ok ? 'ok' : 'fail'">{{ r.ok ? '成功' : '失败' }}</span>
          <b>{{ r.label }}</b>
          <span class="muted">{{ r.elapsed_ms }} ms</span>
          <span v-if="r.http_status" class="muted">HTTP {{ r.http_status }}</span>
        </div>
        <div v-if="r.error" class="result-error">{{ r.error }}</div>
        <pre v-if="r.detail" class="render-box">{{ r.detail }}</pre>
      </div>
      <div class="field-hint">试发用的是一份样例数据，不会影响任何实际数据，也不会真去同步。</div>
    </el-dialog>
  </el-dialog>
</template>

<style scoped>
.channel-list {
  width: 100%;
}

.channel {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--space-4);
  margin-bottom: 10px;
  background: var(--surface-sunken);
}

.channel-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.channel-help {
  flex: 1;
  font-size: var(--fs-label);
  color: var(--text-3);
  line-height: 1.5;
}

.field {
  margin-bottom: 10px;
}

.field:last-child {
  margin-bottom: 0;
}

.field-label {
  font-size: var(--fs-label);
  color: var(--text-2);
  margin-bottom: 4px;
}

.req {
  color: var(--danger);
}

.field-hint {
  font-size: var(--fs-label);
  color: var(--text-3);
  line-height: 1.6;
  margin-top: 4px;
}

.vars {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  margin-top: 6px;
}

.vars-hint {
  font-size: var(--fs-label);
  color: var(--text-3);
}

.vars-group {
  font-size: var(--fs-micro);
  color: var(--text-3);
  background: var(--info-weak);
  border-radius: var(--radius-sm);
  padding: 1px 6px;
}

.var-tag {
  cursor: pointer;
}

.render-row {
  margin-top: 6px;
}

.render-box {
  margin-top: 6px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  font-size: var(--fs-label);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow: auto;
}

.result {
  border: 1px solid var(--border);
  border-left: 3px solid var(--ok);
  border-radius: var(--radius-sm);
  padding: var(--space-4);
  margin-top: 10px;
}

.result.bad {
  border-left-color: var(--danger);
}

.result-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.result-error {
  margin-top: 4px;
  font-size: var(--fs-label);
  color: var(--danger);
  word-break: break-all;
}
</style>
