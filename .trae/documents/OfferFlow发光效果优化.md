# Plan: OfferFlow 发光效果与动画优化

## 目标
为 Hero 区域的 OfferFlow 产品名添加加粗、发光效果和动画，提升品牌识别度。

## 修改内容

### 1. CSS 样式修改

修改 `.hero-title .product-name` 样式：

```css
.hero-title .product-name {
  font-family: 'GTPressuraMono-Light', sans-serif;
  font-size: clamp(1.25rem, 4vw, 2rem);  /* 放大 */
  font-weight: 700;  /* 加粗 */
  color: #d97706;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  margin-bottom: 0.5rem;
  /* 发光效果 */
  text-shadow: 
    0 0 10px rgba(217, 119, 6, 0.5),
    0 0 20px rgba(217, 119, 6, 0.3),
    0 0 30px rgba(217, 119, 6, 0.1);
  /* 动画 */
  animation: glow-pulse 2s ease-in-out infinite;
}
```

### 2. 添加发光动画 Keyframes

```css
@keyframes glow-pulse {
  0%, 100% {
    text-shadow: 
      0 0 10px rgba(217, 119, 6, 0.5),
      0 0 20px rgba(217, 119, 6, 0.3),
      0 0 30px rgba(217, 119, 6, 0.1);
  }
  50% {
    text-shadow: 
      0 0 15px rgba(217, 119, 6, 0.7),
      0 0 30px rgba(217, 119, 6, 0.5),
      0 0 45px rgba(217, 119, 6, 0.3);
  }
}
```

## 设计说明

- **加粗**: 使用 `font-weight: 700` 使 OfferFlow 更醒目
- **发光效果**: 使用多层 `text-shadow` 创造柔和的橙色光晕，与品牌色 (#d97706) 保持一致
- **动画**: 2秒周期的呼吸灯效果，让品牌名更加生动但不抢眼
- **字号放大**: 从 `clamp(1rem, 3vw, 1.5rem)` 改为 `clamp(1.25rem, 4vw, 2rem)`，更加突出

## 文件位置
- `/Users/weihaohuang/Desktop/DeepAgents/frontend/src/views/Homepage.vue` 第 271-279 行附近
