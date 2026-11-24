<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import AppHeader from '../components/AppHeader.vue'
import { auditApi, type AuditItem } from '../api/audit'

const ACTION_MAP: Record<string, string> = {
  login: '登录',
  upload: '上传合同',
  'review:start': '启动审查',
  'review:feedback': '复核处置',
  'report:export': '导出报告',
  'rule:create': '新增规则',
  'rule:update': '修改规则',
  'rule:delete': '删除规则',
  'knowledge:upload': '上传知识库',
  'workflow:failed': '工作流失败',
  'audit:query': '查询审计',
}

const query = reactive({
  page: 1,
  page_size: 20,
  action: '',
  operator: '',
  keyword: '',
})
const range = ref<string[]>([])
const items = ref<AuditItem[]>([])
const total = ref(0)
const actions = ref<string[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const params: Record<string, string | number> = {
      page: query.page, page_size: query.page_size,
    }
    if (query.action) params.action = query.action
    if (query.operator) params.operator = query.operator
    if (query.keyword) params.keyword = query.keyword
    if (range.value?.length === 2) {
      params.start = range.value[0]
      params.end = range.value[1]
    }
    const { data } = await auditApi.logs(params as any)
    items.value = data.data.items
    total.value = data.data.total
  } finally {
    loading.value = false
  }
}

function search() {
  query.page = 1
  load()
}

function reset() {
  query.page = 1
  query.action = ''
  query.operator = ''
  query.keyword = ''
  range.value = []
  load()
}

function onPage(page: number) {
  query.page = page
  load()
}

function onSize(size: number) {
  query.page_size = size
  query.page = 1
  load()
}

onMounted(async () => {
  const { data } = await auditApi.actions()
  actions.value = data.data
  await load()
})
</script>

<template>
  <el-container class="layout" direction="vertical">
    <AppHeader />
    <el-main>
      <div class="toolbar">
        <span class="page-title">审计日志</span>
        <el-select v-model="query.action" placeholder="全部动作" clearable style="width: 180px">
          <el-option v-for="a in actions" :key="a" :label="`${ACTION_MAP[a] ?? a}（${a}）`" :value="a" />
        </el-select>
        <el-input v-model="query.operator" placeholder="操作人" clearable style="width: 140px" />
        <el-input v-model="query.keyword" placeholder="对象/详情关键字" clearable style="width: 180px" />
        <el-date-picker
          v-model="range" type="daterange" value-format="YYYY-MM-DD"
          start-placeholder="开始日期" end-placeholder="结束日期" style="width: 260px"
        />
        <el-button type="primary" @click="search">查询</el-button>
        <el-button @click="reset">重置</el-button>
      </div>

      <el-table v-loading="loading" :data="items" border empty-text="暂无审计记录">
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column label="时间" width="180">
          <template #default="{ row }">{{ new Date(row.create_time).toLocaleString() }}</template>
        </el-table-column>
        <el-table-column label="操作人" width="160">
          <template #default="{ row }">
            {{ row.real_name || row.operator }}
            <span v-if="row.real_name" class="muted">（{{ row.operator }}）</span>
          </template>
        </el-table-column>
        <el-table-column label="动作" width="150">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ ACTION_MAP[row.action] ?? row.action }}</el-tag>
            <span class="muted code">{{ row.action }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="target" label="对象" min-width="180" show-overflow-tooltip />
        <el-table-column prop="detail" label="详情" min-width="240" show-overflow-tooltip />
      </el-table>

      <el-pagination
        class="pager"
        layout="total, sizes, prev, pager, next"
        :total="total"
        :current-page="query.page"
        :page-size="query.page_size"
        :page-sizes="[10, 20, 50, 100]"
        @current-change="onPage"
        @size-change="onSize"
      />
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
  gap: 10px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.page-title {
  font-size: 18px;
  font-weight: 600;
  margin-right: auto;
}
.muted {
  color: #909399;
  font-size: 12px;
}
.code {
  margin-left: 6px;
}
.pager {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
