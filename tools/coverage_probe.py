"""实测一批模块的测试覆盖率——**不引入任何新依赖**。

本脚本只用两样东西：

- `sys.settrace`——CPython 自带的行级跟踪钩子；
- 字节码的 `co_lines()`——**精确**给出「会执行的行」，比"非空非注释行"准。

用法：

    python tools/coverage_probe.py            # 跑整套测试并报告
    python tools/coverage_probe.py -k 某测试   # 透传参数给 pytest
"""

import ast
import os
import sys
import types

# 要统计覆盖率的 15 个运行期模块
RUNTIME_MODULES = [
    "server.py",
    "ai_core.py",
    "app/core/config.py",
    "app/core/database.py",
    "gemma_emotion_client.py",
    "knowledge_graph_service.py",
    "llm_service.py",
    "oss_config.py",
    "oss_utils.py",
    "research_algorithm_fusion.py",
    "research_enhanced_adapters.py",
    "research_registry.py",
    "research_runtime.py",
    "video_processor.py",
    "voiceprint_manager.py",
]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def executable_lines(path: str) -> set:
    """用字节码 `co_lines()` 求「会执行的行号」。

    这与「非空、非注释行」不同：docstring、`if TYPE_CHECKING:` 分支等
    不会产生字节码，用文本法会把它们算进去，从而**低估**覆盖率。
    """
    try:
        source = open(path, encoding="utf-8", errors="replace").read()
        code = compile(source, path, "exec")
    except (SyntaxError, OSError):
        return set()

    lines, stack = set(), [code]
    while stack:
        current = stack.pop()
        lines.update(lineno for _, _, lineno in current.co_lines() if lineno)
        stack.extend(c for c in current.co_consts if isinstance(c, types.CodeType))
    return lines


def child_classes(module_path: str) -> dict:
    """列出模块里的顶层类及其行号区间——用于单看某一个类的覆盖率。"""
    try:
        tree = ast.parse(open(module_path, encoding="utf-8", errors="replace").read())
    except (SyntaxError, OSError):
        return {}
    return {
        node.name: (node.lineno, node.end_lineno)
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    }


def main() -> int:
    pytest_args = sys.argv[1:] or ["-q", "-p", "no:cacheprovider"]

    targets = [os.path.join(ROOT, name) for name in RUNTIME_MODULES]
    total = {t: executable_lines(t) for t in targets}
    hits = {t: set() for t in targets}
    watched = set(targets)

    def tracer(frame, event, arg):
        filename = frame.f_code.co_filename
        if filename in watched:
            if event == "line":
                hits[filename].add(frame.f_lineno)
            return tracer
        return None  # 其余文件（含 pytest 自身）一概不跟踪，避免拖慢

    import pytest

    sys.settrace(tracer)
    try:
        code = pytest.main(pytest_args)
    finally:
        sys.settrace(None)

    print("\n" + "=" * 74)
    print(f"{'模块':<34}{'可执行':>8}{'被执行':>8}{'覆盖率':>10}")
    print("=" * 74)
    hit_total = line_total = 0
    for path in targets:
        n, h = len(total[path]), len(hits[path])
        hit_total += h
        line_total += n
        print(f"{os.path.basename(path):<34}{n:>8}{h:>8}{100 * h / n if n else 0:>9.1f}%")
    print("-" * 74)
    print(
        f"{'合计':<34}{line_total:>8}{hit_total:>8}"
        f"{100 * hit_total / line_total if line_total else 0:>9.1f}%"
    )

    # 单独看某个类（整体数字不够用）
    server = os.path.join(ROOT, "server.py")
    classes = child_classes(server)
    if classes:
        print("\nserver.py 顶层类：")
        print(f"  {'类':<34}{'行区间':>14}{'覆盖率':>10}")
        for name, (lo, hi) in classes.items():
            sub_total = {ln for ln in total[server] if lo <= ln <= hi}
            sub_hit = {ln for ln in hits[server] if lo <= ln <= hi}
            if not sub_total:
                continue
            print(
                f"  {name:<34}{f'{lo}-{hi}':>14}"
                f"{100 * len(sub_hit) / len(sub_total):>9.1f}%"
            )

    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
