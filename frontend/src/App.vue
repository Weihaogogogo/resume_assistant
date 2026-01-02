<script setup>
import { ref, onMounted, watch, nextTick } from 'vue'
import ChatMessage from './components/ChatMessage.vue'
import ResumePreview from './components/ResumePreview.vue'

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
// 简历数据
const resumeData = ref(null)
// 加载状态
const isLoading = ref(false)
// 响应中状态（流式输出时）
const isResponding = ref(false)
// 加载文案状态
const loadingText = ref('正在处理中...')
let loadingTextInterval = null
// 全屏弹窗状态
const isFullscreenDialogOpen = ref(false)
const dialogUserInput = ref('')
// 会话ID - 用于保存对话历史
const sessionId = ref(localStorage.getItem('resumeAssistantSessionId') || '')

// 图片预览状态
const showImagePreview = ref(false)
const previewImageUrl = ref('')

// 模块高亮状态
const highlightedModule = ref('')

// 移除消息数量计算属性

// 初始化简历数据
onMounted(async () => {
  try {
    const response = await fetch('http://localhost:8000/load_resume', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({})
    })
    const data = await response.json()
    resumeData.value = data
    
    // 添加欢迎消息
    messages.value.push({
      id: Date.now(),
      role: 'assistant',
      content: '你好！我是简历助手，有什么可以帮助你的吗？你可以询问简历内容、修改简历信息等。'
    })
  } catch (error) {
    console.error('加载简历失败:', error)
    messages.value.push({
      id: Date.now(),
      role: 'assistant',
      content: '抱歉，加载简历失败。请确保MCP服务已启动。'
    })
  }
})

// 发送消息
async function sendMessage() {
  if ((!userInput.value.trim() && uploadedFiles.value.length === 0) || isLoading.value) return

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

    // 添加上传的文件
    // 注意：uploadedFiles 在函数开头已被清空，这里附件信息已保存在 currentAttachments 中
    currentAttachments.forEach((fileObj) => {
      formData.append('files', fileObj.file)
    })

    // 使用fetch API处理SSE流式响应
    const response = await fetch('http://localhost:8000/chat', {
      method: 'POST',
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
                  sessionId.value = data.session_id
                  localStorage.setItem('resumeAssistantSessionId', data.session_id)
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
              } else if (data.type === 'end') {
                // 结束信号，关闭连接
                isResponding.value = false
                // 只在流式响应结束时调用一次updateResumeData()
                updateResumeData()
                // 更新会话ID并保存到localStorage
                if (data.session_id) {
                  sessionId.value = data.session_id
                  localStorage.setItem('resumeAssistantSessionId', data.session_id)
                }
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

// 更新简历数据
async function updateResumeData() {
  try {
    // 先从服务器获取新数据
    const response = await fetch('http://localhost:8000/load_resume', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({})
    })
    const newData = await response.json()

    // 保存旧数据用于比较
    const oldData = resumeData.value ? JSON.parse(JSON.stringify(resumeData.value)) : null

    // 先更新数据
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

// 监听消息列表变化，自动滚动到底部
// 使用deep: true监听消息内容的变化，确保流式输出时也能自动滚动
watch(
  () => messages.value,
  () => {
    // 使用nextTick确保DOM已更新
    nextTick(() => {
      scrollToBottom()
    })
  },
  { deep: true }
)
</script>

<template>
  <!-- 顶部导航栏（全屏宽度） -->
  <header class="app-header">
    <div class="header-content">
      <h1>
        <svg class="app-icon" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path><line x1="12" y1="12" x2="12" y2="12.01"></line><line x1="8" y1="8" x2="8" y2="8.01"></line><line x1="16" y1="8" x2="16" y2="8.01"></line></svg>
        OfferFlow
      </h1>
      <!-- 移除消息数量提示 -->
      <div class="header-info">
      </div>
    </div>
  </header>
  
  <!-- 主内容区（居中显示） -->
  <div class="app-container">
    <div class="main-content">
      <!-- 左侧聊天区 -->
      <div class="chat-section">
        <div class="chat-container">
          <div class="messages-container" ref="messagesContainer">
            <ChatMessage
              v-for="message in messages"
              :key="message.id + '_' + (message.content?.length || 0)"
              :message="message"
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
            <button
              @click="fileInput?.click()"
              class="file-upload-btn"
              :disabled="isLoading"
              title="上传文件"
            >
              <svg class="upload-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
            </button>
            <div class="textarea-container">
              <textarea
                v-model="userInput"
                @keydown="handleKeyDown"
                @paste="handlePaste"
                placeholder="输入你的问题或请求..."
                rows="1"
                :disabled="isLoading"
              ></textarea>
              <button
                @click="openFullscreenDialog"
                class="fullscreen-btn"
                :disabled="isLoading"
                title="全屏输入"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"></path></svg>
              </button>
            </div>
            <button
              @click="sendMessage"
              :disabled="isLoading || isResponding || (!userInput.trim() && uploadedFiles.length === 0)"
              class="send-button"
            >
              <span>{{ isResponding ? 'Waiting...' : (isLoading ? 'Sending...' : 'Send') }}</span>
            </button>
          </div>
        </div>
      </div>
      
      <!-- 右侧简历预览区 -->
      <div class="resume-section">
        <div class="resume-content">
          <ResumePreview :data="resumeData" :highlighted-module="highlightedModule" />
        </div>
      </div>
    </div>
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
</template>

<style scoped>
.app-container {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 60px); /* 减去header高度 */
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
  background-color: var(--secondary-color);
  width: 100%;
  margin: 0;
  max-width: none;
}

.app-header {
  width: 100%;
  background-color: #ffffff;
  color: var(--text-primary);
  box-shadow: var(--shadow-sm);
  border-bottom: 1px solid var(--border-color);
  position: sticky;
  top: 0;
  z-index: 100;
  margin: 0;
}

.header-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 2rem;
  width: 100%;
  box-sizing: border-box;
  margin: 0;
}

.app-header h1 {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--text-primary);
}

.header-info {
  display: flex;
  gap: 1rem;
  font-size: 0.9rem;
  color: var(--text-secondary);
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
  flex: 0 0 40%; /* 聊天区域40%宽度，简历区域60% */
  display: flex;
  flex-direction: column;
  background-color: white;
  margin: 0;
  padding: 0;
  overflow: hidden;
  position: relative;
  border-right: 1px solid var(--border-color);
  height: 100%; /* 确保高度填满 */
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
  background-color: #ffffff;
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
}

.floating-input-container {
  position: relative;
  padding: 1rem;
  background: #ffffff;
  border-top: 1px solid var(--border-color);
  flex-shrink: 0;
}

.input-wrapper {
  display: flex;
  gap: 0.75rem;
  max-width: 100%;
  background-color: #ffffff;
  padding: 0.75rem;
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-md);
  transition: all 0.3s ease;
  border: 1px solid var(--border-color);
}

.input-wrapper:focus-within {
  box-shadow: 0 6px 25px rgba(0, 0, 0, 0.15);
  border-color: #333333;
}

/* 文件上传按钮样式 */
.file-upload-btn {
  padding: 0.75rem 1rem;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background-color: var(--secondary-color);
  color: var(--text-secondary);
  font-size: 0.9rem;
  cursor: pointer;
  transition: all 0.3s ease;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.file-upload-btn:hover {
  background-color: #f0f0f0;
  border-color: #333333;
  color: #333333;
}

.file-upload-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 文本域容器 */
.textarea-container {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  position: relative;
}

.textarea-container textarea {
  flex: 1;
  padding: 0.75rem 1rem;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  resize: none;
  font-size: 0.95rem;
  font-family: inherit;
  background-color: #ffffff;
  transition: all 0.3s ease;
  min-height: 42px;
  max-height: 120px;
  overflow-y: auto;
  /* 保持滚动功能但隐藏滚动条 */
  overflow-x: hidden;
}

/* 隐藏滚动条 */
.textarea-container textarea::-webkit-scrollbar {
  display: none;
}

.textarea-container textarea {
  -ms-overflow-style: none;
  scrollbar-width: none;
}

.textarea-container textarea:focus {
  outline: none;
  border-color: #333333;
  box-shadow: 0 0 0 3px rgba(0, 0, 0, 0.1);
  background-color: #ffffff;
}

/* 全屏按钮样式（在输入框内） */
.textarea-container .fullscreen-btn {
  padding: 0.5rem;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background-color: var(--secondary-color);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.3s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.textarea-container .fullscreen-btn:hover:not(:disabled) {
  background-color: #f0f0f0;
  border-color: #333333;
  color: #333333;
}

.textarea-container .fullscreen-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
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

.send-button {
  padding: 0.75rem 1.5rem;
  background-color: #333333;
  color: white;
  border: none;
  border-radius: var(--radius-md);
  font-size: 0.95rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s ease;
  align-self: flex-end;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.send-button:hover:not(:disabled) {
  background-color: #555555;
  transform: translateY(-2px);
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3);
}

.send-button:disabled {
  background-color: #ced4da;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.resume-section {
  flex: 1;
  max-width: none;
  background-color: white;
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
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.fullscreen-dialog {
  background-color: white;
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  width: 90%;
  max-width: 800px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.dialog-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid var(--border-color);
}

.dialog-header h3 {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--text-primary);
}

.dialog-close-btn {
  padding: 0.5rem;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
}

.dialog-close-btn:hover {
  background-color: var(--secondary-color);
  color: var(--text-primary);
}

.dialog-body {
  flex: 1;
  padding: 1.5rem;
  overflow: hidden;
}

.dialog-textarea {
  width: 100%;
  height: 100%;
  min-height: 300px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 1rem;
  font-size: 1rem;
  line-height: 1.6;
  resize: none;
  font-family: inherit;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.dialog-textarea:focus {
  outline: none;
  border-color: #333333;
  box-shadow: 0 0 0 3px rgba(51, 51, 51, 0.1);
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  padding: 1.25rem 1.5rem;
  border-top: 1px solid var(--border-color);
  background-color: var(--secondary-color);
}

.dialog-cancel-btn {
  padding: 0.75rem 1.5rem;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background-color: white;
  color: var(--text-secondary);
  font-size: 0.95rem;
  cursor: pointer;
  transition: all 0.2s ease;
}

.dialog-cancel-btn:hover {
  background-color: var(--secondary-color);
  color: var(--text-primary);
  border-color: var(--primary-color);
}

.dialog-save-btn {
  padding: 0.75rem 1.5rem;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background-color: white;
  color: var(--text-secondary);
  font-size: 0.95rem;
  cursor: pointer;
  transition: all 0.2s ease;
}

.dialog-save-btn:hover {
  background-color: var(--secondary-color);
  color: var(--text-primary);
  border-color: var(--primary-color);
}

.dialog-submit-btn {
  padding: 0.75rem 1.5rem;
  border: none;
  border-radius: var(--radius-md);
  background-color: var(--primary-color);
  color: white;
  font-size: 0.95rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.dialog-submit-btn:hover:not(:disabled) {
  background-color: var(--primary-hover);
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
</style>