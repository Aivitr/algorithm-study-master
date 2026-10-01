// 配置axios
axios.defaults.timeout = 120000; // 120秒超时（增加到120秒处理大量数据）
axios.defaults.headers.common['Accept'] = 'application/json; charset=utf-8';
axios.defaults.headers.post['Content-Type'] = 'multipart/form-data';

// 添加请求拦截器
axios.interceptors.request.use(
    config => {
        console.log('📤 发送请求:', config.method.toUpperCase(), config.url);
        return config;
    },
    error => {
        console.error('❌ 请求错误:', error);
        return Promise.reject(error);
    }
);

// 添加响应拦截器
axios.interceptors.response.use(
    response => {
        console.log('📥 收到响应:', response.config.url, response.status);
        // 调试：打印响应数据，特别是包含中文的字段
        if (response.config.url.includes('/api/class-history') || response.config.url.includes('/api/reports')) {
            console.log('响应数据:', response.data);
            if (response.data.history) {
                console.log('历史记录数据:', response.data.history.map(h => ({ topic: h.topic, class_code: h.class_code })));
            }
            if (response.data.reports) {
                console.log('报告数据:', response.data.reports.map(r => ({ meeting_topic: r.data?.meeting_topic })));
            }
        }
        return response;
    },
    error => {
        console.error('❌ 响应错误:', error.message);
        if (error.code === 'ECONNABORTED') {
            console.error('⏱️ 请求超时，数据量过大或网络慢');
            // 不弹窗，只打印日志，给用户温和的提示
        } else if (error.response) {
            console.error('响应状态:', error.response.status);
            console.error('响应数据:', error.response.data);
        } else {
            console.error('网络连接失败，请检查服务器是否启动');
        }
        return Promise.reject(error);
    }
);

new Vue({
    el: '#app',
    data: {
        // 通用弹窗
        globalModal: { show: false, type: 'alert', icon: 'info', title: '', message: '', _resolve: null },
        // 页面状态: 'landing' | 'login' | 'register' | 'lobby' | 'classroom'
        pageState: 'landing',  // ✅ 默认显示落地页
        // 主界面标签页: 'home' | 'history' | 'report' | 'profile' | 'settings'
        activeTab: 'home',
        // 课堂标签页: 'chat' | 'history' | 'summary' | 'ai'
        classroomTab: 'chat',
        // 用户信息
        currentUser: null,
        // 声纹身份绑定
        voiceprintStatus: 'idle', // idle | loading | registered | unregistered | error
        voiceprintRecorder: null,
        voiceprintStream: null,
        voiceprintChunks: [],
        voiceprintAudioBlob: null,
        voiceprintAudioUrl: '',
        voiceprintRecordingMode: 'register',
        voiceprintRecordingSeconds: 0,
        voiceprintRecordingTimer: null,
        isRecordingVoiceprint: false,
        voiceprintUploading: false,
        voiceprintVerifyResult: null,
        // 学习报告列表
        myReports: [],
        reportGenerating: false,
        reportProgress: '',
        reportExercises: {},  // 缓存已加载的习题 {report_id: [exercises]}
        // 答题系统
        quizActive: false,
        quizReportId: null,
        quizTitle: '',
        quizQuestions: [],
        quizCurrentIndex: 0,
        quizAnswers: {},       // {questionIndex: selectedOption}
        quizResults: {},       // {questionIndex: 'correct'|'wrong'}
        quizCorrectCount: 0,
        quizStreak: 0,
        quizMaxStreak: 0,
        quizShowFeedback: '',  // 'correct'|'wrong'|''
        quizShowAnswer: false,
        quizShortAnswers: {},  // {questionIndex: text} for text input
        quizCompleted: false,
        quizEasterEgg: false,
        quizEasterEggText: '',
        quizErrorSummary: null, // AI错题分析结果
        quizErrorLoading: false,
        // 目标完成弹窗
        goalCompletePopup: { show: false, goals: [], allDone: false },
        // 话题建议弹窗
        topicSuggestion: { show: false, text: '', reason: '' },
        classroomHintTimer: null,
        lastClassroomHintAt: 0,
        lastClassroomHintText: '',
        classroomHintCooldownMs: 120000,
        topicSuggestionTimer: null,
        lastTopicSuggestionAt: 0,
        lastTopicSuggestionText: '',
        topicSuggestionCooldownMs: 180000,
        // 沉默检测定时器
        silenceCheckTimer: null,
        quietCheckTimer: null,
        // 登录表单
        loginForm: { student_id: '', password: '' },
        // 注册表单
        registerForm: { student_id: '', username: '', password: '', confirmPassword: '', role: 'student' },
        // 课堂表单
        classForm: { class_code: '', topic: '', materialUrl: '', templateId: '' },
        // 上传的文件
        uploadedFile: null,
        // 弹窗状态
        showClassModal: false,
        showAITutor: false,
        // AI辅导老师(个人中心)
        aiMessages: [],
        aiInput: '',
        aiLoading: false,
        // 课堂AI对话
        classroomAIMessages: [],
        classroomAIInput: '',
        classroomAILoading: false,
        // 课堂状态
        joined: false, loading: false, isPaused: false, errorMsg: '', form: {username:'', class_code:'', topic:'', role:'student'},
        currentTopic: '', goals: [], msgs: [], currentRelevance: 0, hint: null,
        ws: null, wsHeartbeatTimer: null, recorder: null, audioCtx: null, analyser: null, dataArray: null, volumeLevel: 0, silenceStart: null, isSpeaking: false, speakingStartTime: null, statusText: 'Listening...', recordingStartTime: null,
        localMediaStream: null,
        // ===== 声网 Agora SDK (替代 WebRTC Mesh) =====
        agoraAppId: 'd3144900be6843d8a8c14271f1da8cdb',
        agoraClient: null,           // AgoraRTCClient 实例
        agoraLocalAudioTrack: null,  // 本地音频轨道
        agoraLocalVideoTrack: null,  // 本地视频轨道
        agoraRemoteUsers: {},        // {uid: {videoTrack, audioTrack}} 远端用户轨道
        remoteStreams: {},            // {username: true/false} 标记远端视频是否可用（兼容模板）
        speakingMembers: {},          // {username: true/false} 语音活跃检测
        pinnedMember: null,           // 双击放大的成员
        currentSubtitle: null, subtitleTimer: null,
        realtimeSubtitle: null, realtimeSubtitleTimer: null, realtimeSubtitleLastAt: 0,
        asrWs: null, audioProcessor: null, audioSource: null,
        asrWsSeq: 0,
        asrReconnectTimer: null,
        asrDroppedFrames: 0,
        asrHealthTimer: null,
        asrLastMessageAt: 0,
        browserRecognition: null,
        browserAsrActive: false,
        browserAsrRestartTimer: null,
        browserAsrLastFinal: '',
        browserAsrLastFinalAt: 0,
        showKnowledgeGraph: false, knowledgeGraphData: null, chartInstance: null,
        classStartTime: null, timerInterval: null, meetingId: null,
        // 新增: 观点聚类投票
        showViewpointVote: false,
        viewpoints: [],
        viewpointSummary: '',
        viewpointLoading: false,
        selectedViewpoint: null,
        subGoals: [],
        subGoalGuidance: '',
        currentVoteId: null,
        voteResults: {},  // {viewpoint_id: [usernames]}
        voteCounts: {},   // {viewpoint_id: count}
        myVote: null,     // 我投给哪个
        voteConfirmed: false, // 是否已确认选择
        confirmedMembers: [], // 已确认选择的成员列表
        voteDecomposing: false, // 正在分解任务
        onlineMembers: [], // 在线成员列表
        // 新增: 实时统计图表
        showStatsPanel: false,
        pieChartData: [],
        interactionData: { nodes: [], edges: [] },
        emotionTimeline: {},
        memberScores: [], // 成员打分数据
        statsLoading: false,
        // 新增: 情绪分析
        showEmotionDetails: false,  // 是否展示情绪详情
        individualEmotions: {},      // 个体情绪数据（学生端只有自己）
        allIndividualEmotions: {},   // 完整个体情绪数据（用于群体图表）
        groupEmotionTimeline: [],    // 群体情绪趋势
        videoSegments: [],           // 视频片段列表
        selectedMember: null,        // 当前选中的成员
        emotionMode: 'group',        // 'group' 或 'individual'
        playingVideo: null,          // 当前播放的视频
        playingSnapshot: null,       // 当前查看的快照
        // 悬浮卡片状态（防误触）
        hoverCard: {
            visible: false,
            x: 0,
            y: 0,
            data: null
        },
        // 视频播放器状态
        videoPlayer: {
            visible: false,
            url: '',
            startTime: 0,
            loading: true
        },
        // 图表实例缓存
        chartInstances: {},          // 缓存所有ECharts实例
        // 定时器
        emotionRefreshTimer: null,   // 情绪数据刷新定时器
        statsRefreshTimer: null,     // 统计数据刷新定时器
        realtimeDataRefreshTimer: null,
        // 防抖锁
        loadingStats: false,         // 统计数据加载中
        loadingEmotions: false,      // 情绪数据加载中
        // ✅ 请求取消控制器（用于取消旧请求）
        videoRequestController: null,  // 视频查询请求控制器
        statsRequestController: null,  // ✅ 统计请求控制器
        emotionRequestController: null,  // ✅ 情绪请求控制器
        // 新增: 历史记录
        classHistory: [],
        studentHomeSummary: null,
        historyLoading: false,
        historyLoaded: false,
        reportsLoading: false,
        reportsLoaded: false,
        // 新增: 教师小组监控
        activeGroups: [],
        viewingGroupId: null,  // 正在查看的小组
        // 新增: 推荐资料
        recommendedMaterials: [],
        showMaterialsPanel: false,
        // 教师端专属数据
        teacherStats: { totalClasses: 0, totalStudents: 0, avgScore: 0, riskGroups: 0 },
        teacherClasses: [],
        // 新增: 教师查看小组报告
        viewingGroupReports: false,
        groupReports: [],
        currentViewingMeetingId: null,
        allStudentReports: [],
        studentReportsLoading: false,
        studentReportsLoaded: false,
        reportFilter: { classId: '', studentName: '' },
        customTemplate: null,
        selectedClass: null,
        classDetailGroups: [],
        // 教师数据看板
        showTeacherDashboard: false,
        tdMeetingId: null,
        tdGroupInfo: null,
        tdPieData: [],
        tdInteractionData: null,
        tdMemberScores: [],
        tdIndividualEmotions: {},
        tdGroupEmotionTimeline: [],
        tdSelectedMember: '',
        tdTimeWindow: 0,
        tdChartInstances: {},
        tdLoading: false,
        tdRefreshTimer: null,
        tdRequestController: null,
        tdRequestSeq: 0,
        tdSwitchLoading: false,
        tdWindowDebounceTimer: null,
        tdVideoPlayer: { visible: false, url: '', startTime: 0, loading: false },
        // Landing首屏相关数据
        cardPreview: null,  // 卡片预览弹窗数据
        showDemoVideo: false,  // 是否显示演示视频
        cardData: {  // 卡片配置数据
            classroom: {
                title: '实时课堂',
                icon: 'fas fa-chalkboard-teacher',
                gradient: 'linear-gradient(135deg, #3E7C86 0%, #4BA3B0 100%)',
                detail: '支持多人音视频实时互动，AI自动评分与质量反馈，让每次发言都获得专业指导。教师可实时查看学生参与度和学习状态。'
            },
            vote: {
                title: '投票讨论',
                icon: 'fas fa-vote-yea',
                gradient: 'linear-gradient(135deg, #F59E0B 0%, #FBBF24 100%)',
                detail: '智能观点聚类功能，自动整合学生观点并生成投票项。实时展示投票结果，帮助教师快速掌握班级整体观点分布。'
            },
            emotion: {
                title: '情绪分析',
                icon: 'fas fa-smile',
                gradient: 'linear-gradient(135deg, #EC4899 0%, #F87171 100%)',
                detail: '基于CV技术的实时情绪识别，精准捕捉学生学习过程中的情绪波动。支持个体与群体情绪双视角，并提供视频回放功能。'
            },
            graph: {
                title: '知识图谱',
                icon: 'fas fa-project-diagram',
                gradient: 'linear-gradient(135deg, #10B981 0%, #34D399 100%)',
                detail: 'AI自动构建课堂讨论的知识图谱，智能识别关键概念及关联关系。帮助学生建立系统性知识结构，提升学习效果。'
            },
            report: {
                title: '智能报告',
                icon: 'fas fa-file-alt',
                gradient: 'linear-gradient(135deg, #3B82F6 0%, #60A5FA 100%)',
                detail: '课堂结束后自动生成详细的学习分析报告，包括参与度、发言质量、情绪曲线等多维度数据。支持PDF导出和个性化模板定制。'
            }
        }
    },
    computed: {
        currentQuizQ() {
            return (this.quizQuestions && this.quizQuestions[this.quizCurrentIndex]) || {};
        },
        voiceprintIdentity() {
            if (!this.currentUser) return '';
            return String(this.currentUser.student_id || this.currentUser.username || '');
        },
        voiceprintStatusLabel() {
            const labels = {
                loading: '读取中',
                registered: '已绑定',
                unregistered: '未绑定',
                error: '状态异常',
                idle: '未读取'
            };
            return labels[this.voiceprintStatus] || '未读取';
        },
        voiceprintStatusIcon() {
            const icons = {
                loading: 'fas fa-spinner fa-spin',
                registered: 'fas fa-circle-check',
                unregistered: 'fas fa-circle-dot',
                error: 'fas fa-circle-exclamation',
                idle: 'fas fa-circle'
            };
            return icons[this.voiceprintStatus] || 'fas fa-circle';
        },
        quizWrongQuestions() {
            const wrongs = [];
            for (let i = 0; i < this.quizQuestions.length; i++) {
                if (this.quizResults[i] === 'wrong') {
                    const q = this.quizQuestions[i];
                    wrongs.push({
                        index: i,
                        question: q.question,
                        correctAnswer: this._getCorrectAnswerText(q)
                    });
                }
            }
            return wrongs;
        },
        votedCount() {
            const votedSet = new Set();
            Object.values(this.voteResults || {}).forEach(voters => {
                (voters || []).forEach(v => votedSet.add(v));
            });
            return votedSet.size;
        },
        videoMembers() {
            // 只显示实际加入 Agora 的用户（有视频流的用户）
            const members = [];
            // 添加自己
            if (this.currentUser && this.currentUser.student_id) {
                members.push(String(this.currentUser.student_id));
            }
            // 添加远端用户（按 UID 排序保证顺序稳定）
            const remoteUids = Object.keys(this.agoraRemoteUsers || {}).sort();
            remoteUids.forEach(uid => {
                if (uid && uid !== String(this.currentUser.student_id)) {
                    members.push(uid);
                }
            });
            return members;
        },
        displayMsgs() {
            const list = Array.isArray(this.msgs) ? this.msgs : [];
            const normalize = (text) => String(text || '')
                .trim()
                .replace(/\s+/g, '')
                .replace(/[，。！？、,.!?;；:"“”'‘’（）()【】\[\]{}<>《》]/g, '')
                .toLowerCase();
            const identityOf = (m) => {
                if (!m) return '';
                if (m.asr_sentence_id) return `asr:${m.asr_sentence_id}`;
                if (m.client_msg_id) return `client:${m.client_msg_id}`;
                if (m.transcript_id) return `transcript:${m.transcript_id}`;
                return '';
            };
            const messageScore = (m) => {
                if (!m) return -1;
                const feedback = String(m.quality_feedback || '');
                const pending = feedback.includes('正在') || feedback.includes('评估中') || feedback.includes('识别中');
                return (
                    (m.asr_only ? 0 : 1000) +
                    (m.transcript_id ? 500 : 0) +
                    (m.quality_score ? 100 : 0) +
                    (feedback && !pending ? 80 : 0) +
                    normalize(m.text).length
                );
            };
            const result = [];
            const seen = {};
            for (let i = 0; i < list.length; i++) {
                const m = list[i];
                if (!m) continue;
                const currentText = normalize(m.text);
                const hasLaterReplacement = list.some((x, idx) => {
                    if (!x || idx === i || x.username !== m.username) return false;
                    if (x.type !== 'new_speech_fast' && x.type !== 'new_speech') return false;
                    const dt = Math.abs((Number(x.timestamp) || 0) - (Number(m.timestamp) || 0));
                    if (dt > 120000) return false;
                    const other = normalize(x.text);
                    if (!currentText || !other || other.length < currentText.length) return false;
                    const similar = this.textSimilarity(currentText, other);
                    return other.length > currentText.length * 1.2 && (other.includes(currentText) || (currentText.length <= 12 && similar >= 0.45));
                });
                if (hasLaterReplacement) continue;
                if (m.asr_only) {
                    const hasRealSibling = list.some((x, idx) => {
                        if (!x || idx === i || x.username !== m.username || x.asr_only) return false;
                        const dt = Math.abs((Number(x.timestamp) || 0) - (Number(m.timestamp) || 0));
                        if (dt > 30000) return false;
                        const other = normalize(x.text);
                        const similar = this.textSimilarity(currentText, other);
                        return currentText && other && (currentText === other || currentText.includes(other) || other.includes(currentText) || (Math.max(currentText.length, other.length) <= 8 && similar >= 0.45));
                    });
                    if (hasRealSibling) continue;
                }
                const identity = identityOf(m);
                if (identity && seen[identity] !== undefined) {
                    const existingIndex = seen[identity];
                    if (messageScore(m) > messageScore(result[existingIndex])) {
                        result[existingIndex] = m;
                    }
                    continue;
                }
                if (identity) seen[identity] = result.length;
                result.push(m);
            }
            return result;
        },
        // 学生端学习报告：按课堂分组，组内按生成时间倒序
        groupedMyReports() {
            try {
            const reports = Array.isArray(this.myReports) ? this.myReports : [];
            const groups = {};

            reports.forEach((r) => {
                const key = `${r.meeting_id || 'unknown'}::${r.class_code || ''}`;
                if (!groups[key]) {
                    groups[key] = {
                        groupKey: key,
                        meeting_id: r.meeting_id,
                        class_code: r.class_code || '',
                        topic: (r.data && (r.data.meeting_topic || (r.data.basic_info && r.data.basic_info.topic))) || '',
                        reports: []
                    };
                }
                groups[key].reports.push(r);
            });

            const result = Object.values(groups);
            result.forEach((g) => {
                g.reports.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
            });
            result.sort((a, b) => {
                const aTime = a.reports[0] ? new Date(a.reports[0].created_at).getTime() : 0;
                const bTime = b.reports[0] ? new Date(b.reports[0].created_at).getTime() : 0;
                return bTime - aTime;
            });
            return result;
            } catch(e) { console.error('groupedMyReports 计算出错:', e); return []; }
        },
        filteredReports() {
            let reports = this.allStudentReports;
            if (this.reportFilter.classId) {
                reports = reports.filter(r => r.class_code === this.reportFilter.classId);
            }
            if (this.reportFilter.studentName) {
                reports = reports.filter(r => 
                    r.student_name.toLowerCase().includes(this.reportFilter.studentName.toLowerCase())
                );
            }
            return reports;
        },
        // 学生首页统计（基于历史课堂）
        studentHomeStats() {
            if (this.studentHomeSummary) {
                return {
                    activeClasses: Number(this.studentHomeSummary.activeClasses) || 0,
                    completedClasses: Number(this.studentHomeSummary.completedClasses) || 0,
                    studyHours: this.studentHomeSummary.studyHours || '0.0'
                };
            }
            const history = Array.isArray(this.classHistory) ? this.classHistory : [];
            const activeClasses = history.filter(h => h.status === 'active').length;
            const completedClasses = history.filter(h => h.status !== 'active').length;
            const totalMinutes = history.reduce((sum, h) => sum + (Number(h.duration_minutes) || 0), 0);
            const studyHours = (totalMinutes / 60).toFixed(1);
            return {
                activeClasses,
                completedClasses,
                studyHours
            };
        }
    },
    watch: {
        // 声网Agora模式下，远端视频由SDK自动管理，无需手动绑定
        // 监听本地媒体流变化，确保视频元素绑定
        localMediaStream(stream) {
            if (!stream) return;
            console.log('📹 localMediaStream watcher 触发, stream:', !!stream);
            this._bindLocalVideo();
        },
        // 监听在线成员变化，确保本地视频始终绑定
        onlineMembers(members) {
            console.log('👥 onlineMembers watcher 触发:', members);
            this.$nextTick(() => {
                setTimeout(() => this._bindLocalVideo(), 300);
                setTimeout(() => this._syncAgoraRemoteVideos(), 350);
            });
        },
        // 监听 classroomTab 变化，切换到统计页面时重新渲染图表
        classroomTab(newTab, oldTab) {
            console.log(`🔄 Tab切换: ${oldTab} -> ${newTab}`);
            
            if (newTab === 'stats') {
                console.log('📊 进入统计页面，准备渲染图表...');
                console.log('  - pieChartData:', this.pieChartData?.length || 0);
                console.log('  - individualEmotions:', Object.keys(this.individualEmotions).length);
                
                // 延迟渲染以确保DOM存在
                this.$nextTick(() => {
                    setTimeout(() => {
                        // 重新渲染所有图表
                        if (this.pieChartData && this.pieChartData.length > 0) {
                            console.log('🎨 渲染统计图表...');
                            this.renderStatsCharts();
                        } else {
                            console.warn('⚠️ 统计数据为空，跳过渲染');
                        }
                        
                        if (Object.keys(this.individualEmotions).length > 0) {
                            console.log('🎨 渲染情绪图表...');
                            this.renderGroupEmotionChart();
                            this.renderIndividualEmotionChart();
                        } else {
                            console.warn('⚠️ 情绪数据为空，跳过渲染');
                        }
                        // 强制所有已存在的图表重新计算尺寸
                        Object.values(this.chartInstances || {}).forEach(c => { if (c && !c.isDisposed()) c.resize(); });
                    }, 200); // 增加延迟到200ms
                });
            }
        }
    },
    methods: {
        // === 课堂统计标签页切换 ===
        switchToStatsTab() {
            this.classroomTab = 'stats';
            // 等待 Vue 完成 DOM 更新（v-show 生效）
            this.$nextTick(() => {
                // 再等待一小段时间确保 CSS 过渡完成，容器完全可见
                setTimeout(() => {
                    this.loadRealtimeStats();
                    this.loadEmotionDetails();
                }, 100);
            });
        },
        // === 通用弹窗方法 ===
        showAlert(message, icon = 'info', title = '') {
            return new Promise(resolve => {
                this.globalModal = { show: true, type: 'alert', icon, title, message, _resolve: resolve };
            });
        },
        shouldThrottleClassroomNotice(text, lastAt, lastText, cooldownMs) {
            const now = Date.now();
            const clean = this.normalizeSpeechText(text || '');
            const previous = this.normalizeSpeechText(lastText || '');
            if (!clean) return true;
            if (now - (Number(lastAt) || 0) < cooldownMs) return true;
            if (previous) {
                const similar = clean === previous || clean.includes(previous) || previous.includes(clean) || this.textSimilarity(clean, previous) >= 0.72;
                if (similar && now - (Number(lastAt) || 0) < 10 * 60 * 1000) return true;
            }
            return false;
        },
        showClassroomHint(text, duration = 8000, options = {}) {
            const clean = String(text || '').trim();
            if (!clean || this.isPaused) return false;
            const cooldownMs = options.cooldownMs ?? this.classroomHintCooldownMs;
            if (!options.force && this.shouldThrottleClassroomNotice(clean, this.lastClassroomHintAt, this.lastClassroomHintText, cooldownMs)) {
                console.log('⏳ 智能建议冷却中，已静默:', clean);
                return false;
            }
            this.hint = clean;
            this.lastClassroomHintAt = Date.now();
            this.lastClassroomHintText = clean;
            if (this.classroomHintTimer) clearTimeout(this.classroomHintTimer);
            this.classroomHintTimer = setTimeout(() => {
                if (this.hint === clean) this.hint = null;
                this.classroomHintTimer = null;
            }, duration);
            return true;
        },
        showTopicSuggestionNotice(text, reason = '') {
            const clean = String(text || '').trim();
            if (!clean) return false;
            if (this.shouldThrottleClassroomNotice(clean, this.lastTopicSuggestionAt, this.lastTopicSuggestionText, this.topicSuggestionCooldownMs)) {
                console.log('⏳ 话题建议冷却中，已静默:', clean);
                return false;
            }
            this.topicSuggestion = { show: true, text: clean, reason };
            this.lastTopicSuggestionAt = Date.now();
            this.lastTopicSuggestionText = clean;
            if (this.topicSuggestionTimer) clearTimeout(this.topicSuggestionTimer);
            this.topicSuggestionTimer = setTimeout(() => {
                this.topicSuggestion.show = false;
                this.topicSuggestionTimer = null;
            }, 10000);
            return true;
        },
        showConfirm(message, title = '确认操作') {
            return new Promise(resolve => {
                this.globalModal = { show: true, type: 'confirm', icon: 'warning', title, message, _resolve: resolve };
            });
        },
        resolveModal(value) {
            if (this.globalModal._resolve) this.globalModal._resolve(value);
            this.globalModal = { show: false, type: 'alert', icon: 'info', title: '', message: '', _resolve: null };
        },
        closeModal() { this.resolveModal(true); },
        // === 声纹身份绑定 ===
        getVoiceprintMimeType() {
            if (!window.MediaRecorder || !MediaRecorder.isTypeSupported) return '';
            const types = [
                'audio/webm;codecs=opus',
                'audio/webm',
                'audio/mp4',
                'audio/ogg;codecs=opus'
            ];
            return types.find(type => MediaRecorder.isTypeSupported(type)) || '';
        },
        formatVoiceprintTime(seconds) {
            const value = Number(seconds) || 0;
            const m = String(Math.floor(value / 60)).padStart(2, '0');
            const s = String(value % 60).padStart(2, '0');
            return `${m}:${s}`;
        },
        formatVoiceprintPercent(value) {
            const n = Number(value);
            if (!Number.isFinite(n)) return '-';
            return `${Math.max(0, Math.min(100, n * 100)).toFixed(1)}%`;
        },
        formatVoiceprintDistance(value) {
            const n = Number(value);
            return Number.isFinite(n) ? n.toFixed(3) : '-';
        },
        stopVoiceprintTimer() {
            if (this.voiceprintRecordingTimer) {
                clearInterval(this.voiceprintRecordingTimer);
                this.voiceprintRecordingTimer = null;
            }
        },
        stopVoiceprintStream() {
            if (this.voiceprintStream) {
                this.voiceprintStream.getTracks().forEach(track => track.stop());
                this.voiceprintStream = null;
            }
        },
        resetVoiceprintSample() {
            if (this.voiceprintAudioUrl) {
                URL.revokeObjectURL(this.voiceprintAudioUrl);
            }
            this.voiceprintAudioBlob = null;
            this.voiceprintAudioUrl = '';
            this.voiceprintChunks = [];
            this.voiceprintVerifyResult = null;
        },
        cleanupVoiceprintRecorder() {
            this.stopVoiceprintTimer();
            if (this.voiceprintRecorder && this.voiceprintRecorder.state !== 'inactive') {
                this.voiceprintRecorder._discardVoiceprint = true;
                try { this.voiceprintRecorder.stop(); } catch (e) {}
            }
            this.voiceprintRecorder = null;
            this.isRecordingVoiceprint = false;
            this.stopVoiceprintStream();
        },
        async loadVoiceprintStatus() {
            if (!this.currentUser || !this.voiceprintIdentity) return;
            this.voiceprintStatus = 'loading';
            try {
                const res = await axios.get(`/api/voiceprint/status/${encodeURIComponent(this.voiceprintIdentity)}`);
                if (res.data.status === 'success') {
                    this.voiceprintStatus = res.data.registered ? 'registered' : 'unregistered';
                } else {
                    this.voiceprintStatus = 'error';
                }
            } catch (e) {
                console.error('加载声纹状态失败:', e);
                this.voiceprintStatus = 'error';
            }
        },
        async startVoiceprintRecording(mode = 'register') {
            if (!this.currentUser || !this.voiceprintIdentity) {
                return this.showAlert('请先登录后再录制声纹', 'warning', '提示');
            }
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
                return this.showAlert('当前浏览器不支持录音，请更换浏览器后重试', 'warning', '提示');
            }

            this.cleanupVoiceprintRecorder();
            if (mode === 'register') this.resetVoiceprintSample();
            this.voiceprintRecordingMode = mode;
            this.voiceprintVerifyResult = null;
            this.voiceprintRecordingSeconds = 0;
            this.voiceprintChunks = [];

            try {
                const stream = await navigator.mediaDevices.getUserMedia({
                    audio: {
                        echoCancellation: true,
                        noiseSuppression: true,
                        autoGainControl: true
                    }
                });
                const mimeType = this.getVoiceprintMimeType();
                const options = mimeType ? { mimeType } : undefined;
                const recorder = new MediaRecorder(stream, options);

                this.voiceprintStream = stream;
                this.voiceprintRecorder = recorder;
                this.isRecordingVoiceprint = true;

                recorder.ondataavailable = (event) => {
                    if (event.data && event.data.size > 0) {
                        this.voiceprintChunks.push(event.data);
                    }
                };

                recorder.onstop = async () => {
                    if (recorder._discardVoiceprint) return;
                    const blobType = recorder.mimeType || mimeType || 'audio/webm';
                    const blob = new Blob(this.voiceprintChunks, { type: blobType });
                    this.stopVoiceprintTimer();
                    this.stopVoiceprintStream();
                    this.isRecordingVoiceprint = false;
                    if (this.voiceprintRecorder === recorder) this.voiceprintRecorder = null;

                    if (!blob.size) {
                        return this.showAlert('没有录到有效声音，请重试', 'warning', '提示');
                    }

                    if (this.voiceprintRecordingMode === 'test') {
                        await this.verifyVoiceprintBlob(blob);
                    } else {
                        if (this.voiceprintAudioUrl) URL.revokeObjectURL(this.voiceprintAudioUrl);
                        this.voiceprintAudioBlob = blob;
                        this.voiceprintAudioUrl = URL.createObjectURL(blob);
                    }
                };

                recorder.start();
                this.voiceprintRecordingTimer = setInterval(() => {
                    this.voiceprintRecordingSeconds += 1;
                }, 1000);
            } catch (e) {
                this.cleanupVoiceprintRecorder();
                this.showAlert('无法访问麦克风: ' + (e.message || e), 'error', '录音失败');
            }
        },
        stopVoiceprintRecording() {
            this.stopVoiceprintTimer();
            if (this.voiceprintRecorder && this.voiceprintRecorder.state !== 'inactive') {
                this.voiceprintRecorder.stop();
            } else {
                this.cleanupVoiceprintRecorder();
            }
        },
        async uploadVoiceprintSample() {
            if (!this.voiceprintAudioBlob) {
                return this.showAlert('请先录制一段声纹样本', 'warning', '提示');
            }
            this.voiceprintUploading = true;
            try {
                const fd = new FormData();
                fd.append('username', this.voiceprintIdentity);
                fd.append('audio', this.voiceprintAudioBlob, `voiceprint_${this.voiceprintIdentity}.webm`);
                const res = await axios.post('/api/voiceprint/register', fd);
                if (res.data.status === 'success') {
                    this.voiceprintStatus = 'registered';
                    this.resetVoiceprintSample();
                    this.showAlert('声纹已绑定到当前 ID', 'success', '绑定成功');
                } else {
                    this.showAlert(res.data.message || '声纹保存失败', 'error', '绑定失败');
                }
            } catch (e) {
                this.showAlert('声纹保存失败: ' + (e.response?.data?.message || e.message), 'error', '绑定失败');
            } finally {
                this.voiceprintUploading = false;
            }
        },
        async verifyVoiceprintBlob(blob) {
            this.voiceprintUploading = true;
            try {
                const fd = new FormData();
                fd.append('username', this.voiceprintIdentity);
                fd.append('audio', blob, `voiceprint_test_${this.voiceprintIdentity}.webm`);
                const res = await axios.post('/api/voiceprint/verify', fd);
                if (res.data.status === 'success') {
                    this.voiceprintVerifyResult = {
                        is_match: !!res.data.is_match,
                        confidence: Number(res.data.confidence) || 0,
                        distance: Number(res.data.distance) || 1
                    };
                } else {
                    this.showAlert(res.data.message || '声纹测试失败', 'error', '测试失败');
                }
            } catch (e) {
                this.showAlert('声纹测试失败: ' + (e.response?.data?.message || e.message), 'error', '测试失败');
            } finally {
                this.voiceprintUploading = false;
            }
        },
        async deleteVoiceprint() {
            if (!this.voiceprintIdentity) return;
            const ok = await this.showConfirm(`确定删除 ID ${this.voiceprintIdentity} 的声纹吗？`, '删除声纹');
            if (!ok) return;
            this.voiceprintUploading = true;
            try {
                const res = await axios.delete(`/api/voiceprint/unregister/${encodeURIComponent(this.voiceprintIdentity)}`);
                if (res.data.status === 'success') {
                    this.voiceprintStatus = 'unregistered';
                    this.resetVoiceprintSample();
                    this.showAlert('声纹已删除', 'success', '删除成功');
                } else {
                    this.showAlert(res.data.message || '删除声纹失败', 'error', '删除失败');
                }
            } catch (e) {
                this.showAlert('删除声纹失败: ' + (e.response?.data?.message || e.message), 'error', '删除失败');
            } finally {
                this.voiceprintUploading = false;
            }
        },
        // === Landing首屏交互 ===
        // 鼠标视差效果（极轻，≤ 6px位移）
        handleHeroMouseMove(e) {
            if (window.innerWidth < 768) return; // 移动端禁用
            if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return; // 无障碍降级
            
            const grid = this.$refs.bentoGrid;
            if (!grid) return;
            
            const x = (e.clientX / window.innerWidth - 0.5) * 12;  // ±6px
            const y = (e.clientY / window.innerHeight - 0.5) * 12;
            
            requestAnimationFrame(() => {
                grid.style.transform = `translate(${x}px, ${y}px) rotateX(${y * 0.2}deg) rotateY(${x * 0.2}deg)`;
            });
        },
        
        // 打开卡片预览
        openCardPreview(cardType) {
            this.cardPreview = this.cardData[cardType];
        },
        
        // ===下面是原有方法===
        // 切换到注册页
        showRegister() { this.pageState = 'register'; },
        // 切换到登录页
        showLogin() { this.pageState = 'login'; },
        // 用户登录
        async login() {
            if(!this.loginForm.student_id || !this.loginForm.password) return this.showAlert('请填写完整信息', 'warning', '提示');
            this.loading = true;
            try {
                let d = new FormData();
                d.append('student_id', this.loginForm.student_id);
                d.append('password', this.loginForm.password);
                let res = await axios.post('/api/login', d);
                if(res.data.status === 'error') { this.showAlert(res.data.message, 'error', '提示'); this.loading = false; return; }
                this.currentUser = res.data.user;
                this.studentHomeSummary = null;
                this.classHistory = [];
                this.myReports = [];
                this.allStudentReports = [];
                this.historyLoaded = false;
                this.reportsLoaded = false;
                this.studentReportsLoaded = false;
                this.pageState = 'lobby';
                this.loading = false;
                this.hydrateLobbyCache();
                // 检查声纹状态
                this.loadVoiceprintStatus();
                if (this.currentUser.role === 'student') {
                    this.loadStudentHomeStats().catch(e => console.warn('加载首页统计失败:', e));
                    this.ensureClassHistory().catch(e => console.warn('加载历史失败:', e));
                    this.ensureMyReports().catch(e => console.warn('加载报告失败:', e));
                }
                if (this.currentUser.role === 'teacher') {
                    this.loadActiveGroups();
                    this.loadTeacherStats();
                    this.loadTeacherClasses();
                    this.ensureAllStudentReports();
                    this.loadTeacherTemplates();  // 加载模板
                }
            } catch(e) { this.showAlert('登录失败: ' + (e.response?.data?.message || e.message), 'error', '错误'); this.loading = false; }
        },
        // 用户注册
        async register() {
            if(!this.registerForm.student_id || !this.registerForm.username || !this.registerForm.password) {
                return this.showAlert('请填写完整信息', 'warning', '提示');
            }
            // 密码强度校验：至少10位，包含大写、小写字母和数字
            const pwd = this.registerForm.password;
            if (pwd.length < 10) {
                return this.showAlert('密码长度不能少于10位', 'warning', '密码强度不足');
            }
            if (!/[A-Z]/.test(pwd)) {
                return this.showAlert('密码必须包含至少一个大写字母', 'warning', '密码强度不足');
            }
            if (!/[a-z]/.test(pwd)) {
                return this.showAlert('密码必须包含至少一个小写字母', 'warning', '密码强度不足');
            }
            if (!/[0-9]/.test(pwd)) {
                return this.showAlert('密码必须包含至少一个数字', 'warning', '密码强度不足');
            }
            if(this.registerForm.password !== this.registerForm.confirmPassword) {
                return this.showAlert('两次密码不一致', 'warning', '提示');
            }
            this.loading = true;
            try {
                let d = new FormData();
                d.append('student_id', this.registerForm.student_id);
                d.append('username', this.registerForm.username);
                d.append('password', this.registerForm.password);
                d.append('role', this.registerForm.role);
                let res = await axios.post('/api/register', d);
                if(res.data.status === 'error') { this.showAlert(res.data.message, 'error', '提示'); this.loading = false; return; }
                this.showAlert('注册成功，请登录', 'success', '注册成功');
                this.pageState = 'login';
                this.loading = false;
            } catch(e) { this.showAlert('注册失败: ' + (e.response?.data?.message || e.message), 'error', '错误'); this.loading = false; }
        },
        // 退出登录
        logout() {
            this.cleanupVoiceprintRecorder();
            this.resetVoiceprintSample();
            this.voiceprintStatus = 'idle';
            this.currentUser = null;
            this.studentHomeSummary = null;
            this.classHistory = [];
            this.myReports = [];
            this.allStudentReports = [];
            this.historyLoaded = false;
            this.reportsLoaded = false;
            this.studentReportsLoaded = false;
            this.pageState = 'login';
            this.activeTab = 'home';
            this.stopBrowserSpeechRecognition();
            if(this.ws) this.ws.close();
            if(this.recorder) this.recorder.stop();
        },
        // 处理文件上传
        handleFileUpload(event) {
            const file = event.target.files[0];
            if (file) {
                // 限制文件大小 10MB
                if (file.size > 10 * 1024 * 1024) {
                    this.showAlert('文件大小不能超过10MB', 'warning', '提示');
                    return;
                }
                this.uploadedFile = file;
            }
        },
        // 移除文件
        removeFile() {
            this.uploadedFile = null;
            if (this.$refs.fileInput) {
                this.$refs.fileInput.value = '';
            }
        },
        // 加载课堂历史对话（进入课堂后展示所有历史发言）
        async loadChatHistory() {
            if (!this.meetingId) return;
            try {
                const res = await axios.get(`/api/transcripts/${this.meetingId}?limit=2000`);
                if (res.data.status !== 'success') return;
                const list = res.data.transcripts || [];

                const historyMsgs = list.map(t => ({
                    type: 'new_speech_fast',
                    username: t.username,
                    text: t.text,
                    timestamp: t.timestamp || Date.now(),
                    quality_score: t.quality_score,
                    quality_feedback: t.quality_feedback,
                    tags: { emotion: t.emotion, action: t.action },
                    from_history: true
                }));

                const existingKeys = new Set(
                    (this.msgs || []).map(m => `${m.username}::${m.timestamp}::${this.normalizeSpeechText(m.text)}`)
                );
                historyMsgs.forEach(m => {
                    const k = `${m.username}::${m.timestamp}::${this.normalizeSpeechText(m.text)}`;
                    if (!existingKeys.has(k)) {
                        this.msgs.push(m);
                        existingKeys.add(k);
                    }
                });

                this.$nextTick(() => {
                    if (this.$refs.chat) this.$refs.chat.scrollTop = 99999;
                });
            } catch (e) {
                console.error('加载课堂历史对话失败:', e);
            }
        },
        // 进入/创建课堂
        async enterClass() {
            if(!this.classForm.class_code) return this.showAlert('请输入课堂号', 'warning', '提示');
            if(this.currentUser.role === 'teacher' && !this.classForm.topic) return this.showAlert('教师创建课堂需要填写主题', 'warning', '提示');
            this.loading = true;
            let d = new FormData();
            d.append('username', this.currentUser.username);
            d.append('student_id', this.currentUser.student_id);
            d.append('class_code', this.classForm.class_code);
            d.append('role', this.currentUser.role);
            // 调试：打印topic值
            console.log('📤 提交的topic:', this.classForm.topic);
            if(this.classForm.topic) d.append('topic', this.classForm.topic);
            
            // 添加参考资料
            if(this.currentUser.role === 'teacher') {
                // 如果上传了文件
                if(this.uploadedFile) {
                    d.append('material_file', this.uploadedFile);
                }
                // 如果填写了网址
                if(this.classForm.materialUrl) {
                    d.append('material_url', this.classForm.materialUrl);
                }
                // 如果选择了模板
                if(this.classForm.templateId) {
                    d.append('template_path', this.classForm.templateId);
                }
            }
            
            try {
                let res = await axios.post('/login', d);
                if(res.data.status === 'error') { this.showAlert(res.data.message, 'error', '提示'); this.loading = false; return; }
                this.meetingId = res.data.meeting_id; 
                this.goals = res.data.goals; 
                this.currentTopic = this.displayTopicText(res.data.topic || this.classForm.topic, this.classForm.class_code);
                this.joined = true; 
                this.pageState = 'classroom';
                this.showClassModal = false;
                this.classStartTime = Date.now();
                this.startTimer();
                this.startSilenceChecks();
                this.loading = false;
                // 清空表单
                this.classForm = { class_code: '', topic: '', materialUrl: '', templateId: '' };
                this.uploadedFile = null;
                this.$nextTick(async () => {
                    // 优先实时弹幕/ASR：先建立实时连接
                    // 对话栏仅显示本次进入课堂后的会话消息，不再加载往期课堂历史
                    await this.startSmartMedia();
                    this.connectWs();
                    this.connectAsrWs();
                    this._joinAgoraChannel();
                    // 启动情绪数据定时刷新（所有tab都刷新，保证数据实时）
                    if (this.emotionRefreshTimer) clearInterval(this.emotionRefreshTimer);
                    this.emotionRefreshTimer = setInterval(() => {
                        this.loadEmotionDetails();
                    }, 30000);
                });
            } catch(e) { this.showAlert('进入课堂失败', 'error', '错误'); this.loading = false; }
        },
        // 可靠绑定本地视频流（使用 getElementById 避免 Vue ref 在 v-for 内的数组问题）
        _bindLocalVideo() {
            if (!this.localMediaStream) return;
            const tryBind = (attempt) => {
                const videoEl = document.getElementById('localVideo');
                if (videoEl) {
                    if (videoEl.srcObject !== this.localMediaStream) {
                        videoEl.srcObject = this.localMediaStream;
                        console.log('✅ 本地视频已绑定 (attempt ' + attempt + ')');
                    }
                } else if (attempt < 20) {
                    setTimeout(() => tryBind(attempt + 1), 300);
                } else {
                    console.warn('⚠️ 本地视频元素未找到，已重试20次');
                }
            };
            this.$nextTick(() => tryBind(1));
        },
        async startSmartMedia() {
            // 防止重复调用
            if (this._startingMedia) {
                console.warn('⚠️ startSmartMedia 已在执行中，跳过');
                return;
            }
            this._startingMedia = true;
            try {
            // 教师:选择摄像头或屏幕共享
            let stream;
            if (this.currentUser.role === 'teacher') {
                const choice = await this.showConfirm('点击”确定”共享屏幕，”取消”使用摄像头', '选择媒体方式');
                if (choice) {
                    // 屏幕共享
                    try {
                        stream = await navigator.mediaDevices.getDisplayMedia({video: true, audio: true});
                        this.statusText = 'Screen Sharing...';
                    } catch(e) {
                        console.warn('屏幕共享取消或失败，使用摄像头:', e);
                        stream = await navigator.mediaDevices.getUserMedia({video:true, audio:true});
                    }
                } else {
                    stream = await navigator.mediaDevices.getUserMedia({video:true, audio:true});
                }
            } else {
                stream = await navigator.mediaDevices.getUserMedia({video:true, audio:true});
            }
            
            this.localMediaStream = stream;
            // 使用 getElementById 绑定（更可靠）
            this._bindLocalVideo();
            // 启动本地麦克风活跃检测
            this.startLocalAudioAnalysis();
            // 降低视频帧率录制，减少CPU开销（5fps足够做表情识别）
            const lowFpsStream = new MediaStream([
                ...stream.getAudioTracks(),
                ...stream.getVideoTracks()
            ]);
            this.recorder = new MediaRecorder(lowFpsStream, {
                mimeType: 'video/webm',
                videoBitsPerSecond: 500000
            });
            this.recorder.ondataavailable = e => {
                console.log('🎤 ondataavailable 触发:', {
                    size: e.data.size,
                    isPaused: this.isPaused,
                    wsExists: !!this.ws,
                    wsState: this.ws?.readyState
                });

                if(this.isPaused) {
                    console.warn('⏸️ 当前已暂停，忽略录音片段');
                    return;
                }
                if(e.data.size > 0 && this.ws && this.ws.readyState==1) {
                    this.ws.send(e.data);
                    console.log("📤 发送切片:", e.data.size);
                } else {
                    console.warn('⚠️ 音频数据未发送:', {
                        isPaused: this.isPaused,
                        dataSize: e.data.size,
                        wsExists: !!this.ws,
                        wsState: this.ws?.readyState
                    });
                }
            };
            this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            let source = this.audioCtx.createMediaStreamSource(stream); this.analyser = this.audioCtx.createAnalyser(); this.analyser.fftSize = 512; source.connect(this.analyser); this.dataArray = new Uint8Array(this.analyser.frequencyBinCount);

            // --- 新增: 实时 PCM 采集 (AudioWorklet, 独立线程不卡UI) ---
            this.audioSource = source;
            try {
                await this.audioCtx.audioWorklet.addModule('/pcm-processor.js');
                this.audioProcessor = new AudioWorkletNode(this.audioCtx, 'pcm-processor', {
                    processorOptions: { sampleRate: this.audioCtx.sampleRate }
                });
                this.audioSource.connect(this.audioProcessor);
                this.audioProcessor.connect(this.audioCtx.destination);

                this.audioProcessor.port.onmessage = (e) => {
                    if (this.isPaused) return;
                    if (this.asrWs && this.asrWs.readyState === WebSocket.OPEN) {
                        const MAX_BUFFERED_BYTES = 256 * 1024;
                        if ((this.asrWs.bufferedAmount || 0) > MAX_BUFFERED_BYTES) {
                            this.asrDroppedFrames = (this.asrDroppedFrames || 0) + 1;
                            if (this.asrDroppedFrames % 100 === 1) {
                                console.warn(`⚠️ ASR发送拥塞，已丢弃 ${this.asrDroppedFrames} 帧旧音频`);
                            }
                            return;
                        }
                        this.asrWs.send(e.data);
                    }
                };
                console.log('✅ AudioWorklet PCM采集已启动（独立线程）');
            } catch (workletErr) {
                console.warn('⚠️ AudioWorklet不支持，回退到ScriptProcessor:', workletErr);
                // 回退方案：老浏览器用ScriptProcessor
                const bufferSize = 16384;
                this.audioProcessor = this.audioCtx.createScriptProcessor(bufferSize, 1, 1);
                this.audioSource.connect(this.audioProcessor);
                this.audioProcessor.connect(this.audioCtx.destination);
                this.audioProcessor.onaudioprocess = (e) => {
                    if (this.isPaused) return;
                    const inputData = e.inputBuffer.getChannelData(0);
                    const sampleRate = this.audioCtx.sampleRate;
                    const targetRate = 16000;
                    const ratio = sampleRate / targetRate;
                    const targetLength = Math.round(inputData.length / ratio);
                    const result = new Int16Array(targetLength);
                    for (let i = 0; i < targetLength; i++) {
                        const idx = Math.floor(i * ratio);
                        if (idx >= inputData.length) break;
                        let s = Math.max(-1, Math.min(1, inputData[idx]));
                        result[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                    }
                    if (this.asrWs && this.asrWs.readyState === WebSocket.OPEN) {
                        const MAX_BUFFERED_BYTES = 256 * 1024;
                        if ((this.asrWs.bufferedAmount || 0) > MAX_BUFFERED_BYTES) {
                            this.asrDroppedFrames = (this.asrDroppedFrames || 0) + 1;
                            if (this.asrDroppedFrames % 100 === 1) {
                                console.warn(`⚠️ ASR发送拥塞，已丢弃 ${this.asrDroppedFrames} 帧旧音频`);
                            }
                            return;
                        }
                        this.asrWs.send(result.buffer);
                    }
                };
            }
            // --- 结束新增 ---

            this.recorder.start(); this.recordingStartTime = Date.now(); this.detectVolume();
            } finally {
                this._startingMedia = false;
            }
        },
        detectVolume() {
            if(this.isPaused) { setTimeout(() => this.detectVolume(), 100); return; }
            this.analyser.getByteFrequencyData(this.dataArray);
            let sum = 0; for(let i=0; i<this.dataArray.length; i++) sum += this.dataArray[i];
            let average = sum / this.dataArray.length; this.volumeLevel = Math.min(average * 2, 100);
            const THRESHOLD = 30;           // 音量阈值
            const MAX_DURATION = 15000;       // 最大录音时长15秒
            const SILENCE_DURATION = 1500;    // 静默检测1.5秒（触发批量切片）
            const MIN_SPEAKING_DURATION = 800; // 最小说话时长0.8秒
            const ASR_PAUSE_DURATION = 5000;  // ASR断句：停顿5秒视为一句话结束

            if (average > THRESHOLD) {
                if (!this.isSpeaking) {
                    this.speakingStartTime = Date.now();
                    this.isSpeaking = true;
                }
                this.silenceStart = null;
                this._asrPauseHandled = false; // 重置断句标记
                this.statusText = 'Speaking...';
            }
            else {
                if (this.silenceStart === null && this.isSpeaking) {
                    this.silenceStart = Date.now();
                }

                // ASR智能断句：检测到停顿1.2秒，把当前流式文本定稿为一句话
                if (this.isSpeaking && this.silenceStart && !this._asrPauseHandled &&
                    (Date.now() - this.silenceStart > ASR_PAUSE_DURATION)) {
                    this._asrPauseHandled = true;
                    this._finalizeCurrentAsrTyping();
                }

                if (this.isSpeaking && this.silenceStart && (Date.now() - this.silenceStart > SILENCE_DURATION)) {
                    if (this.speakingStartTime && (Date.now() - this.speakingStartTime > MIN_SPEAKING_DURATION)) {
                        this.triggerSlice();
                    } else {
                        this.isSpeaking = false;
                        this.silenceStart = null;
                    }
                }

                if (!this.isSpeaking && (Date.now() - this.recordingStartTime > MAX_DURATION)) {
                    this.triggerSlice();
                }
            }
            setTimeout(() => this.detectVolume(), 100);
        },
        triggerSlice() {
            if (this.recorder.state === 'recording') {
                this.recorder.stop(); this.recorder.start(); this.recordingStartTime = Date.now(); this.isSpeaking = false; this.silenceStart = null; this.speakingStartTime = null; this.statusText = 'Sent'; setTimeout(() => this.statusText = 'Listening...', 500);
            }
        },
        togglePause() {
            this.isPaused = !this.isPaused;
            if (this.recorder) {
                try {
                    if (this.isPaused && this.recorder.state === 'recording') {
                        this.recorder.pause();
                    } else if (!this.isPaused && this.recorder.state === 'paused') {
                        this.recorder.resume();
                    }
                } catch (e) {}
            }
            if (this.isPaused) {
                this.isSpeaking = false;
                this.silenceStart = null;
                this.speakingStartTime = null;
                this.stopBrowserSpeechRecognition();
            }
        },
        // endClass 已移至下方统一版本
        _cleanupClassroom() {
            // 停止录制和媒体
            if (this.recorder && this.recorder.state !== 'inactive') this.recorder.stop();
            if (this.localMediaStream) {
                this.localMediaStream.getTracks().forEach(t => t.stop());
                this.localMediaStream = null;
            }
            // 停止 Agora 本地轨道（关闭摄像头/麦克风）
            if (this.agoraLocalVideoTrack) {
                this.agoraLocalVideoTrack.stop();
                this.agoraLocalVideoTrack.close();
                this.agoraLocalVideoTrack = null;
            }
            if (this.agoraLocalAudioTrack) {
                this.agoraLocalAudioTrack.stop();
                this.agoraLocalAudioTrack.close();
                this.agoraLocalAudioTrack = null;
            }
            if (this.ws) { this.ws.close(); this.ws = null; }
            if (this.asrWs) { this.asrWs._manualClose = true; this.asrWs.close(); this.asrWs = null; }
            this.stopBrowserSpeechRecognition();
            this._leaveAgoraChannel();
            if (this.timerInterval) clearInterval(this.timerInterval);
            if (this.graphUpdateInterval) clearInterval(this.graphUpdateInterval);
            if (this.analyzingCleanupInterval) clearInterval(this.analyzingCleanupInterval);
            if (this.classroomHintTimer) { clearTimeout(this.classroomHintTimer); this.classroomHintTimer = null; }
            if (this.topicSuggestionTimer) { clearTimeout(this.topicSuggestionTimer); this.topicSuggestionTimer = null; }
            if (this.classroomHintTimer) { clearTimeout(this.classroomHintTimer); this.classroomHintTimer = null; }
            if (this.topicSuggestionTimer) { clearTimeout(this.topicSuggestionTimer); this.topicSuggestionTimer = null; }
            if (this.audioCtx) { this.audioCtx.close().catch(() => {}); this.audioCtx = null; }
            // 清理本地视频元素
            const localVideo = document.getElementById('localVideo');
            if (localVideo) localVideo.srcObject = null;
            // 返回主页
            this.currentView = 'main';
            this.meetingId = null;
            this.msgs = [];
            this.onlineMembers = [];
            this.hint = null;
            this.topicSuggestion.show = false;
        },
        startTimer() {
            this.timerInterval = setInterval(() => {
                if (!this.isPaused) {
                    const elapsed = Math.floor((Date.now() - this.classStartTime) / 1000);
                    const minutes = Math.floor(elapsed / 60);
                    const seconds = elapsed % 60;
                    const timerElement = document.getElementById('timer');
                    if (timerElement) {
                        timerElement.textContent =
                            String(minutes).padStart(2, '0') + ':' + String(seconds).padStart(2, '0');
                    }
                }
            }, 1000);

            // 每5分钟更新一次知识图谱
            this.graphUpdateInterval = setInterval(() => {
                if (this.joined && this.meetingId) {
                    console.log('🔄 定时更新知识图谱...');
                    this.loadKnowledgeGraph();
                }
            }, 5 * 60 * 1000); // 5分钟

            // 每10秒清理卡住的"分析中"消息
            this.analyzingCleanupInterval = setInterval(() => {
                const now = Date.now();
                let cleaned = 0;
                this.msgs.forEach(m => {
                    if (m.analyzing && m.timestamp) {
                        const age = now - m.timestamp;
                        // 如果消息超过30秒还在分析中，强制标记为完成
                        if (age > 30000) {
                            m.analyzing = false;
                            if (!m.quality_feedback || m.quality_feedback.includes('正在') || m.quality_feedback.includes('评估中')) {
                                m.quality_feedback = '已评估';
                            }
                            cleaned++;
                        }
                    }
                });
                if (cleaned > 0) {
                    console.log(`🧹 清理了 ${cleaned} 条卡住的分析消息`);
                    this.$forceUpdate();
                }
            }, 10000); // 10秒
        },
        async sendBrowserAsrFinal(text) {
            const clean = String(text || '').trim();
            if (!clean || !this.meetingId || !this.currentUser) return;
            try {
                const formData = new FormData();
                formData.append('meeting_id', this.meetingId);
                formData.append('username', this.currentUser.student_id);
                formData.append('text', clean);
                await axios.post('/api/browser-asr-final', formData);
            } catch (e) {
                console.error('浏览器ASR回写失败:', e);
            }
        },
        startBrowserSpeechRecognition() {
            console.warn('Browser ASR fallback disabled; using Aliyun realtime ASR only.');
            return;
            const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!SR || !this.joined || this.pageState !== 'classroom' || !this.currentUser) return;

            if (!this.browserRecognition) {
                const recognition = new SR();
                recognition.lang = 'zh-CN';
                recognition.continuous = true;
                recognition.interimResults = true;

                recognition.onresult = (event) => {
                    let interimText = '';
                    const finalTexts = [];

                    for (let i = event.resultIndex; i < event.results.length; i++) {
                        const result = event.results[i];
                        const transcript = String(result?.[0]?.transcript || '').trim();
                        if (!transcript) continue;
                        if (result.isFinal) finalTexts.push(transcript);
                        else interimText += transcript;
                    }

                    if (interimText) {
                        this.updateRealtimeSubtitle(this.currentUser.student_id, interimText, false);
                    }

                    finalTexts.forEach((finalText) => {
                        const normalized = this.normalizeSpeechText(finalText);
                        const now = Date.now();
                        if (normalized && this.browserAsrLastFinal === normalized && (now - this.browserAsrLastFinalAt < 4000)) {
                            return;
                        }
                        this.browserAsrLastFinal = normalized;
                        this.browserAsrLastFinalAt = now;
                        this.updateRealtimeSubtitle(this.currentUser.student_id, finalText, true);
                        this.appendAsrFinalToChat(this.currentUser.student_id, finalText, null);
                        this.sendBrowserAsrFinal(finalText);
                    });
                };

                recognition.onerror = (event) => {
                    console.warn('浏览器ASR错误:', event);
                };

                recognition.onend = () => {
                    if (this.browserAsrRestartTimer) {
                        clearTimeout(this.browserAsrRestartTimer);
                        this.browserAsrRestartTimer = null;
                    }
                    if (this.browserAsrActive && this.joined && this.pageState === 'classroom' && !this.isPaused) {
                        this.browserAsrRestartTimer = setTimeout(() => {
                            this.startBrowserSpeechRecognition();
                        }, 800);
                    }
                };

                this.browserRecognition = recognition;
            }

            this.browserAsrActive = true;
            try {
                this.browserRecognition.start();
                console.log('✅ 浏览器ASR兜底已启动');
            } catch (e) {
                const msg = String(e && e.message || e || '');
                if (!/already started/i.test(msg)) {
                    console.warn('启动浏览器ASR失败:', e);
                }
            }
        },
        stopBrowserSpeechRecognition() {
            this.browserAsrActive = false;
            if (this.browserAsrRestartTimer) {
                clearTimeout(this.browserAsrRestartTimer);
                this.browserAsrRestartTimer = null;
            }
            if (this.browserRecognition) {
                try { this.browserRecognition.stop(); } catch (e) {}
            }
        },
        connectAsrWs() {
            let protocol = location.protocol === 'https:' ? 'wss' : 'ws';
            if (this.asrWs) {
                this.asrWs._manualClose = true;
                try { this.asrWs.close(); } catch (e) {}
                this.asrWs = null;
            }
            const seq = (this.asrWsSeq || 0) + 1;
            this.asrWsSeq = seq;
            const ws = new WebSocket(`${protocol}://${location.host}/ws-asr/${this.currentUser.username}/${this.meetingId}`);
            this.asrWs = ws;

            ws.onopen = () => {
                if (this.asrWs !== ws || this.asrWsSeq !== seq) return;
                console.log('✅ 实时ASR WebSocket已连接');
                this._asrErrorShown = false;
                this.asrLastMessageAt = 0;
                if (this.asrHealthTimer) clearTimeout(this.asrHealthTimer);
                this.asrHealthTimer = setTimeout(() => {
                    if (!this.asrLastMessageAt && this.joined && this.pageState === 'classroom') {
                        console.warn('⚠️ 实时ASR暂未返回文本，可能正在等待阿里云返回或当前没有有效语音');
                    }
                }, 6000);
                if (this.asrReconnectTimer) clearTimeout(this.asrReconnectTimer);
                this.asrReconnectTimer = null;
            };

            ws.onmessage = e => {
                if (this.asrWs !== ws || this.asrWsSeq !== seq) return;
                let d = JSON.parse(e.data);
                if (d.type === 'asr_partial') {
                    this.asrLastMessageAt = Date.now();
                    this.stopBrowserSpeechRecognition();
                    this.updateRealtimeSubtitle(d.username, d.text, false);
                    this.upsertAsrPartialToChat(d.username, d.text, d.asr_sentence_id);
                    return;
                } else if (d.type === 'asr_final') {
                    this.asrLastMessageAt = Date.now();
                    this.stopBrowserSpeechRecognition();
                    this.updateRealtimeSubtitle(d.username, d.text, true);
                    this.appendAsrFinalToChat(d.username, d.text, d.asr_sentence_id);
                    this.scheduleRealtimeDataRefresh(800);
                    setTimeout(() => this.scheduleRealtimeDataRefresh(500), 3500);
                } else if (d.type === 'asr_rejected') {
                    this.removeRejectedAsrFromChat(d.username, d.asr_sentence_id);
                    console.warn('⚠️ 当前ASR临时片段已被后端丢弃或去重:', d);
                } else if (d.type === 'asr_error') {
                    console.error('❌ 实时ASR不可用:', d.message || d);
                    this.asrLastMessageAt = 0;
                    if (!this._asrErrorShown) {
                        this._asrErrorShown = true;
                        this.showAlert(d.message || '实时语音转文字暂时不可用', 'warning', 'ASR连接异常');
                    }
                } else if (d.type === 'asr_status') {
                    console.log('ℹ️ 实时ASR状态:', d.message || d);
                } else if (d.type === 'asr_gate_status') {
                    if (d.status === 'passed') {
                        console.log('ℹ️ 收到旧版ASR门控状态:', d);
                    } else if (d.holding) {
                        console.log('ℹ️ 收到旧版ASR门控边界状态:', d);
                    } else {
                        console.warn('⚠️ 收到旧版ASR门控拒绝状态，当前前端不再按声纹门控处理:', d);
                    }
                }
            };

            ws.onerror = e => {
                if (this.asrWs !== ws || this.asrWsSeq !== seq) return;
                console.error('❌ ASR WebSocket错误:', e);
            };
            ws.onclose = e => {
                if (ws._manualClose || this.asrWs !== ws || this.asrWsSeq !== seq) return;
                console.log('⚠️ ASR WebSocket断开', e.code);
                if (this.asrHealthTimer) {
                    clearTimeout(this.asrHealthTimer);
                    this.asrHealthTimer = null;
                }
                if (this.asrReconnectTimer) {
                    clearTimeout(this.asrReconnectTimer);
                    this.asrReconnectTimer = null;
                }
                if (this.joined && this.pageState === 'classroom') {
                    console.warn('⚠️ ASR WebSocket 已断开，等待重连');
                }
                if (this.joined && this.pageState === 'classroom') {
                    this.asrReconnectTimer = setTimeout(() => {
                        if (this.joined && this.pageState === 'classroom' && this.asrWs === ws && this.asrWsSeq === seq) {
                            this.asrWs = null;
                            this.connectAsrWs();
                        }
                    }, 3000);
                }
            };
        },
        // ===== 声网 Agora SDK 方法 =====
        async _initAgora() {
            if (this.agoraClient) return;
            this.agoraClient = AgoraRTC.createClient({ mode: 'rtc', codec: 'vp8' });
            // 音量指示器（替代手动 AudioContext 分析）
            this.agoraClient.enableAudioVolumeIndicator();
            this.agoraClient.on('volume-indicator', (volumes) => {
                volumes.forEach(v => {
                    const uid = String(v.uid);
                    this.$set(this.speakingMembers, uid, v.level > 5);
                });
            });
            // 远端用户发布音视频
            this.agoraClient.on('user-published', async (user, mediaType) => {
                await this.agoraClient.subscribe(user, mediaType);
                const uid = String(user.uid);
                console.log(`📥 Agora: 订阅远端 ${uid} 的 ${mediaType}`);
                if (mediaType === 'video') {
                    this.$set(this.remoteStreams, uid, false);
                    this.$set(this.agoraRemoteUsers, uid, {
                        ...(this.agoraRemoteUsers[uid] || {}),
                        videoTrack: user.videoTrack
                    });
                    this._playAgoraRemoteVideo(uid, user.videoTrack);
                }
                if (mediaType === 'audio') {
                    this.$set(this.agoraRemoteUsers, uid, {
                        ...(this.agoraRemoteUsers[uid] || {}),
                        audioTrack: user.audioTrack
                    });
                    user.audioTrack.play();
                }
            });
            // 远端用户取消发布
            this.agoraClient.on('user-unpublished', (user, mediaType) => {
                const uid = String(user.uid);
                console.log(`📤 Agora: 远端 ${uid} 取消发布 ${mediaType}`);
                if (mediaType === 'video') {
                    this.$set(this.remoteStreams, uid, false);
                    if (this.agoraRemoteUsers[uid]) {
                        this.agoraRemoteUsers[uid].videoTrack = null;
                    }
                    // 清空容器
                    const container = document.getElementById('agora-remote-' + uid);
                    if (container) container.innerHTML = '';
                }
                if (mediaType === 'audio') {
                    if (this.agoraRemoteUsers[uid]) {
                        this.agoraRemoteUsers[uid].audioTrack = null;
                    }
                }
            });
            // 远端用户离开
            this.agoraClient.on('user-left', (user) => {
                const uid = String(user.uid);
                console.log(`👋 Agora: 远端用户离开 ${uid}`);
                this.$delete(this.remoteStreams, uid);
                this.$delete(this.agoraRemoteUsers, uid);
                this.$delete(this.speakingMembers, uid);
                const container = document.getElementById('agora-remote-' + uid);
                if (container) container.innerHTML = '';
            });
            console.log('✅ Agora Client 初始化完成');
        },
        async _joinAgoraChannel() {
            if (!this.meetingId || !this.currentUser || !this.localMediaStream) return;
            try {
                const channel = String(this.meetingId);
                const uid = String(this.currentUser.student_id);
                // 从服务端获取 RTC 配置，避免前后端鉴权模式不一致
                const tokenRes = await axios.get('/api/agora-token', {
                    params: { channel, uid, _: Date.now() },
                    headers: { 'Cache-Control': 'no-cache' }
                });
                const rtcConfig = tokenRes.data || {};
                const appId = rtcConfig.appId || this.agoraAppId;
                const useToken = !!rtcConfig.useToken;
                const authMode = rtcConfig.authMode || (useToken ? 'token' : 'appid');
                const token = rtcConfig.token || null;
                const configError = rtcConfig.error ? String(rtcConfig.error) : '';

                if (!appId) {
                    throw new Error('Agora App ID 未配置');
                }
                this.agoraAppId = appId;

                if (useToken) {
                    if (!token) {
                        throw new Error(configError || 'Agora Token 生成失败，请检查服务端配置');
                    }
                    console.log(`🔑 Agora Token 获取成功，使用 ${authMode} 模式加入频道`);
                } else {
                    console.log(`ℹ️ Agora 使用 ${authMode} 模式免 token 加入频道`);
                }

                await this._initAgora();

                const joinChannel = async (joinToken) => {
                    await this.agoraClient.join(appId, channel, joinToken, uid);
                };

                // 加入频道
                try {
                    await joinChannel(useToken ? token : null);
                } catch (joinErr) {
                    const msg = String((joinErr && joinErr.message) || joinErr || '');
                    const isAuthModeMismatch = (
                        msg.includes('dynamic use static key') ||
                        msg.includes('CAN_NOT_GET_GATEWAY_SERVER')
                    );
                    const shouldRetryWithoutToken = useToken && (
                        isAuthModeMismatch
                    );
                    if (shouldRetryWithoutToken) {
                        console.warn('⚠️ Agora 动态 Token 与当前项目模式不匹配，重建客户端后改用 null token 重试');
                        if (this.agoraClient) {
                            await this.agoraClient.leave().catch(() => {});
                            this.agoraClient = null;
                        }
                        await this._initAgora();
                        await joinChannel(null);
                    } else if (!useToken && isAuthModeMismatch) {
                        throw new Error('当前声网项目要求使用 Token 鉴权。请在项目 .env 中配置 AGORA_APP_ID、AGORA_AUTH_MODE=token、AGORA_APP_CERTIFICATE 后重启服务。');
                    } else {
                        throw joinErr;
                    }
                }
                console.log(`✅ Agora: 已加入频道 ${channel}, UID=${uid}`);
                // 从本地 MediaStream 创建自定义轨道
                const videoTrack = this.localMediaStream.getVideoTracks()[0];
                const audioTrack = this.localMediaStream.getAudioTracks()[0];
                if (videoTrack) {
                    this.agoraLocalVideoTrack = AgoraRTC.createCustomVideoTrack({
                        mediaStreamTrack: videoTrack
                    });
                }
                if (audioTrack) {
                    this.agoraLocalAudioTrack = AgoraRTC.createCustomAudioTrack({
                        mediaStreamTrack: audioTrack
                    });
                }
                // 发布本地轨道
                const tracksToPublish = [];
                if (this.agoraLocalVideoTrack) tracksToPublish.push(this.agoraLocalVideoTrack);
                if (this.agoraLocalAudioTrack) tracksToPublish.push(this.agoraLocalAudioTrack);
                if (tracksToPublish.length > 0) {
                    await this.agoraClient.publish(tracksToPublish);
                    console.log('✅ Agora: 本地音视频已发布');
                }
            } catch (e) {
                console.error('❌ Agora 加入频道失败:', e);
                this.showAlert('视频连接失败: ' + (e.message || e), 'error', '声网错误');
            }
        },
        async _leaveAgoraChannel() {
            try {
                // 关闭本地 Agora 轨道（注意：不要 close，因为底层 MediaStreamTrack 还在被 MediaRecorder/ASR 使用）
                if (this.agoraLocalVideoTrack) {
                    this.agoraClient && await this.agoraClient.unpublish(this.agoraLocalVideoTrack).catch(() => {});
                    this.agoraLocalVideoTrack = null;
                }
                if (this.agoraLocalAudioTrack) {
                    this.agoraClient && await this.agoraClient.unpublish(this.agoraLocalAudioTrack).catch(() => {});
                    this.agoraLocalAudioTrack = null;
                }
                // 清理远端
                Object.keys(this.agoraRemoteUsers).forEach(uid => {
                    const container = document.getElementById('agora-remote-' + uid);
                    if (container) container.innerHTML = '';
                });
                this.agoraRemoteUsers = {};
                this.remoteStreams = {};
                this.speakingMembers = {};
                this.pinnedMember = null;
                // 离开频道
                if (this.agoraClient) {
                    await this.agoraClient.leave().catch(() => {});
                    this.agoraClient = null;
                    console.log('✅ Agora: 已离开频道');
                }
            } catch (e) {
                console.warn('Agora 离开频道异常:', e);
            }
        },
        // 保留本地音频活跃检测（自己的麦克风，用于本地 speaking 状态）
        startLocalAudioAnalysis() {
            if (!this.localMediaStream) return;
            try {
                const ctx = new (window.AudioContext || window.webkitAudioContext)();
                const source = ctx.createMediaStreamSource(this.localMediaStream);
                const analyser = ctx.createAnalyser();
                analyser.fftSize = 512;
                analyser.smoothingTimeConstant = 0.3;
                source.connect(analyser);
                const dataArray = new Uint8Array(analyser.frequencyBinCount);
                const me = this.currentUser.student_id;
                this._localAudioAnalysis = setInterval(() => {
                    analyser.getByteFrequencyData(dataArray);
                    let sum = 0;
                    for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
                    const avg = sum / dataArray.length;
                    this.$set(this.speakingMembers, me, avg > 12);
                }, 200);
                this._localAudioCtx = ctx;
            } catch (e) {}
        },
        cleanupWebRtcAll() {
            // Agora 清理
            this._leaveAgoraChannel();
            // 清理本地音频分析
            if (this._localAudioAnalysis) { clearInterval(this._localAudioAnalysis); this._localAudioAnalysis = null; }
            if (this._localAudioCtx) { try { this._localAudioCtx.close(); } catch (e) {} this._localAudioCtx = null; }
        },
        _playAgoraRemoteVideo(uid, track, attempt = 0) {
            if (!uid || !track) return;

            const currentTrack = this.agoraRemoteUsers[uid] && this.agoraRemoteUsers[uid].videoTrack;
            if (currentTrack !== track) return;

            const container = document.getElementById('agora-remote-' + uid);
            if (container) {
                try {
                    track.play(container, { fit: 'cover' });
                    this.$set(this.remoteStreams, uid, true);
                    return;
                } catch (err) {
                    console.warn(`⚠️ Agora: 播放远端 ${uid} 视频失败，准备重试`, err);
                }
            }

            if (attempt >= 15) {
                console.warn(`⚠️ Agora: 远端 ${uid} 视频容器未就绪，停止重试`);
                this.$set(this.remoteStreams, uid, false);
                return;
            }

            this.$set(this.remoteStreams, uid, false);
            setTimeout(() => {
                this.$nextTick(() => this._playAgoraRemoteVideo(uid, track, attempt + 1));
            }, 250);
        },
        _syncAgoraRemoteVideos() {
            this.$nextTick(() => {
                Object.keys(this.agoraRemoteUsers || {}).forEach(uid => {
                    const remoteUser = this.agoraRemoteUsers[uid];
                    if (remoteUser && remoteUser.videoTrack) {
                        this._playAgoraRemoteVideo(uid, remoteUser.videoTrack);
                    }
                });
            });
        },
        _trimMsgs() {
            const MAX = 150;
            if (this.msgs.length > MAX) {
                this.msgs.splice(0, this.msgs.length - MAX);
            }
        },
        messageRenderKey(m, i) {
            const base = (m && (m.transcript_id || m.asr_sentence_id || m.client_msg_id || m.timestamp)) || 'msg';
            return `${base}-${i}`;
        },
        // 流式ASR：partial结果实时更新到对话栏
        _updateAsrPartialInChat(username, text) {
            if (!text || !text.trim()) return;
            const now = Date.now();
            // 找到当前正在输入的占位消息
            for (let i = this.msgs.length - 1; i >= 0; i--) {
                const m = this.msgs[i];
                if (m && m._asr_typing && m.username === username && (now - m.timestamp < 15000)) {
                    m.text = text;
                    this.$forceUpdate();
                    this.$nextTick(() => {
                        if (this.$refs.chat) this.$refs.chat.scrollTop = 99999;
                    });
                    return;
                }
            }
            // 没有找到，创建新的占位消息
            this.msgs.push({
                type: 'new_speech_fast',
                username,
                text: text,
                timestamp: now,
                quality_score: null,
                quality_feedback: '<i class="fas fa-microphone" style="color: var(--primary); animation: blink 1s infinite;"></i> 识别中...',
                tags: { emotion: '', action: '' },
                asr_only: true,
                _asr_typing: true
            });
            this._trimMsgs();
            this.$nextTick(() => {
                if (this.$refs.chat) this.$refs.chat.scrollTop = 99999;
            });
        },
        // 流式ASR：final结果 — 追加到当前消息，不切断
        _finalizeAsrInChat(username, text) {
            if (!text || !text.trim()) return;
            const now = Date.now();
            // 找到正在输入的占位消息
            for (let i = this.msgs.length - 1; i >= 0; i--) {
                const m = this.msgs[i];
                if (m && m._asr_typing && m.username === username && (now - m.timestamp < 30000)) {
                    // 追加文本而不是替换，用句号/逗号连接
                    const oldText = (m.text || '').trim();
                    const newText = text.trim();
                    if (oldText && oldText !== newText) {
                        // 如果旧文本已经包含新文本的开头（partial更新过），直接替换
                        if (newText.startsWith(oldText)) {
                            m.text = newText;
                        } else {
                            m.text = oldText + '，' + newText;
                        }
                    } else {
                        m.text = newText;
                    }
                    // 保持 _asr_typing = true，等前端停顿5秒才真正定稿
                    m.timestamp = now;
                    this.$forceUpdate();
                    this._checkTopicTrigger(text);
                    return;
                }
            }
            // 没有找到正在输入的消息，找最近的同用户已定稿消息，如果间隔短就追加
            for (let i = this.msgs.length - 1; i >= 0; i--) {
                const m = this.msgs[i];
                if (m && m.username === username && m.asr_only && !m._asr_typing && (now - m.timestamp < 5000)) {
                    // 5秒内的上一条消息，重新激活并追加
                    m.text = (m.text || '').trim() + '，' + text.trim();
                    m._asr_typing = true;
                    m.quality_feedback = '<i class="fas fa-microphone"></i> 识别中...';
                    m.timestamp = now;
                    this.$forceUpdate();
                    this._checkTopicTrigger(text);
                    return;
                }
                break; // 只看最后一条
            }
            // 都没找到，新建一条
            this.appendAsrFinalToChat(username, text);
            this._checkTopicTrigger(text);
        },
        // 客户端停顿断句：当detectVolume检测到停顿时，把当前正在输入的partial文本定稿
        _finalizeCurrentAsrTyping() {
            const now = Date.now();
            for (let i = this.msgs.length - 1; i >= 0; i--) {
                const m = this.msgs[i];
                if (m && m._asr_typing && (now - m.timestamp < 15000)) {
                    const text = (m.text || '').trim();
                    if (text.length >= 2) {
                        m._asr_typing = false;
                        m.quality_feedback = '已断句，正在评分...';
                        m.timestamp = now;
                        this.$forceUpdate();
                        console.log('✅ 停顿断句:', text);
                        this._checkTopicTrigger(text);
                    }
                    return;
                }
            }
        },
        // 检测是否触发话题推送
        _checkTopicTrigger(text) {
            if (!text || this._topicSuggesting) return;
            const triggers = [
                '不知道该说什么', '不知道说什么', '不知道要讨论什么',
                '不知道讨论什么', '接下来说什么', '没什么好说的',
                '说什么呢', '聊什么呢', '讨论什么呢',
                '没有想法', '没想法', '不知道怎么说',
                '无话可说', '说不出来', '不知道从哪里说',
                '没什么可以讨论', '不知道聊什么'
            ];
            const normalized = text.replace(/\s+/g, '');
            const hit = triggers.some(t => normalized.includes(t));
            if (!hit) return;

            console.log('🎯 检测到话题触发词:', text, 'meetingId=', this.meetingId);
            if (!this.meetingId) {
                console.error('❌ 话题推送失败: meetingId为空');
                return;
            }
            this._topicSuggesting = true;

            // 调用后端生成话题建议（不弹中间提示框）
            const formData = new FormData();
            formData.append('meeting_id', this.meetingId);
            console.log('📤 发送话题推送请求, meeting_id=', this.meetingId);
            axios.post('/api/suggest-topic', formData)
                .then(res => {
                    console.log('📥 话题推送响应:', res.data);
                    const data = res.data;
                    if (data.status === 'success' && data.suggestion) {
                        const shown = this.showClassroomHint('💡 话题建议：' + data.suggestion, 10000, { cooldownMs: this.topicSuggestionCooldownMs });
                        // 推送到聊天栏
                        if (shown) {
                            this.msgs.push({
                                type: 'new_speech_fast',
                                username: 'AI助手',
                                text: '💡 ' + data.suggestion,
                                timestamp: Date.now(),
                                quality_score: null,
                                quality_feedback: '自动话题推送',
                                tags: { emotion: '', action: '' },
                                asr_only: false
                            });
                            this._trimMsgs();
                            this.$nextTick(() => {
                                if (this.$refs.chat) this.$refs.chat.scrollTop = 99999;
                            });
                        }
                    } else {
                        console.warn('⚠️ 话题推送返回异常:', data);
                    }
                })
                .catch(err => {
                    console.error('❌ 话题推送请求失败:', err);
                })
                .finally(() => {
                    // 话题触发词冷却更长一些，避免课堂里反复打断
                    setTimeout(() => { this._topicSuggesting = false; }, this.topicSuggestionCooldownMs);
                });
        },
        upsertAsrPartialToChat(username, text, sentenceId = null) {
            const clean = String(text || '').trim();
            if (!clean || !username) return;

            const now = Date.now();
            const normalizedIncoming = this.normalizeSpeechText(clean);
            const stableSentenceId = sentenceId || `local-${username}`;

            for (let i = this.msgs.length - 1; i >= 0; i--) {
                const m = this.msgs[i];
                if (!m || !m.asr_only || m.username !== username) continue;
                const dt = now - (Number(m.last_update_at || m.timestamp) || 0);
                if (dt > 30000) break;
                if (sentenceId && m.asr_sentence_id && m.asr_sentence_id !== sentenceId) continue;
                if (sentenceId && !m.asr_sentence_id) continue;

                const normalizedOld = this.normalizeSpeechText(m.text);
                const sameUtterance = !normalizedOld || !normalizedIncoming ||
                    normalizedOld === normalizedIncoming ||
                    normalizedOld.includes(normalizedIncoming) ||
                    normalizedIncoming.includes(normalizedOld);
                if (!sameUtterance && !m._asr_typing) continue;

                m.text = clean;
                m.last_update_at = now;
                m.asr_sentence_id = stableSentenceId;
                m._asr_typing = true;
                m.analyzing = true;
                m.quality_score = null;
                m.quality_feedback = '正在识别...';
                this.$forceUpdate();
                return;
            }

            for (let i = this.msgs.length - 1; i >= 0; i--) {
                const m = this.msgs[i];
                if (!m || m.asr_only || m.username !== username) continue;
                const dt = now - (Number(m.timestamp) || 0);
                if (dt > 15000) break;
                const normalizedOld = this.normalizeSpeechText(m.text);
                if (normalizedOld && normalizedIncoming && (normalizedOld === normalizedIncoming || normalizedOld.includes(normalizedIncoming) || normalizedIncoming.includes(normalizedOld))) {
                    return;
                }
            }

            this.msgs.push({
                type: 'new_speech_fast',
                client_msg_id: `asr-live-${stableSentenceId}-${now}`,
                asr_sentence_id: stableSentenceId,
                username,
                text: clean,
                timestamp: now,
                last_update_at: now,
                quality_score: null,
                quality_feedback: '正在识别...',
                tags: { emotion: 'neutral', action: '' },
                asr_only: true,
                _asr_typing: true,
                analyzing: true
            });
            this._trimMsgs();
            this.$nextTick(() => {
                if (this.$refs.chat) this.$refs.chat.scrollTop = 99999;
            });
        },
        findSpeechMessageByEvent(d) {
            const normalizedIncoming = this.normalizeSpeechText((d && d.text) || '');
            if (d && d.asr_sentence_id) {
                const bySentence = this.msgs.find(m => String(m.asr_sentence_id || '') === String(d.asr_sentence_id));
                if (bySentence) return bySentence;
            }
            if (d && d.transcript_id !== undefined && d.transcript_id !== null) {
                const byId = this.msgs.find(m => String(m.transcript_id || '') === String(d.transcript_id));
                if (byId) return byId;
            }
            if (d && d.timestamp !== undefined) {
                const byTs = this.msgs.find(m => m.timestamp === d.timestamp);
                if (byTs) return byTs;
            }
            if (!d || !d.username) return null;
            for (let i = this.msgs.length - 1; i >= 0; i--) {
                const m = this.msgs[i];
                if (!m || m.username !== d.username) continue;
                const dt = Math.abs((Number(m.timestamp) || 0) - (Number(d.timestamp) || Date.now()));
                if (dt > 60000) continue;
                const normalizedOld = this.normalizeSpeechText(m.text || '');
                const waiting = String(m.quality_feedback || '').includes('正在评分') || m._feedbackAnimating;
                const incomingIsFragment = normalizedIncoming && normalizedOld && normalizedOld.includes(normalizedIncoming) && normalizedOld.length > normalizedIncoming.length * 1.25;
                if (incomingIsFragment) continue;
                const similar = normalizedIncoming && normalizedOld && (
                    normalizedOld === normalizedIncoming ||
                    normalizedOld.includes(normalizedIncoming) ||
                    normalizedIncoming.includes(normalizedOld)
                );
                if (similar || waiting) return m;
            }
            return null;
        },
        startStreamingFeedback(target) {
            if (!target) return;
            if (target.__feedbackTimer) {
                clearInterval(target.__feedbackTimer);
                target.__feedbackTimer = null;
            }
            target.__feedbackQueue = '';
            target.quality_feedback = '';
            target.analyzing = true;
            this.$set(target, '_feedbackAnimating', true);
            this.$forceUpdate();
        },
        appendStreamingFeedbackDelta(target, delta) {
            if (!target || !delta) return;
            target.__feedbackQueue = (target.__feedbackQueue || '') + String(delta);
            if (target.__feedbackTimer) return;
            this.$set(target, '_feedbackAnimating', true);
            target.__feedbackTimer = setInterval(() => {
                const queue = target.__feedbackQueue || '';
                if (queue.length > 0) {
                    // 批量处理：每次显示3个字符，减少更新频率
                    const chunkSize = Math.min(3, queue.length);
                    target.quality_feedback = String(target.quality_feedback || '') + queue.substring(0, chunkSize);
                    target.__feedbackQueue = queue.slice(chunkSize);
                    // 只在必要时更新，不使用 $forceUpdate
                    this.$set(target, 'quality_feedback', target.quality_feedback);
                    return;
                }
                clearInterval(target.__feedbackTimer);
                target.__feedbackTimer = null;
                this.$set(target, '_feedbackAnimating', false);
            }, 50);
        },
        finishStreamingFeedback(target, finalText) {
            if (!target) return;
            if (target.__feedbackTimer) {
                clearInterval(target.__feedbackTimer);
                target.__feedbackTimer = null;
            }
            target.__feedbackQueue = '';
            target.quality_feedback = finalText || target.quality_feedback || '已评估';
            this.$set(target, '_feedbackAnimating', false);
        },
        updateRealtimeSubtitle(username, text, isFinal) {
            this.realtimeSubtitle = { username, text, isFinal };
            this.realtimeSubtitleLastAt = Date.now();
            if (this.realtimeSubtitleTimer) clearTimeout(this.realtimeSubtitleTimer);
            // 无论 partial/final，都设置“无更新超时清除”，避免卡住在第一句
            const ttl = isFinal ? 3500 : 2500;
            this.realtimeSubtitleTimer = setTimeout(() => {
                // 只有在这段时间内没有新更新才清除
                if (Date.now() - (this.realtimeSubtitleLastAt || 0) >= ttl) {
                    this.realtimeSubtitle = null;
                }
            }, ttl);
        },
        // 规范化文本用于去重匹配
        normalizeSpeechText(text) {
            let str = String(text || "").trim().replace(/\s+/g, "").toLowerCase();
            // 移除中文标点
            str = str.replace(/[\u3000-\u303F\uFF00-\uFFEF]/g, "");
            // 移除英文标点符号
            str = str.replace(/[,.!?;:()[\]{}()<>]/g, "");
            // 移除引号
            str = str.replace(/[\u0027\u0022\u2018\u2019\u201C\u201D]/g, "");
            return str;
        },
        // 计算两个文本的相似度（0-1之间，1表示完全相同）
        textSimilarity(text1, text2) {
            const s1 = this.normalizeSpeechText(text1);
            const s2 = this.normalizeSpeechText(text2);
            if (!s1 || !s2) return 0;
            if (s1 === s2) return 1;

            // 如果一个包含另一个，相似度很高
            if (s1.includes(s2) || s2.includes(s1)) {
                const shorter = Math.min(s1.length, s2.length);
                const longer = Math.max(s1.length, s2.length);
                return shorter / longer;
            }

            // 计算编辑距离相似度
            const maxLen = Math.max(s1.length, s2.length);
            if (maxLen === 0) return 1;
            const distance = this.levenshteinDistance(s1, s2);
            return 1 - (distance / maxLen);
        },
        findRecentSpeechOverlap(username, text, options = {}) {
            const incoming = this.normalizeSpeechText(text);
            if (!incoming) return null;
            const now = Date.now();
            const windowMs = options.windowMs || 90000;
            const threshold = options.threshold || 0.72;
            const includeAsrOnly = !!options.includeAsrOnly;

            for (let i = this.msgs.length - 1; i >= 0; i--) {
                const m = this.msgs[i];
                if (!m || m.username !== username) continue;
                if (m.type !== 'new_speech_fast' && m.type !== 'new_speech') continue;
                if (!includeAsrOnly && m.asr_only) continue;
                const ts = Number(m.last_update_at || m.timestamp) || now;
                if (Math.abs(now - ts) > windowMs) continue;
                const old = this.normalizeSpeechText(m.text || '');
                if (!old) continue;
                const incomingInOld = old.includes(incoming);
                const oldInIncoming = incoming.includes(old);
                const similarity = this.textSimilarity(old, incoming);
                if (incomingInOld || oldInIncoming || similarity >= threshold) {
                    return {
                        index: i,
                        message: m,
                        incomingInOld,
                        oldInIncoming,
                        similarity,
                        oldLength: old.length,
                        incomingLength: incoming.length
                    };
                }
            }
            return null;
        },
        removeContainedSpeechFragments(username, fullText, keepIndex = -1) {
            const full = this.normalizeSpeechText(fullText);
            if (!full || full.length < 12) return;
            const now = Date.now();
            for (let i = this.msgs.length - 1; i >= 0; i--) {
                if (i === keepIndex) continue;
                const m = this.msgs[i];
                if (!m || m.username !== username) continue;
                if (m.type !== 'new_speech_fast' && m.type !== 'new_speech') continue;
                const ts = Number(m.last_update_at || m.timestamp) || now;
                if (Math.abs(now - ts) > 90000) continue;
                const old = this.normalizeSpeechText(m.text || '');
                if (old && full.includes(old) && full.length > old.length * 1.25) {
                    this.msgs.splice(i, 1);
                    if (keepIndex > i) keepIndex -= 1;
                }
            }
        },
        removeSpeechMessageByTranscript(transcriptId) {
            if (transcriptId === undefined || transcriptId === null) return;
            const tid = String(transcriptId);
            this.msgs = this.msgs.filter(m => String((m && m.transcript_id) || '') !== tid);
        },
        // 计算编辑距离（Levenshtein距离）
        levenshteinDistance(str1, str2) {
            const len1 = str1.length;
            const len2 = str2.length;
            const matrix = Array(len1 + 1).fill(null).map(() => Array(len2 + 1).fill(0));

            for (let i = 0; i <= len1; i++) matrix[i][0] = i;
            for (let j = 0; j <= len2; j++) matrix[0][j] = j;

            for (let i = 1; i <= len1; i++) {
                for (let j = 1; j <= len2; j++) {
                    const cost = str1[i - 1] === str2[j - 1] ? 0 : 1;
                    matrix[i][j] = Math.min(
                        matrix[i - 1][j] + 1,      // 删除
                        matrix[i][j - 1] + 1,      // 插入
                        matrix[i - 1][j - 1] + cost // 替换
                    );
                }
            }
            return matrix[len1][len2];
        },
        removeRejectedAsrFromChat(username, sentenceId = null) {
            if (sentenceId) {
                const sid = String(sentenceId);
                this.msgs = this.msgs.filter(m => String((m && m.asr_sentence_id) || '') !== sid);
                return;
            }
            for (let i = this.msgs.length - 1; i >= 0; i--) {
                const m = this.msgs[i];
                if (m && m.asr_only && m.username === username) {
                    this.msgs.splice(i, 1);
                    return;
                }
            }
        },
        // 将阿里云 asr_final 写入聊天，并在后续 new_speech_fast 到来时做合并去重
        appendAsrFinalToChat(username, text, sentenceId = null) {
            const clean = String(text || '').trim();
            if (!clean) return;

            const now = Date.now();
            const normalizedIncoming = this.normalizeSpeechText(clean);
            const overlap = this.findRecentSpeechOverlap(username, clean, {
                includeAsrOnly: true,
                windowMs: 90000,
                threshold: 0.72
            });
            if (overlap && !overlap.message.asr_only) {
                if (overlap.incomingInOld && overlap.oldLength > overlap.incomingLength * 1.25) {
                    console.log('忽略已包含在完整发言里的短句 asr_final:', clean);
                    return;
                }
                if (overlap.oldInIncoming && overlap.incomingLength > overlap.oldLength) {
                    overlap.message.text = clean;
                    overlap.message.last_update_at = now;
                    if (sentenceId) overlap.message.asr_sentence_id = sentenceId;
                    this.removeContainedSpeechFragments(username, clean, overlap.index);
                    this.$forceUpdate();
                    return;
                }
            }

            // 1) 如果同一用户已有正在识别的占位消息，直接更新它，不新建气泡
            for (let i = this.msgs.length - 1; i >= 0; i--) {
                const m = this.msgs[i];
                if (m && m.username === username && m.asr_only) {
                    if (sentenceId && m.asr_sentence_id && m.asr_sentence_id !== sentenceId) continue;
                    const dt = now - (Number(m.timestamp) || 0);
                    if (dt < 30000) {
                        // ✅ 使用相似度匹配
                        const similarity = this.textSimilarity(m.text, clean);
                        if (similarity >= 0.7) {
                            m.text = clean;
                            m.last_update_at = now;
                            if (sentenceId) m.asr_sentence_id = sentenceId;
                            m._asr_typing = false;
                            m.analyzing = true;
                            m.quality_feedback = '已断句，正在评分...';
                            this.removeContainedSpeechFragments(username, clean, i);
                            this.$forceUpdate();
                            return;
                        }
                    }
                }
            }

            // 2) 若真实 new_speech_fast 已先到达（ASR晚到），则不要再追加“等待评分”占位
            const latestRealIdx = (() => {
                for (let i = this.msgs.length - 1; i >= 0; i--) {
                    const m = this.msgs[i];
                    if (!m || m.asr_only) continue;
                    if (m.type !== 'new_speech_fast' && m.type !== 'new_speech') continue;
                    if (m.username !== username) continue;
                    const dt = now - (Number(m.timestamp) || 0);
                    if (dt > 30000) break;
                    // ✅ 使用相似度匹配
                    const similarity = this.textSimilarity(m.text, clean);
                    if (similarity >= 0.7) {
                        return i;
                    }
                }
                return -1;
            })();
            if (latestRealIdx >= 0) {
                this.msgs[latestRealIdx].text = clean;
                this.removeContainedSpeechFragments(username, clean, latestRealIdx);
                this.$forceUpdate();
                return;
            }

            const msg = {
                type: 'new_speech_fast',
                client_msg_id: `asr-final-${sentenceId || username + '-' + now}`,
                asr_sentence_id: sentenceId || null,
                username,
                text: clean,
                timestamp: now,
                quality_score: null,
                quality_feedback: '已断句，正在评分...',
                tags: { emotion: '未知', action: '' },
                asr_only: true,
                _asr_typing: false,
                analyzing: true
            };

            // 避免 asr_final 自身重复刷屏：同一用户短时间内同文本不重复入列
            const lastSame = [...this.msgs].reverse().find(m => m && m.asr_only && m.username === username);
            if (lastSame) {
                if (sentenceId && lastSame.asr_sentence_id && lastSame.asr_sentence_id !== sentenceId) {
                    this.msgs.push(msg);
                    this._trimMsgs();
                    this.$nextTick(() => {
                        if (this.$refs.chat) this.$refs.chat.scrollTop = 99999;
                    });
                    return;
                }
                const dt = now - (Number(lastSame.timestamp) || 0);
                const a = this.normalizeSpeechText(lastSame.text);
                const b = this.normalizeSpeechText(clean);
                if (dt < 8000 && a && b && (a === b || a.includes(b) || b.includes(a))) {
                    lastSame.text = clean;
                    lastSame.last_update_at = now;
                    const keepIndex = this.msgs.indexOf(lastSame);
                    this.removeContainedSpeechFragments(username, clean, keepIndex);
                    this.$forceUpdate();
                    return;
                }
            }

            this.msgs.push(msg);
            this.removeContainedSpeechFragments(username, clean, this.msgs.length - 1);
            this._trimMsgs();
            this.$nextTick(() => {
                if (this.$refs.chat) this.$refs.chat.scrollTop = 99999;
            });
        },
        connectWs() {
            let protocol = location.protocol==="https:"?"wss":"ws";
            this.ws = new WebSocket(`${protocol}://${location.host}/ws/${this.currentUser.username}/${this.meetingId}`);

            // 清除旧的心跳定时器
            if (this.wsHeartbeatTimer) {
                clearInterval(this.wsHeartbeatTimer);
                this.wsHeartbeatTimer = null;
            }

            this.ws.onopen = () => {
                console.log("✅ WebSocket已连接");
                // 启动心跳保活机制（每30秒发送一次ping）
                this.wsHeartbeatTimer = setInterval(() => {
                    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                        this.ws.send("ping");
                        console.log("💓 发送心跳 ping");
                    }
                }, 30000);
            };

            this.ws.onclose = (e) => {
                console.log("⚠️ WebSocket断开，3秒后重连...", e.code);
                // 清除心跳定时器
                if (this.wsHeartbeatTimer) {
                    clearInterval(this.wsHeartbeatTimer);
                    this.wsHeartbeatTimer = null;
                }
                // 自动重连
                if (this.joined && this.pageState === "classroom") {
                    setTimeout(() => {
                        console.log("🔄 尝试重连 WebSocket...");
                        this.connectWs();
                    }, 3000);
                }
            };

            this.ws.onerror = (e) => {
                console.error("❌ WebSocket错误:", e);
            };

            this.ws.onmessage = e => {
                // 处理心跳响应
                if (typeof e.data === "string" && e.data === "pong") {
                    console.log("💓 收到心跳 pong");
                    return;
                }

                let d = JSON.parse(e.data);
                console.log("📨 收到WebSocket消息:", d.type, d);  // ✅ 添加调试日志

                if (d.type === 'asr_partial') {
                    this.asrLastMessageAt = Date.now();
                    this.stopBrowserSpeechRecognition();
                    this.updateRealtimeSubtitle(d.username, d.text, false);
                    this.upsertAsrPartialToChat(d.username, d.text, d.asr_sentence_id);
                    return;
                }
                if (d.type === 'asr_final') {
                    this.asrLastMessageAt = Date.now();
                    this.stopBrowserSpeechRecognition();
                    this.updateRealtimeSubtitle(d.username, d.text, true);
                    this.appendAsrFinalToChat(d.username, d.text, d.asr_sentence_id);
                    this.scheduleRealtimeDataRefresh(800);
                    setTimeout(() => this.scheduleRealtimeDataRefresh(500), 3500);
                    return;
                }
                if (d.type === 'asr_rejected') {
                    this.removeRejectedAsrFromChat(d.username, d.asr_sentence_id);
                    return;
                }

                // === 1. 收到快消息 (文字) ===
                if(d.type === "new_speech_fast") {
                    console.log("✅ 处理new_speech_fast消息:", d.text);
                    if(!d.text || d.text.length < 1) {
                        console.warn('⚠️ 文字为空，忽略');
                        return;
                    }
                    const pendingAnalysis = String(d.quality_feedback || '').includes('正在评分') || String(d.quality_feedback || '').includes('评估中');
                    d.analyzing = pendingAnalysis;
                    if (pendingAnalysis) d.quality_score = null;
                    if (!d.tags) d.tags = { emotion: '未知', action: '' };
                    if (d.replaces_transcript_id) {
                        this.removeSpeechMessageByTranscript(d.replaces_transcript_id);
                    }

                    // ✅ 去重合并：优先查找 asr_only 占位消息并替换
                    const now = Date.now();
                    const incomingSentenceId = d.asr_sentence_id ? String(d.asr_sentence_id) : '';

                    // 第一优先级：查找同一用户的 asr_only 占位消息
                    const idx = (() => {
                        for (let i = this.msgs.length - 1; i >= 0; i--) {
                            const m = this.msgs[i];
                            if (!m || !m.asr_only) continue;
                            if (m.username !== d.username) continue;
                            const dt = now - (Number(m.timestamp) || 0);
                            if (dt > 60000) break; // 超过60秒就不合并

                            // 如果有句子ID，精确匹配
                            if (incomingSentenceId && String(m.asr_sentence_id || '') === incomingSentenceId) {
                                return i;
                            }

                            // 使用相似度和短句等待状态兜底，避免“靠/考”等短误识别拆成两个框
                            {
                                const similarity = this.textSimilarity(m.text, d.text);
                                const oldLen = this.normalizeSpeechText(m.text).length;
                                const newLen = this.normalizeSpeechText(d.text).length;
                                const waiting = String(m.quality_feedback || '').includes('正在') || m._asr_typing || m.analyzing;
                                if (similarity >= 0.45 || (waiting && dt < 12000 && oldLen <= 8 && newLen <= 8)) {
                                    return i;
                                }
                            }
                        }
                        return -1;
                    })();

                    if (idx >= 0) {
                        // 找到占位消息，直接替换
                        const previous = this.msgs[idx] || {};
                        const target = {
                            ...d,
                            text: d.text,
                            asr_only: false,
                            client_msg_id: previous.client_msg_id || d.client_msg_id,
                            asr_sentence_id: d.asr_sentence_id || previous.asr_sentence_id
                        };
                        this.$set(this.msgs, idx, target);
                        console.log('✅ 替换ASR占位消息 -> new_speech_fast', { idx, username: d.username, oldText: previous.text, newText: d.text });
                    } else {
                        const overlap = this.findRecentSpeechOverlap(d.username, d.text, {
                            includeAsrOnly: true,
                            windowMs: 90000,
                            threshold: 0.72
                        });
                        if (overlap) {
                            const target = overlap.message;
                            if (overlap.incomingInOld && overlap.oldLength > overlap.incomingLength * 1.25) {
                                console.log('忽略已包含在完整发言里的短句 new_speech_fast:', d.text);
                            } else {
                                if (overlap.oldInIncoming && overlap.incomingLength > overlap.oldLength) {
                                    target.text = d.text;
                                }
                                if (!target.transcript_id && d.transcript_id !== undefined) target.transcript_id = d.transcript_id;
                                if (d.asr_sentence_id && !target.asr_sentence_id) target.asr_sentence_id = d.asr_sentence_id;
                                if (d.goals) this.goals = d.goals;
                                target.last_update_at = now;
                                this.removeContainedSpeechFragments(d.username, target.text, overlap.index);
                                this.$forceUpdate();
                            }
                            return;
                        }
                        // 没找到占位消息，添加新消息（不需要额外去重，因为上面已经用相似度匹配过了）
                        const msg = { ...d, text: d.text };
                        this.msgs.push(msg);
                        this.removeContainedSpeechFragments(d.username, d.text, this.msgs.length - 1);
                        this._trimMsgs();
                        console.log('✅ 新消息已添加到msgs，当前总数:', this.msgs.length);
                    }
                    if (d.goals) this.goals = d.goals;
                    
                    // 中间黑色弹窗已取消，仅保留绿色实时发言框
                    // ✅ 兜底：如果 asr 实时字幕卡住/断流，使用后端 new_speech_fast 同步刷新青色条
                    if (!this.realtimeSubtitle || (Date.now() - (this.realtimeSubtitleLastAt || 0) > 4000)) {
                        this.updateRealtimeSubtitle(d.username, d.text, true);
                    }
                    
                    // 安全滚动到底部（检查元素是否存在）
                    this.$nextTick(() => {
                        if (this.$refs.chat) {
                            this.$refs.chat.scrollTop = 99999;
                        }
                    });
                }

                // === 2. 收到慢消息 (分析更新) ===
                else if (d.type === 'speech_feedback_stream_start') {
                    const target = this.findSpeechMessageByEvent(d);
                    if (target) {
                        target.asr_only = false;
                        if (d.transcript_id !== undefined) target.transcript_id = d.transcript_id;
                        this.startStreamingFeedback(target);
                    } else {
                        console.warn('⚠️ 未找到流式评语对应的发言消息:', d);
                    }
                }
                else if (d.type === 'speech_feedback_delta') {
                    const target = this.findSpeechMessageByEvent(d);
                    if (target) {
                        target.asr_only = false;
                        if (d.transcript_id !== undefined) target.transcript_id = d.transcript_id;
                        this.appendStreamingFeedbackDelta(target, d.delta || '');
                    } else {
                        console.warn('⚠️ 未找到流式评语增量对应的发言消息:', d);
                    }
                }
                else if (d.type === 'speech_analysis_update') {
                    // 找到刚才那条消息，更新它
                    const normalizedIncoming = this.normalizeSpeechText(d.text || '');
                    let target = null;
                    if (d.asr_sentence_id) {
                        target = this.msgs.find(m => String(m.asr_sentence_id || '') === String(d.asr_sentence_id));
                    }
                    if (d.transcript_id !== undefined && d.transcript_id !== null) {
                        target = target || this.msgs.find(m => String(m.transcript_id || '') === String(d.transcript_id));
                    }
                    if (!target) {
                        target = this.msgs.find(m => m.timestamp === d.timestamp);
                    }
                    if (!target && d.username) {
                        target = (() => {
                            for (let i = this.msgs.length - 1; i >= 0; i--) {
                                const m = this.msgs[i];
                                if (!m || m.username !== d.username) continue;
                                const dt = Math.abs((Number(m.timestamp) || 0) - (Number(d.timestamp) || Date.now()));
                                if (dt > 60000) continue;
                                const normalizedOld = this.normalizeSpeechText(m.text || '');
                                const waiting = String(m.quality_feedback || '').includes('正在评分');
                                const incomingIsFragment = normalizedIncoming && normalizedOld && normalizedOld.includes(normalizedIncoming) && normalizedOld.length > normalizedIncoming.length * 1.25;
                                if (incomingIsFragment) continue;
                                const similar = normalizedIncoming && normalizedOld && (
                                    normalizedOld === normalizedIncoming ||
                                    normalizedOld.includes(normalizedIncoming) ||
                                    normalizedIncoming.includes(normalizedOld)
                                );
                                if (similar || waiting) return m;
                            }
                            return null;
                        })();
                    }
                    if (target) {
                        target.analyzing = false; // 去掉分析中的状态
                        target.asr_only = false;
                        if (d.transcript_id !== undefined) target.transcript_id = d.transcript_id;
                        if (d.timestamp !== undefined) target.timestamp = d.timestamp;
                        // 更新AI评分
                        if (d.quality_score !== undefined) target.quality_score = d.quality_score;
                        if (d.quality_feedback !== undefined) {
                            this.finishStreamingFeedback(target, d.quality_feedback || '已评估');
                        }
                        this.$forceUpdate(); // 强制刷新界面
                    } else {
                        console.warn('⚠️ 未找到评分更新对应的发言消息:', d);
                        // 尝试通过 transcript_id 强制更新
                        if (d.transcript_id) {
                            const fallback = this.msgs.find(m => m.transcript_id === d.transcript_id);
                            if (fallback) {
                                fallback.analyzing = false;
                                fallback.quality_score = d.quality_score;
                                fallback.quality_feedback = d.quality_feedback || '已评估';
                                this.$forceUpdate();
                                console.log('✅ 通过 transcript_id 强制更新消息');
                            }
                        }
                    }
                    if (d.goals) this.goals = d.goals;
                    if (d.relevance !== undefined) this.currentRelevance = d.relevance;
                    if (d.hint && d.username === this.currentUser.username) {
                        this.showClassroomHint(d.hint, 7000, { cooldownMs: this.classroomHintCooldownMs });
                    }
                    
                    // ✅ AI评分完成后也更新统计图表
                    this.scheduleRealtimeDataRefresh(500);
                }

                else if (d.type === 'new_emotion') { 
                    this.msgs.push(d);
                    this._trimMsgs();
                    this.$nextTick(() => {
                        if (this.$refs.chat) {
                            this.$refs.chat.scrollTop = 99999;
                        }
                    }); 
                }
                
                // === 3. 知识图谱更新 ===
                else if (d.type === 'knowledge_graph_update') {
                    this.knowledgeGraphData = d.data;
                    if (this.showKnowledgeGraph) {
                        this.renderKnowledgeGraph();
                    }
                }
                
                // === 实时更新统计图表 ===
                if (d.type === 'new_speech_fast' || d.type === 'new_emotion') {
                    // ✅ 每收到新消息就立即更新统计数据（无论在哪个页面）
                    this.scheduleRealtimeDataRefresh(500);
                    
                    // 观点聚类投票改为手动触发（点击左侧按钮），避免自动弹出打断课堂流程
                }
                else if (d.type === 'speaking_status') {
                    if (d.username) this.$set(this.speakingMembers, d.username, d.status === 'recognizing');
                    const now = Date.now();
                    if (now - (this._lastSpeakingStatusEmotionRefreshAt || 0) > 8000) {
                        this._lastSpeakingStatusEmotionRefreshAt = now;
                        setTimeout(() => this.loadEmotionDetails(), 1200);
                    }
                }
                
                // === 4. 接收其他人的视频流(教师共享屏幕) ===
                else if (d.type === 'teacher_video_stream' && this.currentUser.role === 'student') {
                    // TODO: 显示教师画面(需要WebRTC或视频流转发)
                    console.log('✅ 收到教师画面');
                }
                
                // === 5. 成员加入/离开 ===
                else if (d.type === 'member_update') {
                    this.onlineMembers = d.online_members || [];
                    if (d.action === 'join') {
                        console.log('👥 成员加入:', d.username);
                        // 声网Agora模式：远端用户自动通过SDK事件处理，无需手动连接
                    } else if (d.action === 'leave') {
                        console.log('👥 成员离开:', d.username);
                        // 清理离开成员的状态（Agora SDK 会触发 user-left 事件自动清理远端流）
                        this.$delete(this.remoteStreams, d.username);
                        this.$delete(this.speakingMembers, d.username);
                        if (this.pinnedMember === d.username) this.pinnedMember = null;
                    }
                }
                
                // === 6. 投票开始 ===
                else if (d.type === 'vote_start') {
                    console.log('🗳️ 收到投票开始:', d);
                    this.currentVoteId = d.vote_id;
                    this.viewpoints = d.viewpoints || [];
                    this.viewpointSummary = d.summary || '';
                    this.voteResults = d.votes || {};
                    this.voteCounts = {};
                    for (let k in this.voteResults) {
                        this.voteCounts[k] = this.voteResults[k].length;
                    }
                    this.myVote = null;
                    this.voteConfirmed = false;
                    this.confirmedMembers = [];
                    this.voteDecomposing = false;
                    this.showViewpointVote = true;
                }
                
                // === 7. 投票更新 ===
                else if (d.type === 'vote_update') {
                    console.log('🗳️ 票数更新:', d);
                    this.voteResults = d.votes || {};
                    this.voteCounts = d.vote_counts || {};
                    this.$forceUpdate();
                }

                // === 7.5 投票确认更新 ===
                else if (d.type === 'vote_confirm') {
                    console.log('✅ 成员确认选择:', d);
                    this.confirmedMembers = d.confirmed_members || [];
                    // 当所有成员都确认后，显示任务分解进度
                    if (this.confirmedMembers.length >= d.total_online) {
                        this.voteDecomposing = true;
                        // 安全超时：120秒后自动关闭弹窗，防止永久卡住
                        setTimeout(() => {
                            if (this.voteDecomposing && this.showViewpointVote) {
                                console.warn('⚠️ 投票分解超时120s，自动关闭弹窗');
                                this.showViewpointVote = false;
                                this.voteDecomposing = false;
                                this.hint = '⚠️ 任务分解超时，请稍后在侧边栏查看';
                                setTimeout(() => this.hint = null, 5000);
                            }
                        }, 120000);
                    }
                    this.$forceUpdate();
                }

                // === 8. 投票结果 ===
                else if (d.type === 'vote_result') {
                    console.log('🎉 投票结果:', d);
                    this.showViewpointVote = false;
                    this.voteDecomposing = false;
                    // 如果后台正在异步分解，先显示提示，等 goals_updated 再更新侧边栏
                    if (d.decomposing) {
                        if (d.winner_viewpoint) {
                            this.hint = '🎉 "' + d.winner_viewpoint.title + '"获胜！正在分解子任务...';
                        }
                    } else {
                        if (d.updated_goals) this.goals = d.updated_goals;
                        this.subGoals = d.sub_goals || [];
                        this.subGoalGuidance = d.guidance || '';
                        if (d.winner_viewpoint) {
                            this.hint = '🎉 "' + d.winner_viewpoint.title + '"获胜！新子目标已更新';
                            setTimeout(() => this.hint = null, 8000);
                        }
                    }
                }

                // === 8.5 AI任务分解结果（异步返回） ===
                else if (d.type === 'goals_updated') {
                    console.log('🎯 收到AI任务分解:', d);
                    this.goals = d.updated_goals || [];
                    this.subGoals = d.sub_goals || [];
                    this.subGoalGuidance = d.guidance || '';

                    // 关闭投票弹窗和分解状态
                    this.showViewpointVote = false;
                    this.voteDecomposing = false;

                    if (d.main_viewpoint) {
                        this.hint = '🎯 任务已分解：' + d.main_viewpoint;
                        setTimeout(() => this.hint = null, 8000);
                    }
                }
                                
                // === 9. 资料推荐 ===
                else if (d.type === 'material_recommendation') {
                    console.log('📚 收到资料推荐:', d);
                    this.recommendedMaterials = d.materials || [];
                    this.showMaterialsPanel = true;
                    this.showClassroomHint('📚 推荐了 ' + this.recommendedMaterials.length + ' 份资料', 5000, { cooldownMs: this.classroomHintCooldownMs });
                }

                // === 10. 目标完成通知 ===
                else if (d.type === 'goal_completed') {
                    console.log('🎯 目标完成:', d);
                    this.goals = d.goals || this.goals;
                    this.goalCompletePopup = {
                        show: true,
                        goals: d.completed_goals || [],
                        allDone: d.all_done || false
                    };
                    // 自动关闭
                    setTimeout(() => { this.goalCompletePopup.show = false; }, d.all_done ? 8000 : 5000);
                }

                // === 10.5 课堂结束通知 ===
                else if (d.type === 'class_ended') {
                    console.log('🏁 课堂结束:', d);
                    this.showAlert(d.message || '课堂已结束', 'info', '课堂结束');
                    this._cleanupClassroom();
                }

                // === 11. 话题建议推送 ===
                else if (d.type === 'topic_suggestion') {
                    console.log('💬 话题建议:', d);
                    this.showTopicSuggestionNotice(d.suggestion || '', d.reason || '');
                }
            }
        },
        showSubtitle(username, text) {
            // 清除之前的定时器
            if (this.subtitleTimer) {
                clearTimeout(this.subtitleTimer);
            }
            
            // 显示新字幕
            this.currentSubtitle = { username, text };
            
            // 5秒后自动消失
            this.subtitleTimer = setTimeout(() => {
                this.currentSubtitle = null;
            }, 5000);
        },
        async loadKnowledgeGraph() {
            try {
                let res = await axios.get(`/api/knowledge-graph/${this.meetingId}`);
                if (res.data.status === 'success') {
                    this.knowledgeGraphData = res.data.data;
                    this.renderKnowledgeGraph();
                }
            } catch(e) {
                console.error('加载知识图谱失败:', e);
            }
        },
        async loadClassroomData(meetingId) {
            try {
                // 加载课堂目标
                let meetingRes = await axios.get(`/api/meeting/${meetingId}`);
                if (meetingRes.data.status === 'success') {
                    this.goals = meetingRes.data.goals || [];
                }
                // 加载知识图谱
                await this.loadKnowledgeGraph();
                // 加载统计数据（确保重新进入课堂时能看到历史统计）
                await this.loadRealtimeStats();
            } catch(e) {
                console.error('加载课堂数据失败:', e);
            }
        },
        renderKnowledgeGraph() {
            if (!this.knowledgeGraphData || !this.knowledgeGraphData.nodes) return;
            
            this.$nextTick(() => {
                const chartDom = document.getElementById('knowledgeGraphChart');
                if (!chartDom) return;
                
                if (!this.chartInstance) {
                    this.chartInstance = echarts.init(chartDom);
                }
                
                const option = {
                    title: {
                        text: '课堂知识关系图',
                        left: 'center',
                        top: 20,
                        textStyle: {
                            fontSize: 20,
                            fontWeight: 'bold',
                            color: '#1e293b'
                        }
                    },
                    tooltip: {
                        formatter: function(params) {
                            if (params.dataType === 'node') {
                                return params.data.tooltip ? params.data.tooltip.formatter : params.name;
                            }
                            return params.data.label ? params.data.label.formatter : '';
                        },
                        backgroundColor: 'rgba(255, 255, 255, 0.95)',
                        borderColor: '#3E7C86',
                        borderWidth: 2,
                        textStyle: {
                            color: '#1e293b'
                        }
                    },
                    legend: [{
                        data: this.knowledgeGraphData.categories.map(c => c.name),
                        orient: 'vertical',
                        left: 30,
                        top: 80,
                        itemGap: 15,
                        textStyle: {
                            fontSize: 13,
                            fontWeight: 'bold'
                        },
                        icon: 'circle'
                    }],
                    series: [{
                        type: 'graph',
                        layout: 'force',
                        data: this.knowledgeGraphData.nodes,
                        links: this.knowledgeGraphData.links,
                        categories: this.knowledgeGraphData.categories,
                        roam: true,
                        label: {
                            show: true,
                            position: 'right',
                            fontSize: 12,
                            fontWeight: 'bold'
                        },
                        force: {
                            repulsion: 800,
                            edgeLength: [100, 200],
                            gravity: 0.1
                        },
                        lineStyle: {
                            color: 'source',
                            curveness: 0.3,
                            width: 2
                        },
                        emphasis: {
                            focus: 'adjacency',
                            lineStyle: {
                                width: 6
                            },
                            itemStyle: {
                                shadowBlur: 10,
                                shadowColor: 'rgba(102, 126, 234, 0.5)'
                            }
                        },
                        itemStyle: {
                            borderWidth: 2,
                            borderColor: '#fff',
                            shadowBlur: 5,
                            shadowColor: 'rgba(0, 0, 0, 0.2)'
                        }
                    }]
                };
                
                this.chartInstance.setOption(option);
            });
        },
        async summary() { let res = await axios.get(`/summary?meeting_id=${this.meetingId}`); this.showAlert(JSON.stringify(res.data, null, 2), 'info', '会议总结'); },
        // 情绪英文转中文
        translateEmotion(e) {
            const map = {
                'excited': '兴奋', 'happy': '开心', 'surprised': '惊喜',
                'calm': '平静', 'neutral': '平静', 'thinking': '思考',
                'confused': '困惑', 'sad': '难过', 'angry': '生气',
                'relaxed': '放松', 'anxious': '焦虑', 'worried': '担忧'
            };
            return map[(e || '').toLowerCase()] || e || '平静';
        },
        // Markdown渲染
        renderMarkdown(text) {
            if (text === null || text === undefined || text === '') return '';
            if (Array.isArray(text)) text = text.join(', ');
            if (typeof text !== 'string') {
                try { text = JSON.stringify(text); } catch(e) { text = String(text); }
            }
            try {
                if (typeof marked !== 'undefined') {
                    marked.setOptions({ breaks: true, gfm: true });
                    return marked.parse(text);
                }
            } catch(e) {}
            try { return text.replace(/\n/g, '<br>'); } catch(e) { return ''; }
        },
        // 打字机效果：逐字显示文本
        animateText(target, field, fullText, speed) {
            const timerKey = '__animTimer_' + field;
            if (target[timerKey]) clearInterval(target[timerKey]);
            let i = 0;
            const timer = setInterval(() => {
                if (i < fullText.length) {
                    target[field] = fullText.substring(0, i + 1);
                    i++;
                    this.$forceUpdate();
                } else {
                    clearInterval(timer);
                    target[timerKey] = null;
                    this.$set(target, '_feedbackAnimating', false);
                    this.$forceUpdate();
                }
            }, speed || 30);
            target[timerKey] = timer;
        },
        // 流式生成学习报告（SSE）
        async _streamReportGeneration(meetingId, userId) {
            const formData = new FormData();
            formData.append('meeting_id', meetingId);
            formData.append('user_id', userId);
            this.reportGenerating = true;
            this.reportProgress = '正在连接服务器...';

            try {
                const response = await fetch('/api/generate-report-stream', {
                    method: 'POST',
                    body: formData
                });

                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n');
                    buffer = lines.pop();

                    for (const line of lines) {
                        if (!line.startsWith('data: ')) continue;
                        const data = line.substring(6).trim();
                        if (data === '[DONE]') {
                            this.reportGenerating = false;
                            this.reportProgress = '';
                            return;
                        }
                        try {
                            const parsed = JSON.parse(data);
                            if (parsed.type === 'progress') {
                                this.reportProgress = parsed.message;
                            } else if (parsed.type === 'complete') {
                                this.reportProgress = '报告生成完毕！';
                                await this.loadMyReports({force: true});
                                await this.loadClassHistory({force: true});
                                // 自动跳转到学习报告标签
                                this.activeTab = 'report';
                                setTimeout(() => {
                                    this.reportGenerating = false;
                                    this.reportProgress = '';
                                }, 1500);
                            } else if (parsed.type === 'error') {
                                this.reportProgress = '生成失败: ' + parsed.message;
                                setTimeout(() => {
                                    this.reportGenerating = false;
                                    this.reportProgress = '';
                                }, 3000);
                            }
                        } catch (e) { /* ignore parse errors */ }
                    }
                }
            } catch (e) {
                console.error('报告流式生成失败:', e);
                this.reportProgress = '网络错误，请稍后重试';
                setTimeout(() => {
                    this.reportGenerating = false;
                    this.reportProgress = '';
                }, 3000);
            }
        },
        // 加载习题详情
        async loadExercises(reportId) {
            if (this.reportExercises[reportId]) return; // 已缓存
            try {
                const res = await axios.get(`/api/exercises/${reportId}`);
                if (res.data.status === 'success') {
                    this.$set(this.reportExercises, reportId, res.data.exercises);
                }
            } catch (e) {
                console.error('加载习题失败:', e);
            }
        },

        // ==================== 答题系统方法 ====================
        async startQuiz(reportId, title) {
            // 加载习题
            if (!this.reportExercises[reportId]) {
                await this.loadExercises(reportId);
            }
            const exercises = this.reportExercises[reportId];
            if (!exercises || exercises.length === 0) {
                this.showAlert('暂无习题', 'info', '提示');
                return;
            }
            this.quizReportId = reportId;
            this.quizTitle = title || '课堂习题';
            this.quizQuestions = exercises;
            this.quizCurrentIndex = 0;
            this.quizAnswers = {};
            this.quizResults = {};
            this.quizCorrectCount = 0;
            this.quizStreak = 0;
            this.quizMaxStreak = 0;
            this.quizShowFeedback = '';
            this.quizShowAnswer = false;
            this.quizShortAnswers = {};
            this.quizCompleted = false;
            this.quizEasterEgg = false;
            this.quizErrorSummary = null;
            this.quizErrorLoading = false;
            this.quizActive = true;
        },
        async exitQuiz() {
            if (!this.quizCompleted && Object.keys(this.quizResults).length > 0) {
                if (!await this.showConfirm('答题尚未完成，确认退出吗？', '确认退出')) return;
            }
            this.quizActive = false;
        },
        _getCorrectAnswerText(q) {
            if (!q.answer) return '未提供';
            const answer = q.answer.toString().trim();
            // 如果答案是 A/B/C/D 格式，返回对应选项
            if (q.options && q.options.length && /^[A-Da-d]/.test(answer)) {
                const idx = answer.charCodeAt(0) - (answer.charCodeAt(0) >= 97 ? 97 : 65);
                return q.options[idx] || answer;
            }
            return answer.length > 50 ? answer.substring(0, 50) + '...' : answer;
        },
        quizOptionText(opt) {
            // 移除开头的 "A. " "B. " 等前缀（因为我们已经单独显示了字母）
            return opt.replace(/^[A-Da-d][.、．:：\s]+/, '');
        },
        quizOptionClass(oi) {
            const idx = this.quizCurrentIndex;
            if (!this.quizResults[idx]) {
                return this.quizAnswers[idx] === oi ? 'selected' : '';
            }
            // 已作答
            if (this.quizIsCorrectOption(oi)) return 'show-correct';
            if (this.quizAnswers[idx] === oi && this.quizResults[idx] === 'wrong') return 'wrong';
            if (this.quizAnswers[idx] === oi && this.quizResults[idx] === 'correct') return 'correct';
            return '';
        },
        quizIsCorrectOption(oi) {
            const q = this.quizQuestions[this.quizCurrentIndex];
            if (!q || !q.answer) return false;
            const answer = q.answer.toString().trim();
            const letter = String.fromCharCode(65 + oi); // 0->A, 1->B, ...
            const answerUpper = answer.toUpperCase();

            // 1. 答案是纯字母 (A, B, C, D)
            if (/^[A-Da-d]$/.test(answer)) {
                return answerUpper === letter;
            }
            // 2. 答案以字母开头 (A. xxx, B、xxx)
            if (/^[A-Da-d][.、．:：\s]/.test(answer)) {
                return answerUpper.charAt(0) === letter;
            }
            // 3. 答案是选项全文，用规范化文本匹配
            if (q.options && q.options[oi]) {
                const normalize = s => s.replace(/^[A-Da-d][.、．:：\s]+/, '').replace(/\s+/g, '').toLowerCase();
                const normAnswer = normalize(answer);
                const normOption = normalize(q.options[oi]);
                if (normAnswer && normOption) {
                    return normAnswer === normOption || normOption.includes(normAnswer) || normAnswer.includes(normOption);
                }
            }
            return false;
        },
        quizGetCorrectLabel() {
            const q = this.quizQuestions[this.quizCurrentIndex];
            if (!q || !q.answer) return '';
            const answer = q.answer.toString().trim();
            if (q.options && q.options.length && /^[A-Da-d]/.test(answer)) {
                return answer.charAt(0).toUpperCase();
            }
            return answer.length > 80 ? answer.substring(0, 80) + '...' : answer;
        },
        quizSelectOption(oi) {
            const idx = this.quizCurrentIndex;
            if (this.quizResults[idx]) return; // 已作答
            this.$set(this.quizAnswers, idx, oi);
            // 判断对错
            const isCorrect = this.quizIsCorrectOption(oi);
            this.$set(this.quizResults, idx, isCorrect ? 'correct' : 'wrong');
            if (isCorrect) {
                this.quizCorrectCount++;
                this.quizStreak++;
                if (this.quizStreak > this.quizMaxStreak) this.quizMaxStreak = this.quizStreak;
                this.quizShowFeedback = 'correct';
                // 彩蛋检查
                if (this.quizStreak === 3) {
                    this.quizTriggerEasterEgg();
                }
                // 自动跳下一题
                setTimeout(() => {
                    if (this.quizShowFeedback === 'correct') {
                        this.quizShowFeedback = '';
                        if (this.quizCurrentIndex < this.quizQuestions.length - 1) {
                            this.quizNext();
                        } else if (Object.keys(this.quizResults).length === this.quizQuestions.length) {
                            this.quizFinish();
                        }
                    }
                }, 1200);
            } else {
                this.quizStreak = 0;
                this.quizShowFeedback = 'wrong';
                this.quizShowAnswer = true;
            }
            this.$forceUpdate();
            // 持久化答题记录
            this._saveQuizAnswer(idx, isCorrect ? 1 : 0);
        },
        quizSubmitShortAnswer() {
            const idx = this.quizCurrentIndex;
            const text = (this.quizShortAnswers[idx] || '').trim();
            if (!text) return;
            const q = this.quizQuestions[idx];

            // 显示加载状态
            this.$set(this.quizResults, idx, 'grading');
            this.quizShowFeedback = 'grading';
            this.$forceUpdate();

            // 调用大模型评分
            const formData = new FormData();
            formData.append('question', q.question || '');
            formData.append('correct_answer', q.answer || '');
            formData.append('student_answer', text);
            formData.append('question_type', q.question_type || '简答题');

            fetch('/api/grade-short-answer', { method: 'POST', body: formData })
                .then(r => r.json())
                .then(data => {
                    const isCorrect = data.is_correct;
                    const feedback = data.feedback || '';

                    if (isCorrect) {
                        this.$set(this.quizResults, idx, 'correct');
                        this.quizCorrectCount++;
                        this.quizStreak++;
                        if (this.quizStreak > this.quizMaxStreak) this.quizMaxStreak = this.quizStreak;
                        this.quizShowFeedback = 'correct';
                        if (this.quizStreak === 3) this.quizTriggerEasterEgg();
                    } else {
                        this.$set(this.quizResults, idx, 'wrong');
                        this.quizStreak = 0;
                        this.quizShowFeedback = 'wrong';
                    }
                    // 保存AI反馈到题目上
                    if (feedback) {
                        this.$set(q, 'ai_feedback', feedback);
                    }
                    this.quizShowAnswer = true;
                    this.$forceUpdate();
                    this._saveQuizAnswer(idx, isCorrect ? 1 : 0);

                    setTimeout(() => {
                        if (isCorrect && this.quizCurrentIndex < this.quizQuestions.length - 1) {
                            this.quizNext();
                        }
                    }, 1500);
                })
                .catch(err => {
                    console.error('AI评分失败:', err);
                    // 降级：标记为已完成
                    this.$set(this.quizResults, idx, 'correct');
                    this.quizShowFeedback = 'correct';
                    this.quizShowAnswer = true;
                    this.$forceUpdate();
                    this._saveQuizAnswer(idx, 1);
                });
        },
        quizPrev() {
            if (this.quizCurrentIndex > 0) {
                this.quizCurrentIndex--;
                this.quizShowAnswer = false;
                this.quizShowFeedback = '';
            }
        },
        quizNext() {
            if (this.quizCurrentIndex < this.quizQuestions.length - 1) {
                this.quizCurrentIndex++;
                this.quizShowAnswer = false;
                this.quizShowFeedback = '';
            }
        },
        quizGoTo(qi) {
            this.quizCurrentIndex = qi;
            this.quizShowAnswer = false;
            this.quizShowFeedback = '';
        },
        quizRetry() {
            const idx = this.quizCurrentIndex;
            if (this.quizResults[idx] === 'wrong') {
                this.quizCorrectCount = Math.max(0, this.quizCorrectCount);
                this.$delete(this.quizResults, idx);
                this.$delete(this.quizAnswers, idx);
                this.quizShowAnswer = false;
                this.quizShowFeedback = '';
                this.$forceUpdate();
            }
        },
        async quizFinish() {
            this.quizCompleted = true;
            this.quizShowFeedback = '';
            // 如果有错题，请求AI分析
            if (this.quizWrongQuestions.length > 0) {
                this.quizErrorLoading = true;
                try {
                    const wrongData = this.quizWrongQuestions.map(wq => ({
                        question: wq.question,
                        correctAnswer: wq.correctAnswer
                    }));
                    const formData = new FormData();
                    formData.append('wrong_questions', JSON.stringify(wrongData));
                    formData.append('topic', this.quizTitle);
                    const res = await axios.post('/api/quiz-error-analysis', formData);
                    if (res.data.status === 'success') {
                        this.quizErrorSummary = res.data.analysis;
                    }
                } catch (e) {
                    console.error('AI错题分析失败:', e);
                    this.quizErrorSummary = '分析请求失败，请稍后重试。';
                }
                this.quizErrorLoading = false;
            }
        },
        quizRestart() {
            this.quizCurrentIndex = 0;
            this.quizAnswers = {};
            this.quizResults = {};
            this.quizCorrectCount = 0;
            this.quizStreak = 0;
            this.quizMaxStreak = 0;
            this.quizShowFeedback = '';
            this.quizShowAnswer = false;
            this.quizShortAnswers = {};
            this.quizCompleted = false;
            this.quizEasterEgg = false;
            this.quizErrorSummary = null;
        },
        quizTriggerEasterEgg() {
            const eggs = [
                '知道吗？人类的大脑每天产生约7万个想法。看来你的大脑今天特别给力！',
                '据说连续答对3题的人，今晚做梦都会梦到满分试卷🌙',
                '你的知识储备量让AI都感到压力了😎',
                '传说答题连对3次的同学，会在考试中获得神秘加成✨',
                '学霸光环已开启！你的正确率让老师都想拜你为师📚',
            ];
            this.quizEasterEggText = eggs[Math.floor(Math.random() * eggs.length)];
            this.quizEasterEgg = true;
        },
        _saveQuizAnswer(questionIndex, isCorrect) {
            const q = this.quizQuestions[questionIndex];
            if (!q || !q.id || !this.currentUser) return;
            const answerContent = isCorrect
                ? (q.options ? q.options[this.quizAnswers[questionIndex]] : this.quizShortAnswers[questionIndex] || '')
                : (q.options ? q.options[this.quizAnswers[questionIndex]] : this.quizShortAnswers[questionIndex] || '');
            const formData = new FormData();
            formData.append('exercise_id', q.id);
            formData.append('user_id', this.currentUser.id);
            formData.append('answer_content', answerContent || '');
            formData.append('is_correct', isCorrect);
            axios.post('/api/submit-answer', formData).catch(e => console.warn('保存答题记录失败:', e));
        },
        _streamAIRequest(question, messagesArr, chatBoxRef, historyArr) {
            const formData = new FormData();
            formData.append('question', question);
            // 发送历史对话上下文
            const history = (historyArr || []).filter(m => m.role && m.content).map(m => ({role: m.role, content: m.content}));
            formData.append('history', JSON.stringify(history));

            // 创建AI消息占位
            const aiMsg = { role: 'assistant', content: '', streaming: true };
            messagesArr.push(aiMsg);

            const self = this;
            return new Promise((resolve) => {
                fetch('/api/ai-tutor-stream', {
                    method: 'POST',
                    body: formData
                }).then(response => {
                    const reader = response.body.getReader();
                    const decoder = new TextDecoder();
                    let buffer = '';

                    function read() {
                        reader.read().then(({ done, value }) => {
                            if (done) {
                                aiMsg.streaming = false;
                                self.$forceUpdate();
                                resolve();
                                return;
                            }
                            buffer += decoder.decode(value, { stream: true });
                            const lines = buffer.split('\n');
                            buffer = lines.pop() || '';

                            for (const line of lines) {
                                if (line.startsWith('data: ')) {
                                    const data = line.slice(6);
                                    if (data === '[DONE]') {
                                        aiMsg.streaming = false;
                                        self.$forceUpdate();
                                        resolve();
                                        return;
                                    }
                                    try {
                                        const token = JSON.parse(data);
                                        aiMsg.content += token;
                                        self.$forceUpdate();
                                        // 滚动到底部
                                        self.$nextTick(() => {
                                            const box = self.$refs[chatBoxRef];
                                            if (box) box.scrollTop = box.scrollHeight;
                                        });
                                    } catch(e) {}
                                }
                            }
                            read();
                        }).catch(() => {
                            aiMsg.streaming = false;
                            if (!aiMsg.content) aiMsg.content = '网络异常，请重试。';
                            self.$forceUpdate();
                            resolve();
                        });
                    }
                    read();
                }).catch(() => {
                    aiMsg.streaming = false;
                    aiMsg.content = '抱歉，系统出现错误，请稍后再试。';
                    self.$forceUpdate();
                    resolve();
                });
            });
        },
        // 发送AI消息(个人中心) - 流式
        async sendAIMessage() {
            if (!this.aiInput.trim() || this.aiLoading) return;

            const userMessage = this.aiInput.trim();
            this.aiMessages.push({ role: 'user', content: userMessage });
            this.aiInput = '';
            this.aiLoading = true;

            this.$nextTick(() => {
                if (this.$refs.aiChatBox) this.$refs.aiChatBox.scrollTop = this.$refs.aiChatBox.scrollHeight;
            });

            await this._streamAIRequest(userMessage, this.aiMessages, 'aiChatBox', this.aiMessages);

            this.aiLoading = false;
            this.$nextTick(() => {
                if (this.$refs.aiChatBox) this.$refs.aiChatBox.scrollTop = this.$refs.aiChatBox.scrollHeight;
            });
        },
        // 发送课堂AI消息 - 流式
        async sendClassroomAIMessage() {
            if (!this.classroomAIInput.trim() || this.classroomAILoading) return;

            const userMessage = this.classroomAIInput.trim();
            this.classroomAIMessages.push({ role: 'user', content: userMessage });
            this.classroomAIInput = '';
            this.classroomAILoading = true;

            this.$nextTick(() => {
                if (this.$refs.classroomAIChatBox) this.$refs.classroomAIChatBox.scrollTop = this.$refs.classroomAIChatBox.scrollHeight;
            });

            await this._streamAIRequest(userMessage, this.classroomAIMessages, 'classroomAIChatBox', this.classroomAIMessages);

            this.classroomAILoading = false;
            this.$nextTick(() => {
                if (this.$refs.classroomAIChatBox) this.$refs.classroomAIChatBox.scrollTop = this.$refs.classroomAIChatBox.scrollHeight;
            });
        },
        // 返回主界面
        backToLobby() {
            // 清理定时器
            if (this.emotionRefreshTimer) {
                clearInterval(this.emotionRefreshTimer);
                this.emotionRefreshTimer = null;
            }

            // 停止WebSocket和录音
            if (this.ws) this.ws.close();
            if (this.asrWs) { this.asrWs._manualClose = true; this.asrWs.close(); this.asrWs = null; }
            this.stopBrowserSpeechRecognition();
            if (this.asrReconnectTimer) {
                clearTimeout(this.asrReconnectTimer);
                this.asrReconnectTimer = null;
            }
            if (this.asrHealthTimer) {
                clearTimeout(this.asrHealthTimer);
                this.asrHealthTimer = null;
            }
            this.cleanupWebRtcAll();
            if (this.recorder) this.recorder.stop();
            if (this.timerInterval) clearInterval(this.timerInterval);
            if (this.graphUpdateInterval) clearInterval(this.graphUpdateInterval);
            if (this.analyzingCleanupInterval) clearInterval(this.analyzingCleanupInterval);

            // 停止沉默检测定时器
            this.stopSilenceChecks();

            // 停止实时音频处理节点
            if (this.audioProcessor) {
                this.audioProcessor.disconnect();
                this.audioProcessor = null;
            }
            if (this.audioSource) {
                this.audioSource.disconnect();
                this.audioSource = null;
            }

            // 停止摄像头
            const videoEl = Array.isArray(this.$refs.video) ? this.$refs.video[0] : this.$refs.video;
            if (videoEl && videoEl.srcObject) {
                videoEl.srcObject.getTracks().forEach(track => track.stop());
                videoEl.srcObject = null;
            }
            this.localMediaStream = null;

            // 停止 Agora 本地轨道（关闭摄像头/麦克风）
            if (this.agoraLocalVideoTrack) {
                this.agoraLocalVideoTrack.stop();
                this.agoraLocalVideoTrack.close();
                this.agoraLocalVideoTrack = null;
            }
            if (this.agoraLocalAudioTrack) {
                this.agoraLocalAudioTrack.stop();
                this.agoraLocalAudioTrack.close();
                this.agoraLocalAudioTrack = null;
            }
            this._leaveAgoraChannel();
            this.agoraRemoteUsers = {};

            // 停止音频上下文
            if (this.audioCtx) {
                this.audioCtx.close();
                this.audioCtx = null;
            }

            // 清理图表实例
            if (this.chartInstances.pieChart) {
                this.chartInstances.pieChart.dispose();
                this.chartInstances.pieChart = null;
            }
            if (this.chartInstances.barChart) {
                this.chartInstances.barChart.dispose();
                this.chartInstances.barChart = null;
            }
            if (this.chartInstances.groupEmotionChart) {
                this.chartInstances.groupEmotionChart.dispose();
                this.chartInstances.groupEmotionChart = null;
            }
            if (this.chartInstances.individualEmotionChart) {
                this.chartInstances.individualEmotionChart.dispose();
                this.chartInstances.individualEmotionChart = null;
            }

            // 重置课堂状态
            this.pageState = 'lobby';
            this.classroomTab = 'chat';
            this.joined = false;
            this.msgs = [];
            this.goals = [];
            this.currentRelevance = 0;
            this.hint = null;
            this.topicSuggestion.show = false;
            this.classroomAIMessages = [];
            this.classroomAIInput = '';

            // 清理统计数据
            this.pieChartData = [];
            this.interactionData = [];
            this.groupEmotions = {};
            this.individualEmotions = {};
            this.selectedMember = null;

            if (this.currentUser && this.currentUser.role === 'student') {
                this.loadStudentHomeStats();
                this.loadClassHistory({force: true});
                this.loadMyReports({force: true}).catch(() => {});
            } else if (this.currentUser && this.currentUser.role === 'teacher') {
                this.loadActiveGroups();
                this.loadTeacherStats();
                this.loadTeacherClasses();
                this.loadAllStudentReports({force: true});
            }
        },
        // 下课（教师+学生统一入口）
        async endClass() {
            if (this.currentUser.role === 'teacher') {
                if (!await this.showConfirm('确定要结束本次课堂吗？所有学生将被断开连接。', '结束课堂')) return;
                try {
                    const fd = new FormData();
                    fd.append('meeting_id', this.meetingId);
                    fd.append('username', this.currentUser.student_id);
                    const res = await axios.post('/api/end-class', fd);
                    if (res.data.status === 'success') {
                        this.showAlert('课堂已结束', 'success', '提示');
                    } else {
                        this.showAlert(res.data.message || '结束课堂失败', 'error', '错误');
                    }
                } catch (e) {
                    this.showAlert('结束课堂失败: ' + (e.message || e), 'error', '错误');
                }
                this._cleanupClassroom();
                this.backToLobby();
            } else {
                // 学生下课
                if (!await this.showConfirm('确认下课吗？', '确认下课')) return;
                const meetingId = this.meetingId;
                const userId = this.currentUser.id;

                const formData = new FormData();
                formData.append('meeting_id', meetingId);
                formData.append('user_id', userId);

                // 先清理资源再回首页
                this._cleanupClassroom();
                this.loading = false;
                this.backToLobby();

                // 延迟生成学习报告
                const START_DELAY_MS = 15000;
                console.log(`⏳ 下课后 ${START_DELAY_MS}ms 延迟生成学习报告...`);
                this.reportGenerating = true;
                this.reportProgress = '等待最后的发言入库...';
                setTimeout(() => {
                    this._streamReportGeneration(meetingId, userId);
                }, START_DELAY_MS);
            }
        },
        // 格式化时间戳
        formatTime(timestamp) {
            if (!timestamp) return new Date().toLocaleTimeString();
            const date = new Date(timestamp);
            return date.toLocaleTimeString();
        },
        // 获取下一步建议
        getNextStepSuggestion() {
            const pendingGoals = this.goals.filter(g => g.status === 'pending');
            const doneGoals = this.goals.filter(g => g.status === 'done');
            
            if (pendingGoals.length === 0) {
                return '所有目标已完成!可以总结课程并布置练习题。';
            }
            
            if (doneGoals.length === 0) {
                return `建议先从第一个目标开始: ${pendingGoals[0].desc}。可以通过案例分析或小组讨论的方式引导学生。`;
            }
            
            return `已完成${doneGoals.length}个目标,接下来关注: ${pendingGoals[0].desc}。建议结合已学知识进行递进式教学。`;
        },
        // 沉默检测和话题建议
        startSilenceChecks() {
            // 每30秒检查一次全组沉默
            this.silenceCheckTimer = setInterval(async () => {
                if (!this.meetingId || !this.joined) return;
                try {
                    const fd = new FormData();
                    fd.append('meeting_id', this.meetingId);
                    await axios.post('/api/check-silence', fd);
                } catch(e) { /* 静默失败 */ }
            }, 30000);

            // 每60秒检查一次沉默成员
            this.quietCheckTimer = setInterval(async () => {
                if (!this.meetingId || !this.joined) return;
                try {
                    const fd = new FormData();
                    fd.append('meeting_id', this.meetingId);
                    await axios.post('/api/check-quiet-members', fd);
                } catch(e) { /* 静默失败 */ }
            }, 60000);
        },
        stopSilenceChecks() {
            if (this.silenceCheckTimer) { clearInterval(this.silenceCheckTimer); this.silenceCheckTimer = null; }
            if (this.quietCheckTimer) { clearInterval(this.quietCheckTimer); this.quietCheckTimer = null; }
        },
        async loadStudentHomeStats() {
            if (!this.currentUser || this.currentUser.role !== 'student') return;
            try {
                const res = await axios.get(`/api/student-home-stats/${this.currentUser.id}`);
                if (res.data.status === 'success') {
                    this.studentHomeSummary = res.data.stats || {
                        activeClasses: 0,
                        completedClasses: 0,
                        studyHours: '0.0'
                    };
                }
            } catch(e) {
                console.error('加载学生首页统计失败:', e);
            }
        },
        lobbyCacheKey(name) {
            return this.currentUser ? `ai-study:${name}:${this.currentUser.id}` : '';
        },
        readLobbyCache(name, fallback) {
            try {
                const key = this.lobbyCacheKey(name);
                if (!key) return fallback;
                const raw = localStorage.getItem(key);
                return raw ? JSON.parse(raw) : fallback;
            } catch(e) {
                return fallback;
            }
        },
        writeLobbyCache(name, value) {
            try {
                const key = this.lobbyCacheKey(name);
                if (key) localStorage.setItem(key, JSON.stringify(value || []));
            } catch(e) {}
        },
        hydrateLobbyCache() {
            const cachedHistory = this.readLobbyCache('classHistory', []);
            if (Array.isArray(cachedHistory) && cachedHistory.length) {
                this.classHistory = cachedHistory;
                this.historyLoaded = true;
            }
            const cachedReports = this.readLobbyCache('myReports', []);
            if (Array.isArray(cachedReports) && cachedReports.length) {
                this.myReports = cachedReports;
                this.reportsLoaded = true;
            }
            const cachedStudentReports = this.readLobbyCache('allStudentReports', []);
            if (Array.isArray(cachedStudentReports) && cachedStudentReports.length) {
                this.allStudentReports = cachedStudentReports;
                this.studentReportsLoaded = true;
            }
        },
        async ensureMyReports() {
            if (this.reportsLoaded || this.reportsLoading) return;
            return this.loadMyReports();
        },
        async ensureClassHistory() {
            if (this.historyLoaded || this.historyLoading) return;
            return this.loadClassHistory();
        },
        async ensureAllStudentReports() {
            if (this.studentReportsLoaded || this.studentReportsLoading) return;
            return this.loadAllStudentReports();
        },
        async loadMyReports(options = {}) {
            if (!this.currentUser) {
                console.log('⚠️ 未登录,无法加载报告');
                return;
            }
            if (!options.force && this.reportsLoaded) return;
            if (this.reportsLoading) return;
            this.reportsLoading = true;
            try {
                console.log(`🔄 正在加载用户 ${this.currentUser.id} 的报告...`);
                const res = await axios.get(`/api/reports/${this.currentUser.id}`);
                console.log('📦 API返回:', res.data);
                
                if (res.data.status === 'success') {
                    this.myReports = res.data.reports || [];
                    this.reportsLoaded = true;
                    this.writeLobbyCache('myReports', this.myReports);
                    console.log(`✅ 成功加载 ${this.myReports.length} 份报告`);
                    if (this.myReports.length > 0) {
                        console.log('📊 第一份报告详情:', this.myReports[0]);
                    }
                } else {
                    console.error('❌ 返回状态错误:', res.data);
                }
            } catch(e) {
                console.error('❌ 加载报告失败:', e);
                console.error('错误详情:', e.response?.data);
                if (options.force) this.showAlert('加载学习报告失败: ' + (e.response?.data?.message || e.message), 'error', '错误');
            } finally {
                this.reportsLoading = false;
            }
        },
        // 下载PDF报告
        async downloadReportPDF(meeting_id, user_id) {
            try {
                console.log(`📝 开始生成PDF: meeting_id=${meeting_id}, user_id=${user_id}`);
                this.loading = true;
                
                const formData = new FormData();
                formData.append('meeting_id', meeting_id);
                formData.append('user_id', user_id);
                
                const res = await axios.post('/api/generate-pdf-report', formData);
                console.log('📎 PDF生成响应:', res.data);
                
                if (res.data.status === 'success') {
                    // 直接打开PDF下载链接
                    const pdfUrl = res.data.pdf_url;
                    window.open(pdfUrl, '_blank');
                    console.log('✅ PDF下载开始:', pdfUrl);
                } else {
                    this.showAlert('PDF生成失败: ' + res.data.message, 'error', '错误');
                }
            } catch(e) {
                console.error('❌ PDF生成错误:', e);
                this.showAlert('PDF生成失败: ' + (e.response?.data?.message || e.message), 'error', '错误');
            } finally {
                this.loading = false;
            }
        },
        // 教师查看小组所有成员报告
        async viewGroupReports(meeting_id) {
            try {
                console.log(`📊 查看小组报告, meeting_id=${meeting_id}`);
                this.loading = true;
                
                const res = await axios.get(`/api/meeting-reports/${meeting_id}`);
                console.log('📦 小组报告响应:', res.data);
                
                if (res.data.status === 'success') {
                    this.groupReports = res.data.reports;
                    this.currentViewingMeetingId = meeting_id;
                    this.viewingGroupReports = true;
                    console.log(`✅ 加载了 ${this.groupReports.length} 份报告`);
                } else {
                    this.showAlert('加载失败: ' + res.data.message, 'error', '错误');
                }
            } catch(e) {
                console.error('❌ 加载小组报告错误:', e);
                this.showAlert('加载失败: ' + (e.response?.data?.message || e.message), 'error', '错误');
            } finally {
                this.loading = false;
            }
        },
        // 关闭小组报告查看
        closeGroupReports() {
            this.viewingGroupReports = false;
            this.groupReports = [];
            this.currentViewingMeetingId = null;
        },
        // AI 快速任务分解（一步到位，跳过聚类投票）
        async quickDecompose() {
            if (!this.meetingId) {
                this.showAlert('课堂未开始', 'warning', '提示');
                return;
            }
            this.viewpointLoading = true;
            try {
                const formData = new FormData();
                formData.append('meeting_id', this.meetingId);
                const res = await axios.post('/api/quick-decompose', formData);
                if (res.data.status === 'success') {
                    this.goals = res.data.updated_goals || [];
                    this.subGoals = res.data.sub_goals || [];
                    this.subGoalGuidance = res.data.guidance || '';
                    this.hint = '🎯 AI 已分解任务：' + (res.data.main_viewpoint || '');
                } else {
                    this.showAlert(res.data.message || '分解失败', 'warning', '提示');
                }
            } catch(e) {
                this.showAlert('任务分解失败: ' + (e.response?.data?.message || e.message), 'error', '错误');
            }
            this.viewpointLoading = false;
        },
        // 观点聚类
        async clusterViewpoints() {
            if (!this.meetingId) {
                this.showAlert('课堂未开始', 'warning', '提示');
                return;
            }
            this.viewpointLoading = true;
            try {
                const formData = new FormData();
                formData.append('meeting_id', this.meetingId);
                console.log('📤 发起观点聚类请求, meeting_id:', this.meetingId);
                const res = await axios.post('/api/cluster-viewpoints', formData);
                console.log('📥 观点聚类响应:', res.data);
                if (res.data.status === 'success') {
                    this.currentVoteId = res.data.vote_id;
                    console.log('✅ 观点聚类已发起');
                } else {
                    this.showAlert('观点聚类失败: ' + (res.data.message || '未知错误'), 'error', '错误');
                }
            } catch(e) {
                console.error('观点聚类错误:', e);
                this.showAlert('观点聚类请求失败: ' + (e.response?.data?.message || e.message), 'error', '错误');
            }
            this.viewpointLoading = false;
        },
        // 投票
        async castVote(vp) {
            if (!this.currentVoteId) return;
            this.myVote = vp.id;
            try {
                const formData = new FormData();
                formData.append('vote_id', this.currentVoteId);
                formData.append('viewpoint_id', vp.id);
                formData.append('username', this.currentUser.username);
                formData.append('meeting_id', this.meetingId);
                const res = await axios.post('/api/cast-vote', formData);
                if (res.data.status === 'success') {
                    console.log('✅ 投票成功');
                }
            } catch(e) {
                console.error('投票错误:', e.message);
            }
        },
        // 结束投票(教师或达到条件时)
        async closeVote() {
            if (!this.currentVoteId) return;
            try {
                const formData = new FormData();
                formData.append('vote_id', this.currentVoteId);
                formData.append('meeting_id', this.meetingId);
                const res = await axios.post('/api/close-vote', formData);
                if (res.data.status === 'success') {
                    console.log('✅ 投票结束');
                }
            } catch(e) {
                console.error('结束投票错误:', e.message);
            }
        },
        // 确认观点选择完毕
        async confirmVote() {
            if (!this.currentVoteId || !this.myVote) return;
            try {
                const formData = new FormData();
                formData.append('vote_id', this.currentVoteId);
                formData.append('username', this.currentUser.username);
                formData.append('meeting_id', this.meetingId);
                const res = await axios.post('/api/confirm-vote', formData);
                if (res.data.status === 'success') {
                    this.voteConfirmed = true;
                    console.log('✅ 已确认选择');
                }
            } catch(e) {
                console.error('确认选择错误:', e.message);
            }
        },
        // 选择观点生成子目标(兼容旧版)
        async selectViewpoint(vp) {
            this.castVote(vp);
        },
        scheduleRealtimeDataRefresh(delay = 500) {
            if (this.realtimeDataRefreshTimer) {
                clearTimeout(this.realtimeDataRefreshTimer);
            }
            this.realtimeDataRefreshTimer = setTimeout(() => {
                this.realtimeDataRefreshTimer = null;
                this.loadRealtimeStats();
            }, delay);
        },
        // 加载实时统计
        async loadRealtimeStats() {
            if (!this.meetingId) return;
            
            // 防抖：如果正在加载，直接返回
            if (this.loadingStats) {
                console.log('⏭️ 跳过统计加载（上一次请求未完成）');
                this.loadEmotionDetails();
                return;
            }
            this.loadingStats = true;
            
            try {
                console.log('📊 加载实时统计数据...');
                
                // ✅ 取消之前的统计请求（如果存在）
                if (this.statsRequestController) {
                    console.log('🚫 取消之前的统计请求...');
                    this.statsRequestController.abort();
                }
                
                // ✅ 创建新的AbortController
                this.statsRequestController = new AbortController();
                
                const res = await axios.get(`/api/realtime-stats/${this.meetingId}`, {
                    timeout: 120000,  // 120秒超时
                    signal: this.statsRequestController.signal  // ✅ 绑定取消信号
                });
                console.log('📊 统计数据API返回:', res.data);
                
                if (res.data.status === 'success') {
                    this.pieChartData = res.data.pie_data;
                    this.interactionData = res.data.interaction;
                    this.emotionTimeline = res.data.emotion_timeline;
                    this.memberScores = res.data.member_scores || [];
                    
                    console.log('✅ 统计数据加载成功:');
                    console.log('  - 说话次数数据:', this.pieChartData?.length || 0, '个成员');
                    console.log('  - 交互关系:', this.interactionData?.nodes?.length || 0, '个节点');
                    console.log('  - 成员评分:', this.memberScores?.length || 0, '人');
                    
                    // ✅ 关键修改：延迟渲染以确保DOM存在（v-if切换需要更多时间）
                    this.$nextTick(() => {
                        setTimeout(() => {
                            console.log('🎨 开始渲染统计图表...');
                            this.renderStatsCharts();
                        }, 300);
                    });
                }
            } catch(e) {
                // ✅ 如果是被取消的请求，不显示错误
                if (e.name === 'AbortError' || e.code === 'ERR_CANCELED') {
                    console.log('⚠️ 统计请求已被取消（优先级低于视频请求）');
                    return;  // 静默失败，不弹窗
                }
                
                console.error('加载统计失败:', e);
                // 统一兜底重试：非取消类错误都在10秒后重试，避免界面长期空白
                console.warn('⏱️ 统计请求失败，10秒后自动重试...');
                setTimeout(() => this.loadRealtimeStats(), 10000);
            } finally {
                this.loadingStats = false;  // 释放锁
            }
            // 同时加载情绪数据
            this.loadEmotionDetails();
            
            // === 添加定时刷新机制 ===
            // ✅ 每30秒刷新一次统计数据（减少频率以避免连接池耗尽）
            if (this.statsRefreshTimer) clearInterval(this.statsRefreshTimer);
            this.statsRefreshTimer = setInterval(async () => {
                // ✅ 只在统计页面时刷新
                if (this.classroomTab === 'stats') {
                    await this.loadRealtimeStats();  // 使用防抖版本
                }
            }, 30000);  // 30秒
            
            // ✅ 每30秒刷新一次情绪数据（减少频率）
            if (this.emotionRefreshTimer) clearInterval(this.emotionRefreshTimer);
            this.emotionRefreshTimer = setInterval(() => {
                // 不管在哪个tab都刷新情绪数据，保证所有人都有实时数据
                this.loadEmotionDetails();
            }, 30000);  // 30秒
        },
        // 新增: 加载情绪详情
        async loadEmotionDetails() {
            if (!this.meetingId) return;
            
            // 防抖：如果正在加载，直接返回
            if (this.loadingEmotions) {
                console.log('⏭️ 跳过情绪加载（上一次请求未完成）');
                return;
            }
            this.loadingEmotions = true;
            
            try {
                // ✅ 取消之前的情绪请求（如果存在）
                if (this.emotionRequestController) {
                    console.log('🚫 取消之前的情绪请求...');
                    this.emotionRequestController.abort();
                }
                
                // ✅ 创建新的AbortController
                this.emotionRequestController = new AbortController();
                
                // 学生端只返回自己的个体情绪；教师端返回全员个体情绪
                let emotionUrl = `/api/emotion-details/${this.meetingId}?minutes=0`;
                if (this.currentUser && this.currentUser.role === 'student' && this.currentUser.username) {
                    emotionUrl += `&username=${encodeURIComponent(this.currentUser.username)}`;
                }
                const res = await axios.get(emotionUrl, {
                    timeout: 120000,  // 120秒超时
                    signal: this.emotionRequestController.signal  // ✅ 绑定取消信号
                });
                console.log('📊 情绪数据API返回:', res.data);
                
                if (res.data.status === 'success') {
                    // 个体图表用过滤后的数据（学生端只有自己）
                    this.individualEmotions = res.data.individual_emotions || {};
                    // 群体图表用完整数据（所有成员）
                    this.allIndividualEmotions = res.data.all_individual_emotions || this.individualEmotions;

                    if (
                        this.currentUser &&
                        this.currentUser.role === 'student' &&
                        Object.keys(this.individualEmotions).length === 0 &&
                        Object.keys(this.allIndividualEmotions || {}).length > 0
                    ) {
                        const ownCandidates = [
                            this.currentUser.username,
                            this.currentUser.student_id,
                            this.currentUser.name
                        ].filter(Boolean).map(String);
                        const allKeys = Object.keys(this.allIndividualEmotions);
                        const matchedKey = res.data.current_user_key || allKeys.find(key => ownCandidates.includes(String(key)));
                        if (matchedKey && this.allIndividualEmotions[matchedKey]) {
                            this.individualEmotions = { [matchedKey]: this.allIndividualEmotions[matchedKey] };
                        } else if (allKeys.length === 1) {
                            this.individualEmotions = { [allKeys[0]]: this.allIndividualEmotions[allKeys[0]] };
                        }
                    }

                    // 限制内存中的数据点数量，只保留最近200个
                    const MAX_EMOTION_POINTS = 200;
                    Object.keys(this.individualEmotions).forEach(member => {
                        if (this.individualEmotions[member].length > MAX_EMOTION_POINTS) {
                            this.individualEmotions[member] = this.individualEmotions[member].slice(-MAX_EMOTION_POINTS);
                        }
                    });
                    Object.keys(this.allIndividualEmotions).forEach(member => {
                        if (this.allIndividualEmotions[member].length > MAX_EMOTION_POINTS) {
                            this.allIndividualEmotions[member] = this.allIndividualEmotions[member].slice(-MAX_EMOTION_POINTS);
                        }
                    });
                    this.groupEmotionTimeline = res.data.group_emotion_timeline;
                    if (this.groupEmotionTimeline.length > MAX_EMOTION_POINTS) {
                        this.groupEmotionTimeline = this.groupEmotionTimeline.slice(-MAX_EMOTION_POINTS);
                    }
                    this.videoSegments = res.data.video_segments;
                    
                    // 详细日志
                    console.log('✅ 情绪数据加载成功:');
                    console.log('  - 个体情绪数据:', Object.keys(this.individualEmotions).length, '个成员');
                    console.log('  - 群体情绪数据点:', this.groupEmotionTimeline.length, '个');
                    console.log('  - 视频片段:', this.videoSegments.length, '个');
                    
                    // 如果没有数据，给出提示
                    if (Object.keys(this.individualEmotions).length === 0 && this.groupEmotionTimeline.length === 0) {
                        console.warn('⚠️ 没有情绪数据！请确保：');
                        console.warn('  1. 已经开始说话（情绪记录在说话时保存）');
                        console.warn('  2. 摄像头正常工作（需要捕获人脸表情）');
                        console.warn('  3. 等待几秒后刷新统计页面');
                    }
                    
                    // 选中成员策略：
                    // - 学生：始终选中自己，避免显示到别人曲线
                    // - 教师：首次默认第一个成员
                    const members = Object.keys(this.individualEmotions);
                    if (this.currentUser && this.currentUser.role === 'student' && this.currentUser.username) {
                        const ownCandidates = [
                            res.data.current_user_key,
                            this.currentUser.username,
                            this.currentUser.student_id,
                            this.currentUser.name
                        ].filter(Boolean).map(String);
                        const matchedMember = members.find(member => ownCandidates.includes(String(member)));
                        if (matchedMember) {
                            this.selectedMember = matchedMember;
                        } else if (members.length > 0) {
                            this.selectedMember = members[0];
                        } else {
                            this.selectedMember = null;
                        }
                        console.log('🎯 学生端选中成员:', this.selectedMember);
                    } else if (!this.selectedMember && members.length > 0) {
                        this.selectedMember = members[0];
                        console.log('🎯 自动选择成员:', this.selectedMember);
                    }
                    // 渲染图表（延迟以确保DOM已更新）
                    this.$nextTick(() => {
                        setTimeout(() => {
                            console.log('🎨 开始渲染情绪图表...');
                            // 无论在哪个标签页都尝试渲染，图表方法内部会检查容器是否存在
                            this.renderIndividualEmotionChart();
                            this.renderGroupEmotionChart();
                        }, 100);
                    });
                }
            } catch(e) {
                // ✅ 如果是被取消的请求，不显示错误
                if (e.name === 'AbortError' || e.code === 'ERR_CANCELED') {
                    console.log('⚠️ 情绪请求已被取消（优先级低于视频请求）');
                    return;  // 静默失败，不弹窗
                }
                
                console.error('❌ 加载情绪数据失败:', e);
                console.error('  错误详情:', e.response?.data || e.message);
                // 如果是超时，静默重试一次
                if (e.code === 'ECONNABORTED' || e.message.includes('timeout')) {
                    console.warn('⏱️ 请求超时，10秒后静默重试...');
                    setTimeout(() => this.loadEmotionDetails(), 10000);  // 10秒后重试
                }
            } finally {
                this.loadingEmotions = false;  // 释放锁
            }
        },
        // 切换情绪模式
        switchEmotionMode(mode) {
            this.emotionMode = mode;
            if (mode === 'individual') {
                if (this.currentUser && this.currentUser.role === 'student' && this.currentUser.username) {
                    const ownCandidates = [
                        this.currentUser.username,
                        this.currentUser.student_id,
                        this.currentUser.name
                    ].filter(Boolean).map(String);
                    const matchedMember = Object.keys(this.individualEmotions || {}).find(member => ownCandidates.includes(String(member)));
                    if (matchedMember) {
                        this.selectedMember = matchedMember;
                    }
                } else if (!this.selectedMember && Object.keys(this.individualEmotions).length > 0) {
                    this.selectedMember = Object.keys(this.individualEmotions)[0];
                }
            }
            this.$nextTick(() => this.renderEmotionCharts());
        },
        // 选择成员
        selectMember(member) {
            this.selectedMember = member;
            this.$nextTick(() => this.renderEmotionCharts());
        },
        // 根据时间戳显示快照图片或视频片段（直接弹窗）
        async showSnapshotAtTime(memberName, timestamp) {
            try {
                console.log('🎬 查询视频片段, 成员:', memberName, ', 时间戳:', timestamp);
                
                // ✅ 视频请求是最高优先级，取消所有低优先级请求
                if (this.statsRequestController) {
                    console.log('🚨 取消统计请求（视频请求抢占）');
                    this.statsRequestController.abort();
                }
                if (this.emotionRequestController) {
                    console.log('🚨 取消情绪请求（视频请求抢占）');
                    this.emotionRequestController.abort();
                }
                
                // ✅ 取消之前的视频查询请求（如果存在）
                if (this.videoRequestController) {
                    console.log('🚫 取消之前的视频请求...');
                    this.videoRequestController.abort();
                }
                
                // ✅ 创建新的AbortController
                this.videoRequestController = new AbortController();
                
                // ✅ 立即打开弹窗（显示加载状态）
                this.videoPlayer = {
                    visible: true,
                    url: '',  // 先留空，等待API返回
                    startTime: 0,
                    loading: true
                };
                
                const user_id = this.currentUser.id;
                
                console.log('🔍 开始调用API...', { meeting_id: this.meetingId, user_id, timestamp });
                const startTime = Date.now();
                
                // 调用视频上下文API
                const res = await axios.get(`/api/get-video-context`, {
                    params: { 
                        meeting_id: this.meetingId,
                        user_id: user_id,      // 兼容旧接口
                        username: memberName,  // 优先按被点击成员查询
                        timestamp: timestamp 
                    },
                    timeout: 10000,  // ✅ 10秒超时
                    signal: this.videoRequestController.signal  // ✅ 绑定取消信号
                });
                
                const elapsed = Date.now() - startTime;
                console.log(`✅ API返回成功，耗时: ${elapsed}ms`);
                
                if (res.data.status === 'success') {
                    console.log('✅ 找到视频:', res.data.video_url);
                    
                    // ✅ 更新URL并立即初始化
                    this.videoPlayer.url = res.data.video_url;
                    this.videoPlayer.startTime = res.data.jump_to_time || 0;
                    
                    // 等待视频元素加载
                    this.$nextTick(() => {
                        this.initVideoPlayer();
                    });
                } else {
                    console.warn('⚠️ 未找到视频:', res.data.message);
                    this.videoPlayer.loading = false;
                    this.videoPlayer.visible = false;
                    this.showAlert('该时间点暂无视频记录', 'info', '提示');
                }
            } catch (e) {
                // ✅ 如果是被取消的请求，不显示错误
                if (e.name === 'AbortError' || e.code === 'ERR_CANCELED') {
                    console.log('⚠️ 请求已被取消（用户发起了新请求）');
                    return;  // 静默失败，不弹窗
                }

                console.error('❌ 查询视频失败:', e);
                console.error('  错误详情:', e.response?.data || e.message);
                console.error('  错误类型:', e.code);
                this.videoPlayer.loading = false;
                this.videoPlayer.visible = false;

                if (e.code === 'ECONNABORTED') {
                    this.showAlert('视频查询超时10秒，请检查网络或稍后重试', 'error', '错误');
                } else {
                    this.showAlert('加载失败，请重试', 'error', '错误');
                }
            }
        },
        // 关闭悬浮卡片
        closeHoverCard() {
            this.hoverCard.visible = false;
        },
        // 用户确认查看视频
        confirmViewVideo() {
            const { video_url, jump_to_time } = this.hoverCard.data;
            
            console.log('🎬 打开视频播放器:', { video_url, jump_to_time });
            
            // 打开视频播放器模态框
            this.videoPlayer = {
                visible: true,
                url: video_url,
                startTime: jump_to_time,
                loading: true
            };
            
            // 关闭悬浮卡片
            this.closeHoverCard();
            
            // 等待视频元素加载后跳转
            this.$nextTick(() => {
                this.initVideoPlayer();
            });
        },
        // 初始化视频播放器（秒开核心优化版）
        initVideoPlayer() {
            const video = document.getElementById('emotionVideoPlayer');
            if (!video) {
                console.error('❌ 视频元素不存在');
                return;
            }
            
            console.log('🎞️ 初始化视频播放器, URL:', this.videoPlayer.url);
            
            // ✅ 检查URL是否为空
            if (!this.videoPlayer.url) {
                console.error('❌ 视频URL为空！');
                this.videoPlayer.loading = false;
                setTimeout(() => {
                    this.closeVideoPlayer();
                }, 2000);
                return;
            }
            
            // ✅ 关键优化：设置 preload 为 auto（主动缓冲）
            video.preload = 'auto';
            video.src = this.videoPlayer.url;
            console.log('📹 已设置video.src:', video.src);
            
            // ✅ 加速加载：立即调用 load()
            video.load();
            
            // 监听元数据加载完成
            video.onloadedmetadata = () => {
                console.log(`✅ 视频元数据加载完成, 总时长: ${video.duration}秒`);
                
                // 🚀 核心：跳转到目标时间（浏览器自动发送Range请求）
                if (this.videoPlayer.startTime > 0) {
                    video.currentTime = this.videoPlayer.startTime;
                    console.log(`⏩ 跳转到 ${this.videoPlayer.startTime} 秒`);
                } else {
                    // 无需跳转，直接播放
                    this.videoPlayer.loading = false;
                    video.play().catch(e => {
                        console.warn('自动播放被阻止，用户需手动点击', e);
                        this.videoPlayer.loading = false;
                    });
                }
            };
            
            // ✅ 可以播放部分数据时立即开始
            video.oncanplay = () => {
                console.log('✅ 视频可以播放，关闭加载提示');
                this.videoPlayer.loading = false;
            };
            
            // 监听跳转完成
            video.onseeked = () => {
                console.log('✅ 时间跳转完成，开始播放');
                this.videoPlayer.loading = false;
                
                // 自动播放
                video.play().catch(e => {
                    console.warn('自动播放被阻止，用户需手动点击', e);
                    this.videoPlayer.loading = false;
                });
            };
            
            // 错误处理
            video.onerror = (e) => {
                console.error('❌ 视频加载错误:', video.error);
                this.videoPlayer.loading = false;
                
                let errorMsg = '视频加载失败';
                if (video.error) {
                    switch(video.error.code) {
                        case 1: errorMsg = '视频加载被中止'; break;
                        case 2: errorMsg = '网络错误，请检查网络连接'; break;
                        case 3: errorMsg = '视频解码错误'; break;
                        case 4: errorMsg = '视频格式不支持或文件不存在'; break;
                    }
                }
                
                // ✅ 不弹窗，直接在播放器内显示错误
                console.error(`❌ ${errorMsg} (错误代码: ${video.error?.code})`);
                
                // ✅ 2秒后自动关闭播放器
                setTimeout(() => {
                    this.closeVideoPlayer();
                }, 2000);
            };
            
            // ✅ 加载进度监听（调试用）
            video.onprogress = () => {
                if (video.buffered.length > 0) {
                    const bufferedEnd = video.buffered.end(video.buffered.length - 1);
                    const percent = (bufferedEnd / video.duration * 100).toFixed(0);
                    console.log(`📶 已缓冲: ${bufferedEnd.toFixed(2)}秒 (${percent}%)`);
                }
            };
        },
        // 关闭视频播放器（安全版）
        closeVideoPlayer() {
            console.log('🛝 关闭视频播放器');
            const video = document.getElementById('emotionVideoPlayer');
            if (video) {
                try {
                    video.pause();
                    video.src = '';
                    video.load();  // 释放资源
                } catch (e) {
                    console.warn('⚠️ 关闭视频时出错:', e);
                }
            }
            // 同时清理两个状态（兼容旧版本）
            this.videoPlayer.visible = false;
            this.playingVideo = null;
        },
        // 播放视频片段（保留旧逻辑，但不再使用）
        playVideoSegment(segment) {
            console.log('🎬 开始播放视频片段:', segment);
            this.playingVideo = segment;
            // 展示视频播放器弹窗
            this.$nextTick(() => {
                const video = document.getElementById('emotionVideoPlayer');
                if (video) {
                    console.log('📹 设置视频源:', segment.video_path);
                    video.preload = 'auto';
                    video.src = segment.video_path;
                    video.onloadeddata = () => {
                        console.log('✅ 视频加载完成，开始播放');
                        video.play().catch(e => {
                            console.error('❌ 播放失败:', e);
                            this.showAlert('视频播放失败: ' + e.message, 'error', '错误');
                        });
                    };
                    video.onerror = (e) => {
                        console.error('❌ 视频加载失败:', segment.video_path, e);
                        this.showAlert('视频文件加载失败', 'error', '错误');
                        this.closeVideoPlayer();
                    };
                }
            });
        },
        // 渲染情绪图表
        renderEmotionCharts() {
            if (this.emotionMode === 'group') {
                this.renderGroupEmotionChart();
            } else {
                this.renderIndividualEmotionChart();
            }
        },
        // 渲染群体情绪图（多条折线，每个成员一条）
        renderGroupEmotionChart() {
            try {
                const el = document.getElementById('groupEmotionChart');
                if (!el) return;

                // 检查容器是否可见（只警告，不重试）
                if (el.offsetWidth === 0 || el.offsetHeight === 0) {
                    console.warn('⚠️ 群体情绪图表容器尺寸为0，可能容器被隐藏了（v-show）。请确保在切换到统计页面后再调用此方法。');
                    return;
                }

                // 初始化图表实例（只创建一次）
                if (!this.chartInstances.groupEmotionChart || this.chartInstances.groupEmotionChart.isDisposed()) {
                    this.chartInstances.groupEmotionChart = echarts.init(el);

                    // 绑定点击事件（只绑定一次）
                    this.chartInstances.groupEmotionChart.on('click', params => {
                        if (params.componentType === 'series') {
                            const memberName = params.seriesName;
                            const timeValue = params.data[0];
                            const timestamp = typeof timeValue === 'string' ? new Date(timeValue).getTime() : timeValue;
                            this.showSnapshotAtTime(memberName, timestamp);
                        }
                    });

                    // 首次设置静态配置（坐标轴、样式、dataZoom等）
                    this.chartInstances.groupEmotionChart.setOption({
                        title: {
                            text: '群体情绪波动',
                            left: 'center',
                            textStyle: { fontSize: 16, color: '#065f46', fontWeight: 'bold' }
                        },
                        tooltip: {
                            trigger: 'item',
                            backgroundColor: 'rgba(0,0,0,0.85)',
                            borderColor: '#10b981',
                            borderWidth: 1,
                            textStyle: { color: '#eafff7', fontSize: 13 },
                            formatter: (params) => {
                                const time = new Date(params.data[0]).toLocaleTimeString('zh-CN');
                                return `<b>${params.seriesName}</b><br/>时间: ${time}<br/>情绪值: ${params.data[1]}<br/><span style="color:#fbbf24">💡 点击查看视频</span>`;
                            }
                        },
                        grid: { left: 60, right: 30, top: 80, bottom: 90 },
                        xAxis: {
                            type: 'time',
                            minInterval: 60 * 1000,
                            splitNumber: 6,
                            axisLabel: {
                                fontSize: 11, color: '#166534', rotate: 0,
                                hideOverlap: true,
                                margin: 10,
                                formatter: (value) => new Date(value).toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'})
                            },
                            axisLine: { lineStyle: { color: '#10b981' } },
                            splitLine: { show: false }
                        },
                        yAxis: {
                            type: 'value', min: 0, max: 100,
                            name: '情绪值',
                            nameTextStyle: { color: '#065f46', fontSize: 12 },
                            axisLabel: { fontSize: 11, color: '#166534' },
                            axisLine: { lineStyle: { color: '#10b981' } },
                            splitLine: { lineStyle: { color: 'rgba(16,185,129,0.25)', type: 'dashed' } }
                        },
                        legend: { top: 35, textStyle: { color: '#065f46', fontSize: 12 } },
                        dataZoom: [
                            { type: 'inside', xAxisIndex: 0, filterMode: 'none' },
                            { type: 'slider', xAxisIndex: 0, filterMode: 'none', height: 18, bottom: 25, borderColor: '#86efac', fillerColor: 'rgba(16,185,129,0.2)', handleStyle: { color: '#10b981' } }
                        ],
                        animationDuration: 500,
                        animationEasing: 'cubicOut',
                        series: []
                    });
                    this.$nextTick(() => this.chartInstances.groupEmotionChart.resize());
                }
                const chart = this.chartInstances.groupEmotionChart;

                // 如果没有数据
                if (!this.allIndividualEmotions || Object.keys(this.allIndividualEmotions).length === 0) {
                    chart.setOption({ series: [], legend: { data: [] } }, false);
                    return;
                }

                // 构建 series 数据（增量更新，只替换 series + legend）
                const colors = ['#10b981', '#059669', '#34d399', '#2dd4bf', '#22c55e', '#14b8a6'];
                const series = [];
                const legendData = [];

                Object.keys(this.allIndividualEmotions).forEach((member, idx) => {
                    const rawData = this.allIndividualEmotions[member];
                    // 群体图也做去重+排序，避免同一时间点造成回折/重影
                    const normalize = (list) => {
                        const byTs = new Map();
                        (list || []).forEach(item => {
                            const ts = new Date(item.time).getTime();
                            if (!Number.isFinite(ts)) return;
                            byTs.set(ts, { ...item, _ts: ts });
                        });
                        let normalized = Array.from(byTs.values()).sort((a, b) => a._ts - b._ts);
                        const MAX_POINTS = 200;
                        if (normalized.length > MAX_POINTS) normalized = normalized.slice(-MAX_POINTS);
                        return normalized;
                    };
                    const displayData = normalize(rawData);
                    legendData.push(member);
                    series.push({
                        name: member,
                        type: 'line',
                        data: displayData.map(d => [d._ts, d.emotion_value]),
                        smooth: false,
                        symbol: 'circle',
                        symbolSize: 8,
                        lineStyle: { width: 3, color: colors[idx % colors.length] },
                        itemStyle: { color: colors[idx % colors.length] },
                        large: true,
                        sampling: 'lttb'
                    });
                });

                // 只更新数据部分，不覆盖用户的 dataZoom 位置
                chart.setOption({ series: series, legend: { data: legendData } }, false);
                // 确保图表尺寸正确（v-show 切换后可能需要重新计算）
                this.$nextTick(() => chart.resize());

            } catch (error) {
                console.error('渲染群体情绪图表失败:', error);
            }
        },
        // 渲染个体情绪图
        renderIndividualEmotionChart() {
            try {
                const el = document.getElementById('individualEmotionChart');
                if (!el) {
                    console.log('⚠️ 个体情绪图表元素不存在');
                    return;
                }

                // 检查容器是否可见（只警告，不重试）
                if (el.offsetWidth === 0 || el.offsetHeight === 0) {
                    console.warn('⚠️ 个体情绪图表容器尺寸为0，可能容器被隐藏了（v-show）。请确保在切换到统计页面后再调用此方法。');
                    return;
                }

                console.log('📉 渲染个体情绪图, 选中成员:', this.selectedMember);
                console.log('  - 可用成员:', Object.keys(this.individualEmotions));

                // 初始化图表实例（只创建一次）
                if (!this.chartInstances.individualEmotionChart || this.chartInstances.individualEmotionChart.isDisposed()) {
                    this.chartInstances.individualEmotionChart = echarts.init(el);

                    // 绑定点击事件（只绑定一次）
                    this.chartInstances.individualEmotionChart.on('click', params => {
                        if (params.componentType === 'series') {
                            // 用点击的时间值查找最近的原始数据点（避免采样后索引不匹配）
                            const clickedTime = params.data[0];
                            const memberData = this.individualEmotions[this.selectedMember];
                            if (memberData && memberData.length > 0) {
                                const timestamp = typeof clickedTime === 'string' ? new Date(clickedTime).getTime() : clickedTime;
                                this.showSnapshotAtTime(this.selectedMember, timestamp);
                            }
                        }
                    });

                    // 静态配置只设置一次（tooltip、grid、axes、dataZoom、animation）
                    this.chartInstances.individualEmotionChart.setOption({
                        title: {
                            text: '',
                            left: 'center',
                            textStyle: { fontSize: 16, color: '#065f46', fontWeight: 'bold' }
                        },
                        tooltip: {
                            trigger: 'item',
                            backgroundColor: 'rgba(0,0,0,0.85)',
                            borderColor: '#10b981',
                            borderWidth: 2,
                            textStyle: { color: '#fff', fontSize: 13 }
                        },
                        grid: { left: 50, right: 20, top: 45, bottom: 70 },
                        xAxis: {
                            type: 'time',
                            minInterval: 60 * 1000,
                            splitNumber: 6,
                            axisLabel: {
                                fontSize: 11,
                                color: '#166534',
                                rotate: 0,
                                hideOverlap: true,
                                margin: 10,
                                formatter: (value) => new Date(value).toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'})
                            },
                            axisLine: { lineStyle: { color: '#10b981' } },
                            splitLine: { show: false }
                        },
                        yAxis: {
                            type: 'value',
                            min: 0,
                            max: 100,
                            name: '情绪值',
                            nameTextStyle: { color: '#065f46', fontSize: 12 },
                            axisLabel: { fontSize: 11, color: '#166534' },
                            axisLine: { lineStyle: { color: '#10b981' } },
                            splitLine: { lineStyle: { color: 'rgba(16,185,129,0.25)', type: 'dashed' } }
                        },
                        dataZoom: [
                            { type: 'inside', xAxisIndex: 0, filterMode: 'none' },
                            {
                                type: 'slider',
                                xAxisIndex: 0,
                                filterMode: 'none',
                                height: 18,
                                bottom: 25,
                                borderColor: '#86efac',
                                fillerColor: 'rgba(16,185,129,0.2)',
                                handleStyle: { color: '#10b981' }
                            }
                        ],
                        animationDuration: 500,
                        animationEasing: 'cubicOut',
                        series: []
                    });
                    this.$nextTick(() => this.chartInstances.individualEmotionChart.resize());
                }
                const chart = this.chartInstances.individualEmotionChart;

                // 如果没有选中的成员或没有数据，渲染空图表
                if (!this.selectedMember || !this.individualEmotions[this.selectedMember]) {
                    chart.setOption({
                        title: { text: '暂无个体情绪数据', subtext: '请选择成员或等待情绪数据生成', subtextStyle: { fontSize: 12, color: '#bbb' } },
                        series: []
                    }, false);
                    console.log('📦 个体情绪图表显示空数据提示');
                    return;
                }

                const rawData = this.individualEmotions[this.selectedMember];
                const normalizeAndSample = (list) => {
                    const byTs = new Map();
                    (list || []).forEach(item => {
                        const ts = new Date(item.time).getTime();
                        if (!Number.isFinite(ts)) return;
                        // 同时间点去重：保留最后一条，避免曲线回折
                        byTs.set(ts, { ...item, _ts: ts });
                    });
                    let normalized = Array.from(byTs.values()).sort((a, b) => a._ts - b._ts);
                    if (normalized.length > 50) {
                        const step = Math.ceil(normalized.length / 50);
                        normalized = normalized.filter((_, idx) => idx % step === 0 || idx === normalized.length - 1);
                    }
                    return normalized;
                };
                const data = normalizeAndSample(rawData);

                // 只更新动态数据（title、series、tooltip.formatter），保留 dataZoom 用户位置
                chart.setOption({
                    title: { text: `${this.selectedMember}的情绪变化`, subtext: '' },
                    tooltip: {
                        formatter: params => {
                            const item = data[params.dataIndex];
                            if (!item) return '';
                            const time = new Date(item.time).toLocaleTimeString('zh-CN');
                            return `<b>时间</b>: ${time}<br/><b>情绪</b>: ${item.emotion_type}<br/><b>数值</b>: ${item.emotion_value}<br/><span style="color:#fbbf24">💡 点击查看视频</span>`;
                        }
                    },
                    series: [{
                        type: 'line',
                        data: data.map(d => [d._ts, d.emotion_value]),
                        smooth: 0.25,
                        smoothMonotone: 'x',
                        symbol: 'circle',
                        symbolSize: 10,
                        lineStyle: { width: 4, color: '#10b981' },
                        itemStyle: {
                            color: '#10b981',
                            borderWidth: 2,
                            borderColor: '#fff'
                        },
                        areaStyle: {
                            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                                { offset: 0, color: 'rgba(16, 185, 129, 0.35)' },
                                { offset: 1, color: 'rgba(16, 185, 129, 0.05)' }
                            ])
                        }
                    }]
                }, false);  // notMerge=false 增量更新，保留 dataZoom 位置
                // 确保图表尺寸正确（v-show 切换后可能需要重新计算）
                this.$nextTick(() => chart.resize());

            } catch (error) {
                console.error('渲染个体情绪图表失败:', error);
            }
        },
        // 渲染统计图表
        renderStatsCharts() {
            console.log('🎨 开始渲染统计图表...');
            console.log('  - pieChartData:', this.pieChartData);
            console.log('  - interactionData:', this.interactionData);

            // 发言占比饶图
            const pieEl = document.getElementById('pieChart');
            console.log('  - pieEl:', pieEl);

            // ✅ 检查容器是否可见且有尺寸（只警告，不重试）
            if (pieEl && pieEl.offsetWidth === 0) {
                console.warn('⚠️ 图表容器尺寸为0，可能容器被隐藏了（v-show）。请确保在切换到统计页面后再调用此方法。');
                return;
            }

            if (pieEl) {
                // DOM 可能因 v-if/v-else 切换而重建，需要重新初始化
                if (!this.chartInstances.pieChart || this.chartInstances.pieChart.isDisposed()) {
                    this.chartInstances.pieChart = echarts.init(pieEl);
                }
                const pieChart = this.chartInstances.pieChart;

                // 即使数据为空也渲染图表（显示空状态）
                const chartData = (this.pieChartData && this.pieChartData.length > 0) ? this.pieChartData : [];

                // notMerge: false 实现增量更新，不白屏
                pieChart.setOption({
                    tooltip: { trigger: 'item', formatter: '{b}: {c}次 ({d}%)' },
                    color: ['#3E8E91', '#2D6A6D', '#5FA8AB', '#4BA3B0', '#E88C5D', '#6B9396'],
                    series: [{
                        type: 'pie',
                        radius: ['40%', '75%'],
                        center: ['50%', '50%'],
                        data: chartData,
                        label: { show: true, formatter: '{b}\n{d}%', fontSize: 10 },
                        emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)' } }
                    }],
                    // 数据为空时显示提示
                    graphic: chartData.length === 0 ? [{
                        type: 'text',
                        left: 'center',
                        top: 'middle',
                        style: {
                            text: '暂无数据',
                            fontSize: 14,
                            fill: '#999'
                        }
                    }] : []
                }, false);  // notMerge: false
            }
            
            // 发言次数柱状图
            const barEl = document.getElementById('barChart');
            if (barEl) {
                if (!this.chartInstances.barChart || this.chartInstances.barChart.isDisposed()) {
                    this.chartInstances.barChart = echarts.init(barEl);
                }
                const barChart = this.chartInstances.barChart;

                // 即使数据为空也渲染图表
                const chartData = (this.pieChartData && this.pieChartData.length > 0) ? this.pieChartData : [];
                const names = chartData.map(d => d.name);
                const values = chartData.map(d => d.value);

                barChart.setOption({
                    tooltip: { trigger: 'axis', formatter: '{b}: {c}次' },
                    xAxis: {
                        type: 'category',
                        data: names,
                        axisLabel: { fontSize: 10, rotate: 30 }
                    },
                    yAxis: {
                        type: 'value',
                        name: '发言次数',
                        nameTextStyle: { fontSize: 10 },
                        axisLabel: { fontSize: 10 }
                    },
                    grid: { left: 40, right: 15, top: 20, bottom: 50 },
                    series: [{
                        type: 'bar',
                        data: values,
                        itemStyle: {
                            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                                { offset: 0, color: '#4BA3B0' },
                                { offset: 1, color: '#3E8E91' }
                            ]),
                            borderRadius: [4, 4, 0, 0]
                        },
                        label: { show: true, position: 'top', fontSize: 10, color: '#333' }
                    }],
                    // 数据为空时显示提示
                    graphic: chartData.length === 0 ? [{
                        type: 'text',
                        left: 'center',
                        top: 'middle',
                        style: {
                            text: '暂无数据',
                            fontSize: 14,
                            fill: '#999'
                        }
                    }] : []
                }, false);
            }

            // 小组成员平均学习状态曲线
            const avgLearningEl = document.getElementById('avgLearningChart');
            if (avgLearningEl) {
                if (!this.chartInstances.avgLearningChart || this.chartInstances.avgLearningChart.isDisposed()) {
                    this.chartInstances.avgLearningChart = echarts.init(avgLearningEl);
                }
                const avgLearningChart = this.chartInstances.avgLearningChart;
                const timeline = Array.isArray(this.groupEmotionTimeline) ? this.groupEmotionTimeline.slice(-60) : [];

                if (!timeline.length) {
                    avgLearningChart.setOption({
                        title: {
                            text: '暂无学习状态数据',
                            left: 'center',
                            top: 'middle',
                            textStyle: { color: '#9ca3af', fontSize: 13, fontWeight: 'normal' }
                        },
                        xAxis: { show: false },
                        yAxis: { show: false },
                        series: []
                    }, true);
                } else {
                    const xData = timeline.map(item => {
                        const dt = new Date(String(item.time).replace(' ', 'T'));
                        if (!Number.isNaN(dt.getTime())) {
                            return dt.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
                        }
                        return String(item.time).slice(-5);
                    });
                    const yData = timeline.map(item => Number(item.value || 0));

                    avgLearningChart.setOption({
                        title: {
                            text: '',
                            left: 'center',
                            top: 4,
                            textStyle: { fontSize: 13, color: '#4b5563', fontWeight: 'bold' }
                        },
                        tooltip: {
                            trigger: 'axis',
                            formatter: params => `${params[0].axisValue}<br/>平均学习状态: ${params[0].data}`
                        },
                        grid: { left: 42, right: 20, top: 42, bottom: 36 },
                        xAxis: {
                            type: 'category',
                            data: xData,
                            name: '时间',
                            nameTextStyle: { fontSize: 11, color: '#6b7280' },
                            axisLabel: { fontSize: 10, color: '#6b7280' },
                            axisLine: { lineStyle: { color: '#9ca3af' } },
                            boundaryGap: false
                        },
                        yAxis: {
                            type: 'value',
                            min: 0,
                            max: 100,
                            name: '平均学习评分',
                            nameTextStyle: { fontSize: 11, color: '#6b7280' },
                            axisLabel: { fontSize: 10, color: '#6b7280' },
                            splitLine: { lineStyle: { color: '#e5e7eb' } }
                        },
                        series: [{
                            type: 'line',
                            smooth: true,
                            data: yData,
                            symbol: 'circle',
                            symbolSize: 6,
                            lineStyle: { color: '#3E8E91', width: 3 },
                            itemStyle: { color: '#3E8E91' },
                            areaStyle: {
                                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                                    { offset: 0, color: 'rgba(75, 163, 176, 0.22)' },
                                    { offset: 1, color: 'rgba(75, 163, 176, 0.04)' }
                                ])
                            }
                        }]
                    }, true);
                }
            }
            
            // 成员互动关系雷达图
            const graphEl = document.getElementById('interactionChart');
            if (graphEl) {
                if (!this.chartInstances.graphChart || this.chartInstances.graphChart.isDisposed()) {
                    this.chartInstances.graphChart = echarts.init(graphEl);
                }
                const graphChart = this.chartInstances.graphChart;
                const interactionMap = {};
                const nodes = (this.interactionData && Array.isArray(this.interactionData.nodes)) ? this.interactionData.nodes : [];
                const edges = (this.interactionData && Array.isArray(this.interactionData.edges)) ? this.interactionData.edges : [];

                nodes.forEach(n => {
                    if (n && n.name) interactionMap[n.name] = 0;
                });
                edges.forEach(e => {
                    const weight = Number(e.value || 0);
                    if (e.source) interactionMap[e.source] = (interactionMap[e.source] || 0) + weight;
                    if (e.target) interactionMap[e.target] = (interactionMap[e.target] || 0) + weight;
                });

                if (!edges.length) {
                    nodes.forEach(n => {
                        if (n && n.name) interactionMap[n.name] = Math.max(interactionMap[n.name] || 0, Number(n.value || 0));
                    });
                }

                const members = Object.keys(interactionMap).length
                    ? Object.keys(interactionMap)
                    : (this.pieChartData || []).map(d => d.name);
                const values = members.map(name => Number(interactionMap[name] || 0));
                const maxVal = Math.max(...values, 10);
                const radarMax = Math.ceil(maxVal * 1.25);

                graphChart.setOption({
                    title: {
                        text: '',
                        left: 'center',
                        top: 6,
                        textStyle: { fontSize: 13, color: '#4b5563', fontWeight: 'bold' }
                    },
                    tooltip: {
                        trigger: 'item',
                        formatter: params => {
                            if (!params.value || !members.length) return '暂无数据';
                            return members.map((m, idx) => `${m}: ${params.value[idx] || 0}`).join('<br/>');
                        }
                    },
                    radar: {
                        radius: '62%',
                        center: ['50%', '58%'],
                        indicator: members.map(name => ({ name, max: radarMax })),
                        splitNumber: 4,
                        axisName: { color: '#4b5563', fontSize: 12 },
                        splitLine: { lineStyle: { color: ['rgba(62,142,145,0.14)', 'rgba(62,142,145,0.14)', 'rgba(62,142,145,0.14)', 'rgba(62,142,145,0.14)'] } },
                        splitArea: { areaStyle: { color: ['rgba(75,163,176,0.06)', 'rgba(255,255,255,0.96)'] } },
                        axisLine: { lineStyle: { color: 'rgba(62,142,145,0.2)' } }
                    },
                    series: members.length ? [{
                        type: 'radar',
                        data: [{
                            value: values,
                            name: '互动强度',
                            lineStyle: { color: '#3E8E91', width: 3 },
                            itemStyle: { color: '#3E8E91' },
                            areaStyle: { color: 'rgba(75,163,176,0.12)' },
                            symbol: 'circle',
                            symbolSize: 5
                        }]
                    }] : []
                }, true);
            }
                    
            // ✅ 关键修复：渲染完成后调用resize()确保图表占据全宽
            this.$nextTick(() => {
                if (this.chartInstances.pieChart) this.chartInstances.pieChart.resize();
                if (this.chartInstances.barChart) this.chartInstances.barChart.resize();
                if (this.chartInstances.avgLearningChart) this.chartInstances.avgLearningChart.resize();
                if (this.chartInstances.graphChart) this.chartInstances.graphChart.resize();
                console.log('✅ 所有图表已resize');
            });
                    
            // 旧的情绪波动图（已废弃，不再渲染）
            // 情绪相关的图表现在由独立的方法处理
        },
        // ===== 教师数据看板方法 =====
        // 打开数据看板
        openTeacherDashboard(group) {
            this.tdMeetingId = group.meeting_id;
            this.tdGroupInfo = group;
            this.showTeacherDashboard = true;
            this.tdLoading = true;
            this.$nextTick(() => {
                this.loadTeacherDashboardData();
            });
        },
        // 关闭数据看板
        closeTeacherDashboard() {
            this.showTeacherDashboard = false;
            if (this.tdRequestController) {
                this.tdRequestController.abort();
                this.tdRequestController = null;
            }
            if (this.tdWindowDebounceTimer) {
                clearTimeout(this.tdWindowDebounceTimer);
                this.tdWindowDebounceTimer = null;
            }
            // 关闭视频播放器
            this.closeTdVideoPlayer();
            // 清理定时器
            if (this.tdRefreshTimer) {
                clearInterval(this.tdRefreshTimer);
                this.tdRefreshTimer = null;
            }
            // 销毁图表实例
            Object.keys(this.tdChartInstances).forEach(key => {
                if (this.tdChartInstances[key]) {
                    this.tdChartInstances[key].dispose();
                }
            });
            this.tdChartInstances = {};
            // 重置数据
            this.tdPieData = [];
            this.tdInteractionData = null;
            this.tdMemberScores = [];
            this.tdIndividualEmotions = {};
            this.tdGroupEmotionTimeline = [];
            this.tdSelectedMember = '';
            this.tdTimeWindow = 0;
            this.tdRequestSeq = 0;
            this.tdSwitchLoading = false;
            this.tdMeetingId = null;
            this.tdGroupInfo = null;
        },
        setTdTimeWindow(minutes) {
            const parsed = Number(minutes);
            const nextWindow = Number.isNaN(parsed) ? 0 : parsed;
            if (this.tdTimeWindow === nextWindow) return;
            this.tdTimeWindow = nextWindow;
            this.tdSwitchLoading = true;
            // 立即清空旧情绪曲线，避免切换窗口时保留旧数据造成“卡住”错觉
            this.tdIndividualEmotions = {};
            this.tdGroupEmotionTimeline = [];
            this.tdSelectedMember = '';
            this.$nextTick(() => {
                this.renderTdIndividualEmotionChart();
                this.renderTdGroupEmotionChart();
            });
            if (this.tdWindowDebounceTimer) clearTimeout(this.tdWindowDebounceTimer);
            this.tdWindowDebounceTimer = setTimeout(() => {
                this.loadTeacherDashboardData();
            }, 300);
        },
        // 加载数据看板数据
        async loadTeacherDashboardData() {
            if (!this.tdMeetingId) return;
            // 只在首次加载时显示loading，后续刷新不显示（避免图表DOM被销毁）
            const isFirstLoad = !this.tdPieData.length && !Object.keys(this.tdIndividualEmotions).length;
            if (isFirstLoad) this.tdLoading = true;
            const requestSeq = ++this.tdRequestSeq;
            try {
                if (this.tdRequestController) {
                    this.tdRequestController.abort();
                }
                this.tdRequestController = new AbortController();
                const signal = this.tdRequestController.signal;
                // 并行请求统计和情绪数据
                const [statsRes, emotionRes] = await Promise.all([
                    axios.get(`/api/realtime-stats/${this.tdMeetingId}`, { timeout: 120000, signal }),
                    axios.get(`/api/emotion-details/${this.tdMeetingId}?minutes=${this.tdTimeWindow}`, { timeout: 120000, signal })
                ]);

                // 只接受最后一次请求结果，避免“后发先至”导致图表回跳到旧窗口
                if (requestSeq !== this.tdRequestSeq) return;

                if (statsRes.data.status === 'success') {
                    this.tdPieData = statsRes.data.pie_data || [];
                    this.tdInteractionData = statsRes.data.interaction || null;
                    this.tdMemberScores = statsRes.data.member_scores || [];
                }

                if (emotionRes.data.status === 'success') {
                    const windowIndividual = emotionRes.data.individual_emotions || {};
                    const allIndividual = emotionRes.data.all_individual_emotions || {};
                    this.tdIndividualEmotions = Object.keys(allIndividual).length ? allIndividual : windowIndividual;
                    this.tdGroupEmotionTimeline = emotionRes.data.group_emotion_timeline || [];
                    const emotionKeys = Object.keys(this.tdIndividualEmotions);
                    const selectedExists = this.tdSelectedMember && emotionKeys.includes(this.tdSelectedMember);
                    if (!selectedExists) {
                        this.tdSelectedMember = emotionKeys[0] || (this.tdMemberScores[0] && this.tdMemberScores[0].name) || '';
                    }
                }
            } catch(e) {
                if (!(e.name === 'AbortError' || e.code === 'ERR_CANCELED')) {
                    console.error('加载数据看板失败:', e);
                }
            } finally {
                if (requestSeq === this.tdRequestSeq) {
                    this.tdLoading = false;
                    this.tdSwitchLoading = false;
                }
            }

            // 渲染图表
            this.$nextTick(() => {
                setTimeout(() => {
                    this.renderTdStatsCharts();
                    this.renderTdIndividualEmotionChart();
                    this.renderTdGroupEmotionChart();
                }, 200);
            });

            // 设置自动刷新（30秒）- 只在首次设置
            if (!this.tdRefreshTimer) {
                this.tdRefreshTimer = setInterval(() => {
                    if (this.showTeacherDashboard) {
                        this.loadTeacherDashboardData();
                    }
                }, 30000);
            }
        },
        // 渲染数据看板统计图表
        renderTdStatsCharts() {
            // 饼图
            const pieEl = document.getElementById('tdPieChart');
            if (pieEl && this.tdPieData && this.tdPieData.length > 0) {
                if (!this.tdChartInstances.pieChart || this.tdChartInstances.pieChart.isDisposed()) {
                    this.tdChartInstances.pieChart = echarts.init(pieEl);
                }
                this.tdChartInstances.pieChart.setOption({
                    tooltip: { trigger: 'item', formatter: '{b}: {c}次 ({d}%)' },
                    color: ['#3E8E91', '#2D6A6D', '#5FA8AB', '#4BA3B0', '#E88C5D', '#6B9396'],
                    series: [{
                        type: 'pie',
                        radius: ['40%', '75%'],
                        center: ['50%', '50%'],
                        data: this.tdPieData,
                        label: { show: true, formatter: '{b}\n{d}%', fontSize: 11 },
                        emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)' } }
                    }]
                }, false);
            }

            // 柱状图
            const barEl = document.getElementById('tdBarChart');
            if (barEl && this.tdPieData && this.tdPieData.length > 0) {
                if (!this.tdChartInstances.barChart || this.tdChartInstances.barChart.isDisposed()) {
                    this.tdChartInstances.barChart = echarts.init(barEl);
                }
                const names = this.tdPieData.map(d => d.name);
                const values = this.tdPieData.map(d => d.value);
                this.tdChartInstances.barChart.setOption({
                    tooltip: { trigger: 'axis', formatter: '{b}: {c}次' },
                    xAxis: {
                        type: 'category',
                        data: names,
                        axisLabel: { fontSize: 11, rotate: 30 }
                    },
                    yAxis: {
                        type: 'value',
                        name: '发言次数',
                        nameTextStyle: { fontSize: 11 },
                        axisLabel: { fontSize: 11 }
                    },
                    grid: { left: 45, right: 20, top: 25, bottom: 55 },
                    series: [{
                        type: 'bar',
                        data: values,
                        itemStyle: {
                            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                                { offset: 0, color: '#4BA3B0' },
                                { offset: 1, color: '#3E8E91' }
                            ]),
                            borderRadius: [4, 4, 0, 0]
                        },
                        label: { show: true, position: 'top', fontSize: 11, color: '#333' }
                    }]
                }, false);
            }

            // 小组成员平均学习状态曲线
            const avgLearningEl = document.getElementById('tdAvgLearningChart');
            if (avgLearningEl) {
                if (!this.tdChartInstances.avgLearningChart || this.tdChartInstances.avgLearningChart.isDisposed()) {
                    this.tdChartInstances.avgLearningChart = echarts.init(avgLearningEl);
                }
                const avgLearningChart = this.tdChartInstances.avgLearningChart;
                const timeline = Array.isArray(this.tdGroupEmotionTimeline) ? this.tdGroupEmotionTimeline.slice(-80) : [];

                if (!timeline.length) {
                    avgLearningChart.setOption({
                        title: {
                            text: '暂无学习状态数据',
                            left: 'center',
                            top: 'middle',
                            textStyle: { color: '#9ca3af', fontSize: 14, fontWeight: 'normal' }
                        },
                        xAxis: { show: false },
                        yAxis: { show: false },
                        series: []
                    }, true);
                } else {
                    const xData = timeline.map(item => {
                        const dt = new Date(String(item.time).replace(' ', 'T'));
                        if (!Number.isNaN(dt.getTime())) {
                            return dt.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
                        }
                        return String(item.time).slice(-5);
                    });
                    const yData = timeline.map(item => Number(item.value || 0));

                    avgLearningChart.setOption({
                        title: {
                            text: '',
                            left: 'center',
                            top: 8,
                            textStyle: { fontSize: 15, color: '#4b5563', fontWeight: 'bold' }
                        },
                        tooltip: {
                            trigger: 'axis',
                            formatter: params => `${params[0].axisValue}<br/>平均学习状态: ${params[0].data}`
                        },
                        grid: { left: 48, right: 24, top: 52, bottom: 42 },
                        xAxis: {
                            type: 'category',
                            data: xData,
                            name: '时间',
                            nameTextStyle: { fontSize: 12, color: '#6b7280' },
                            axisLabel: { fontSize: 11, color: '#6b7280' },
                            axisLine: { lineStyle: { color: '#9ca3af' } },
                            boundaryGap: false
                        },
                        yAxis: {
                            type: 'value',
                            min: 0,
                            max: 100,
                            name: '平均学习评分',
                            nameTextStyle: { fontSize: 12, color: '#6b7280' },
                            axisLabel: { fontSize: 11, color: '#6b7280' },
                            splitLine: { lineStyle: { color: '#e5e7eb' } }
                        },
                        series: [{
                            type: 'line',
                            smooth: true,
                            data: yData,
                            symbol: 'circle',
                            symbolSize: 7,
                            lineStyle: { color: '#3E8E91', width: 3 },
                            itemStyle: { color: '#3E8E91' },
                            areaStyle: {
                                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                                    { offset: 0, color: 'rgba(75, 163, 176, 0.22)' },
                                    { offset: 1, color: 'rgba(75, 163, 176, 0.04)' }
                                ])
                            }
                        }]
                    }, true);
                }
            }

            // 成员互动关系雷达图
            const graphEl = document.getElementById('tdInteractionChart');
            if (graphEl) {
                if (!this.tdChartInstances.graphChart || this.tdChartInstances.graphChart.isDisposed()) {
                    this.tdChartInstances.graphChart = echarts.init(graphEl);
                }
                const interactionMap = {};
                const nodes = (this.tdInteractionData && Array.isArray(this.tdInteractionData.nodes)) ? this.tdInteractionData.nodes : [];
                const edges = (this.tdInteractionData && Array.isArray(this.tdInteractionData.edges)) ? this.tdInteractionData.edges : [];

                nodes.forEach(n => {
                    if (n && n.name) interactionMap[n.name] = 0;
                });
                edges.forEach(e => {
                    const weight = Number(e.value || 0);
                    if (e.source) interactionMap[e.source] = (interactionMap[e.source] || 0) + weight;
                    if (e.target) interactionMap[e.target] = (interactionMap[e.target] || 0) + weight;
                });

                if (!edges.length) {
                    nodes.forEach(n => {
                        if (n && n.name) interactionMap[n.name] = Math.max(interactionMap[n.name] || 0, Number(n.value || 0));
                    });
                }

                const members = Object.keys(interactionMap).length
                    ? Object.keys(interactionMap)
                    : (this.tdPieData || []).map(d => d.name);
                const values = members.map(name => Number(interactionMap[name] || 0));
                const maxVal = Math.max(...values, 10);
                const radarMax = Math.ceil(maxVal * 1.25);

                this.tdChartInstances.graphChart.setOption({
                    title: {
                        text: '',
                        left: 'center',
                        top: 10,
                        textStyle: { fontSize: 15, color: '#4b5563', fontWeight: 'bold' }
                    },
                    tooltip: {
                        trigger: 'item',
                        formatter: params => {
                            if (!params.value || !members.length) return '暂无数据';
                            return members.map((m, idx) => `${m}: ${params.value[idx] || 0}`).join('<br/>');
                        }
                    },
                    radar: {
                        radius: '66%',
                        center: ['50%', '58%'],
                        indicator: members.map(name => ({ name, max: radarMax })),
                        splitNumber: 4,
                        axisName: { color: '#4b5563', fontSize: 13 },
                        splitLine: { lineStyle: { color: ['rgba(62,142,145,0.14)', 'rgba(62,142,145,0.14)', 'rgba(62,142,145,0.14)', 'rgba(62,142,145,0.14)'] } },
                        splitArea: { areaStyle: { color: ['rgba(75,163,176,0.06)', 'rgba(255,255,255,0.96)'] } },
                        axisLine: { lineStyle: { color: 'rgba(62,142,145,0.2)' } }
                    },
                    series: members.length ? [{
                        type: 'radar',
                        data: [{
                            value: values,
                            name: '互动强度',
                            lineStyle: { color: '#3E8E91', width: 3 },
                            itemStyle: { color: '#3E8E91' },
                            areaStyle: { color: 'rgba(75,163,176,0.12)' },
                            symbol: 'circle',
                            symbolSize: 6
                        }]
                    }] : []
                }, true);
            }

            // resize
            this.$nextTick(() => {
                if (this.tdChartInstances.pieChart) this.tdChartInstances.pieChart.resize();
                if (this.tdChartInstances.barChart) this.tdChartInstances.barChart.resize();
                if (this.tdChartInstances.avgLearningChart) this.tdChartInstances.avgLearningChart.resize();
                if (this.tdChartInstances.graphChart) this.tdChartInstances.graphChart.resize();
            });
        },
        // 渲染数据看板个体情绪图
        renderTdIndividualEmotionChart() {
            const el = document.getElementById('tdIndividualEmotionChart');
            if (!el) return;

            if (!this.tdChartInstances.individualEmotionChart || this.tdChartInstances.individualEmotionChart.isDisposed()) {
                this.tdChartInstances.individualEmotionChart = echarts.init(el);
                // 绑定点击事件 - 播放视频（只绑定一次）
                this.tdChartInstances.individualEmotionChart.on('click', params => {
                    if (params.componentType === 'series') {
                        const clickedTime = params.data && params.data[0];
                        if (clickedTime) this.tdShowSnapshotAtTime(this.tdSelectedMember, Number(clickedTime));
                    }
                });
                // 静态配置只设置一次
                this.tdChartInstances.individualEmotionChart.setOption({
                    title: { text: '', left: 'center', textStyle: { fontSize: 16, color: '#065f46', fontWeight: 'bold' } },
                    tooltip: {
                        trigger: 'item',
                        backgroundColor: 'rgba(0,0,0,0.85)',
                        borderColor: '#10b981',
                        borderWidth: 2,
                        textStyle: { color: '#fff', fontSize: 13 }
                    },
                    grid: { left: 50, right: 20, top: 45, bottom: 70 },
                    xAxis: {
                        type: 'time',
                        minInterval: 60 * 1000,
                        splitNumber: 6,
                        axisLabel: {
                            fontSize: 11,
                            color: '#166534',
                            hideOverlap: true,
                            margin: 10,
                            formatter: (value) => new Date(value).toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'})
                        },
                        axisLine: { lineStyle: { color: '#10b981' } },
                        splitLine: { show: false }
                    },
                    yAxis: {
                        type: 'value', min: 0, max: 100, name: '情绪值',
                        nameTextStyle: { color: '#065f46', fontSize: 12 },
                        axisLabel: { fontSize: 11, color: '#166534' },
                        axisLine: { lineStyle: { color: '#10b981' } },
                        splitLine: { lineStyle: { color: 'rgba(16,185,129,0.25)', type: 'dashed' } }
                    },
                    dataZoom: [
                        { type: 'inside', xAxisIndex: 0, filterMode: 'none' },
                        { type: 'slider', xAxisIndex: 0, filterMode: 'none', height: 18, bottom: 25, borderColor: '#86efac', fillerColor: 'rgba(16,185,129,0.2)', handleStyle: { color: '#10b981' } }
                    ],
                    animationDuration: 500,
                    animationEasing: 'cubicOut',
                    series: []
                });
                this.$nextTick(() => this.tdChartInstances.individualEmotionChart.resize());
            }
            const chart = this.tdChartInstances.individualEmotionChart;

            if (!this.tdSelectedMember || !this.tdIndividualEmotions[this.tdSelectedMember]) {
                chart.setOption({
                    title: { text: '暂无个体情绪数据', subtext: '请选择成员', subtextStyle: { fontSize: 12, color: '#bbb' } },
                    series: []
                }, { notMerge: false, replaceMerge: ['series'] });
                return;
            }

            const rawData = this.tdIndividualEmotions[this.tdSelectedMember];
            const normalizeAndSample = (list) => {
                const byTs = new Map();
                (list || []).forEach(item => {
                    const ts = new Date(item.time).getTime();
                    if (!Number.isFinite(ts)) return;
                    // 同时间点去重：保留最后一条，避免曲线回折
                    byTs.set(ts, { ...item, _ts: ts });
                });
                let normalized = Array.from(byTs.values()).sort((a, b) => a._ts - b._ts);
                if (normalized.length > 50) {
                    const step = Math.ceil(normalized.length / 50);
                    normalized = normalized.filter((_, idx) => idx % step === 0 || idx === normalized.length - 1);
                }
                return normalized;
            };
            const data = normalizeAndSample(rawData);

            // 只更新动态数据（title、series、tooltip.formatter），保留 dataZoom 位置
            chart.setOption({
                title: { text: `${this.tdSelectedMember}的情绪变化`, subtext: '' },
                tooltip: {
                    formatter: params => {
                        const item = data[params.dataIndex];
                        if (!item) return '';
                        const time = new Date(item.time).toLocaleTimeString('zh-CN');
                        return `<b>时间</b>: ${time}<br/><b>情绪</b>: ${item.emotion_type}<br/><b>数值</b>: ${item.emotion_value}`;
                    }
                },
                series: [{
                    type: 'line',
                    data: data.map(d => [d._ts, d.emotion_value]),
                    smooth: 0.25,
                    smoothMonotone: 'x',
                    symbol: 'circle',
                    symbolSize: 10,
                    lineStyle: { width: 4, color: '#10b981' },
                    itemStyle: { color: '#10b981', borderWidth: 2, borderColor: '#fff' },
                    areaStyle: {
                        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                            { offset: 0, color: 'rgba(16, 185, 129, 0.35)' },
                            { offset: 1, color: 'rgba(16, 185, 129, 0.05)' }
                        ])
                    }
                }]
            }, false);  // notMerge=false 增量更新，保留 dataZoom 位置
        },
        // 渲染数据看板群体情绪图
        renderTdGroupEmotionChart() {
            const el = document.getElementById('tdGroupEmotionChart');
            if (!el) return;

            if (!this.tdChartInstances.groupEmotionChart || this.tdChartInstances.groupEmotionChart.isDisposed()) {
                this.tdChartInstances.groupEmotionChart = echarts.init(el);
                // 绑定点击事件 - 播放视频（只绑定一次）
                this.tdChartInstances.groupEmotionChart.on('click', params => {
                    if (params.componentType === 'series') {
                        const memberName = params.seriesName;
                        const timeValue = params.data[0];
                        const timestamp = typeof timeValue === 'string' ? new Date(timeValue).getTime() : timeValue;
                        this.tdShowSnapshotAtTime(memberName, timestamp);
                    }
                });
                // 静态配置只设置一次
                this.tdChartInstances.groupEmotionChart.setOption({
                    title: { show: false },
                    tooltip: {
                        trigger: 'item',
                        backgroundColor: 'rgba(0,0,0,0.85)',
                        borderColor: '#10b981',
                        borderWidth: 1,
                        textStyle: { color: '#eafff7', fontSize: 13 },
                        formatter: (params) => {
                            const time = new Date(params.data[0]).toLocaleTimeString('zh-CN');
                            return `<b>${params.seriesName}</b><br/>时间: ${time}<br/>情绪值: ${params.data[1]}`;
                        }
                    },
                    grid: { left: 60, right: 30, top: 78, bottom: 90 },
                    xAxis: {
                        type: 'time',
                        minInterval: 60 * 1000,
                        splitNumber: 6,
                        axisLabel: {
                            fontSize: 11,
                            color: '#166534',
                            hideOverlap: true,
                            margin: 10,
                            formatter: (value) => new Date(value).toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'})
                        },
                        axisLine: { lineStyle: { color: '#10b981' } },
                        splitLine: { show: false }
                    },
                    yAxis: {
                        type: 'value', min: 0, max: 100, name: '情绪值',
                        nameTextStyle: { color: '#065f46', fontSize: 12 },
                        axisLabel: { fontSize: 11, color: '#166534' },
                        axisLine: { lineStyle: { color: '#10b981' } },
                        splitLine: { lineStyle: { color: 'rgba(16,185,129,0.25)', type: 'dashed' } }
                    },
                    legend: {
                        type: 'scroll',
                        top: 8,
                        left: 'center',
                        right: 20,
                        textStyle: { color: '#065f46', fontSize: 12 }
                    },
                    dataZoom: [
                        { type: 'inside', xAxisIndex: 0, filterMode: 'none' },
                        { type: 'slider', xAxisIndex: 0, filterMode: 'none', height: 18, bottom: 25, borderColor: '#86efac', fillerColor: 'rgba(16,185,129,0.2)', handleStyle: { color: '#10b981' } }
                    ],
                    animationDuration: 500,
                    animationEasing: 'cubicOut',
                    series: []
                });
                this.$nextTick(() => this.tdChartInstances.groupEmotionChart.resize());
            }
            const chart = this.tdChartInstances.groupEmotionChart;

            if (!this.tdIndividualEmotions || Object.keys(this.tdIndividualEmotions).length === 0) {
                chart.setOption({
                    title: {
                        show: true,
                        text: '暂无群体情绪数据',
                        subtext: '等待学生发言产生数据',
                        top: 18,
                        left: 'center',
                        subtextStyle: { fontSize: 12, color: '#bbb' }
                    },
                    legend: { data: [] },
                    series: []
                }, { notMerge: false, replaceMerge: ['series', 'legend'] });
                return;
            }

            const normalizeAndSample = (list) => {
                const byTs = new Map();
                (list || []).forEach(item => {
                    const ts = new Date(item.time).getTime();
                    if (!Number.isFinite(ts)) return;
                    byTs.set(ts, { ...item, _ts: ts });
                });
                let normalized = Array.from(byTs.values()).sort((a, b) => a._ts - b._ts);
                if (normalized.length > 50) {
                    const step = Math.ceil(normalized.length / 50);
                    normalized = normalized.filter((_, idx) => idx % step === 0 || idx === normalized.length - 1);
                }
                return normalized;
            };

            const colors = ['#10b981', '#059669', '#34d399', '#2dd4bf', '#22c55e', '#14b8a6'];
            const series = [];
            const legendData = [];

            Object.keys(this.tdIndividualEmotions).forEach((member, idx) => {
                const rawData = this.tdIndividualEmotions[member];
                const sampledData = normalizeAndSample(rawData);
                legendData.push(member);
                series.push({
                    name: member,
                    type: 'line',
                    data: sampledData.map(d => [d._ts, d.emotion_value]),
                    smooth: false,
                    symbol: 'circle',
                    symbolSize: 8,
                    lineStyle: { width: 3, color: colors[idx % colors.length] },
                    itemStyle: { color: colors[idx % colors.length] }
                });
            });

            // 只更新动态数据（title + series + legend），保留 dataZoom 位置
            // 这里必须显式恢复标题，避免之前空状态标题“暂无群体情绪数据”残留
            chart.setOption({
                title: { show: false, text: '', subtext: '' },
                series: series,
                legend: { data: legendData }
            }, false);
        },
        // 教师数据看板 - 查询并播放视频片段
        async tdShowSnapshotAtTime(memberName, timestamp) {
            try {
                console.log('🎬 [教师看板] 查询视频片段, 成员:', memberName, ', 时间戳:', timestamp);

                this.tdVideoPlayer = {
                    visible: true,
                    url: '',
                    startTime: 0,
                    loading: true
                };

                const res = await axios.get('/api/get-video-context', {
                    params: {
                        meeting_id: this.tdMeetingId,
                        username: memberName,
                        timestamp: timestamp
                    },
                    timeout: 10000
                });

                if (res.data.status === 'success') {
                    console.log('✅ [教师看板] 找到视频:', res.data.video_url);
                    this.tdVideoPlayer.url = res.data.video_url;
                    this.tdVideoPlayer.startTime = res.data.jump_to_time || 0;

                    this.$nextTick(() => {
                        this.initTdVideoPlayer();
                    });
                } else {
                    console.warn('⚠️ [教师看板] 未找到视频:', res.data.message);
                    this.tdVideoPlayer.loading = false;
                    this.tdVideoPlayer.visible = false;
                    this.showAlert('该时间点暂无视频记录', 'info', '提示');
                }
            } catch (e) {
                if (e.name === 'AbortError' || e.code === 'ERR_CANCELED') return;
                console.error('❌ [教师看板] 查询视频失败:', e);
                this.tdVideoPlayer.loading = false;
                this.tdVideoPlayer.visible = false;
                if (e.code === 'ECONNABORTED') {
                    this.showAlert('视频查询超时，请稍后重试', 'error', '错误');
                } else {
                    this.showAlert('加载失败，请重试', 'error', '错误');
                }
            }
        },
        // 教师数据看板 - 初始化视频播放器
        initTdVideoPlayer() {
            const video = document.getElementById('tdEmotionVideoPlayer');
            if (!video || !this.tdVideoPlayer.url) {
                this.tdVideoPlayer.loading = false;
                return;
            }
            video.src = this.tdVideoPlayer.url;
            video.onloadedmetadata = () => {
                if (this.tdVideoPlayer.startTime > 0) {
                    video.currentTime = this.tdVideoPlayer.startTime;
                }
                this.tdVideoPlayer.loading = false;
                video.play().catch(() => { this.tdVideoPlayer.loading = false; });
            };
            video.onerror = () => {
                this.tdVideoPlayer.loading = false;
                console.error('❌ [教师看板] 视频加载失败');
            };
            video.load();
        },
        // 教师数据看板 - 关闭视频播放器
        closeTdVideoPlayer() {
            const video = document.getElementById('tdEmotionVideoPlayer');
            if (video) {
                try {
                    video.pause();
                    video.src = '';
                    video.load();
                } catch (e) {
                    console.warn('⚠️ 关闭视频时出错:', e);
                }
            }
            this.tdVideoPlayer.visible = false;
        },
        // 加载历史记录
        async loadClassHistory(options = {}) {
            if (!this.currentUser) return;
            if (!options.force && this.historyLoaded) return;
            if (this.historyLoading) return;
            this.historyLoading = true;
            try {
                const res = await axios.get(`/api/class-history/${this.currentUser.id}`);
                if (res.data.status === 'success') {
                    this.classHistory = res.data.history || [];
                    this.historyLoaded = true;
                    this.writeLobbyCache('classHistory', this.classHistory);
                }
            } catch(e) {
                console.error('加载历史失败:', e);
                if (options.force) this.showAlert('加载历史记录失败: ' + (e.response?.data?.message || e.message), 'error', '错误');
            } finally {
                this.historyLoading = false;
            }
        },
        // 下载PDF报告
        async downloadPDF(report) {
            try {
                const formData = new FormData();
                formData.append('meeting_id', report.meeting_id);
                formData.append('user_id', this.currentUser.id);
                const res = await axios.post('/api/generate-pdf-report', formData);
                if (res.data.status === 'success') {
                    window.open(res.data.pdf_url, '_blank');
                } else {
                    this.showAlert(res.data.message || 'PDF生成失败', 'error', '错误');
                }
            } catch(e) {
                this.showAlert('PDF生成错误: ' + e.message, 'error', '错误');
            }
        },
        // 下载习题
        downloadExercises(reportId) {
            window.open(`/api/download-exercises/${reportId}`, '_blank');
        },
        // 格式化日期
        formatDate(isoStr) {
            if (!isoStr) return '-';
            const d = new Date(isoStr);
            return d.toLocaleDateString() + ' ' + d.toLocaleTimeString();
        },
        // 安全格式化成员列表（兼容数组/字符串/旧数据）
        formatMembers(members) {
            if (!members) return '';
            if (Array.isArray(members)) return members.join('、');
            return String(members);
        },
        // 显示文本兜底：仅用于前端展示，避免乱码影响界面
        isLikelyGarbledText(text) {
            const raw = String(text || '').trim();
            console.log('🔍 检测文本:', JSON.stringify(raw), '长度:', raw.length);
            console.log('  - 包含中文字符:', /[\u4e00-\u9fa5]/.test(raw));
            
            if (!raw) return true;
            if (/[�]/.test(raw)) return true;
            if (/[<>]/.test(raw) || /^["'=\s_\-]+$/.test(raw)) return true;
            // 检查是否包含中文字符
            if (/[\u4e00-\u9fa5]/.test(raw)) return false;
            // 检查是否包含常见的中文乱码模式（如²âÊÔ）
            if (/[\x80-\xFF]{2,}/.test(raw)) return true;
            // 检查是否是明显的乱码模式（如"hb"这样的简短字符串）
            if (raw.length <= 2 && /^[a-zA-Z0-9]+$/.test(raw)) return true;
            const qCount = (raw.match(/\?/g) || []).length;
            return qCount >= 2;
        },
        normalizeDisplayText(value, fallback = '') {
            const raw = String(value ?? '').trim();
            if (!raw) return fallback;
            return this.isLikelyGarbledText(raw) ? fallback : raw;
        },
        displayTopicText(topic, classCode = '') {
            const fallback = classCode ? `课堂 #${classCode}` : '未命名课堂';
            return this.normalizeDisplayText(topic, fallback);
        },
        displayScoreLevelText(level, score = 0) {
            const safeLevel = this.normalizeDisplayText(level, '');
            if (safeLevel) return safeLevel;
            const n = Number(score) || 0;
            if (n >= 80) return '优秀';
            if (n >= 60) return '良好';
            return '待提高';
        },
        // 加载活动小组(教师用)
        async loadActiveGroups() {
            if (this.currentUser.role !== 'teacher') return;
            try {
                const res = await axios.get(`/api/active-groups/${this.currentUser.id}`);
                if (res.data.status === 'success') {
                    this.activeGroups = res.data.groups || [];
                }
            } catch(e) {
                console.error('加载小组失败:', e);
            }
        },
        // 进入小组查看(教师)
        async enterGroupView(group) {
            this.viewingGroupId = group.meeting_id;
            this.meetingId = group.meeting_id;
            this.currentTopic = this.displayTopicText(group.topic, group.class_code);
            this.classForm.class_code = group.class_code;
            this.joined = true;
            this.pageState = 'classroom';
            this.classStartTime = Date.now();
            this.startTimer();
            // 加载目标和图谱数据
            await this.loadClassroomData(group.meeting_id);
            // 只连接WebSocket查看，不开启视频
            this.connectWs();
        },
        // 学生进入已加入的课堂
        async enterClassFromHistory(classItem) {
            this.meetingId = classItem.meeting_id;
            this.currentTopic = this.displayTopicText(classItem.topic, classItem.class_code);
            this.classForm.class_code = classItem.class_code;
            this.joined = true;
            this.pageState = 'classroom';
            this.classStartTime = Date.now();
            this.startTimer();
            // 加载目标和图谱数据
            await this.loadClassroomData(classItem.meeting_id);
            // 连接WebSocket并开启视频
            this.$nextTick(async ()=>{ await this.startSmartMedia(); this.connectWs(); this.connectAsrWs(); this._joinAgoraChannel(); });
        },
        // 教师从课堂管理进入课堂
        async enterClassAsTeacher(cls) {
            this.meetingId = cls.meeting_id;
            this.currentTopic = this.displayTopicText(cls.topic, cls.class_code);
            this.classForm.class_code = cls.class_code;
            this.joined = true;
            this.pageState = 'classroom';
            this.classStartTime = Date.now();
            this.startTimer();
            this.startSilenceChecks();
            // 加载目标和图谱数据
            await this.loadClassroomData(cls.meeting_id);
            this.$nextTick(async () => {
                await this.startSmartMedia();
                this.connectWs();
                this.connectAsrWs();
                this._joinAgoraChannel();
            });
        },
        // 教师从课堂管理结束课堂
        async endClassFromManage(cls) {
            if (!confirm(`确定要结束课堂「${this.displayTopicText(cls.topic, cls.class_code)}」吗？所有学生将被断开。`)) return;
            try {
                const fd = new FormData();
                fd.append('meeting_id', cls.meeting_id);
                fd.append('username', this.currentUser.student_id);
                const res = await axios.post('/api/end-class', fd);
                if (res.data.status === 'success') {
                    this.showAlert('课堂已结束', 'success', '提示');
                    cls.status = 'ended';
                    this.$forceUpdate();
                } else {
                    this.showAlert(res.data.message || '结束失败', 'error', '错误');
                }
            } catch (e) {
                this.showAlert('结束课堂失败: ' + (e.message || e), 'error', '错误');
            }
        },
        // ===== 教师端专属方法 =====
        // 加载教师统计数据
        async loadTeacherStats() {
            if (this.currentUser.role !== 'teacher') return;
            try {
                const res = await axios.get(`/api/teacher-stats/${this.currentUser.id}`);
                if (res.data.status === 'success') {
                    this.teacherStats = res.data.stats;
                }
            } catch(e) {
                console.error('加载教师统计失败:', e);
            }
        },
        // 加载教师创建的所有课堂
        async loadTeacherClasses() {
            if (this.currentUser.role !== 'teacher') return;
            try {
                const res = await axios.get(`/api/teacher-classes/${this.currentUser.id}`);
                if (res.data.status === 'success') {
                    this.teacherClasses = res.data.classes || [];
                }
            } catch(e) {
                console.error('加载课堂列表失败:', e);
            }
        },
        // 查看课堂详情(小组情况)
        async viewClassDetail(cls) {
            this.selectedClass = cls;
            try {
                const res = await axios.get(`/api/class-groups/${cls.meeting_id}`);
                if (res.data.status === 'success') {
                    this.classDetailGroups = res.data.groups || [];
                }
            } catch(e) {
                console.error('加载小组详情失败:', e);
            }
        },
        // 关闭课堂详情
        closeClassDetail() {
            this.selectedClass = null;
            this.classDetailGroups = [];
        },
        // 加载所有学生报告
        async loadAllStudentReports(options = {}) {
            if (this.currentUser.role !== 'teacher') return;
            if (!options.force && this.studentReportsLoaded) return;
            if (this.studentReportsLoading) return;
            this.studentReportsLoading = true;
            try {
                const res = await axios.get(`/api/all-student-reports/${this.currentUser.id}`);
                if (res.data.status === 'success') {
                    this.allStudentReports = res.data.reports || [];
                    this.studentReportsLoaded = true;
                    this.writeLobbyCache('allStudentReports', this.allStudentReports);
                }
            } catch(e) {
                console.error('加载学生报告失败:', e);
                if (options.force) this.showAlert('加载学生报告失败: ' + (e.response?.data?.message || e.message), 'error', '错误');
            } finally {
                this.studentReportsLoading = false;
            }
        },
        // 查看学生报告详情
        viewStudentReport(report) {
            // 在新窗口打开报告详情
            this.showAlert(`查看 ${report.student_name} 的报告:\n发言次数: ${report.speech_count}\n专注度: ${report.avg_relevance}%\n评价: ${report.summary || '无'}`, 'info', '学生报告');
        },
        // 下载学生报告PDF
        async downloadStudentPDF(report) {
            try {
                const formData = new FormData();
                formData.append('meeting_id', report.meeting_id);
                formData.append('user_id', report.user_id);
                const res = await axios.post('/api/generate-pdf-report', formData);
                if (res.data.status === 'success') {
                    window.open(res.data.pdf_url, '_blank');
                } else {
                    this.showAlert(res.data.message || 'PDF生成失败', 'error', '错误');
                }
            } catch(e) {
                this.showAlert('PDF生成错误: ' + e.message, 'error', '错误');
            }
        },
        // 处理模板上传
        async handleTemplateUpload(event) {
            const file = event.target.files[0];
            if (!file) return;
            
            // 限制文件大小 5MB
            if (file.size > 5 * 1024 * 1024) {
                this.showAlert('模板文件不能超过5MB', 'warning', '提示');
                return;
            }
            
            const formData = new FormData();
            formData.append('template_file', file);
            formData.append('teacher_id', this.currentUser.id);
            
            try {
                const res = await axios.post('/api/upload-report-template', formData);
                if (res.data.status === 'success') {
                    this.customTemplate = {
                        id: res.data.template_id,
                        filename: res.data.filename,
                        path: res.data.template_path,
                        uploadTime: new Date().toLocaleString()
                    };
                    this.showAlert('模板上传成功！', 'success', '成功');
                } else {
                    this.showAlert('上传失败: ' + res.data.message, 'error', '错误');
                }
            } catch(e) {
                this.showAlert('上传错误: ' + e.message, 'error', '错误');
            }
        },
        // 加载教师模板
        async loadTeacherTemplates() {
            if (this.currentUser.role !== 'teacher') return;
            try {
                const res = await axios.get(`/api/teacher-templates/${this.currentUser.id}`);
                if (res.data.status === 'success' && res.data.templates.length > 0) {
                    // 找到默认模板
                    const defaultTpl = res.data.templates.find(t => t.is_default === 1) || res.data.templates[0];
                    this.customTemplate = {
                        id: defaultTpl.id,
                        filename: defaultTpl.filename,
                        path: defaultTpl.filepath,
                        uploadTime: defaultTpl.created_at
                    };
                }
            } catch(e) {
                console.error('加载模板失败:', e);
            }
        },
        // 移除模板
        async removeTemplate() {
            if (!this.customTemplate || !this.customTemplate.id) {
                this.customTemplate = null;
                return;
            }
            
            if (await this.showConfirm('确定要删除自定义模板吗？删除后将使用默认模板生成报告。', '确认删除')) {
                try {
                    await axios.delete(`/api/delete-template/${this.customTemplate.id}`);
                    this.customTemplate = null;
                    this.showAlert('模板已删除', 'success', '成功');
                } catch(e) {
                    this.showAlert('删除失败: ' + e.message, 'error', '错误');
                }
            }
        }
    },
    beforeDestroy() {
        this.cleanupVoiceprintRecorder();
        this.resetVoiceprintSample();
        this.stopBrowserSpeechRecognition();
        if (this.timerInterval) {
            clearInterval(this.timerInterval);
        }
        if (this.graphUpdateInterval) {
            clearInterval(this.graphUpdateInterval);
        }
        if (this.subtitleTimer) {
            clearTimeout(this.subtitleTimer);
        }
        // 清理统计刷新定时器
        if (this.statsRefreshTimer) {
            clearInterval(this.statsRefreshTimer);
        }
        if (this.emotionRefreshTimer) {
            clearInterval(this.emotionRefreshTimer);
        }
        if (this.asrHealthTimer) {
            clearTimeout(this.asrHealthTimer);
        }
        if (this.tdWindowDebounceTimer) {
            clearTimeout(this.tdWindowDebounceTimer);
        }
    },
    watch: {
        showKnowledgeGraph(newVal) {
            if (newVal && !this.knowledgeGraphData) {
                this.loadKnowledgeGraph();
            } else if (newVal && this.knowledgeGraphData) {
                this.renderKnowledgeGraph();
            }
        }
    }
})
