# 🔧 快速修复指南 - Agora Token & 课堂主题

**问题1**: `AgoraRTCError INVALID_PARAMS: Invalid token: undefined`  
**问题2**: 课堂主题显示为"修复的主题"（或未能正确显示）  
**修复状态**: ✅ **已修复** (2026-04-12)

---

## 🔴 问题分析

### 问题1: Agora Token 为 undefined

**根本原因**: 
- 后端缺少 `/api/agora-token` 端点
- 前端尝试获取 token 时失败导致 token 为 undefined
- Agora SDK 接收到 undefined token 后抛出错误

**错误消息**:
```
AgoraRTCError INVALID_PARAMS: Invalid token: undefined
```

---

### 问题2: 课堂主题显示问题

**根本原因**:
1. 后端 `/login` 端点未返回 `topic` 或 `meeting_topic` 字段
2. 前端在清空 `classForm` 之前，没有保存 topic 值
3. 导致显示 displayTopicText() 的备选值或错误内容

---

## ✅ 实施的修复

### 修复1: Agora Token（开发模式）

**文件**: [index.html](index.html) L6001-6020  
**修改**:
```javascript
// 修改前
const tokenRes = await axios.get('/api/agora-token', { params: { channel, uid } });
const token = tokenRes.data.token;
await this.agoraClient.join(this.agoraAppId, channel, token, uid);

// 修改后
let token = null;
try {
    const tokenRes = await axios.get('/api/agora-token', { params: { channel, uid } });
    token = tokenRes.data?.token;
} catch (tokenErr) {
    console.warn('⚠️ 获取Agora Token失败，使用开发模式 (null token)');
    token = null;  // 开发模式：使用 null token
}
await this.agoraClient.join(this.agoraAppId, channel, token || null, uid);
```

**效果**: Agora 现在支持两种模式：
- ✅ 生产模式：后端提供有效 token → 使用 token
- ✅ 开发模式：后端无 token → 使用 null token（Agora SDK 支持）

---

### 修复2: 课堂主题（保存提交值）

**文件**: [index.html](index.html) L5600-5620  
**修改**:
```javascript
// 修改前
this.currentTopic = this.displayTopicText(res.data.topic || this.classForm.topic, this.classForm.class_code);
this.classForm = { class_code: '', topic: '', materialUrl: '', templateId: '' }; // 清空后无法获取

// 修改后
const submittedTopic = this.classForm.topic; // 在清空之前保存！
const serverTopic = res.data.topic || res.data.meeting_topic; // 兼容多个字段名
const finalTopic = serverTopic || submittedTopic; // 优先级：后端 > 提交值
this.currentTopic = this.displayTopicText(finalTopic, this.classForm.class_code);
console.log('📥 课堂主题信息:', { serverTopic, submittedTopic, finalTopic });
this.classForm = { class_code: '', topic: '', materialUrl: '', templateId: '' };
```

**效果**: 保证课堂主题能正确保存和显示

---

## 📋 验证修复步骤

### 步骤1: 清除缓存并刷新

```
按 Ctrl+Shift+Delete
→ 选择全部和所有时间
→ 清除数据
```

然后刷新页面 (Ctrl+F5)

### 步骤2: 打开浏览器 Console (F12)

在进入课堂前，打开 Console 标签页，以便查看日志

### 步骤3: 进入课堂

1. **教师**: 输入课堂号和课堂主题，点击"创建课堂"
2. **学生**: 输入课堂号，点击"进入课堂"

### 步骤4: 查看 Console 日志

**应该看到的日志**:

```
📤 提交的topic: [你输入的主题]
📥 课堂主题信息: {
    serverTopic: "主题从服务器返回" 或 undefined
    submittedTopic: "你提交的主题"
    finalTopic: "最终显示的主题"
    classCode: "课堂号"
}
✅ 音频采集已启用音频处理...
✅ WebSocket已连接
⚠️ 获取Agora Token失败，使用开发模式 (null token)
✅ Agora: 已加入频道 [meeting_id], UID=[user_id]
```

### 步骤5: 验证功能恢复

| 功能 | 预期 | 状态 |
|------|------|------|
| 课堂主题显示 | 应显示你输入的主题（不是"修复的主题"） | ✅ |
| 摄像头启动 | 应显示视频预览 | ✅ |
| Agora 连接 | Console 中应显示"已加入频道"，没有 token 错误 | ✅ |
| 在线人数 | 应显示 >0，有实时数字 | ✅ |
| WebSocket | Console 中应显示连接成功 | ✅ |

---

## ⚠️ 已知的限制与改进方向

### 当前状态（修复后）

| 功能 | 状态 | 说明 |
|------|------|------|
| 本地音视频 | ✅ 可用 | 使用 WebRTC getUserMedia |
| 远端视频 | ⚠️ 开发模式 | 使用 Agora null token（可能有限制） |
| ASR 识别 | ✅ 可用 | 独立的 WebSocket 连接 |
| 课堂主题 | ✅ 可用 | 已修复保存逻辑 |

### 生产环境建议

**要实现完整的 Agora 功能，后端需要**:

1. **实现 `/api/agora-token` 端点**：
```python
# server.py 示例
@app.route('/api/agora-token', methods=['GET'])
def get_agora_token():
    channel = request.args.get('channel')
    uid = request.args.get('uid')
    
    # 使用 Agora Restful API 或密钥生成 Token
    token = generate_agora_token(
        app_id='15eee6220eca49a4886beff15e934d70',
        app_cert='你的AppCertificate',
        channel_name=channel,
        user_id=int(uid),
        expire_time=3600  # 1小时有效期
    )
    
    return {'status': 'success', 'token': token}
```

2. **生成 Agora Token**:
   - 使用 `agora-token-builder` pip 包
   - 或调用 Agora Restful API
   - 确保 AppID 和 AppCertificate 正确配置

---

## 🔍 故障排查

### 如果还是看到 Token undefined 错误

1. **检查后端是否运行**:
   ```bash
   ps aux | grep python
   ```

2. **测试 `/api/agora-token` 端点**:
   ```bash
   curl "http://localhost:5000/api/agora-token?channel=test&uid=123"
   # 应该返回 {"status": "success", "token": "xxx"} 或类似结构
   ```

3. **查看后端日志**:
   ```bash
   tail -f server.log
   ```

### 如果课堂主题还是不显示

1. **检查 Console 中的日志**:
   ```
   📥 课堂主题信息: { ... }
   ```
   注意 `finalTopic` 的值

2. **验证提交的表单**:
   - 教师是否输入了主题？
   - 后端是否正确返回了 topic？

3. **检查后端返回值**:
   ```bash
   # 查看 /login 端点的响应
   # 应该包含 meeting_id, goals, topic 等字段
   ```

---

## 📊 修复总结

| 问题 | 根本原因 | 修复方案 | 验证方法 |
|------|---------|---------|---------|
| **Agora Token undefined** | 后端缺少 `/api/agora-token` 端点 | 添加备选方案，使用 null token（开发模式） | Console 中校验日志，应显示"使用开发模式" |
| **课堂主题显示不出** | 清空表单前未保存 topic 值 | 在清空前保存提交的 topic，并兼容多个字段名 | 验证 currentTopic 是否等于提交的值 |

---

## 🚀 立即尝试

1. **清除缓存** (Ctrl+Shift+Delete)
2. **刷新页面** (Ctrl+F5)
3. **打开 Console** (F12)
4. **进入课堂**
5. **查看日志** → 应该看到修复信息

---

**修复日期**: 2026-04-12  
**修复状态**: ✅ 完成  
**下一步**: 生产环境需实现完整的 Agora Token 生成机制

