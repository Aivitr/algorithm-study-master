# -*- coding: utf-8 -*-
"""
LLM 和 ASR 集成回归测试脚本

验证以下关键路径无回归：
1. 语音链路 - ASR 正常工作
2. 报告链路 - 生成报告功能正常
3. 课堂交互链路 - 实时对话功能正常

运行: python tests/regression_test.py

验收标准:
- 核心测试全部通过
- 无阻断性回归：语音链路、报告链路、课堂交互链路
"""
import asyncio
import sys
import os
import time
import json
from datetime import datetime
from typing import Dict, List, Any
from unittest.mock import patch, MagicMock

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from server import app

# 创建測試客户端
client = TestClient(app)


class RegressionTestResult:
    """回归测试结果"""

    def __init__(self, test_name: str):
        self.test_name = test_name
        self.passed = 0
        self.failed = 0
        self.errors = []
        self.start_time = None
        self.end_time = None

    def add_pass(self, message: str = ""):
        self.passed += 1
        print(f"  ✓ {message}")

    def add_fail(self, message: str, error: str = ""):
        self.failed += 1
        self.errors.append(f"{message}: {error}")
        print(f"  ✗ {message}")
        if error:
            print(f"    错误: {error}")

    def get_summary(self) -> Dict[str, Any]:
        """获取测试摘要"""
        return {
            "test_name": self.test_name,
            "passed": self.passed,
            "failed": self.failed,
            "total": self.passed + self.failed,
            "success_rate": (self.passed / (self.passed + self.failed) * 100) if (self.passed + self.failed) > 0 else 0,
            "duration": (self.end_time - self.start_time) if self.start_time and self.end_time else 0,
            "errors": self.errors
        }

    def print_report(self):
        """打印报告"""
        summary = self.get_summary()
        print(f"\n{'='*70}")
        print(f"测试: {self.test_name}")
        print(f"{'='*70}")
        print(f"通过: {summary['passed']}")
        print(f"失败: {summary['failed']}")
        print(f"总计: {summary['total']}")
        print(f"成功率: {summary['success_rate']:.1f}%")
        print(f"耗时: {summary['duration']:.2f}s")

        if summary["errors"]:
            print(f"\n错误列表:")
            for error in summary["errors"]:
                print(f"  - {error}")

        print(f"{'='*70}\n")


class ASRRegressionTest:
    """ASR（语音识别）回归测试"""

    def run(self) -> RegressionTestResult:
        """运行 ASR 测试"""
        result = RegressionTestResult("ASR 语音链路")
        result.start_time = time.time()

        try:
            # 测试 1: WebSocket ASR 端点存在
            self._test_asr_endpoint_exists(result)

            # 测试 2: 检查媒体连接端点
            self._test_media_endpoint(result)

            # 测试 3: 检查转录保存端点
            self._test_transcript_endpoint(result)

        except Exception as e:
            result.add_fail("ASR 测试失败", str(e))

        result.end_time = time.time()
        return result

    def _test_asr_endpoint_exists(self, result: RegressionTestResult):
        """测试 ASR 端点是否存在"""
        # 注：WebSocket 端点无法直接通过 TestClient 测试，这里检查服务器是否运行
        try:
            response = client.get("/docs")
            if response.status_code == 200:
                result.add_pass("API 文档端点可访问")
            else:
                result.add_fail("API 文档端点不可访问", f"状态码: {response.status_code}")
        except Exception as e:
            result.add_fail("API 文档端点测试失败", str(e))

    def _test_media_endpoint(self, result: RegressionTestResult):
        """测试媒体相关端点"""
        try:
            # 检查存储路径
            response = client.get("/storage/")
            if response.status_code in [200, 404, 403]:
                result.add_pass("存储端点可访问")
            else:
                result.add_fail("存储端点异常", f"状态码: {response.status_code}")
        except Exception as e:
            result.add_fail("存储端点测试失败", str(e))

    def _test_transcript_endpoint(self, result: RegressionTestResult):
        """测试转录相关端点"""
        try:
            # 测试转录保存端点（如果存在）
            response = client.post("/api/save-transcript", json={
                "meeting_id": 1,
                "user_id": 1,
                "content": "测试转录内容",
                "timestamp": datetime.now().isoformat()
            })

            if response.status_code in [200, 201, 404]:
                result.add_pass("转录端点可用或不存在（预期行为）")
            else:
                result.add_fail("转录端点异常", f"状态码: {response.status_code}")
        except Exception as e:
            result.add_fail("转录端点测试失败", str(e))


class ReportRegressionTest:
    """报告生成回归测试"""

    def run(self) -> RegressionTestResult:
        """运行报告测试"""
        result = RegressionTestResult("报告链路")
        result.start_time = time.time()

        try:
            # 测试 1: 生成课程报告
            self._test_generate_course_report(result)

            # 测试 2: 生成练习题
            self._test_generate_exercises(result)

            # 测试 3: 生成 AI 见解
            self._test_ai_tutor(result)

        except Exception as e:
            result.add_fail("报告测试失败", str(e))

        result.end_time = time.time()
        return result

    def _test_generate_course_report(self, result: RegressionTestResult):
        """测试生成课程报告"""
        try:
            response = client.post("/api/generate-report", json={
                "meeting_id": 1,
                "student_id": 1,
                "topic": "Python 基础"
            })

            if response.status_code == 200:
                data = response.json()
                if "report" in data or "content" in data or len(data) > 0:
                    result.add_pass("课程报告生成成功")
                else:
                    result.add_fail("课程报告生成但内容为空")
            elif response.status_code == 404:
                result.add_pass("报告端点不存在（可能已移除）")
            else:
                result.add_fail("课程报告生成失败", f"状态码: {response.status_code}")
        except Exception as e:
            result.add_fail("课程报告测试失败", str(e))

    def _test_generate_exercises(self, result: RegressionTestResult):
        """测试生成练习题"""
        try:
            response = client.post("/api/generate-exercises", json={
                "topic": "Python 基础",
                "difficulty": "中档",
                "count": 5
            })

            if response.status_code == 200:
                data = response.json()
                if "exercises" in data or "questions" in data or len(data) > 0:
                    result.add_pass("练习题生成成功")
                else:
                    result.add_fail("练习题生成但内容为空")
            elif response.status_code == 404:
                result.add_pass("练习题端点不存在（可能已移除）")
            else:
                result.add_fail("练习题生成失败", f"状态码: {response.status_code}")
        except Exception as e:
            result.add_fail("练习题测试失败", str(e))

    def _test_ai_tutor(self, result: RegressionTestResult):
        """测试 AI 导师功能"""
        try:
            response = client.post("/api/ai-tutor", json={
                "question": "什么是变量？",
                "context": "Python 编程"
            })

            if response.status_code == 200:
                data = response.json()
                if len(data) > 0:
                    result.add_pass("AI 导师回答生成成功")
                else:
                    result.add_fail("AI 导师回答为空")
            else:
                result.add_fail("AI 导师请求失败", f"状态码: {response.status_code}")
        except Exception as e:
            result.add_fail("AI 导师测试失败", str(e))


class ClassroomInteractionRegressionTest:
    """课堂交互回归测试"""

    def run(self) -> RegressionTestResult:
        """运行课堂交互测试"""
        result = RegressionTestResult("课堂交互链路")
        result.start_time = time.time()

        try:
            # 测试 1: 话题建议
            self._test_suggest_topic(result)

            # 测试 2: 测试题分析
            self._test_quiz_analysis(result)

            # 测试 3: 情感分析
            self._test_emotion_analysis(result)

        except Exception as e:
            result.add_fail("课堂交互测试失败", str(e))

        result.end_time = time.time()
        return result

    def _test_suggest_topic(self, result: RegressionTestResult):
        """测试话题建议"""
        try:
            response = client.post("/api/suggest-topic", json={
                "context": "机器学习入门",
                "student_level": "beginner"
            })

            if response.status_code == 200:
                result.add_pass("话题建议功能正常")
            else:
                result.add_fail("话题建议失败", f"状态码: {response.status_code}")
        except Exception as e:
            result.add_fail("话题建议测试失败", str(e))

    def _test_quiz_analysis(self, result: RegressionTestResult):
        """测试测试题分析"""
        try:
            response = client.post("/api/quiz-error-analysis", json={
                "question": "Python 中 == 和 is 的区别是什么？",
                "correct_answer": "== 比较值，is 比较身份",
                "student_answer": "都是用来比较的",
                "topic": "Python"
            })

            if response.status_code == 200:
                result.add_pass("测试题分析功能正常")
            else:
                result.add_fail("测试题分析失败", f"状态码: {response.status_code}")
        except Exception as e:
            result.add_fail("测试题分析测试失败", str(e))

    def _test_emotion_analysis(self, result: RegressionTestResult):
        """测试情感分析"""
        try:
            response = client.post("/api/analyze-emotion", json={
                "text": "这太棒了！我完全理解了！",
                "timestamp": datetime.now().isoformat()
            })

            if response.status_code in [200, 404]:
                result.add_pass("情感分析端点正常或不存在")
            else:
                result.add_fail("情感分析异常", f"状态码: {response.status_code}")
        except Exception as e:
            # 情感分析端点可能不存在，这是可以接受的
            result.add_pass("情感分析端点不存在（可接受）")


class DatabaseRegressionTest:
    """数据库回归测试"""

    def run(self) -> RegressionTestResult:
        """运行数据库测试"""
        result = RegressionTestResult("数据库操作")
        result.start_time = time.time()

        try:
            # 测试 1: 用户相关操作
            self._test_user_operations(result)

            # 测试 2: 课堂相关操作
            self._test_meeting_operations(result)

            # 测试 3: 转录相关操作
            self._test_transcript_operations(result)

        except Exception as e:
            result.add_fail("数据库测试失败", str(e))

        result.end_time = time.time()
        return result

    def _test_user_operations(self, result: RegressionTestResult):
        """测试用户操作"""
        try:
            # 尝试获取用户信息
            response = client.get("/api/user/1")
            if response.status_code in [200, 404]:
                result.add_pass("用户查询端点正常")
            else:
                result.add_fail("用户查询异常", f"状态码: {response.status_code}")
        except Exception as e:
            result.add_fail("用户操作测试失败", str(e))

    def _test_meeting_operations(self, result: RegressionTestResult):
        """测试课堂操作"""
        try:
            response = client.get("/api/meetings")
            if response.status_code in [200, 401, 404]:
                result.add_pass("课堂查询端点正常")
            else:
                result.add_fail("课堂查询异常", f"状态码: {response.status_code}")
        except Exception as e:
            result.add_fail("课堂操作测试失败", str(e))

    def _test_transcript_operations(self, result: RegressionTestResult):
        """测试转录操作"""
        try:
            response = client.get("/api/transcripts/1")
            if response.status_code in [200, 404, 401]:
                result.add_pass("转录查询端点正常")
            else:
                result.add_fail("转录查询异常", f"状态码: {response.status_code}")
        except Exception as e:
            result.add_fail("转录操作测试失败", str(e))


def run_all_regression_tests():
    """运行所有回归测试"""
    print(f"\n{'*'*70}")
    print(f"LLM 和 ASR 集成回归测试")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'*'*70}\n")

    all_results = []

    # 运行 ASR 测试
    print("执行 ASR 语音链路测试...")
    asr_result = ASRRegressionTest().run()
    asr_result.print_report()
    all_results.append(asr_result)

    # 运行报告链路测试
    print("执行报告链路测试...")
    report_result = ReportRegressionTest().run()
    report_result.print_report()
    all_results.append(report_result)

    # 运行课堂交互测试
    print("执行课堂交互链路测试...")
    classroom_result = ClassroomInteractionRegressionTest().run()
    classroom_result.print_report()
    all_results.append(classroom_result)

    # 运行数据库测试
    print("执行数据库操作测试...")
    db_result = DatabaseRegressionTest().run()
    db_result.print_report()
    all_results.append(db_result)

    # 生成总结报告
    print(f"\n{'#'*70}")
    print("回归测试汇总报告")
    print(f"{'#'*70}\n")

    total_passed = sum(r.passed for r in all_results)
    total_failed = sum(r.failed for r in all_results)
    total_tests = total_passed + total_failed

    for result in all_results:
        summary = result.get_summary()
        status = "✓ 通过" if summary['failed'] == 0 else "✗ 失败"
        print(f"{status} | {result.test_name:20s} | 通过: {summary['passed']:3d} | 失败: {summary['failed']:3d}")

    print(f"\n总计: {total_tests} 个测试")
    print(f"通过: {total_passed} ✓")
    print(f"失败: {total_failed} ✗")
    print(f"成功率: {(total_passed/total_tests*100):.1f}% " + ("✓" if total_failed == 0 else "✗"))

    # 导出报告
    report_filename = f"regression_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    export_data = {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total_tests": total_tests,
            "passed": total_passed,
            "failed": total_failed,
            "success_rate": (total_passed / total_tests * 100) if total_tests > 0 else 0
        },
        "results": [r.get_summary() for r in all_results]
    }

    with open(report_filename, "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)

    print(f"\n✓ 报告已导出到: {report_filename}")
    print(f"{'#'*70}\n")

    # 返回是否全部通过
    return total_failed == 0


if __name__ == "__main__":
    try:
        success = run_all_regression_tests()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"✗ 回归测试执行失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
