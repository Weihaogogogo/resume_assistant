# 修复上传简历解析中弹窗loading态不一致问题

## 问题分析

### 根本原因

模板中解析中状态的显示条件是：

```vue
<div v-if="isParsingResume && !resumeImagePreview" class="parsing-status">
```

当用户点击"开始解析"按钮时：

* 第1744行设置了 `isParsingResume.value = true`

* 但 `resumeImagePreview` 仍然有值（用户选择文件时设置的预览图或 'pdf'）

* 导致条件 `isParsingResume && !resumeImagePreview` 不成立，无法显示解析中状态

而刷新页面时（第275行）：

* 同时设置了 `resumeImagePreview.value = ''` 和 `isParsingResume.value = true`

* 条件成立，所以能显示解析中状态

## 修复方案

### 步骤1：修复解析中弹窗loading态显示

在 `parseAndSaveResume` 函数中，设置 `isParsingResume.value = true` 的同时，清空 `resumeImagePreview`：

```javascript
isParsingResume.value = true
resumeImagePreview.value = ''  // 添加这行
```

### 步骤2：移除按钮的loading spinner

在模板中，按钮的loading态是通过以下代码实现的：

```vue
<button @click="parseAndSaveResume" :disabled="isParsingResume" class="btn-primary full-width">
  <span v-if="isParsingResume" class="btn-spinner"></span>
  {{ isParsingResume ? '解析中...' : '开始解析' }}
</button>
```

修改为移除 spinner 但保留 disabled 状态和文字变化：

```vue
<button @click="parseAndSaveResume" :disabled="isParsingResume" class="btn-primary full-width">
  {{ isParsingResume ? '解析中...' : '开始解析' }}
</button>
```

