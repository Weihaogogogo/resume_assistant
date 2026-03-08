<template>
  <div class="admin-page">
    <header class="admin-header">
      <div class="header-content">
        <h1 class="admin-title">管理后台</h1>
      </div>
    </header>

    <main class="admin-container">
      <div class="admin-card">
        <div class="section">
          <h2>新注册用户看板</h2>
          <div class="refresh-row">
            <span>新增用户总数：{{ growthTotal }}</span>
            <div class="refresh-actions">
              <button @click="exportGrowthCsv" class="refresh-btn">
                导出数据
              </button>
              <input v-model="rangeStart" type="date" class="status-filter date-input" />
              <span class="date-sep">至</span>
              <input v-model="rangeEnd" type="date" class="status-filter date-input" />
              <button @click="applyDateRange" class="refresh-btn">应用</button>
            </div>
          </div>
          <div v-if="growthLoading" class="chart-loading">加载中...</div>
          <div v-else class="chart-card">
            <div class="chart-note">{{ chartGranularityText }}</div>
            <div class="chart-layout">
              <div class="y-axis">
                <span v-for="tick in yTicks" :key="`y-${tick}`">{{ tick }}</span>
              </div>
              <div class="plot-area">
                <div class="grid-lines">
                  <span v-for="tick in yTicks" :key="`g-${tick}`"></span>
                </div>
                <div class="bars">
                  <div
                    v-for="point in growthDisplayPoints"
                    :key="point.key"
                    class="bar-item"
                    :title="point.tooltip"
                  >
                    <div class="bar-wrap">
                      <div class="bar-tooltip">{{ point.count }}</div>
                      <div
                        class="bar"
                        :style="{ height: `${maxGrowthCount ? (point.count / maxGrowthCount) * 100 : 0}%` }"
                      ></div>
                    </div>
                    <div class="bar-label">{{ point.label }}</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 创建邀请码 -->
        <div class="section">
          <h2>创建邀请码</h2>
          <div class="create-form">
            <input v-model.number="count" type="number" min="1" max="20" placeholder="数量" class="count-input" />
            <button @click="createCodes" :disabled="loading" class="create-btn">
              {{ loading ? '创建中...' : `生成 ${count || 1} 个邀请码` }}
            </button>
          </div>
        </div>

        <!-- 邀请码列表 -->
        <div class="section">
          <h2>邀请码列表</h2>
          <div class="refresh-row">
            <span>共 {{ filteredCodes.length }} / {{ codes.length }} 个邀请码</span>
            <div class="refresh-actions">
              <select v-model="statusFilter" class="status-filter">
                <option value="all">全部</option>
                <option value="unused">未使用</option>
                <option value="used">已使用</option>
              </select>
              <button @click="copyCurrentPageCodes" class="refresh-btn">
                复制本页
              </button>
              <button @click="fetchCodes" class="refresh-btn">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="23 4 23 10 17 10"></polyline>
                  <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
                </svg>
                刷新
              </button>
            </div>
          </div>
          <div class="table-container">
            <table class="code-table">
              <thead>
                <tr>
                  <th>邀请码</th>
                  <th>状态</th>
                  <th>创建时间</th>
                  <th>使用时间</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="code in paginatedCodes" :key="code.code">
                  <td class="code-cell">{{ code.code }}</td>
                  <td>
                    <span :class="['status', code.is_used ? 'used' : 'unused']">
                      {{ code.is_used ? '已使用' : '未使用' }}
                    </span>
                  </td>
                  <td>{{ formatTime(code.created_at) }}</td>
                  <td>{{ formatTime(code.used_at) }}</td>
                </tr>
                <tr v-if="paginatedCodes.length === 0">
                  <td colspan="4" class="empty-row">暂无邀请码</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="pagination-row">
            <button @click="prevPage" :disabled="page <= 1" class="refresh-btn">上一页</button>
            <span>第 {{ page }} / {{ totalPages }} 页</span>
            <button @click="nextPage" :disabled="page >= totalPages" class="refresh-btn">下一页</button>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<script>
export default {
  name: 'Admin',
  data() {
    return {
      count: 5,
      loading: false,
      codes: [],
      statusFilter: 'all',
      page: 1,
      pageSize: 10,
      growthLoading: false,
      rangeStart: '',
      rangeEnd: '',
      growthPoints: [],
      growthTotal: 0
    }
  },
  computed: {
    filteredCodes() {
      if (this.statusFilter === 'used') return this.codes.filter(c => c.is_used)
      if (this.statusFilter === 'unused') return this.codes.filter(c => !c.is_used)
      return this.codes
    },
    totalPages() {
      return Math.max(1, Math.ceil(this.filteredCodes.length / this.pageSize))
    },
    paginatedCodes() {
      const start = (this.page - 1) * this.pageSize
      return this.filteredCodes.slice(start, start + this.pageSize)
    },
    maxGrowthCount() {
      return this.growthDisplayPoints.reduce((m, p) => Math.max(m, p.count || 0), 0)
    },
    growthDisplayPoints() {
      // 日期范围超过14天按周聚合，避免X轴拥挤
      if (this.growthRangeDays <= 14) {
        return (this.growthPoints || []).map(p => ({
          key: p.date,
          count: p.count || 0,
          label: this.formatShortDate(p.date),
          tooltip: `${p.date}: ${p.count || 0}`
        }))
      }

      const points = this.growthPoints || []
      const grouped = []
      for (let i = 0; i < points.length; i += 7) {
        const chunk = points.slice(i, i + 7)
        if (!chunk.length) continue
        const start = chunk[0].date
        const end = chunk[chunk.length - 1].date
        const total = chunk.reduce((sum, it) => sum + (it.count || 0), 0)
        grouped.push({
          key: `${start}_${end}`,
          count: total,
          label: `${this.formatShortDate(start)}-${this.formatShortDate(end)}`,
          tooltip: `${start} ~ ${end}: ${total}`
        })
      }
      return grouped
    },
    chartGranularityText() {
      return this.growthRangeDays <= 14 ? '按天展示' : '按周聚合展示（导出仍为每日明细）'
    },
    growthRangeDays() {
      if (!this.rangeStart || !this.rangeEnd) return this.growthPoints.length || 0
      const s = new Date(this.rangeStart)
      const e = new Date(this.rangeEnd)
      return Math.floor((e - s) / (24 * 3600 * 1000)) + 1
    },
    yTicks() {
      const max = this.maxGrowthCount
      if (!max) return [4, 3, 2, 1, 0]
      const step = Math.max(1, Math.ceil(max / 4))
      return [step * 4, step * 3, step * 2, step, 0]
    }
  },
  watch: {
    statusFilter() {
      this.page = 1
    }
  },
  mounted() {
    this.initDefaultDateRange()
    this.fetchCodes()
    this.fetchGrowth()
  },
  methods: {
    initDefaultDateRange() {
      const end = new Date()
      const start = new Date(end)
      start.setDate(end.getDate() - 6) // 默认最近7天（含今天）
      this.rangeStart = this.formatIsoDate(start)
      this.rangeEnd = this.formatIsoDate(end)
    },
    formatIsoDate(d) {
      const y = d.getFullYear()
      const m = String(d.getMonth() + 1).padStart(2, '0')
      const day = String(d.getDate()).padStart(2, '0')
      return `${y}-${m}-${day}`
    },
    applyDateRange() {
      if (!this.rangeStart || !this.rangeEnd) {
        alert('请选择开始和结束日期')
        return
      }
      if (new Date(this.rangeStart) > new Date(this.rangeEnd)) {
        alert('开始日期不能晚于结束日期')
        return
      }
      this.fetchGrowth()
    },
    async fetchCodes() {
      try {
        const token = localStorage.getItem('access_token')
        const response = await fetch('/auth/invite-codes', {
          method: 'GET',
          headers: {
            'Authorization': `Bearer ${token}`
          }
        })
        if (response.ok) {
          this.codes = await response.json()
          if (this.page > this.totalPages) this.page = this.totalPages
        } else {
          alert('获取邀请码列表失败')
        }
      } catch (error) {
        console.error('获取邀请码列表失败:', error)
        alert('获取邀请码列表失败')
      }
    },

    async createCodes() {
      this.loading = true
      try {
        const token = localStorage.getItem('access_token')
        const response = await fetch('/auth/invite-codes', {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ count: this.count || 5 })
        })
        if (response.ok) {
          const newCodes = await response.json()
          const createdCount = Array.isArray(newCodes) ? newCodes.length : 1
          await this.fetchCodes()
          alert(`成功创建 ${createdCount} 个邀请码`)
        } else {
          const error = await response.json()
          alert(error.detail || '创建失败')
        }
      } catch (error) {
        console.error('创建邀请码失败:', error)
        alert('创建邀请码失败')
      } finally {
        this.loading = false
      }
    },
    async fetchGrowth() {
      this.growthLoading = true
      try {
        const token = localStorage.getItem('access_token')
        const params = new URLSearchParams({
          start_date: this.rangeStart,
          end_date: this.rangeEnd
        })
        const response = await fetch(`/auth/user-growth?${params.toString()}`, {
          method: 'GET',
          headers: {
            'Authorization': `Bearer ${token}`
          }
        })
        if (response.ok) {
          const data = await response.json()
          this.growthPoints = data.points || []
          this.growthTotal = data.total_new_users || 0
        }
      } catch (error) {
        console.error('获取注册增长数据失败:', error)
      } finally {
        this.growthLoading = false
      }
    },
    prevPage() {
      if (this.page > 1) this.page -= 1
    },
    nextPage() {
      if (this.page < this.totalPages) this.page += 1
    },
    async copyCurrentPageCodes() {
      const text = this.paginatedCodes.map(c => c.code).join(',')
      if (!text) {
        alert('当前页没有可复制的邀请码')
        return
      }
      try {
        await navigator.clipboard.writeText(text)
        alert('已复制当前页邀请码')
      } catch (e) {
        console.error('复制失败:', e)
        alert('复制失败，请检查浏览器权限')
      }
    },
    formatShortDate(dateStr) {
      if (!dateStr) return ''
      const d = new Date(dateStr)
      return `${d.getMonth() + 1}/${d.getDate()}`
    },
    exportGrowthCsv() {
      const rows = [['date', 'new_users']]
      ;(this.growthPoints || []).forEach(p => {
        rows.push([p.date, String(p.count || 0)])
      })
      const csv = rows.map(r => r.join(',')).join('\n')
      const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8;' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `user_growth_${this.rangeStart}_${this.rangeEnd}.csv`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    },

    formatTime(timeStr) {
      if (!timeStr) return '-'
      const date = new Date(timeStr)
      return date.toLocaleString('zh-CN')
    }
  }
}
</script>

<style scoped>
/* 页面布局 */
.admin-page {
  min-height: 100vh;
  background-color: rgb(254, 253, 251);
  display: flex;
  flex-direction: column;
}

/* 顶部导航 */
.admin-header {
  background-color: rgb(249, 245, 242);
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
  padding: 0;
}

.header-content {
  max-width: 800px;
  margin: 0 auto;
  padding: 0.7rem 1.5rem;
  display: flex;
  align-items: center;
  justify-content: flex-start;
}

.admin-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
  letter-spacing: -0.02em;
}

/* 主容器 */
.admin-container {
  flex: 1;
  display: flex;
  justify-content: center;
  padding: 2rem 1.5rem;
}

/* 卡片样式 */
.admin-card {
  background: white;
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-md);
  padding: 1.5rem;
  width: 100%;
  max-width: 700px;
}

.section {
  margin-bottom: 1.5rem;
}

.section:last-child {
  margin-bottom: 0;
}

h2 {
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 1rem 0;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid var(--border-color);
}

/* 创建表单 */
.create-form {
  display: flex;
  gap: 0.75rem;
  align-items: center;
  flex-wrap: wrap;
}

.count-input {
  width: 88px;
  padding: 0.5rem 0.65rem;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  font-size: 0.9rem;
  background: white;
  transition: border-color 0.2s;
}

.count-input:focus {
  outline: none;
  border-color: var(--primary-color);
}

.create-btn {
  flex: none;
  min-width: 180px;
  padding: 0.5rem 0.95rem;
  background-color: #ffffff;
  color: #5a4a3a;
  border: 1px solid #d8cec2;
  border-radius: var(--radius-md);
  font-size: 0.88rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.create-btn:hover:not(:disabled) {
  background-color: #f7f4f0;
  border-color: #cbbcae;
  color: #3f3428;
}

.create-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

/* 刷新行 */
.refresh-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
  color: var(--text-secondary);
  font-size: 0.9rem;
}

.refresh-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.status-filter {
  padding: 0.38rem 0.5rem;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  background: white;
  color: var(--text-secondary);
}

.date-input {
  min-width: 138px;
}

.date-sep {
  color: var(--text-secondary);
  font-size: 0.85rem;
}

.refresh-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 0.4rem 0.8rem;
  background: white;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  font-size: 0.85rem;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s;
}

.refresh-btn:hover {
  background: var(--accent-color);
  color: var(--text-primary);
}

.empty-row {
  text-align: center;
  color: var(--text-secondary);
}

.pagination-row {
  margin-top: 0.8rem;
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 0.6rem;
  color: var(--text-secondary);
  font-size: 0.85rem;
}

.chart-loading {
  color: var(--text-secondary);
  font-size: 0.9rem;
}

.chart-card {
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 0.75rem;
  background: white;
}

.chart-note {
  font-size: 0.8rem;
  color: var(--text-secondary);
  margin-bottom: 0.5rem;
}

.chart-layout {
  display: flex;
  gap: 0.6rem;
}

.y-axis {
  width: 34px;
  height: 240px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  align-items: flex-end;
  font-size: 0.72rem;
  color: var(--text-secondary);
}

.plot-area {
  position: relative;
  flex: 1;
  height: 240px;
  border-left: 1px solid #ddd6cd;
  border-bottom: 1px solid #ddd6cd;
  padding: 0 0.25rem 0.1rem;
}

.grid-lines {
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  bottom: 24px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  pointer-events: none;
}

.grid-lines span {
  border-top: 1px dashed #eee6dc;
}

.bars {
  position: absolute;
  left: 4px;
  right: 4px;
  bottom: 0;
  top: 0;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(12px, 1fr));
  gap: 0.25rem;
  align-items: end;
}

.bar-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.15rem;
  z-index: 1;
}

.bar-wrap {
  width: 100%;
  height: 210px;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  background: transparent;
  position: relative;
}

.bar {
  width: 78%;
  background: #ea7a00;
  border-radius: 0;
  min-height: 0;
}

.bar-tooltip {
  position: absolute;
  bottom: 100%;
  transform: translateY(-4px);
  font-size: 0.68rem;
  color: #fff;
  background: rgba(48, 48, 48, 0.9);
  padding: 2px 5px;
  border-radius: 4px;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.15s ease;
  white-space: nowrap;
}

.bar-item:hover .bar-tooltip {
  opacity: 1;
}

.bar-label {
  font-size: 0.66rem;
  color: var(--text-secondary);
}

/* 表格容器 */
.table-container {
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.code-table {
  width: 100%;
  border-collapse: collapse;
  background: white;
}

.code-table th,
.code-table td {
  padding: 0.7rem 1rem;
  text-align: left;
  border-bottom: 1px solid var(--border-color);
}

.code-table th {
  background: rgb(249, 245, 242);
  font-weight: 600;
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.code-table tr:last-child td {
  border-bottom: none;
}

.code-table tr:hover td {
  background: rgb(254, 253, 251);
}

.code-cell {
  font-family: 'SF Mono', 'Fira Code', 'Courier New', monospace;
  font-size: 0.9rem;
  letter-spacing: 0.5px;
  color: var(--text-primary);
}

.status {
  display: inline-block;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.8rem;
  font-weight: 500;
}

.status.unused {
  background: #ecfccb;
  color: #3f6212;
}

.status.used {
  background: #fef2f2;
  color: #991b1b;
}

/* 响应式 */
@media (max-width: 600px) {
  .header-content {
    flex-direction: column;
    gap: 0.5rem;
    align-items: flex-start;
  }

  .create-form {
    flex-direction: row;
    align-items: center;
  }

  .count-input {
    width: 84px;
  }

  .refresh-row {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.6rem;
  }

  .refresh-actions {
    width: 100%;
    flex-wrap: wrap;
  }

  .code-table th:nth-child(3),
  .code-table td:nth-child(3),
  .code-table th:nth-child(4),
  .code-table td:nth-child(4) {
    display: none;
  }

  .chart-layout {
    gap: 0.4rem;
  }

  .y-axis {
    width: 26px;
    font-size: 0.66rem;
  }
}
</style>
