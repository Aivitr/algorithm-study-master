#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快速测试启动脚本
一键运行所有 P4 测试：单元测试、接口测试、回归测试、压测

用法：
  python run_all_tests.py
  或
  python run_all_tests.py --quick  （跳过压测）
"""
import subprocess
import sys
import os
import time
import argparse
from datetime import datetime


class Colors:
    """终端颜色"""
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'


def print_header(text: str):
    """打印标题"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*70}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text:^70}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*70}{Colors.END}\n")


def print_success(text: str):
    """打印成功信息"""
    print(f"{Colors.GREEN}✓ {text}{Colors.END}")


def print_error(text: str):
    """打印错误信息"""
    print(f"{Colors.RED}✗ {text}{Colors.END}")


def print_info(text: str):
    """打印信息"""
    print(f"{Colors.BLUE}ℹ {text}{Colors.END}")


def run_command(cmd: list, verbose: bool = False) -> tuple:
    """
    运行命令
    返回：(return_code, stdout, stderr)
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "命令超时"
    except Exception as e:
        return -1, "", str(e)


def check_server():
    """检查服务器是否运行"""
    import httpx
    try:
        client = httpx.Client(timeout=2)
        response = client.get("http://127.0.0.1:8000/docs")
        client.close()
        return True
    except:
        return False


def main():
    parser = argparse.ArgumentParser(description="运行所有 P4 测试")
    parser.add_argument("--quick", action="store_true", help="跳过压测（仅运行单元、接口、回归测试）")
    parser.add_argument("--verbose", action="store_true", help="显示详细输出")
    parser.add_argument("--skip-server-check", action="store_true", help="跳过服务器检查")
    args = parser.parse_args()

    print_header("P4 测试执行框架")
    print_info(f"启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print_info(f"快速模式: {'是' if args.quick else '否'}")
    print_info(f"详细模式: {'是' if args.verbose else '否'}")

    # 检查必需文件
    print_header("前置条件检查")
    required_files = [
        "llm_service.py",
        "ai_core.py",
        "speaker_diarizer.py",
        "tests/test_llm_adapter.py",
        "tests/test_llm_endpoints.py",
        "tests/regression_test.py",
    ]

    missing_files = []
    for file in required_files:
        if os.path.exists(file):
            print_success(f"文件存在: {file}")
        else:
            print_error(f"文件缺失: {file}")
            missing_files.append(file)

    if missing_files:
        print_error(f"缺失 {len(missing_files)} 个必需文件，请检查项目结构")
        return 1

    # 检查服务器（如果不跳过检查且需要接口测试）
    if not args.skip_server_check:
        print_header("服务器状态检查")
        if check_server():
            print_success("服务器运行正常 (http://127.0.0.1:8000)")
        else:
            print_error("无法连接到服务器 (http://127.0.0.1:8000)")
            print_info("请在另一个终端运行: python server.py")
            input("按 Enter 继续，或按 Ctrl+C 中止...")

    # 测试清单
    tests = [
        {
            "name": "单元测试",
            "cmd": ["pytest", "tests/test_llm_adapter.py", "-v"],
            "skip": False
        },
        {
            "name": "接口测试",
            "cmd": ["pytest", "tests/test_llm_endpoints.py", "-v", "-s"],
            "skip": False
        },
        {
            "name": "回归测试",
            "cmd": ["python", "tests/regression_test.py"],
            "skip": False
        },
        {
            "name": "压测",
            "cmd": ["python", "tests/load_test.py"],
            "skip": args.quick
        }
    ]

    # 执行测试
    print_header("开始执行测试")

    results = []
    start_time = time.time()

    for i, test in enumerate(tests, 1):
        if test["skip"]:
            print_info(f"[{i}/{len([t for t in tests if not t['skip']])}] 跳过: {test['name']}")
            continue

        print_header(f"[{i}/{len([t for t in tests if not t['skip']])}] {test['name']}")

        test_start = time.time()
        returncode, stdout, stderr = run_command(test["cmd"], verbose=args.verbose)
        test_duration = time.time() - test_start

        if returncode == 0:
            print_success(f"{test['name']} 通过 ({test_duration:.1f}s)")
            results.append((test["name"], True, test_duration))
        else:
            print_error(f"{test['name']} 失败 ({test_duration:.1f}s)")
            results.append((test["name"], False, test_duration))
            if stderr:
                print_error(f"错误信息:\n{stderr[:500]}")

    total_duration = time.time() - start_time

    # 总结报告
    print_header("测试执行总结")

    for test_name, passed, duration in results:
        status = f"{Colors.GREEN}✓ 通过{Colors.END}" if passed else f"{Colors.RED}✗ 失败{Colors.END}"
        print(f"{status} | {test_name:20s} | {duration:6.1f}s")

    total_tests = len(results)
    passed_tests = sum(1 for _, passed, _ in results if passed)
    failed_tests = total_tests - passed_tests

    print(f"\n总计: {total_tests} 个测试")
    print(f"通过: {Colors.GREEN}{passed_tests}{Colors.END} ✓")
    print(f"失败: {Colors.RED}{failed_tests}{Colors.END} ✗")
    print(f"总耗时: {Colors.YELLOW}{total_duration:.1f}s{Colors.END}")

    success_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0
    if success_rate == 100:
        print(f"成功率: {Colors.GREEN}{success_rate:.1f}%{Colors.END} ✓")
    else:
        print(f"成功率: {Colors.RED}{success_rate:.1f}%{Colors.END} ✗")

    print_info(f"完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 输出建议
    if failed_tests > 0:
        print_header("后续步骤")
        print_error("检测到测试失败，请：")
        print("1. 查看详细测试输出")
        print("2. 检查错误日志")
        print("3. 修复相关代码")
        print("4. 重新运行测试")

    print_header("✓ P4 测试框架执行完毕")

    return 0 if failed_tests == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print_error("\n测试被中断")
        sys.exit(1)
    except Exception as e:
        print_error(f"执行失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
