<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import AppHeader from '../components/AppHeader.vue'
import { monitorApi, type MonitorOverview } from '../api/monitor'

const SERVICE_LABELS: Record<string, string> = {
  database: '数据库',
  redis: 'Redis',
  celery: 'Celery Worker',
  milvus: 'Milvus 向量库',
  llm: 'LLM 模型服务',
}

const data = ref<MonitorOverview | null>(null)
const loading = ref(false)
let timer: ReturnType<typeof setInterval> | undefined

function tagType(status: string): 'success' | 'danger' | 'warning' | 'info' {
  if (status === 'up') return 'success'
  if (status === 'down') return 'danger'
  if (status === 'unconfigured') return 'warning'
  return 'info'
}

function serviceText(status: string): string {
  return { up: '正常', down: '异常', configured: '已配置', unconfigured: '未配置' }[status] ?? status
}

async function load() {
  loading.value = true
  try {
    const { data: resp } = await monitorApi.overview()
    data.value = resp.data
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  load()
  timer = setInterval(load, 30000)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <el-container class="layout" direction="vertical">
    <AppHeader />
    <el-main v-loading="loading">
      <div class="toolbar">
        <span class="page-title">系统监控</span>
        <span v-if="data" class="muted">检查时间：{{ new Date(data.checked_at).toLocaleString() }}</span>
        <el-button @click="load">刷新</el-button>
      </div>

      <template v-if="data">
        <el-row :gutter="16" class="cards">
          <el-col v-for="(status, key) in data.services" :key="key" :span="4">
            <el-card shadow="never">
              <div class="card-label">{{ SERVICE_LABELS[key] ?? key }}</div>
              <el-tag :type="tagType(status)" effect="dark">{{ serviceText(status) }}</el-tag>
            </el-card>
          </el-col>
          <el-col :span="4">
            <el-card shadow="never">
              <div class="card-label">在线 Worker</div>
              <div class="card-value">{{ data.workers }}</div>
            </el-card>
          </el-col>
        </el-row>

        <el-row :gutter="16" class="cards">
          <el-col :span="4"><el-card shadow="never"><div class="card-label">队列积压</div><div class="card-value">{{ data.queue_length }}</div></el-card></el-col>
          <el-col :span="4"><el-card shadow="never"><div class="card-label">运行中</div><div class="card-value">{{ data.tasks.running }}</div></el-card></el-col>
          <el-col :span="4"><el-card shadow="never"><div class="card-label">待复核</div><div class="card-value orange">{{ data.tasks.pending_audit }}</div></el-card></el-col>
          <el-col :span="4"><el-card shadow="never"><div class="card-label">24h 完成</div><div class="card-value green">{{ data.tasks.done_24h }}</div></el-card></el-col>
          <el-col :span="4"><el-card shadow="never"><div class="card-label">24h 失败</div><div class="card-value red">{{ data.tasks.failed_24h }}</div></el-card></el-col>
          <el-col :span="4"><el-card shadow="never"><div class="card-label">24h 失败率</div><div class="card-value">{{ (data.tasks.failure_rate * 100).toFixed(1) }}%</div></el-card></el-col>
        </el-row>

        <el-card shadow="never">
          <template #header>最近失败任务</template>
          <el-table :data="data.recent_failures" border empty-text="暂无失败任务">
            <el-table-column prop="task_id" label="任务ID" width="90" />
            <el-table-column prop="contract_name" label="合同名称" min-width="220" show-overflow-tooltip />
            <el-table-column prop="error_msg" label="失败原因" min-width="300" show-overflow-tooltip />
            <el-table-column label="时间" width="180">
              <template #default="{ row }">
                {{ row.finish_time ? new Date(row.finish_time).toLocaleString() : '—' }}
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </template>
    </el-main>
  </el-container>
</template>

<style scoped>
.layout {
  min-height: 100vh;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.page-title {
  font-size: 18px;
  font-weight: 600;
  margin-right: auto;
}
.muted {
  color: #909399;
  font-size: 13px;
}
.cards {
  margin-bottom: 16px;
}
.card-label {
  color: #909399;
  font-size: 13px;
  margin-bottom: 8px;
}
.card-value {
  font-size: 24px;
  font-weight: 600;
}
.card-value.green { color: #67c23a; }
.card-value.orange { color: #e6a23c; }
.card-value.red { color: #f56c6c; }
</style>
