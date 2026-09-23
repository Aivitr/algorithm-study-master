# -*- coding: utf-8 -*-
"""
LLM 端点负载测试（并发 10 用户，记录 P50/P95 延迟）

运行:
  python tests/load_test.py
  或者 pytest tests/load_test.py --tb=short

支持的端点:
  - /api/ai-tutor
  - /api/suggest-topic
  - /api/quiz-error-analysis
"""
import asyncio
import httpx
import time
import json
import statistics
from datetime import datetime
from typing import List, Dict, Any
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 配置
BASE_URL = "http://127.0.0.1:8000"
CONCURRENT_USERS = 10
REQUESTS_PER_USER = 5
REQUEST_TIMEOUT = 60

# 测试数据
TEST_SCENARIOS = {
    "ai_tutor": {
        "endpoint": "/api/ai-tutor",
        "method": "POST",
        "payload": {
            "question": "请解释什么是人工智能？",
            "context": "高中生物学"
        }
    },
    "suggest_topic": {
        "endpoint": "/api/suggest-topic",
        "method": "POST",
        "payload": {
            "context": "正在学习机器学习基础",
            "student_level": "intermediate"
        }
    },
    "quiz_error_analysis": {
        "endpoint": "/api/quiz-error-analysis",
        "method": "POST",
        "payload": {
            "question": "地球绕太阳公转一周需要多少时间？",
            "correct_answer": "365天",
            "student_answer": "360天",
            "topic": "天文学"
        }
    }
}


class LoadTestResult:
    """负载测试结果"""

    def __init__(self, scenario_name: str, endpoint: str):
        self.scenario_name = scenario_name
        self.endpoint = endpoint
        self.response_times: List[float] = []
        self.errors: List[str] = []
        self.successful_requests = 0
        self.failed_requests = 0
        self.start_time = None
        self.end_time = None

    def add_response_time(self, elapsed: float):
        """添加响应时间"""
        self.response_times.append(elapsed)
        self.successful_requests += 1

    def add_error(self, error: str):
        """添加错误"""
        self.errors.append(error)
        self.failed_requests += 1

    def calculate_statistics(self):
        """计算统计信息"""
        if not self.response_times:
            return {}

        sorted_times = sorted(self.response_times)
        stats = {
            "count": len(sorted_times),
            "successful": self.successful_requests,
            "failed": self.failed_requests,
            "total_requests": self.successful_requests + self.failed_requests,
            "min": min(sorted_times),
            "max": max(sorted_times),
            "mean": statistics.mean(sorted_times),
            "median": statistics.median(sorted_times),
            "p50": sorted_times[int(len(sorted_times) * 0.50)],
            "p75": sorted_times[int(len(sorted_times) * 0.75)],
            "p90": sorted_times[int(len(sorted_times) * 0.90)],
            "p95": sorted_times[int(len(sorted_times) * 0.95)],
            "p99": sorted_times[int(len(sorted_times) * 0.99)] if len(sorted_times) > 10 else sorted_times[-1],
            "stddev": statistics.stdev(sorted_times) if len(sorted_times) > 1 else 0,
        }

        if self.start_time and self.end_time:
            total_time = self.end_time - self.start_time
            stats["total_time"] = total_time
            stats["requests_per_second"] = self.successful_requests / total_time if total_time > 0 else 0

        return stats

    def print_report(self):
        """打印结果报告"""
        stats = self.calculate_statistics()

        print(f"\n{'='*70}")
        print(f"段测试结果: {self.scenario_name} ({self.endpoint})")
        print(f"{'='*70}")
        print(f"并发用户数: {CONCURRENT_USERS}")
        print(f"每用户请求数: {REQUESTS_PER_USER}")
        print(f"总请求数: {stats.get('total_requests', 0)}")
        print(f"成功: {stats.get('successful', 0)}")
        print(f"失败: {stats.get('failed', 0)}")

        if stats.get("failed", 0) > 0:
            print(f"\n错误列表:")
            for error in self.errors[:5]:  # 只显示前5个错误
                print(f"  - {error}")

        print(f"\n响应时间统计 (秒):")
        print(f"  最小值(Min): {stats.get('min', 0):.3f}s")
        print(f"  最大值(Max): {stats.get('max', 0):.3f}s")
        print(f"  平均值(Mean): {stats.get('mean', 0):.3f}s")
        print(f"  中位数(P50): {stats.get('p50', 0):.3f}s  ⭐ 重点关注")
        print(f"  75百分位(P75): {stats.get('p75', 0):.3f}s")
        print(f"  90百分位(P90): {stats.get('p90', 0):.3f}s")
        print(f"  95百分位(P95): {stats.get('p95', 0):.3f}s  ⭐ 重点关注")
        print(f"  99百分位(P99): {stats.get('p99', 0):.3f}s")
        print(f"  标准差(StdDev): {stats.get('stddev', 0):.3f}s")

        if stats.get("total_time"):
            print(f"\n总耗时: {stats.get('total_time', 0):.2f}s")
            print(f"吞吐量: {stats.get('requests_per_second', 0):.2f} req/s")

        print(f"{'='*70}\n")

    def export_json(self, filename: str):
        """导出为 JSON 格式"""
        stats = self.calculate_statistics()
        data = {
            "scenario": self.scenario_name,
            "endpoint": self.endpoint,
            "timestamp": datetime.now().isoformat(),
            "config": {
                "concurrent_users": CONCURRENT_USERS,
                "requests_per_user": REQUESTS_PER_USER,
            },
            "statistics": stats,
            "response_times": {
                "all": self.response_times,
                "sorted": sorted(self.response_times)
            }
        }

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"结果已导出到: {filename}")


async def make_request(client: httpx.AsyncClient, endpoint: str, payload: Dict[str, Any]) -> float:
    """发送单个请求并返回响应时间"""
    start_time = time.time()

    try:
        response = await client.post(
            f"{BASE_URL}{endpoint}",
            json=payload,
            timeout=REQUEST_TIMEOUT
        )
        elapsed = time.time() - start_time

        # 检查响应状态
        if response.status_code not in [200, 201]:
            raise Exception(f"HTTP {response.status_code}")

        return elapsed

    except asyncio.TimeoutError as e:
        elapsed = time.time() - start_time
        raise Exception(f"Timeout after {elapsed:.2f}s")

    except Exception as e:
        elapsed = time.time() - start_time
        raise Exception(f"{type(e).__name__}: {str(e)}")


async def simulate_user(client: httpx.AsyncClient, user_id: int, endpoint: str, payload: Dict[str, Any], result: LoadTestResult):
    """模拟单个用户的行为"""
    for request_num in range(REQUESTS_PER_USER):
        try:
            elapsed = await make_request(client, endpoint, payload)
            result.add_response_time(elapsed)
            print(f"  用户 {user_id} 请求 {request_num + 1}/{REQUESTS_PER_USER}: {elapsed:.3f}s ✓")

        except Exception as e:
            result.add_error(str(e))
            print(f"  用户 {user_id} 请求 {request_num + 1}/{REQUESTS_PER_USER}: 失败 - {e} ✗")

        # 用户之间请求间隔
        await asyncio.sleep(0.5)


async def run_load_test_scenario(scenario_name: str, scenario_config: Dict[str, Any]) -> LoadTestResult:
    """运行单个负载测试场景"""
    endpoint = scenario_config["endpoint"]
    payload = scenario_config["payload"]

    result = LoadTestResult(scenario_name, endpoint)
    result.start_time = time.time()

    print(f"\n开始测试: {scenario_name}")
    print(f"端点: {endpoint}")
    print(f"并发用户: {CONCURRENT_USERS}, 每用户请求: {REQUESTS_PER_USER}")

    async with httpx.AsyncClient() as client:
        # 创建并发任务
        tasks = [
            simulate_user(client, user_id, endpoint, payload, result)
            for user_id in range(1, CONCURRENT_USERS + 1)
        ]

        # 等待所有用户完成
        await asyncio.gather(*tasks)

    result.end_time = time.time()

    return result


async def run_all_tests():
    """运行所有测试场景"""
    print(f"\n{'*'*70}")
    print(f"LLM 端点负载测试")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"并发用户数: {CONCURRENT_USERS}")
    print(f"每用户请求数: {REQUESTS_PER_USER}")
    print(f"请求超时: {REQUEST_TIMEOUT}s")
    print(f"目标 URL: {BASE_URL}")
    print(f"{'*'*70}")

    results: Dict[str, LoadTestResult] = {}

    for scenario_name, scenario_config in TEST_SCENARIOS.items():
        try:
            result = await run_load_test_scenario(scenario_name, scenario_config)
            results[scenario_name] = result
            result.print_report()

        except Exception as e:
            print(f"测试 {scenario_name} 失败: {e}")

    # 生成汇总报告
    print(f"\n{'#'*70}")
    print("测试汇总报告")
    print(f"{'#'*70}")

    summary_data = {
        "timestamp": datetime.now().isoformat(),
        "config": {
            "base_url": BASE_URL,
            "concurrent_users": CONCURRENT_USERS,
            "requests_per_user": REQUESTS_PER_USER,
            "request_timeout": REQUEST_TIMEOUT,
        },
        "scenarios": {}
    }

    for scenario_name, result in results.items():
        stats = result.calculate_statistics()
        summary_data["scenarios"][scenario_name] = {
            "endpoint": result.endpoint,
            "statistics": stats
        }

        print(f"\n{scenario_name}:")
        print(f"  P50: {stats.get('p50', 0):.3f}s | P95: {stats.get('p95', 0):.3f}s | 成功率: {stats.get('successful', 0)}/{stats.get('total_requests', 0)}")

    # 导出结果
    report_filename = f"load_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_filename, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2, ensure_ascii=False)

    print(f"\n✓ 完整报告已导出到: {report_filename}")
    print(f"完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*70}\n")


def main():
    """主函数"""
    # 检查服务器连接
    print("检查服务器连接...")
    try:
        import httpx
        client = httpx.Client(timeout=5)
        response = client.get(f"{BASE_URL}/docs", follow_redirects=True)
        client.close()
        print(f"✓ 服务器可访问: {BASE_URL}")
    except Exception as e:
        print(f"✗ 无法连接到服务器: {BASE_URL}")
        print(f"  错误: {e}")
        print(f"  请确保服务器正在运行: python server.py")
        return

    # 运行测试
    try:
        asyncio.run(run_all_tests())
    except KeyboardInterrupt:
        print("\n测试被中断")
    except Exception as e:
        print(f"测试出错: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()