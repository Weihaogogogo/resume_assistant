<template>
  <div class="rich-editor">
    <!-- 编辑区域 -->
    <div
      ref="editorRef"
      class="editor-content"
      contenteditable="true"
      :placeholder="placeholder"
      @input="onInput"
      @keydown.ctrl.b="handleCtrlB"
      @keydown.meta.b="handleCtrlB"
      @paste="handlePaste"
      @blur="onBlur"
    ></div>
    <!-- 提示 -->
    <div class="editor-hint">
      <span class="hint-text">提示：选中文字后按 <kbd>Ctrl+B</kbd> 加粗</span>
      <span class="line-count">{{ displayLineCount }} 行</span>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, nextTick, computed } from 'vue'

const props = defineProps({
  modelValue: {
    type: String,
    default: ''
  },
  placeholder: {
    type: String,
    default: '请输入内容'
  }
})

const emit = defineEmits(['update:modelValue'])

const editorRef = ref(null)
const isUpdating = ref(false) // 避免循环更新
const displayLineCount = ref(0) // 实时显示的行数

// 计算行数（从 HTML 内容实时计算）
function updateLineCount() {
  if (!editorRef.value) return
  const html = editorRef.value.innerHTML
  // 将 <br> 转为换行，计算换行次数
  const text = html.replace(/<br\s*\/?>/gi, '\n').replace(/<\/div>/gi, '\n').replace(/<div[^>]*>/gi, '\n')
  // 移除 HTML 标签
  const plainText = text.replace(/<[^>]+>/g, '')
  // 解码 HTML 实体
  const decodedText = plainText.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
  // 计算行数
  const lines = decodedText.split('\n').filter(line => line.trim()).length
  displayLineCount.value = lines || 0
}

// 实时输入处理（只用于更新行数，不同步数据）
function onInput() {
  updateLineCount()
}

// 格式化文本：将 **text** 转为 <b>text</b>
function formatToHtml(text) {
  if (!text) return ''
  // 转义 HTML 特殊字符
  let escaped = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  // 将换行转为 <br>
  escaped = escaped.replace(/\n/g, '<br>')
  // 将 **text** 转为 <b>text</b>
  escaped = escaped.replace(/\*\*(.*?)\*\*/g, '<b>$1</b>')
  return escaped
}

// 解析 HTML 为纯文本（保留 ** 标记）
function parseToText(html) {
  if (!html) return ''
  // 将 <b> 转回 **
  let text = html.replace(/<b>/g, '**').replace(/<\/b>/g, '**')
  // 将 <br> 和 <div> 转为换行
  text = text.replace(/<br\s*\/?>/gi, '\n').replace(/<\/div>/gi, '\n').replace(/<div[^>]*>/gi, '\n')
  // 移除其他 HTML 标签
  text = text.replace(/<[^>]+>/g, '')
  // 解码 HTML 实体
  text = text.replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
  // 清理多余的换行
  text = text.replace(/\n{3,}/g, '\n\n')
  return text.trim()
}

function onBlur() {
  // 只在失去焦点时同步数据到父组件
  if (editorRef.value && !isUpdating.value) {
    const text = parseToText(editorRef.value.innerHTML)
    if (text !== props.modelValue) {
      emit('update:modelValue', text)
    }
  }
}

function handleCtrlB(e) {
  e.preventDefault()
  const selection = window.getSelection()
  if (selection.rangeCount > 0) {
    const range = selection.getRangeAt(0)
    let selectedText = range.toString()

    if (selectedText) {
      // 检查选中的文字是否已经在一个 <b> 标签内
      const container = range.commonAncestorContainer
      const parentB = container.nodeType === Node.TEXT_NODE
        ? container.parentElement.closest('b')
        : container.closest('b')

      if (parentB) {
        // 取消加粗：移除 <b> 标签，保留文字内容
        const textNode = document.createTextNode(parentB.textContent)
        parentB.parentNode.replaceChild(textNode, parentB)

        // 恢复选区
        const newRange = document.createRange()
        newRange.setStart(textNode, 0)
        newRange.setEnd(textNode, textNode.textContent.length)
        selection.removeAllRanges()
        selection.addRange(newRange)
      } else {
        // 添加加粗：插入 <b> 标签
        const boldNode = document.createElement('b')
        boldNode.textContent = selectedText

        range.deleteContents()
        range.insertNode(boldNode)

        // 移动光标到加粗文本后面
        const newRange = document.createRange()
        newRange.setStartAfter(boldNode)
        newRange.setEndAfter(boldNode)
        selection.removeAllRanges()
        selection.addRange(newRange)
      }

      // 更新行数
      updateLineCount()
    }
  }
}

function handlePaste(e) {
  e.preventDefault()
  const text = e.clipboardData.getData('text/plain')
  // 插入纯文本
  document.execCommand('insertText', false, text)
  // 更新行数
  updateLineCount()
}

// 更新显示（从 modelValue 到 HTML）
function updateDisplay() {
  if (editorRef.value && !isUpdating.value) {
    const currentHtml = editorRef.value.innerHTML
    const formatted = formatToHtml(props.modelValue || '')

    // 比较并更新
    const currentText = parseToText(currentHtml)
    if (currentText !== props.modelValue) {
      isUpdating.value = true
      editorRef.value.innerHTML = formatted || '<br>'
      nextTick(() => {
        isUpdating.value = false
        updateLineCount()
      })
    }
  }
}

// 监听 modelValue 变化（从父组件传入）
watch(() => props.modelValue, (newVal) => {
  if (newVal !== undefined) {
    nextTick(() => {
      updateDisplay()
    })
  }
}, { immediate: true })

onMounted(() => {
  nextTick(() => {
    updateDisplay()
    updateLineCount()
  })
})
</script>

<style scoped>
.rich-editor {
  width: 100%;
  border: 1px solid #e9ecef;
  border-radius: var(--radius-sm);
  background: #fafafa;
  transition: all 0.2s ease;
}

.rich-editor:focus-within {
  border-color: var(--primary-color);
  background: #fff;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.08);
}

.editor-content {
  width: 100%;
  min-height: 120px;
  max-height: 250px;
  padding: 0.75rem;
  font-size: 0.85rem;
  line-height: 1.6;
  outline: none;
  white-space: pre-wrap;
  word-break: break-word;
  overflow-y: auto;
  font-family: inherit;
}

/* 让 contenteditable 按 Enter 时插入 <br> 而不是 <div> */
.editor-content div {
  display: inline;
}

.editor-content:empty:before {
  content: attr(placeholder);
  color: #adb5bd;
  pointer-events: none;
}

.editor-content b {
  font-weight: 600;
  color: var(--text-primary);
}

.editor-hint {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.4rem 0.75rem;
  background: #f8f9fa;
  border-top: 1px solid #e9ecef;
  font-size: 0.75rem;
  color: #adb5bd;
  border-radius: 0 0 var(--radius-sm) var(--radius-sm);
}

.hint-text {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.hint-text kbd {
  display: inline-block;
  padding: 0.15rem 0.4rem;
  font-size: 0.7rem;
  font-family: inherit;
  background: #fff;
  border: 1px solid #dee2e6;
  border-radius: 3px;
  box-shadow: 0 1px 0 #dee2e6;
}

.line-count {
  color: #adb5bd;
}

/* 隐藏滚动条但保留功能 */
.editor-content::-webkit-scrollbar {
  width: 6px;
}

.editor-content::-webkit-scrollbar-track {
  background: transparent;
}

.editor-content::-webkit-scrollbar-thumb {
  background: #dee2e6;
  border-radius: 3px;
}

.editor-content::-webkit-scrollbar-thumb:hover {
  background: #ced4da;
}
</style>
