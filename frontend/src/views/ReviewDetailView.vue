<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { reviewApi, type FeedbackAction, type Risk, type TaskDetail } from '../api/review'
import { useUserStore } from '../stores/user'
import AppHeader from '../components/AppHeader.vue'

const route = useRoute()
const store = useUserStore()
const taskId = Number(route.params.id)

const detail = ref<TaskDetail | null>(null)
const loading = ref(false)
const submitting = ref(false)

// 待提交的处置动作（riskId → 动作）
const actionsMap = reactive<Record<number, FeedbackAction>>({})
// 编辑对话框
const editDialog = ref(false)
const editTarget = ref<Risk | null>(null)
const editText = ref('')

const LEVEL_MAP: Record<string, { text: string; type: 'danger' | 'warning' | 'info' }> = {
  high: { text: '高风险', type: 'danger' },
  medium: { text: '中风险', type: 'warning' },
  low: { text: '低风险', type: 'info' },
}
const HANDLE_MAP: Record<string, string> = {
  pending: '待处置', accepted: '已采纳', rejected: '已拒绝', edited: '已编辑',
}
const ACTION_TEXT: Record<'accept' | 'reject' | 'edit', string> = {
  accept: '接受', reject: '拒绝', edit: '编辑',
}

const auditable = computed(
  () => detail.value?.task.status === 'pending_audit' && store.hasPerm('review:audit'),
)
const actionCount = computed(() => Object.keys(actionsMap).length)
const pendingCount = computed(
  () => detail.value?.risks.filter((r) => r.handle_status === 'pending').length ?? 0,
)
const levelCount = computed(() => {
  const c = { high: 0, medium: 0, low: 0 }
  detail.value?.risks.forEach((r) => { c[r.level] += 1 })
  return c
})
// 条款 → 最高风险等级（左侧条款树着色）
const clauseLevel = computed(() => {
  const m: Record<number, string> = {}
  const order = ['low', 'medium', 'high']
  detail.value?.risks.forEach((r) => {
    if (r.clause_id == null) return
    const cur = m[r.clause_id]
    if (!cur || order.indexOf(r.level) > order.indexOf(cur)) m[r.clause_id] = r.level
  })
  return m
})

async function load() {
  loading.value = true
  try {
    const { data } = await reviewApi.detail(taskId)
    detail.value = data.data
  } finally {
    loading.value = false
  }
}

function setAction(risk: Risk, action: 'accept' | 'reject') {
  if (actionsMap[risk.id]?.action === action) {
    delete actionsMap[risk.id] // 再次点击取消
    return
  }
  actionsMap[risk.id] = {
    risk_id: risk.id,
    action,
    ...(risk.suggestion ? { suggestion_id: risk.suggestion.id } : {}),
  }
}

function openEdit(risk: Risk) {
  editTarget.value = risk
  editText.value = risk.suggestion?.suggest_text ?? ''
  editDialog.value = true
}

function confirmEdit() {
  if (!editText.value.trim()) {
    ElMessage.warning('请填写修改后的条款文本')
    return
  }
  const risk = editTarget.value!
  actionsMap[risk.id] = {
    risk_id: risk.id,
    action: 'edit',
    edited_text: editText.value.trim(),
    ...(risk.suggestion ? { suggestion_id: risk.suggestion.id } : {}),
  }
  editDialog.value = false
}

async function submit() {
  if (!actionCount.value) {
    ElMessage.warning('请先对风险项进行处置（接受/拒绝/编辑）')
    return
  }
  submitting.value = true
  try {
    await reviewApi.feedback(taskId, Object.values(actionsMap))
    ElMessage.success('复核意见已提交，工作流继续生成报告')
    Object.keys(actionsMap).forEach((k) => delete actionsMap[Number(k)])
    // 轮询等待报告生成
    for (let i = 0; i < 40; i++) {
      await new Promise((r) => setTimeout(r, 3000))
      await load()
      const st = detail.value?.task.status
      if (st === 'done' || st === 'failed') break
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? '提交失败')
    await load()
  } finally {
    submitting.value = false
  }
}

function actionOf(risk: Risk) {
  return actionsMap[risk.id]?.action
}

function downloadReport() {
  window.open(reviewApi.exportUrl(taskId), '_blank')
}

onMounted(load)
</script>

<template>
  <el-container class="layout" direction="vertical" v-loading="loading">
    <AppHeader />

    <el-main v-if="detail">
      <!-- 概要栏 -->
      <div class="summary">
        <span class="contract">{{ detail.task.contract_name }}</span>
        <el-tag :type="detail.task.status === 'done' ? 'success' : detail.task.status === 'failed' ? 'danger' : 'warning'">
          {{ detail.task.status }}
        </el-tag>
        <el-tag type="danger" size="small">高 {{ levelCount.high }}</el-tag>
        <el-tag type="warning" size="small">中 {{ levelCount.medium }}</el-tag>
        <el-tag type="info" size="small">低 {{ levelCount.low }}</el-tag>
        <el-button
          v-if="detail.task.status === 'done'"
          type="success" size="small"
          @click="downloadReport"
        >下载报告</el-button>
      </div>

      <div class="panels">
        <!-- 左：条款树 -->
        <div class="clause-panel">
          <h3>条款（{{ detail.clauses.length }}）</h3>
          <el-collapse>
            <el-collapse-item v-for="c in detail.clauses" :key="c.id" :name="c.id">
              <template #title>
                <span class="clause-title" :class="'lv-' + (clauseLevel[c.id] ?? 'none')">
                  [{{ c.clause_no }}] {{ c.title || '（无标题）' }}
                  <el-tag v-if="c.clause_type" size="small" type="info" effect="plain">{{ c.clause_type }}</el-tag>
                </span>
              </template>
              <pre class="clause-content">{{ c.content }}</pre>
            </el-collapse-item>
          </el-collapse>
        </div>

        <!-- 右：风险清单 -->
        <div class="risk-panel">
          <h3>风险与建议（{{ detail.risks.length }}）</h3>
          <el-empty v-if="!detail.risks.length" description="未识别出风险" />
          <div v-for="r in detail.risks" :key="r.id" class="risk-card" :class="'border-' + r.level">
            <div class="risk-head">
              <el-tag :type="LEVEL_MAP[r.level].type" size="small">{{ LEVEL_MAP[r.level].text }}</el-tag>
              <span class="risk-type">{{ r.risk_type }}</span>
              <span class="evidence" v-if="r.evidence">依据 {{ r.evidence }}</span>
              <el-tag v-if="r.handle_status !== 'pending'" size="small" effect="plain" type="success">
                {{ HANDLE_MAP[r.handle_status] ?? r.handle_status }}
              </el-tag>
              <el-tag v-if="actionOf(r)" size="small" type="primary">
                待提交：{{ actionOf(r) ? ACTION_TEXT[actionOf(r)!] : '' }}
              </el-tag>
            </div>
            <div class="risk-desc">{{ r.description }}</div>
            <div v-if="r.suggestion" class="suggestion">
              <div class="sug-title">AI 修改建议（引用 {{ r.suggestion.reference || '-' }}）</div>
              <pre class="sug-text">{{ r.suggestion.suggest_text }}</pre>
              <div class="sug-reason">理由：{{ r.suggestion.reason }}</div>
            </div>
            <div v-if="auditable && r.handle_status === 'pending'" class="ops">
              <el-button
                v-if="r.suggestion" size="small" type="success"
                :plain="actionOf(r) !== 'accept'" @click="setAction(r, 'accept')"
              >接受建议</el-button>
              <el-button
                size="small" type="danger"
                :plain="actionOf(r) !== 'reject'" @click="setAction(r, 'reject')"
              >拒绝</el-button>
              <el-button
                size="small" type="primary"
                :plain="actionOf(r) !== 'edit'" @click="openEdit(r)"
              >编辑条款</el-button>
            </div>
          </div>
        </div>
      </div>

      <!-- 提交栏 -->
      <div v-if="auditable" class="submit-bar">
        <span>已处置 {{ actionCount }} / {{ pendingCount }} 项</span>
        <el-button type="primary" :loading="submitting" :disabled="!actionCount" @click="submit">
          提交复核并生成报告
        </el-button>
      </div>
    </el-main>

    <!-- 编辑对话框 -->
    <el-dialog v-model="editDialog" title="编辑条款文本" width="640px">
      <el-input v-model="editText" type="textarea" :rows="10" />
      <template #footer>
        <el-button @click="editDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmEdit">确定</el-button>
      </template>
    </el-dialog>
  </el-container>
</template>

<style scoped>
.layout {
  min-height: 100vh;
}
.summary {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}
.contract {
  font-size: 16px;
  font-weight: 600;
}
.panels {
  display: grid;
  grid-template-columns: 5fr 7fr;
  gap: 16px;
  align-items: start;
}
.clause-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
}
.lv-high {
  border-left: 3px solid #f56c6c;
  padding-left: 8px;
}
.lv-medium {
  border-left: 3px solid #e6a23c;
  padding-left: 8px;
}
.lv-low {
  border-left: 3px solid #909399;
  padding-left: 8px;
}
.clause-content {
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  font-family: inherit;
  color: #444;
}
.risk-card {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 12px;
  margin-bottom: 12px;
  background: #fff;
}
.border-high {
  border-left: 4px solid #f56c6c;
}
.border-medium {
  border-left: 4px solid #e6a23c;
}
.border-low {
  border-left: 4px solid #909399;
}
.risk-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.risk-type {
  font-weight: 600;
}
.evidence {
  color: #909399;
  font-size: 12px;
}
.risk-desc {
  color: #333;
  line-height: 1.6;
}
.suggestion {
  margin-top: 10px;
  background: #f0f7ff;
  border-radius: 4px;
  padding: 10px;
}
.sug-title {
  color: #409eff;
  font-size: 13px;
  margin-bottom: 6px;
}
.sug-text {
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0 0 6px;
  font-family: inherit;
}
.sug-reason {
  color: #909399;
  font-size: 12px;
}
.ops {
  margin-top: 10px;
  display: flex;
  gap: 8px;
}
.submit-bar {
  position: sticky;
  bottom: 0;
  margin-top: 16px;
  padding: 12px 16px;
  background: #fff;
  border-top: 1px solid #ebeef5;
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 16px;
}
</style>
