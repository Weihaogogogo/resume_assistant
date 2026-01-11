<script setup>
import { ref, computed, onMounted, watch, nextTick, onUnmounted } from 'vue'

const props = defineProps({
  data: {
    type: Object,
    required: false,
    default: () => null
  },
  // 高亮模块 - 值为: 'basics', 'education', 'work_experience', 'project_experience', 'others', 'self_evaluation'
  highlightedModule: {
    type: String,
    required: false,
    default: ''
  },
  // JD数据（新增）
  jdData: {
    type: Object,
    required: false,
    default: null
  }
})

const emit = defineEmits(['open-jd-dialog', 'open-resume-edit'])

// ========== 样式控制变量 ==========
const marginVertical = ref(9)
const marginHorizontal = ref(9)
const moduleMargin = ref(1)
const lineHeight = ref(1.6)
const fontSize = ref(11)

// A4尺寸（像素，96dpi）
const PAGE_WIDTH = 794
const PAGE_HEIGHT = 1123
const MM_TO_PX = 3.78

// 计算边距的像素值
const marginTopPx = computed(() => marginVertical.value * MM_TO_PX)
const marginBottomPx = computed(() => marginVertical.value * MM_TO_PX)
const marginLeftPx = computed(() => marginHorizontal.value * MM_TO_PX)
const marginRightPx = computed(() => marginHorizontal.value * MM_TO_PX)

// 动态样式 - 设置基础字体大小（使用em单位需要父元素有font-size）
const pageStyles = computed(() => ({
  fontSize: `${fontSize.value}pt`,
  lineHeight: lineHeight.value,
  '--module-margin': `${moduleMargin.value}rem`
}))

const pagePaddingStyle = computed(() => ({
  paddingTop: `${marginTopPx.value}px`,
  paddingBottom: `${marginBottomPx.value}px`,
  paddingLeft: `${marginLeftPx.value}px`,
  paddingRight: `${marginRightPx.value}px`
}))

// ========== 分页相关 ==========
const pageCount = ref(1)
const scale = ref(1)
const observer = ref(null)
const containerRef = ref(null)
const contentRef = ref(null)
const pageRanges = ref([])

// 扁平化的所有可分页项目
const allItems = computed(() => {
  if (!props.data) return []
  const items = []
  let index = 0

  if (props.data.basics) {
    items.push({ type: 'basics', index: index++, visible: true })
  }

  if (props.data.education) {
    items.push({ type: 'education-title', index: index++, visible: true })
    props.data.education.forEach((edu, i) => {
      items.push({ type: 'education-item', dataIndex: i, index: index++, visible: true })
      // 添加论文作为独立的可分页项
      if (edu.theses?.length) {
        edu.theses.forEach((_, tIdx) => {
          items.push({ type: 'thesis-item', dataIndex: `${i}-${tIdx}`, index: index++, visible: true })
        })
      }
    })
  }

  if (props.data.work_experience) {
    items.push({ type: 'work-title', index: index++, visible: true })
    props.data.work_experience.forEach((work, i) => {
      items.push({ type: 'work-item', dataIndex: i, index: index++, visible: true })
      // 添加工作详情作为独立的可分页项
      if (work.details?.length) {
        items.push({ type: 'work-details', dataIndex: i, index: index++, visible: true })
      }
    })
  }

  if (props.data.project_experience || props.data.projects) {
    items.push({ type: 'projects-title', index: index++, visible: true })
    const projects = props.data.project_experience || props.data.projects
    projects.forEach((proj, i) => {
      items.push({ type: 'project-item', dataIndex: i, index: index++, visible: true })
      // 添加项目详情作为独立的可分页项
      if (proj.details?.length) {
        items.push({ type: 'project-details', dataIndex: i, index: index++, visible: true })
      }
    })
  }

  if (props.data.others) {
    items.push({ type: 'others-title', index: index++, visible: true })
    // 技能一行显示
    if (props.data.others.skills?.length) {
      items.push({ type: 'skill-line', index: index++, visible: true })
    }
    // 证书一行显示
    if (props.data.others.certificates?.length) {
      items.push({ type: 'cert-line', index: index++, visible: true })
    }
    // 语言一行显示
    if (props.data.others.languages?.length) {
      items.push({ type: 'lang-line', index: index++, visible: true })
    }
  }

  // 每条自我评价独立分页
  if (props.data.self_evaluation) {
    items.push({ type: 'self-eval-title', index: index++, visible: true })
    props.data.self_evaluation.forEach((_, i) => {
      items.push({ type: 'self-eval-item', dataIndex: i, index: index++, visible: true })
    })
  }

  return items
})

// 页面容器样式
const pageStyle = computed(() => ({
  width: `${PAGE_WIDTH}px`,
  height: `${PAGE_HEIGHT}px`
}))

// 预览区域容器样式
const pagesContainerStyle = computed(() => ({
  transform: `scale(${scale.value})`,
  transformOrigin: 'top center',
  width: `${PAGE_WIDTH}px`
}))

// ========== 精细分页算法 ==========
const calculatePagination = async () => {
  // 等待字体完全加载（带超时）
  try {
    const fontsPromise = document.fonts.ready
    const timeoutPromise = new Promise((_, reject) =>
      setTimeout(() => reject(new Error('fonts timeout')), 500)
    )
    await Promise.race([fontsPromise, timeoutPromise])
  } catch (e) {
    await new Promise(resolve => setTimeout(resolve, 100))
  }

  await nextTick()
  await nextTick()

  if (!props.data || !contentRef.value) {
    pageRanges.value = []
    pageCount.value = 1
    return
  }

  const container = contentRef.value
  const topMargin = marginTopPx.value
  const bottomMargin = marginBottomPx.value
  const pageContentHeight = PAGE_HEIGHT - topMargin - bottomMargin

  // 只获取直接子元素中的 pageable-item
  const children = Array.from(container.children).filter(el => {
    return el.classList.contains('pageable-item')
  })

  if (children.length === 0) {
    pageCount.value = 1
    return
  }

  // 直接累加每个元素的高度，找到最佳分页点
  const elementHeights = children.map((child, idx) => {
    return {
      idx,
      height: child.offsetHeight  // 使用 offsetHeight
    }
  })

  // 计算源内容总高度
  const sourceHeight = container.scrollHeight

  // 计算需要的页数
  const estimatedPageCount = Math.max(1, Math.ceil(sourceHeight / pageContentHeight))

  // 累积分页算法
  const ranges = []
  let currentStart = 0
  let currentHeight = 0

  for (let i = 0; i < elementHeights.length; i++) {
    const elem = elementHeights[i]

    // 检查加上这个元素是否超出页面
    // 如果当前高度 + 这个元素高度 > 可用高度，需要分页
    // 留更大余量（约120px），因为 margin collapse 可能累积，且每个页面顶部会损失更多
    // 首行没有 margin-top，所以每个新页面会多出一些可用空间
    const wouldExceed = currentHeight + elem.height > (pageContentHeight - 120)

    if (currentStart === i && estimatedPageCount === 1) {
      // 只有一页的情况，直接包含所有元素
      currentHeight += elem.height
    } else if (wouldExceed && i > 0) {
      // 保存当前页
      ranges.push({ start: currentStart, end: i })

      // 开始新页面
      currentStart = i
      currentHeight = elem.height
    } else {
      currentHeight += elem.height
    }
  }

  // 保存最后一页
  if (currentStart < elementHeights.length) {
    ranges.push({ start: currentStart, end: elementHeights.length })
  }

  // 确保至少有一页
  if (ranges.length === 0 && elementHeights.length > 0) {
    ranges.push({ start: 0, end: elementHeights.length })
  }

  pageRanges.value = ranges
  pageCount.value = ranges.length

  // 验证：测量实际渲染的页面高度，如果溢出则调整
  await nextTick()
  await nextTick()

  const verifyAndFixPagination = async () => {
    const pageContents = document.querySelectorAll('.page-content')
    if (pageContents.length === 0) return

    let adjusted = false
    const availableHeight = pageContentHeight

    pageContents.forEach((el, idx) => {
      const actualHeight = el.scrollHeight
      if (actualHeight > availableHeight + 50) {
        // 标记需要重新计算
        adjusted = true
      }
    })

    // 如果有溢出，重新计算分页，使用更小的每页高度限制
    if (adjusted) {
      const newRanges = []
      let currentStart = 0
      let currentHeight = 0

      for (let i = 0; i < elementHeights.length; i++) {
        const elem = elementHeights[i]
        const wouldExceed = currentHeight + elem.height > (availableHeight - 150)

        if (wouldExceed && i > 0) {
          newRanges.push({ start: currentStart, end: i })
          currentStart = i
          currentHeight = elem.height
        } else {
          currentHeight += elem.height
        }
      }

      if (currentStart < elementHeights.length) {
        newRanges.push({ start: currentStart, end: elementHeights.length })
      }

      if (newRanges.length > ranges.length) {
        pageRanges.value = newRanges
        pageCount.value = newRanges.length
      }
    }
  }

  // 延迟验证，确保DOM已完全渲染
  setTimeout(verifyAndFixPagination, 200)
}

// ========== 监听变化 ==========
watch([() => props.data, marginVertical, marginHorizontal, moduleMargin, lineHeight, fontSize],
  () => {
    // 增加延迟时间，确保字体变化后浏览器有足够时间重新渲染
    if (window.requestAnimationFrame) {
      window.requestAnimationFrame(() => {
        setTimeout(calculatePagination, 300)  // 增加延迟
      })
    } else {
      setTimeout(calculatePagination, 300)
    }
  }, { deep: true })

// ========== 高亮模块滚动 ==========
watch(() => props.highlightedModule, async (newModule) => {
  if (newModule && props.data) {
    await nextTick()
    // 延迟执行滚动，确保DOM已完全渲染
    setTimeout(() => {
      // 在可见的 pages-wrapper 中查找对应模块
      const pagesWrapper = document.querySelector('.pages-wrapper')
      if (pagesWrapper) {
        // 根据模块类型查找对应的section标题
        const sectionTitle = pagesWrapper.querySelector(`[data-module="${newModule}"]`)
        if (sectionTitle) {
          sectionTitle.scrollIntoView({ behavior: 'smooth', block: 'center' })
        } else {
          // 如果没找到，尝试在 preview-content 中查找
          const previewContent = document.querySelector('.preview-content')
          if (previewContent) {
            const element = previewContent.querySelector(`[data-module="${newModule}"]`)
            if (element) {
              element.scrollIntoView({ behavior: 'smooth', block: 'center' })
            }
          }
        }
      }
    }, 200)
  }
})

// 调试方法：在控制台调用 testHighlight('education') 测试高亮效果
window.testHighlight = (moduleName) => {
  const previewContent = document.querySelector('.preview-content')
  if (previewContent) {
    const element = previewContent.querySelector(`[data-module="${moduleName}"]`)
    if (element) {
      // 添加高亮类测试动画
      element.classList.add('title-highlight')
      // 测试滚动
      element.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }
}

// 测试动画的独立方法
window.testAnimation = (moduleName) => {
  const element = document.querySelector(`[data-module="${moduleName}"]`)
  if (element) {
    element.classList.add('title-highlight')
    setTimeout(() => {
      element.classList.remove('title-highlight')
    }, 3000)
  }
}

// ========== 缩放计算 ==========
const calculateScale = () => {
  const container = containerRef.value || document.querySelector('.preview-content')
  if (!container) return

  const availableWidth = container.clientWidth - 60
  const newScale = Math.min(1, Math.max(0.3, availableWidth / PAGE_WIDTH))

  if (Math.abs(newScale - scale.value) > 0.01) {
    scale.value = newScale
  }
}

// ========== 工具栏控制 ==========
const controlPanelTimeout = ref(null)

const showControlPanel = (event) => {
  const toolbarControls = event.currentTarget.querySelector('.toolbar-controls')
  if (toolbarControls) {
    clearTimeout(controlPanelTimeout.value)
    // 隐藏所有其他控制面板
    document.querySelectorAll('.toolbar-controls').forEach(panel => {
      if (panel !== toolbarControls) panel.style.display = 'none'
    })

    // 使用 fixed 定位，脱离所有层叠上下文
    const rect = event.currentTarget.getBoundingClientRect()
    toolbarControls.style.position = 'fixed'
    toolbarControls.style.left = `${rect.left}px`
    toolbarControls.style.transform = 'none'
    toolbarControls.style.top = `${rect.bottom + window.scrollY}px`
    toolbarControls.style.display = 'flex'
  }
}

const hideControlPanel = (event) => {
  const toolbarControls = event.currentTarget.querySelector('.toolbar-controls')
  if (toolbarControls) {
    controlPanelTimeout.value = setTimeout(() => {
      toolbarControls.style.display = 'none'
    }, 150)
  }
}

// ========== 格式化文本 ==========
const formatText = (text) => {
  if (typeof text !== 'string') return text
  return text.trim().replace(/\*\*(.*?)\*\*/g, '<b>$1</b>')
}

// ========== 导出PDF（调用后端API，使用WeasyPrint生成矢量PDF）============
const showSuccessDialog = ref(false)
const isExportingPDF = ref(false)

const exportPDF = async () => {
  if (!props.data) return

  isExportingPDF.value = true
  try {
    // 构建样式参数
    const style = {
      marginTop: marginVertical.value,
      marginBottom: marginVertical.value,
      marginLeft: marginHorizontal.value,
      marginRight: marginHorizontal.value,
      moduleMargin: moduleMargin.value,
      lineHeight: lineHeight.value,
      fontSize: fontSize.value
    }

    // 调用后端API
    const response = await fetch('http://localhost:8000/export_pdf', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        resume_data: props.data,
        style: style
      })
    })

    if (!response.ok) {
      throw new Error('PDF生成失败')
    }

    // 获取PDF二进制数据
    const pdfBlob = await response.blob()

    // 创建下载链接
    const url = window.URL.createObjectURL(pdfBlob)
    const a = document.createElement('a')
    a.href = url
    a.download = `resume_${props.data.basics?.name || 'export'}.pdf`
    document.body.appendChild(a)
    a.click()
    window.URL.revokeObjectURL(url)
    document.body.removeChild(a)

    // 显示成功提示弹窗
    showSuccessDialog.value = true

  } catch (error) {
    console.error('PDF导出错误:', error)
    alert('PDF导出失败，请确保后端服务已启动')
  } finally {
    isExportingPDF.value = false
  }
}

// ========== 生命周期 ==========
onMounted(async () => {
  await nextTick()
  setTimeout(async () => {
    await calculatePagination()
    calculateScale()
  }, 100)

  observer.value = new ResizeObserver(() => {
    clearTimeout(window.scaleTimeout)
    window.scaleTimeout = setTimeout(async () => {
      await calculatePagination()
      calculateScale()
    }, 100)
  })

  const container = document.querySelector('.preview-content')
  if (container) observer.value.observe(container)
  // 也监听隐藏内容的变化（字体变化会影响高度）
  if (contentRef.value) observer.value.observe(contentRef.value)
  observer.value.observe(document.body)
  window.addEventListener('resize', calculateScale)
})

onUnmounted(() => {
  observer.value?.disconnect()
  window.removeEventListener('resize', calculateScale)
  clearTimeout(window.scaleTimeout)
})

// ========== 分页工具函数 ==========
const isItemVisible = (item, pageIndex) => {
  if (!pageRanges.value.length) return true
  const range = pageRanges.value[pageIndex]
  return range && item.index >= range.start && item.index < range.end
}

const getItemIndex = (type, dataIndex) => {
  const items = allItems.value
  if (!items.length) return 0

  const singleTypes = ['basics', 'education-title', 'work-title', 'projects-title', 'others-title', 'self-eval-title']
  if (singleTypes.includes(type)) {
    const found = items.find(item => item.type === type)
    return found ? found.index : 0
  }

  // 处理 cert-line、lang-line 和 skill-line（无 dataIndex 的特殊类型）
  if (type === 'cert-line' || type === 'lang-line' || type === 'skill-line') {
    const found = items.find(item => item.type === type)
    return found ? found.index : items.length
  }

  // 处理带 dataIndex 的类型
  const found = items.find(item => {
    if (item.type !== type) return false
    return item.dataIndex === dataIndex
  })
  return found ? found.index : 0
}
</script>

<template>
  <div v-if="data" class="resume-wrapper">
    <!-- 工具栏 - 相对于整个简历区域 sticky -->
    <div class="resume-toolbar-wrapper">
      <div class="resume-toolbar">
        <div class="toolbar-icon">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
          </svg>
        </div>
        <div class="toolbar-controls-container">
          <div class="toolbar-section" @mouseenter="showControlPanel" @mouseleave="hideControlPanel">
            <h3 class="toolbar-title">页边距</h3>
            <div class="toolbar-controls">
              <div class="control-item">
                <label class="control-label">上下: {{ marginVertical }}rem</label>
                <input type="range" v-model.number="marginVertical" min="3" max="12" step="0.25" class="slider">
              </div>
              <div class="control-item">
                <label class="control-label">左右: {{ marginHorizontal }}rem</label>
                <input type="range" v-model.number="marginHorizontal" min="3" max="12" step="0.25" class="slider">
              </div>
            </div>
          </div>
          <div class="toolbar-section" @mouseenter="showControlPanel" @mouseleave="hideControlPanel">
            <h3 class="toolbar-title">模块边距</h3>
            <div class="toolbar-controls">
              <div class="control-item">
                <label class="control-label">间距: {{ moduleMargin }}rem</label>
                <input type="range" v-model.number="moduleMargin" min="0.25" max="2" step="0.25" class="slider">
              </div>
            </div>
          </div>
          <div class="toolbar-section" @mouseenter="showControlPanel" @mouseleave="hideControlPanel">
            <h3 class="toolbar-title">行间距</h3>
            <div class="toolbar-controls">
              <div class="control-item">
                <label class="control-label">行距: {{ lineHeight }}</label>
                <input type="range" v-model.number="lineHeight" min="1.1" max="2.2" step="0.1" class="slider">
              </div>
            </div>
          </div>
          <div class="toolbar-section" @mouseenter="showControlPanel" @mouseleave="hideControlPanel">
            <h3 class="toolbar-title">字体大小</h3>
            <div class="toolbar-controls">
              <div class="control-item">
                <label class="control-label">大小: {{ fontSize }}pt</label>
                <input type="range" v-model.number="fontSize" min="9" max="14" step="0.5" class="slider">
              </div>
            </div>
          </div>
        </div>
        <div class="toolbar-section toolbar-actions">
          <button
            class="jd-upload-btn"
            @click="emit('open-resume-edit')"
            title="编辑简历"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
            </svg>
            <span>编辑简历</span>
          </button>
          <button
            class="jd-upload-btn"
            @click="emit('open-jd-dialog')"
            title="上传目标岗位信息"
          >
            <span v-if="!jdData" class="red-dot"></span>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
              <line x1="16" y1="13" x2="8" y2="13"></line>
              <line x1="16" y1="17" x2="8" y2="17"></line>
              <polyline points="10 9 9 9 8 9"></polyline>
            </svg>
            <span>目标岗位</span>
          </button>
          <button class="export-btn" @click="exportPDF" :disabled="isExportingPDF">
            <span v-if="isExportingPDF" class="spinner"></span>
            <span>{{ isExportingPDF ? '导出中...' : '导出PDF' }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 预览内容区域 -->
    <div class="preview-content" ref="containerRef">
      <!-- 隐藏的完整内容（用于测量） -->
      <div ref="contentRef" class="content-source" :style="[pageStyles, pagePaddingStyle]">
      <!-- 个人信息 -->
      <div v-if="data.basics" class="pageable-item personal-info" :class="{ 'module-highlight': highlightedModule === 'basics' }" data-module="basics">
        <h1 class="name">{{ data.basics.name || '姓名未填写' }}</h1>
        <div class="contact-info">
          <span v-if="data.basics.gender" v-html="formatText(data.basics.gender)"></span>
          <span v-if="data.basics.gender || data.basics.phone" class="separator">|</span>
          <span v-if="data.basics.phone" v-html="formatText(data.basics.phone)"></span>
          <span v-if="(data.basics.gender || data.basics.phone) && data.basics.email" class="separator">|</span>
          <span v-if="data.basics.email" v-html="formatText(data.basics.email)"></span>
        </div>
        <div v-if="data.basics.target_position" class="target-position">
          目标岗位：<span v-html="formatText(data.basics.target_position)"></span>
        </div>
      </div>

      <!-- 教育经历 -->
      <template v-if="data.education">
        <h2 class="pageable-item section-title" :class="{ 'title-highlight': highlightedModule === 'education' }" data-module="education">教育经历</h2>
        <div v-for="(item, idx) in data.education" :key="idx" class="pageable-item education-item">
          <div class="education-header">
            <div class="school-info">
              <span class="school" v-html="formatText(item.school_name || '学校未填写')"></span>
              <div v-if="item.school_tags?.length" class="school-tags">
                <span v-for="(tag, tIdx) in item.school_tags" :key="tIdx" class="school-tag" v-html="formatText(tag)"></span>
              </div>
            </div>
            <span class="graduation-date">{{ item.date_range?.[0] || '' }} - {{ item.date_range?.[1] || '至今' }}</span>
          </div>
          <div class="degree-major" v-html="formatText(`${item.degree || ''} ${item.major || ''}`)"></div>
        </div>
        <template v-if="data.education">
          <template v-for="(item, idx) in data.education">
            <template v-if="item.theses?.length">
              <div v-for="(thesis, tIdx) in item.theses" :key="'thesis-'+idx+'-'+tIdx" class="pageable-item thesis-item">
                <h4 class="subfield-title">论文</h4>
                <div class="thesis-title" v-html="formatText(thesis.title)"></div>
                <ul v-if="thesis.details?.length" class="list-items">
                  <li v-for="(detail, dIdx) in thesis.details" :key="dIdx" class="list-item" v-html="formatText(detail)"></li>
                </ul>
              </div>
            </template>
          </template>
        </template>
      </template>

      <!-- 工作经历 -->
      <template v-if="data.work_experience">
        <h2 class="pageable-item section-title" :class="{ 'title-highlight': highlightedModule === 'work_experience' }" data-module="work_experience">工作经历</h2>
        <div v-for="(item, idx) in data.work_experience" :key="idx" class="pageable-item work-item">
          <div class="work-header">
            <div class="work-main">
              <div class="company" v-html="formatText(item.company_name || '公司未填写')"></div>
              <div class="position" v-html="formatText(`${item.job_title || ''} ${item.job_type ? `(${item.job_type})` : ''}`)"></div>
            </div>
            <span class="work-period">{{ item.date_range?.[0] || '' }} - {{ item.date_range?.[1] || '至今' }}</span>
          </div>
        </div>
        <template v-if="data.work_experience">
          <template v-for="(item, idx) in data.work_experience">
            <div v-if="item.details" :key="'details-'+idx" class="pageable-item work-details">
              <ul class="list-items">
                <li v-for="(detail, dIdx) in item.details" :key="dIdx" class="list-item" v-html="formatText(detail)"></li>
              </ul>
            </div>
          </template>
        </template>
      </template>

      <!-- 项目经历 -->
      <template v-if="data.project_experience || data.projects">
        <h2 class="pageable-item section-title" :class="{ 'title-highlight': highlightedModule === 'project_experience' }" data-module="project_experience">项目经历</h2>
        <div v-for="(item, idx) in (data.project_experience || data.projects)" :key="idx" class="pageable-item project-item">
          <div class="project-header">
            <div class="project-name" v-html="formatText(item.project_name || item.name || '项目未填写')"></div>
            <div class="project-role">
              <span v-if="item.date_range?.length" v-html="formatText(`${item.role || '角色'} | ${item.date_range[0]} - ${item.date_range[1] || '至今'}`)"></span>
              <span v-else-if="item.start_date || item.end_date" v-html="formatText(`${item.role || '角色'} | ${item.start_date || ''} - ${item.end_date || '至今'}`)"></span>
              <span v-else v-html="formatText(item.role || '项目')"></span>
            </div>
          </div>
        </div>
        <template v-if="data.project_experience || data.projects">
          <template v-for="(item, idx) in (data.project_experience || data.projects)">
            <div v-if="item.details" :key="'details-'+idx" class="pageable-item project-details">
              <ul class="list-items">
                <li v-for="(detail, dIdx) in item.details" :key="dIdx" class="list-item" v-html="formatText(detail)"></li>
              </ul>
            </div>
          </template>
        </template>
      </template>

      <!-- 其他 -->
      <template v-if="data.others">
        <h2 class="pageable-item section-title" :class="{ 'title-highlight': highlightedModule === 'others' }" data-module="others">其他</h2>
        <!-- 技能一行显示 -->
        <template v-if="data.others.skills?.length">
          <div class="pageable-item cert-lang-line">
            <span class="cert-lang-label">技能：</span>
            <template v-for="(skill, sIdx) in data.others.skills">
              <span v-html="formatText(skill)"></span><span v-if="sIdx < data.others.skills.length - 1" class="cert-lang-separator"> | </span>
            </template>
          </div>
        </template>
        <!-- 证书一行显示 -->
        <template v-if="data.others.certificates?.length">
          <div class="pageable-item cert-lang-line">
            <span class="cert-lang-label">证书：</span>
            <template v-for="(cert, cIdx) in data.others.certificates">
              <span v-html="formatText(cert)"></span><span v-if="cIdx < data.others.certificates.length - 1" class="cert-lang-separator"> | </span>
            </template>
          </div>
        </template>
        <!-- 语言一行显示 -->
        <template v-if="data.others.languages?.length">
          <div class="pageable-item cert-lang-line">
            <span class="cert-lang-label">语言：</span>
            <template v-for="(lang, lIdx) in data.others.languages">
              <span v-html="formatText(lang)"></span><span v-if="lIdx < data.others.languages.length - 1" class="cert-lang-separator"> | </span>
            </template>
          </div>
        </template>
      </template>

      <!-- 自我评价 -->
      <template v-if="data.self_evaluation">
        <h2 class="pageable-item section-title" :class="{ 'title-highlight': highlightedModule === 'self_evaluation' }" data-module="self_evaluation">自我评价</h2>
        <!-- 每条自我评价独立分页 -->
        <template v-for="(item, idx) in data.self_evaluation">
          <div v-if="item" :key="'self-eval-'+idx" class="pageable-item self-eval-item">
            <span v-html="formatText(item)"></span>
          </div>
        </template>
      </template>
    </div>

    <!-- 打印专用容器 - 连续内容流，让浏览器自动分页 -->
    <div class="print-container" :style="[pageStyles, pagePaddingStyle]">
      <!-- 个人信息 -->
      <div class="personal-info">
        <h1 class="name">{{ data.basics.name || '姓名未填写' }}</h1>
        <div class="contact-info">
          <span v-if="data.basics.gender" v-html="formatText(data.basics.gender)"></span>
          <span v-if="data.basics.gender || data.basics.phone" class="separator">|</span>
          <span v-if="data.basics.phone" v-html="formatText(data.basics.phone)"></span>
          <span v-if="(data.basics.gender || data.basics.phone) && data.basics.email" class="separator">|</span>
          <span v-if="data.basics.email" v-html="formatText(data.basics.email)"></span>
        </div>
        <div v-if="data.basics.target_position" class="target-position">
          目标岗位：<span v-html="formatText(data.basics.target_position)"></span>
        </div>
      </div>

      <!-- 教育经历 -->
      <template v-if="data.education">
        <h2 class="section-title">教育经历</h2>
        <div v-for="(item, idx) in data.education" :key="idx" class="education-item">
          <div class="education-header">
            <div class="school-info">
              <span class="school" v-html="formatText(item.school_name || '学校未填写')"></span>
              <div v-if="item.school_tags?.length" class="school-tags">
                <span v-for="(tag, tIdx) in item.school_tags" :key="tIdx" class="school-tag" v-html="formatText(tag)"></span>
              </div>
            </div>
            <span class="graduation-date">{{ item.date_range?.[0] || '' }} - {{ item.date_range?.[1] || '至今' }}</span>
          </div>
          <div class="degree-major" v-html="formatText(`${item.degree || ''} ${item.major || ''}`)"></div>
          <!-- 论文 -->
          <template v-if="item.theses?.length">
            <div v-for="(thesis, tIdx) in item.theses" :key="'thesis-'+idx+'-'+tIdx" class="thesis-item">
              <h4 class="subfield-title">论文</h4>
              <div class="thesis-title" v-html="formatText(thesis.title)"></div>
              <ul v-if="thesis.details?.length" class="list-items">
                <li v-for="(detail, dIdx) in thesis.details" :key="dIdx" class="list-item" v-html="formatText(detail)"></li>
              </ul>
            </div>
          </template>
        </div>
      </template>

      <!-- 工作经历 -->
      <template v-if="data.work_experience">
        <h2 class="section-title">工作经历</h2>
        <div v-for="(item, idx) in data.work_experience" :key="idx" class="work-item">
          <div class="work-header">
            <div class="work-main">
              <div class="company" v-html="formatText(item.company_name || '公司未填写')"></div>
              <div class="position" v-html="formatText(`${item.job_title || ''} ${item.job_type ? `(${item.job_type})` : ''}`)"></div>
            </div>
            <span class="work-period">{{ item.date_range?.[0] || '' }} - {{ item.date_range?.[1] || '至今' }}</span>
          </div>
          <ul v-if="item.details?.length" class="list-items">
            <li v-for="(detail, dIdx) in item.details" :key="dIdx" class="list-item" v-html="formatText(detail)"></li>
          </ul>
        </div>
      </template>

      <!-- 项目经历 -->
      <template v-if="data.project_experience || data.projects">
        <h2 class="section-title">项目经历</h2>
        <div v-for="(item, idx) in (data.project_experience || data.projects)" :key="idx" class="project-item">
          <div class="project-header">
            <div class="project-name" v-html="formatText(item.project_name || item.name || '项目未填写')"></div>
            <div class="project-role">
              <span v-if="item.date_range?.length" v-html="formatText(`${item.role || '角色'} | ${item.date_range[0]} - ${item.date_range[1] || '至今'}`)"></span>
              <span v-else-if="item.start_date || item.end_date" v-html="formatText(`${item.role || '角色'} | ${item.start_date || ''} - ${item.end_date || '至今'}`)"></span>
              <span v-else v-html="formatText(item.role || '项目')"></span>
            </div>
          </div>
          <ul v-if="item.details?.length" class="list-items">
            <li v-for="(detail, dIdx) in item.details" :key="dIdx" class="list-item" v-html="formatText(detail)"></li>
          </ul>
        </div>
      </template>

      <!-- 其他 -->
      <template v-if="data.others">
        <h2 class="section-title">其他</h2>
        <div v-if="data.others.skills?.length" class="cert-lang-line">
          <span class="cert-lang-label">技能：</span>
          <template v-for="(skill, sIdx) in data.others.skills" :key="'skill-'+sIdx">
            <span v-html="formatText(skill)"></span><span v-if="sIdx < data.others.skills.length - 1" class="cert-lang-separator"> | </span>
          </template>
        </div>
        <div v-if="data.others.certificates?.length" class="cert-lang-line">
          <span class="cert-lang-label">证书：</span>
          <template v-for="(cert, cIdx) in data.others.certificates" :key="'cert-'+cIdx">
            <span v-html="formatText(cert)"></span><span v-if="cIdx < data.others.certificates.length - 1" class="cert-lang-separator"> | </span>
          </template>
        </div>
        <div v-if="data.others.languages?.length" class="cert-lang-line">
          <span class="cert-lang-label">语言：</span>
          <template v-for="(lang, lIdx) in data.others.languages" :key="'lang-'+lIdx">
            <span v-html="formatText(lang)"></span><span v-if="lIdx < data.others.languages.length - 1" class="cert-lang-separator"> | </span>
          </template>
        </div>
      </template>

      <!-- 自我评价 -->
      <template v-if="data.self_evaluation">
        <h2 class="section-title">自我评价</h2>
        <template v-for="(item, idx) in data.self_evaluation">
          <div v-if="item" :key="'self-eval-'+idx" class="self-eval-item" v-html="formatText(item)"></div>
        </template>
      </template>
    </div>

    <!-- 分页预览 -->
    <div class="pages-wrapper" :style="pagesContainerStyle">
      <div v-for="page in pageCount" :key="page" class="a4-page" :style="pageStyle">
        <div class="page-inner" :style="pagePaddingStyle">
          <div class="page-content" :style="pageStyles">
            <!-- 个人信息 -->
            <div v-if="data.basics && isItemVisible({index: getItemIndex('basics', 0)}, page - 1)" class="personal-info" :class="{ 'module-highlight': highlightedModule === 'basics' }" data-module="basics">
              <h1 class="name">{{ data.basics.name || '姓名未填写' }}</h1>
              <div class="contact-info">
                <span v-if="data.basics.gender" v-html="formatText(data.basics.gender)"></span>
                <span v-if="data.basics.gender || data.basics.phone" class="separator">|</span>
                <span v-if="data.basics.phone" v-html="formatText(data.basics.phone)"></span>
                <span v-if="(data.basics.gender || data.basics.phone) && data.basics.email" class="separator">|</span>
                <span v-if="data.basics.email" v-html="formatText(data.basics.email)"></span>
              </div>
              <div v-if="data.basics.target_position" class="target-position">
                目标岗位：<span v-html="formatText(data.basics.target_position)"></span>
              </div>
            </div>

            <!-- 教育经历 -->
            <template v-if="data.education">
              <h2 v-if="isItemVisible({index: getItemIndex('education-title', 0)}, page - 1)" class="section-title" :class="{ 'title-highlight': highlightedModule === 'education' }" data-module="education">教育经历</h2>
              <template v-for="(item, idx) in data.education">
                <div v-if="isItemVisible({index: getItemIndex('education-item', idx)}, page - 1)" :key="'edu-'+idx" class="education-item" :class="{ 'content-highlight': highlightedModule === 'education' }">
                  <div class="education-header">
                    <div class="school-info">
                      <span class="school" v-html="formatText(item.school_name || '学校未填写')"></span>
                      <div v-if="item.school_tags?.length" class="school-tags">
                        <span v-for="(tag, tIdx) in item.school_tags" :key="tIdx" class="school-tag" v-html="formatText(tag)"></span>
                      </div>
                    </div>
                    <span class="graduation-date">{{ item.date_range?.[0] || '' }} - {{ item.date_range?.[1] || '至今' }}</span>
                  </div>
                  <div class="degree-major" v-html="formatText(`${item.degree || ''} ${item.major || ''}`)"></div>
                </div>
                <!-- 论文（独立分页项） -->
                <template v-if="item.theses?.length">
                  <template v-for="(thesis, tIdx) in item.theses">
                    <div v-if="isItemVisible({index: getItemIndex('thesis-item', `${idx}-${tIdx}`)}, page - 1)" :key="'thesis-'+idx+'-'+tIdx" class="thesis-item">
                      <h4 class="subfield-title">论文</h4>
                      <div class="thesis-title" v-html="formatText(thesis.title)"></div>
                      <ul v-if="thesis.details?.length" class="list-items">
                        <li v-for="(detail, dIdx) in thesis.details" :key="dIdx" class="list-item" v-html="formatText(detail)"></li>
                      </ul>
                    </div>
                  </template>
                </template>
              </template>
            </template>

            <!-- 工作经历 -->
            <template v-if="data.work_experience">
              <h2 v-if="isItemVisible({index: getItemIndex('work-title', 0)}, page - 1)" class="section-title" :class="{ 'title-highlight': highlightedModule === 'work_experience' }" data-module="work_experience">工作经历</h2>
              <template v-for="(item, idx) in data.work_experience">
                <div v-if="isItemVisible({index: getItemIndex('work-item', idx)}, page - 1)" :key="'work-'+idx" class="work-item" :class="{ 'content-highlight': highlightedModule === 'work_experience' }">
                  <div class="work-header">
                    <div class="work-main">
                      <div class="company" v-html="formatText(item.company_name || '公司未填写')"></div>
                      <div class="position" v-html="formatText(`${item.job_title || ''} ${item.job_type ? `(${item.job_type})` : ''}`)"></div>
                    </div>
                    <span class="work-period">{{ item.date_range?.[0] || '' }} - {{ item.date_range?.[1] || '至今' }}</span>
                  </div>
                </div>
                <!-- 工作详情（独立分页项） -->
                <div v-if="item.details && isItemVisible({index: getItemIndex('work-details', idx)}, page - 1)" :key="'work-details-'+idx" class="work-details">
                  <ul class="list-items">
                    <li v-for="(detail, dIdx) in item.details" :key="dIdx" class="list-item" v-html="formatText(detail)"></li>
                  </ul>
                </div>
              </template>
            </template>

            <!-- 项目经历 -->
            <template v-if="data.project_experience || data.projects">
              <h2 v-if="isItemVisible({index: getItemIndex('projects-title', 0)}, page - 1)" class="section-title" :class="{ 'title-highlight': highlightedModule === 'project_experience' }" data-module="project_experience">项目经历</h2>
              <template v-for="(item, idx) in (data.project_experience || data.projects)">
                <div v-if="isItemVisible({index: getItemIndex('project-item', idx)}, page - 1)" :key="'proj-'+idx" class="project-item" :class="{ 'content-highlight': highlightedModule === 'project_experience' }">
                  <div class="project-header">
                    <div class="project-name" v-html="formatText(item.project_name || item.name || '项目未填写')"></div>
                    <div class="project-role">
                      <span v-if="item.date_range?.length" v-html="formatText(`${item.role || '角色'} | ${item.date_range[0]} - ${item.date_range[1] || '至今'}`)"></span>
                      <span v-else-if="item.start_date || item.end_date" v-html="formatText(`${item.role || '角色'} | ${item.start_date || ''} - ${item.end_date || '至今'}`)"></span>
                      <span v-else v-html="formatText(item.role || '项目')"></span>
                    </div>
                  </div>
                </div>
                <!-- 项目详情（独立分页项） -->
                <div v-if="item.details && isItemVisible({index: getItemIndex('project-details', idx)}, page - 1)" :key="'proj-details-'+idx" class="project-details">
                  <ul class="list-items">
                    <li v-for="(detail, dIdx) in item.details" :key="dIdx" class="list-item" v-html="formatText(detail)"></li>
                  </ul>
                </div>
              </template>
            </template>

            <!-- 其他 -->
            <template v-if="data.others">
              <h2 v-if="isItemVisible({index: getItemIndex('others-title', 0)}, page - 1)" class="section-title" :class="{ 'title-highlight': highlightedModule === 'others' }" data-module="others">其他</h2>
              <!-- 技能一行显示 -->
              <template v-if="data.others.skills?.length">
                <div v-if="isItemVisible({index: getItemIndex('skill-line', 0)}, page - 1)" class="cert-lang-line">
                  <span class="cert-lang-label">技能：</span>
                  <template v-for="(skill, sIdx) in data.others.skills">
                    <span v-html="formatText(skill)"></span><span v-if="sIdx < data.others.skills.length - 1" class="cert-lang-separator"> | </span>
                  </template>
                </div>
              </template>
              <!-- 证书一行显示 -->
              <template v-if="data.others.certificates?.length">
                <div v-if="isItemVisible({index: getItemIndex('cert-line', 0)}, page - 1)" class="cert-lang-line">
                  <span class="cert-lang-label">证书：</span>
                  <template v-for="(cert, cIdx) in data.others.certificates">
                    <span v-html="formatText(cert)"></span><span v-if="cIdx < data.others.certificates.length - 1" class="cert-lang-separator"> | </span>
                  </template>
                </div>
              </template>
              <!-- 语言一行显示 -->
              <template v-if="data.others.languages?.length">
                <div v-if="isItemVisible({index: getItemIndex('lang-line', 0)}, page - 1)" class="cert-lang-line">
                  <span class="cert-lang-label">语言：</span>
                  <template v-for="(lang, lIdx) in data.others.languages">
                    <span v-html="formatText(lang)"></span><span v-if="lIdx < data.others.languages.length - 1" class="cert-lang-separator"> | </span>
                  </template>
                </div>
              </template>
            </template>

            <!-- 自我评价 -->
            <template v-if="data.self_evaluation">
              <h2 v-if="isItemVisible({index: getItemIndex('self-eval-title', 0)}, page - 1)" class="section-title" :class="{ 'title-highlight': highlightedModule === 'self_evaluation' }" data-module="self_evaluation">自我评价</h2>
              <!-- 每条自我评价独立分页 -->
              <template v-for="(item, idx) in data.self_evaluation">
                <div v-if="item && isItemVisible({index: getItemIndex('self-eval-item', idx)}, page - 1)" :key="'self-eval-'+idx" class="self-eval-item" :class="{ 'content-highlight': highlightedModule === 'self_evaluation' }">
                  <span v-html="formatText(item)"></span>
                </div>
              </template>
            </template>
          </div>
        </div>
        <div class="page-footer">{{ page }} / {{ pageCount }}</div>
      </div>
    </div>
    <div v-if="pageCount > 1" class="page-indicator">共 {{ pageCount }} 页</div>
  </div>

  <div v-if="!data" class="no-data">
    <p>暂无简历数据，请稍后重试</p>
  </div>
  </div>

  <!-- 成功提示弹窗 -->
  <div v-if="showSuccessDialog" class="success-dialog-overlay" @click.self="showSuccessDialog = false">
    <div class="success-dialog">
      <div class="success-icon">
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
        </svg>
      </div>
      <h3>简历导出成功</h3>
      <p>PDF 文件已成功下载。<br><br>网页预览与实际 PDF 文件在排版上可能有细微差异，这不是问题——如果需要，你可以随时调整样式参数后重新导出。</p>
      <button class="confirm-btn" @click="showSuccessDialog = false">我知道了</button>
    </div>
  </div>
</template>

<style scoped>
.resume-wrapper {
  height: 100%;
  display: flex;
  flex-direction: column;
  position: relative;
}
/* 工具栏包装器 - 为sticky提供正确的定位上下文 */
.resume-toolbar-wrapper {
  position: sticky;
  top: 0;
  z-index: 100;
  background: #ffffff;
  flex-shrink: 0;
}
.resume-toolbar {
  background: #ffffff;
  padding: 0.75rem 1rem;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  border: 1px solid #e9ecef;
  display: flex;
  align-items: center;
  gap: 1rem;
  flex-shrink: 0;
}
.toolbar-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #333;
  width: 24px;
  height: 24px;
  flex-shrink: 0;
}
.toolbar-controls-container {
  display: flex;
  align-items: center;
  gap: 1.5rem;
  flex-shrink: 0;
}
.toolbar-section {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  position: relative;
  flex-shrink: 0;
  z-index: 1;
}
.toolbar-section:last-child {
  margin-left: auto;
  flex-shrink: 0;
}
.toolbar-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.toolbar-title {
  font-size: 0.8rem;
  font-weight: 500;
  margin: 0;
  color: #495057;
  white-space: nowrap;
  cursor: pointer;
  padding: 0.4rem 0.8rem;
  border-radius: 6px;
  background: #f8f9fa;
  border: 1px solid transparent;
}
.toolbar-title:hover {
  background: #e9ecef;
  border-color: #dee2e6;
}
.toolbar-controls {
  display: none;
  position: fixed;
  left: 50%;
  transform: translateX(-50%);
  background: #ffffff;
  border: 1px solid #e9ecef;
  border-radius: 8px;
  padding: 1rem;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
  gap: 0.8rem;
  flex-direction: column;
  z-index: 10000;
  min-width: 220px;
  white-space: nowrap;
}
.toolbar-section:hover > .toolbar-controls,
.toolbar-section:hover > .toolbar-title,
.toolbar-controls:hover {
  display: flex;
}
.control-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  justify-content: space-between;
}
.control-label {
  font-size: 0.75rem;
  color: #6c757d;
  font-weight: 500;
  white-space: nowrap;
  min-width: 60px;
}
.slider {
  -webkit-appearance: none;
  width: 120px;
  height: 5px;
  border-radius: 4px;
  background: linear-gradient(to right, #333 0%, #333 50%, #e9ecef 50%, #e9ecef 100%);
  outline: none;
}
.slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #333;
  cursor: pointer;
  border: 3px solid #ffffff;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.15);
}
.slider::-moz-range-thumb {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #333;
  cursor: pointer;
  border: 3px solid #ffffff;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.15);
}
.export-btn {
  background: #333;
  color: white;
  border: none;
  padding: 0.5rem 1.2rem;
  font-size: 0.8rem;
  font-weight: 500;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.3s ease;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}
.export-btn:hover {
  background: #555;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}
.export-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}
/* JD上传按钮 */
.jd-upload-btn {
  background: #fff;
  color: #333;
  border: 1px solid #ddd;
  padding: 0.4rem 0.8rem;
  font-size: 0.75rem;
  font-weight: 500;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  gap: 0.3rem;
  position: relative;
}
.jd-upload-btn:hover {
  background: #f5f5f5;
  border-color: #ccc;
}
.red-dot {
  position: absolute;
  top: -3px;
  right: -3px;
  width: 8px;
  height: 8px;
  background: #ef4444;
  border-radius: 50%;
  border: 2px solid white;
}
/* Spinner 转圈圈 */
.spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-radius: 50%;
  border-top-color: white;
  animation: spin 0.8s linear infinite;
  margin-right: 6px;
  vertical-align: middle;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
/* 预览内容区域 - 处理滚动 */
.preview-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 20px;
  background: #f5f5f5;
  width: 100%;
  box-sizing: border-box;
  overflow-y: auto;
  overflow-x: hidden;
  flex: 1;
  min-height: 0;
}
.content-source {
  /* 使用 opacity: 0 而非 visibility: hidden，确保可以准确测量高度 */
  position: fixed;
  left: 0;
  top: 0;
  opacity: 0;
  width: 794px;
  box-sizing: border-box;
  background: white;
  pointer-events: none;
}
.pages-wrapper {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* 打印容器默认隐藏，只在打印时显示 */
.print-container {
  display: none;
}
.a4-page {
  background: white;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
  position: relative;
  box-sizing: border-box;
  flex-shrink: 0;
}
.a4-page::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  border: 1px solid #e0e0e0;
  pointer-events: none;
  z-index: 1;
}
.page-inner {
  width: 100%;
  height: 100%;
  box-sizing: border-box;
}
.page-content {
  width: 100%;
  box-sizing: border-box;
  word-wrap: break-word;
  overflow-wrap: break-word;
}
.personal-info {
  text-align: center;
  margin-bottom: var(--module-margin);
}
.name {
  font-size: 1.5em;
  font-weight: 700;
  margin: 0 0 0.25em 0;
  color: #212529;
}
.contact-info {
  display: flex;
  justify-content: center;
  gap: 0.5em;
  flex-wrap: wrap;
  font-size: 0.8em;
  color: #6c757d;
  margin-bottom: 0.25em;
}
.separator {
  color: #6c757d;
}
.target-position {
  font-size: 0.8em;
  color: #212529;
  font-weight: 600;
}
.section-title {
  font-size: 1.1em;
  font-weight: 600;
  margin: 0 0 0.5em 0;
  color: #212529;
  padding-bottom: 0.25em;
  border-bottom: 2px solid #333;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.education-item,
.work-item,
.project-item {
  margin-bottom: 0.5em;
}
.education-header,
.work-header,
.project-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 0.5em;
}
.school,
.company,
.project-name {
  font-size: 1em;
  font-weight: 600;
  color: #212529;
}
.school-info {
  display: flex;
  align-items: baseline;
  gap: 0.5em;
  flex-wrap: wrap;
}
.school-tags {
  display: inline-flex;
  gap: 0.375em;
  flex-wrap: nowrap;
  white-space: nowrap;
}
.school-tag {
  display: inline-block;
  padding: 0.125em 0.5em;
  background: #333;
  color: white;
  font-size: 0.75em;
  border-radius: 4px;
  font-weight: 500;
}
.graduation-date,
.work-period {
  font-size: 0.8em;
  color: #95a5a6;
  white-space: nowrap;
  font-weight: 500;
}
.degree-major,
.position,
.project-role {
  font-size: 0.8em;
  color: #6c757d;
  font-weight: 500;
}
.list-items {
  list-style: none;
  padding: 0;
  margin: 0;
}
.list-item {
  position: relative;
  padding-left: 1.25em;
  margin-bottom: 0.25em;
  font-size: 0.8em;
  line-height: var(--line-height, 1.6);
}
.list-item::before {
  content: '•';
  position: absolute;
  left: 0;
  color: #333;
  font-weight: bold;
}
.self-eval-item {
  font-size: 0.8em;
  line-height: var(--line-height, 1.6);
  color: #212529;
}
.others-title {
  font-size: 0.9em;
  font-weight: 600;
  color: #212529;
  margin: 0 0 0.25em 0;
}
.skill-section,
.cert-section,
.lang-section {
  margin-bottom: 0.5em;
}
.skill-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5em;
}
.skill-item,
.cert-lang-line,
.inline-item {
  font-size: 0.8em;
  color: #212529;
  word-wrap: break-word;
  overflow-wrap: break-word;
  max-width: 100%;
}
.cert-lang-label {
  font-weight: 600;
  margin-right: 0.25em;
}
.cert-lang-separator {
  color: #333;
  margin: 0 0.25em;
}
.skills-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5em;
}
.thesis-item {
  margin-top: 0.25em;
}
.thesis-title {
  font-weight: 600;
  font-size: 0.85em;
}
.subfield-title {
  font-size: 0.825em;
  font-weight: 600;
  color: #6c757d;
  margin-bottom: 0.25em;
  display: block;
}
.inline-list {
  display: inline;
}
.inline-item:not(:last-child)::after {
  content: '·';
  color: #333;
  font-weight: bold;
  margin-left: 0.5em;
  margin-right: 0.5em;
}
:deep(b) {
  font-weight: 600;
}
.page-footer {
  position: absolute;
  bottom: 15px;
  right: 20px;
  font-size: 10pt;
  color: #6c757d;
}
.page-indicator {
  background: rgba(0, 0, 0, 0.7);
  color: white;
  padding: 8px 16px;
  border-radius: 20px;
  font-size: 14px;
  font-weight: 500;
  position: fixed;
  bottom: 30px;
  right: 30px;
  z-index: 100;
}
.no-data {
  text-align: center;
  padding: 3rem 1rem;
  color: #6c757d;
  font-size: 1.1rem;
}

/* 成功提示弹窗 */
.success-dialog-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  animation: fadeIn 0.3s ease;
}

.success-dialog {
  background: white;
  border-radius: var(--radius-lg);
  padding: 32px;
  max-width: 420px;
  width: 90%;
  text-align: center;
  box-shadow: var(--shadow-lg);
  animation: slideUp 0.3s ease;
}

.success-icon {
  width: 64px;
  height: 64px;
  margin: 0 auto 20px;
  background: #f0f9f0;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.success-icon svg {
  width: 32px;
  height: 32px;
  color: #22c55e;
}

.success-dialog h3 {
  margin: 0 0 16px;
  font-size: 1.25rem;
  font-weight: 600;
  color: #212529;
}

.success-dialog p {
  margin: 0 0 24px;
  font-size: 0.95rem;
  color: #6c757d;
  line-height: 1.6;
}

.success-dialog .confirm-btn {
  background: #212529;
  color: white;
  border: none;
  padding: 12px 32px;
  border-radius: var(--radius-md);
  font-size: 0.95rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.success-dialog .confirm-btn:hover {
  background: #495057;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* ========== 模块高亮动画 - AI风格蓝紫色炫光 ========== */

/* 模块高亮边框脉冲动画 */
.module-highlight {
  position: relative;
  animation: borderPulse 2s ease-in-out infinite;
}

@keyframes borderPulse {
  0%, 100% {
    box-shadow: 0 0 0 0 rgba(6, 182, 212, 0);
  }
  25% {
    box-shadow: 0 0 0 2px rgba(6, 182, 212, 0.3), 0 0 10px rgba(139, 92, 246, 0.2);
  }
  50% {
    box-shadow: 0 0 0 4px rgba(6, 182, 212, 0.2), 0 0 20px rgba(139, 92, 246, 0.3);
  }
  75% {
    box-shadow: 0 0 0 2px rgba(6, 182, 212, 0.3), 0 0 10px rgba(139, 92, 246, 0.2);
  }
}

/* 标题文字炫光动画 */
.title-highlight {
  position: relative;
  background: linear-gradient(
    90deg,
    #212529 0%,
    #06b6d4 25%,
    #8b5cf6 50%,
    #06b6d4 75%,
    #212529 100%
  );
  background-size: 200% 100%;
  background-clip: text;
  -webkit-background-clip: text;
  color: transparent;
  animation: titleShimmer 2.5s ease-in-out infinite;
  display: inline-block;
}

@keyframes titleShimmer {
  0% {
    background-position: 100% 0;
  }
  100% {
    background-position: -100% 0;
  }
}
</style>

<!-- 全局样式 - 用于动态添加的高亮类 -->
<style>
/* ========== 模块高亮动画 - 全局样式（用于动态添加的类） ========== */

/* 模块高亮边框脉冲动画 */
:global(.module-highlight) {
  position: relative;
  animation: borderPulseGlobal 2s ease-in-out infinite;
}

@keyframes borderPulseGlobal {
  0%, 100% {
    box-shadow: 0 0 0 0 rgba(6, 182, 212, 0);
  }
  25% {
    box-shadow: 0 0 0 2px rgba(6, 182, 212, 0.3), 0 0 10px rgba(139, 92, 246, 0.2);
  }
  50% {
    box-shadow: 0 0 0 4px rgba(6, 182, 212, 0.2), 0 0 20px rgba(139, 92, 246, 0.3);
  }
  75% {
    box-shadow: 0 0 0 2px rgba(6, 182, 212, 0.3), 0 0 10px rgba(139, 92, 246, 0.2);
  }
}

/* 标题文字炫光动画 - 使用 :global() 配合父选择器提高优先级 */
:global(.resume-wrapper .title-highlight),
:global(.preview-content .title-highlight),
:global(.pages-wrapper .title-highlight) {
  background: linear-gradient(
    90deg,
    #212529 0%,
    #06b6d4 25%,
    #8b5cf6 50%,
    #06b6d4 75%,
    #212529 100%
  ) !important;
  background-size: 200% 100% !important;
  -webkit-background-clip: text !important;
  background-clip: text !important;
  color: transparent !important;
  animation: titleShimmerGlobal 2.5s ease-in-out infinite;
  display: inline-block !important;
  background-repeat: repeat-y !important;
}

@keyframes titleShimmerGlobal {
  0% {
    background-position: 100% 0;
  }
  100% {
    background-position: -100% 0;
  }
}

/* 内容项动画 - 淡入闪烁效果 */
:global(.resume-wrapper .content-highlight),
:global(.preview-content .content-highlight),
:global(.pages-wrapper .content-highlight) {
  animation: contentPulseGlobal 2s ease-in-out infinite;
  border-radius: 4px;
}

@keyframes contentPulseGlobal {
  0%, 100% {
    background-color: transparent;
  }
  25% {
    background-color: rgba(6, 182, 212, 0.1);
  }
  50% {
    background-color: rgba(139, 92, 246, 0.15);
  }
  75% {
    background-color: rgba(6, 182, 212, 0.1);
  }
}
</style>
