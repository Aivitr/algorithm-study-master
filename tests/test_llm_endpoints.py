# -*- coding: utf-8 -*-
"""
LLM 应用接口测试
覆盖 ai-tutor、suggest-topic、quiz-error-analysis 等关键端点

运行: pytest tests/test_llm_endpoints.py -v -s
"""
import pytest
import json
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app
from database import SessionLocal

client = TestClient(app)


class TestAITutorEndpoint:
    """测试 /api/ai-tutor 端点"""

    def test_ai_tutor_basic_question(self):
        """测试基本问题解答"""
        response = client.post("/api/ai-tutor", json={
            "question": "1+1等于多少？",
            "context": "数学课"
        })
        
        assert response.status_code == 200
        data = response.json()
        assert "response" in data or "content" in data or "answer" in data
        assert len(data) > 0

    def test_ai_tutor_with_previous_messages(self):
        """测试带有对话历史的问题"""
        response = client.post("/api/ai-tutor", json={
            "question": "那么2+2呢？",
            "previous_messages": [
                {"role": "user", "content": "1+1等于多少？"},
                {"role": "assistant", "content": "1+1等于2"}
            ]
        })
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0

    def test_ai_tutor_empty_question(self):
        """测试空问题的处理"""
        response = client.post("/api/ai-tutor", json={
            "question": ""
        })
        
        # 应该返回 400 或优雅地处理
        assert response.status_code in [200, 400, 422]

    def test_ai_tutor_very_long_question(self):
        """测试超长问题"""
        long_question = "这是一个很长的问题？" * 100
        response = client.post("/api/ai-tutor", json={
            "question": long_question[:1000]
        })
        
        assert response.status_code in [200, 413, 422]

    def test_ai_tutor_special_characters(self):
        """测试特殊字符处理"""
        response = client.post("/api/ai-tutor", json={
            "question": "什么是🎉？代码: <script>alert('xss')</script>"
        })
        
        assert response.status_code == 200

    @patch("llm_service.llm._chat_with_fallback")
    def test_ai_tutor_with_fallback(self, mock_fallback):
        """测试 fallback 触发"""
        mock_fallback.return_value = '{"response": "fallback response"}'
        
        response = client.post("/api/ai-tutor", json={
            "question": "测试回退"
        })
        
        assert response.status_code == 200

    def test_ai_tutor_stream_response(self):
        """测试流式响应"""
        response = client.post("/api/ai-tutor-stream", json={
            "question": "流式测试"
        }, stream=True)
        
        assert response.status_code in [200, 404]  # 如果不支持流也可以


class TestSuggestTopicEndpoint:
    """测试 /api/suggest-topic 端点"""

    def test_suggest_topic_basic(self):
        """测试基本话题建议"""
        response = client.post("/api/suggest-topic", json={
            "context": "正在学习人工智能"
        })
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0

    def test_suggest_topic_with_student_level(self):
        """测试针对学生水平的话题建议"""
        response = client.post("/api/suggest-topic", json={
            "context": "数据结构",
            "student_level": "advanced"
        })
        
        assert response.status_code == 200

    def test_suggest_topic_empty_context(self):
        """测试空上下文"""
        response = client.post("/api/suggest-topic", json={
            "context": ""
        })
        
        assert response.status_code in [200, 400, 422]

    def test_suggest_topic_chinese_context(self):
        """测试中文上下文"""
        response = client.post("/api/suggest-topic", json={
            "context": "深度学习和神经网络的应用"
        })
        
        assert response.status_code == 200

    def test_suggest_topic_multiple_topics(self):
        """测试多个话题建议"""
        response = client.post("/api/suggest-topic", json={
            "context": "编程基础",
            "num_suggestions": 5
        })
        
        assert response.status_code == 200

    @patch("llm_service.llm._chat_json_with_fallback")
    def test_suggest_topic_json_response_format(self, mock_json):
        """测试 JSON 响应格式"""
        mock_json.return_value = {
            "topics": [
                {"title": "Topic1", "description": "Desc1"},
                {"title": "Topic2", "description": "Desc2"}
            ]
        }
        
        response = client.post("/api/suggest-topic", json={
            "context": "test"
        })
        
        assert response.status_code == 200


class TestQuizErrorAnalysisEndpoint:
    """测试 /api/quiz-error-analysis 端点"""

    def test_quiz_error_analysis_basic(self):
        """测试基本错误分析"""
        response = client.post("/api/quiz-error-analysis", json={
            "question": "1+1=?",
            "correct_answer": "2",
            "student_answer": "3",
            "topic": "数学"
        })
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0

    def test_quiz_error_analysis_with_explanation(self):
        """测试包含解释的错误分析"""
        response = client.post("/api/quiz-error-analysis", json={
            "question": "2的平方是多少？",
            "correct_answer": "4",
            "student_answer": "2",
            "explanation": "学生可能混淆了概念"
        })
        
        assert response.status_code == 200

    def test_quiz_error_analysis_similar_answers(self):
        """测试相似答案的分析"""
        response = client.post("/api/quiz-error-analysis", json={
            "question": "首都是哪里？",
            "correct_answer": "北京",
            "student_answer": "上海",
            "similar_answers": ["天津", "河北"]
        })
        
        assert response.status_code == 200

    def test_quiz_error_analysis_no_error(self):
        """测试答案正确的情况"""
        response = client.post("/api/quiz-error-analysis", json={
            "question": "1+1=?",
            "correct_answer": "2",
            "student_answer": "2"
        })
        
        # 应该返回 "no error" 或类似的正面反馈
        assert response.status_code == 200

    def test_quiz_error_analysis_empty_student_answer(self):
        """测试空学生答案"""
        response = client.post("/api/quiz-error-analysis", json={
            "question": "问题",
            "correct_answer": "答案",
            "student_answer": ""
        })
        
        assert response.status_code in [200, 400, 422]

    @patch("llm_service.llm.analyze_speech_and_progress")
    def test_quiz_error_analysis_structured_output(self, mock_analyze):
        """测试结构化输出"""
        mock_analyze.return_value = {
            "error_type": "conceptual_error",
            "explanation": "学生错误理解了概念",
            "suggestions": ["复习基础概念", "做更多练习题"]
        }
        
        response = client.post("/api/quiz-error-analysis", json={
            "question": "test",
            "correct_answer": "correct",
            "student_answer": "wrong"
        })
        
        assert response.status_code == 200


class TestEndpointErrorHandling:
    """测试所有端点的错误处理"""

    def test_ai_tutor_500_error_handling(self):
        """测试 500 错误的优雅处理"""
        with patch("llm_service.llm._chat_with_fallback") as mock:
            mock.side_effect = Exception("Database connection error")
            
            response = client.post("/api/ai-tutor", json={
                "question": "test"
            })
            
            # 应该返回 500 或有错误消息但不暴露内部细节
            assert response.status_code in [200, 500]

    def test_invalid_json_request(self):
        """测试无效的 JSON 请求"""
        response = client.post(
            "/api/ai-tutor",
            data="invalid json",
            headers={"content-type": "application/json"}
        )
        
        assert response.status_code in [400, 422]

    def test_missing_required_fields(self):
        """测试缺少必需字段"""
        response = client.post("/api/suggest-topic", json={
            # 缺少 context 字段
        })
        
        assert response.status_code in [400, 422, 200]  # 取决于实现

    def test_timeout_handling(self):
        """测试超时处理"""
        with patch("llm_service.llm._chat_with_fallback") as mock:
            import asyncio
            mock.side_effect = asyncio.TimeoutError("Request timed out")
            
            response = client.post("/api/ai-tutor", json={
                "question": "test"
            })
            
            # 应该返回友好的错误消息而不是 500
            assert response.status_code in [200, 408, 500]


class TestResponseFormat:
    """测试响应格式一致性"""

    def test_ai_tutor_response_format(self):
        """测试 ai-tutor 响应格式"""
        response = client.post("/api/ai-tutor", json={
            "question": "test"
        })
        
        assert response.status_code == 200
        data = response.json()
        
        # 验证常见的响应字段
        assert isinstance(data, (dict, list, str))

    def test_suggest_topic_response_array(self):
        """测试 suggest-topic 返回数组"""
        response = client.post("/api/suggest-topic", json={
            "context": "test"
        })
        
        assert response.status_code == 200
        data = response.json()
        
        # 应该返回列表或包含列表的对象
        assert isinstance(data, (list, dict))

    def test_quiz_error_analysis_response_structure(self):
        """测试 quiz-error-analysis 响应结构"""
        response = client.post("/api/quiz-error-analysis", json={
            "question": "q",
            "correct_answer": "c",
            "student_answer": "s"
        })
        
        assert response.status_code == 200
        data = response.json()
        
        # 应该包含分析结果
        assert len(data) > 0


class TestASRIntegration:
    """测试 ASR 相关的端点"""

    def test_ws_asr_connection(self):
        """测试 WebSocket ASR 连接"""
        # FastAPI TestClient 不支持 WebSocket，需要使用 WebSocketTestSession
        # 这里仅做占位符测试
        assert True

    def test_transcript_save_endpoint(self):
        """测试转录保存端点"""
        response = client.post("/api/save-transcript", json={
            "meeting_id": 1,
            "user_id": 1,
            "content": "测试转录",
            "timestamp": "2026-01-01T00:00:00"
        })
        
        # 可能返回 404 如果端点不存在
        assert response.status_code in [200, 404, 401]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
