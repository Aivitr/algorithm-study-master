(function () {
    const METRICS = [
        { key: 'participation', label: '参与度', icon: 'fa-users', tip: '成员是否都有发言机会' },
        { key: 'internal_cohesion', label: '内部凝聚力', icon: 'fa-link', tip: '组内语义与互动是否聚焦' },
        { key: 'overall_responsivity', label: '响应性', icon: 'fa-reply-all', tip: '发言是否被其他成员接续' },
        { key: 'social_impact', label: '社会影响', icon: 'fa-bullhorn', tip: '个体发言对群体的影响程度' },
        { key: 'newness', label: '信息新度', icon: 'fa-lightbulb', tip: '讨论是否持续带来新内容' },
        { key: 'communication_density', label: '沟通密度', icon: 'fa-comments', tip: '单位时间内的交流丰富程度' },
    ];

    const COLORS = ['#3E8E91', '#4BAA7A', '#D9A441', '#4B86C5', '#D66565', '#8A6FB1'];

    // GCA 看板已下线，预填问题不再引用 GCA 口径；LEGACY_* 只用于把旧文案就地纠正。
    const LEGACY_TEACHER_QUESTION =
        '请结合课堂事实与 GCA 六项指标，分析当前小组协作情况，指出需要关注的成员，并给出可执行的干预建议。';
    const TEACHER_QUESTION =
        '请结合课堂事实，分析当前小组协作情况，指出需要关注的成员，并给出可执行的干预建议。';
    const STUDENT_QUESTION =
        '请结合课堂发言，说说我们小组现在的协作情况，指出可以改进的地方，并给出具体建议。';

    window.ClassroomInsightsMixin = {
        data() {
            return {
                insightSection: 'gca',
                insightCharts: {},
                gcaLoading: false,
                gcaLoaded: false,
                gcaError: '',
                gcaDashboard: null,
                gcaMemberNames: {},
                agentQuestion: TEACHER_QUESTION,
                myNotes: '',
                todoState: {},
                aiDrawerPos: null,
                followUpText: '',
                followUpHistory: [],
                editingScript: {},
                openSpeech: {},
                evidenceHit: '',
                starred: {},
                speaking: false,
                agentLoading: false,
                agentError: '',
                agentResult: null,
                agentTranscriptMap: {},
                agentEvidenceLoading: false,
                agentConfirming: {},
                agentIgnoring: {},
                agentActionHistory: [],
                agentActionHistoryLoading: false,
                agentLastRunAt: '',
                agentTools: [],
                agentToolsLoading: false,
                agentToolsError: '',
                agentToolsLoaded: false,
                evidenceOpen: {},
                quizHistory: null,
                quizLoading: false,
                quizError: '',
                reportGenerating: false,
            };
        },
        computed: {
            gcaMetricCards() {
                const metrics = this.gcaDashboard && this.gcaDashboard.group_metrics || {};
                return METRICS.map((metric) => {
                    const raw = metrics[metric.key] || {};
                    const numeric = raw.mean === null || raw.mean === undefined ? NaN : Number(raw.mean);
                    return {
                        ...metric,
                        value: Number.isFinite(numeric) ? numeric : null,
                        min: raw.min === null || raw.min === undefined ? null : Number(raw.min),
                        max: raw.max === null || raw.max === undefined ? null : Number(raw.max),
                        std: raw.std === null || raw.std === undefined ? null : Number(raw.std),
                        count: Number(raw.count || 0),
                    };
                });
            },
            gcaStudentRows() {
                const metrics = this.gcaDashboard && this.gcaDashboard.student_metrics || {};
                return Object.entries(metrics).map(([userId, values]) => ({
                    userId,
                    name: this.gcaMemberNames[String(userId)] || `学生 ${userId}`,
                    participation: this._metricPercent(values.participation),
                    internal_cohesion: this._metricPercent(values.internal_cohesion),
                    overall_responsivity: this._metricPercent(values.overall_responsivity),
                    social_impact: this._metricPercent(values.social_impact),
                    newness: this._metricPercent(values.newness),
                    communication_density: this._metricPercent(values.communication_density),
                }));
            },
            gcaFixedWindows() {
                return this.gcaDashboard && this.gcaDashboard.timeline
                    && Array.isArray(this.gcaDashboard.timeline.fixed_5min)
                    ? this.gcaDashboard.timeline.fixed_5min : [];
            },
            /** 没有真实结果时用示例数据填充面板（标「示例」，不写库）。 */
            isDemoAnalysis() {
                return !(this.agentResult && this.agentResult.analysis);
            },
            agentAnalysis() {
                if (this.agentResult && this.agentResult.analysis) return this.agentResult.analysis;
                return this.isTeacherRole ? this.demoGroupAnalysis : this.demoPersonalAnalysis;
            },
            /** 教师：群体示例，数字来自当前课堂的发言。 */
            demoGroupAnalysis() {
                const stats = this.groupQuickStats || {};
                const silent = this.silentMembers || [];
                return {
                    summary:
                        `本组 ${stats.speakers || 0} 名学生已产生 ${stats.speeches || 0} 条发言，`
                        + `平均质量 ${stats.avgQuality === '—' ? '暂无' : stats.avgQuality} 分。`
                        + (silent.length ? `其中 ${silent.join('、')} 尚未开口。` : '')
                        + '尚未运行 AI 分析，点击分析按钮后生成基于真实发言的结论。',
                    findings: [],
                    interventions: [],
                    metrics_reading: [],
                    data_gaps: ['尚未运行 AI 分析'],
                    unsupported_claims: [],
                };
            },
            /** 学生：尚未分析时只展示真实统计，不编造结论。 */
            demoPersonalAnalysis() {
                const stats = this.myStats || {};
                return {
                    summary:
                        `你在本组共发言 ${stats.count || 0} 条，占全组 ${stats.share || '—'}，`
                        + `平均质量 ${stats.avgQuality === '—' ? '暂无' : stats.avgQuality} 分，`
                        + `主要情绪是 ${stats.topEmotion || '—'}。`
                        + '尚未生成个人反馈，点击“分析我的表现”查看。',
                    findings: [],
                    interventions: [],
                    metrics_reading: [],
                    data_gaps: ['尚未生成个人反馈'],
                    unsupported_claims: [],
                };
            },
            agentFindings() {
                return this.agentAnalysis && Array.isArray(this.agentAnalysis.findings)
                    ? this.agentAnalysis.findings : [];
            },
            agentInterventions() {
                return this.agentAnalysis && Array.isArray(this.agentAnalysis.interventions)
                    ? this.agentAnalysis.interventions : [];
            },
            agentEvidenceRefs() {
                const refs = new Set();
                const analysis = this.agentAnalysis;
                if (!analysis) return [];
                (analysis.metrics_reading || []).forEach((item) => (item.evidence || []).forEach((ref) => refs.add(ref)));
                (analysis.findings || []).forEach((item) => (item.evidence || []).forEach((ref) => refs.add(ref)));
                (analysis.interventions || []).forEach((item) => (item.evidence || []).forEach((ref) => refs.add(ref)));
                return Array.from(refs).map((ref) => this._describeEvidence(ref));
            },
            gcaAvailable() {
                return !!(this.gcaDashboard && this.gcaDashboard.ok);
            },
            gcaMetadataRows() {
                const meta = this.gcaDashboard && this.gcaDashboard.metadata;
                if (!meta || typeof meta !== 'object') return [];
                const LABELS = {
                    n_utterances: '发言条数',
                    n_speakers: '参与人数',
                    duration_seconds: '课堂时长（秒）',
                    empty_text_count: '空文本条数',
                    'lsa.requested_dimensions': '请求 LSA 维度',
                    'lsa.actual_dimensions': '实际 LSA 维度',
                    'tokenization.scheme': '分词方案',
                    'tokenization.total_tokens': '总词数',
                    'tokenization.tokens_per_utterance': '每条均词数',
                    'gca_config.spanning_window': '跨度窗口',
                    'gca_config.zero_vector_policy': '零向量策略',
                    'gca_config.word_count': '词数口径',
                    engine_version: '引擎版本',
                    computed_at: '计算时间',
                };
                const rows = [];
                const walk = (obj, prefix) => {
                    Object.entries(obj || {}).forEach(([key, value]) => {
                        if (value === null || value === undefined) return;
                        const path = prefix ? prefix + '.' + key : key;
                        if (typeof value === 'object' && !Array.isArray(value)) {
                            walk(value, path);
                        } else {
                            rows.push({
                                key: path,
                                label: LABELS[path] || LABELS[key] || path,
                                value: Array.isArray(value) ? value.join(', ') : String(value),
                            });
                        }
                    });
                };
                walk(meta, '');
                return rows.slice(0, 12);
            },
            agentConfirmedCount() {
                return this.agentInterventions.filter((item) => item.confirmed).length;
            },
            agentPendingCount() {
                return this.agentInterventions.length - this.agentConfirmedCount;
            },
            /** GCA 看板已下线（教师与学生共用「Agent / 证据与动作」两页签）。 */
            insightShowsGca() {
                return false;
            },
            /** 抽屉位置：默认贴右下，拖动后按坐标定位。 */
            aiDrawerStyle() {
                if (!this.aiDrawerPos) return {};
                return {
                    top: this.aiDrawerPos.top + 'px',
                    left: this.aiDrawerPos.left + 'px',
                    right: 'auto',
                    bottom: 'auto',
                };
            },
            /** 教师才有动作确认权限；界面上的确认入口按它判断。 */
            isTeacherRole() {
                return !!(this.currentUser && this.currentUser.role === 'teacher');
            },
            /** 快捷问题：教师问群体，学生问自己。 */
            presetQuestions() {
                if (this.isTeacherRole) {
                    return ['谁还没发言', '观点是否收敛', '下一阶段怎么推进'];
                }
                return ['我的发言质量如何', '我的观点被回应了吗', '我下一步能做什么'];
            },
            /** 一条发言都没有的成员（教师视图里用来点名）。 */
            silentMembers() {
                const spoken = new Set((this.transcriptItems || []).map((item) => item.username));
                const all = (this.onlineMembers || [])
                    .map((m) => (typeof m === 'string' ? m : (m && (m.username || m.name)) || ''))
                    .filter(Boolean);
                return all.filter((name) => !spoken.has(name)).slice(0, 2);
            },
            /** 把 /api/transcripts 的原始项归一化：接口给的是 id / username，不是 speaker / evidence_id。 */
            transcriptItems() {
                return Object.entries(this.agentTranscriptMap || {}).map(([ref, item]) => ({
                    ref,
                    username: item.username || item.speaker || '',
                    text: item.text || '',
                    qualityScore: Number.isFinite(Number(item.quality_score)) ? Number(item.quality_score) : null,
                    feedback: item.quality_feedback || '',
                    emotion: item.emotion || '',
                    timestamp: item.timestamp || 0,
                }));
            },
            /** 我的发言对应的证据编号集合。 */
            myEvidenceRefs() {
                const refs = new Set();
                (this.myTranscripts || []).forEach((item) => refs.add(item.ref));
                return refs;
            },
            /** 我的发言明细（时间正序）。 */
            myTranscripts() {
                const name = this.currentUser && this.currentUser.username;
                if (!name) return [];
                return (this.transcriptItems || [])
                    .filter((item) => item.username === name)
                    .sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));
            },
            /** 我的数据：条数 / 占比 / 平均质量 / 主要情绪 / 质量走势。 */
            myStats() {
                const mine = this.myTranscripts || [];
                const all = this.transcriptItems || [];
                const qualities = mine
                    .map((item) => item.qualityScore)
                    .filter((value) => Number.isFinite(value));
                const emotions = {};
                mine.forEach((item) => {
                    const key = item.emotion || '未标注';
                    emotions[key] = (emotions[key] || 0) + 1;
                });
                const topEmotion = Object.entries(emotions).sort((a, b) => b[1] - a[1])[0];
                const avg = qualities.length
                    ? Math.round(qualities.reduce((sum, value) => sum + value, 0) / qualities.length)
                    : null;
                return {
                    count: mine.length,
                    share: all.length ? Math.round((mine.length / all.length) * 100) + '%' : '—',
                    avgQuality: avg === null ? '—' : avg,
                    topEmotion: topEmotion ? topEmotion[0] : '—',
                    series: qualities.slice(-8).map((value) => Math.max(6, Math.min(100, value))),
                };
            },
            /** 教师端只留 3 条群体信号，避免面板过长。 */
            groupFindings() {
                return (this.agentFindings || []).slice(0, 3);
            },
            /** 学生端：证据落在我身上的发现。 */
            personalFindings() {
                const refs = this.myEvidenceRefs;
                return (this.agentFindings || []).filter((finding) =>
                    (finding.evidence || []).some((ref) => refs.has(ref))
                );
            },
            /** 学生端：指向我（或引用我发言）的干预动作。 */
            personalInterventions() {
                const refs = this.myEvidenceRefs;
                const name = this.currentUser && this.currentUser.username;
                return (this.agentInterventions || []).filter((action) => {
                    const target = String(action.target || '').trim();
                    const hitName = name && target.includes(name);
                    const hitRef = (action.evidence || []).some((ref) => refs.has(ref));
                    // 面向「小组」的动作对我也成立，否则学生常常一条都看不到
                    const hitGroup = !target || target === '小组';
                    return hitName || hitRef || hitGroup;
                });
            },
            /** 学生端待办：动作卡转成可勾选清单，状态存本机。 */
            myTodos() {
                return (this.personalInterventions || []).map((action, index) => {
                    const key = this._todoKey(action, index);
                    return {
                        key,
                        action: action.action,
                        script: action.script,
                        done: !!this.todoState[key],
                    };
                });
            },
            /** 成员总数：优先用在线名单，拿不到时退回「已发言人数」，避免显示 0。 */
            memberCount() {
                const online = (this.onlineMembers || []).length;
                const spoken = (this.groupQuickStats && this.groupQuickStats.speakers) || 0;
                return Math.max(online, spoken);
            },
            /** 参与率：已发言学生 / 成员总数。 */
            participationRate() {
                const total = this.memberCount || 0;
                if (!total) return 0;
                return Math.min(100, Math.round(((this.groupQuickStats.speakers || 0) / total) * 100));
            },
            /** 我发言占比的数值形式，给环形图用。 */
            myShareNum() {
                const share = String(this.myStats.share || '').replace('%', '');
                const num = Number(share);
                return Number.isFinite(num) ? Math.min(100, num) : 0;
            },
            /** 最近 5 条我的发言（倒序展示更近的在后）。 */
            recentMyTranscripts() {
                return (this.myTranscripts || []).slice(-5);
            },
            todoDoneCount() {
                return (this.myTodos || []).filter((item) => item.done).length;
            },
            todoPercent() {
                const total = (this.myTodos || []).length;
                return total ? Math.round((this.todoDoneCount / total) * 100) : 0;
            },
            /** 教师端速览：参与人数 / 发言条数 / 平均质量。 */
            groupQuickStats() {
                const items = this.transcriptItems || [];
                const speakers = new Set(items.map((item) => item.username).filter(Boolean));
                const qualities = items
                    .map((item) => item.qualityScore)
                    .filter((value) => Number.isFinite(value));
                const avg = qualities.length
                    ? Math.round(qualities.reduce((sum, value) => sum + value, 0) / qualities.length)
                    : null;
                return {
                    speakers: speakers.size,
                    speeches: items.length,
                    avgQuality: avg === null ? '—' : avg,
                };
            },
        },
        methods: {
            /** 按住抽屉标题栏拖动窗口（限制在视口内）。 */
            startAiDrawerDrag(event) {
                const drawer = event.currentTarget.closest('.ai-drawer');
                if (!drawer) return;
                event.preventDefault();
                const rect = drawer.getBoundingClientRect();
                const offsetX = event.clientX - rect.left;
                const offsetY = event.clientY - rect.top;
                this.aiDrawerPos = { top: Math.round(rect.top), left: Math.round(rect.left) };
                const move = (ev) => {
                    const maxLeft = window.innerWidth - rect.width - 8;
                    const maxTop = window.innerHeight - 80;
                    const left = Math.min(Math.max(8, ev.clientX - offsetX), Math.max(8, maxLeft));
                    const top = Math.min(Math.max(8, ev.clientY - offsetY), Math.max(8, maxTop));
                    this.aiDrawerPos = { top: Math.round(top), left: Math.round(left) };
                };
                const up = () => {
                    window.removeEventListener('mousemove', move);
                    window.removeEventListener('mouseup', up);
                    document.body.style.userSelect = '';
                };
                document.body.style.userSelect = 'none';
                window.addEventListener('mousemove', move);
                window.addEventListener('mouseup', up);
            },
            /** AI 页签入口：Agent 面板所在，进入时补齐证据/成员/工具数据。 */
            openAgentTab() {
                this.classroomTab = 'ai';
                this._hydrateAgentQuestion();
                this.restoreStudentState();
                if (this.isTeacherRole) this.loadAgentTools();
            },
            openInsightPanel(section) {
                // 「分析」页签已取消：Agent 能力并入 AI 页签
                this.classroomTab = 'ai';
                this.insightSection = this._normalizeInsightSection(section);
                this._hydrateAgentQuestion();
                this.restoreStudentState();
                this.$nextTick(() => setTimeout(() => this._ensureInsightSection(), 100));
            },
            /** 预填问题不再出现 GCA 口径；用户改过就不再覆盖。 */
            _hydrateAgentQuestion() {
                const text = String(this.agentQuestion || '').trim();
                const defaults = [TEACHER_QUESTION, STUDENT_QUESTION, LEGACY_TEACHER_QUESTION];
                if (!text || defaults.includes(text)) {
                    this.agentQuestion = this.isTeacherRole ? TEACHER_QUESTION : STUDENT_QUESTION;
                }
            },
            _normalizeInsightSection(section) {
                const value = section || 'agent';
                return value === 'gca' ? 'agent' : value;
            },
            switchInsightSection(section) {
                this.insightSection = this._normalizeInsightSection(section);
                this.$nextTick(() => setTimeout(() => this._ensureInsightSection(), 80));
            },
            _ensureInsightSection() {
                if (this.insightSection === 'gca') {
                    this.insightSection = 'agent';
                }
                if (this.insightSection === 'agent') {
                    this.loadAgentTools();
                } else if (this.insightSection === 'evidence') {
                    this.loadAgentTranscriptEvidence();
                }
            },
            async loadGcaInsights() {
                // GCA 看板已下线：不再请求 /metrics 与 /class-groups，函数留作兼容旧调用点
                return;
            },
            /** 证据编号 → 中文显示（指标类走中文名，发言类保留 T# 编号）。 */
            refLabel(ref) {
                const value = String(ref || '');
                if (value.startsWith('M:')) {
                    const metric = METRICS.find((item) => item.key === value.slice(2));
                    return metric ? metric.label : '课堂指标';
                }
                return value;
            },
            /** 工具函数名 → 通俗中文名。 */
            toolLabel(name) {
                const map = {
                    get_classroom_transcripts: '读取课堂发言',
                    get_classroom_statistics: '读取课堂统计',
                    get_classroom_knowledge: '读取课堂知识',
                    get_class_metrics: '读取课堂指标',
                };
                return map[name] || '课堂数据';
            },
            /** 工具可用状态 → 中文。 */
            toolStateLabel(state) {
                const map = { running: '上课中', ended: '已结束', paused: '已暂停' };
                return map[state] || '可用';
            },
            /** 头像文字：取称呼首字（王同学 → 王）。 */
            shortName(name) {
                const text = String(name || '').trim();
                if (!text) return '组';
                return text.slice(0, 1);
            },
            _todoKey(action, index) {
                const mid = this.meetingId || 0;
                const uid = (this.currentUser && this.currentUser.id) || 0;
                return `${mid}:${uid}:${index}:${action.action || ''}`;
            },
            _studentStorageKey(kind) {
                const mid = this.meetingId || 0;
                const uid = (this.currentUser && this.currentUser.id) || 0;
                return `insight:${kind}:${mid}:${uid}`;
            },
            /** 打开面板时加载证据；学生额外恢复本机的待办与笔记。 */
            restoreStudentState() {
                this.loadAgentTranscriptEvidence();
                try {
                    const rawStars = localStorage.getItem(this._studentStorageKey('stars'));
                    this.starred = rawStars ? JSON.parse(rawStars) : {};
                } catch (e) {
                    this.starred = {};
                }
                if (this.isTeacherRole) return;
                try {
                    const rawTodos = localStorage.getItem(this._studentStorageKey('todos'));
                    this.todoState = rawTodos ? JSON.parse(rawTodos) : {};
                    const rawNotes = localStorage.getItem(this._studentStorageKey('notes'));
                    this.myNotes = rawNotes || '';
                } catch (e) {
                    this.todoState = {};
                    this.myNotes = '';
                }
            },
            toggleMyTodo(key) {
                const next = { ...this.todoState };
                if (next[key]) {
                    delete next[key];
                } else {
                    next[key] = true;
                }
                this.todoState = next;
                try {
                    localStorage.setItem(this._studentStorageKey('todos'), JSON.stringify(next));
                } catch (e) {
                    /* 隐私模式下写不进去，忽略 */
                }
            },
            saveMyNotes() {
                try {
                    localStorage.setItem(this._studentStorageKey('notes'), this.myNotes || '');
                } catch (e) {
                    /* 同上 */
                }
            },
            /** 预置问题：点一下直接跑，不用手打。 */
            runPresetQuestion(question) {
                if (this.agentLoading) return;
                this.agentQuestion = question;
                this.runClassroomAgent();
            },
            /** 就某一条自己的发言追问。 */
            askAboutTranscript(item) {
                if (!item || this.agentLoading) return;
                this.agentQuestion = `请只针对我的这条发言 ${item.evidence_id}：「${item.text}」，说明我表达得怎么样、可以怎么改进。`;
                this.runClassroomAgent();
            },
            /** 多轮追问：把历史和本次问题拼成一次请求，答案记进对话线。 */
            async askFollowUp() {
                const text = String(this.followUpText || '').trim();
                if (!text || this.agentLoading) return;
                const history = this.followUpHistory
                    .slice(-2)
                    .map((turn) => `上一轮问答｜问：${turn.question}｜答：${turn.answer}`)
                    .join('\n');
                const question = (history ? history + '\n' : '')
                    + `新问题：${text}\n只回答这个问题，可以引用 T# 证据编号。`;
                this.followUpText = '';
                const previous = this.agentResult;
                await this.runClassroomAgent(question, { silent: true });
                const answer = (this.agentAnalysis && this.agentAnalysis.summary) || '';
                if (this.agentResult !== previous && answer) {
                    this.followUpHistory.push({ question: text, answer });
                }
            },
            /** 朗读结论/反馈（浏览器 SpeechSynthesis，前端本地能力）。 */
            speakSummary(text) {
                if (!('speechSynthesis' in window)) {
                    this.showAlert('当前浏览器不支持朗读', 'warning', '提示');
                    return;
                }
                const synth = window.speechSynthesis;
                if (this.speaking) {
                    synth.cancel();
                    this.speaking = false;
                    return;
                }
                const utter = new SpeechSynthesisUtterance(String(text || ''));
                utter.lang = 'zh-CN';
                utter.rate = 1.02;
                utter.onend = () => { this.speaking = false; };
                utter.onerror = () => { this.speaking = false; };
                this.speaking = true;
                synth.cancel();
                synth.speak(utter);
            },
            /** 星标收藏（本机保存）。 */
            isStarred(key) {
                return !!this.starred[key];
            },
            toggleStar(key) {
                const next = { ...this.starred };
                if (next[key]) {
                    delete next[key];
                } else {
                    next[key] = true;
                    this.showAlert('已收藏，下次还在这台设备上', 'success', '已收藏');
                }
                this.starred = next;
                try {
                    localStorage.setItem(this._studentStorageKey('stars'), JSON.stringify(next));
                } catch (e) {
                    /* 忽略隐私模式写入失败 */
                }
            },
            /** 话术就地编辑。 */
            startEditScript(index, action) {
                this.$set(this.editingScript, index, true);
                if (action) this._scriptBackup = action.script;
            },
            stopEditScript(index) {
                this.$set(this.editingScript, index, false);
            },
            /** 点信号里的 T# 跳到证据页并高亮该条。 */
            openEvidenceAt(ref) {
                this.evidenceHit = ref;
                this.$set(this.evidenceOpen, ref, true);
                this.$nextTick(() => {
                    setTimeout(() => {
                        const el = document.querySelector(`[data-ev="${ref}"]`);
                        if (el && el.scrollIntoView) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    }, 260);
                });
            },
            /** 展开「我的发言」的评分理由。 */
            toggleSpeech(ref) {
                this.$set(this.openSpeech, ref, !this.openSpeech[ref]);
            },
            /** 教师：给未发言成员生成可直接复制的话术。 */
            makeSilentScript() {
                const names = this.silentMembers || [];
                if (!names.length) {
                    this.showAlert('当前没有未发言成员', 'info', '提示');
                    return;
                }
                const script = `${names[0]}，刚才这轮你一直在听，能就「光照减弱后暗反应会怎样」补一句你的判断吗？说一个理由就行。`;
                this.agentQuestion = script;
                this.copyText(script, '点名话术');
            },
            /** 复制文本到剪贴板（http 页面下退化为 execCommand）。 */
            async copyText(text, label) {
                const value = String(text || '').trim();
                if (!value) {
                    this.showAlert('没有可复制的内容', 'warning', '提示');
                    return;
                }
                try {
                    if (navigator.clipboard && navigator.clipboard.writeText) {
                        await navigator.clipboard.writeText(value);
                    } else {
                        const area = document.createElement('textarea');
                        area.value = value;
                        document.body.appendChild(area);
                        area.select();
                        document.execCommand('copy');
                        document.body.removeChild(area);
                    }
                    this.showAlert(`${label || '内容'}已复制`, 'success', '已复制');
                } catch (e) {
                    this.showAlert('复制失败，请手动选择文本', 'error', '复制失败');
                }
            },
            /** 把本次分析导出成 markdown，纯前端生成。 */
            downloadAgentMarkdown() {
                const analysis = this.agentAnalysis;
                if (!analysis) {
                    this.showAlert('先运行一次分析', 'warning', '提示');
                    return;
                }
                const lines = [];
                lines.push(`# ${this.isTeacherRole ? '群体' : '个体'}分析 · 课堂 ${this.meetingId}`);
                lines.push('');
                lines.push(`- 生成时间：${new Date().toLocaleString('zh-CN')}`);
                lines.push(`- 提问：${this.agentQuestion}`);
                lines.push('');
                lines.push('## 结论');
                lines.push(analysis.summary || '');
                (analysis.findings || []).forEach((finding, index) => {
                    lines.push('');
                    lines.push(`## 发现 ${index + 1}（${finding.confidence || 'medium'}）`);
                    lines.push(finding.finding || '');
                    lines.push(`证据：${(finding.evidence || []).join('、')}`);
                });
                (analysis.interventions || []).forEach((action, index) => {
                    lines.push('');
                    lines.push(`## 动作 ${index + 1}：${action.action || ''}`);
                    lines.push(`对象：${action.target || '小组'}`);
                    lines.push(`话术：${action.script || ''}`);
                    lines.push(`预期：${action.expected || ''}`);
                    lines.push(`风险：${action.risk || ''}`);
                });
                const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' });
                const url = URL.createObjectURL(blob);
                const link = document.createElement('a');
                link.href = url;
                link.download = `classroom-${this.meetingId}-${this.isTeacherRole ? 'group' : 'me'}-analysis.md`;
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                URL.revokeObjectURL(url);
            },
            async runClassroomAgent(overrideQuestion, options) {
                if (!this.meetingId || this.agentLoading) return;
                const silent = !!(options && options.silent);
                const question = String(overrideQuestion || this.agentQuestion || '').trim();
                if (!question) {
                    return this.showAlert('请输入希望 Agent 分析的问题', 'warning', '提示');
                }
                this.agentLoading = true;
                this.agentError = '';
                this.agentResult = null;
                this.agentConfirming = {};
                try {
                    const response = await axios.post('/api/agents/group-analysis', {
                        meeting_id: this.meetingId,
                        question,
                        max_turns: 8,
                    }, { timeout: 120000, headers: { 'Content-Type': 'application/json' } });
                    this.agentResult = response.data;
                    if (!silent) this.followUpHistory = [];
                    this.agentLastRunAt = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
                    this.insightSection = 'agent';
                    await this.loadAgentTranscriptEvidence();
                } catch (error) {
                    this.agentError = error.response?.data?.detail || error.response?.data?.message || error.message || 'Agent 分析失败';
                } finally {
                    this.agentLoading = false;
                }
            },
            async loadAgentTranscriptEvidence(force = false) {
                if (!this.meetingId || this.agentEvidenceLoading) return;
                if (!force && Object.keys(this.agentTranscriptMap).length) return;
                this.agentEvidenceLoading = true;
                try {
                    const response = await axios.get(`/api/transcripts/${this.meetingId}?limit=500`);
                    const map = {};
                    (response.data.transcripts || []).forEach((item) => {
                        map[`T#${item.id}`] = item;
                    });
                    this.agentTranscriptMap = map;
                } catch (error) {
                    console.warn('证据原文加载失败', error);
                } finally {
                    this.agentEvidenceLoading = false;
                }
            },
            async confirmAgentAction(action, index) {
                if (!this.meetingId || this.agentConfirming[index]) return;
                const ok = await this.showConfirm(
                    `确认记录“${action.action || '干预动作'}”吗？确认后只记录教师审批，不会自动向学生发送。`,
                    '确认干预动作'
                );
                if (!ok) return;
                this.$set(this.agentConfirming, index, true);
                try {
                    const response = await axios.post('/api/agents/group-analysis/actions/confirm', {
                        meeting_id: this.meetingId,
                        target: action.target || '',
                        action: action.action || '',
                        script: action.script || '',
                        expected: action.expected || '',
                        risk: action.risk || '',
                        evidence: action.evidence || [],
                    }, { headers: { 'Content-Type': 'application/json' } });
                    this.$set(action, 'confirmed', true);
                    this.$set(action, 'confirmationId', response.data.confirmation_id);
                    await this.loadAgentActionHistory();
                    await this.showAlert('动作已确认并记录', 'success', '确认成功');
                } catch (error) {
                    await this.showAlert(
                        error.response?.data?.detail || error.response?.data?.message || error.message || '确认失败',
                        'error',
                        '确认失败'
                    );
                } finally {
                    this.$set(this.agentConfirming, index, false);
                }
            },
            async ignoreAgentAction(action, index) {
                if (!this.meetingId || this.agentIgnoring[index]) return;
                const ok = await this.showConfirm(
                    `忽略“${action.action || '干预动作'}”吗？忽略也会记录审计，不会向学生发送。`,
                    '忽略干预动作'
                );
                if (!ok) return;
                this.$set(this.agentIgnoring, index, true);
                try {
                    await axios.post('/api/agents/group-analysis/actions/ignore', {
                        meeting_id: this.meetingId,
                        target: action.target || '',
                        action: action.action || '',
                        script: action.script || '',
                        expected: action.expected || '',
                        risk: action.risk || '',
                        evidence: action.evidence || [],
                    }, { headers: { 'Content-Type': 'application/json' } });
                    this.$set(action, 'ignored', true);
                    await this.loadAgentActionHistory();
                    await this.showAlert('动作已忽略并记录', 'success', '操作成功');
                } catch (error) {
                    await this.showAlert(
                        error.response?.data?.detail || error.response?.data?.message || error.message || '忽略失败',
                        'error',
                        '忽略失败'
                    );
                } finally {
                    this.$set(this.agentIgnoring, index, false);
                }
            },
            async loadAgentActionHistory() {
                if (!this.isTeacherRole || !this.meetingId) return;
                this.agentActionHistoryLoading = true;
                try {
                    const response = await axios.get(
                        `/api/agents/group-analysis/actions/${this.meetingId}`,
                        { params: { limit: 20 } }
                    );
                    this.agentActionHistory = response.data.items || [];
                } catch (error) {
                    console.warn('动作历史加载失败', error);
                } finally {
                    this.agentActionHistoryLoading = false;
                }
            },
            formatAuditTime(value) {
                if (!value) return '';
                const date = new Date(value);
                return Number.isNaN(date.getTime())
                    ? String(value)
                    : date.toLocaleString('zh-CN', { hour12: false });
            },
            _describeEvidence(ref) {
                const value = String(ref || '');
                if (value.startsWith('T#')) {
                    const row = this.agentTranscriptMap[value];
                    const chars = row ? String(row.text || '').trim().length : 0;
                    const stamp = row && row.timestamp
                        ? new Date(Number(row.timestamp)).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
                        : '';
                    return {
                        ref: value,
                        kind: '课堂发言',
                        // 只给聚合后的描述，不回显原句（原句统一在「对话」页查看）
                        title: row
                            ? `${row.username || '学生'} 的一条发言`
                            : '课堂发言',
                        meta: row
                            ? [stamp, `质量 ${row.quality_score ?? '—'}`, `情绪 ${this.translateEmotion(row.emotion) || '—'}`, `${chars} 字`].filter(Boolean).join(' · ')
                            : '等待加载',
                    };
                }
                if (value.startsWith('M:')) {
                    const metric = METRICS.find((item) => item.key === value.slice(2));
                    return {
                        ref: value,
                        kind: '质量指标',
                        label: metric ? metric.label : '课堂指标',
                        title: metric ? `${metric.label}：${metric.tip}` : value.slice(2),
                        meta: 'GCA 确定性指标',
                    };
                }
                return { ref: value || 'E?', kind: '证据', title: value || '未命名证据', meta: '' };
            },
            _metricPercent(value) {
                const numeric = Number(value);
                return Number.isFinite(numeric) ? Math.round(Math.max(0, Math.min(1, numeric)) * 100) : null;
            },
            gcaMetricDisplay(metric) {
                if (metric.value === null) return '—';
                return `${Math.round(metric.value * 100)}%`;
            },
            gcaMetricMeta(metric) {
                if (metric.value === null) return metric.count ? `${metric.count} 个样本` : '暂无有效样本';
                const min = metric.min === null ? '—' : `${Math.round(metric.min * 100)}%`;
                const max = metric.max === null ? '—' : `${Math.round(metric.max * 100)}%`;
                const spread = metric.std === null || metric.std === undefined
                    ? ''
                    : ` · ±${Math.round(Number(metric.std) * 100)}%`;
                return `${min}–${max}${spread} · ${metric.count} 个样本`;
            },
            metricLabel(key) {
                const found = METRICS.find((item) => item.key === key);
                if (found) return found.label;
                return ({
                    speech_count: '发言数', participant_count: '参与人数',
                    interaction_count: '互动次数', average_quality: '平均质量',
                    emotion_count: '情绪记录', coverage_ratio: '目标覆盖率',
                })[key] || key;
            },
            agentMetricValue(item) {
                const value = Number(item.value);
                if (!Number.isFinite(value)) return '—';
                return item.layer === 'quality' ? Math.round(value * 100) + '%' : String(value);
            },
            renderInsightCharts() {
                if (this.classroomTab !== 'insight') return;
                this.$nextTick(() => {
                    this._renderGcaRadar();
                    this._renderGcaTimeline();
                    // 面板首次挂载时容器可能还没有宽度（v-show 隐藏态下 init 的
                    // ECharts 实例不会出 canvas）。布局稳定后再 resize 一次。
                    setTimeout(() => {
                        Object.values(this.insightCharts || {}).forEach((chart) => {
                            if (chart && !chart.isDisposed()) chart.resize();
                        });
                    }, 160);
                });
            },
            _ensureInsightChart(key, elementId) {
                const element = document.getElementById(elementId);
                if (!element || !element.offsetWidth) return null;
                let chart = this.insightCharts[key];
                // Vue 重渲染会换掉 DOM 节点：实例还在，但它挂的是已经脱离文档的
                // 旧节点，新节点上就永远画不出 canvas。此处按 getDom() 对齐后重建。
                if (chart && !chart.isDisposed() && chart.getDom() !== element) {
                    chart.dispose();
                    chart = null;
                }
                if (!chart || chart.isDisposed()) {
                    chart = echarts.init(element);
                    this.insightCharts[key] = chart;
                }
                return chart;
            },
            _renderGcaRadar() {
                const chart = this._ensureInsightChart('radar', 'gcaRadarChart');
                if (!chart) return;
                const values = this.gcaMetricCards.map((item) => item.value === null ? 0 : Math.round(item.value * 100));
                chart.setOption({
                    animationDuration: 500,
                    color: [COLORS[0]],
                    tooltip: { trigger: 'item' },
                    radar: {
                        center: ['50%', '55%'],
                        radius: '64%',
                        indicator: METRICS.map((item) => ({ name: item.label, max: 100 })),
                        splitNumber: 4,
                        axisName: { color: '#5f7078', fontSize: 9 },
                        splitLine: { lineStyle: { color: 'rgba(62,142,145,0.16)' } },
                        splitArea: { areaStyle: { color: ['rgba(75,163,176,0.04)', 'rgba(255,255,255,0.9)'] } },
                        axisLine: { lineStyle: { color: 'rgba(62,142,145,0.2)' } },
                    },
                    series: [{
                        type: 'radar',
                        symbolSize: 5,
                        data: [{ value: values, name: 'GCA 六指标' }],
                        lineStyle: { width: 2.5, color: COLORS[0] },
                        itemStyle: { color: COLORS[0] },
                        areaStyle: { color: 'rgba(62,142,145,0.16)' },
                    }],
                }, true);
            },
            _renderGcaTimeline() {
                const chart = this._ensureInsightChart('timeline', 'gcaTimelineChart');
                if (!chart) return;
                const windows = this.gcaFixedWindows;
                const labels = windows.map((item) => `${Math.round((item.start_second || 0) / 60)}-${Math.round((item.end_second || 0) / 60)}分`);
                const series = METRICS.map((metric, index) => ({
                    name: metric.label,
                    type: 'line',
                    smooth: true,
                    symbolSize: 4,
                    connectNulls: false,
                    data: windows.map((window) => {
                        const stats = window.group_metrics && window.group_metrics[metric.key];
                        const value = Number(stats && stats.mean);
                        return Number.isFinite(value) ? Math.round(value * 100) : null;
                    }),
                    lineStyle: { width: 2, color: COLORS[index] },
                    itemStyle: { color: COLORS[index] },
                }));
                chart.setOption({
                    animationDuration: 450,
                    color: COLORS,
                    tooltip: { trigger: 'axis' },
                    legend: { type: 'scroll', bottom: 0, itemWidth: 10, itemHeight: 7, textStyle: { fontSize: 9, color: '#64748b' } },
                    grid: { left: 34, right: 12, top: 18, bottom: 58 },
                    xAxis: {
                        type: 'category',
                        boundaryGap: false,
                        data: labels,
                        axisLabel: { fontSize: 9, color: '#718087' },
                        axisLine: { lineStyle: { color: '#cbd5da' } },
                    },
                    yAxis: {
                        type: 'value',
                        min: 0,
                        max: 100,
                        axisLabel: { fontSize: 9, color: '#718087', formatter: '{value}%' },
                        splitLine: { lineStyle: { color: '#edf2f4' } },
                    },
                    series,
                    graphic: windows.length ? [] : [{
                        type: 'text', left: 'center', top: 'middle',
                        style: { text: '暂无时间窗口数据', fill: '#9ca3af', fontSize: 11 },
                    }],
                }, true);
            },
            loadAgentTools(force = false) {
                if (this.agentToolsLoading) return;
                if (this.agentToolsLoaded && !force) {
                    this._drawAgentToolStates();
                    return;
                }
                this.agentToolsLoading = true;
                this.agentToolsError = '';
                axios.get('/api/agents/group-analysis/tools')
                    .then((response) => {
                        this.agentTools = Array.isArray(response.data && response.data.tools)
                            ? response.data.tools : [];
                        this.agentToolsLoaded = true;
                        this.$nextTick(() => this._drawAgentToolStates());
                    })
                    .catch((error) => {
                        this.agentToolsError = error.response?.data?.detail || error.message || '工具清单加载失败';
                    })
                    .finally(() => {
                        this.agentToolsLoading = false;
                    });
            },
            _drawAgentToolStates() {
                // 工具清单本身不需要图表，保留钩子以便将来扩展状态门禁可视化
            },
            toggleEvidence(ref) {
                if (!ref) return;
                this.$set(this.evidenceOpen, ref, !this.evidenceOpen[ref]);
            },
            loadQuizHistory(force = false) {
                const user = this.currentUser;
                if (!user || !user.id) return;
                if (this.quizLoading) return;
                if (this.quizHistory && !force) return;
                this.quizLoading = true;
                this.quizError = '';
                axios.get(`/api/student-quiz-history/${user.id}`)
                    .then((response) => {
                        this.quizHistory = response.data && response.data.status === 'success'
                            ? response.data : null;
                    })
                    .catch((error) => {
                        this.quizError = error.response?.data?.detail || error.message || '答题统计加载失败';
                    })
                    .finally(() => {
                        this.quizLoading = false;
                    });
            },
            async generateMyReport() {
                if (this.reportGenerating) return;
                const user = this.currentUser;
                if (!user || !user.id) return;
                if (!this.meetingId) {
                    return this.showAlert('请先进入课堂再生成报告', 'warning', '提示');
                }
                this.reportGenerating = true;
                try {
                    const form = new FormData();
                    form.append('meeting_id', this.meetingId);
                    form.append('user_id', user.id);
                    const response = await axios.post('/api/generate-report', form, { timeout: 180000 });
                    const body = response.data || {};
                    if (body.status === 'success') {
                        this.showAlert('本轮学习报告已生成', 'success', '生成成功');
                        await this.loadMyReports({ force: true });
                    } else if (body.status === 'no_new_data') {
                        this.showAlert(body.message || '本次课堂没有你的新发言，暂不生成新报告', 'warning', '提示');
                    } else {
                        this.showAlert(body.message || '报告生成失败', 'error', '提示');
                    }
                } catch (error) {
                    this.showAlert(
                        error.response?.data?.message || error.message || '报告生成失败',
                        'error',
                        '错误'
                    );
                } finally {
                    this.reportGenerating = false;
                }
            },
        },
        watch: {
            activeTab(newValue) {
                if (newValue === 'report') {
                    this.$nextTick(() => setTimeout(() => this.loadQuizHistory(), 120));
                }
            },
            classroomTab(newValue) {
                if (newValue !== 'ai') return;
                this.restoreStudentState();
                if (this.isTeacherRole) {
                    this.loadAgentTools();
                    this.loadAgentActionHistory();
                }
            },
            meetingId() {
                this.gcaLoaded = false;
                this.agentResult = null;
                this.followUpHistory = [];
                this.agentActionHistory = [];
            },
        },
    };
})();
