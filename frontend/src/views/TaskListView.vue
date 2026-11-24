<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { reviewApi, type ReviewTask } from '../api/review'
import { useUserStore } from '../stores/user'
import AppHeader from '../components/AppHeader.vue'

const router = useRouter()
const store = useUserStore()
const tasks = ref<ReviewTask[]>([])
const uploading = ref(false)

// SSE 连接（按任务 id 管理）
const sources = new Map<number, EventSource>()
// 每个任务的实时进度消息
const progressMap = ref<Record<number, string>>({})

const STATUS_MAP: Record<string, { text: string; type: string }> = {
  pending: { text: '待启动', type: 'info' },
  queued: { text: '排队中', type: 'info' },
  parsing: { text: '解析中', type: 'warning' },
  extracting: { text: '条款提取中', type: 'warning' },
  reviewing: { text: '风险识别中', type: 'warning' },
  pending_audit: { text: '待复核', type: 'danger' },
  reporting: { text: '报告生成中', type: 'warning' },
  done: { text: '已完成', type: 'success' },
  failed: { text: '失败', type: 'danger' },
}

async function loadTasks() {
  const { data } = await reviewApi.list()
  tasks.value = data.data
}

async function onUpload(file: File) {
  uploading.value = true
  try {
    const { data } = await reviewApi.upload(file)
    ElMessage.success('上传成功，已创建审查任务')
    await startTask(data.data.task_id)
    await loadTasks()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? '上传失败')
  } finally {
    uploading.value = false
  }
  return false // 阻止 el-upload 默认提交
}

async function startTask(taskId: number) {
  await reviewApi.start(taskId)
  watchProgress(taskId)
}

function watchProgress(taskId: number) {
  if (sources.has(taskId)) return
  const es = new EventSource(`/api/review/${taskId}/events?token=${store.token}`)
  es.addEventListener('progress', (e) => {
    const evt = JSON.parse((e as MessageEvent).data)
    progressMap.value[taskId] = evt.message ?? ''
    if (evt.node === 'workflow') {
      es.close()
      sources.delete(taskId)
      loadTasks()
    }
  })
  es.onerror = () => {
    es.close()
    sources.delete(taskId)
  }
  sources.set(taskId, es)
}

function downloadReport(taskId: number) {
  window.open(reviewApi.exportUrl(taskId), '_blank')
}

onMounted(loadTasks)
onUnmounted(() => sources.forEach((es) => es.close()))
</script>

<template>
  <el-container class="layout" direction="vertical">
    <AppHeader />
    <el-main>
      <div class="toolbar">
        <el-upload :show-file-list="false" :before-upload="onUpload" accept=".pdf,.docx,.txt">
          <el-button type="primary" :loading="uploading">上传合同</el-button>
        </el-upload>
        <el-button @click="loadTasks">刷新</el-button>
      </div>

      <el-table :data="tasks" border>
        <el-table-column prop="id" label="任务ID" width="80" />
        <el-table-column prop="contract_name" label="合同名称" min-width="200" show-overflow-tooltip />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="STATUS_MAP[row.status]?.type ?? 'info'">
              {{ STATUS_MAP[row.status]?.text ?? row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="实时进度" min-width="220">
          <template #default="{ row }">
            <span>{{ progressMap[row.id] || row.error_msg || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="create_time" label="创建时间" width="180">
          <template #default="{ row }">{{ new Date(row.create_time).toLocaleString() }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button v-if="row.status === 'pending' || row.status === 'failed'" link type="primary" @click="startTask(row.id)">
              启动
            </el-button>
            <el-button v-if="['reviewing', 'pending_audit', 'reporting', 'done'].includes(row.status)" link type="primary" @click="router.push(`/review/${row.id}`)">
              详情
            </el-button>
            <el-button v-if="row.status === 'done'" link type="success" @click="downloadReport(row.id)">
              下载报告
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-main>
  </el-container>
</template>

<style scoped>
.layout {
  min-height: 100vh;
}
.toolbar {
  margin-bottom: 16px;
  display: flex;
  gap: 12px;
}
</style>
