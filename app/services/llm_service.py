import os
from app.core import config  # 先加载 .env，确保 os.getenv 能读到 LLM_API_KEY
import json
import time
import threading
from collections import OrderedDict
from typing import Dict, List, Any, Optional
from openai import OpenAI

# DeepSeek API Key
API_KEY = os.getenv("LLM_API_KEY", "")
BASE_URL = "https://api.deepseek.com"

# 缓存配置
CACHE_MAX_SIZE = 1000
CACHE_EXPIRY = 3600


class ExpiringLRUCache:
    """线程安全的带过期时间 LRU 缓存"""

    def __init__(self, maxsize: int = 1000, expiry: int = 3600):
        self.maxsize = maxsize
        self.expiry = expiry
        self.cache_data = OrderedDict()
        self.lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self.lock:
            if key not in self.cache_data:
                return None
            value, timestamp = self.cache_data[key]
            if time.time() - timestamp > self.expiry:
                del self.cache_data[key]
                return None
            self.cache_data.move_to_end(key)
            return value

    def set(self, key: str, value: Any):
        with self.lock:
            if key in self.cache_data:
                del self.cache_data[key]
            elif len(self.cache_data) >= self.maxsize:
                self.cache_data.popitem(last=False)
            self.cache_data[key] = (value, time.time())
            self.cache_data.move_to_end(key)

    def delete(self, key: str):
        with self.lock:
            if key in self.cache_data:
                del self.cache_data[key]

    def clear(self):
        with self.lock:
            self.cache_data.clear()

    def __len__(self):
        with self.lock:
            return len(self.cache_data)


class LLMService:
    def __init__(self):
        self.client = OpenAI(
            api_key=API_KEY,
            base_url=BASE_URL,
            timeout=60.0,
            max_retries=3,
        )
        self.cache = ExpiringLRUCache(maxsize=CACHE_MAX_SIZE, expiry=CACHE_EXPIRY)

        self.SYSTEM_PROMPT_TEMPLATE = (
            "你是一名专业的教育课程分析助手，严格遵守以下规则：\n"
            "1. 输出必须严格匹配指定的JSON格式，字段完整、类型正确，无多余内容；\n"
            "2. 内容需具体、可落地，避免空泛的描述；\n"
            "3. 分析需基于提供的上下文，不编造信息；\n"
            "4. 语言风格专业、简洁、易懂，符合教育场景需求；\n"
            "5. 严格按照要求的数量、长度生成内容，不超范围。"
        )

    # ---------------------------
    # 基础工具
    # ---------------------------
    def _clean_json(self, text: str) -> Optional[Any]:
        if not text:
            return None
        text = text.strip().replace("```json", "").replace("```", "")
        try:
            return json.loads(text)
        except Exception:
            pass

        # 尝试截取最外层 JSON
        for start_char, end_char in (("{", "}"), ("[", "]")):
            start = text.find(start_char)
            end = text.rfind(end_char)
            if start != -1 and end != -1 and end > start:
                candidate = text[start : end + 1]
                try:
                    return json.loads(candidate)
                except Exception:
                    continue

        compact = text.replace("\n", " ").replace("\t", " ")
        try:
            return json.loads(compact)
        except Exception as e:
            print(f"JSON解析失败: {e}, 原始文本片段: {text[:200]}...")
            return None

    def _normalize_text(self, text: Any, max_len: int = 500) -> str:
        if text is None:
            return ""
        if not isinstance(text, str):
            text = json.dumps(text, ensure_ascii=False)
        text = " ".join(text.split())
        return text[:max_len]

    def _normalize_context_lines(self, items: List[Any], max_items: int = 8, each_len: int = 80, total_len: int = 500) -> str:
        lines = []
        for item in items[-max_items:]:
            if isinstance(item, dict):
                user = item.get("username") or item.get("student_name") or item.get("user") or "用户"
                content = item.get("content") or item.get("text") or item.get("speech") or ""
                line = f"{user}: {self._normalize_text(content, each_len)}"
            else:
                line = self._normalize_text(item, each_len)
            if line.strip():
                lines.append(line)
        return "\n".join(lines)[:total_len]

    def _get_cache_key(self, method: str, *args, **kwargs) -> str:
        def normalize(obj):
            if isinstance(obj, str):
                return " ".join(obj.split())[:800]
            if isinstance(obj, list):
                return [normalize(x) for x in obj[:20]]
            if isinstance(obj, dict):
                return {k: normalize(v) for k, v in sorted(obj.items()) if v is not None}
            return obj

        try:
            payload = {
                "method": method,
                "args": normalize(list(args)),
                "kwargs": normalize(kwargs),
            }
            return json.dumps(payload, ensure_ascii=False, sort_keys=True)
        except Exception:
            return f"{method}:{hash(str(args))}:{hash(str(kwargs))}"

    def _validate_and_complement(self, data: Dict, required_fields: List[str]) -> Dict:
        if not isinstance(data, dict):
            data = {}
        for field in required_fields:
            if field not in data:
                if field == "score":
                    data[field] = 50
                elif field == "relevance":
                    data[field] = 50
                elif field in ["summary", "feedback", "guidance", "hint", "discussion_process", "class_atmosphere"]:
                    data[field] = "暂无有效内容"
                elif field in ["materials", "exercises", "viewpoints", "sub_goals", "core_questions", "student_reviews", "key_findings", "updated_goals"]:
                    data[field] = []
                elif field == "dimensions":
                    data[field] = {"relevance": 50, "depth": 50, "creativity": 50, "expression": 50}
                else:
                    data[field] = ""
        return data

    def _call_json(
        self,
        prompt: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 800,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> Optional[Any]:
        options = {}
        if timeout is not None:
            options["timeout"] = timeout
        if max_retries is not None:
            options["max_retries"] = max_retries
        client = self.client.with_options(**options) if options else self.client

        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT_TEMPLATE},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return self._clean_json(response.choices[0].message.content)

    def _default_score_result(self, speech_content: str = "") -> Dict:
        content_len = len((speech_content or "").strip())
        if content_len < 3:
            base = 30
            feedback = "发言内容过短，建议补充具体观点"
        elif content_len < 12:
            base = 45
            feedback = "已表达基本观点，建议补充原因或例子"
        else:
            base = 55
            feedback = "观点基本清晰，建议进一步增强深度和论证"
        return {
            "score": base,
            "feedback": feedback,
            "dimensions": {
                "relevance": base,
                "depth": max(30, base - 5),
                "creativity": max(30, base - 8),
                "expression": base,
            },
        }

    def _default_progress_result(self, current_goals: List[Dict], student_name: str) -> Dict:
        return {
            "relevance": 50,
            "updated_goals": current_goals or [],
            "hint": f"{student_name}可结合课堂目标补充更具体的观点和例子",
        }

    def _build_speech_analysis_prompt(
        self,
        speech_content: str,
        topic: str,
        recent_context: str = "",
        current_goals: Optional[List[Dict]] = None,
        student_name: str = "同学",
    ) -> str:
        goals_json = json.dumps((current_goals or [])[:8], ensure_ascii=False)
        return f"""
课程主题：{topic or '未提供'}
课堂最近上下文：{recent_context or '无'}
当前学生发言：{speech_content}
当前目标列表：{goals_json}

请一次性完成两类分析，并严格返回 JSON：
{{
  "score": 0-100 的整数综合分，按 relevance*0.4 + depth*0.3 + creativity*0.1 + expression*0.2 四舍五入,
  "feedback": "30-50字的详细点评，使用Markdown格式，可包含**加粗**强调关键词，指出优点和改进方向",
  "dimensions": {{
    "relevance": 0-100整数,
    "depth": 0-100整数,
    "creativity": 0-100整数,
    "expression": 0-100整数
  }},
  "relevance": 0-100 的整数，表示该发言与课堂目标和讨论方向的相关度,
  "updated_goals": [
    {{"id": 1, "desc": "原目标", "status": "pending或done"}}
  ],
  "hint": "给{student_name}的个性化建议，30-50字，使用Markdown格式"
}}

要求：
1. 只能基于给定发言和上下文分析，不编造不存在的完成情况；
2. 如果无法判断目标完成，则保持原状态；
3. 输出必须是可解析 JSON；
4. 内容简洁，避免冗长解释。
"""

    def _extract_json_string_prefix(self, buffer: str, key: str) -> tuple:
        marker = f'"{key}"'
        start = buffer.find(marker)
        if start < 0:
            return "", False
        colon = buffer.find(":", start + len(marker))
        if colon < 0:
            return "", False
        quote = buffer.find('"', colon + 1)
        if quote < 0:
            return "", False

        out = []
        i = quote + 1
        while i < len(buffer):
            ch = buffer[i]
            if ch == "\\":
                if i + 1 >= len(buffer):
                    break
                nxt = buffer[i + 1]
                if nxt == "u":
                    hex_part = buffer[i + 2:i + 6]
                    if len(hex_part) < 4:
                        break
                    try:
                        out.append(chr(int(hex_part, 16)))
                    except Exception:
                        pass
                    i += 6
                    continue
                out.append({"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}.get(nxt, nxt))
                i += 2
                continue
            if ch == '"':
                return "".join(out), True
            out.append(ch)
            i += 1
        return "".join(out), False

    def stream_speech_analysis_and_progress(
        self,
        speech_content: str,
        topic: str,
        recent_context: str = "",
        current_goals: Optional[List[Dict]] = None,
        student_name: str = "同学",
    ):
        """流式接收同一份真实大模型 JSON 分析，并提前吐出 feedback 字段。"""
        speech_content = self._normalize_text(speech_content, 500)
        topic = self._normalize_text(topic, 120)
        recent_context = self._normalize_text(recent_context, 240)
        current_goals = current_goals or []
        if not speech_content:
            return

        cache_key = self._get_cache_key(
            "analyze_speech_and_progress",
            speech_content,
            topic,
            recent_context,
            current_goals,
            student_name,
        )
        cached = self.cache.get(cache_key)
        if cached:
            feedback = cached.get("feedback") or ""
            if feedback:
                yield {"type": "feedback_delta", "delta": feedback}
            yield {"type": "result", "result": cached}
            return

        prompt = self._build_speech_analysis_prompt(
            speech_content=speech_content,
            topic=topic,
            recent_context=recent_context,
            current_goals=current_goals,
            student_name=student_name,
        )

        buffer = ""
        emitted_feedback = ""
        try:
            client = self.client.with_options(timeout=45.0, max_retries=0)
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT_TEMPLATE},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=420,
                stream=True,
            )
            for chunk in response:
                try:
                    delta = chunk.choices[0].delta.content or ""
                except Exception:
                    delta = ""
                if not delta:
                    continue
                buffer += delta
                current_feedback, _ = self._extract_json_string_prefix(buffer, "feedback")
                if len(current_feedback) > len(emitted_feedback):
                    new_text = current_feedback[len(emitted_feedback):]
                    emitted_feedback = current_feedback
                    yield {"type": "feedback_delta", "delta": new_text}

            result = self._clean_json(buffer) or {}
            result = self._validate_and_complement(
                result,
                ["score", "feedback", "dimensions", "relevance", "updated_goals", "hint"],
            )
            default_progress = self._default_progress_result(current_goals, student_name)
            if not result.get("feedback") or result.get("feedback") == "暂无有效内容":
                result["feedback"] = emitted_feedback or "大模型未返回有效评语，请稍后重试"
            if not result.get("hint") or result.get("hint") == "暂无有效内容":
                result["hint"] = default_progress["hint"]
            if not result.get("updated_goals"):
                result["updated_goals"] = current_goals
            self.cache.set(cache_key, result)
            yield {"type": "result", "result": result}
        except Exception as e:
            print(f"流式联合分析失败: {e}")
            return

    # ---------------------------
    # 高频实时分析：一份结果复用两处接口
    # ---------------------------
    def analyze_speech_and_progress(
        self,
        speech_content: str,
        topic: str,
        recent_context: str = "",
        current_goals: Optional[List[Dict]] = None,
        student_name: str = "同学",
    ) -> Dict:
        """一次调用同时返回发言评分和进度分析。"""
        speech_content = self._normalize_text(speech_content, 500)
        topic = self._normalize_text(topic, 120)
        recent_context = self._normalize_text(recent_context, 240)
        current_goals = current_goals or []

        if not speech_content:
            score_result = self._default_score_result("")
            progress_result = self._default_progress_result(current_goals, student_name)
            return {**score_result, **progress_result}

        cache_key = self._get_cache_key(
            "analyze_speech_and_progress",
            speech_content,
            topic,
            recent_context,
            current_goals,
            student_name,
        )
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        prompt = self._build_speech_analysis_prompt(
            speech_content=speech_content,
            topic=topic,
            recent_context=recent_context,
            current_goals=current_goals,
            student_name=student_name,
        )

        try:
            result = self._call_json(prompt, temperature=0.1, max_tokens=420, timeout=10.0, max_retries=0) or {}
            result = self._validate_and_complement(
                result,
                ["score", "feedback", "dimensions", "relevance", "updated_goals", "hint"],
            )
            default_score = self._default_score_result(speech_content)
            default_progress = self._default_progress_result(current_goals, student_name)
            if not result.get("feedback") or result.get("feedback") == "暂无有效内容":
                result["feedback"] = "大模型未返回有效评语，请稍后重试"
            if not result.get("hint") or result.get("hint") == "暂无有效内容":
                result["hint"] = default_progress["hint"]
            if not result.get("updated_goals"):
                result["updated_goals"] = current_goals
            self.cache.set(cache_key, result)
            return result
        except Exception as e:
            print(f"联合分析失败: {e}")
            progress_result = self._default_progress_result(current_goals, student_name)
            return {
                "score": 50,
                "feedback": "大模型评语生成超时，请稍后重试",
                "dimensions": {"relevance": 50, "depth": 50, "creativity": 50, "expression": 50},
                **progress_result,
            }

    def score_speech_quality(self, speech_content: str, topic: str, recent_context: str = "") -> Dict:
        """兼容旧接口：内部自动复用联合分析结果。"""
        result = self.analyze_speech_and_progress(
            speech_content=speech_content,
            topic=topic,
            recent_context=recent_context,
            current_goals=[],
            student_name="同学",
        )
        return {
            "score": result.get("score", 50),
            "feedback": result.get("feedback", "暂无反馈"),
            "dimensions": result.get(
                "dimensions",
                {"relevance": 50, "depth": 50, "creativity": 50, "expression": 50},
            ),
        }

    def analyze_progress(self, lesson_plan: str, current_goals: List[Dict], recent_context: str, student_name: str) -> Optional[Dict]:
        """兼容旧接口：若 recent_context 与评分接口一致，可直接命中联合分析缓存。"""
        if not recent_context:
            return None
        result = self.analyze_speech_and_progress(
            speech_content=recent_context,
            topic=lesson_plan,
            recent_context=recent_context,
            current_goals=current_goals,
            student_name=student_name,
        )
        return {
            "relevance": result.get("relevance", 50),
            "updated_goals": result.get("updated_goals", current_goals),
            "hint": result.get("hint", f"请{student_name}继续围绕课堂目标展开思考"),
        }

    # ---------------------------
    # 低频方法：主要做裁剪、缓存与 token 控制
    # ---------------------------
    def init_meeting_goals(self, lesson_plan: str) -> List[Dict]:
        lesson_plan = self._normalize_text(lesson_plan, 200)
        cache_key = self._get_cache_key("init_meeting_goals", lesson_plan)
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        prompt = f"""
根据课程主题或计划生成 3-5 个具体、可执行的课堂目标，严格返回 JSON：
{{
  "goals": [
    {{"id": 1, "desc": "掌握XX核心概念", "status": "pending"}},
    {{"id": 2, "desc": "结合案例分析XX问题", "status": "pending"}}
  ]
}}

课程计划：{lesson_plan}

要求：
1. 目标具体可执行；
2. 每条不超过 24 字；
3. 仅返回 JSON。
"""
        try:
            result = self._call_json(prompt, temperature=0.2, max_tokens=220) or {}
            goals = result.get("goals", []) if isinstance(result, dict) else []
            if len(goals) < 3:
                goals = [
                    {"id": 1, "desc": "理解基本概念", "status": "pending"},
                    {"id": 2, "desc": "掌握核心方法", "status": "pending"},
                    {"id": 3, "desc": "完成课堂讨论", "status": "pending"},
                ]
            self.cache.set(cache_key, goals)
            return goals
        except Exception as e:
            print(f"初始化会议目标失败: {e}")
            return [
                {"id": 1, "desc": "理解基本概念", "status": "pending"},
                {"id": 2, "desc": "掌握核心方法", "status": "pending"},
                {"id": 3, "desc": "完成课堂讨论", "status": "pending"},
            ]

    def analyze_emotion_and_summary(self, topic: str, full_text: str, emotion_stats: Dict) -> Dict:
        topic = self._normalize_text(topic, 120)
        full_text = self._normalize_text(full_text, 1000)
        emotion_stats = emotion_stats or {}
        cache_key = self._get_cache_key("analyze_emotion_and_summary", topic, full_text, emotion_stats)
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        prompt = f"""
讨论主题：{topic}
讨论内容：{full_text}
情绪统计：{json.dumps(emotion_stats, ensure_ascii=False)}

请返回 JSON：
{{
  "summary": "50-100字总结",
  "emotion_analysis": "主要情绪与变化原因",
  "goal_status": "未开始/进行中/部分完成/已完成",
  "next_step": "下一步建议"
}}
"""
        try:
            result = self._call_json(prompt, temperature=0.2, max_tokens=320) or {}
            result = self._validate_and_complement(result, ["summary", "emotion_analysis", "goal_status", "next_step"])
            self.cache.set(cache_key, result)
            return result
        except Exception as e:
            print(f"情绪与总结分析失败: {e}")
            return {
                "summary": "课堂讨论已完成，建议结合发言内容进一步复盘。",
                "emotion_analysis": "整体情绪较稳定。",
                "goal_status": "进行中",
                "next_step": "围绕主题整理关键观点并完成课后巩固。",
            }

    def generate_course_report(self, meeting_topic: str, all_transcripts: List[Dict], emotion_stats: Dict, student_performances: List[Dict]) -> Dict:
        meeting_topic = self._normalize_text(meeting_topic, 120)
        transcript_text = self._normalize_context_lines(all_transcripts, max_items=20, each_len=120, total_len=1600)
        perf_text = self._normalize_text(student_performances, 800)
        cache_key = self._get_cache_key("generate_course_report", meeting_topic, transcript_text, emotion_stats, perf_text)
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        prompt = f"""
请基于以下课堂信息生成结构化课程报告，严格返回 JSON。

课堂主题：{meeting_topic}
讨论摘录：
{transcript_text}
情绪统计：{json.dumps(emotion_stats, ensure_ascii=False)}
学生表现摘要：{perf_text}

JSON 结构：
{{
  "basic_info": {{
    "topic": "{meeting_topic}",
    "members": [],
    "recorder": "课程助手"
  }},
  "summary": "课堂总结",
  "core_questions": ["问题1", "问题2"],
  "viewpoints": [
    {{
      "title": "观点标题",
      "support_reasons": ["理由1"],
      "case_analysis": "案例分析",
      "objections": "无"
    }}
  ],
  "highlights": {{
    "most_inspiring": "",
    "most_controversial": "",
    "innovative_ideas": ""
  }},
  "consensus": ["共识1"],
  "unresolved": {{
    "further_research": "",
    "disagreements": ""
  }},
  "action_plan": {{
    "next_direction": "",
    "materials_needed": "",
    "task_division": ""
  }},
  "student_reviews": [
    {{
      "student_name": "学生姓名",
      "strengths": ["优点"],
      "weaknesses": ["不足"],
      "personal_gains": {{
        "knowledge": "",
        "thinking": "",
        "improvements": ""
      }},
      "unmastered_concepts": [],
      "suggestions": ""
    }}
  ],
  "class_atmosphere": "",
  "discussion_process": "50字内",
  "key_findings": ["发现1", "发现2"]
}}

要求：
1. 字段完整；
2. 所有文本内容使用Markdown格式，善用**加粗**、*斜体*、列表等标记增强可读性；
3. summary字段至少100字，详细总结课堂讨论过程和要点；
4. student_reviews中的suggestions至少50字，给出具体可操作的建议；
5. 不编造未出现的事实；
6. 内容具体、有深度。
"""
        try:
            result = self._call_json(prompt, temperature=0.25, max_tokens=2400) or {}
            result = self._validate_and_complement(
                result,
                [
                    "basic_info",
                    "summary",
                    "core_questions",
                    "viewpoints",
                    "student_reviews",
                    "class_atmosphere",
                    "discussion_process",
                    "key_findings",
                ],
            )
            if not isinstance(result.get("basic_info"), dict):
                result["basic_info"] = {"topic": meeting_topic, "members": [], "recorder": "课程助手"}
            result["basic_info"].setdefault("topic", meeting_topic)
            result["basic_info"].setdefault("members", [])
            result["basic_info"].setdefault("recorder", "课程助手")
            self.cache.set(cache_key, result)
            return result
        except Exception as e:
            print(f"生成课程报告失败: {e}")
            return {
                "basic_info": {"topic": meeting_topic, "members": [], "recorder": "课程助手"},
                "summary": "本次课堂围绕主题展开了讨论。",
                "core_questions": [],
                "viewpoints": [],
                "highlights": {},
                "consensus": [],
                "unresolved": {},
                "action_plan": {},
                "student_reviews": [],
                "class_atmosphere": "整体课堂氛围较稳定。",
                "discussion_process": "课堂围绕主题进行了交流。",
                "key_findings": [],
            }

    def generate_exercises(self, student_weaknesses: str, topic: str) -> Dict:
        topic = self._normalize_text(topic, 120)
        student_weaknesses = self._normalize_text(student_weaknesses, 300)
        cache_key = self._get_cache_key("generate_exercises", student_weaknesses, topic)
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        prompt = f"""
课程主题：{topic}
学生薄弱点：{student_weaknesses}

请生成 5-8 道针对性练习题，严格返回 JSON。题目内容使用Markdown格式，可包含代码块、公式、列表等。
{{
  "exercises": [
    {{
      "question": "使用Markdown格式的题目内容，可包含代码块、公式、表格等",
      "type": "选择题/填空题/简答题/分析题",
      "options": ["A. 选项1", "B. 选项2", "C. 选项3", "D. 选项4"],
      "answer": "正确答案，包含详细的解析说明（至少30字），解释为什么选择该答案",
      "knowledge_tag": "对应知识点",
      "difficulty": 0.5,
      "estimated_time": 3
    }}
  ]
}}

要求：
1. 题型多样化，包含选择题、填空题、简答题、分析题；
2. 题目有层次，从基础到进阶；
3. 答案必须包含详细的解析过程；
4. 题目内容使用Markdown格式增强可读性。
"""
        try:
            result = self._call_json(prompt, temperature=0.3, max_tokens=1500) or {}
            result = self._validate_and_complement(result, ["exercises"])
            if len(result.get("exercises", [])) < 5:
                result["exercises"] = result.get("exercises", []) + [
                    {
                        "question": f"请解释{topic}中的核心概念",
                        "type": "简答题",
                        "answer": "",
                        "knowledge_tag": student_weaknesses[:20] or topic,
                        "difficulty": 0.5,
                        "estimated_time": 5,
                    }
                ] * (5 - len(result.get("exercises", [])))
            self.cache.set(cache_key, result)
            return result
        except Exception as e:
            print(f"生成练习题失败: {e}")
            return {"exercises": []}

    def recommend_materials(self, discussion_context: List[Dict], topic: str) -> Dict:
        topic = self._normalize_text(topic, 120)
        context_text = self._normalize_context_lines(discussion_context, max_items=8, each_len=80, total_len=480)
        cache_key = self._get_cache_key("recommend_materials", topic, context_text)
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        prompt = f"""
课程主题：{topic}
核心讨论内容：
{context_text}

请推荐 3-5 个高相关学习材料，严格返回 JSON：
{{
  "materials": [
    {{
      "title": "材料标题",
      "type": "article/video/book/paper",
      "description": "50字内简介",
      "relevance_reason": "20字内关联原因",
      "url": "https://example.com"
    }}
  ],
  "trigger_reason": "触发推荐的具体原因"
}}
"""
        try:
            result = self._call_json(prompt, temperature=0.35, max_tokens=520) or {}
            result = self._validate_and_complement(result, ["materials", "trigger_reason"])
            if len(result.get("materials", [])) < 3:
                result["materials"] = result.get("materials", []) + [
                    {
                        "title": f"{topic}核心知识点解析",
                        "type": "article",
                        "description": f"帮助梳理{topic}相关的核心概念和应用场景",
                        "relevance_reason": f"匹配{topic}当前学习需求",
                        "url": f"https://example.com/{topic}",
                    }
                ] * (3 - len(result.get("materials", [])))
            self.cache.set(cache_key, result)
            return result
        except Exception as e:
            print(f"推荐学习材料失败: {e}")
            return {"materials": [], "trigger_reason": ""}

    def monitor_class_atmosphere(self, recent_transcripts: List[Dict], emotion_stats: Dict, time_window_minutes: int = 5) -> Dict:
        speech_count = len(recent_transcripts or [])
        total_emotions = sum((emotion_stats or {}).values()) if emotion_stats else 0
        positive_ratio = 0.0
        if total_emotions > 0:
            positive_count = emotion_stats.get("happy", 0) + emotion_stats.get("excited", 0)
            positive_ratio = positive_count / total_emotions

        if speech_count == 0:
            return {
                "atmosphere": "cold",
                "heat_score": 0,
                "alert": True,
                "alert_message": f"最近{time_window_minutes}分钟课堂较安静，请引导互动",
                "suggestions": ["抛出开放问题", "邀请学生举例", "组织简短讨论"],
            }
        if speech_count < 3:
            return {
                "atmosphere": "cold",
                "heat_score": 30,
                "alert": True,
                "alert_message": f"最近{time_window_minutes}分钟发言较少，可适当活跃气氛",
                "suggestions": ["点名互动", "展示案例", "设置任务分工"],
            }
        if speech_count >= 10 and positive_ratio >= 0.4:
            return {
                "atmosphere": "active",
                "heat_score": 90,
                "alert": False,
                "alert_message": "",
                "suggestions": [],
            }
        return {
            "atmosphere": "normal",
            "heat_score": 60,
            "alert": False,
            "alert_message": "",
            "suggestions": [],
        }

    def cluster_viewpoints(self, all_transcripts: List[Dict], topic: str) -> Dict:
        if len(all_transcripts or []) < 3:
            return {"viewpoints": [], "summary": "讨论内容较少，暂不适合聚类", "suggested_next": ""}

        topic = self._normalize_text(topic, 120)
        context_text = self._normalize_context_lines(all_transcripts, max_items=20, each_len=100, total_len=1200)
        cache_key = self._get_cache_key("cluster_viewpoints", topic, context_text)
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        prompt = f"""
主题：{topic}
课堂发言摘录：
{context_text}

请对观点进行聚类，必须生成恰好 4 个不同的观点选项，严格返回 JSON：
{{
  "viewpoints": [
    {{
      "id": 1,
      "title": "观点标题",
      "description": "观点概述",
      "supporters": ["学生A", "学生B"]
    }},
    {{
      "id": 2,
      "title": "观点标题",
      "description": "观点概述",
      "supporters": ["学生C"]
    }},
    {{
      "id": 3,
      "title": "观点标题",
      "description": "观点概述",
      "supporters": ["学生D"]
    }},
    {{
      "id": 4,
      "title": "观点标题",
      "description": "观点概述",
      "supporters": ["学生E"]
    }}
  ],
  "summary": "整体观点总结",
  "suggested_next": "下一步建议"
}}

要求：
1. 必须生成恰好 4 个不同的观点
2. 每个观点要有明确的差异性
3. 如果发言内容不足 4 个观点，可以从不同角度拆分或补充相关观点
"""
        try:
            result = self._call_json(prompt, temperature=0.25, max_tokens=700, timeout=60.0) or {}
            result = self._validate_and_complement(result, ["viewpoints", "summary", "suggested_next"])

            # 确保恰好有 4 个观点
            viewpoints = result.get("viewpoints", [])
            if len(viewpoints) < 4:
                print(f"[WARNING] LLM 只返回了 {len(viewpoints)} 个观点，需要补充到 4 个")
                # 补充观点到 4 个
                while len(viewpoints) < 4:
                    viewpoints.append({
                        "id": len(viewpoints) + 1,
                        "title": f"观点{len(viewpoints) + 1}",
                        "description": "待补充的观点",
                        "supporters": []
                    })
                result["viewpoints"] = viewpoints
            elif len(viewpoints) > 4:
                print(f"[WARNING] LLM 返回了 {len(viewpoints)} 个观点，截取前 4 个")
                result["viewpoints"] = viewpoints[:4]

            self.cache.set(cache_key, result)
            return result
        except Exception as e:
            print(f"观点聚类失败: {e}")
            return {"viewpoints": [], "summary": "暂未生成观点聚类结果", "suggested_next": ""}

    def generate_sub_goals(self, selected_viewpoint: Dict, topic: str, current_goals: List[Dict]) -> Dict:
        topic = self._normalize_text(topic, 120)
        selected_viewpoint = selected_viewpoint or {}
        cache_key = self._get_cache_key("generate_sub_goals", selected_viewpoint, topic, current_goals)
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        prompt = f"""
课程主题：{topic}
当前目标：{json.dumps(current_goals[:8], ensure_ascii=False)}
选中观点：{json.dumps(selected_viewpoint, ensure_ascii=False)}

请生成 3-5 个子目标和一条引导语，严格返回 JSON：
{{
  "sub_goals": [
    {{"id": 1, "desc": "具体子目标", "status": "pending"}}
  ],
  "guidance": "教师引导建议"
}}
"""
        try:
            print(f"[LLM] 开始生成子目标，观点: {selected_viewpoint.get('title', 'N/A')}")
            result = self._call_json(prompt, temperature=0.25, max_tokens=320, timeout=90.0) or {}
            print(f"[LLM] 子目标生成成功: {result}")
            result = self._validate_and_complement(result, ["sub_goals", "guidance"])
            self.cache.set(cache_key, result)
            return result
        except Exception as e:
            print(f"[ERROR] 生成子目标失败: {e}")
            import traceback
            traceback.print_exc()
            return {"sub_goals": [], "guidance": ""}

    def quick_decompose(self, all_transcripts: List[Dict], topic: str, current_goals: List[Dict]) -> Dict:
        """一步到位：直接分析发言内容并生成子任务（跳过聚类+投票）"""
        topic = self._normalize_text(topic, 120)
        context_text = self._normalize_context_lines(all_transcripts, max_items=20, each_len=100, total_len=1200)
        cache_key = self._get_cache_key("quick_decompose", topic, context_text)
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        prompt = f"""
课程主题：{topic}
当前教学目标：{json.dumps(current_goals[:8], ensure_ascii=False)}
课堂发言摘录：
{context_text}

请根据课堂讨论内容，提炼核心观点并直接分解为 3-5 个可执行的子目标。严格返回 JSON：
{{
  "main_viewpoint": "从讨论中提炼的核心观点/方向",
  "sub_goals": [
    {{"id": 1, "desc": "具体子目标", "status": "pending"}}
  ],
  "guidance": "教师引导建议（一句话）"
}}
"""
        try:
            result = self._call_json(prompt, temperature=0.25, max_tokens=500) or {}
            result = self._validate_and_complement(result, ["main_viewpoint", "sub_goals", "guidance"])
            self.cache.set(cache_key, result)
            return result
        except Exception as e:
            print(f"快速分解失败: {e}")
            return {"main_viewpoint": "", "sub_goals": [], "guidance": ""}

    def generate_topic_suggestion(self, topic: str, recent_context: str, current_goals: list, target_type: str = "quiet") -> str:
        """为沉默成员或全组生成话题建议"""
        topic = self._normalize_text(topic, 120)
        recent_context = self._normalize_text(recent_context, 500)

        if target_type == "quiet":
            role_desc = "一位需要鼓励参与的同学"
            instruction = "生成一个友好的话题建议，帮助这位同学融入当前讨论。语气要温暖鼓励，给出具体可以发言的切入点。"
        else:
            role_desc = "整个小组（已沉默超过2分钟）"
            instruction = "生成一个能激发讨论的话题建议，打破沉默。可以是一个问题、一个新视角、或一个有趣的思考方向。"

        pending_goals = [g["desc"] for g in (current_goals or []) if g.get("status") == "pending"]
        goals_text = "、".join(pending_goals[:3]) if pending_goals else "无待完成目标"

        prompt = f"""课程主题：{topic}
待完成目标：{goals_text}
最近讨论：
{recent_context}

请为{role_desc}生成话题建议。{instruction}
要求：直接给出建议内容，不超过80字，不要加前缀标签。"""

        try:
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "你是一位善于引导讨论的课堂助手。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.6,
                max_tokens=150
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"生成话题建议失败: {e}")
            if target_type == "quiet":
                return f"试试从你的角度聊聊对「{topic}」的看法吧，你的想法对小组很重要！"
            return f"大家可以讨论一下：关于「{topic}」，还有哪些方面值得深入探讨？"

    def ai_tutor(self, question: str):
        """AI 导师接口：复用同一个 client，避免每次重建。"""
        question = self._normalize_text(question, 800)
        if not question:
            return "问题不能为空"
        cache_key = self._get_cache_key("ai_tutor", question)
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        try:
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "你是一位耐心的AI导师，擅长用简单易懂的方式解答学生问题。请使用Markdown格式来组织你的回答，合理使用标题、列表、代码块、表格等。"},
                    {"role": "user", "content": question},
                ],
                temperature=0.4,
                max_tokens=1200,
            )
            answer = response.choices[0].message.content.strip()
            self.cache.set(cache_key, answer)
            return answer
        except Exception as e:
            print(f"AI导师回答失败: {e}")
            return "抱歉，AI导师暂时无法回答，请稍后重试。"

    def ai_tutor_stream(self, question: str, history: list = None):
        """流式AI导师接口，yield每个token。"""
        question = self._normalize_text(question, 800)
        if not question:
            yield "问题不能为空"
            return

        cache_key = self._get_cache_key("ai_tutor", question)
        cached = self.cache.get(cache_key)
        if cached:
            yield cached
            return

        messages = [
            {"role": "system", "content": "你是一位耐心的AI导师，擅长用简单易懂的方式解答学生问题。请使用Markdown格式来组织你的回答，合理使用标题、列表、代码块、表格等。"},
        ]
        # 添加历史对话上下文（最近6轮）
        if history:
            for msg in history[-6:]:
                messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
        messages.append({"role": "user", "content": question})

        try:
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                temperature=0.4,
                max_tokens=1200,
                stream=True,
            )
            full_answer = []
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    full_answer.append(token)
                    yield token
            # 缓存完整回答
            self.cache.set(cache_key, "".join(full_answer))
        except Exception as e:
            print(f"AI导师流式回答失败: {e}")
            yield "抱歉，AI导师暂时无法回答，请稍后重试。"


llm = LLMService()
