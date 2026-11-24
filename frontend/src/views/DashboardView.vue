<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import * as echarts from 'echarts'
import AppHeader from '../components/AppHeader.vue'
import { dashboardApi, type DashboardOverview } from '../api/dashboard'

const days = ref(14)
const loading = ref(false)
const data = ref<DashboardOverview | null>(null)

const trendRef = ref<HTMLDivElement | null>(null)
const levelRef = ref<HTMLDivElement | null>(null)
const typeRef = ref<HTMLDivElement | null>(null)
const statusRef = ref<HTMLDivElement | null>(null)

let charts: echarts.ECharts[] = []

const LEVEL_COLORS: Record<string, string> = { 高: '#f56c6c', 中: '#e6a23c', 低: '#909399' }

function setup(el: HTMLDivElement | null, option: echarts.EChartsOption) {
  if (!el) return
  const chart = echarts.getInstanceByDom(el) ?? echarts.init(el)
  chart.setOption(option, true)
  if (!charts.includes(chart)) charts.push(chart)
}

function render() {
  const d = data.value
  if (!d) return

  setup(trendRef.value, {
    tooltip: { trigger: 'axis' },
    legend: { data: ['创建任务', '完成任务'], top: 0 },
    grid: { left: 40, right: 24, top: 36, bottom: 28 },
    xAxis: { type: 'category', data: d.trend.map((t) => t.date.slice(5)) },
    yAxis: { type: 'value', minInterval: 1 },
    series: [
      { name: '创建任务', type: 'line', smooth: true, data: d.trend.map((t) => t.created), areaStyle: { opacity: 0.12 } },
      { name: '完成任务', type: 'line', smooth: true, data: d.trend.map((t) => t.completed), areaStyle: { opacity: 0.12 } },
    ],
  })

  setup(levelRef.value, {
    tooltip: { trigger: 'item', formatter: '{b}风险：{c} 项（{d}%）' },
    legend: { bottom: 0 },
    series: [{
      type: 'pie', radius: ['45%', '70%'], center: ['50%', '45%'],
      label: { formatter: '{b}\n{c}' },
      data: d.risk_levels.map((x) => ({
        name: x.name, value: x.value,
        itemStyle: { color: LEVEL_COLORS[x.name] ?? '#409eff' },
      })).filter((x) => x.value > 0),
    }],
  })

  setup(typeRef.value, {
    tooltip: { trigger: 'axis' },
    grid: { left: 110, right: 24, top: 12, bottom: 24 },
    xAxis: { type: 'value', minInterval: 1 },
    yAxis: { type: 'category', data: d.risk_types.map((x) => x.name) },
    series: [{
      type: 'bar', barMaxWidth: 16, itemStyle: { color: '#409eff' },
      data: d.risk_types.map((x) => x.value),
    }],
  })

  setup(statusRef.value, {
    tooltip: { trigger: 'item', formatter: '{b}：{c} 个（{d}%）' },
    legend: { bottom: 0 },
    series: [{
      type: 'pie', radius: '65%', center: ['50%', '45%'],
      label: { formatter: '{b}\n{c}' },
      data: d.status_distribution.filter((x) => x.value > 0),
    }],
  })
}

async function load() {
  loading.value = true
  try {
    const { data: resp } = await dashboardApi.overview(days.value)
    data.value = resp.data
  } finally {
    loading.value = false
  }
  // 等卡片布局完成后再初始化，避免容器尺寸为 0 导致图表空白
  await nextTick()
  requestAnimationFrame(() => {
    render()
    setTimeout(resize, 200)
  })
}

function resize() {
  charts.forEach((c) => c.resize())
}

onMounted(() => {
  load()
  window.addEventListener('resize', resize)
})
onUnmounted(() => {
  window.removeEventListener('resize', resize)
  charts.forEach((c) => c.dispose())
  charts = []
})
</script>

<template>
  <el-container class="layout" direction="vertical">
    <AppHeader />
    <el-main v-loading="loading">
      <div class="toolbar">
        <span class="page-title">数据看板</span>
        <el-radio-group v-model="days" @change="load">
          <el-radio-button :value="7">近 7 天</el-radio-button>
          <el-radio-button :value="14">近 14 天</el-radio-button>
          <el-radio-button :value="30">近 30 天</el-radio-button>
        </el-radio-group>
        <el-button @click="load">刷新</el-button>
      </div>

      <template v-if="data">
        <el-row :gutter="16" class="kpis">
          <el-col :span="4">
            <el-card shadow="never"><div class="kpi-label">审查任务总数</div><div class="kpi-value">{{ data.summary.total_tasks }}</div></el-card>
          </el-col>
          <el-col :span="4">
            <el-card shadow="never"><div class="kpi-label">已完成</div><div class="kpi-value green">{{ data.summary.done_tasks }}</div></el-card>
          </el-col>
          <el-col :span="4">
            <el-card shadow="never"><div class="kpi-label">待复核</div><div class="kpi-value orange">{{ data.summary.pending_audit }}</div></el-card>
          </el-col>
          <el-col :span="4">
            <el-card shadow="never"><div class="kpi-label">平均耗时（分钟）</div><div class="kpi-value">{{ data.summary.avg_duration_minutes }}</div></el-card>
          </el-col>
          <el-col :span="4">
            <el-card shadow="never"><div class="kpi-label">高风险项</div><div class="kpi-value red">{{ data.summary.high_risks }}</div></el-card>
          </el-col>
          <el-col :span="4">
            <el-card shadow="never"><div class="kpi-label">处置采纳率</div><div class="kpi-value">{{ (data.summary.accept_rate * 100).toFixed(1) }}%</div></el-card>
          </el-col>
        </el-row>

        <el-row :gutter="16">
          <el-col :span="16">
            <el-card shadow="never">
              <template #header>审查量趋势</template>
              <div ref="trendRef" class="chart" />
            </el-card>
          </el-col>
          <el-col :span="8">
            <el-card shadow="never">
              <template #header>风险等级分布</template>
              <div ref="levelRef" class="chart" />
            </el-card>
          </el-col>
        </el-row>

        <el-row :gutter="16" class="second-row">
          <el-col :span="12">
            <el-card shadow="never">
              <template #header>风险类型 TOP 10</template>
              <div ref="typeRef" class="chart" />
            </el-card>
          </el-col>
          <el-col :span="12">
            <el-card shadow="never">
              <template #header>任务状态分布</template>
              <div ref="statusRef" class="chart" />
            </el-card>
          </el-col>
        </el-row>
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
  gap: 16px;
  margin-bottom: 16px;
}
.page-title {
  font-size: 18px;
  font-weight: 600;
  margin-right: auto;
}
.kpis {
  margin-bottom: 16px;
}
.kpi-label {
  color: #909399;
  font-size: 13px;
}
.kpi-value {
  font-size: 26px;
  font-weight: 600;
  margin-top: 6px;
}
.kpi-value.green { color: #67c23a; }
.kpi-value.orange { color: #e6a23c; }
.kpi-value.red { color: #f56c6c; }
.chart {
  width: 100%;
  height: 300px;
}
.second-row {
  margin-top: 16px;
}
</style>
