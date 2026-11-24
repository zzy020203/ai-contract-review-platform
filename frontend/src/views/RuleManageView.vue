<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import AppHeader from '../components/AppHeader.vue'
import { ruleApi, type RuleItem } from '../api/rule'

const rules = ref<RuleItem[]>([])
const loading = ref(false)
const keyword = ref('')
const statusFilter = ref<number | undefined>(undefined)

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return rules.value.filter((r) => {
    const hitKw = !kw || [r.code, r.name, r.group_name, r.content]
      .some((v) => (v ?? '').toLowerCase().includes(kw))
    const hitStatus = statusFilter.value == null || r.status === statusFilter.value
    return hitKw && hitStatus
  })
})

async function load() {
  loading.value = true
  try {
    const { data } = await ruleApi.list()
    rules.value = data.data
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

// ---------- 新增 / 编辑 ----------
const dialogVisible = ref(false)
const saving = ref(false)
const editing = ref<RuleItem | null>(null)
const formRef = ref<FormInstance>()
const form = reactive({ code: '', name: '', group_name: '', content: '', status: 1 })
const formRules: FormRules = {
  code: [{ required: true, message: '请输入规则编号', trigger: 'blur' }],
  name: [{ required: true, message: '请输入规则名称', trigger: 'blur' }],
  content: [{ required: true, message: '请输入规则内容', trigger: 'blur' }],
}

function openCreate() {
  editing.value = null
  Object.assign(form, { code: '', name: '', group_name: '', content: '', status: 1 })
  dialogVisible.value = true
}

function openEdit(row: RuleItem) {
  editing.value = row
  Object.assign(form, {
    code: row.code, name: row.name, group_name: row.group_name,
    content: row.content, status: row.status,
  })
  dialogVisible.value = true
}

async function submit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  saving.value = true
  try {
    const { data } = editing.value
      ? await ruleApi.update(editing.value.id, {
        name: form.name, group_name: form.group_name,
        content: form.content, status: form.status,
      })
      : await ruleApi.create({ ...form })
    dialogVisible.value = false
    notifySaved(data.data)
    await load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    saving.value = false
  }
}

function notifySaved(rule: RuleItem) {
  if (rule.vector_status.startsWith('failed')) {
    ElMessage.warning(`规则已保存，但向量化失败：${rule.vector_status.slice(7)}`)
  } else {
    ElMessage.success('规则已保存并完成向量化')
  }
}

async function toggleStatus(row: RuleItem) {
  const next = row.status === 1 ? 0 : 1
  try {
    const { data } = await ruleApi.update(row.id, { status: next })
    row.status = data.data.status
    ElMessage.success(next === 1 ? '规则已启用' : '规则已停用')
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

async function remove(row: RuleItem) {
  try {
    await ElMessageBox.confirm(
      `确定删除规则「${row.code} ${row.name}」？删除后其向量索引也会移除。`,
      '删除规则', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await ruleApi.remove(row.id)
    ElMessage.success('规则已删除')
    await load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
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

onMounted(load)
</script>

<template>
  <el-container class="layout" direction="vertical">
    <AppHeader />
    <el-main>
      <div class="toolbar">
        <span class="page-title">规则管理</span>
        <el-input v-model="keyword" placeholder="编号 / 名称 / 分组 / 内容" clearable style="width: 240px" />
        <el-select v-model="statusFilter" placeholder="全部状态" clearable style="width: 130px">
          <el-option label="启用" :value="1" />
          <el-option label="停用" :value="0" />
        </el-select>
        <el-button @click="load">刷新</el-button>
        <el-button type="primary" @click="openCreate">新增规则</el-button>
      </div>

      <el-alert
        type="info" :closable="false" show-icon class="tip"
        title="规则内容变更会自动升版并重新向量化；停用规则不会参与风险识别的 RAG 检索。"
      />

      <el-table v-loading="loading" :data="filtered" border empty-text="暂无规则">
        <el-table-column prop="code" label="编号" width="100" />
        <el-table-column prop="name" label="规则名称" min-width="160" show-overflow-tooltip />
        <el-table-column prop="group_name" label="分组" width="130" show-overflow-tooltip />
        <el-table-column prop="version" label="版本" width="80" align="center">
          <template #default="{ row }">v{{ row.version }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="row.status === 1 ? 'success' : 'info'" size="small">
              {{ row.status === 1 ? '启用' : '停用' }}
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
        <el-table-column prop="content" label="规则内容" min-width="320" show-overflow-tooltip />
        <el-table-column label="操作" width="190" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="primary" @click="toggleStatus(row)">
              {{ row.status === 1 ? '停用' : '启用' }}
            </el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-dialog
        v-model="dialogVisible" :title="editing ? '编辑规则' : '新增规则'"
        width="680px" destroy-on-close
      >
        <el-form ref="formRef" :model="form" :rules="formRules" label-width="90px">
          <el-form-item label="规则编号" prop="code">
            <el-input v-model="form.code" :disabled="Boolean(editing)" placeholder="如 R-009" />
          </el-form-item>
          <el-form-item label="规则名称" prop="name">
            <el-input v-model="form.name" placeholder="如 付款条款完整性" />
          </el-form-item>
          <el-form-item label="分组">
            <el-input v-model="form.group_name" placeholder="如 价格与付款" />
          </el-form-item>
          <el-form-item label="规则内容" prop="content">
            <el-input
              v-model="form.content" type="textarea" :rows="7"
              placeholder="填写审查口径；内容变更将自动升版并重新入库"
            />
          </el-form-item>
          <el-form-item label="状态">
            <el-switch
              v-model="form.status" :active-value="1" :inactive-value="0"
              active-text="启用" inactive-text="停用"
            />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
        </template>
      </el-dialog>
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
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.page-title {
  font-size: 18px;
  font-weight: 600;
  margin-right: auto;
}
.tip {
  margin-bottom: 12px;
}
</style>
