<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { UploadRawFile } from 'element-plus'
import AppHeader from '../components/AppHeader.vue'
import { knowledgeApi, type KnowledgeDoc, type KnowledgeHit } from '../api/knowledge'

const activeTab = ref<'history' | 'template'>('history')
const docs = ref<KnowledgeDoc[]>([])
const loading = ref(false)
const uploading = ref(false)

async function loadDocs() {
  loading.value = true
  try {
    const { data } = await knowledgeApi.list(activeTab.value)
    docs.value = data.data
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    loading.value = false
  }
}

function errMsg(e: unknown) {
  const resp = (e as { response?: { data?: { detail?: string } }; message?: string })
  return resp?.response?.data?.detail ?? resp?.message ?? '操作失败'
}

async function beforeUpload(file: UploadRawFile) {
  const suffix = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
  if (!['.pdf', '.docx', '.txt'].includes(suffix)) {
    ElMessage.error('仅支持 PDF / DOCX / TXT 格式')
    return false
  }
  if (file.size > 20 * 1024 * 1024) {
    ElMessage.error('文件不能超过 20MB')
    return false
  }

  uploading.value = true
  try {
    const { data } = await knowledgeApi.upload(file, activeTab.value)
    const doc = data.data
    if (doc.vector_status.startsWith('failed')) {
      ElMessage.warning(`上传完成，但向量化失败：${doc.vector_status.slice(7)}`)
    } else {
      ElMessage.success(`上传成功，已生成 ${doc.chunk_count} 个向量片段`)
    }
    await loadDocs()
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    uploading.value = false
  }
  return false // 阻止 el-upload 默认上传行为
}

function vectorType(status: string): 'success' | 'warning' | 'danger' {
  if (status === 'done') return 'success'
  if (status === 'pending') return 'warning'
  return 'danger'
}

function vectorText(status: string) {
  if (status === 'done') return '已入库'
  if (status === 'pending') return '待向量化'
  return '失败'
}

// ---------- 相似检索验证 ----------
const searchQ = ref('')
const searchLib = ref<'rule' | 'history' | 'template'>('rule')
const searchTopK = ref(3)
const searching = ref(false)
const searched = ref(false)
const hits = ref<KnowledgeHit[]>([])

async function doSearch() {
  const q = searchQ.value.trim()
  if (!q) {
    ElMessage.warning('请输入要检索的条款或问题')
    return
  }
  searching.value = true
  try {
    const { data } = await knowledgeApi.search(q, searchLib.value, searchTopK.value)
    hits.value = data.data.hits
    searched.value = true
    if (!hits.value.length) ElMessage.info('没有命中结果')
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    searching.value = false
  }
}

function hitSource(row: KnowledgeHit) {
  if (row.code) return `规则 ${row.code} · ${row.name ?? ''} · v${row.version ?? 1}`
  return row.title ?? '知识库文档'
}

function fmtTime(value: string) {
  return value ? new Date(value).toLocaleString() : ''
}

onMounted(loadDocs)
</script>

<template>
  <el-container class="layout" direction="vertical">
    <AppHeader />
    <el-main>
      <div class="toolbar">
        <span class="page-title">知识库</span>
        <span class="hint">支持 PDF / DOCX / TXT，上传后自动按段落切分并向量化入库</span>
        <el-upload
          :show-file-list="false" :before-upload="beforeUpload"
          accept=".pdf,.docx,.txt" :disabled="uploading"
        >
          <el-button type="primary" :loading="uploading">
            {{ activeTab === 'history' ? '上传历史合同' : '上传标准模板' }}
          </el-button>
        </el-upload>
      </div>

      <el-tabs v-model="activeTab" @tab-change="loadDocs">
        <el-tab-pane label="历史合同库" name="history" />
        <el-tab-pane label="标准模板库" name="template" />
      </el-tabs>

      <el-table v-loading="loading" :data="docs" border empty-text="该库暂无文档，请先上传">
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="title" label="文档标题" min-width="320" show-overflow-tooltip />
        <el-table-column label="库类型" width="120" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">
              {{ row.lib_type === 'history' ? '历史合同' : row.lib_type }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="向量化" width="110" align="center">
          <template #default="{ row }">
            <el-tooltip :content="row.vector_status" placement="top">
              <el-tag :type="vectorType(row.vector_status)" size="small" effect="plain">
                {{ vectorText(row.vector_status) }}
              </el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="上传时间" width="180">
          <template #default="{ row }">{{ fmtTime(row.create_time) }}</template>
        </el-table-column>
      </el-table>

      <el-divider content-position="left">相似检索验证</el-divider>

      <div class="search-bar">
        <el-input
          v-model="searchQ" placeholder="输入条款文本或问题，验证向量检索效果"
          clearable style="width: 360px" @keyup.enter="doSearch"
        />
        <el-select v-model="searchLib" style="width: 140px">
          <el-option label="规则库" value="rule" />
          <el-option label="历史合同" value="history" />
          <el-option label="标准模板" value="template" />
        </el-select>
        <el-select v-model="searchTopK" style="width: 110px">
          <el-option label="Top 3" :value="3" />
          <el-option label="Top 5" :value="5" />
          <el-option label="Top 10" :value="10" />
        </el-select>
        <el-button type="primary" :loading="searching" @click="doSearch">检索</el-button>
      </div>

      <el-table
        v-if="hits.length" :data="hits" border class="hit-table"
        empty-text="无命中结果"
      >
        <el-table-column label="相似度" width="100" align="center">
          <template #default="{ row }">
            <el-tag type="success" size="small">{{ row.score.toFixed(4) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="240" show-overflow-tooltip>
          <template #default="{ row }">{{ hitSource(row) }}</template>
        </el-table-column>
        <el-table-column prop="content" label="命中内容" min-width="400" show-overflow-tooltip />
      </el-table>
      <el-empty v-else-if="searched && !searching" description="没有命中结果，可尝试调整检索内容或库类型" />
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
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.page-title {
  font-size: 18px;
  font-weight: 600;
}
.hint {
  color: #909399;
  font-size: 13px;
  margin-right: auto;
}
.search-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.hit-table {
  margin-top: 4px;
}
</style>
