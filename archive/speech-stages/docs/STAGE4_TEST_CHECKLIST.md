# 🎤 阶段4 - 前端音频约束实现 - 测试清单

**状态**: ✅ **完全实现** | 时间: 2026-04-12 | 版本: 1.0

---

## 📋 动态验证清单

### 1️⃣ 代码级别验证 (✅ 已完成)

#### getUserMedia / getDisplayMedia 调用
- [x] **L5660** - getDisplayMedia (屏幕共享)
  ```javascript
  audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1}
  ```
  状态: ✅ 已更新

- [x] **L5664** - getUserMedia (屏幕共享失败回退)
  ```javascript
  audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1}
  ```
  状态: ✅ 已更新

- [x] **L5667** - getUserMedia (非屏幕共享路径)
  ```javascript
  audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1}
  ```
  状态: ✅ 已更新

- [x] **L5670** - getUserMedia (学生用户路径)
  ```javascript
  audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1, sampleRate: { ideal: 16000 }}
  ```
  状态: ✅ 已更新

#### 音频约束参数
- [x] `echoCancellation: true` - 回声消除
- [x] `noiseSuppression: true` - 噪声抑制
- [x] `autoGainControl: true` - 自动增益控制
- [x] `channelCount: 1` - 单声道
- [x] `sampleRate: { ideal: 16000 }` - 16kHz采样率

#### 用户通知
- [x] L5675-L5676 - showToast() 消息
  ```javascript
  showToast('✅ 音频采集已启用音频处理（回声消除、噪声抑制、自动增益）\n📢 为获得最佳效果，建议使用耳机！', 5000);
  ```
  状态: ✅ 已添加

#### 调试日志
- [x] L5677-L5684 - console.log() 输出约束信息
  状态: ✅ 已添加

---

### 2️⃣ 手动浏览器测试 (🔄 待执行)

#### 测试环境准备
- [ ] 打开 Chrome/Edge 浏览器
- [ ] 访问 `http://localhost:5000` (或对应的web服务地址)
- [ ] 打开开发者工具 (F12) → Console 选项卡

#### 测试用例 A: 带约束的音频采集
1. [ ] 点击"开始课程"或类似的开始按钮
2. [ ] 观察Console输出:
   ```
   ✅ [阶段4] 音频约束已应用: {
       echoCancellation: true,
       noiseSuppression: true,
       autoGainControl: true,
       channelCount: 1,
       sampleRate: '16kHz'
   }
   ```
3. [ ] 观察前端显示的 Toast 提示信息:
   ```
   ✅ 音频采集已启用音频处理（回声消除、噪声抑制、自动增益）
   📢 为获得最佳效果，建议使用耳机！
   ```
4. [ ] 观察浏览器权限提示是否正确
5. [ ] 验证摄像头/屏幕共享开始工作

#### 测试用例 B: WebSocket 消息验证
1. [ ] 打开 Network 选项卡
2. [ ] 过滤 WebSocket 消息
3. [ ] 找到 `asr-stream` 或类似的WebSocket连接
4. [ ] 观察Frames列表中的消息，查找:
   - [ ] `audio_rms` 字段 (音频RMS采样值)
   - [ ] `speaker_confidence` 字段 (说话人置信度)
   - [ ] `speaker_rank` 字段 (说话人排名)
5. [ ] 验证这些字段值是否合理 (RMS范围: 0-100, confidence范围: 0-1)

#### 测试用例 C: 音量表现对比
1. [ ] 打开 [audio_constraint_test.html](audio_constraint_test.html)
2. [ ] **路径A**: 点击"✅ 测试（带约束）"按钮
   - [ ] 允许音频权限
   - [ ] 观察右侧实时音量表
   - [ ] 典型表现: 50-70% 的稳定音量，波动 <20%
3. [ ] 停止音频流
4. [ ] **路径B**: 点击"❌ 对比（无约束）"按钮
   - [ ] 允许音频权限
   - [ ] 观察右侧实时音量表
   - [ ] 典型表现: 不稳定，可能出现 30-90% 的大波动，<5% 的尖峰噪声

#### 测试用例 D: 物理环境测试
在有回声和噪音的环境测试 (如卡拉OK厅、教室、开放办公室)
- [ ] **带约束**: 回声明显减少，背景噪音更安静，说话声音更清晰
- [ ] **无约束**: 明显的回声，背景噪音很突出，说话声音可能刺耳或模糊

---

### 3️⃣ 浏览器兼容性检查 (🔄 待执行)

| 浏览器 | 版本 | echoCancellation | noiseSuppression | autoGainControl | 备注 |
|-------|------|:----------------:|:----------------:|:---------------:|------|
| Chrome | 94+ | ✅ | ✅ | ✅ | 完全支持 |
| Edge | 94+ | ✅ | ✅ | ✅ | 完全支持 |
| Firefox | 25+ | ⚠️ 部分 | ❌ 不支持 | ✅ | 仅支持 echoCancellation 和 autoGainControl |
| Safari | 14.1+ | ✅ | ⚠️ 部分 | ✅ | iOS 15+ 完全支持 |

**降级策略**: 所有约束都使用 `ideal` 而非 `exact`，浏览器不支持时会自动忽略相应参数。

---

### 4️⃣ 性能验证 (🔄 待执行)

#### CPU 使用率测试
- [ ] 带约束: 约 5-10% CPU (预期)
- [ ] 无约束: 约 2-3% CPU (基线)
- [ ] **预期**: 约增加 3-5% 的CPU负担用于音频处理

#### 内存使用
- [ ] 长时间运行 (>30分钟) 是否有内存泄漏
- [ ] 观察 Chrome DevTools → Memory:
  - [ ] 启动时 ~50MB
  - [ ] 长时间运行后增长 <10MB

#### 音频捕获延迟 (Latency)
- [ ] 说话 → WebSocket 消息 ≤ 200ms (端到端)
- [ ] 约束不应增加显著的延迟

---

### 5️⃣ 集成验证 (🔄 待执行)

#### 与阶段1-3的协同工作
- [ ] Stage 1 (发言人锁): 带约束的音频是否正确触发lock
- [ ] Stage 2 (重复文本抑制): 带约束的音频是否降低重复识别率
- [ ] Stage 3 (音量仲裁): 带约束的音频RMS是否更稳定

#### 测试场景: 同一教室3个学生
1. [ ] 学生A (有约束): 清晰说话
2. [ ] 学生B (有约束): 轻声说话
3. [ ] 学生C (有约束): 嘈杂背景下说话
4. [ ] **预期结果**:
   - [ ] Stage 1: 只有1个学生的音频进入ASR
   - [ ] Stage 2: 重复文本 <2%
   - [ ] Stage 3: RMS正确排名，confidence梯度明显 (1.0 > 0.8 > 0.5)

---

## 📊 测试结果记录

### 代码验证结果
```
✅ 音频约束参数验证:
  ✅ echoCancellation     已应用
  ✅ noiseSuppression     已应用
  ✅ autoGainControl      已应用
  ✅ channelCount         已应用
  ✅ sampleRate           已应用

✅ 功能检查:
  ✅ 所有约束参数都已定义          
  ✅ 所有媒体获取调用都已更新
  ✅ 用户通知已添加

📈 整体状态: ✅ 完全实现
```

### 手动测试结果
*(待测试环境就绪后填写)*

| 测试项 | 预期 | 实际 | 状态 | 备注 |
|------|------|------|------|------|
| Console 日志输出 | 显示约束配置 | - | ⏳ 待测 | - |
| Toast 通知显示 | 提示音频处理已启用 | - | ⏳ 待测 | - |
| 音量表现对比 | 带约束更稳定 | - | ⏳ 待测 | - |
| WebSocket 消息 | 包含RMS和confidence字段 | - | ⏳ 待测 | - |
| Stage 1-3协同 | 相互配合正常 | - | ⏳ 待测 | - |

---

## 🎯 下一步

### 立即可以做的
1. ✅ 代码验证完成 (所有约束已应用)
2. ✅ 创建了测试工具 (`audio_constraint_test.html`)
3. ✅ 创建了验证脚本 (`verify_stage4.py`)

### 需要在测试环境中做的
1. 🔄 运行浏览器手动测试 (用例A-D)
2. 🔄 测试多浏览器兼容性
3. 🔄 验证与Stage 1-3的集成
4. 🔄 记录性能数据

### 阶段5准备
一旦Stage 4测试完成，开始实现**交互式兜底方案**:
- [ ] **PTT模式** (Push-To-Talk 按住说话)
- [ ] **举手系统** (Hand-raising queue)
- [ ] **教师干预** (Teacher override)

---

## 📁 相关文件

| 文件 | 说明 |
|------|------|
| [index.html](index.html) | 主前端文件 (已更新L5660, L5664, L5667, L5670) |
| [audio_constraint_test.html](audio_constraint_test.html) | 独立的约束测试工具 |
| [verify_stage4.py](verify_stage4.py) | 自动化验证脚本 |
| [STAGE4_FRONTEND_AUDIO_CONSTRAINT_IMPLEMENTATION.md](STAGE4_FRONTEND_AUDIO_CONSTRAINT_IMPLEMENTATION.md) | 详细实现文档 |
| [STAGE4_VERIFICATION_REPORT.json](STAGE4_VERIFICATION_REPORT.json) | 验证报告 (JSON格式) |

---

## 💡 故障排查

### 问题 1: 没有看到约束日志
**原因**: Browser DevTools Console 未打开或被过滤  
**解决**: 
- 按 F12 打开 DevTools
- 在 Console 中搜索 "[阶段4]"
- 确保 Verbose 级别日志已启用

### 问题 2: Toast 通知没有显示
**原因**: showToast() 方法可能被覆盖或 Vue 组件未加载  
**解决**:
- 检查 Console 中是否有错误信息
- 验证 Vue app 是否正确初始化 (看页面标题和导航)

### 问题 3: 某些浏览器检测不到约束
**原因**: 旧版浏览器或浏览器权限设置  
**解决**:
- 使用最新版本浏览器 (Chrome 94+)
- 检查浏览器麦克风权限 (地址栏最右侧)
- 在audio_constraint_test.html中使用对比模式

### 问题 4: 音频效果没有改善
**原因**: 
- 硬件可能不支持noise suppression
- 可能是环形回声 (设备指向扬声器)
- 可能需要更好的麦克风
  
**解决**:
- 尝试使用耳机中的麦克风 (内建麦克风可能更难处理)
- 检查 audio_constraint_test.html 的 WebRTC Stats → audio track settings
- 验证 sampleRate 确实被设置为 16000

---

## 📞 联系与反馈

测试中遇到问题? 提供以下信息:
1. 浏览器和版本 (Chrome 94, Firefox 115, ...)
2. 操作系统 (Windows 10, macOS 13, ...)
3. Console 中的错误信息 (复制完整错误堆栈)
4. audio_constraint_test.html 显示的约束值
5. Network WebSocket 消息示例

---

**最后更新**: 2026-04-12  
**测试清单版本**: 1.0  
**阶段状态**: ✅ 代码实现完成，🔄 待浏览器测试

