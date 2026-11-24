<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { reviewApi, type QueueTask } from '../api/review'
import AppHeader from '../components/AppHeader.vue'

const router = useRouter()
const tasks = ref<QueueTask[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const { data } = await reviewApi.queue()
    tasks.value = data.data
  } finally {
    loading.value = false
  }
}

function goReview(taskId: number) {
  router.push(`/review/${taskId}`)
}

onMounted(load)
</script>

<template>
  <el-container class="layout" direction="vertical">
    <AppHeader />
    <el-main>
      <div class="toolbar">
        <el-button @click="load">刷新</el-button>
      </div>
      <el-table v-loading="loading" :data="tasks" border empty-text="暂无待复核任务">
        <el-table-column prop="id" label="任务ID" width="80" />
        <el-table-column prop="contract_name" label="合同名称" min-width="200" show-overflow-tooltip />
        <el-table-column label="风险统计" width="200">
          <template #default="{ row }">
            <el-tag type="danger" size="small">高 {{ row.high_count }}</el-tag>
            <el-tag type="warning" size="small" style="margin-left: 6px">中 {{ row.medium_count }}</el-tag>
            <span style="margin-left: 6px">共 {{ row.risk_total }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="create_time" label="创建时间" width="180">
          <template #default="{ row }">{{ new Date(row.create_time).toLocaleString() }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button link type="danger" @click="goReview(row.id)">去复核</el-button>
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
}
</style>
