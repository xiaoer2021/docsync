<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { listTasks, type Task } from '@/api/sync';
import RunLogTable from '@/components/RunLogTable.vue';
import TaskBriefDialog from '@/components/TaskBriefDialog.vue';
const tasks = ref<Task[]>([]);
const pickedTask = ref<number | null>(null);
const briefTask = ref<number | null>(null);
const briefVisible = ref(false);
function openBrief(taskId: number) {
    briefTask.value = taskId;
    briefVisible.value = true;
}
onMounted(async () => {
    try {
        tasks.value = await listTasks();
    }
    catch {
        tasks.value = [];
    }
});
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">执行记录</h1>
        <div class="page-sub">
          查看每次同步的读取与写入数量、异常数据和规则处理结果。
          点一行展开看日志正文。
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-body">
        <div class="filter-bar">
          <span class="muted">看哪个任务</span>
          <el-select
            v-model="pickedTask"
            size="small"
            style="width: 260px"
            placeholder="全部任务"
            clearable
          >
            <el-option v-for="t in tasks" :key="t.id" :label="t.name" :value="t.id" />
          </el-select>
          <span v-if="!tasks.length" class="muted">（还没有任务）</span>
        </div>

        <RunLogTable :task-id="pickedTask" @pick-task="openBrief" />
      </div>
    </div>

    <TaskBriefDialog v-model="briefVisible" :task-id="briefTask" />
  </div>
</template>

<style scoped>
.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
</style>
