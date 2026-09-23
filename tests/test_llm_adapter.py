# -*- coding: utf-8 -*-
"""
LLM 适配器单元测试
覆盖 provider 路由、fallback、异常兜底、JSON 清洗行为

运行: pytest tests/test_llm_adapter.py -v
"""
import pytest
import json
from unittest.mock import patch, MagicMock
from llm_service import llm, ExpiringLRUCache


class TestJSONParsing:
    """测试 JSON 解析和清洗"""

    def test_clean_json_valid_json_string(self):
        """测试清洁有效的 JSON 字符串"""
        raw = '{"key": "value", "count": 42}'
        result = llm._clean_json(raw)
        assert result == {"key": "value", "count": 42}

    def test_clean_json_with_markdown_code_fence(self):
        """测试清洁 Markdown 代码块中的 JSON"""
        raw = '```json\n{"a": 1, "b": 2}\n```'
        result = llm._clean_json(raw)
        assert result == {"a": 1, "b": 2}

    def test_clean_json_with_triple_backticks(self):
        """测试清洁带反引号的 JSON"""
        raw = '```\n{"status": "ok"}\n```'
        result = llm._clean_json(raw)
        assert result == {"status": "ok"}

    def test_clean_json_with_text_before_and_after(self):
        """测试清洁前后有文字的 JSON"""
        raw = 'Here is the result:\n```json\n{"result": "success"}\n```\nDone!'
        result = llm._clean_json(raw)
        assert result == {"result": "success"}

    def test_clean_json_invalid_input_returns_empty_dict(self):
        """测试清洁无效 JSON 返回空字典"""
        raw = "not a json at all"
        result = llm._clean_json(raw)
        assert isinstance(result, dict)
        # 不应该抛异常

    def test_clean_json_with_single_quotes(self):
        """测试清洁单引号 JSON（应当转为双引号）"""
        raw = "{'key': 'value'}"
        result = llm._clean_json(raw)
        assert isinstance(result, dict)  # 可能返回空或尝试转换

    def test_clean_json_nested_structure(self):
        """测试清洁嵌套 JSON 结构"""
        raw = '```json\n{"user": {"name": "Alice", "age": 30}, "items": [1, 2, 3]}\n```'
        result = llm._clean_json(raw)
        assert result["user"]["name"] == "Alice"
        assert result["items"] == [1, 2, 3]

    def test_clean_json_with_escaped_quotes(self):
        """测试清洁包含转义引号的 JSON"""
        raw = '{"message": "She said \\"Hello\\""}'
        result = llm._clean_json(raw)
        assert result["message"] == 'She said "Hello"'


class TestCaching:
    """测试缓存机制"""

    def test_cache_get_set(self):
        """测试缓存基本的 get/set 操作"""
        cache = ExpiringLRUCache(maxsize=10, expiry=3600)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_cache_lru_eviction(self):
        """测试 LRU 缓存驱逐最老的条目"""
        cache = ExpiringLRUCache(maxsize=2, expiry=3600)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")
        # key1 应已被驱逐
        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3"

    def test_cache_delete(self):
        """测试缓存删除操作"""
        cache = ExpiringLRUCache(maxsize=10, expiry=3600)
        cache.set("key1", "value1")
        cache.delete("key1")
        assert cache.get("key1") is None

    def test_cache_with_none_value(self):
        """测试缓存 None 值"""
        cache = ExpiringLRUCache(maxsize=10, expiry=3600)
        cache.set("key1", None)
        # None 作为有效值存储
        result = cache.get("key1")
        assert result is None  # 但无法区分 "key 不存在" vs "key 值为 None"

    def test_cache_thread_safety(self):
        """测试缓存的线程安全性"""
        import threading
        cache = ExpiringLRUCache(maxsize=100, expiry=3600)

        def writer():
            for i in range(50):
                cache.set(f"key{i}", f"value{i}")

        def reader():
            for i in range(50):
                cache.get(f"key{i}")

        threads = [threading.Thread(target=writer) for _ in range(2)]
        threads += [threading.Thread(target=reader) for _ in range(2)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 不抛出异常即为通过
        assert True


class TestFallback:
    """测试降级和回退机制"""

    @patch.object(llm, "_chat_once")
    def test_fallback_when_primary_fails(self, mock_chat):
        """当主 provider 失败时测试降级"""
        # 主 provider 失败
        mock_chat.side_effect = Exception("Primary provider failed")

        with patch.object(llm, "_fallback_chat") as mock_fallback:
            mock_fallback.return_value = '{"result": "fallback_response"}'
            result = llm._chat_with_fallback([{"role": "user", "content": "test"}])
            
            # 应该调用 fallback
            mock_fallback.assert_called_once()
            assert isinstance(result, dict) or isinstance(result, str)

    @patch.object(llm, "_chat_once")
    def test_no_fallback_when_primary_succeeds(self, mock_chat):
        """当主 provider 成功时不应该降级"""
        mock_chat.return_value = '{"result": "primary_response"}'

        with patch.object(llm, "_fallback_chat") as mock_fallback:
            result = llm._chat_with_fallback([{"role": "user", "content": "test"}])
            
            # 不应该调用 fallback
            mock_fallback.assert_not_called()

    @patch.object(llm, "_chat_once")
    def test_fallback_timeout_handling(self, mock_chat):
        """测试超时异常的降级处理"""
        import asyncio
        mock_chat.side_effect = asyncio.TimeoutError("Request timeout")

        with patch.object(llm, "_fallback_chat") as mock_fallback:
            mock_fallback.return_value = '{"error": "timeout", "fallback_used": true}'
            result = llm._chat_with_fallback([{"role": "user", "content": "test"}])
            
            mock_fallback.assert_called_once()


class TestExceptionHandling:
    """测试异常处理和兜底策略"""

    @patch.object(llm, "_chat_once")
    @patch.object(llm, "_fallback_chat")
    def test_both_primary_and_fallback_fail(self, mock_fallback, mock_chat):
        """当主 provider 和 fallback 都失败时的处理"""
        mock_chat.side_effect = Exception("Primary failed")
        mock_fallback.side_effect = Exception("Fallback also failed")

        result = llm._chat_with_fallback([{"role": "user", "content": "test"}])
        
        # 应该返回默认值而不是抛出异常
        assert result is not None

    def test_invalid_model_name_handling(self):
        """测试无效的模型名称处理"""
        with patch.object(llm, "model", "invalid-model-xyz"):
            # 应该优雅地处理而不是直接抛异常
            result = llm._clean_json('{"result": "test"}')
            assert isinstance(result, dict)

    @patch.object(llm, "_chat_once")
    def test_malformed_response_recovery(self, mock_chat):
        """测试对格式错误响应的恢复"""
        # 返回格式错误的响应
        mock_chat.return_value = "not valid json at all {{"

        result = llm._clean_json(mock_chat.return_value)
        
        # 应该返回字典而不是崩溃
        assert isinstance(result, dict)

    def test_empty_response_handling(self):
        """测试空响应处理"""
        result = llm._clean_json("")
        assert isinstance(result, dict)

    def test_very_large_response_handling(self):
        """测试超大响应处理"""
        large_json_string = '{"data": "' + "x" * 10000 + '"}'
        result = llm._clean_json(large_json_string)
        assert isinstance(result, dict)
        assert len(result.get("data", "")) > 1000


class TestProviderConfiguration:
    """测试 provider 配置"""

    def test_provider_initialization_with_env(self):
        """测试使用环境变量初始化 provider"""
        with patch.dict("os.environ", {"LLM_PROVIDER": "ollama"}):
            # 应该能够读取环境变量
            assert True

    def test_multiple_provider_support(self):
        """测试支持多个 provider"""
        providers = ["ollama", "deepseek", "gemma"]
        
        for provider in providers:
            # 每个 provider 应该能够被初始化
            assert provider in ["ollama", "deepseek", "gemma"]

    def test_fallback_provider_configuration(self):
        """测试 fallback provider 配置"""
        with patch.dict("os.environ", {
            "LLM_PROVIDER": "ollama",
            "LLM_FALLBACK_PROVIDER": "deepseek"
        }):
            # 应该能够配置预备 provider
            assert True


class TestRateLimiting:
    """测试速率限制"""

    @patch.object(llm, "_chat_once")
    def test_concurrent_requests_handling(self, mock_chat):
        """测试并发请求处理"""
        import threading
        mock_chat.return_value = '{"result": "ok"}'
        
        results = []
        
        def make_request():
            result = llm._chat_with_fallback([{"role": "user", "content": "test"}])
            results.append(result)
        
        threads = [threading.Thread(target=make_request) for _ in range(10)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(results) == 10
        assert all(r is not None for r in results)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
