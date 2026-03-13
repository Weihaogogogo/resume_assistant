<script setup>
const props = defineProps({
  start: {
    type: String,
    default: ''
  },
  end: {
    type: String,
    default: ''
  },
  isPresent: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['update:start', 'update:end', 'update:isPresent'])

function handleStartChange(value) {
  emit('update:start', value || '')
  if (props.end && value && props.end < value) {
    emit('update:end', '')
  }
}

function handleEndChange(value) {
  emit('update:end', value || '')
}

function handlePresentChange(event) {
  const checked = Boolean(event?.target?.checked)
  emit('update:isPresent', checked)
  if (checked) {
    emit('update:end', '')
  }
}

function disableEndBeforeStart(date) {
  if (!props.start) return false
  const startDate = new Date(`${props.start}-01T00:00:00`)
  return date < startDate
}
</script>

<template>
  <div class="range-picker">
    <div class="range-inputs">
      <el-date-picker
        :model-value="start || null"
        type="month"
        placeholder="开始时间"
        format="YYYY.MM"
        value-format="YYYY-MM"
        class="range-date-picker"
        @update:model-value="handleStartChange"
      />
      <span class="range-separator">至</span>
      <template v-if="!isPresent">
        <el-date-picker
          :model-value="end || null"
          type="month"
          placeholder="结束时间"
          format="YYYY.MM"
          value-format="YYYY-MM"
          class="range-date-picker"
          :disabled-date="disableEndBeforeStart"
          @update:model-value="handleEndChange"
        />
      </template>
      <template v-else>
        <div class="present-display">至今</div>
      </template>
      <label class="present-toggle">
        <input type="checkbox" :checked="isPresent" @change="handlePresentChange" />
        至今
      </label>
    </div>
  </div>
</template>

<style scoped>
.range-picker {
  width: 100%;
}

.range-inputs {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.range-date-picker {
  flex: 1;
  min-width: 180px;
}

.range-date-picker :deep(.el-input__wrapper) {
  background: transparent;
  border: 1px solid #303030;
  border-radius: 0;
  box-shadow: none;
}

.range-date-picker :deep(.el-input__wrapper:hover),
.range-date-picker :deep(.el-input__wrapper.is-focus) {
  box-shadow: none;
  border-color: #111;
}

.range-separator {
  font-size: 0.75rem;
  color: #303030;
  font-family: 'GTPressuraMono-Light', sans-serif;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.present-display {
  min-width: 180px;
  padding: 0.65rem 0.85rem;
  border: 1px solid #303030;
  color: #303030;
  background: rgba(48, 48, 48, 0.04);
  font-size: 0.875rem;
}

.present-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  width: fit-content;
  flex-shrink: 0;
  font-size: 0.75rem;
  color: #303030;
  font-family: 'GTPressuraMono-Light', sans-serif;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.present-toggle input[type="checkbox"] {
  width: 14px;
  height: 14px;
  accent-color: #303030;
}

@media (max-width: 640px) {
  .present-toggle {
    margin-left: 0;
  }
}
</style>
