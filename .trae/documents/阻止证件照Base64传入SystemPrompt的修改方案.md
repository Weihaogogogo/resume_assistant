# 阻止证件照 Base64 编码传入 System Prompt 的修改方案

## 问题分析

### 问题根源

在 `resume_agent.py` 的 `conversation_node` 函数（第 500-512 行）中，`resume_data` 被完整序列化为 JSON 后传入 system prompt。如果 `resume_data.basics.photo` 包含 base64 编码的证件照数据，这些数据会被包含在提示词中，导致提示词长度膨胀至约 20,000 字。

### 当前

```
Resume 表
├── user_id: int
├── name: str
├── resume_data: JSON  ← 包含 basics.photo (base64编码的证件照)
├── parsing_status: str
└── ...

简历 JSON 结构示例：
{
  "basics": {
    "name": "张三",
    "photo": "data:image/jpeg;base64,/9j/4AAQSkZJRg...",  ← 问题所在
    "email": "..."
  },
  "work": [...],
  "education": [...]
}
```

### 相关代码位置

* **核心问题代码**: [resume\_agent.py](file:///Users/weihaohuang/Desktop/DeepAgents/resume_agent.py#L500-L512) - `conversation_node` 函数中的 `CONVERSATION_PROMPT` 替换逻辑

* **照片数据来源**: [mcp\_service\_simple.py](file:///Users/weihaohuang/Desktop/DeepAgents/mcp_service_simple.py#L523-606) - 简历解析端点接收前端传递的 base64 图片

* **系统提示词定义**: [resume\_agent.py](file:///Users/weihaohuang/Desktop/DeepAgents/resume_agent.py#L160-L233) - `CONVERSATION_PROMPT` 模板

* **数据库模型**: [database.py](file:///Users/weihaohuang/Desktop/DeepAgents/database.py#L38-L47) - Resume 表定义

***

## 方案对比

### 方案 A：快速修复（推荐先做）

在传入 system prompt 时过滤掉 photo 字段，同时在保存时恢复证件照。

**优点**：

* 改动小，风险低

* 快速解决问题

**缺点**：

* photo 字段仍然存在于 resume\_data JSON 中，不够干净

### 方案 B：重构架构（更彻底的解决方案）

将证件照从 resume\_data 中解耦，单独存储在 Resume 表的独立字段中。

**重构后的数据结构**：

```
Resume 表
├── user_id: int
├── name: str
├── resume_data: JSON  ← 不再包含 photo 字段
├── photo: str         ← 单独存储证件照 base64
├── parsing_status: str
└── ...

简历 JSON 结构示例：
{
  "basics": {
    "name": "张三",
    "email": "...",
    // photo 字段移除
  },
  "work": [...],
  "education": [...]
}
```

**优点**：

* 架构更清晰，photo 和 resume\_data 完全解耦

* 无需在各处过滤/恢复 photo 字段

* PDF 导出、前端渲染时再拼接

**缺点**：

* 改动较大，涉及数据库迁移和多处代码修改

***

**建议**：先实施方案 A 快速解决问题，再在后续迭代中实施方案 B 进行架构优化。

## 修改方案

### 方案概述

在 `conversation_node` 函数中，将 `resume_data` 序列化为 JSON 之前，过滤掉 `basics.photo` 字段，避免 base64 编码的证件照传入 system prompt。

### 具体实现步骤

#### 步骤 1: 修改 `conversation_node` 函数

**文件**: `resume_agent.py`
**位置**: 第 500-512 行附近

**修改前**:

```python
if state.resume_data:
    resume_json = json.dumps(state.resume_data, ensure_ascii=False, indent=2)
    system_content = CONVERSATION_PROMPT.replace("{{resume_data}}", f"\n{resume_json}\n")
else:
    system_content = CONVERSATION_PROMPT.replace("{{resume_data}}", "\n（简历数据尚未加载）")
```

**修改后**:

```python
if state.resume_data:
    # 过滤掉 photo 字段，避免 base64 编码的证件照传入 system prompt
    filtered_resume_data = _filter_photo_from_resume(state.resume_data)
    resume_json = json.dumps(filtered_resume_data, ensure_ascii=False, indent=2)
    system_content = CONVERSATION_PROMPT.replace("{{resume_data}}", f"\n{resume_json}\n")
else:
    system_content = CONVERSATION_PROMPT.replace("{{resume_data}}", "\n（简历数据尚未加载）")
```

#### 步骤 2: 添加过滤辅助函数

**文件**: `resume_agent.py`
**位置**: 在 `conversation_node` 函数之前添加

**新增函数**:

```python
def _filter_photo_from_resume(resume_data):
    """
    过滤掉简历数据中的 photo 字段，避免 base64 编码的证件照传入 LLM。
    
    Args:
        resume_data: 完整的简历数据字典
        
    Returns:
        过滤后的简历数据副本
    """
    if not resume_data:
        return resume_data
    
    import copy
    filtered_data = copy.deepcopy(resume_data)
    
    if 'basics' in filtered_data and 'photo' in filtered_data['basics']:
        filtered_data['basics']['photo'] = ""
    
    return filtered_data
```

#### 步骤 3: 修改保存确认接口，防止证件照丢失

**文件**: `mcp_service_simple.py`
**位置**: 第 1047-1049 行附近

**修改前**:

```python
# 保存修改后的简历数据
from tools import update_resume
result = update_resume(updated_resume_data, user_id=current_user.id)
```

**修改后**:

```python
# 保存修改后的简历数据（保留原证件照）
from tools import update_resume

# 从数据库获取原简历数据
old_resume = get_user_resume(db, current_user.id)
if old_resume and old_resume.get('basics', {}).get('photo'):
    # 如果原简历有证件照且新数据没有，则恢复证件照
    if not updated_resume_data.get('basics'):
        updated_resume_data['basics'] = {}
    if not updated_resume_data['basics'].get('photo'):
        updated_resume_data['basics']['photo'] = old_resume['basics']['photo']

result = update_resume(updated_resume_data, user_id=current_user.id)
```

***

## 方案 B：重构架构 - 具体实现步骤

### 步骤 1: 修改数据库模型，添加 photo 字段

**文件**: `database.py`
**位置**: Resume 类定义（第 38-47 行）

**修改后**:

```python
class Resume(Base):
    """简历数据表"""
    __tablename__ = "resumes"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    name = Column(String(100), default="默认简历")
    resume_data = Column(JSON, default=dict)
    photo = Column(Text, default="")  # 新增：单独存储证件照 base64
    parsing_status = Column(String(20), default="none")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

### 步骤 2: 数据库迁移

需要执行数据库迁移，为现有用户的 photo 字段填充数据：

```python
# 迁移脚本（一次性）
def migrate_photo_to_separate_field(db):
    """将 resume_data 中的 photo 迁移到独立的 photo 字段"""
    resumes = db.query(Resume).all()
    for resume in resumes:
        if resume.resume_data and resume.resume_data.get('basics', {}).get('photo'):
            resume.photo = resume.resume_data['basics']['photo']
            # 从 resume_data 中移除 photo
            resume.resume_data['basics'].pop('photo', None)
    db.commit()
```

### 步骤 3: 修改简历解析接口，分离证件照存储

**文件**: `mcp_service_simple.py`
**位置**: parse\_and\_save\_resume\_endpoint（第 523-606 行附近）

**修改逻辑**:

* 解析简历时，将提取的 photo 存储到 Resume.photo 字段

* 从 resume\_data 中移除 photo 字段

* 保存时同时保存 resume\_data 和 photo

### 步骤 4: 修改保存接口

**文件**: `mcp_service_simple.py`
**位置**: confirm\_save\_endpoint（第 1047-1049 行附近）

**修改逻辑**:

* 保存时，从 updated\_resume\_data 中提取 photo

* 分别存储到 Resume.photo 和 Resume.resume\_data

### 步骤 5: 修改 PDF 生成逻辑

**文件**: `pdf_generator.py`
**位置**: 第 47-49 行附近

**修改前**:

```python
if basics.get("photo"):
    html_parts.append(f'<img src="{basics["photo"]}" class="profile-photo" alt="证件照" />')
```

**修改后**:

```python
# 从 resume_data 中获取 photo（已移除）
# 证件照从 Resume.photo 字段单独获取
if resume.photo:
    html_parts.append(f'<img src="{resume.photo}" class="profile-photo" alt="证件照" />')
```

### 步骤 6: 修改前端渲染逻辑

**文件**: `frontend/src/App.vue`
**位置**: 与显示证件照相关的代码

**修改逻辑**:

* 前端获取简历时，分别获取 resume\_data 和 photo

* 渲染时拼接显示

### 步骤 7: 移除过滤逻辑（方案 A 不再需要）

由于 photo 已单独存储，resume\_data 中不再包含 photo 字段，方案 A 的过滤逻辑不再需要。

***

## 涉及的代码模块

### 方案 A 涉及模块

| 模块   | 文件路径                    | 作用                               |
| ---- | ----------------------- | -------------------------------- |
| 核心逻辑 | `resume_agent.py`       | 修改 `conversation_node` 函数和添加过滤函数 |
| 保存确认 | `mcp_service_simple.py` | 添加证件照恢复逻辑，确保保存时不丢失证件照            |

### 方案 B 涉及模块

| 模块    | 文件路径                    | 作用                           |
| ----- | ----------------------- | ---------------------------- |
| 数据库模型 | `database.py`           | 添加 photo 字段                  |
| 简历解析  | `mcp_service_simple.py` | 分离存储证件照                      |
| 保存确认  | `mcp_service_simple.py` | 分离保存证件照                      |
| PDF生成 | `pdf_generator.py`      | 从独立字段获取证件照                   |
| 前端    | `frontend/src/App.vue`  | 从独立字段获取证件照渲染                 |
| 核心逻辑  | `resume_agent.py`       | 无需修改（resume\_data 不再含 photo） |

***

## 测试验证方法

### 测试用例设计

#### 1. 单元测试：验证过滤函数

```python
def test_filter_photo_from_resume():
    # 测试数据：包含 photo 字段的简历
    resume_with_photo = {
        "basics": {
            "name": "张三",
            "photo": "data:image/jpeg;base64,/9j/4AAQSkZJRg..."
        },
        "work": [...]
    }
    
    # 执行过滤
    result = _filter_photo_from_resume(resume_with_photo)
    
    # 验证：photo 字段应为空字符串
    assert result["basics"]["photo"] == ""
    # 验证：其他字段应保持不变
    assert result["basics"]["name"] == "张三"
```

#### 2. 集成测试：验证 system prompt 不包含 base64

1. 准备包含证件照的简历数据
2. 调用 `conversation_node` 函数
3. 检查生成的 system\_content 中不包含 base64 编码字符串

#### 3. 功能测试：确保其他文本内容正常处理

* 测试不含照片的简历能否正常处理

* 测试 JD 数据能否正常传入

* 测试对话功能是否正常工作

***

## ⚠️ 重要问题：证件照丢失风险分析

### 问题描述

经过深入分析代码流程，发现存在证件照丢失的风险：

**数据流程**：

1. 用户上传简历（包含证件照）→ 解析 → 存储在 SQLite 数据库的 `resume_data` 中
2. AI 调用 `save_resume_tool` 时，传入 AI 生成的完整 JSON
3. 用户确认 → 调用 `update_resume` → **直接覆盖保存到数据库**

**风险点**：

* 如果 system prompt 中不包含 `photo` 字段，AI 生成的简历 JSON 也不会包含 `photo`

* 保存时直接覆盖，导致原有的证件照数据丢失

### 解决方案

**采用"保存时恢复"策略**：在用户确认保存简历时，自动从数据库中获取旧简历数据，将新数据中没有的 `photo` 字段从旧数据中恢复。

**修改位置**：`mcp_service_simple.py` 第 1047-1049 行

**修改前**：

```python
# 保存修改后的简历数据
from tools import update_resume
result = update_resume(updated_resume_data, user_id=current_user.id)
```

**修改后**：

```python
# 保存修改后的简历数据（保留原证件照）
from tools import update_resume

# 从数据库获取原简历数据
old_resume = get_user_resume(db, current_user.id)
if old_resume and old_resume.get('basics', {}).get('photo'):
    # 如果原简历有证件照且新数据没有，则恢复证件照
    if not updated_resume_data.get('basics'):
        updated_resume_data['basics'] = {}
    if not updated_resume_data['basics'].get('photo'):
        updated_resume_data['basics']['photo'] = old_resume['basics']['photo']

result = update_resume(updated_resume_data, user_id=current_user.id)
```

### 为什么这个方案更好？

1. **安全性**：确保证件照永远不会丢失
2. **解耦**：过滤逻辑和保存逻辑分离，各司其职
3. **兼容性**：不影响 AI 的正常功能，同时减少 system prompt 长度

如果未来需要更精细地控制哪些字段需要过滤，可以在 `resume_agent.py` 中定义一个配置列表：

```python
# 需要过滤的字段列表（不会传给 LLM）
FILTERED_RESUME_FIELDS = ['photo']

def _filter_photo_from_resume(resume_data):
    if not resume_data:
        return resume_data
    
    import copy
    filtered_data = copy.deepcopy(resume_data)
    
    if 'basics' in filtered_data:
        for field in FILTERED_RESUME_FIELDS:
            if field in filtered_data['basics']:
                filtered_data['basics'][field] = ""
    
    return filtered_data
```

这样可以方便地扩展需要过滤的字段。

***

## 影响评估

### 正面影响

1. **减少 token 消耗**：移除照片的 base64 数据后，每次对话请求可节省大量 tokens
2. **提升响应速度**：提示词长度减少，LLM 处理速度提升
3. **降低 API 成本**：减少 token 使用量直接降低 API 调用成本
4. **保护隐私**：证件照不必要地暴露给 LLM 的问题得以解决

### 无负面影响

* 简历的其他文本内容完全不受影响

* PDF 生成功能使用独立的 `resume_data`，不受此修改影响

* 前端显示证件照的功能不受影响（前端直接使用 `basics.photo`）

***

## 实施检查清单

### 方案 A 检查清单

* [ ] 在 `resume_agent.py` 中添加 `_filter_photo_from_resume` 辅助函数

* [ ] 修改 `conversation_node` 函数中的 JSON 序列化逻辑

* [ ] 在 `mcp_service_simple.py` 的确认保存接口中，添加证件照恢复逻辑

* [ ] 运行现有测试确保功能正常

* [ ] 手动验证：上传包含证件照的简历，进行对话测试，确认提示词长度正常

* [ ] 手动验证：让 AI 修改简历，确认后证件照仍然存在

### 方案 B 检查清单

* [ ] 修改 `database.py` 中 Resume 类，添加 photo 字段

* [ ] 执行数据库迁移脚本

* [ ] 修改 `mcp_service_simple.py` 简历解析接口，分离存储证件照

* [ ] 修改 `mcp_service_simple.py` 保存接口，分别保存 resume\_data 和 photo

* [ ] 修改 `pdf_generator.py` 从独立字段获取证件照

* [ ] 修改前端 `App.vue` 渲染逻辑

* [ ] 验证所有功能正常工作（简历上传、对话、修改、PDF导出）

