<script setup lang="ts">
import { reactive, ref, watch } from 'vue';
import { toastErr, toastOk } from '@/api/client';
import { listApps, updateDoc, type DingApp, type DocItem } from '@/api/dingtalk';
import AppPicker from '@/components/AppPicker.vue';
import GroupSelect from '@/components/GroupSelect.vue';
const props = defineProps<{
    doc: DocItem | null;
}>();
const visible = defineModel<boolean>({ default: false });
const emit = defineEmits<{
    (e: 'saved'): void;
    (e: 'check'): void;
}>();
const apps = ref<DingApp[]>([]);
const saving = ref(false);
const form = reactive({
    name: '',
    group_ids: [] as number[],
    app_id: undefined as number | undefined,
    operator_union_id: '',
    status: 'enabled',
    remark: '',
});
async function ensureApps() {
    if (apps.value.length)
        return;
    try {
        apps.value = await listApps();
    }
    catch {
    }
}
watch(visible, async (open) => {
    if (!open || !props.doc)
        return;
    await ensureApps();
    Object.assign(form, {
        name: props.doc.name,
        group_ids: [...(props.doc.group_ids || [])],
        app_id: props.doc.app_id,
        operator_union_id: props.doc.operator_union_id || '',
        status: props.doc.status,
        remark: props.doc.remark || '',
    });
});
async function save() {
    if (!props.doc)
        return;
    saving.value = true;
    try {
        await updateDoc(props.doc.id, {
            name: form.name,
            group_ids: form.group_ids,
            app_id: form.app_id,
            operator_union_id: form.operator_union_id || null,
            status: form.status,
            remark: form.remark,
        });
        toastOk('已保存');
        visible.value = false;
        emit('saved');
    }
    catch (err) {
        toastErr(err, '保存失败');
    }
    finally {
        saving.value = false;
    }
}
</script>

<template>
  <el-dialog v-model="visible" title="编辑表单" width="520px" append-to-body>
    <el-form label-width="100px">
      <el-form-item label="表单别名">
        <el-input v-model="form.name" />
      </el-form-item>

      <el-form-item label="归属应用">
        <AppPicker v-model="form.app_id" :apps="apps" />
      </el-form-item>
      <el-form-item label="操作人">
        <el-input v-model="form.operator_union_id" placeholder="留空则用应用的默认操作人" />
      </el-form-item>
      <el-form-item label="业务分组">
        <GroupSelect v-model="form.group_ids" placeholder="未分组" />
        <div class="field-hint">
          可以选多个 —— 一张在线表里可能同时放着两个平台的数据。
        </div>
      </el-form-item>
      <el-form-item label="启用状态">
        <el-switch
          :model-value="form.status === 'enabled'"
          active-text="启用"
          inactive-text="停用"
          @change="(v: boolean) => (form.status = v ? 'enabled' : 'disabled')"
        />
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="form.remark" type="textarea" :rows="2" />
      </el-form-item>

      <el-form-item label="列变化">
        <template v-if="doc?.watch_enabled">
          <el-button link type="primary" size="small" @click="emit('check')">
            检测已登记子表的列名有没有变
          </el-button>
        </template>
        <span v-else class="muted">这个表单没开「多了列就提醒我」，不会自动检查</span>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>
