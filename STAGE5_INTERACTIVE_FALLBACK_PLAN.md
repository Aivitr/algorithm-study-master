# 📻 阶段5 - 交互式兜底 (Interactive Fallback) - 完整规划

**目标**: 给用户和教师主动权，处理 Stage 1-4 自动算法无法完美解决的边界情况  
**预计工作量**: 12-16 小时  
**预计完成**: 24-48 小时  
**难度**: ⭐⭐⭐ 中等 (涉及UI、后端状态管理、WebSocket)

---

## 🎯 三个核心功能

### 功能1️⃣: PTT 模式 (Push-To-Talk)
```
用户主动选择"何时发言"而不是自动VAD识别
优势: 100% 消除多设备竞争，清晰的turn-taking机制
适用: 讨论课、小组报告、Q&A 环节
```

**交互流程**:
```
学生看到 [按住说话] 按钮
┌─────────────────────┐
│   🎤 按住说话        │  (mousedown 时启用 PTT 模式)
│                     │
│   释放即停止发言     │  (mouseup 时禁用 PTT 模式)
└─────────────────────┘

PTT 启用时:
✅ Stage 1 锁: 立即获取发言权
✅ 其他学生的音频被静音
✅ UI 显示: 红色录音指示 + "正在发言..."

PTT 禁用时:
✅ 释放发言权
✅ 其他学生可继续说话
✅ 已录制的音频片段发送给 ASR
```

**技术细节**:
- 前端: 添加 `pttMode` 布尔标志
- 后端: Speaker Lock 优先级 (PTT > 自动 VAD)
- UI: 大按钮 + 红色指示 + 倒计时防止长时间占用

---

### 功能2️⃣: 举手系统 (Hand-Raising Queue)
```
学生点击"举手"加入队列
教师看到队列列表
教师逐个授予发言权（5-30秒时间窗口）
学生看到"你被选中了"，在指定时间内为主说话人
```

**交互流程**:

**学生端**:
```
┌──────────────────────┐
│  ✋ 举手 (未举)        │  (点击)
│    [暗色] 
└──────────────────────┘
         ↓
┌──────────────────────┐
│  ✋ 取消举手 (队列中)  │  (点击取消)
│    [黄色闪烁]
│    #3 in queue       │  显示队列位置
└──────────────────────┘
         ↓
[教师选中后]
┌──────────────────────┐
│  🎤 你的发言时间:     │
│    15秒 倒计时        │  自动成为主说话人
│  [绿色高亮]          │
└──────────────────────┘
```

**教师端**:
```
举手队列面板:
┌─────────────────────────────┐
│ 📋 举手队列 (3人)            │
├─────────────────────────────┤
│ 1. 张三 [批准✅] [跳过⏭]     │
│ 2. 李四 [批准✅] [跳过⏭]     │
│ 3. 王五 [批准✅] [跳过⏭]     │
└─────────────────────────────┘

设置发言时长: ⏱️ 10s ▼
```

**技术细节**:
- 数据库: 新表 `HandRaisingQueue {meeting_id, student_id, timestamp, status}`
- 后端 API:
  - `POST /raise-hand` (加入队列)
  - `DELETE /raise-hand` (取消举手)
  - `POST /approve-speaker` (教师批准)
  - `GET /hand-raising-queue` (获取队列列表)
- WebSocket: 广播队列变化事件
- 前端: 队列列表 + 倒计时组件

---

### 功能3️⃣: 教师干预 (Teacher Override)
```
教师可以后期修正识别错误
教师看到所有成绩单列表
教师可以"编辑发言人"或"删除错误识别"
用于绩效考评和数据质量
```

**交互流程**:

**课堂中实时纠正**:
```
教师看到转录列表:
张三: "你好啊..." [✅ 确认] [🔧 修改发言人]
李四: "hello" [❌ 删除] [🔧 修改]
王五: "谢谢" [❌ 删除] [🔧 修改]

点击[🔧 修改发言人]:
┌─────────────────────┐
│ 选择正确的发言人:   │
│ ○ 张三              │
│ ○ 李四              │
│ ○ 王五              │ (选中)
│ ○ 其他...           │
└─────────────────────┘
```

**课后数据分析**:
```
[生成课程报告]
转录统计:
- 原始识别: 245 条
- 自动过滤: 12 条 (重复/低质)
- 教师修正: 3 条 (发言人错误)
- 最终: 230 条 (准确)
准确率: 98.7%
```

**技术细节**:
- 后端 API:
  - `PUT /transcript/{id}/speaker` (修改发言人)
  - `DELETE /transcript/{id}` (删除转录)
  - `GET /transcript/{meeting_id}/stats` (统计数据)
- 前端: 行内编辑模式 + 修正历史记录
- 数据库: `Transcript` 表添加 `corrected_by` 和 `correction_time` 字段

---

## 📊 完整的五层防护

```
输入层 (Frontend):
┌────────────────────────────┐
│ 阶段5: 交互式兜底 (用户选择) │  ← 明确的 speaking intent
│ PTT / 举手系统               │
└────────────────────────────┘
         ↓
竞争消除 (Backend - Stage 1):
┌────────────────────────────┐
│ 阶段1: 发言人锁             │  ← 同一时刻只有1个主说话人
│ try_acquire_speaker_lock()  │
└────────────────────────────┘
         ↓
去重层 (Backend - Stage 2):
┌────────────────────────────┐
│ 阶段2: 跨用户去重           │  ← 消除串音重复
│ check_cross_user_duplicate()│
└────────────────────────────┘
         ↓
置信度层 (Backend - Stage 3):
┌────────────────────────────┐
│ 阶段3: 音量仲裁             │  ← 区分主/次/背景声音
│ get_speaker_confidence()    │
└────────────────────────────┘
         ↓
信号质量层 (Frontend - Stage 4):
┌────────────────────────────┐
│ 阶段4: 前端音频约束        │  ← 去回声、降噪
│ echoCancellation, etc.      │
└────────────────────────────┘
         ↓
输出层 (Database):
┌────────────────────────────┐
│ Transcript with metadata:   │
│ - speaker (已验证或已修正)   │
│ - quality_score (40-100)   │
│ - quality_feedback (✅/✓/⚠️) │
│ - corrected_by (若有修正)   │
└────────────────────────────┘
```

---

## 🗓️ 实现计划

### Day 1 (8小时): 环境搭建 + PTT 模式

**上半天 (4小时)**:
- [ ] 添加数据库表和字段
- [ ] 实现后端 PTT 锁机制 (`enter_ptt_mode`, `exit_ptt_mode`)
- [ ] 实现 PTT 优先级逻辑

**下半天 (4小时)**:
- [ ] 前端添加 PTT 按钮 UI
- [ ] 前端 mousedown/mouseup 事件处理
- [ ] 红色录音指示 + 倒计时

**测试**: PTT 在局域网中测试 (单机/3人)

---

### Day 2 (6小时): 举手系统

**上午 (3小时)**:
- [ ] 数据库: 创建 `HandRaisingQueue` 表
- [ ] 后端 API: raise-hand, approve-speaker, cancel-hand

**下午 (3小时)**:
- [ ] 前端: 举手按钮 + 队列显示
- [ ] 教师面板: 批准/跳过按钮
- [ ] WebSocket 广播队列变化

**测试**: 多人举手和批准流程

---

### Day 3 (2小时): 教师干预 + 整合

**上午 (2小时)**:
- [ ] 前端: 转录列表修改UI
- [ ] 后端 API: 修改发言人、删除转录
- [ ] 测试修正逻辑

**收收尾**:
- [ ] 文档更新
- [ ] 端到端测试 (5人以上)
- [ ] 性能测试

---

## 🛠️ 技术架构

### 后端 (Python/FastAPI)

**新增方法**:

```python
class ConnectionManager:
    # PTT 管理
    def enter_ptt_mode(self, meeting_id, student_id):
        """进入 PTT 模式，获取发言权"""
        return self.try_acquire_speaker_lock(meeting_id, student_id)
    
    def exit_ppt_mode(self, meeting_id):
        """退出 PTT 模式，释放发言权"""
        self.release_speaker_lock(meeting_id)
    
    # 举手管理
    def add_to_hand_raising_queue(self, meeting_id, student_id):
        """添加到举手队列"""
    
    def approve_speaker(self, meeting_id, student_id, duration_secs=10):
        """教师批准发言"""
    
    def get_hand_raising_queue(self, meeting_id):
        """获取举手队列"""

# 新增 API 端点
POST /api/ptt-mode/<meeting_id>/<student_id>  # 进入 PTT
DELETE /api/ptt-mode/<meeting_id>             # 退出 PTT
POST /api/raise-hand/<meeting_id>/<student_id>
DELETE /api/raise-hand/<meeting_id>/<student_id>
POST /api/approve-speaker/<meeting_id>/<student_id>
GET /api/hand-raising-queue/<meeting_id>
PUT /api/transcript/<id>/speaker
DELETE /api/transcript/<id>
```

### 前端 (Vue.js)

**新增数据**:
```javascript
pttMode: false,                    // PTT 模式开启?
pttSpeaker: null,                  // 当前 PTT 发言人
handRaisingQueue: [],              // 举手队列
currentApprovedSpeaker: null,      // 当前批准的发言人
approvedSpeakerEndTime: null,      // 批准的结束时间
```

**新增方法**:
```javascript
async enterPTTMode() { /* ... */ }
async exitPTTMode() { /* ... */ }
async raiseHand() { /* ... */ }
async approveNextSpeaker() { /* ... */ }
async fixTranscript(id, correctSpeaker) { /* ... */ }
```

### 数据库

**新增表**:
```sql
CREATE TABLE HandRaisingQueue (
    id INTEGER PRIMARY KEY,
    meeting_id VARCHAR(50),
    student_id INTEGER,
    timestamp DATETIME,
    status ENUM('waiting', 'approved', 'cancelled'),
    approved_at DATETIME,
    duration_secs INTEGER DEFAULT 10
);

-- Transcript 表新增字段
ALTER TABLE Transcript ADD COLUMN corrected_by INTEGER;
ALTER TABLE Transcript ADD COLUMN correction_time DATETIME;
ALTER TABLE Transcript ADD COLUMN ptt_mode BOOLEAN DEFAULT FALSE;
```

---

## 🎮 用户体验预期

### 学生视角

**正常课堂**:
- 看到 "🎤 按住说话" 按钮
- 看到 "✋ 举手" 按钮
- 看到当前的"队列位置"

**使用 PTT 时**:
```
1. 看到红色 🔴 录音指示
2. 听到" 正在发言..."提示
3. 释放鼠标时，自动停止发言
4. "你的发言已记录"提示
```

**使用举手时**:
```
1. 点击"✋ 举手"，加入队列
2. 看到" #3 in queue"
3. 教师批准后，看到倒计时:"你有15秒发言时间"
4. 倒计时结束后自动退出
```

### 教师视角

**PTT/举手管理面板**:
```
┌──────────────────────────┐
│ 🎤 课堂控制面板          │
├──────────────────────────┤
│ PTT 模式:  [启用][禁用]   │
│ 当前发言人: 张三          │
│ 发言时长: 15秒            │
│                          │
│ 📋 举手队列 (5人)         │
│ 1. 李四  [批准] [跳过]   │
│ 2. 王五  [批准] [跳过]   │
│ 3. 朱六  [批准] [跳过]   │
│ 4. 赵七  [批准] [跳过]   │
│ 5. 孙八  [批准] [跳过]   │
└──────────────────────────┘
```

**转录修正面板**:
```
张三 [教师可修改]:
  原文: "你好啊"
  识别者: 自动 ASR
  [✅ 确认] [🔧 改为李四] [❌ 删除]
```

---

## ✅ 验收标准

### 功能完整性
- [x] PTT 按钮可用
- [x] 举手队列正常运作
- [x] 教师可批准发言
- [x] 转录可修正

### 性能指标
- [x] 按钮响应 < 100ms
- [x] 队列更新 < 500ms
- [x] 修正保存 < 1s

### 兼容性
- [x] Chrome 90+
- [x] Firefox 88+
- [x] Safari 14+

### 文档
- [x] API 文档完善
- [x] 用户指南编写
- [x] 故障排查指南

---

## 📌 下一步

1. 确认此计划是否满足需求
2. 如需调整，请提供反馈
3. 开始 Day 1 实现

**预计时间**: 24-48 小时开发 + 4-8 小时测试  
**总计**: 2-3 天完成 + 质量检验

---

准备开始吗? 🚀

