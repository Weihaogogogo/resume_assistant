<script setup>
import { ref, onMounted, watch, nextTick, computed, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ChatMessage from './components/ChatMessage.vue'
import ResumePreview from './components/ResumePreview.vue'
import RichTextEditor from './components/RichTextEditor.vue'
import MonthRangePresentPicker from './components/MonthRangePresentPicker.vue'
import MobileTabBar from './components/MobileTabBar.vue'
import { labels } from './utils/labels.js'

// 响应式布局状态
const isMobileView = ref(false)
const currentTab = ref('chat')
let resizeObserver = null

// 语言状态
const currentLang = ref('zh')
const showTranslateConfirm = ref(false)
const pendingLang = ref('zh')  // 切换语言时的目标语言
const isSwitchingLang = ref(false)

function resetLangToZhDefault() {
  currentLang.value = 'zh'
  pendingLang.value = 'zh'
}

// 检测是否为移动端视图
function checkMobileView() {
  isMobileView.value = window.innerWidth < 1200
}

// Tooltip 状态管理
const tooltipState = ref({ visible: false, text: '', x: 0, top: 0 })
let tooltipTimeout = null

function showTooltip(event, text) {
  clearTimeout(tooltipTimeout)
  
  let rect = null
  
  if (event && event.currentTarget) {
    const button = event.currentTarget
    rect = button.getBoundingClientRect()
  }
  
  tooltipTimeout = setTimeout(() => {
    if (!rect) return
    
    tooltipState.value = {
      visible: true,
      text: text,
      x: rect.right + 8,
      top: rect.top + (rect.height / 2)
    }
  }, 100)
}

function hideTooltip() {
  clearTimeout(tooltipTimeout)
  tooltipState.value.visible = false
}

// 语言切换函数
async function switchLang(lang) {
  // AI未结束回复时或切换进行中，禁止切换
  if (isLanguageSwitchDisabled.value) {
    return
  }

  const targetLang = lang
  if (targetLang === currentLang.value) {
    return
  }

  const sourceLang = targetLang === 'zh' ? 'en' : 'zh'
  isSwitchingLang.value = true

  try {
    // 判断简历是否有实际内容（不只是有basics对象）
    const hasRealContent = (resume) => {
      if (!resume) return false
      // 检查是否有实际内容：basics有name，或者有education/work_experience等
      const basics = resume.basics || {}
      const hasName = !!basics.name
      const hasEducation = (resume.education && resume.education.length > 0)
      const hasWork = (resume.work_experience && resume.work_experience.length > 0)
      const hasProject = (resume.project_experience && resume.project_experience.length > 0)
      const hasOthers = (resume.others && (resume.others.skills?.length > 0 || resume.others.certificates?.length > 0 || resume.others.languages?.length > 0))
      const hasSelfEval = (resume.self_evaluation && resume.self_evaluation.length > 0)
      return hasName || hasEducation || hasWork || hasProject || hasOthers || hasSelfEval
    }

    // 获取切换前的目标简历状态（用于判断是否需要弹窗）
    const targetResumeBeforeSwitch = targetLang === 'zh' ? zhResume.value : enResume.value
    const wasTargetEmpty = !hasRealContent(targetResumeBeforeSwitch)


    // 获取源语言简历
    const sourceResume = sourceLang === 'zh' ? zhResume.value : enResume.value
    const isSourceHasContent = hasRealContent(sourceResume)


    // 步骤1：如果目标语言简历为空，则复制源语言简历到目标语言并保存
    if (wasTargetEmpty && isSourceHasContent) {
      const copiedResume = JSON.parse(JSON.stringify(sourceResume))
      if (targetLang === 'zh') {
        zhResume.value = copiedResume
      } else {
        enResume.value = copiedResume
      }
      // 保存到数据库
      await saveResumeToBackend(copiedResume, targetLang)
    } else {
    }

    // 步骤2：从后端重新加载目标语言的最新简历
    try {
      const response = await fetch('/load_resume', {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({
          session_id: sessionId.value || 'default',
          lang: targetLang
        })
      })

      if (response.ok) {
        const latestResume = await response.json()

        // 更新对应语言的简历缓存
        if (targetLang === 'zh') {
          zhResume.value = latestResume
        } else {
          enResume.value = latestResume
        }

        // 切换语言
        currentLang.value = targetLang
        resumeData.value = latestResume

      }
    } catch (error) {
      console.error('切换语言时加载简历失败:', error)
    }

    // 步骤3：如果目标简历原本为空（现在已复制），弹窗询问是否翻译
    if (wasTargetEmpty && isSourceHasContent) {
      pendingLang.value = targetLang
      showTranslateConfirm.value = true
    }
    // 步骤4：如果目标简历原本就不为空，直接切换，不弹窗
  } finally {
    isSwitchingLang.value = false
  }
}

// 保存简历到后端
async function saveResumeToBackend(resumeDataToSave, lang) {
  try {
    await fetch('/save_resume', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        resume_data: resumeDataToSave,
        session_id: sessionId.value || 'default',
        lang: lang
      })
    })
  } catch (error) {
    console.error('保存简历失败:', error)
  }
}

// 确认翻译
function confirmTranslate() {
  showTranslateConfirm.value = false

  // 设置目标语言
  currentLang.value = pendingLang.value
  resumeData.value = enResume.value

  // 确保英文简历已保存到数据库
  if (enResume.value) {
    saveResumeToBackend(enResume.value, 'en')
  }

  // 在聊天区域发送翻译请求
  const translateMessage = "请将简历内容翻译为英文，需要符合英文表达习惯，保留原汁原味，不要添加或虚构内容。"

  // 调用现有的发送消息逻辑
  userInput.value = translateMessage
  sendMessage()
}

// 取消翻译
function cancelTranslate() {
  showTranslateConfirm.value = false
  // 切换到英文但不翻译
  currentLang.value = pendingLang.value
  resumeData.value = enResume.value

  // 确保英文简历已保存到数据库
  if (enResume.value) {
    saveResumeToBackend(enResume.value, 'en')
  }
}

// 获取当前语言的标签
const t = computed(() => labels[currentLang.value] || labels.zh)

// 翻译弹窗文案（根据目标语言显示）
const translateLabels = computed(() => {
  const lang = labels.zh
  // 根据pendingLang决定显示中文还是英文的翻译确认文案
  if (pendingLang.value === 'en') {
    return {
      ...lang,
      translateConfirmMessage: lang.translateToEnMessage
    }
  } else {
    return {
      ...lang,
      translateConfirmMessage: lang.translateToZhMessage
    }
  }
})

// 认证状态
const isLoggedIn = ref(false)
const currentUser = ref(null)
const token = ref(localStorage.getItem('access_token') || '')
const router = useRouter()
const route = useRoute()

// 计算属性：判断是否为管理页面路由
const isAdminRoute = computed(() => route.path === '/admin')

// 聊天消息列表
const messages = ref([])
// 消息容器引用，用于自动滚动
const messagesContainer = ref(null)
// 文件输入引用
const fileInput = ref(null)
// 用户输入
const userInput = ref('')
// 上传的文件列表
const uploadedFiles = ref([])
// 简历数据（当前显示的）
const resumeData = ref(null)
// 中文简历数据
const zhResume = ref(null)
// 英文简历数据
const enResume = ref(null)
// JD数据（新增）
const jdData = ref(null)
// 加载状态
const isLoading = ref(false)
// 响应中状态（流式输出时）
const isResponding = ref(false)
// 确认区域状态（当有 confirm area 时，禁用输入）
const hasConfirmArea = ref(false)
// 加载文案状态
const loadingText = ref('正在处理中...')
let loadingTextInterval = null
// 全屏弹窗状态
const isFullscreenDialogOpen = ref(false)
const dialogUserInput = ref('')
// 会话ID与会话列表
const sessionId = ref(localStorage.getItem('resumeAssistantSessionId') || '')
const sessions = ref([])
const activeSessionId = ref('')
const isSessionSidebarExpanded = ref(false)
const editingSessionId = ref('')
const editingSessionTitle = ref('')
const activeDropdown = ref(null)  // 当前展开的下拉框对应的 session_id
const menuSession = ref(null)  // 当前打开菜单的会话
const showSessionMenu = ref(false)  // 是否显示会话菜单
const showRenameModal = ref(false)  // 是否显示重命名弹窗
const showDeleteModal = ref(false)  // 是否显示删除确认弹窗
const renameSessionTitle = ref('')  // 重命名输入框的值
const menuPosition = ref({ top: '0px', left: '0px' })  // 菜单位置
const isSessionBusy = ref(false)
const isUiInteractionLocked = computed(() => {
  return (
    isLoading.value ||
    isResponding.value ||
    hasConfirmArea.value ||
    isLoadingInitialData.value ||
    isSessionBusy.value ||
    isSwitchingLang.value
  )
})
const isSessionSwitchLocked = computed(() => {
  return isUiInteractionLocked.value
})
const isLanguageSwitchDisabled = computed(() => isUiInteractionLocked.value)

function guardWhileResponding(actionName = '该操作') {
  if (isResponding.value) {
    alert(`AI 还在回复中，请等待本轮回复完成后再进行${actionName}。`)
    return true
  }
  return false
}

// 图片预览状态
const showImagePreview = ref(false)
const previewImageUrl = ref('')

// 模块高亮状态
const highlightedModule = ref('')

// JD上传弹窗状态（新增）
const isJDDialogOpen = ref(false)
const jdInputMode = ref('input') // 'input' | 'form'
const jdInputText = ref('')
const jdInputImage = ref('') // base64
const isParsingJD = ref(false) // 解析中状态
const isSaving = ref(false) // 保存中状态
const jdFormData = ref({}) // 解析后的表单数据
const newSkill = ref('') // 用于添加技能标签

// 简历编辑弹窗状态（新增）
const isResumeEditDialogOpen = ref(false)
const resumeFormData = ref({
  basics: { name: '', gender: '', phone: '', email: '', target_position: '', photo: '' },
  education: [],
  work_experience: [],
  project_experience: [],
  others: { skills: [], certificates: [], languages: [] },
  self_evaluation: []
})
// 简历照片错误信息
const photoError = ref('')
// 标签输入
const newResumeSkill = ref('')
const newResumeCert = ref('')
const newResumeLang = ref('')

// 多行文本编辑（临时存储）
const workDetailsText = ref('')
const projectDetailsText = ref('')
const selfEvalText = ref('')

// 首次进入选择弹窗状态
const showStartDialog = ref(false)
const showUploadDialog = ref(false)
const resumeImageFile = ref(null) // 选择的图片文件
const resumeImagePreview = ref('') // 图片预览
const isResumePdf = ref(false) // 是否是PDF文件
const isParsingResume = ref(false) // 解析中状态
const resumeFileInput = ref(null) // 简历文件输入元素引用
const hasResumeFileSelected = ref(false) // 是否已选择简历文件（上传流程已开始，不可返回）
const isLoadingInitialData = ref(false) // 防止 loadInitialData 重复调用
let parsingStatusPollInterval = null // 解析状态轮询定时器

// 身份选择弹窗状态
const showIdentityDialog = ref(false)
const selectedIdentity = ref(null) // 'intern' | 'campus' | 'jobhop' | 'custom'
const customIdentity = ref('') // 自定义身份输入

// 预设身份的 AI 首次提问消息
const IDENTITY_GREETINGS = {
  intern: {
    role: 'assistant',
    content: `你好！我是你的简历助手 👋  
为了帮你找到合适的**实习机会**，我们可以从你最熟悉的部分开始。

比如：  
你目前读什么**专业**？学到哪些和实习相关的课程或知识？  
或者，有没有做过让你觉得特别有收获的**课程项目**或小实践？  
又或者，你希望尝试哪个方向的**实习**？为什么对它感兴趣？

不用着急写完整简历，先随便聊聊其中一点就好～`
  },
  campus: {
    role: 'assistant',
    content: `你好！我是你的简历助手 👋  
校招竞争激烈，但每个人都有独特的故事。我们可以从你最有信心的一块开始梳理。

比如：  
你最想投递什么类型的**岗位**？为什么觉得它适合你？  
或者，有没有一段**项目/实习**经历，让你觉得自己"真的搞定了点东西"？  
又或者，你在学校里做过哪些别人可能没有的经历（**比赛**、**科研**、**创业**、**社团**等）？

选一个你愿意多说几句的方向，我来帮你理清楚怎么写进简历～`
  },
  jobhop: {
    role: 'assistant',
    content: `你好！我是你的简历助手 👋  
跳槽或转型的关键，是让新公司看到你过去经验的价值。我们可以从你最想突出的部分聊起。

比如：  
你现在主要做什么**工作**？最近半年最有成就感的一件事是什么？  
或者，你希望下一步往哪个方向发展？是什么让你决定要**转型**？  
又或者，有没有一个**项目**，让你觉得"这段经历绝对值得写在简历里"？

不用马上全部回答，先说说其中一点，我来帮你提炼亮点 💡`
  }
}

// 获取认证 headers
function getAuthHeaders() {
  const headers = {
    'Content-Type': 'application/json'
  }
  if (token.value) {
    headers['Authorization'] = `Bearer ${token.value}`
  }
  return headers
}

function setCurrentSession(id) {
  const normalized = id || ''
  sessionId.value = normalized
  activeSessionId.value = normalized
  if (normalized) {
    localStorage.setItem('resumeAssistantSessionId', normalized)
  } else {
    localStorage.removeItem('resumeAssistantSessionId')
  }
}

function getSessionLockedHint() {
  return '助手正在回复或等待确认，暂时不能切换会话'
}

function clearSessionTransientState() {
  uploadedFiles.value = []
  userInput.value = ''
  dialogUserInput.value = ''
  showStartDialog.value = false
  if (loadingTextInterval) {
    clearTimeout(loadingTextInterval)
    loadingTextInterval = null
  }
}

async function loadSessions() {
  if (!isLoggedIn.value) return []
  try {
    const response = await fetch('/sessions', {
      method: 'GET',
      headers: getAuthHeaders()
    })
    if (response.status === 401) {
      logout()
      return []
    }
    if (!response.ok) {
      throw new Error(`加载会话失败: ${response.status}`)
    }
    const data = await response.json()
    sessions.value = Array.isArray(data) ? data : []
    return sessions.value
  } catch (error) {
    console.error('加载会话列表失败:', error)
    sessions.value = []
    return []
  }
}

async function createSession(title = '新会话') {
  const response = await fetch('/sessions', {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify({ title })
  })
  if (response.status === 401) {
    logout()
    return null
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(data.error || `创建会话失败: ${response.status}`)
  }
  return response.json()
}

function startRenameSession(session) {
  if (!session || isSessionSwitchLocked.value) return
  editingSessionId.value = session.session_id
  editingSessionTitle.value = session.title || ''
  nextTick(() => {
    const target = document.querySelector('.session-rename-input')
    if (target) target.focus()
  })
}

function cancelRenameSession() {
  editingSessionId.value = ''
  editingSessionTitle.value = ''
}

// 打开会话菜单
function openSessionMenu(session, event) {
  if (isSessionSwitchLocked.value) {
    alert(getSessionLockedHint())
    return
  }
  menuSession.value = session
  // 计算菜单位置
  const rect = event.currentTarget.getBoundingClientRect()
  menuPosition.value = {
    top: `${rect.bottom + 4}px`,
    left: `${rect.left - 100}px` // 菜单宽度约 140px，向左偏移使其右对齐
  }
  showSessionMenu.value = true
}

// 关闭会话菜单
function closeSessionMenu() {
  showSessionMenu.value = false
  menuSession.value = null
}

// 打开重命名弹窗
function openRenameModal() {
  if (!menuSession.value) return
  renameSessionTitle.value = menuSession.value.title || ''
  showSessionMenu.value = false
  showRenameModal.value = true
}

// 关闭重命名弹窗
function closeRenameModal() {
  showRenameModal.value = false
  renameSessionTitle.value = ''
  menuSession.value = null
}

// 提交重命名
async function submitRenameModal() {
  if (!menuSession.value) return
  const title = renameSessionTitle.value.trim()
  if (!title) {
    alert('会话标题不能为空')
    return
  }
  if (title.length > 50) {
    alert('会话标题不能超过50个字符')
    return
  }
  try {
    const response = await fetch(`/sessions/${menuSession.value.session_id}`, {
      method: 'PATCH',
      headers: getAuthHeaders(),
      body: JSON.stringify({ title })
    })
    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      throw new Error(data.error || `重命名失败: ${response.status}`)
    }
    await loadSessions()
    closeRenameModal()
  } catch (error) {
    console.error('重命名会话失败:', error)
    alert(error.message || '重命名失败，请稍后重试')
  }
}

// 打开删除确认弹窗
function openDeleteModal() {
  if (!menuSession.value) return
  showSessionMenu.value = false
  showDeleteModal.value = true
}

// 关闭删除确认弹窗
function closeDeleteModal() {
  showDeleteModal.value = false
  menuSession.value = null
}

// 确认删除
async function confirmDeleteSession() {
  if (!menuSession.value) return
  isSessionBusy.value = true
  try {
    const response = await fetch(`/sessions/${menuSession.value.session_id}`, {
      method: 'DELETE',
      headers: getAuthHeaders()
    })
    if (response.status === 401) {
      logout()
      return
    }
    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      throw new Error(data.error || `删除失败: ${response.status}`)
    }
    sessions.value = sessions.value.filter(s => s.session_id !== menuSession.value.session_id)
    const removedActive = menuSession.value.session_id === sessionId.value
    if (removedActive) {
      if (sessions.value.length > 0) {
        setCurrentSession(sessions.value[0].session_id)
        await loadInitialData()
      } else {
        const created = await createSession('新会话')
        await loadSessions()
        if (created?.session_id) {
          setCurrentSession(created.session_id)
          await loadInitialData()
        }
      }
    }
    closeDeleteModal()
  } catch (error) {
    console.error('删除会话失败:', error)
    alert(error.message || '删除会话失败，请稍后重试')
  } finally {
    isSessionBusy.value = false
  }
}

async function switchSession(targetSessionId) {
  if (!targetSessionId || targetSessionId === sessionId.value) {
    return
  }
  if (isSessionSwitchLocked.value) {
    alert(getSessionLockedHint())
    return
  }
  isSessionBusy.value = true
  try {
    cancelRenameSession()
    clearSessionTransientState()
    setCurrentSession(targetSessionId)
    
    // 清除当前会话的本地数据
    messages.value = []
    resumeData.value = {}
    zhResume.value = {}
    enResume.value = {}
    jdData.value = {}
    
    // 加载新会话的数据（不调用 loadSessions 避免重新排序）
    await loadSessionData(targetSessionId)
  } finally {
    isSessionBusy.value = false
  }
}

// 加载会话数据
async function loadSessionData(sessionIdToLoad) {
  if (!sessionIdToLoad) return
  
  try {
    // 会话切换时默认回到中文简历视图
    resetLangToZhDefault()

    const zhResponse = await fetch('/load_resume', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ session_id: sessionIdToLoad, lang: 'zh' })
    })
    const enResponse = await fetch('/load_resume', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ session_id: sessionIdToLoad, lang: 'en' })
    })

    if (zhResponse.status === 401 || enResponse.status === 401) {
      logout()
      return
    }

    const zhData = await zhResponse.json()
    const enData = await enResponse.json()
    
    // 设置简历数据（使用整个响应对象，与 loadInitialData 保持一致）
    zhResume.value = zhData
    enResume.value = enData
    resumeData.value = zhData
    

    const [messagesRes, jdRes] = await Promise.all([
      fetch('/load_conversation', {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ session_id: sessionIdToLoad })
      }),
      fetch('/load_jd', {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ session_id: sessionIdToLoad })
      })
    ])

    if (messagesRes.ok) {
      const messagesData = await messagesRes.json()
      // 后端直接返回数组，不是 { messages: [...] } 格式
      messages.value = Array.isArray(messagesData) ? messagesData : (messagesData.messages || [])
    }

    if (jdRes.ok) {
      const jdResData = await jdRes.json()
      jdData.value = jdResData.jd_data || {}
    }

    scrollToBottom()
  } catch (error) {
    console.error('加载会话数据失败:', error)
  }
}

async function createSessionAndSwitch() {
  if (isSessionSwitchLocked.value) {
    alert(getSessionLockedHint())
    return
  }
  isSessionBusy.value = true
  try {
    // 从后端获取当前会话的中文简历（确保获取的是中文，不是当前显示的语言）
    let currentZhResume = null
    try {
      const zhRes = await fetch('/load_resume', {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ session_id: sessionId.value || 'default', lang: 'zh' })
      })
      if (zhRes.ok) {
        currentZhResume = await zhRes.json()
        console.log('[createSession] 获取到的简历:', currentZhResume)
        console.log('[createSession] 简历语言检测 - basics:', currentZhResume?.basics)
      }
    } catch (e) {
      console.error('[createSession] 获取简历失败:', e)
    }
    
    const created = await createSession('新会话')
    if (!created?.session_id) return
    
    // 如果有中文简历，复制到新会话
    console.log('[createSession] 准备复制简历到新会话:', created.session_id)
    console.log('[createSession] 简历数据:', currentZhResume)
    if (currentZhResume && Object.keys(currentZhResume).length > 0) {
      console.log('[createSession] 正在保存中文简历...')
      await fetch('/save_resume', {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({
          resume_data: currentZhResume,
          session_id: created.session_id,
          lang: 'zh'
        })
      })
    }
    
    await loadSessions()
    setCurrentSession(created.session_id)
    clearSessionTransientState()
    
    // 添加欢迎消息（使用模板字符串确保换行正确显示）
    const welcomeMessage = {
      id: 'welcome_' + Date.now(),
      role: 'assistant',
      content: `**你好！边聊边改简历，改完还能模拟面试——我来陪你把求职这件事儿打磨好。**\n\n先跟我说说你在投什么方向？如果手头有JD，也可以点右上角「目标岗位」上传，我帮你分析得更准。`
    }
    
    // 保存欢迎消息到后端（只保存欢迎消息，不复制旧会话的聊天记录）
    await fetch('/save_conversation', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        session_id: created.session_id,
        messages: [welcomeMessage]
      })
    })
    
    await loadInitialData()
  } catch (error) {
    console.error('创建会话失败:', error)
    alert(error.message || '创建会话失败，请稍后重试')
  } finally {
    isSessionBusy.value = false
  }
}

// 检查登录状态
async function checkLoginStatus() {
  const savedToken = localStorage.getItem('access_token')
  const savedUser = localStorage.getItem('user')

  if (savedToken && savedUser) {
    token.value = savedToken
    currentUser.value = JSON.parse(savedUser)
    isLoggedIn.value = true
  } else {
    isLoggedIn.value = false
    currentUser.value = null
  }
}

// 监听 localStorage 变化（用于跨标签页同步登录状态）
function handleStorageChange(event) {
  if (event.key === 'access_token' || event.key === 'user') {
    checkLoginStatus()
  }
}

// 初始化简历数据
onMounted(async () => {
  // 等待登录状态检查完成
  await checkLoginStatus()

  // 如果未登录，不加载数据
  if (!isLoggedIn.value) {
    return
  }

  // 加载数据并检查是否首次访问
  await loadInitialData()
})

// 初始化响应式检测
onMounted(() => {
  // 初始检测
  checkMobileView()

  // 监听 localStorage 变化
  window.addEventListener('storage', handleStorageChange)

  // 使用 ResizeObserver 监听窗口大小变化
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => {
      checkMobileView()
    })
    resizeObserver.observe(document.body)
  } else {
    // 降级方案：使用 window resize 事件
    window.addEventListener('resize', checkMobileView)
  }

  // 监听聊天容器滚动事件（带节流）
  // 使用 nextTick 确保 DOM 已挂载
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.addEventListener('scroll', handleScroll)
    } else {
    }
  })

  // 初始化页面滚动状态（直接访问 /admin 时）
  if (route.path === '/admin') {
    document.body.style.overflow = 'auto'
  } else {
    document.body.style.overflow = 'hidden'
  }
})

// 清理监听器
onUnmounted(() => {
  window.removeEventListener('storage', handleStorageChange)
  stopParsingStatusPoll()
  if (messagesContainer.value) {
    messagesContainer.value.removeEventListener('scroll', handleScroll)
  }
  if (resizeObserver) {
    resizeObserver.disconnect()
  } else {
    window.removeEventListener('resize', checkMobileView)
  }
})

// 监听路由变化，自动更新登录状态
watch(() => route.path, async () => {
  // 切换到首页时，检查登录状态并加载数据
  if (route.path === '/') {
    await checkLoginStatus()
    if (isLoggedIn.value) {
      await loadInitialData()
    }
  }

  // /admin 页面启用滚动，其他页面禁用页面级滚动
  if (route.path === '/admin') {
    document.body.style.overflow = 'auto'
  } else {
    document.body.style.overflow = 'hidden'
  }
})

// 加载初始数据的函数（同时检查首次访问）
async function loadInitialData() {
  // 防止重复调用
  if (isLoadingInitialData.value) {
    return
  }
  isLoadingInitialData.value = true

  // 页面刷新/首次加载时默认显示中文简历
  resetLangToZhDefault()

  try {
    let sessionList = await loadSessions()
    if (sessionList.length === 0) {
      const created = await createSession('新会话')
      if (created?.session_id) {
        sessionList = await loadSessions()
      }
    }

    if (sessionList.length === 0) {
      throw new Error('未能初始化会话')
    }

    const currentSessionExists = sessionId.value && sessionList.some(s => s.session_id === sessionId.value)
    const currentSessionId = currentSessionExists ? sessionId.value : sessionList[0].session_id
    setCurrentSession(currentSessionId)

    // 分别加载中文和英文简历（顺序加载，确保先加载中文）
    const zhResponse = await fetch('/load_resume', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ session_id: currentSessionId, lang: 'zh' })
    })
    const enResponse = await fetch('/load_resume', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ session_id: currentSessionId, lang: 'en' })
    })

    // 如果认证失败，跳转登录
    if (zhResponse.status === 401 || enResponse.status === 401) {
      logout()
      return
    }

    const zhData = await zhResponse.json()
    const enData = await enResponse.json()

    // 分别保存到对应的变量
    zhResume.value = zhData
    enResume.value = enData

    // 设置当前显示的简历
    resumeData.value = zhData


    // 检查解析状态（使用中文简历的状态）
    const parsingStatus = zhData.parsing_status || 'none'

    // 如果正在解析中，显示上传弹窗并启动轮询
    if (parsingStatus === 'parsing') {
      showUploadDialog.value = true
      hasResumeFileSelected.value = true
      isParsingResume.value = true
      resumeImagePreview.value = ''
      resumeImageFile.value = null
      isResumePdf.value = false
      // 启动轮询检查解析状态
      startParsingStatusPoll()
      return
    }

    // 停止轮询（如果之前在轮询中）
    stopParsingStatusPoll()

    // 加载JD数据
    try {
      const jdResponse = await fetch('/load_jd', {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ session_id: currentSessionId })
      })
      if (jdResponse.status === 401) {
        logout()
        return
      }
      const jdResult = await jdResponse.json()
      if (jdResult && Object.keys(jdResult).length > 0) {
        jdData.value = jdResult
      }
    } catch (jdError) {
    }

    // 检查是否首次进入（无简历且无聊天记录）
    // 修正判断逻辑：检查basics中是否有有效字段
    const { parsing_status, basics, ...rest } = zhData
    const hasResume = basics && (basics.name || basics.target_position || Object.keys(rest).length > 0)

    // 加载对话历史
    try {
      const convResponse = await fetch('/load_conversation', {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ session_id: currentSessionId })
      })
      if (convResponse.status === 401) {
        logout()
        return
      }
      const convData = await convResponse.json()
      const hasChatHistory = Array.isArray(convData) && convData.length > 0

      // 首次进入检测：无简历且无聊天记录
      if (!hasResume && !hasChatHistory) {
        showStartDialog.value = true
        return
      }

      if (hasChatHistory) {
        messages.value = convData
      } else {
        messages.value = [{
          id: Date.now(),
          role: 'assistant',
          content: '你好！我是简历助手，有什么可以帮助你的吗？你可以询问简历信息等。简历内容、修改'
        }]
      }
    } catch (convError) {
      messages.value = [{
        id: Date.now(),
        role: 'assistant',
        content: '你好！我是简历助手，有什么可以帮助你的吗？你可以询问简历内容、修改简历信息等。'
      }]
    }
  } catch (error) {
    console.error('加载数据失败:', error)
    messages.value = [{
      id: Date.now(),
      role: 'assistant',
      content: '抱歉，加载简历失败。请稍后重试。'
    }]
  } finally {
    activeSessionId.value = sessionId.value
    isLoadingInitialData.value = false
  }
}

// 轮询检查解析状态
async function pollParsingStatus() {
  try {
    const response = await fetch('/api/resume/parsing_status', {
      method: 'GET',
      headers: getAuthHeaders()
    })

    if (response.status === 401) {
      logout()
      return
    }

    const data = await response.json()
    const status = data.parsing_status || 'none'

    if (status === 'completed') {
      // 解析完成，重新加载简历数据
      stopParsingStatusPoll()
      isParsingResume.value = false
      showUploadDialog.value = false
      // 重新加载简历
      await loadResumeData()

      // 刷新页面后首次加载时，需要调用 first_message_from_resume 生成首次提问
      // 检查是否已有聊天历史，如果没有则调用
      if (messages.value.length === 0) {
        isLoading.value = true
        try {
          const firstMsgResponse = await fetch('/api/chat/first_message_from_resume', {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify({
              session_id: sessionId.value || ''
            })
          })

          const firstMsgData = await firstMsgResponse.json()
          isLoading.value = false

          if (!firstMsgData.error && firstMsgData.message) {
            const aiMessage = firstMsgData.message || firstMsgData.content
            messages.value = [{
              id: Date.now(),
              role: 'assistant',
              content: aiMessage
            }]

            if (firstMsgData.session_id) {
              setCurrentSession(firstMsgData.session_id)
            }

            // 保存对话到数据库
            try {
              await fetch('/save_conversation', {
                method: 'POST',
                headers: getAuthHeaders(),
                body: JSON.stringify({
                  session_id: sessionId.value,
                  messages: [{ type: 'ai', content: aiMessage }]
                })
              })
            } catch (saveError) {
              console.error('保存对话失败:', saveError)
            }

            // 保存到数据库和上下文
            try {
              await fetch('/api/chat/save_ai_message', {
                method: 'POST',
                headers: getAuthHeaders(),
                body: JSON.stringify({
                  message: aiMessage,
                  session_id: sessionId.value || ''
                })
              })
            } catch (saveAiError) {
              console.error('保存 AI 消息失败:', saveAiError)
            }
          }
        } catch (firstMsgError) {
          isLoading.value = false
          console.error('获取首次提问失败:', firstMsgError)
        }
      }
    } else if (status === 'failed') {
      // 解析失败
      console.error('❌ 解析失败')
      stopParsingStatusPoll()
      isParsingResume.value = false
      alert('简历解析失败，请重新上传')
    }
    // 如果还是 'parsing'，继续轮询
  } catch (error) {
    console.error('检查解析状态失败:', error)
  }
}

// 启动解析状态轮询
function startParsingStatusPoll() {
  // 先清除之前的轮询
  stopParsingStatusPoll()
  // 立即检查一次
  pollParsingStatus()
  // 每3秒检查一次
  parsingStatusPollInterval = setInterval(pollParsingStatus, 3000)
}

// 停止解析状态轮询
function stopParsingStatusPoll() {
  if (parsingStatusPollInterval) {
    clearInterval(parsingStatusPollInterval)
    parsingStatusPollInterval = null
  }
}

// 加载简历数据（支持双语）
async function loadResumeData() {
  try {
    const response = await fetch('/load_resume', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        session_id: sessionId.value || 'default',
        lang: currentLang.value
      })
    })

    if (response.status === 401) {
      logout()
      return
    }

    const data = await response.json()

    // 根据当前语言保存到对应的简历
    if (currentLang.value === 'zh') {
      zhResume.value = data
    } else {
      enResume.value = data
    }

    // 同时更新 resumeData 供显示
    resumeData.value = data

    // 更新简历内容
    const { parsing_status, ...resumeContent } = data
    if (resumeContent && Object.keys(resumeContent).length > 0) {
    }
  } catch (error) {
    console.error('加载简历数据失败:', error)
  }
}

// 登出
function logout() {
  localStorage.removeItem('access_token')
  localStorage.removeItem('user')
  localStorage.removeItem('resumeAssistantSessionId')
  token.value = ''
  currentUser.value = null
  isLoggedIn.value = false
  sessions.value = []
  activeSessionId.value = ''
  sessionId.value = ''
  // 刷新页面
  window.location.reload()
}

// 发送消息
async function sendMessage() {
  // 检查登录状态
  if (!isLoggedIn.value) {
    alert('请先登录')
    return
  }
  if ((!userInput.value.trim() && uploadedFiles.value.length === 0) || isLoading.value) return

  // 如果有未处理的 confirm area，取消它（用户发送了新消息）
  const pendingConfirmIndex = messages.value.findIndex(m => m.type === 'confirm' && !m.handled)
  if (pendingConfirmIndex !== -1) {
    messages.value[pendingConfirmIndex] = {
      ...messages.value[pendingConfirmIndex],
      handled: true
    }
    hasConfirmArea.value = false
  }

  const input = userInput.value.trim()
  userInput.value = ''

  // 先保存附件
  const currentAttachments = [...uploadedFiles.value]

  // 清空上传的文件列表
  uploadedFiles.value = []

  // 创建消息ID - 使用更可靠的方式确保唯一性
  const baseId = Date.now() * 1000 + Math.floor(Math.random() * 1000)
  const userMessageId = baseId
  const streamMessageId = baseId + 1

  // 添加用户消息
  const userMessage = {
    id: userMessageId,
    role: 'user',
    content: input,
    attachments: currentAttachments
  }
  messages.value.push(userMessage)

  // 预先添加一个流式消息占位符 - 确保role属性始终为assistant
  const streamingMessage = {
    id: streamMessageId,
    role: 'assistant',
    content: '',
    streaming: true
  }
  messages.value.push(streamingMessage)

  isLoading.value = true
  isResponding.value = true
  // 启动加载文案切换
  loadingText.value = '正在处理中...'
  let textIndex = 0
  const loadingTexts = ['正在处理中...', '正在思考中...', '正在总结提炼回答...']
  const textDelays = [8000, 10000] // 第一个8秒，第二个10秒，之后一直显示第三个

  // 使用setTimeout实现不同时长的文案切换
  const runTextCycle = () => {
    textIndex++
    if (textIndex < loadingTexts.length) {
      loadingText.value = loadingTexts[textIndex]
      const delay = textIndex < textDelays.length ? textDelays[textIndex] : 0
      if (delay > 0) {
        loadingTextInterval = setTimeout(runTextCycle, delay)
      }
    }
  }
  loadingTextInterval = setTimeout(runTextCycle, textDelays[0])
  
  try {
    // 创建FormData对象
    const formData = new FormData()
    formData.append('message', input)
    formData.append('session_id', sessionId.value)
    formData.append('lang', currentLang.value)

    // 添加上传的文件
    // 注意：uploadedFiles 在函数开头已被清空，这里附件信息已保存在 currentAttachments 中
    currentAttachments.forEach((fileObj) => {
      formData.append('files', fileObj.file)
    })

    // 使用fetch API处理SSE流式响应
    const response = await fetch('/chat', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token.value}`
      },
      body: formData
    })
    
    if (!response.ok) {
      throw new Error(`HTTP错误! 状态: ${response.status}`)
    }
    
    // 检查是否支持流式响应
    if (!response.body) {
      throw new Error('不支持流式响应')
    }
    
    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    
    while (true) {
      const { done, value } = await reader.read()
      
      if (done) break
      
      // 解码接收到的数据
      buffer += decoder.decode(value, { stream: true })
      
      // 处理接收到的SSE消息
      let newlineIndex
      while ((newlineIndex = buffer.indexOf('\n\n')) !== -1) {
        const message = buffer.substring(0, newlineIndex)
        buffer = buffer.substring(newlineIndex + 2)
        
        // 处理SSE消息格式（data: {...}）
        if (message.startsWith('data: ')) {
          const jsonData = message.substring(6).trim()
          if (jsonData) {
            try {
              const data = JSON.parse(jsonData)

              if (data.type === 'stream') {
                // 停止加载文案切换
                if (loadingTextInterval) {
                  clearTimeout(loadingTextInterval)
                  loadingTextInterval = null
                }
                // 收到第一个流式数据时，立即隐藏加载指示器
                isLoading.value = false

                // 实时流式更新内容
                const index = messages.value.findIndex(m => m.id === streamMessageId)
                if (index !== -1) {
                  // 创建新对象触发 Vue 响应式更新
                  messages.value[index] = {
                    ...messages.value[index],
                    content: data.content,
                    streaming: true
                  }
                }
              } else if (data.type === 'final') {
                // 停止加载文案切换
                if (loadingTextInterval) {
                  clearTimeout(loadingTextInterval)
                  loadingTextInterval = null
                }
                // 更新流式消息为最终内容
                const index = messages.value.findIndex(m => m.id === streamMessageId)
                if (index !== -1) {
                  // 使用对象展开语法，确保role属性不会被修改
                  messages.value[index] = {
                    ...messages.value[index],
                    content: data.content,
                    streaming: false
                  }
                }
                // 收到第一个流式输出后，隐藏加载指示器
                isLoading.value = false
                // 更新会话ID并保存到localStorage
                if (data.session_id) {
                  setCurrentSession(data.session_id)
                }
              } else if (data.type === 'tool_call') {
                // 停止加载文案切换
                if (loadingTextInterval) {
                  clearTimeout(loadingTextInterval)
                  loadingTextInterval = null
                }
                // 收到工具调用通知，隐藏加载指示器，显示正在调用工具
                isLoading.value = false
                // 更新流式消息，显示正在调用工具
                const index = messages.value.findIndex(m => m.id === streamMessageId)
                if (index !== -1) {
                  messages.value[index] = {
                    ...messages.value[index],
                    content: data.content,
                    streaming: true
                  }
                }
              } else if (data.type === 'confirm') {
                // 停止加载文案切换
                if (loadingTextInterval) {
                  clearTimeout(loadingTextInterval)
                  loadingTextInterval = null
                }
                isLoading.value = false
                isResponding.value = false
                // 添加新的确认消息（不更新现有消息，确保按钮在AI消息下方显示）
                messages.value.push({
                  id: data.id || Date.now(),
                  role: 'assistant',
                  type: 'confirm',
                  content: data.content,
                  options: data.options,
                  confirm_id: data.confirm_id,
                  streaming: false
                })
                // 标记有 confirm area，禁用输入
                hasConfirmArea.value = true
              } else if (data.type === 'end') {
                // 结束信号，关闭连接
                isResponding.value = false
                // 只在流式响应结束时调用一次updateResumeData()
                updateResumeData()
                // 更新会话ID并保存到localStorage
                if (data.session_id) {
                  setCurrentSession(data.session_id)
                }
                await loadSessions()
                break
              }
            } catch (e) {
              console.error('解析JSON失败:', e)
              // 记录原始消息以便调试
              console.error('原始消息:', jsonData)
            }
          }
        }
      }
    }
  } catch (error) {
    console.error('发送消息失败:', error)
    let errorMessage = '抱歉，发送消息失败。'
    if (error.name === 'AbortError') {
      errorMessage = '请求超时，请稍后重试。'
    } else if (error.message) {
      errorMessage = `抱歉，发送消息失败: ${error.message}`
    }
    messages.value.push({
      id: Date.now(),
      role: 'assistant',
      content: errorMessage
    })
  } finally {
    isLoading.value = false
    isResponding.value = false

    // 保存对话历史（过滤掉未处理的 confirm 消息，已处理的 confirm 消息保留 handled 状态）
    try {
      const messagesToSave = messages.value.filter(m => !(m.type === 'confirm' && m.confirm_id && !m.handled))
      await fetch('/save_conversation', {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({
          session_id: sessionId.value,
          messages: messagesToSave
        })
      })
    } catch (saveError) {
      console.error('保存对话历史失败:', saveError)
    }
    await loadSessions()
  }
}

// 处理确认按钮点击
async function handleOptionClick({ confirm_id, value }) {
  // 找到并标记确认消息为已处理
  const confirmMsgIndex = messages.value.findIndex(m => m.type === 'confirm' && m.confirm_id === confirm_id)
  if (confirmMsgIndex !== -1) {
    messages.value[confirmMsgIndex] = {
      ...messages.value[confirmMsgIndex],
      handled: true
    }
  }
  // 清除 confirm area 状态
  hasConfirmArea.value = false

  // 如果点击取消，不调用 graph
  if (value === 'cancel') {
    return
  }

  // 发送确认回复到 /chat，触发 handle_confirmation → formatter_llm → save_resume_tool
  const confirmMessage = `[CONFIRM_REPLY:${confirm_id}:${value}]`

  const baseId = Date.now() * 1000 + Math.floor(Math.random() * 1000)
  const userMessageId = baseId
  const streamMessageId = baseId + 1

  messages.value.push({
    id: userMessageId,
    role: 'user',
    content: value === 'confirm' ? '确认保存' : '取消'
  })

  messages.value.push({
    id: streamMessageId,
    role: 'assistant',
    content: '',
    streaming: true
  })

  try {
    isLoading.value = true
    isResponding.value = true

    const formData = new FormData()
    formData.append('message', confirmMessage)
    formData.append('session_id', sessionId.value)
    formData.append('lang', currentLang.value)

    const response = await fetch('/chat', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token.value}` },
      body: formData
    })

    if (!response.ok) throw new Error(`HTTP错误! 状态: ${response.status}`)

    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''

    while (true) {
      const { done, value: chunk } = await reader.read()
      if (done) break

      buffer += decoder.decode(chunk, { stream: true })

      let newlineIndex
      while ((newlineIndex = buffer.indexOf('\n\n')) !== -1) {
        const message = buffer.substring(0, newlineIndex)
        buffer = buffer.substring(newlineIndex + 2)

        if (message.startsWith('data: ')) {
          const jsonData = message.substring(6).trim()
          if (!jsonData) continue

          try {
            const data = JSON.parse(jsonData)

            if (data.type === 'stream') {
              isLoading.value = false
              const idx = messages.value.findIndex(m => m.id === streamMessageId)
              if (idx !== -1) {
                messages.value[idx] = { ...messages.value[idx], content: data.content, streaming: true }
              }
            } else if (data.type === 'final') {
              isLoading.value = false
              isResponding.value = false
              const idx = messages.value.findIndex(m => m.id === streamMessageId)
              if (idx !== -1) {
                messages.value[idx] = { ...messages.value[idx], content: data.content, streaming: false }
              }
              if (data.session_id) {
                setCurrentSession(data.session_id)
              }
              updateResumeData()
            } else if (data.type === 'end') {
              isResponding.value = false
              updateResumeData()
              if (data.session_id) {
                setCurrentSession(data.session_id)
              }
              await loadSessions()
            }
          } catch (e) {
            console.error('解析JSON失败:', e)
          }
        }
      }
    }
  } catch (error) {
    console.error('确认操作失败:', error)
    isLoading.value = false
    isResponding.value = false
    messages.value.push({
      id: Date.now() + 2,
      role: 'assistant',
      content: '处理确认请求失败，请重试。'
    })
  } finally {
    await loadSessions()
  }
}

// 检测哪个模块发生了变化
function detectChangedModule(oldData, newData) {
  if (!oldData || !newData) return ''

  const modules = ['basics', 'education', 'work_experience', 'project_experience', 'others', 'self_evaluation']

  for (const module of modules) {
    const oldVal = JSON.stringify(oldData[module] || {})
    const newVal = JSON.stringify(newData[module] || {})

    if (oldVal !== newVal) {
      return module
    }
  }

  return ''
}

// 更新简历数据（使用当前语言）
async function updateResumeData() {
  try {
    // 先从服务器获取新数据
    const response = await fetch('/load_resume', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        session_id: sessionId.value || 'default',
        lang: currentLang.value
      })
    })
    const newData = await response.json()

    // 保存旧数据用于比较
    const oldData = resumeData.value ? JSON.parse(JSON.stringify(resumeData.value)) : null

    // 更新当前语言的简历缓存
    if (currentLang.value === 'zh') {
      zhResume.value = newData
    } else {
      enResume.value = newData
    }

    // 更新显示
    resumeData.value = newData

    // 检测变化并触发高亮
    const changedModule = detectChangedModule(oldData, newData)

    if (changedModule) {
      highlightedModule.value = changedModule

      // 3秒后清除高亮
      setTimeout(() => {
        highlightedModule.value = ''
      }, 3000)
    }
  } catch (error) {
    console.error('更新简历数据失败:', error)
  }
}

// 处理键盘事件
function handleKeyDown(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    sendMessage()
  }
}

// 处理粘贴事件
function handlePaste(event) {
  // 检查剪贴板是否有图片
  const clipboardItems = (event.clipboardData || event.originalEvent.clipboardData).items
  for (let item of clipboardItems) {
    if (item.kind === 'file' && item.type.startsWith('image/')) {
      // 获取图片文件
      const file = item.getAsFile()
      if (file) {
        // 创建文件对象，包含文件信息和缩略图URL
        const fileObj = {
          id: Date.now(),
          file: file,
          name: `pasted_image_${Date.now()}.${file.type.split('/')[1]}`,
          type: file.type,
          thumbnail: ''
        }
        
        // 生成缩略图
        const reader = new FileReader()
        reader.onload = (e) => {
          fileObj.thumbnail = e.target.result
        }
        reader.readAsDataURL(file)
        
        uploadedFiles.value.push(fileObj)
      }
      break
    }
  }
}

// 处理文件选择
function handleFileSelect(event) {
  const files = event.target.files
  if (files.length > 0) {
    for (let i = 0; i < files.length; i++) {
      const file = files[i]
      // 检查文件类型
      if (file.type.match(/(image\/(png|jpeg|jpg)|application\/pdf)/)) {
        // 创建文件对象，包含文件信息和缩略图URL
        const fileObj = {
          id: Date.now() + i,
          file: file,
          name: file.name,
          type: file.type,
          thumbnail: ''
        }
        
        // 生成缩略图
        if (file.type.startsWith('image/')) {
          const reader = new FileReader()
          reader.onload = (e) => {
            fileObj.thumbnail = e.target.result
          }
          reader.readAsDataURL(file)
        } else if (file.type === 'application/pdf') {
          // PDF文件使用默认图标
          fileObj.thumbnail = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjQiIGhlaWdodD0iMjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHBhdGggZD0iTTMgN2MwLTEuMS45LTIgMi0yaDE2YzEuMSAwIDIgLjkgMiAydjEwYzAgMS4xLS45IDItMiAyaC0zLjVjLS42IDAtMS4yLjItMS41LjV2LS41SDV2NkgzbTIgOWguNXYxLjVoLTJ6TTUgMTBoMTZ2Mi41SDV6TTUgMTZoMTR2Mi41SDV6Ii8+PC9zdmc+'
        }
        
        uploadedFiles.value.push(fileObj)
      }
    }
  }
}

// 删除上传的文件
function deleteFile(fileId) {
  uploadedFiles.value = uploadedFiles.value.filter(file => file.id !== fileId)
}

// 打开图片预览
function openImagePreview(file) {
  if (file.thumbnail) {
    previewImageUrl.value = file.thumbnail
    showImagePreview.value = true
  }
}

// 关闭图片预览
function closeImagePreview() {
  showImagePreview.value = false
  previewImageUrl.value = ''
}

// ==================== JD 上传功能（新增） ====================

// 打开岗位信息弹窗
function openJDDialog() {
  if (guardWhileResponding('目标岗位编辑')) return
  isJDDialogOpen.value = true
  // 如果已有岗位信息，直接显示编辑表单
  if (jdData.value && Object.keys(jdData.value).length > 0) {
    jdInputMode.value = 'form'
    jdFormData.value = {
      ...jdData.value,
      preferred_qualifications_text: arrayToCommaSeparated(jdData.value.preferred_qualifications),
      highlights_text: arrayToCommaSeparated(jdData.value.highlights)
    }
  } else {
    jdInputMode.value = 'input'
    jdInputText.value = ''
    jdInputImage.value = ''
    jdFormData.value = {
      company: '',
      position: '',
      department: '',
      location: '',
      job_type: '',
      salary: '',
      description: '',
      requirements: {
        education: '',
        experience: '',
        skills: [],
        language: ''
      },
      preferred_qualifications: [],
      highlights: [],
      preferred_qualifications_text: '',
      highlights_text: ''
    }
  }
  newSkill.value = ''
}

// 退回上一步
function backToInputMode() {
  jdInputMode.value = 'input'
}

// 关闭JD弹窗
function closeJDDialog() {
  isJDDialogOpen.value = false
}

// ==================== 简历编辑功能（新增） ====================

// 打开简历编辑弹窗
function openResumeEditDialog() {
  if (guardWhileResponding('简历编辑')) return
  // 深拷贝当前简历数据
  if (resumeData.value && Object.keys(resumeData.value).length > 0) {
    resumeFormData.value = JSON.parse(JSON.stringify(resumeData.value))
  } else {
    // 使用空结构
    resumeFormData.value = {
      basics: { name: '', gender: '', phone: '', email: '', target_position: '' },
      education: [],
      work_experience: [],
      project_experience: [],
      others: { skills: [], certificates: [], languages: [] },
      self_evaluation: []
    }
  }

  // 确保所有必要字段都存在（防御性编程）
  resumeFormData.value.education = resumeFormData.value.education || []
  resumeFormData.value.work_experience = resumeFormData.value.work_experience || []
  resumeFormData.value.project_experience = resumeFormData.value.project_experience || []
  resumeFormData.value.others = resumeFormData.value.others || { skills: [], certificates: [], languages: [] }
  resumeFormData.value.self_evaluation = resumeFormData.value.self_evaluation || []

  // 初始化日期范围和"至今"标志
  const initDateRange = (item) => {
    if (!item.date_range) {
      item.date_range = ['', '']
    }
    const start = item.date_range[0] ? item.date_range[0].replace('.', '-') : ''
    const end = item.date_range[1] && item.date_range[1] !== '至今'
      ? item.date_range[1].replace('.', '-')
      : ''
    item._startDate = start
    item._endDate = end
    item._isPresent = item.date_range[1] === '至今'
  }

  // 为每项工作经历初始化日期
  resumeFormData.value.work_experience.forEach(work => {
    initDateRange(work)
    work._detailsText = arrayToMultiline(work.details || [])
  })

  // 为每项项目经历初始化日期
  resumeFormData.value.project_experience.forEach(proj => {
    initDateRange(proj)
    proj._detailsText = arrayToMultiline(proj.details || [])
  })

  // 为每项教育经历初始化日期
  resumeFormData.value.education.forEach(edu => {
    initDateRange(edu)
    edu.major_courses = edu.major_courses || []
    edu.academic_achievements = edu.academic_achievements || []
    edu.honors_awards = edu.honors_awards || []
    edu._majorCoursesText = arrayToEducationText(edu.major_courses)
    edu._academicAchievementsText = arrayToEducationText(edu.academic_achievements)
    edu._honorsAwardsText = arrayToEducationText(edu.honors_awards)
  })

  // 转换自我评价为多行文本
  selfEvalText.value = arrayToMultiline(resumeFormData.value.self_evaluation || [])

  isResumeEditDialogOpen.value = true
}

// 将日期范围转换为保存格式
function convertDateRangeToSave(item) {
  const start = item._startDate ? item._startDate.replace('-', '.') : ''
  const end = item._isPresent ? '至今' : (item._endDate ? item._endDate.replace('-', '.') : '')
  item.date_range = [start, end]
  // 清理临时字段
  delete item._startDate
  delete item._endDate
  delete item._isPresent
}

// 关闭简历编辑弹窗
function closeResumeEditDialog() {
  isResumeEditDialogOpen.value = false
  photoError.value = ''
}

// 处理证件照上传
function handlePhotoUpload(event) {
  const file = event.target.files[0]
  photoError.value = ''
  
  if (!file) return
  
  // 1. 验证文件类型
  if (!file.type.startsWith('image/')) {
    photoError.value = '请选择图片文件（jpg、png 等）'
    return
  }
  
  // 2. 验证文件大小（限制 2MB）
  if (file.size > 2 * 1024 * 1024) {
    photoError.value = '照片大小不能超过 2MB，请选择更小的图片'
    event.target.value = ''
    return
  }
  
  // 3. 读取并验证图片尺寸
  const reader = new FileReader()
  reader.onload = (e) => {
    const img = new Image()
    img.onload = () => {
      const width = img.width
      const height = img.height
      
      // 1寸照片比例约 3:3.5，允许误差 ±20%
      const ratio = width / height
      const targetRatio = 3 / 3.5  // 约 0.857
      const minRatio = targetRatio * 0.8
      const maxRatio = targetRatio * 1.2
      
      // 像素尺寸限制
      const minPixels = 200
      
      if (width < minPixels || height < minPixels) {
        photoError.value = `照片像素太低，请选择至少 ${minPixels}x${minPixels} 像素的图片`
        return
      }
      
      // 比例提示（非强制）
      if (ratio < minRatio || ratio > maxRatio) {
        console.warn('照片比例偏离 1 寸标准')
      }
      
      // 4. 压缩图片
      compressAndSave(img)
    }
    img.src = e.target.result
  }
  reader.readAsDataURL(file)
}

// 压缩并保存图片
function compressAndSave(img) {
  const canvas = document.createElement('canvas')
  const ctx = canvas.getContext('2d')
  
  // 限制最大尺寸
  const MAX_SIZE = 400
  let width = img.width
  let height = img.height
  
  if (width > height) {
    if (width > MAX_SIZE) {
      height = height * (MAX_SIZE / width)
      width = MAX_SIZE
    }
  } else {
    if (height > MAX_SIZE) {
      width = width * (MAX_SIZE / height)
      height = MAX_SIZE
    }
  }
  
  canvas.width = width
  canvas.height = height
  ctx.drawImage(img, 0, 0, width, height)
  
  // 转换为 Base64（质量 0.8）
  resumeFormData.value.basics.photo = canvas.toDataURL('image/jpeg', 0.8)
}

// 删除证件照
function removePhoto() {
  resumeFormData.value.basics.photo = ''
  photoError.value = ''
  // 清空文件输入
  const input = document.querySelector('.photo-input')
  if (input) input.value = ''
}

// 添加学历
function addEducation() {
  resumeFormData.value.education.push({
    school_name: '',
    major: '',
    degree: '',
    date_range: ['', ''],
    school_tags: [],
    major_courses: [],
    academic_achievements: [],
    honors_awards: [],
    _majorCoursesText: '',
    _academicAchievementsText: '',
    _honorsAwardsText: ''
  })
}

// 删除学历
function removeEducation(index) {
  resumeFormData.value.education.splice(index, 1)
}

function moveArrayItem(items, fromIndex, offset) {
  const toIndex = fromIndex + offset
  if (!Array.isArray(items)) return
  if (fromIndex < 0 || toIndex < 0) return
  if (fromIndex >= items.length || toIndex >= items.length) return
  const [movedItem] = items.splice(fromIndex, 1)
  items.splice(toIndex, 0, movedItem)
}

function moveEducation(index, offset) {
  moveArrayItem(resumeFormData.value.education, index, offset)
}

// 添加学校标签
function addSchoolTag(edu) {
  if (edu.newSchoolTag && edu.newSchoolTag.trim()) {
    edu.school_tags.push(edu.newSchoolTag.trim())
    edu.newSchoolTag = ''
  }
}

// 添加工作经历
function addWork() {
  resumeFormData.value.work_experience.push({
    company_name: '',
    job_title: '',
    date_range: ['', ''],
    job_type: '全职',
    details: ['']
  })
}

// 删除工作经历
function removeWork(index) {
  resumeFormData.value.work_experience.splice(index, 1)
}

function moveWork(index, offset) {
  moveArrayItem(resumeFormData.value.work_experience, index, offset)
}

// 添加工作内容
function addWorkDetail(work) {
  work.details.push('')
}

// 删除工作内容
function removeWorkDetail(work, index) {
  work.details.splice(index, 1)
}

// 添加项目经历
function addProject() {
  resumeFormData.value.project_experience.push({
    project_name: '',
    role: '',
    date_range: ['', ''],
    details: ['']
  })
}

// 删除项目经历
function removeProject(index) {
  resumeFormData.value.project_experience.splice(index, 1)
}

function moveProject(index, offset) {
  moveArrayItem(resumeFormData.value.project_experience, index, offset)
}

// 添加项目内容
function addProjectDetail(proj) {
  proj.details.push('')
}

// 删除项目内容
function removeProjectDetail(proj, index) {
  proj.details.splice(index, 1)
}

// 标签添加方法
function addResumeSkill() {
  if (newResumeSkill.value.trim()) {
    resumeFormData.value.others.skills.push(newResumeSkill.value.trim())
    newResumeSkill.value = ''
  }
}

function addResumeCert() {
  if (newResumeCert.value.trim()) {
    resumeFormData.value.others.certificates.push(newResumeCert.value.trim())
    newResumeCert.value = ''
  }
}

function addResumeLang() {
  if (newResumeLang.value.trim()) {
    resumeFormData.value.others.languages.push(newResumeLang.value.trim())
    newResumeLang.value = ''
  }
}

// 加载简历数据（使用当前语言）
async function loadResume() {
  try {
    const response = await fetch('/load_resume', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        session_id: sessionId.value || 'default',
        lang: currentLang.value
      })
    })
    const data = await response.json()

    // 更新当前语言的简历缓存
    if (currentLang.value === 'zh') {
      zhResume.value = data
    } else {
      enResume.value = data
    }

    // 更新显示
    resumeData.value = data
  } catch (error) {
    console.error('加载简历失败:', error)
  }
}

// 辅助函数：日期格式转换 YYYY-MM -> YYYY.MM
function formatDateForSave(dateStr) {
  if (!dateStr) return ''
  // 如果已经是 YYYY.MM 格式，直接返回
  if (dateStr.includes('.')) return dateStr
  // YYYY-MM 转换为 YYYY.MM
  return dateStr.replace('-', '.')
}

function arrayToEducationText(arr) {
  if (!arr || !Array.isArray(arr)) return ''
  return arr.map(item => item?.trim()).filter(Boolean).join('、')
}

function educationTextToArray(text) {
  if (!text) return []
  return text
    .split(/[\n、,，;；]+/)
    .map(item => item.trim())
    .filter(Boolean)
}

// 将数组转换为多行文本（用于编辑）
function arrayToMultiline(arr) {
  if (!arr || !Array.isArray(arr)) return ''
  return arr.filter(item => item.trim()).join('\n')
}

// 将多行文本转换为数组（用于保存）
function multilineToArray(text) {
  if (!text) return []
  return text.split('\n').map(line => line.trim()).filter(line => line)
}

function getDateRangeValidationMessage(item, sectionLabel, index) {
  const start = (item?._startDate || '').trim()
  const end = (item?._endDate || '').trim()
  const isPresent = Boolean(item?._isPresent)

  if (!start && !end && !isPresent) return ''
  if (!start) return `${sectionLabel}${index + 1}的时间范围缺少开始时间`
  if (!isPresent && !end) return `${sectionLabel}${index + 1}的时间范围缺少结束时间，或请勾选“至今”`
  return ''
}

function validateResumeDateRanges() {
  const validations = [
    { items: resumeFormData.value.education || [], label: '教育经历 ' },
    { items: resumeFormData.value.work_experience || [], label: '工作经历 ' },
    { items: resumeFormData.value.project_experience || [], label: '项目经历 ' }
  ]

  for (const { items, label } of validations) {
    for (const [index, item] of items.entries()) {
      const message = getDateRangeValidationMessage(item, label, index)
      if (message) return message
    }
  }

  return ''
}

// 保存简历
async function saveResume() {
  if (guardWhileResponding('简历保存')) return
  const dateRangeError = validateResumeDateRanges()
  if (dateRangeError) {
    alert(dateRangeError)
    return
  }
  isSaving.value = true
  try {
    // 复制数据进行处理
    const dataToSave = JSON.parse(JSON.stringify(resumeFormData.value))

    // 处理性别：保密 -> 空字符串
    if (dataToSave.basics.gender === '保密') {
      dataToSave.basics.gender = ''
    }

    // 处理日期格式：确保是 YYYY.MM 格式
    dataToSave.education?.forEach(edu => {
      convertDateRangeToSave(edu)
      edu.major_courses = educationTextToArray(edu._majorCoursesText)
      edu.academic_achievements = educationTextToArray(edu._academicAchievementsText)
      edu.honors_awards = educationTextToArray(edu._honorsAwardsText)
      delete edu._majorCoursesText
      delete edu._academicAchievementsText
      delete edu._honorsAwardsText
      delete edu.theses
    })
    dataToSave.work_experience?.forEach(work => {
      convertDateRangeToSave(work)
      // 将多行文本转换回数组
      if (work._detailsText !== undefined) {
        work.details = multilineToArray(work._detailsText)
        delete work._detailsText
      }
    })
    dataToSave.project_experience?.forEach(proj => {
      convertDateRangeToSave(proj)
      // 将多行文本转换回数组
      if (proj._detailsText !== undefined) {
        proj.details = multilineToArray(proj._detailsText)
        delete proj._detailsText
      }
    })

    // 将自我评价多行文本转换回数组
    dataToSave.self_evaluation = multilineToArray(selfEvalText.value)

    const response = await fetch('/save_resume', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        resume_data: dataToSave,
        session_id: sessionId.value || 'default',
        lang: currentLang.value
      })
    })

    if (response.ok) {
      closeResumeEditDialog()
      // 刷新简历渲染
      loadResume()
    } else {
      alert('保存失败，请重试')
    }
  } catch (error) {
    console.error('保存简历失败:', error)
    alert('保存失败，请重试')
  } finally {
    isSaving.value = false
  }
}

// 解析岗位信息
async function parseJD() {
  if (!jdInputText.value.trim() && !jdInputImage.value) {
    alert('请输入职位描述或粘贴图片')
    return
  }

  isParsingJD.value = true
  try {
    const response = await fetch('/parse_jd', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        text: jdInputText.value,
        image: jdInputImage.value
      })
    })

    if (!response.ok) {
      throw new Error('识别失败')
    }

    const result = await response.json()

    if (result.error) {
      alert('识别失败: ' + result.error)
      return
    }

    // 确保所有字段都存在
    jdFormData.value = {
      company: result.company || '',
      position: result.position || '',
      department: result.department || '',
      location: result.location || '',
      job_type: result.job_type || '',
      salary: result.salary || '',
      description: result.description || '',
      requirements: {
        education: result.requirements?.education || '',
        experience: result.requirements?.experience || '',
        skills: result.requirements?.skills || [],
        language: result.requirements?.language || ''
      },
      preferred_qualifications: result.preferred_qualifications || [],
      highlights: result.highlights || []
    }

    jdInputMode.value = 'form'
  } catch (error) {
    console.error('识别失败:', error)
    alert('识别失败，请重试')
  } finally {
    isParsingJD.value = false
  }
}

// 保存岗位信息
async function saveJD() {
  isSaving.value = true
  try {
    const response = await fetch('/save_jd', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        jd_data: jdFormData.value,
        session_id: sessionId.value
      })
    })

    const result = await response.json()

    if (result.success) {
      jdData.value = { ...jdFormData.value }
      isJDDialogOpen.value = false
    } else {
      alert('保存失败: ' + (result.error || '未知错误'))
    }
  } catch (error) {
    console.error('保存失败:', error)
    alert('保存失败，请重试')
  } finally {
    isSaving.value = false
  }
}

// 添加技能标签
function addSkill() {
  const skill = newSkill.value.trim()
  if (skill && !jdFormData.value.requirements.skills.includes(skill)) {
    jdFormData.value.requirements.skills.push(skill)
    newSkill.value = ''
  }
}

// 删除技能标签
function removeSkill(index) {
  jdFormData.value.requirements.skills.splice(index, 1)
}

// 处理图片上传
function handleJDImageUpload(event) {
  const file = event.target.files[0]
  if (file) {
    const reader = new FileReader()
    reader.onload = (e) => {
      jdInputImage.value = e.target.result
    }
    reader.readAsDataURL(file)
  }
}

// 处理粘贴事件（支持图片粘贴）
function handleJDPaste(event) {
  const items = event.clipboardData?.items
  if (!items) return

  for (let i = 0; i < items.length; i++) {
    const item = items[i]
    if (item.type.startsWith('image/')) {
      event.preventDefault()
      const file = item.getAsFile()
      const reader = new FileReader()
      reader.onload = (e) => {
        jdInputImage.value = e.target.result
      }
      reader.readAsDataURL(file)
      break
    }
  }
}

// 辅助函数：将逗号分隔的文本转换为数组
function parseCommaSeparated(text) {
  if (!text) return []
  return text.split(',').map(s => s.trim()).filter(s => s)
}

// 将数组转换为逗号分隔的文本（用于表单绑定）
function arrayToCommaSeparated(arr) {
  if (!arr || !Array.isArray(arr)) return ''
  return arr.join(', ')
}

// 更新优先条件数组
function updatePreferredQualifications() {
  jdFormData.value.preferred_qualifications = parseCommaSeparated(jdFormData.value.preferred_qualifications_text)
}

// 更新亮点数组
function updateHighlights() {
  jdFormData.value.highlights = parseCommaSeparated(jdFormData.value.highlights_text)
}

// 在解析后初始化文本字段
function initFormTexts() {
  jdFormData.value.preferred_qualifications_text = arrayToCommaSeparated(jdFormData.value.preferred_qualifications)
  jdFormData.value.highlights_text = arrayToCommaSeparated(jdFormData.value.highlights)
}

// 在解析成功后调用初始化
const originalParseJD = parseJD
parseJD = async function() {
  await originalParseJD()
  if (jdInputMode.value === 'form') {
    initFormTexts()
  }
}

// 打开全屏弹窗
function openFullscreenDialog() {
  dialogUserInput.value = userInput.value
  isFullscreenDialogOpen.value = true
  nextTick(() => {
    const dialogTextarea = document.querySelector('.dialog-textarea')
    if (dialogTextarea) {
      dialogTextarea.focus()
    }
  })
}

// 关闭全屏弹窗（不保存内容）
function closeFullscreenDialog() {
  isFullscreenDialogOpen.value = false
}

// 保存弹窗内容到输入框
function saveDialogContent() {
  userInput.value = dialogUserInput.value
  isFullscreenDialogOpen.value = false
}

// 提交弹窗内容
function submitFullscreenDialog() {
  if (dialogUserInput.value.trim()) {
    userInput.value = dialogUserInput.value.trim()
    isFullscreenDialogOpen.value = false
    sendMessage()
  }
}

// 监听ESC键关闭弹窗
function handleDialogKeydown(event) {
  if (event.key === 'Escape') {
    closeFullscreenDialog()
  } else if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
    submitFullscreenDialog()
  }
}

// ==================== 首次进入选择弹窗 ====================

// 打开开始选择弹窗（首次进入且无简历时）
function openStartDialog() {
  showStartDialog.value = true
}

// 关闭开始弹窗
function closeStartDialog() {
  showStartDialog.value = false
}

// 从空白创建简历 - 打开身份选择弹窗
function startFromBlank() {
  closeStartDialog()
  // 打开身份选择弹窗
  showIdentityDialog.value = true
  selectedIdentity.value = null
  customIdentity.value = ''
}

// 关闭身份选择弹窗
function closeIdentityDialog() {
  showIdentityDialog.value = false
  selectedIdentity.value = null
  customIdentity.value = ''
}

// 从身份选择返回上一步（回到开始选择弹窗）
function backToStartFromIdentity() {
  showIdentityDialog.value = false
  selectedIdentity.value = null
  customIdentity.value = ''
  showStartDialog.value = true
}

// 处理预设身份选择
function selectIdentity(identity) {
  selectedIdentity.value = identity
  customIdentity.value = ''
}

// 确认身份选择
async function confirmIdentitySelection() {
  if (!selectedIdentity.value) {
    alert('请选择一个身份类型')
    return
  }

  if (selectedIdentity.value === 'custom' && !customIdentity.value.trim()) {
    alert('请输入你的身份描述')
    return
  }

  // 先保存选择的身份，因为 closeIdentityDialog 会重置 selectedIdentity
  const identity = selectedIdentity.value
  const customDesc = customIdentity.value.trim()

  closeIdentityDialog()
  closeStartDialog()

  if (identity === 'custom') {
    // 自定义身份：调用后端 API 获取首次提问
    isLoading.value = true
    try {
      const response = await fetch('/api/chat/first_message', {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({
          user_type: 'custom',
          custom_identity: customDesc,
          session_id: sessionId.value || ''
        })
      })

      const data = await response.json()
      
      isLoading.value = false

      if (data.error) {
        alert(data.error)
        return
      }

      const aiMessage = data.message || data.content

      messages.value = [{
        id: Date.now(),
        role: 'assistant',
        content: aiMessage
      }]

      // 保存 session_id 到全局
      if (data.session_id) {
        setCurrentSession(data.session_id)
      }

      // 保存对话到数据库（后端已保存，但确保前端也保存一次）
      try {
        await fetch('/save_conversation', {
          method: 'POST',
          headers: getAuthHeaders(),
          body: JSON.stringify({
            session_id: sessionId.value,
            messages: [
              { type: 'human', content: `我的身份描述：${customDesc}` },
              { type: 'ai', content: aiMessage }
            ]
          })
        })
      } catch (saveError) {
        console.error('保存对话失败:', saveError)
      }

      // 调用后端保存 AI 消息（保存到数据库和上下文）
      try {
        await fetch('/api/chat/save_ai_message', {
          method: 'POST',
          headers: getAuthHeaders(),
          body: JSON.stringify({
            message: aiMessage,
            session_id: sessionId.value || ''
          })
        })
      } catch (saveAiError) {
        console.error('保存 AI 消息失败:', saveAiError)
      }
    } catch (error) {
      isLoading.value = false
      console.error('获取首次提问失败:', error)
      alert('获取首次提问失败，请重试')
    }
  } else {
    // 预设身份：直接使用预制消息并保存到数据库
    isLoading.value = true
    const greeting = IDENTITY_GREETINGS[identity]
    const aiMessage = greeting.content

    messages.value = [{
      id: Date.now(),
      role: greeting.role,
      content: aiMessage
    }]

    // 保存对话到数据库
    try {
      await fetch('/save_conversation', {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({
          session_id: sessionId.value,
          messages: [{ type: 'ai', content: aiMessage }]
        })
      })
    } catch (saveError) {
      console.error('保存对话失败:', saveError)
    }

    isLoading.value = false

    // 调用后端保存 AI 消息
    try {
      const saveResponse = await fetch('/api/chat/save_ai_message', {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({
          message: greeting.content,
          session_id: sessionId.value || ''
        })
      })

      const saveData = await saveResponse.json()
      if (saveData.session_id) {
        setCurrentSession(saveData.session_id)
      }
    } catch (saveError) {
      console.error('保存消息失败:', saveError)
    }
  }
}

// 显示上传弹窗
function showUploadResumeDialog() {
  closeStartDialog()
  showUploadDialog.value = true
  resumeImagePreview.value = ''
  resumeImageFile.value = null
  isResumePdf.value = false
  hasResumeFileSelected.value = false  // 重置，允许返回
}

// 触发文件选择器
function triggerResumeFileSelect() {
  resumeFileInput.value?.click()
}

// 关闭上传弹窗
function closeUploadDialog() {
  showUploadDialog.value = false
  resumeImagePreview.value = ''
  resumeImageFile.value = null
  isResumePdf.value = false
  hasResumeFileSelected.value = false
}

// 返回上一步（回到开始选择弹窗）
function backToStartDialog() {
  showUploadDialog.value = false
  resumeImagePreview.value = ''
  resumeImageFile.value = null
  isResumePdf.value = false
  hasResumeFileSelected.value = false
  showStartDialog.value = true
}

// 重新选择文件
function reselectResumeFile() {
  resumeImagePreview.value = ''
  resumeImageFile.value = null
  isResumePdf.value = false
  hasResumeFileSelected.value = false  // 重置，允许返回
}

// 处理简历图片选择
function handleResumeImageSelect(event) {
  const file = event.target.files[0]
  if (!file) return

  // 验证文件类型
  if (!file.type.startsWith('image/') && file.type !== 'application/pdf') {
    alert('请上传图片文件（JPG、PNG）或 PDF')
    return
  }

  // 验证文件大小（5MB）
  if (file.size > 5 * 1024 * 1024) {
    alert('文件大小不能超过 5MB')
    return
  }

  resumeImageFile.value = file
  hasResumeFileSelected.value = true  // 已选择文件，不可返回上一步

  // 检测是否是PDF文件
  isResumePdf.value = file.type === 'application/pdf'

  // 生成预览（PDF不生成图片预览，只显示图标）
  if (isResumePdf.value) {
    resumeImagePreview.value = 'pdf'  // 设置为非空值以触发界面切换
  } else {
    const reader = new FileReader()
    reader.onload = (e) => {
      resumeImagePreview.value = e.target.result
    }
    reader.readAsDataURL(file)
  }
}

// 解析并保存简历
async function parseAndSaveResume() {
  if (guardWhileResponding('简历解析')) return
  if (!resumeImageFile.value) {
    alert('请先选择简历图片')
    return
  }

  isParsingResume.value = true
  resumeImagePreview.value = ''

  try {
    // 使用 FormData 直接上传文件
    const formData = new FormData()
    formData.append('file', resumeImageFile.value)

    // 构建 headers（不设置 Content-Type，让浏览器自动处理 multipart/form-data）
    const headers = {}
    if (token.value) {
      headers['Authorization'] = `Bearer ${token.value}`
    }

    const response = await fetch('/api/resume/parse_and_save', {
      method: 'POST',
      headers: headers,
      body: formData
    })

    const data = await response.json()

    if (data.success) {
      // 更新当前语言的简历缓存
      if (currentLang.value === 'zh') {
        zhResume.value = data.resume_data
      } else {
        enResume.value = data.resume_data
      }

      // 更新简历数据
      resumeData.value = data.resume_data
      closeUploadDialog()

      // 获取 AI 的首次针对性提问
      isLoading.value = true
      try {
        const firstMsgResponse = await fetch('/api/chat/first_message_from_resume', {
          method: 'POST',
          headers: getAuthHeaders(),
          body: JSON.stringify({
            session_id: sessionId.value || ''
          })
        })

        const firstMsgData = await firstMsgResponse.json()

        isLoading.value = false

        if (firstMsgData.error) {
          // 如果获取首次提问失败，使用通用欢迎消息
          messages.value = [{
            id: Date.now(),
            role: 'assistant',
            content: '简历已解析完成！我是简历助手，有什么可以帮助你的吗？'
          }]
        } else {
          // 显示 AI 的首次针对性提问
          const aiMessage = firstMsgData.message || firstMsgData.content
          messages.value = [{
            id: Date.now(),
            role: 'assistant',
            content: aiMessage
          }]

          // 保存 session_id 到全局
          if (firstMsgData.session_id) {
            setCurrentSession(firstMsgData.session_id)
          }

          // 保存对话到数据库
          try {
            await fetch('/save_conversation', {
              method: 'POST',
              headers: getAuthHeaders(),
              body: JSON.stringify({
                session_id: sessionId.value,
                messages: [{ type: 'ai', content: aiMessage }]
              })
            })
          } catch (saveError) {
            console.error('保存对话失败:', saveError)
          }

          // 调用后端保存 AI 消息（保存到数据库和上下文）
          try {
            await fetch('/api/chat/save_ai_message', {
              method: 'POST',
              headers: getAuthHeaders(),
              body: JSON.stringify({
                message: aiMessage,
                session_id: sessionId.value || ''
              })
            })
          } catch (saveAiError) {
            console.error('保存 AI 消息失败:', saveAiError)
          }
        }
      } catch (firstMsgError) {
        isLoading.value = false
        console.error('获取首次提问失败:', firstMsgError)
        // 使用通用欢迎消息
        messages.value = [{
          id: Date.now(),
          role: 'assistant',
          content: '简历已解析完成！我是简历助手，有什么可以帮助你的吗？'
        }]
      }
    } else {
      alert('解析失败：' + data.error)
      // 解析失败，保留状态让用户可以重试
    }
  } catch (error) {
    console.error('解析简历失败:', error)
    alert('解析简历失败，请稍后重试')
  } finally {
    // 重置前端状态
    isParsingResume.value = false
    hasResumeFileSelected.value = false
  }
}

// 自动滚动到底部，添加丝滑过渡效果
function scrollToBottom() {
  if (messagesContainer.value) {
    // 立即滚动到底部，带有丝滑过渡效果
    messagesContainer.value.scrollTo({
      top: messagesContainer.value.scrollHeight,
      behavior: 'smooth'
    })
  }
}

// 滑动至底部按钮状态
const showScrollToBottomButton = ref(false)
let scrollThrottleTimer = null

// 检查是否需要显示滑动至底部按钮
function checkScrollPosition() {
  if (!messagesContainer.value) {
    return
  }
  
  const { scrollTop, scrollHeight, clientHeight } = messagesContainer.value
  const distanceFromBottom = scrollHeight - scrollTop - clientHeight
  
  
  // 滚动距离底部超过20像素时显示按钮
  showScrollToBottomButton.value = distanceFromBottom > 1500
}

// 滚动事件节流处理（100ms间隔）
function handleScroll() {
  if (scrollThrottleTimer) return
  
  scrollThrottleTimer = setTimeout(() => {
    scrollThrottleTimer = null
    checkScrollPosition()
  }, 100)
}

// 点击滑动至底部按钮
function handleScrollToBottomClick() {
  scrollToBottom()
  // 滚动完成后隐藏按钮
  setTimeout(() => {
    showScrollToBottomButton.value = false
  }, 500)
}

// 监听消息列表变化，自动滚动到底部
// 使用deep: true监听消息内容的变化，确保流式输出时也能自动滚动
watch(
  () => messages.value,
  () => {
    // 使用nextTick确保DOM已更新
    nextTick(() => {
      scrollToBottom()
      // 检查是否需要显示滚动按钮
      checkScrollPosition()
    })
  },
  { deep: true }
)
</script>

<template>
  <!-- 首次进入选择弹窗 -->
  <Teleport to="body">
    <Transition name="dialog-fade">
      <div v-if="showStartDialog" class="modal-mask">
        <div class="modal-container start-modal" @click.stop>
          <div class="modal-header">
            <div class="header-badge">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                <polyline points="14 2 14 8 20 8"></polyline>
              </svg>
            </div>
            <h2>创建简历</h2>
          </div>
          <p class="modal-desc">选择一种方式开始创建你的简历</p>
          <div class="option-list">
            <button @click="startFromBlank" class="option-item">
              <div class="optionGraphic graphic-plus">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <line x1="12" y1="5" x2="12" y2="19"></line>
                  <line x1="5" y1="12" x2="19" y2="12"></line>
                </svg>
              </div>
              <div class="option-content">
                <span class="option-label">从空白创建</span>
                <span class="option-sublabel">手动填写，逐步完善</span>
              </div>
              <svg class="option-arrow" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="9 18 15 12 9 6"></polyline>
              </svg>
            </button>
            <button @click="showUploadResumeDialog" class="option-item primary">
              <div class="optionGraphic graphic-upload">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                  <polyline points="17 8 12 3 7 8"></polyline>
                  <line x1="12" y1="3" x2="12" y2="15"></line>
                </svg>
              </div>
              <div class="option-content">
                <span class="option-label">上传已有简历</span>
                <span class="option-sublabel">支持图片或 PDF，自动解析</span>
              </div>
              <svg class="option-arrow" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="9 18 15 12 9 6"></polyline>
              </svg>
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>

  <!-- 身份选择弹窗 -->
  <Teleport to="body">
    <Transition name="dialog-fade">
      <div v-if="showIdentityDialog" class="modal-mask">
        <div class="modal-container start-modal identity-selection" @click.stop>
          <div class="modal-header">
            <div class="header-badge">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                <circle cx="12" cy="7" r="4"></circle>
              </svg>
            </div>
            <h2>选择你的身份</h2>
            <div class="modal-actions">
              <button @click="backToStartFromIdentity" class="modal-back">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <line x1="19" y1="12" x2="5" y2="12"></line>
                  <polyline points="12 19 5 12 12 5"></polyline>
                </svg>
                返回
              </button>
            </div>
          </div>
          <p class="modal-desc">选择最符合你当前情况的身份类型</p>
          
          <div class="identity-cards-container">
            <!-- 四个身份卡片竖排 -->
            <div class="identity-cards-row">
              <!-- 寻找实习 -->
              <button 
                @click="selectIdentity('intern')" 
                :class="['identity-card', { active: selectedIdentity === 'intern' }]"
              >
                <div class="identity-icon">
                  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <path d="M22 10v6M2 10l10-5 10 5-10 5z"/>
                    <path d="M6 12v5c3 3 9 3 12 0v-5"/>
                  </svg>
                </div>
                <div class="identity-card-content">
                  <div class="identity-title">寻找实习</div>
                  <div class="identity-desc">正在寻找实习机会的学生</div>
                </div>
              </button>
              
              <!-- 校招应届 -->
              <button 
                @click="selectIdentity('campus')" 
                :class="['identity-card', { active: selectedIdentity === 'campus' }]"
              >
                <div class="identity-icon pink">
                  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <path d="M22 10v6M2 10l10-5 10 5-10 5z"/>
                    <path d="M6 12v5c3 3 9 3 12 0v-5"/>
                    <path d="M12 16v4"/>
                  </svg>
                </div>
                <div class="identity-card-content">
                  <div class="identity-title">校招应届</div>
                  <div class="identity-desc">准备参加校园招聘的应届毕业生</div>
                </div>
              </button>
              
              <!-- 跳槽转型 -->
              <button 
                @click="selectIdentity('jobhop')" 
                :class="['identity-card', { active: selectedIdentity === 'jobhop' }]"
              >
                <div class="identity-icon">
                  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <rect x="2" y="7" width="20" height="14" rx="2" ry="2"/>
                    <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>
                  </svg>
                </div>
                <div class="identity-card-content">
                  <div class="identity-title">跳槽转型</div>
                  <div class="identity-desc">计划跳槽的职场白领</div>
                </div>
              </button>

              <!-- 自定义 -->
              <button 
                @click="selectIdentity('custom')" 
                :class="['identity-card', { active: selectedIdentity === 'custom' }]"
              >
                <div class="identity-icon pink">
                  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                  </svg>
                </div>
                <div class="identity-card-content">
                  <div class="identity-title">自定义</div>
                  <div class="identity-desc">不符合上述选项，描述你的情况</div>
                </div>
              </button>
            </div>

            <!-- 自定义身份输入框 -->
            <div v-if="selectedIdentity === 'custom'" class="custom-identity-input">
              <textarea 
                v-model="customIdentity" 
                placeholder="请简单描述你的情况，例如：我是工作3年的产品经理，想转行做技术..."
                rows="3"
              ></textarea>
            </div>
          </div>

          <div class="modal-footer">
            <button @click="confirmIdentitySelection" :disabled="!selectedIdentity || (selectedIdentity === 'custom' && !customIdentity.trim())" class="btn-primary full-width">
              开始创建简历
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>

  <!-- 简历上传弹窗 -->
  <Teleport to="body">
    <Transition name="dialog-fade">
      <div v-if="showUploadDialog" class="modal-mask">
        <div class="modal-container upload-modal" @click.stop>
          <div class="modal-header">
            <div class="header-badge">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="17 8 12 3 7 8"></polyline>
                <line x1="12" y1="3" x2="12" y2="15"></line>
              </svg>
            </div>
            <h2>上传简历</h2>
            <div class="modal-actions">
              <!-- 未选择文件且不在解析中时显示返回按钮 -->
              <button v-if="!hasResumeFileSelected && !isParsingResume" @click="backToStartDialog" class="modal-back">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <line x1="19" y1="12" x2="5" y2="12"></line>
                  <polyline points="12 19 5 12 12 5"></polyline>
                </svg>
                返回
              </button>
            </div>
          </div>
          <div class="modal-body">
            <!-- 未选择文件且不在解析中时显示上传框 -->
            <div v-if="!resumeImagePreview && !isParsingResume" class="upload-box" @click="triggerResumeFileSelect()">
              <input type="file" accept="image/*,.pdf" @change="handleResumeImageSelect" ref="resumeFileInput" class="hidden-input" />
              <div class="upload-graphic">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                  <polyline points="17 8 12 3 7 8"></polyline>
                  <line x1="12" y1="3" x2="12" y2="15"></line>
                </svg>
              </div>
              <p class="upload-title">点击上传简历</p>
              <p class="upload-hint">自动解析并生成结构化简历</p>
              <span class="upload-formats">支持 JPG、PNG、PDF</span>
            </div>
            <!-- 解析中状态显示 -->
            <div v-if="isParsingResume && !resumeImagePreview" class="parsing-status">
              <div class="parsing-spinner"></div>
              <p class="parsing-text">简历正在解析中...</p>
              <p class="parsing-hint">请稍候，解析完成后将自动显示结果</p>
            </div>
            <div v-else-if="!isParsingResume && resumeImagePreview" class="preview-box">
              <!-- PDF文件预览 -->
              <div v-if="isResumePdf" class="pdf-preview">
                <div class="pdf-icon-wrapper">
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                    <polyline points="14 2 14 8 20 8"></polyline>
                    <line x1="16" y1="13" x2="8" y2="13"></line>
                    <line x1="16" y1="17" x2="8" y2="17"></line>
                    <polyline points="10 9 9 9 8 9"></polyline>
                  </svg>
                </div>
                <p class="pdf-filename">{{ resumeImageFile?.name }}</p>
                <p class="pdf-hint">PDF文件准备解析</p>
              </div>
              <!-- 图片预览 -->
              <img v-else :src="resumeImagePreview" alt="简历预览" class="preview-img" />
              <button @click="reselectResumeFile" class="btn-reselect">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                  <polyline points="17 8 12 3 7 8"></polyline>
                  <line x1="12" y1="3" x2="12" y2="15"></line>
                </svg>
                重新选择
              </button>
            </div>
          </div>
          <div class="modal-footer" v-if="resumeImagePreview || isParsingResume">
            <button @click="parseAndSaveResume" :disabled="isParsingResume || isResponding" class="btn-primary full-width">
              {{ isParsingResume ? '解析中...' : '开始解析' }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>

  <!-- 顶部导航栏（全屏宽度） -->
  <header class="app-header">
    <div class="header-content">
      <h1>
        <router-link to="/">
          <img src="@/assets/offerflow.svg" alt="OfferFlow" class="app-logo" />
        </router-link>
      </h1>
      <div class="header-info">
        <div class="header-contact">
          <span class="contact-link">联系我们</span>
          <div class="contact-tooltip">
            <p class="tooltip-text">进产品交流群请扫码添加</p>
            <p class="tooltip-text">备注"入群"更快通过~</p>
            <img src="@/assets/wechatcode.jpg" alt="微信" class="wechat-qr" />
          </div>
        </div>
        <template v-if="isLoggedIn">
          <span class="user-email">{{ currentUser?.email }}</span>
          <button @click="logout" class="logout-btn">登出</button>
        </template>
        <template v-else>
          <router-link to="/login" class="auth-link">登录</router-link>
          <router-link to="/register" class="auth-link">注册</router-link>
        </template>
      </div>
    </div>
  </header>

  <!-- 主内容区（居中显示） -->
  <div class="app-container">
    <!-- 路由视图：登录/注册/管理页面 -->
    <router-view v-if="!isLoggedIn || isAdminRoute"></router-view>

    <!-- 已登录且非管理页面：显示主内容（聊天界面） -->
    <div v-if="isLoggedIn && !isAdminRoute" class="main-content" :class="{ 'lang-switching': isSwitchingLang, 'session-busy': isSessionBusy }">
      <!-- 桌面端：并排显示 -->
      <template v-if="!isMobileView">
        <!-- 左侧聊天区 -->
      <div class="chat-section">
          <aside class="session-sidebar" :class="{ collapsed: !isSessionSidebarExpanded, 'session-busy': isSessionBusy }">
            <div class="session-sidebar-header">
              <!-- 新建按钮 -->
              <button
                class="session-create-btn"
                @click="createSessionAndSwitch"
                :class="{ loading: isSessionBusy }"
                :disabled="isSessionSwitchLocked"
                @mouseenter="(e) => showTooltip(e, isSessionSwitchLocked ? getSessionLockedHint() : '新建会话')"
                @mouseleave="hideTooltip"
              >
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" style="width: 20px !important; height: 20px !important; overflow: visible !important; pointer-events: none;">
                  <rect x="3" y="3" width="14" height="14" rx="2" stroke="#333" stroke-width="1.2"/>
                  <path d="M10 7V13M7 10H13" stroke="#333" stroke-width="1.2" stroke-linecap="round"/>
                </svg>
              </button>
              <!-- 展开/收起按钮 -->
              <button
                class="session-toggle-btn"
                @click="isSessionSidebarExpanded = !isSessionSidebarExpanded"
                @mouseenter="(e) => showTooltip(e, isSessionSidebarExpanded ? '收起侧边栏' : '展开侧边栏')"
                @mouseleave="hideTooltip"
              >
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" style="width: 20px !important; height: 20px !important; overflow: visible !important; pointer-events: none;">
                  <path fill="#333" d="M16.5 4C17.3284 4 18 4.67157 18 5.5V14.5C18 15.3284 17.3284 16 16.5 16H3.5C2.67157 16 2 15.3284 2 14.5V5.5C2 4.67157 2.67157 4 3.5 4H16.5ZM7 15H16.5C16.7761 15 17 14.7761 17 14.5V5.5C17 5.22386 16.7761 5 16.5 5H7V15ZM3.5 5C3.22386 5 3 5.22386 3 5.5V14.5C3 14.7761 3.22386 15 3.5 15H6V5H3.5Z"/>
                </svg>
              </button>
            </div>

            <!-- 仅在展开时显示会话列表 -->
            <div v-if="isSessionSidebarExpanded" class="session-list">
            <div
              v-for="session in sessions"
              :key="session.session_id"
              class="session-item"
              :class="{ active: session.session_id === activeSessionId }"
            >
              <button
                class="session-item-main"
                @click="switchSession(session.session_id)"
                :disabled="isSessionSwitchLocked || session.session_id === activeSessionId"
                :title="isSessionSwitchLocked ? getSessionLockedHint() : (session.title || '新会话')"
              >
                <template v-if="isSessionSidebarExpanded">
                  <span class="session-item-title">{{ session.title || '新会话' }}</span>
                </template>
                <template v-else>
                  <span class="session-item-dot"></span>
                </template>
              </button>
              <div v-if="isSessionSidebarExpanded" class="session-item-actions">
                <button 
                  class="session-more-btn" 
                  type="button"
                  @click.stop="openSessionMenu(session, $event)"
                >
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" style="width: 16px !important; height: 16px !important; overflow: visible !important;">
                    <circle cx="8" cy="4" r="1" fill="#555"/>
                    <circle cx="8" cy="8" r="1" fill="#555"/>
                    <circle cx="8" cy="12" r="1" fill="#555"/>
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </aside>

        <div class="chat-main">
          <div class="chat-container">
            <div class="messages-container" ref="messagesContainer">
              <ChatMessage
                v-for="message in messages"
                :key="message.id + '_' + (message.content?.length || 0)"
                :message="message"
                @optionClick="handleOptionClick"
              />
              <!-- 只有当没有过程消息且正在加载时才显示默认加载指示器 -->
            <div v-if="isLoading" class="loading-indicator">
              <div class="loading-spinner">
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                  <circle cx="10" cy="10" r="7" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-dasharray="32" stroke-dashoffset="10" opacity="0.3"/>
                  <path d="M10 3 A 7 7 0 0 1 10 17 A 7 7 0 0 1 10 3" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>
                </svg>
              </div>
              <span class="loading-text">{{ loadingText }}</span>
            </div>
            </div>

            <!-- 滑动至底部按钮 -->
            <Transition name="fade">
              <button
                v-if="showScrollToBottomButton"
                class="scroll-to-bottom-btn"
                @click="handleScrollToBottomClick"
              >
                <span class="scroll-arrow">↓</span>
              </button>
            </Transition>
          </div>
          
          <!-- 悬浮输入容器 -->
          <div class="floating-input-container">
            <!-- 文件上传区域 -->
            <div v-if="uploadedFiles.length > 0" class="uploaded-files">
              <div v-for="file in uploadedFiles" :key="file.id" class="file-thumbnail">
                <!-- 图片类型 - 支持点击预览 -->
                <div
                  v-if="file.type.startsWith('image/')"
                  class="file-icon image-icon"
                  :style="{ cursor: 'pointer' }"
                  @click="openImagePreview(file)"
                >
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>
                </div>
                <!-- PDF类型 - 不支持点击 -->
                <div v-else-if="file.type === 'application/pdf'" class="file-icon pdf-icon">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>
                </div>
                <div class="file-name">{{ file.name }}</div>
                <div @click="deleteFile(file.id)" class="delete-file-btn">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>
                </div>
              </div>
            </div>
            
            <div class="input-wrapper">
              <input
                type="file"
                ref="fileInput"
                multiple
                accept="image/png, image/jpeg, image/jpg, application/pdf"
                @change="handleFileSelect"
                style="display: none;"
              />
              <div class="textarea-container">
                <textarea
                  v-model="userInput"
                  @keydown="handleKeyDown"
                  @paste="handlePaste"
                  placeholder="输入你的问题或请求..."
                  rows="1"
                  :disabled="isUiInteractionLocked"
                ></textarea>
                <!-- 底部工具栏 -->
                <div class="toolbar">
                  <!-- 上传按钮 -->
                  <button
                    @click="fileInput?.click()"
                    class="icon-btn"
                    :disabled="isUiInteractionLocked"
                    @mouseenter="(e) => showTooltip(e, '上传文件')"
                    @mouseleave="hideTooltip"
                    @mousemove="(e) => { tooltipState.x = e.currentTarget.getBoundingClientRect().left + e.currentTarget.getBoundingClientRect().width / 2; tooltipState.y = e.currentTarget.getBoundingClientRect().bottom + 8 }"
                  >
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                      <polyline points="17 8 12 3 7 8"></polyline>
                      <line x1="12" y1="3" x2="12" y2="15"></line>
                    </svg>
                  </button>
                  <!-- 全屏按钮 -->
                  <button
                    @click="openFullscreenDialog"
                    class="icon-btn"
                    :disabled="isUiInteractionLocked"
                    @mouseenter="(e) => showTooltip(e, '全屏输入')"
                    @mouseleave="hideTooltip"
                    @mousemove="(e) => { tooltipState.x = e.currentTarget.getBoundingClientRect().left + e.currentTarget.getBoundingClientRect().width / 2; tooltipState.y = e.currentTarget.getBoundingClientRect().bottom + 8 }"
                  >
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"></path>
                    </svg>
                  </button>
                  <!-- 发送按钮 - 预留空间避免高度突变 -->
                  <div class="send-btn-placeholder" v-if="!(userInput.trim() || uploadedFiles.length > 0)"></div>
                  <button
                    v-if="userInput.trim() || uploadedFiles.length > 0"
                    @click="sendMessage"
                    class="icon-btn send-btn"
                    :disabled="isUiInteractionLocked"
                  >
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <line x1="22" y1="2" x2="11" y2="13"></line>
                      <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                    </svg>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧简历预览区 -->
      <div class="resume-section" :class="{ 'lang-switching': isSwitchingLang }">
        <div class="resume-content">
          <ResumePreview :data="resumeData" :highlighted-module="highlightedModule" :jd-data="jdData" :lang="currentLang" :session-id="sessionId" :is-language-switch-disabled="isLanguageSwitchDisabled" :is-language-switch-loading="isSwitchingLang" :is-operation-locked="isUiInteractionLocked" @open-jd-dialog="openJDDialog" @open-resume-edit="openResumeEditDialog" @toggle-lang="switchLang" />
        </div>
      </div>
      </template>

      <!-- 移动端：Tab 切换显示 -->
      <template v-else>
        <!-- 聊天 Tab 内容 -->
        <Transition name="tab-content" mode="out-in">
          <div v-if="currentTab === 'chat'" class="mobile-chat-view" key="chat">
            <div class="chat-container">
              <div class="messages-container" ref="messagesContainer">
                <ChatMessage
                  v-for="message in messages"
                  :key="message.id + '_' + (message.content?.length || 0)"
                  :message="message"
                  @optionClick="handleOptionClick"
                />
                <div v-if="isLoading" class="loading-indicator">
                  <div class="loading-spinner">
                    <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                      <circle cx="10" cy="10" r="7" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-dasharray="32" stroke-dashoffset="10" opacity="0.3"/>
                      <path d="M10 3 A 7 7 0 0 1 10 17 A 7 7 0 0 1 10 3" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>
                    </svg>
                  </div>
                  <span class="loading-text">{{ loadingText }}</span>
                </div>
              </div>
              
              <!-- 滑动至底部按钮 -->
              <Transition name="fade">
                <button
                  v-if="showScrollToBottomButton"
                  class="scroll-to-bottom-btn"
                  @click="handleScrollToBottomClick"
                >
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#666" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M6 9l6 6 6-6"/>
                  </svg>
                </button>
              </Transition>
            </div>
            
            <!-- 悬浮输入容器 -->
            <div class="floating-input-container mobile-input">
              <div v-if="uploadedFiles.length > 0" class="uploaded-files">
                <div v-for="file in uploadedFiles" :key="file.id" class="file-thumbnail">
                  <div v-if="file.type.startsWith('image/')" class="file-icon image-icon" :style="{ cursor: 'pointer' }" @click="openImagePreview(file)">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>
                  </div>
                  <div v-else-if="file.type === 'application/pdf'" class="file-icon pdf-icon">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>
                  </div>
                  <div class="file-name">{{ file.name }}</div>
                  <div @click="deleteFile(file.id)" class="delete-file-btn">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                  </div>
                </div>
              </div>
              
              <div class="input-wrapper">
                <input type="file" ref="fileInput" multiple accept="image/png, image/jpeg, image/jpg, application/pdf" @change="handleFileSelect" style="display: none;" />
                <div class="textarea-container">
                  <textarea v-model="userInput" @keydown="handleKeyDown" @paste="handlePaste" placeholder="输入你的问题或请求..." rows="1" :disabled="isUiInteractionLocked"></textarea>
                  <div class="toolbar mobile-toolbar">
                    <button @click="fileInput?.click()" class="icon-btn" :disabled="isUiInteractionLocked">
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
                    </button>
                    <button @click="openFullscreenDialog" class="icon-btn" :disabled="isUiInteractionLocked">
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"></path></svg>
                    </button>
                    <div class="send-btn-placeholder" v-if="!(userInput.trim() || uploadedFiles.length > 0)"></div>
                    <button v-if="userInput.trim() || uploadedFiles.length > 0" @click="sendMessage" class="icon-btn send-btn" :disabled="isUiInteractionLocked">
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 简历 Tab 内容 -->
          <div v-else-if="currentTab === 'resume'" class="mobile-resume-view" :class="{ 'lang-switching': isSwitchingLang }" key="resume">
            <ResumePreview :data="resumeData" :highlighted-module="highlightedModule" :jd-data="jdData" :is-mobile-view="isMobileView" :lang="currentLang" :session-id="sessionId" :is-language-switch-disabled="isLanguageSwitchDisabled" :is-language-switch-loading="isSwitchingLang" :is-operation-locked="isUiInteractionLocked" @open-jd-dialog="openJDDialog" @open-resume-edit="openResumeEditDialog" @toggle-lang="switchLang" />
          </div>
        </Transition>

        <!-- 移动端底部 Tab 栏 -->
        <MobileTabBar :active-tab="currentTab" @update:activeTab="currentTab = $event" />
      </template>
    </div> <!-- 闭合 v-else main-content -->
  </div>

  <!-- 图片预览弹窗 -->
  <Teleport to="body">
    <div v-if="showImagePreview" class="image-preview-modal" @click="closeImagePreview">
      <div class="image-preview-content" @click.stop>
        <button class="image-preview-close" @click="closeImagePreview">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
        <img :src="previewImageUrl" class="image-preview-image" alt="Preview" />
      </div>
    </div>
  </Teleport>

  <!-- 自定义 Tooltip -->
  <Teleport to="body">
    <Transition name="tooltip-fade">
      <div 
        v-if="tooltipState.visible" 
        class="custom-tooltip"
        :style="{ left: tooltipState.x + 'px', top: tooltipState.top + 'px' }"
      >
        {{ tooltipState.text }}
      </div>
    </Transition>
  </Teleport>

  <!-- 全屏输入弹窗 -->
  <Teleport to="body">
    <Transition name="dialog-fade">
      <div v-if="isFullscreenDialogOpen" class="fullscreen-dialog-overlay" @click.self="closeFullscreenDialog">
        <div class="fullscreen-dialog" @keydown="handleDialogKeydown">
          <div class="dialog-header">
            <h3>输入你的请求</h3>
            <button class="dialog-close-btn" @click="closeFullscreenDialog" title="关闭 (ESC)">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            </button>
          </div>
          <div class="dialog-body">
            <textarea
              v-model="dialogUserInput"
              class="dialog-textarea"
              placeholder="输入你的问题或请求...（按Enter换行）"
              rows="15"
              autofocus
            ></textarea>
          </div>
          <div class="dialog-footer">
            <button class="dialog-save-btn" @click="saveDialogContent">保存</button>
            <button
              class="dialog-submit-btn"
              @click="submitFullscreenDialog"
              :disabled="!dialogUserInput.trim()"
            >
              发送 (Ctrl+Enter)
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>

  <!-- 会话菜单弹窗 -->
  <Teleport to="body">
    <Transition name="dialog-fade">
      <div v-if="showSessionMenu" class="session-menu-overlay" @click.self="closeSessionMenu">
        <div class="session-menu" :style="menuPosition">
          <button class="session-menu-item" @click="openRenameModal">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 2L14 4L6 12H4V10L12 2Z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>
            </svg>
            <span>重命名</span>
          </button>
          <button class="session-menu-item danger" @click="openDeleteModal">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M2 4H14M5 4V3C5 2.44772 5.44772 2 6 2H10C10.5523 2 11 2.44772 11 3V4M13 4V13C13 13.5523 12.5523 14 12 14H4C3.44772 14 3 13.5523 3 13V4" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <span>删除</span>
          </button>
        </div>
      </div>
    </Transition>
  </Teleport>

  <!-- 重命名弹窗 -->
  <Teleport to="body">
    <Transition name="dialog-fade">
      <div v-if="showRenameModal" class="modal-overlay" @click.self="closeRenameModal">
        <div class="modal-container rename-modal">
          <div class="modal-header">
            <h3>重命名会话</h3>
            <button class="modal-close-btn" @click="closeRenameModal" title="关闭">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
              </svg>
            </button>
          </div>
          <div class="modal-body">
            <input
              v-model="renameSessionTitle"
              type="text"
              class="modal-input"
              maxlength="50"
              placeholder="输入会话名称"
              @keydown.enter.prevent="submitRenameModal"
            />
          </div>
          <div class="modal-footer">
            <button class="cancel-btn" @click="closeRenameModal">取消</button>
            <button class="save-btn" @click="submitRenameModal" :disabled="!renameSessionTitle.trim()">保存</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>

  <!-- 删除确认弹窗 -->
  <Teleport to="body">
    <Transition name="dialog-fade">
      <div v-if="showDeleteModal" class="modal-overlay" @click.self="closeDeleteModal">
        <div class="modal-container delete-modal">
          <div class="modal-header">
            <h3>删除会话</h3>
            <button class="modal-close-btn" @click="closeDeleteModal" title="关闭">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
              </svg>
            </button>
          </div>
          <div class="modal-body">
            <p class="delete-message">确定要删除会话 "{{ menuSession?.title || '未命名会话' }}" 吗？此操作无法撤销。</p>
          </div>
          <div class="modal-footer">
            <button class="cancel-btn" @click="closeDeleteModal">取消</button>
            <button class="save-btn" @click="confirmDeleteSession">删除</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>

  <!-- 翻译确认弹窗 -->
  <Teleport to="body">
    <Transition name="dialog-fade">
      <div v-if="showTranslateConfirm" class="translate-dialog-overlay" @click.self="cancelTranslate">
        <div class="translate-dialog">
          <div class="dialog-header">
            <h3>{{ translateLabels.translateConfirmTitle }}</h3>
            <button class="dialog-close-btn" @click="cancelTranslate" title="关闭">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            </button>
          </div>
          <div class="dialog-body">
            <p>{{ translateLabels.translateConfirmMessage }}</p>
          </div>
          <div class="dialog-footer">
            <button class="cancel-btn" @click="cancelTranslate">{{ translateLabels.cancel }}</button>
            <button class="confirm-btn" @click="confirmTranslate">{{ translateLabels.confirm }}</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>

  <!-- JD上传弹窗（新增） -->
  <Teleport to="body">
    <Transition name="dialog-fade">
      <div v-if="isJDDialogOpen" class="jd-dialog-overlay">
        <div class="jd-dialog">
          <div class="dialog-header">
            <h3>{{ jdInputMode === 'input' ? '上传目标岗位信息' : '编辑岗位信息' }}</h3>
            <button class="dialog-close-btn" @click="closeJDDialog" title="关闭">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            </button>
          </div>

          <!-- 输入模式 -->
          <div v-if="jdInputMode === 'input'" class="jd-input-section">
            <!-- 有图片时：显示图片预览 -->
            <div v-if="jdInputImage" class="input-group">
              <label>目标岗位描述（图片）</label>
              <img :src="jdInputImage" class="jd-image-preview" alt="图片预览" />
              <button class="remove-image-btn" @click="jdInputImage = ''">移除图片</button>
            </div>
            <!-- 没有图片时：显示输入框 -->
            <div v-else class="input-group">
              <label>粘贴职位描述</label>
              <textarea
                v-model="jdInputText"
                @paste="handleJDPaste"
                placeholder="粘贴招聘要求内容，支持直接粘贴图片（Ctrl+V）..."
                rows="10"
              ></textarea>
            </div>
          </div>

          <!-- 表单模式 -->
          <div v-if="jdInputMode === 'form'" class="jd-form-section">
            <div class="form-header">
              <button class="back-btn" @click="backToInputMode">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M19 12H5M12 19l-7-7 7-7"/>
                </svg>
                退回上一步
              </button>
            </div>

            <!-- 基本信息（双列：3行×2列） -->
            <h4 class="section-title">基本信息</h4>
            <div class="form-grid">
              <div class="field-group">
                <label>公司名称</label>
                <input v-model="jdFormData.company" placeholder="请输入" />
              </div>
              <div class="field-group">
                <label>职位名称</label>
                <input v-model="jdFormData.position" placeholder="请输入" />
              </div>
              <div class="field-group">
                <label>部门/团队</label>
                <input v-model="jdFormData.department" placeholder="请输入" />
              </div>
              <div class="field-group">
                <label>工作地点</label>
                <input v-model="jdFormData.location" placeholder="请输入" />
              </div>
              <div class="field-group">
                <label>工作类型</label>
                <select v-model="jdFormData.job_type">
                  <option value="">请选择</option>
                  <option value="全职">全职</option>
                  <option value="实习">实习</option>
                </select>
              </div>
              <div class="field-group">
                <label>薪资范围</label>
                <input v-model="jdFormData.salary" placeholder="如：30k-50k" />
              </div>
            </div>

            <!-- 职位描述（单列） -->
            <h4 class="section-title">职位描述</h4>
            <div class="form-grid">
              <div class="field-group full-width">
                <textarea v-model="jdFormData.description" rows="3" placeholder="请输入"></textarea>
              </div>
            </div>

            <!-- 任职要求（双列） -->
            <h4 class="section-title">任职要求</h4>
            <div class="form-grid">
              <div class="field-group">
                <label>学历要求</label>
                <input v-model="jdFormData.requirements.education" placeholder="如：本科及以上" />
              </div>
              <div class="field-group">
                <label>经验要求</label>
                <input v-model="jdFormData.requirements.experience" placeholder="如：3年以上" />
              </div>
              <div class="field-group">
                <label>语言要求</label>
                <input v-model="jdFormData.requirements.language" placeholder="如：普通话流利" />
              </div>
            </div>

            <!-- 其他信息（单列） -->
            <h4 class="section-title">其他信息</h4>
            <div class="form-grid">
              <div class="field-group full-width">
                <label>技能要求</label>
                <div class="tags-input">
                  <span v-for="(skill, i) in jdFormData.requirements.skills" :key="i" class="tag">
                    {{ skill }}
                    <button @click="removeSkill(i)" class="tag-remove">×</button>
                  </span>
                  <input
                    v-model="newSkill"
                    @keydown.enter="addSkill"
                    placeholder="回车添加技能"
                    class="tag-input"
                  />
                </div>
              </div>
              <div class="field-group full-width">
                <label>优先条件</label>
                <textarea v-model="jdFormData.preferred_qualifications_text" rows="2" placeholder="请输入（用逗号分隔）" @blur="updatePreferredQualifications"></textarea>
              </div>
              <div class="field-group full-width">
                <label>亮点/核心关键词</label>
                <textarea v-model="jdFormData.highlights_text" rows="2" placeholder="请输入（用逗号分隔）" @blur="updateHighlights"></textarea>
              </div>
            </div>
          </div>

          <!-- 底部按钮（固定在底部，不随内容滚动） -->
          <div class="dialog-actions">
            <template v-if="jdInputMode === 'input'">
              <button class="parse-btn" @click="parseJD" :disabled="!jdInputText.trim() && !jdInputImage || isParsingJD">
                <span v-if="isParsingJD" class="spinner"></span>
                <span>{{ isParsingJD ? '识别中...' : '智能识别' }}</span>
              </button>
            </template>
            <template v-else>
              <button class="cancel-btn" @click="closeJDDialog">取消</button>
              <button class="save-btn" @click="saveJD" :disabled="isSaving">
                <span v-if="isSaving" class="spinner"></span>
                <span>{{ isSaving ? '保存中...' : '保存' }}</span>
              </button>
            </template>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>

  <!-- 简历编辑弹窗（新增） -->
  <Teleport to="body">
    <Transition name="dialog-fade">
      <div v-if="isResumeEditDialogOpen" class="resume-dialog-overlay">
        <div class="resume-dialog">
          <div class="dialog-header">
            <h3>编辑简历</h3>
            <button class="dialog-close-btn" @click="closeResumeEditDialog" title="关闭">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            </button>
          </div>

          <div class="resume-form-section">
            <!-- 基本信息 -->
            <h4 class="section-title">基本信息</h4>
            
            <!-- 证件照上传 -->
            <div class="field-group photo-upload-group">
              <label>证件照</label>
              <div class="photo-upload-area" :class="{ 'has-error': photoError }">
                <img v-if="resumeFormData.basics.photo" :src="resumeFormData.basics.photo" class="photo-preview" />
                <div v-else class="photo-placeholder" @click="$refs.photoInput.click()">
                  <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                    <circle cx="12" cy="7" r="4"></circle>
                  </svg>
                  <span>点击上传证件照</span>
                  <small>（1寸照片，不超过2MB）</small>
                </div>
                <input 
                  ref="photoInput"
                  type="file" 
                  accept="image/jpeg,image/png"
                  @change="handlePhotoUpload"
                  class="photo-input" 
                />
                <button v-if="resumeFormData.basics.photo" @click="removePhoto" class="remove-photo-btn">×</button>
              </div>
              <div v-if="photoError" class="photo-error">{{ photoError }}</div>
            </div>
            
            <div class="form-grid">
              <div class="field-group">
                <label>姓名</label>
                <input v-model="resumeFormData.basics.name" placeholder="请输入" class="element-input" />
              </div>
              <div class="field-group">
                <label>性别</label>
                <el-select v-model="resumeFormData.basics.gender" placeholder="请选择" class="element-select">
                  <el-option label="男" value="男" />
                  <el-option label="女" value="女" />
                  <el-option label="保密" value="保密" />
                </el-select>
              </div>
              <div class="field-group">
                <label>手机</label>
                <input v-model="resumeFormData.basics.phone" placeholder="请输入" class="element-input" />
              </div>
              <div class="field-group">
                <label>邮箱</label>
                <input v-model="resumeFormData.basics.email" placeholder="请输入" class="element-input" />
              </div>
              <div class="field-group full-width">
                <label>期望岗位</label>
                <input v-model="resumeFormData.basics.target_position" placeholder="请输入" class="element-input" />
              </div>
            </div>

            <!-- 教育背景 -->
            <h4 class="section-title">教育背景</h4>
            <div v-for="(edu, i) in resumeFormData.education" :key="i" class="array-item">
              <div class="array-item-header">
                <span class="array-item-title">学历 {{ i + 1 }}</span>
                <div class="array-item-actions">
                  <button
                    v-if="i > 0"
                    @click="moveEducation(i, -1)"
                    class="move-btn"
                    type="button"
                    aria-label="上移学历"
                  >上移</button>
                  <button
                    v-if="i < resumeFormData.education.length - 1"
                    @click="moveEducation(i, 1)"
                    class="move-btn"
                    type="button"
                    aria-label="下移学历"
                  >下移</button>
                  <button @click="removeEducation(i)" class="remove-btn" type="button">删除</button>
                </div>
              </div>
              <div class="form-grid">
                <div class="field-group">
                  <label>学校</label>
                  <input v-model="edu.school_name" placeholder="请输入" />
                </div>
                <div class="field-group">
                  <label>专业</label>
                  <input v-model="edu.major" placeholder="请输入" class="element-input" />
                </div>
                <div class="field-group">
                  <label>学历</label>
                  <el-select v-model="edu.degree" placeholder="请选择" class="element-select">
                    <el-option label="博士" value="博士" />
                    <el-option label="硕士" value="硕士" />
                    <el-option label="本科" value="本科" />
                    <el-option label="大专" value="大专" />
                    <el-option label="中专" value="中专" />
                    <el-option label="高中" value="高中" />
                    <el-option label="初中及以下" value="初中及以下" />
                  </el-select>
                </div>
                <div class="field-group full-width">
                  <label>时间范围</label>
                  <MonthRangePresentPicker
                    v-model:start="edu._startDate"
                    v-model:end="edu._endDate"
                    v-model:is-present="edu._isPresent"
                  />
                </div>
                <div class="field-group full-width">
                  <label>学校标签</label>
                  <div class="tags-input">
                    <span v-for="(tag, j) in edu.school_tags" :key="j" class="tag">
                      {{ tag }}
                      <button @click="edu.school_tags.splice(j, 1)" class="tag-remove">×</button>
                    </span>
                    <input v-model="edu.newSchoolTag" @keydown.enter="addSchoolTag(edu)" placeholder="回车添加标签" class="tag-input" />
                  </div>
                </div>
              </div>
              <div class="array-item-nested">
                <div class="field-group full-width">
                  <label>主修课程</label>
                  <textarea
                    v-model="edu._majorCoursesText"
                    rows="2"
                    placeholder="请输入主修课程，用顿号、逗号或换行分隔"
                    class="multiline-textarea"
                  ></textarea>
                </div>
                <div class="field-group full-width">
                  <label>学术成果</label>
                  <textarea
                    v-model="edu._academicAchievementsText"
                    rows="2"
                    placeholder="请输入学术成果，用顿号、逗号或换行分隔"
                    class="multiline-textarea"
                  ></textarea>
                </div>
                <div class="field-group full-width">
                  <label>荣誉奖项</label>
                  <textarea
                    v-model="edu._honorsAwardsText"
                    rows="2"
                    placeholder="请输入荣誉奖项，用顿号、逗号或换行分隔"
                    class="multiline-textarea"
                  ></textarea>
                </div>
              </div>
            </div>
            <button @click="addEducation" class="add-btn">+ 添加学历</button>

            <!-- 工作经历 -->
            <h4 class="section-title">工作经历</h4>
            <div v-for="(work, i) in resumeFormData.work_experience" :key="i" class="array-item">
              <div class="array-item-header">
                <span class="array-item-title">工作 {{ i + 1 }}</span>
                <div class="array-item-actions">
                  <button
                    v-if="i > 0"
                    @click="moveWork(i, -1)"
                    class="move-btn"
                    type="button"
                    aria-label="上移工作经历"
                  >上移</button>
                  <button
                    v-if="i < resumeFormData.work_experience.length - 1"
                    @click="moveWork(i, 1)"
                    class="move-btn"
                    type="button"
                    aria-label="下移工作经历"
                  >下移</button>
                  <button @click="removeWork(i)" class="remove-btn" type="button">删除</button>
                </div>
              </div>
              <div class="form-grid">
                <div class="field-group">
                  <label>公司</label>
                  <input v-model="work.company_name" placeholder="请输入" class="element-input" />
                </div>
                <div class="field-group">
                  <label>职位</label>
                  <input v-model="work.job_title" placeholder="请输入" class="element-input" />
                </div>
                <div class="field-group">
                  <label>工作类型</label>
                  <el-select v-model="work.job_type" placeholder="请选择" class="element-select">
                    <el-option label="全职" value="全职" />
                    <el-option label="实习" value="实习" />
                  </el-select>
                </div>
                <div class="field-group full-width">
                  <label>时间范围</label>
                  <MonthRangePresentPicker
                    v-model:start="work._startDate"
                    v-model:end="work._endDate"
                    v-model:is-present="work._isPresent"
                  />
                </div>
              </div>
              <!-- 工作内容 -->
              <div class="array-item-nested">
                <label>工作内容</label>
                <RichTextEditor
                  v-model="work._detailsText"
                  placeholder="请输入工作内容，支持换行和 Ctrl+B 加粗"
                  class="rich-editor-field"
                />
              </div>
            </div>
            <button @click="addWork" class="add-btn">+ 添加工作经历</button>

            <!-- 项目经历 -->
            <h4 class="section-title">项目经历</h4>
            <div v-for="(proj, i) in resumeFormData.project_experience" :key="i" class="array-item">
              <div class="array-item-header">
                <span class="array-item-title">项目 {{ i + 1 }}</span>
                <div class="array-item-actions">
                  <button
                    v-if="i > 0"
                    @click="moveProject(i, -1)"
                    class="move-btn"
                    type="button"
                    aria-label="上移项目经历"
                  >上移</button>
                  <button
                    v-if="i < resumeFormData.project_experience.length - 1"
                    @click="moveProject(i, 1)"
                    class="move-btn"
                    type="button"
                    aria-label="下移项目经历"
                  >下移</button>
                  <button @click="removeProject(i)" class="remove-btn" type="button">删除</button>
                </div>
              </div>
              <div class="form-grid">
                <div class="field-group">
                  <label>项目名称</label>
                  <input v-model="proj.project_name" placeholder="请输入" class="element-input" />
                </div>
                <div class="field-group">
                  <label>角色</label>
                  <input v-model="proj.role" placeholder="请输入" class="element-input" />
                </div>
                <div class="field-group full-width">
                  <label>时间范围</label>
                  <MonthRangePresentPicker
                    v-model:start="proj._startDate"
                    v-model:end="proj._endDate"
                    v-model:is-present="proj._isPresent"
                  />
                </div>
              </div>
              <!-- 项目内容 -->
              <div class="array-item-nested">
                <label>项目内容</label>
                <RichTextEditor
                  v-model="proj._detailsText"
                  placeholder="请输入项目内容，支持换行和 Ctrl+B 加粗"
                  class="rich-editor-field"
                />
              </div>
            </div>
            <button @click="addProject" class="add-btn">+ 添加项目经历</button>

            <!-- 其他信息 -->
            <h4 class="section-title">其他信息</h4>
            <div class="others-section">
              <div class="field-group full-width">
                <label>技能</label>
                <div class="tags-input">
                  <span v-for="(skill, i) in resumeFormData.others.skills" :key="i" class="tag">
                    {{ skill }}
                    <button @click="resumeFormData.others.skills.splice(i, 1)" class="tag-remove">×</button>
                  </span>
                  <input v-model="newResumeSkill" @keydown.enter="addResumeSkill" placeholder="回车添加技能" class="tag-input" />
                </div>
              </div>
              <div class="field-group full-width">
                <label>证书</label>
                <div class="tags-input">
                  <span v-for="(cert, i) in resumeFormData.others.certificates" :key="i" class="tag">
                    {{ cert }}
                    <button @click="resumeFormData.others.certificates.splice(i, 1)" class="tag-remove">×</button>
                  </span>
                  <input v-model="newResumeCert" @keydown.enter="addResumeCert" placeholder="回车添加证书" class="tag-input" />
                </div>
              </div>
              <div class="field-group full-width">
                <label>语言</label>
                <div class="tags-input">
                  <span v-for="(lang, i) in resumeFormData.others.languages" :key="i" class="tag">
                    {{ lang }}
                    <button @click="resumeFormData.others.languages.splice(i, 1)" class="tag-remove">×</button>
                  </span>
                  <input v-model="newResumeLang" @keydown.enter="addResumeLang" placeholder="回车添加语言" class="tag-input" />
                </div>
              </div>
            </div>

            <!-- 自我评价 -->
            <h4 class="section-title">自我评价</h4>
            <RichTextEditor
              v-model="selfEvalText"
              placeholder="请输入自我评价，支持换行和 Ctrl+B 加粗"
              class="rich-editor-field"
            />
          </div>

          <div class="dialog-actions">
            <button class="cancel-btn" @click="closeResumeEditDialog">取消</button>
            <button class="save-btn" @click="saveResume" :disabled="isSaving || isResponding">
              <span v-if="isSaving" class="spinner"></span>
              <span>{{ isSaving ? '保存中...' : '保存' }}</span>
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.app-container {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 60px); /* 减去header高度 */
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
  background-color: #e6e2dd;
  width: 100%;
  margin: 0;
  max-width: none;
}

.app-header {
  width: 100%;
  background-color: rgb(249, 245, 242);
  color: var(--text-primary);
  box-shadow: none;
  border-bottom: 1px solid #e0e0e0;
  position: sticky;
  top: 0;
  z-index: 9999;
  margin: 0;
}

.header-content {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  padding: 1rem 2rem;
  width: 100%;
  box-sizing: border-box;
  margin: 0;
}

.app-header h1 {
  margin: 0;
  display: flex;
  align-items: center;
  margin-right: auto;
}

.app-header h1 a {
  display: block;
}

.app-logo {
  height: 26px;
  width: auto;
}

.header-contact {
  position: relative;
}

.contact-link {
  font-family: 'GTPressuraMono-Light', sans-serif;
  font-size: 0.6875rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: #666;
  cursor: pointer;
  transition: color 0.2s;
  margin-right: 1.5rem;
}

.contact-link:hover {
  color: #d97706;
}

.contact-tooltip {
  position: absolute;
  top: calc(100% + 8px);
  left: 50%;
  transform: translateX(-50%);
  padding: 1rem;
  background: white;
  border: 1px solid #e5e5e5;
  border-radius: 8px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.12);
  opacity: 0;
  visibility: hidden;
  transition: all 0.2s ease;
  z-index: 9999;
  text-align: center;
  min-width: 200px;
}

.contact-tooltip::before {
  content: '';
  position: absolute;
  top: -6px;
  left: 50%;
  transform: translateX(-50%);
  width: 0;
  height: 0;
  border-left: 6px solid transparent;
  border-right: 6px solid transparent;
  border-bottom: 6px solid white;
}

.header-contact:hover .contact-tooltip {
  opacity: 1;
  visibility: visible;
}

.tooltip-text {
  font-family: 'PingFang SC', 'Noto Sans SC', sans-serif;
  font-size: 0.8125rem;
  color: #303030;
  margin: 0 0 0.5rem;
  letter-spacing: 0;
  text-transform: none;
}

.tooltip-text:last-of-type {
  margin-bottom: 0.75rem;
}

.wechat-qr {
  width: 160px;
  height: auto;
  display: block;
  margin: 0 auto;
  border-radius: 4px;
}

.header-info {
  display: flex;
  gap: 1rem;
  font-family: 'GTPressuraMono-Light', sans-serif;
  font-size: 0.6875rem;
  text-transform: uppercase;
  letter-spacing: 0.25em;
  color: #303030;
  align-items: center;
  margin-left: auto;
}

.user-email {
  color: #303030;
  font-weight: 400;
}

.logout-btn {
  padding: 0.5rem 1rem;
  border: 1px solid #303030;
  border-radius: 0;
  background: transparent;
  color: #303030;
  font-family: 'GTPressuraMono-Light', sans-serif;
  font-size: 0.6875rem;
  text-transform: uppercase;
  letter-spacing: 0.25em;
  cursor: pointer;
  transition: all 0.2s ease;
}

.logout-btn:hover {
  background: #303030;
  color: #f8bebe;
}

.auth-link {
  color: #303030;
  text-decoration: none;
  padding: 0.5rem 1rem;
  border: 1px solid #303030;
  border-radius: 0;
  font-family: 'GTPressuraMono-Light', sans-serif;
  font-size: 0.6875rem;
  text-transform: uppercase;
  letter-spacing: 0.25em;
  transition: all 0.2s ease;
}

.auth-link:hover {
  background: #303030;
  color: #f8bebe;
}

/* 未登录提示样式 */
.not-logged-in {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: white;
}

.not-logged-in-content {
  text-align: center;
  padding: 3rem;
}

.not-logged-in-content svg {
  color: var(--text-secondary);
  margin-bottom: 1rem;
}

.not-logged-in-content h2 {
  margin: 0 0 0.5rem 0;
  color: var(--text-primary);
  font-size: 1.5rem;
}

.not-logged-in-content p {
  margin: 0 0 1.5rem 0;
  color: var(--text-secondary);
}

.auth-buttons {
  display: flex;
  gap: 1rem;
  justify-content: center;
}

.auth-btn {
  padding: 0.75rem 2rem;
  border-radius: var(--radius-md);
  text-decoration: none;
  font-weight: 500;
  transition: all 0.2s ease;
}

.login-btn {
  background: white;
  border: 1px solid var(--border-color);
  color: var(--text-primary);
}

.login-btn:hover {
  background: var(--secondary-color);
}

.register-btn {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border: none;
  color: white;
}

.register-btn:hover {
  opacity: 0.9;
}

.message-count {
  background-color: var(--accent-color);
  padding: 0.25rem 0.75rem;
  border-radius: var(--radius-full);
  font-size: 0.8rem;
}

.main-content {
  display: flex;
  flex: 1;
  overflow: hidden; /* 关键：让子元素处理滚动 */
  margin: 0;
  padding: 0;
}

.chat-section {
  display: flex;
  flex-direction: row;
  background-color: rgb(254, 253, 251);
  margin: 0;
  padding: 0;
  overflow: hidden;
  position: relative;
  border-right: 1px solid #e0e0e0;
  height: 100%; /* 确保高度填满 */
  width: 50%; /* 聊天区域占50% */
  flex-shrink: 0; /* 不允许收缩 */
}

/* Claude 风格侧边栏 */
.session-sidebar {
  width: 220px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: #faf9f7;
  border-right: 1px solid #e8e6e3;
  transition: width 0.2s ease;
}

.session-sidebar.collapsed {
  width: 52px;
}

.session-sidebar.collapsed .session-sidebar-header {
  flex-direction: column;
  justify-content: flex-start;
  gap: 4px;
  padding: 8px;
}

.session-sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px;
  border-bottom: 1px solid #e8e6e3;
  min-height: 52px;
  box-sizing: border-box;
}

/* 新建按钮 */
.session-create-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border: none;
  background: transparent !important;
  color: #333 !important;
  opacity: 1 !important;
  font-size: 13px;
  font-weight: 500;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
  outline: none;
}

.session-create-btn:hover {
  color: #333 !important;
  background: rgba(0, 0, 0, 0.08) !important;
}

.session-create-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.session-create-btn.loading,
.session-create-btn.loading:disabled {
  cursor: progress;
}

/* 展开收起按钮 */
.session-toggle-btn {
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
  outline: none;
}

.session-toggle-btn:hover {
  color: #333 !important;
  background: rgba(0, 0, 0, 0.08) !important;
}

/* 会话列表 */
.session-list {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 8px 10px;
  overflow-y: auto;
  flex: 1;
}

/* 会话项 - Claude风格 */
.session-item {
  display: flex;
  align-items: center;
  position: relative;
  border-radius: 8px;
  transition: all 0.15s ease;
}

.session-item:hover {
  background: rgba(0, 0, 0, 0.02);
}

.session-item.active {
  background: rgba(217, 119, 6, 0.15);
}

.session-item.active .session-item-title {
  color: #222;
  font-weight: 500;
}

.session-item-main {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 0;
  border: none;
  background: transparent;
  border-radius: 8px;
  padding: 10px 12px;
  text-align: left;
  min-width: 0;
  cursor: pointer;
  transition: all 0.15s ease;
  outline: none;
}

.session-item-main:hover:not(:disabled) {
  background: transparent;
}

.session-item-main:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.session-sidebar.session-busy,
.session-sidebar.session-busy .session-item-main,
.session-sidebar.session-busy .session-more-btn,
.session-sidebar.session-busy .session-toggle-btn {
  cursor: progress;
}

.session-item-title {
  flex: 1;
  font-size: 13.5px;
  font-weight: 400;
  color: #444;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.5;
}

/* 选中项文字颜色保持不变 */

/* 更多按钮 */
.session-item-actions {
  display: flex;
  align-items: center;
  opacity: 0;
  transition: opacity 0.15s ease;
  margin-right: 4px;
}

.session-item:hover .session-item-actions,
.session-item.active .session-item-actions {
  opacity: 1;
}

.session-more-btn {
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  color: #555;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
  outline: none;
}

.session-more-btn:hover {
  background: rgba(0, 0, 0, 0.1);
  color: #333;
}

.session-item.active .session-more-btn {
  color: #333;
}

.session-item.active .session-more-btn:hover {
  background: transparent;
}

/* 会话菜单 - Claude风格弹出框 */
.session-menu-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 1000;
}

.session-menu {
  position: fixed;
  background: #fff;
  border: 1px solid #e0e0e0;
  border-radius: 12px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15), 0 1px 3px rgba(0, 0, 0, 0.1);
  padding: 6px;
  min-width: 160px;
  z-index: 1001;
  animation: menuFadeIn 0.1s ease;
}

@keyframes menuFadeIn {
  from {
    opacity: 0;
    transform: scale(0.96);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

.session-menu-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: none;
  background: transparent;
  color: #444;
  font-size: 14px;
  font-weight: 400;
  cursor: pointer;
  text-align: left;
  border-radius: 8px;
  transition: all 0.1s ease;
}

.session-menu-item:hover {
  background: #f5f5f5;
}

.session-menu-item.danger {
  color: #dc2626;
}

.session-menu-item.danger:hover {
  background: #fef2f2;
}

/* 模态弹窗 - Claude风格 */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
  backdrop-filter: blur(4px);
}

.modal-container {
  background: #fff;
  border-radius: 0;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
  width: 100%;
  max-width: 400px;
  overflow: hidden;
  animation: modalSlideIn 0.2s ease;
}

@keyframes modalSlideIn {
  from {
    opacity: 0;
    transform: scale(0.95) translateY(-10px);
  }
  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 20px 16px;
  border-bottom: none;
}

.modal-header h3 {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
  color: #1a1a1a;
}

.modal-close-btn {
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  color: #999;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
}

.modal-close-btn:hover {
  background: #f0f0f0;
  color: #666;
}

.modal-body {
  padding: 0 20px 20px;
}

.modal-input {
  width: 100%;
  padding: 12px 14px;
  border: 1px solid #e0e0e0;
  border-radius: 10px;
  font-size: 15px;
  font-family: inherit;
  background: #fff;
  color: #1a1a1a;
  outline: none;
  transition: all 0.15s ease;
  box-sizing: border-box;
}

.modal-input:focus {
  border-color: #d97706;
  box-shadow: 0 0 0 3px rgba(217, 119, 6, 0.1);
}

.delete-message {
  margin: 0;
  font-size: 14px;
  color: #555;
  line-height: 1.6;
}

.modal-footer {
  display: flex;
  gap: 10px;
  padding: 0 20px 20px;
  justify-content: flex-end;
}

.modal-btn {
  padding: 10px 18px;
  border: none;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.modal-btn.cancel {
  background: #f0f0f0;
  color: #555;
}

.modal-btn.cancel:hover {
  background: #e0e0e0;
}

.modal-btn.save {
  background: #1a1a1a;
  color: #fff;
}

.modal-btn.save:hover:not(:disabled) {
  background: #333;
}

.modal-btn.save:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.modal-btn.delete {
  background: #dc2626;
  color: #fff;
}

.modal-btn.delete:hover {
  background: #b91c1c;
}

.chat-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

/* 简洁的滚动条样式 - 应用于所有可滚动区域 */
.messages-container::-webkit-scrollbar,
.preview-content::-webkit-scrollbar {
  width: 8px;
}

.messages-container::-webkit-scrollbar-track,
.preview-content::-webkit-scrollbar-track {
  background: #f1f1f1;
  border-radius: 4px;
}

.messages-container::-webkit-scrollbar-thumb,
.preview-content::-webkit-scrollbar-thumb {
  background: #c1c1c1;
  border-radius: 4px;
  min-height: 30px;
}

.messages-container::-webkit-scrollbar-thumb:hover,
.preview-content::-webkit-scrollbar-thumb:hover {
  background: #a8a8a8;
}

/* 聊天区域容器 */
.chat-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  flex: 1;
  overflow: hidden;
  padding: 0;
  background-color: transparent;
  position: relative;
}

.messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  width: 100%;
  max-width: 1200px;
  margin: 0 auto;
  font-size: 14px; /* 聊天区域字体缩小，避免内容太拥挤 */
}

/* 滑动至底部按钮 */
.scroll-to-bottom-btn {
  position: absolute;
  left: 50%;
  bottom: 20px;
  transform: translateX(-50%);
  width: 44px;
  height: 44px;
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.75);
  border: 1px solid rgba(224, 224, 224, 0.8);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.12);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #555;
  transition: all 0.2s ease;
  z-index: 10;
  backdrop-filter: blur(4px);
}

.scroll-to-bottom-btn:hover {
  background: rgba(255, 255, 255, 0.95);
  color: #333;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.18);
  transform: translateX(-50%) translateY(-2px);
}

.scroll-to-bottom-btn:active {
  transform: translateX(-50%) translateY(0);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
}

.scroll-to-bottom-btn svg {
  width: 20px;
  height: 20px;
  stroke-width: 2;
}

.scroll-arrow {
  font-size: 20px;
  color: #666;
  line-height: 1;
}

/* 按钮淡入淡出动画 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.floating-input-container {
  position: relative;
  padding: 1rem;
  background: rgb(254, 253, 251);
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='3.0' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E");
  background-blend-mode: overlay;
  background-repeat: repeat;
  background-size: auto;
  border-top: 1px solid transparent;
  flex-shrink: 0;
}

.input-wrapper {
  display: flex;
  max-width: 100%;
  background-color: transparent;
}

.input-wrapper:focus-within {
}

/* 文本域容器 - 模仿模板风格 */
.textarea-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  background-color: #f5f4f2;
  border: 1px solid #e0e0e0;
  transition: all 0.2s ease;
  overflow: hidden;
  border-radius: 0;
}

.textarea-container:focus-within {
  background-color: white;
  border-color: #303030;
}

.textarea-container textarea {
  flex: 1;
  width: 100%;
  padding: 1.125rem;
  border: none;
  resize: none;
  font-size: 0.875rem;
  font-family: 'GTPressuraMono-Light', sans-serif;
  background-color: transparent;
  transition: all 0.2s ease;
  min-height: 4.0625rem;
  max-height: 150px;
  overflow-y: auto;
  line-height: 1.5;
  color: #303030;
}

.textarea-container textarea::-webkit-scrollbar {
  display: none;
}

.textarea-container textarea {
  -ms-overflow-style: none;
  scrollbar-width: none;
}

.textarea-container textarea:focus {
  outline: none;
}

.textarea-container textarea::placeholder {
  color: #666;
}

/* 底部工具栏 */
.toolbar {
  display: flex;
  align-items: center;
  gap: 0;
  padding: 0.5rem;
  border-top: none;
  background-color: transparent;
}

/* 图标按钮 - 模仿模板风格 */
.icon-btn {
  background: transparent;
  border: none;
  padding: 0.5rem;
  border-radius: 0;
  color: #303030;
  cursor: pointer;
  transition: all 0.15s ease;
  display: flex;
  align-items: center;
  justify-content: center;
}

.icon-btn:hover:not(:disabled) {
  background-color: transparent;
  color: #f8bebe;
}

.icon-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.icon-btn svg {
  width: 1.25rem;
  height: 1.25rem;
}

.icon-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* 发送按钮 - 模仿模板风格 */
.send-btn {
  color: #303030;
  margin-left: auto;
  background-color: transparent;
  border: none;
  padding: 0.75rem;
  cursor: pointer;
  transition: all 0.2s ease;
}

.send-btn:hover:not(:disabled) {
  background-color: transparent;
  color: #f8bebe;
}

.send-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.send-btn svg {
  width: 1.25rem;
  height: 1.25rem;
}

/* 发送按钮占位符 - 预留空间避免高度突变 */
.send-btn-placeholder {
  width: 2.75rem;
  height: 2.75rem;
  flex-shrink: 0;
}

/* 自定义 Tooltip 样式 - 使用 Teleport 渲染到 body */
.custom-tooltip {
  position: fixed;
  transform: translateY(-50%);
  background-color: #303030;
  color: white;
  padding: 0.375rem 0.625rem;
  border-radius: 4px;
  font-size: 0.75rem;
  white-space: nowrap;
  pointer-events: none;
  z-index: 9999;
}

/* Tooltip 淡入淡出动画 */
.tooltip-fade-enter-active,
.tooltip-fade-leave-active {
  transition: opacity 0.1s ease;
}

.tooltip-fade-enter-from,
.tooltip-fade-leave-to {
  opacity: 0;
}

/* 上传文件展示区域 */
.uploaded-files {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-bottom: 1rem;
  padding: 0.25rem;
}

.file-thumbnail {
  position: relative;
  width: 60px;
  height: 60px;
  border-radius: var(--radius-md);
  /* 移除overflow: hidden，确保删除按钮完全可见 */
  overflow: visible;
  border: 1px solid var(--border-color);
  background-color: white;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 0.5rem;
  box-shadow: var(--shadow-sm);
  transition: all 0.3s ease;
  /* 确保容器能正确显示绝对定位的删除按钮 */
  z-index: 1;
}

.file-thumbnail:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}

.thumbnail-image {
  width: 32px;
  height: 32px;
  object-fit: contain;
  margin-bottom: 0.125rem;
}

.file-name {
  font-size: 0.6rem;
  color: var(--text-secondary);
  text-align: center;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  width: 100%;
  max-height: 12px;
}

.delete-file-btn {
  position: absolute;
  top: -8px;
  right: -8px;
  background-color: rgba(255, 0, 0, 0.8);
  border: 2px solid white;
  border-radius: 50%;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  opacity: 0;
  transition: all 0.3s ease;
  /* 确保是完美圆形 */
  min-width: 24px;
  min-height: 24px;
  max-width: 24px;
  max-height: 24px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  /* 确保图标可见 */
  color: white;
  /* 确保div样式正确 */
  padding: 0;
  margin: 0;
  box-sizing: border-box;
  /* 确保图标显示正确 */
  overflow: hidden;
}

.file-thumbnail:hover .delete-file-btn {
  opacity: 1;
}

.delete-file-btn:hover {
  background-color: rgba(255, 0, 0, 1);
  transform: scale(1.1);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
}

.delete-file-btn svg {
  width: 10px;
  height: 10px;
  stroke-width: 3;
  stroke: white;
}

/* 调整上传文件区域的间距 */
.uploaded-files {
  margin-bottom: 0.5rem;
}

.resume-section {
  flex: 1 1 auto; /* 简历区域自动适应剩余空间 */
  width: 0; /* 配合 flex: 1 实现自动宽度 */
  max-width: none;
  background-color: rgb(249, 245, 242);
  margin: 0;
  padding: 1rem;
  position: relative;
  overflow: visible;
  border-left: none;
  min-height: 0; /* 关键：允许flex子元素收缩 */
  box-shadow: none;
  border-radius: 0;
  display: flex;
  flex-direction: column;
}

.resume-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
}

.main-content.lang-switching,
.resume-section.lang-switching,
.mobile-resume-view.lang-switching {
  cursor: progress;
}

.main-content.session-busy,
.main-content.session-busy .chat-section,
.main-content.session-busy .resume-section,
.main-content.session-busy .session-sidebar,
.main-content.session-busy .session-item-main,
.main-content.session-busy .session-create-btn,
.main-content.session-busy .session-toggle-btn,
.main-content.session-busy .session-more-btn {
  cursor: progress;
}

.loading-indicator {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1rem;
  color: var(--text-secondary);
  font-size: 0.9rem;
  background-color: var(--secondary-color);
  border-radius: var(--radius-md);
  margin: 0.5rem 0;
  box-shadow: var(--shadow-sm);
}

.loading-spinner {
  animation: spin 1s linear infinite;
  color: var(--primary-color);
  transform-origin: center;
}

.loading-text {
  font-weight: 500;
  background: linear-gradient(
    90deg,
    #9ca3af 0%,
    #d1d5db 50%,
    #9ca3af 100%
  );
  background-size: 200% 100%;
  background-clip: text;
  -webkit-background-clip: text;
  color: transparent;
  animation: shimmer 1.5s ease-in-out infinite;
}

@keyframes shimmer {
  0% {
    background-position: 100% 0;
  }
  100% {
    background-position: -100% 0;
  }
}

/* 图片预览弹窗样式 */
.image-preview-modal {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.85);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  padding: 20px;
}

.image-preview-content {
  position: relative;
  max-width: 90vw;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.image-preview-image {
  max-width: 100%;
  max-height: 85vh;
  object-fit: contain;
  border-radius: 8px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
}

.image-preview-close {
  position: absolute;
  top: -40px;
  right: 0;
  background: none;
  border: none;
  color: white;
  cursor: pointer;
  padding: 8px;
  border-radius: 50%;
  transition: background-color 0.2s;
}

.image-preview-close:hover {
  background-color: rgba(255, 255, 255, 0.1);
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

/* 全屏弹窗样式 */
.fullscreen-dialog-overlay {
  position: fixed;
  inset: 0;
  background-color: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.fullscreen-dialog {
  background-color: rgb(254, 253, 251);
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='3.0' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E");
  background-blend-mode: overlay;
  background-repeat: repeat;
  border: 1px solid #303030;
  border-radius: 0;
  box-shadow: none;
  width: 90%;
  max-width: 720px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.dialog-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 1.5rem;
  border-bottom: 1px solid #303030;
  background-color: transparent;
}

.dialog-header h3 {
  margin: 0;
  font-size: 0.875rem;
  font-weight: 400;
  font-family: 'GTPressuraMono-Light', sans-serif;
  color: #303030;
  text-transform: uppercase;
  letter-spacing: 0.2em;
}

.dialog-close-btn {
  padding: 0.5rem;
  border: 1px solid #303030;
  background: transparent;
  color: #303030;
  cursor: pointer;
  border-radius: 0;
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
}

.dialog-close-btn:hover {
  background: #303030;
  color: #f8bebe;
}

.dialog-body {
  flex: 1;
  padding: 1.5rem;
  overflow: hidden;
}

.dialog-textarea {
  width: 100%;
  height: 100%;
  min-height: 280px;
  background-color: #f5f4f2;
  border: 1px solid #e0e0e0;
  border-radius: 0;
  padding: 1rem;
  font-size: 0.875rem;
  line-height: 1.6;
  resize: none;
  font-family: 'GTPressuraMono-Light', sans-serif;
  transition: all 0.2s ease;
  color: #303030;
}

.dialog-textarea:focus {
  outline: none;
  background-color: white;
  border-color: #303030;
}

.dialog-textarea::placeholder {
  color: #999;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  padding: 1rem 1.5rem;
  border-top: 1px solid #303030;
  background-color: transparent;
}

.dialog-cancel-btn {
  padding: 0.5rem 1rem;
  border: 1px solid #303030;
  border-radius: 0;
  background: transparent;
  color: #303030;
  font-family: 'GTPressuraMono-Light', sans-serif;
  font-size: 0.6875rem;
  text-transform: uppercase;
  letter-spacing: 0.25em;
  cursor: pointer;
  transition: all 0.2s ease;
}

.dialog-cancel-btn:hover {
  background: #303030;
  color: #f8bebe;
}

.dialog-save-btn {
  padding: 0.5rem 1rem;
  border: 1px solid #303030;
  border-radius: 0;
  background: transparent;
  color: #303030;
  font-family: 'GTPressuraMono-Light', sans-serif;
  font-size: 0.6875rem;
  text-transform: uppercase;
  letter-spacing: 0.25em;
  cursor: pointer;
  transition: all 0.2s ease;
}

.dialog-save-btn:hover {
  background: #f8bebe;
  border-color: #303030;
}

.dialog-submit-btn {
  padding: 0.5rem 1rem;
  border: 1px solid #303030;
  border-radius: 0;
  background: #f8bebe;
  color: #303030;
  font-family: 'GTPressuraMono-Light', sans-serif;
  font-size: 0.6875rem;
  text-transform: uppercase;
  letter-spacing: 0.25em;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 2px 2px 0 #303030;
}

.dialog-submit-btn:hover:not(:disabled) {
  background: #303030;
  color: #f8bebe;
  box-shadow: none;
  transform: translate(2px, 2px);
}

.dialog-submit-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 弹窗过渡动画 */
.dialog-fade-enter-active,
.dialog-fade-leave-active {
  transition: opacity 0.2s ease;
}

.dialog-fade-enter-active .fullscreen-dialog,
.dialog-fade-leave-active .fullscreen-dialog {
  transition: transform 0.3s ease, opacity 0.2s ease;
}

.dialog-fade-enter-from,
.dialog-fade-leave-to {
  opacity: 0;
}

.dialog-fade-enter-from .fullscreen-dialog,
.dialog-fade-leave-to .fullscreen-dialog {
  transform: scale(0.95);
}

/* ==================== 翻译确认弹窗样式 ==================== */
.translate-dialog-overlay {
  position: fixed;
  inset: 0;
  background-color: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 1rem;
}

.translate-dialog {
  background-color: rgb(254, 253, 251);
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='3.0' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E");
  background-blend-mode: overlay;
  background-repeat: repeat;
  border: 1px solid #303030;
  border-radius: 0;
  width: 100%;
  max-width: 400px;
  display: flex;
  flex-direction: column;
  box-shadow: none;
}

.translate-dialog .dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.5rem;
  border-bottom: 1px solid #303030;
  background-color: transparent;
}

.translate-dialog .dialog-header h3 {
  font-size: 0.875rem;
  font-weight: 400;
  font-family: 'GTPressuraMono-Light', sans-serif;
  color: #303030;
  margin: 0;
  text-transform: uppercase;
  letter-spacing: 0.2em;
}

.translate-dialog .dialog-body {
  padding: 1.5rem;
}

.translate-dialog .dialog-body p {
  margin: 0;
  font-size: 0.875rem;
  color: #303030;
  line-height: 1.6;
}

.translate-dialog .dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  padding: 1rem 1.5rem;
  border-top: 1px solid #303030;
}

.translate-dialog .confirm-btn {
  background: #303030;
  color: #f8bebe;
  border: 1px solid #303030;
  padding: 0.5rem 1rem;
  font-size: 0.75rem;
  font-family: 'GTPressuraMono-Light', sans-serif;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  cursor: pointer;
  transition: all 0.2s ease;
}

.translate-dialog .confirm-btn:hover {
  background: #4a4a4a;
}

/* ==================== JD上传弹窗样式（新增） ==================== */
.jd-dialog-overlay {
  position: fixed;
  inset: 0;
  background-color: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 1rem;
}

.jd-dialog {
  background-color: rgb(254, 253, 251);
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='3.0' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E");
  background-blend-mode: overlay;
  background-repeat: repeat;
  border: 1px solid #303030;
  border-radius: 0;
  width: 100%;
  max-width: 600px;
  max-height: 70vh;
  display: flex;
  flex-direction: column;
  box-shadow: none;
}

.jd-dialog .dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.5rem;
  border-bottom: 1px solid #303030;
  background-color: transparent;
}

.jd-dialog .dialog-header h3 {
  font-size: 0.875rem;
  font-weight: 400;
  font-family: 'GTPressuraMono-Light', sans-serif;
  color: #303030;
  margin: 0;
  text-transform: uppercase;
  letter-spacing: 0.2em;
}

.jd-dialog .dialog-close-btn {
  background: transparent;
  border: 1px solid #303030;
  cursor: pointer;
  padding: 0.5rem;
  border-radius: 0;
  color: #303030;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}

.jd-dialog .dialog-close-btn:hover {
  background: #303030;
  color: #f8bebe;
}

.jd-input-section {
  padding: 1.5rem;
  overflow-y: auto;
}

.jd-input-section .input-group {
  margin-bottom: 1rem;
}

.jd-input-section .input-group label {
  display: block;
  font-size: 0.75rem;
  font-weight: 400;
  font-family: 'GTPressuraMono-Light', sans-serif;
  color: #303030;
  margin-bottom: 0.5rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
}

.jd-input-section .input-group textarea {
  width: 100%;
  padding: 0.75rem;
  border: 1px solid #e0e0e0;
  border-radius: 0;
  font-size: 0.875rem;
  line-height: 1.5;
  resize: vertical;
  font-family: 'GTPressuraMono-Light', sans-serif;
  background-color: #f5f4f2;
  transition: all 0.2s ease;
  color: #303030;
}

.jd-input-section .input-group textarea:focus {
  outline: none;
  border-color: #303030;
  background-color: white;
}

.jd-input-section .image-upload-input {
  display: block;
  width: 100%;
  padding: 0.5rem;
  border: 1px dashed #303030;
  border-radius: 0;
  font-size: 0.875rem;
  font-family: 'GTPressuraMono-Light', sans-serif;
}

.jd-image-preview {
  width: 100%;
  max-height: 200px;
  object-fit: contain;
  border-radius: 0;
  margin-top: 0.5rem;
  border: 1px solid #303030;
}

.jd-input-section .image-tip {
  font-size: 0.875rem;
  color: #666;
  margin-top: 0.75rem;
  line-height: 1.5;
  padding: 0.5rem;
  background: rgba(48, 48, 48, 0.04);
  border-left: 2px solid #f8bebe;
}

.remove-image-btn {
  margin-top: 0.5rem;
  padding: 0.4rem 0.8rem;
  background: transparent;
  color: #303030;
  border: 1px solid #303030;
  border-radius: 0;
  cursor: pointer;
  font-family: 'GTPressuraMono-Light', sans-serif;
  font-size: 0.6875rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  transition: all 0.2s ease;
}

.remove-image-btn:hover {
  background: #f8bebe;
}

.jd-dialog .dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  padding: 1rem 1.5rem;
  border-top: 1px solid #303030;
  background-color: transparent;
  flex-shrink: 0;
}

.parse-btn {
  padding: 0.5rem 1rem;
  border: 1px solid #303030;
  border-radius: 0;
  background: #f8bebe;
  color: #303030;
  font-family: 'GTPressuraMono-Light', sans-serif;
  font-size: 0.6875rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  box-shadow: 2px 2px 0 #303030;
}

.parse-btn:hover:not(:disabled) {
  background: #303030;
  color: #f8bebe;
  box-shadow: none;
  transform: translate(2px, 2px);
}

.parse-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Spinner 动效 */
.spinner {
  width: 12px;
  height: 12px;
  border: 2px solid rgba(48, 48, 48, 0.3);
  border-top-color: #303030;
  border-radius: 0;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.cancel-btn {
  padding: 0.5rem 1rem;
  border: 1px solid #303030;
  border-radius: 0;
  background: transparent;
  color: #303030;
  font-family: 'GTPressuraMono-Light', sans-serif;
  font-size: 0.6875rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  cursor: pointer;
  transition: all 0.2s ease;
}

.cancel-btn:hover {
  background: #303030;
  color: #f8bebe;
}

.save-btn {
  padding: 0.5rem 1rem;
  border: 1px solid #303030;
  border-radius: 0;
  background: #f8bebe;
  color: #303030;
  font-family: 'GTPressuraMono-Light', sans-serif;
  font-size: 0.6875rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 2px 2px 0 #303030;
}

.save-btn:hover {
  background: #303030;
  color: #f8bebe;
  box-shadow: none;
  transform: translate(2px, 2px);
}

/* JD表单样式 */
.jd-form-section {
  padding: 1.5rem;
  overflow-y: auto;
  flex: 1;
  min-height: 0;
}

.form-header {
  display: flex;
  align-items: center;
  margin-bottom: 1rem;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid var(--border-color);
}

.back-btn {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.4rem 0.75rem;
  background: #f8f9fa;
  border: 1px solid #e9ecef;
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.2s ease;
}

.back-btn:hover {
  background: #e9ecef;
  color: var(--text-primary);
}

/* 分组标题 */
.section-title {
  font-size: 1rem;
  font-weight: 600;
  color: #212529;
  margin: 1.5rem 0 0.75rem 0;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid #e9ecef;
}

/* 子项标题（学历1、工作1、项目1） */
.array-item-title {
  font-size: 0.75rem;
  color: #6c757d;
  font-weight: 500;
}

/* 表单布局 */
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.5rem 0.75rem;
  margin-bottom: 0.75rem;
}

.form-grid + .form-grid {
  margin-top: 0.5rem;
}

/* 字段容器 */
.field-group {
  display: flex;
  flex-direction: column;
}

.field-group.full-width {
  grid-column: 1 / -1;
}

.field-group label {
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: 0.2rem;
}

.field-group input,
.field-group select,
.field-group textarea {
  width: 100%;
  padding: 0.5rem 0.6rem;
  border: 1px solid #e9ecef;
  border-radius: var(--radius-sm);
  font-size: 0.8rem;
  font-family: inherit;
  background: #fafafa;
  transition: all 0.2s ease;
}

.field-group input:hover,
.field-group select:hover,
.field-group textarea:hover {
  border-color: #dee2e6;
}

.field-group input:focus,
.field-group select:focus,
.field-group textarea:focus {
  outline: none;
  border-color: var(--primary-color);
  background: #fff;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.08);
}

.field-group input::placeholder,
.field-group textarea::placeholder {
  color: #adb5bd;
}

.field-group textarea {
  resize: vertical;
  min-height: 56px;
  line-height: 1.5;
}

.tags-input {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  padding: 0.5rem;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  align-items: center;
}

.tags-input.full-width {
  grid-column: 1 / -1;
}

.tags-input .tag {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.25rem 0.5rem;
  background-color: var(--secondary-color);
  border-radius: var(--radius-sm);
  font-size: 0.75rem;
  color: var(--text-primary);
}

.tags-input .tag-remove {
  background: none;
  border: none;
  cursor: pointer;
  padding: 0;
  font-size: 1rem;
  line-height: 1;
  color: var(--text-secondary);
}

.tags-input .tag-remove:hover {
  color: var(--error-color);
}

/* 证件照上传样式 */
.photo-upload-group {
  grid-column: 1 / -1;
  margin-bottom: 1rem;
}

.photo-upload-area {
  width: 80px;
  height: 100px;
  border: 2px dashed #e0e0e0;
  border-radius: 8px;
  overflow: hidden;
  position: relative;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: #fafafa;
  transition: all 0.2s ease;
}

.photo-upload-area:hover {
  border-color: #999;
  background-color: #f5f5f5;
}

.photo-upload-area.has-error {
  border-color: #dc3545;
}

.photo-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  color: #999;
  font-size: 10px;
  text-align: center;
  padding: 6px;
}

.photo-placeholder svg {
  width: 24px;
  height: 24px;
  color: #ccc;
}

.photo-placeholder small {
  display: none;
}

.photo-preview {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.photo-input {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  cursor: pointer;
}

.remove-photo-btn {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: rgba(0,0,0,0.6);
  color: white;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  line-height: 1;
  transition: background 0.2s ease;
  padding: 0;
}

.remove-photo-btn:hover {
  background: rgba(0,0,0,0.7);
}

.photo-error {
  color: #dc3545;
  font-size: 12px;
  margin-top: 4px;
}

.tags-input .tag-input {
  flex: 1;
  min-width: 100px;
  border: none;
  padding: 0.25rem;
  font-size: 0.875rem;
}

.tags-input .tag-input:focus {
  outline: none;
  box-shadow: none;
}

/* ==================== 简历编辑弹窗样式（新增） ==================== */
.resume-dialog-overlay {
  position: fixed;
  inset: 0;
  background-color: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 1rem;
}

.resume-dialog {
  background-color: rgb(254, 253, 251);
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='3.0' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E");
  background-blend-mode: overlay;
  background-repeat: repeat;
  border: 1px solid #303030;
  border-radius: 0;
  width: 100%;
  max-width: 700px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  box-shadow: none;
}

.resume-dialog .dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.5rem;
  border-bottom: 1px solid #303030;
  background-color: transparent;
}

.resume-dialog .dialog-header h3 {
  font-size: 0.875rem;
  font-weight: 400;
  font-family: 'GTPressuraMono-Light', sans-serif;
  color: #303030;
  margin: 0;
  text-transform: uppercase;
  letter-spacing: 0.2em;
}

.resume-dialog .dialog-close-btn {
  background: transparent;
  border: 1px solid #303030;
  cursor: pointer;
  padding: 0.5rem;
  border-radius: 0;
  color: #303030;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}

.resume-dialog .dialog-close-btn:hover {
  background: #303030;
  color: #f8bebe;
}

.resume-form-section {
  flex: 1;
  overflow-y: auto;
  padding: 1.5rem;
}

.array-item {
  border: 1px solid #303030;
  border-radius: 0;
  padding: 1rem;
  margin-bottom: 1rem;
}

.array-item-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
  font-weight: 400;
  font-family: 'GTPressuraMono-Light', sans-serif;
  font-size: 0.75rem;
  color: #303030;
  text-transform: uppercase;
  letter-spacing: 0.1em;
}

.array-item-actions {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.array-item-nested {
  margin-top: 0.75rem;
}

.nested-array-header {
  margin-bottom: 0.5rem;
}

.nested-add-btn {
  padding: 0.25rem 0.5rem;
  font-size: 0.625rem;
}

.nested-empty-state {
  padding: 0.75rem;
  border: 1px dashed #303030;
  font-size: 0.75rem;
  color: #666;
}

.array-item-nested > label {
  display: block;
  font-size: 0.75rem;
  font-weight: 400;
  font-family: 'GTPressuraMono-Light', sans-serif;
  color: #303030;
  margin-bottom: 0.5rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
}

.nested-item {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}

.nested-item input {
  flex: 1;
}

.add-btn {
  width: 100%;
  padding: 0.5rem;
  border: 1px dashed #303030;
  background: none;
  cursor: pointer;
  border-radius: 0;
  font-family: 'GTPressuraMono-Light', sans-serif;
  font-size: 0.6875rem;
  color: #303030;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  transition: all 0.2s ease;
}

.add-btn:hover {
  background: #f8bebe;
  border-color: #303030;
}

.add-nested-btn {
  padding: 0.4rem 0.75rem;
  font-family: 'GTPressuraMono-Light', sans-serif;
  font-size: 0.6875rem;
  border: 1px dashed #303030;
  background: none;
  cursor: pointer;
  border-radius: 0;
  color: #303030;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  transition: all 0.2s ease;
}

.add-nested-btn:hover {
  background: #f8bebe;
  border-color: #303030;
}

.move-btn {
  color: #303030;
  background: none;
  border: 1px dashed #303030;
  cursor: pointer;
  font-family: 'GTPressuraMono-Light', sans-serif;
  font-size: 0.6875rem;
  padding: 0.25rem 0.5rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
}

.move-btn:hover {
  background: #f8bebe;
  border-color: #303030;
}

.remove-btn {
  color: #303030;
  background: none;
  border: 1px solid #303030;
  cursor: pointer;
  font-family: 'GTPressuraMono-Light', sans-serif;
  font-size: 0.6875rem;
  padding: 0.25rem 0.5rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
}

.remove-btn:hover {
  background: #f8bebe;
  color: #303030;
  border-color: #303030;
}

/* Element UI 组件样式 */
.element-input {
  width: 100%;
  padding: 0.5rem 0.75rem;
  border: 1px solid #e9ecef;
  border-radius: var(--radius-sm);
  font-size: 0.8rem;
  font-family: inherit;
  background: #fafafa;
  transition: all 0.2s ease;
}

.element-input:hover {
  border-color: #dee2e6;
}

.element-input:focus {
  outline: none;
  border-color: var(--primary-color);
  background: #fff;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.08);
}

.element-select {
  width: 100%;
}

.element-select :deep(.el-input__wrapper) {
  background: #fafafa;
  border-color: #e9ecef;
  border-radius: var(--radius-sm);
}

.element-select :deep(.el-input__wrapper:hover) {
  border-color: #dee2e6;
}

.element-select :deep(.el-input__wrapper.is-focus) {
  background: #fff;
  border-color: var(--primary-color);
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.08);
}

/* 其他信息单列布局 */
.others-section {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}

/* 嵌套项全宽布局 */
.nested-item.full-width {
  flex-direction: column;
}

.nested-item.full-width :deep(.bold-textarea) {
  width: 100%;
}

.nested-item.full-width :deep(.content-area) {
  min-height: 80px;
}

/* 按钮布局优化 */
.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 1rem;
  padding: 1rem 1.5rem;
  border-top: 1px solid #303030;
  background-color: transparent;
  flex-shrink: 0;
}

.cancel-btn, .save-btn {
  min-width: 80px;
  padding: 0.5rem 1rem;
}

.save-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.save-btn:disabled .spinner {
  margin-right: 0.4rem;
}

/* 字段组的样式 */
.field-group label {
  font-family: 'GTPressuraMono-Light', sans-serif;
  font-size: 0.6875rem;
  font-weight: 400;
  color: #303030;
  margin-bottom: 0.2rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
}

.field-group input,
.field-group select,
.field-group textarea {
  width: 100%;
  padding: 0.5rem 0.6rem;
  border: 1px solid #e0e0e0;
  border-radius: 0;
  font-size: 0.8rem;
  font-family: 'GTPressuraMono-Light', sans-serif;
  background: #f5f4f2;
  transition: all 0.2s ease;
  color: #303030;
}

.field-group input:hover,
.field-group select:hover,
.field-group textarea:hover {
  border-color: #303030;
}

.field-group input:focus,
.field-group select:focus,
.field-group textarea:focus {
  outline: none;
  border-color: #303030;
  background: #fff;
  box-shadow: none;
}

.field-group input::placeholder,
.field-group textarea::placeholder {
  color: #999;
}

.field-group textarea {
  resize: vertical;
  min-height: 56px;
  line-height: 1.5;
}

.tags-input {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  padding: 0.5rem;
  border: 1px solid #e0e0e0;
  border-radius: 0;
  align-items: center;
  background: #f5f4f2;
}

.tags-input .tag {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.25rem 0.5rem;
  background-color: #e6e2dd;
  border-radius: 0;
  font-family: 'GTPressuraMono-Light', sans-serif;
  font-size: 0.6875rem;
  color: #303030;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.tags-input .tag-remove {
  background: none;
  border: none;
  cursor: pointer;
  padding: 0;
  font-size: 1rem;
  line-height: 1;
  color: #303030;
}

.tags-input .tag-remove:hover {
  color: #f8bebe;
}

.tags-input .tag-input {
  flex: 1;
  min-width: 100px;
  border: none;
  padding: 0.25rem;
  font-size: 0.875rem;
  background: transparent;
}

.tags-input .tag-input:focus {
  outline: none;
  box-shadow: none;
}

/* 字段组的 select 样式 */
.field-group select {
  width: 100%;
  padding: 0.5rem 0.6rem;
  border: 1px solid #e0e0e0;
  border-radius: 0;
  font-size: 0.8rem;
  font-family: 'GTPressuraMono-Light', sans-serif;
  background: #f5f4f2;
  cursor: pointer;
  transition: all 0.2s ease;
  color: #303030;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23303030' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 0.5rem center;
  padding-right: 1.5rem;
}

.field-group select:hover {
  border-color: #303030;
}

.field-group select:focus {
  outline: none;
  border-color: #303030;
  background-color: #fff;
}

.field-group select:hover {
  border-color: #dee2e6;
}

.field-group select:focus {
  outline: none;
  border-color: var(--primary-color);
  background: #fff;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.08);
}

/* 多行文本域样式 */
.multiline-textarea {
  width: 100%;
  min-height: 100px;
  max-height: 300px;
  padding: 0.75rem;
  border: 1px solid #e9ecef;
  border-radius: var(--radius-sm);
  font-size: 0.8rem;
  font-family: inherit;
  line-height: 1.6;
  resize: vertical;
  background: #fafafa;
  transition: all 0.2s ease;
}

.multiline-textarea:hover {
  border-color: #dee2e6;
}

.multiline-textarea:focus {
  outline: none;
  border-color: var(--primary-color);
  background: #fff;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.08);
}

/* 富文本编辑器样式 */
.rich-editor-field {
  width: 100%;
}

.rich-editor-field :deep(.rich-editor) {
  border: 1px solid #e9ecef;
  background: #fafafa;
}

.rich-editor-field :deep(.rich-editor:focus-within) {
  border-color: var(--primary-color);
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.08);
}

.rich-editor-field :deep(.editor-content) {
  min-height: 100px;
  max-height: 200px;
  font-size: 0.85rem;
}

/* ==================== 移动端响应式布局 ==================== */
@media (max-width: 1199px) {
  /* 主内容区域 */
  .main-content {
    flex-direction: column;
    height: calc(100vh - 48px);
    overflow: hidden;
  }

  .chat-section,
  .resume-section {
    flex: none;
    width: 100%;
    height: 100%;
    border-right: none;
  }

  /* 移动端聊天视图 */
  .mobile-chat-view {
    display: flex;
    flex-direction: column;
    height: 100%;
    overflow: hidden;
    background-color: rgb(254, 253, 251); /* 与PC端聊天区域背景色一致 */
    padding-bottom: 60px; /* 为底部导航栏留出空间 */
    position: relative;
  }

  .mobile-chat-view .chat-container {
    flex: 1;
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }

  .mobile-chat-view .messages-container {
    flex: 1;
    padding: 1rem;
    font-size: 14px;
  }

  /* 移动端输入区域 */
  .floating-input-container.mobile-input {
    padding: 12px 16px;
    padding-bottom: calc(12px + env(safe-area-inset-bottom, 0));
    background: #f9f5f0;
    border-top: 1px solid #e0e0e0;
    flex-shrink: 0;
  }

  .mobile-input .textarea-container {
    background-color: #fff;
    border: 1px solid #e0e0e0;
    border-radius: 8px;
  }

  .mobile-input .textarea-container textarea {
    min-height: 48px;
    padding: 14px;
    font-size: 16px;
  }

  .mobile-toolbar {
    height: 52px;
    padding: 0 4px;
  }

  .mobile-toolbar .icon-btn {
    width: 44px;
    height: 44px;
  }

  .mobile-toolbar .send-btn-placeholder {
    width: 44px;
    height: 44px;
  }

  /* 移动端简历视图 */
  .mobile-resume-view {
    height: 100%;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    padding-bottom: 60px; /* 为底部导航栏留出空间 */
  }

  /* 移动端设置视图 */
  .mobile-settings-view {
    padding: 2rem 1.5rem;
    overflow-y: auto;
  }

  .settings-content {
    max-width: 400px;
    margin: 0 auto;
  }

  .settings-content h2 {
    font-size: 1.25rem;
    margin-bottom: 1.5rem;
    font-weight: 600;
  }

  .settings-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1rem 0;
    border-bottom: 1px solid #e0e0e0;
  }

  .settings-value {
    color: #666;
    font-size: 0.875rem;
  }

  .settings-logout {
    width: 100%;
    margin-top: 2rem;
    padding: 0.875rem;
    font-size: 0.875rem;
  }

  /* Tab 内容切换动画 */
  .tab-content-enter-active,
  .tab-content-leave-active {
    transition: opacity 0.2s ease, transform 0.2s ease;
  }

  .tab-content-enter-from {
    opacity: 0;
    transform: translateX(20px);
  }

  .tab-content-leave-to {
    opacity: 0;
    transform: translateX(-20px);
  }

  .tab-content-enter-to,
  .tab-content-leave-from {
    opacity: 1;
    transform: translateX(0);
  }

  /* 上传文件区域适配 */
  .uploaded-files {
    padding: 8px 12px;
    gap: 8px;
  }

  .file-thumbnail {
    padding: 6px;
  }

  .file-name {
    font-size: 11px;
    max-width: 80px;
  }
}

/* 小屏幕适配 */
@media (max-width: 480px) {
  .mobile-tab-bar {
    height: 56px;
  }

  .mobile-tab-label {
    font-size: 10px;
  }

  .mobile-tab-icon {
    width: 20px;
    height: 20px;
  }

  .floating-input-container.mobile-input {
    padding: 10px 12px;
  }

  .mobile-input .textarea-container textarea {
    padding: 12px;
    font-size: 15px;
  }

  .mobile-toolbar .icon-btn {
    width: 40px;
    height: 40px;
  }

  .mobile-toolbar .send-btn-placeholder {
    width: 40px;
    height: 40px;
  }

  .messages-container {
    padding: 0.75rem;
    font-size: 13px;
  }
}
</style>
