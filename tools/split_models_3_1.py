"""把 ORM 模型从仓库根的 `database.py` **逐字**搬进 `app/models/`。

为什么用脚本搬，而不是手抄
--------------------------
`database.py` 的注释里含有 73 处字面量 `[EMOJI]` 占位符。手工重打一遍，任何一处
空白或字符的出入都不会有人发现。

本脚本的做法是**按 AST 求出的行区间直接从源文件切片**，搬移后再把写出的每一行
与源行逐字节比对。所以「逐字等价」在这里不是一句承诺，是一条能重跑的检查。

用法
----
    python tools/split_models_3_1.py            # 预演：只打印计划与校验结果
    python tools/split_models_3_1.py --write    # 执行搬移
    python tools/split_models_3_1.py --verify   # 只校验现有 app/models/ 与源一致

`--verify` 读的是 `git show HEAD:database.py`——搬移之后 `database.py` 里已经没有
这些类了，只能回到索引里取原文。这使校验在搬移之后仍然可复现。

搬移的边界
----------
本脚本**只搬类定义与那三条 `Index()`**。`engine` / `SessionLocal` / `get_db` /
`_ensure_transcripts_columns()` 留在 `database.py`，本步不动。
"""

from __future__ import annotations

import argparse
import ast
import builtins
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = "database.py"
MODELS_DIR = ROOT / "app" / "models"

# ---------------------------------------------------------------- 分组
# 「一个类一个文件」对 15 个模型来说过于零碎；这里按领域分组成 8 个模块，
# 分组只体现职责，不改变任何定义。
GROUPS: list[tuple[str, list[str], list[str]]] = [
    # (模块名, 类名（按原文件出现顺序）, 归属本模块的 Index 名)
    ("user", ["User"], []),
    ("classroom", ["Meeting", "MemberConnection"], []),
    ("transcript", ["Transcript"], ["idx_transcript_meeting_user"]),
    ("emotion", ["EmotionLog", "MentalHealthAssessment"], ["idx_emotion_meeting_user"]),
    ("insight", ["AIInsight"], []),
    ("knowledge_graph", ["KnowledgeGraph", "GraphNode", "GraphEdge"], []),
    ("learning", ["LearningReport", "Exercise", "StudentAnswer", "ReportTemplate"],
     ["idx_exercise_report"]),
    ("vote", ["ViewpointVote"], []),
]

MODULE_DOC = {
    "user": "用户账号（教师 / 学生）。",
    "classroom": "课堂会话与其成员在场状态。",
    "transcript": "课堂转写文本（含研究增强的跨模态绑定字段）。",
    "emotion": "情绪记录与心理健康评估。",
    "insight": "AI 生成的课堂洞察。",
    "knowledge_graph": "知识图谱：图、节点、边。",
    "learning": "学习报告、练习题、学生作答、报告模板。",
    "vote": "观点投票。",
}

# 每个名字需要哪个 import。用于给每个模块算出**恰好够用**的 import 头，
# 而不是统一塞一大串——统一塞会引入未使用导入，是纯粹的新噪声。
#
# 用名的判定走 AST 的 Name 节点，**不是**文本匹配（文本匹配会漏掉
# `Column(Text, nullable=False)` 这种 `Text` 后无括号的用法）。
_NAME_IMPORTS = {
    "Base": "from app.models.base import Base",
    "Column": "from sqlalchemy import Column",
    "DateTime": "from sqlalchemy import DateTime",
    "Float": "from sqlalchemy import Float",
    "ForeignKey": "from sqlalchemy import ForeignKey",
    "Index": "from sqlalchemy import Index",
    "Integer": "from sqlalchemy import Integer",
    "JSON": "from sqlalchemy import JSON",
    "String": "from sqlalchemy import String",
    "Text": "from sqlalchemy import Text",
    "NVARCHAR": "from sqlalchemy.dialects.mssql import NVARCHAR",
    "relationship": "from sqlalchemy.orm import relationship",
    "datetime": "from datetime import datetime",
}

HEADER = '''"""{doc}

阶段 3.1：本文件的类定义从仓库根的 `database.py` **逐字搬移**而来，只换了 import 头。
字段、默认值、注释（含字面量 `[EMOJI]` 占位符）一律未动——搬移与校验过程见
`tools/split_models_3_1.py`，可随时用 `--verify` 重跑。
"""

'''


def source_text(rev: str | None) -> str:
    """取 `database.py` 的文本：`rev` 为空时读工作区，否则读 git 里的那一版。"""
    if rev is None:
        return (ROOT / SOURCE).read_text(encoding="utf-8")
    out = subprocess.run(
        ["git", "show", f"{rev}:{SOURCE}"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout
    return out.decode("utf-8")


def carve(text: str) -> dict[str, list[str]]:
    """按 AST 把源文件切成「每个类 / 每条 Index 的原始行」以及它上方的注释。"""
    lines = text.splitlines()
    tree = ast.parse(text)

    blocks: dict[str, list[str]] = {}

    def pull(node: ast.AST, key: str) -> None:
        start = node.lineno - 1
        # 紧贴其上的连续注释行也属于这个块（之间不能隔空行，否则是上一段的尾注释）
        while start > 0 and lines[start - 1].strip().startswith("#"):
            start -= 1
        blocks[key] = lines[start:node.end_lineno]

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            pull(node, node.name)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Name) and func.id == "Index":
                name = node.value.args[0].value
                blocks[name] = lines[node.lineno - 1:node.end_lineno]

    missing = [n for _, classes, indexes in GROUPS for n in classes + indexes
               if n not in blocks]
    if missing:
        raise SystemExit(
            f"源文件里找不到 {missing}。\n"
            f"最可能的原因：对**已经搬过一次**的 database.py 重跑本脚本——"
            f"那时类已经不在里面了。请先 `git checkout HEAD -- database.py` 还原。"
        )
    return blocks


def imports_for(body: list[str], local_names: list[str]) -> str:
    """按正文里**真正使用到的名字**生成 import 头。

    碰到没登记的名字直接抛错——宁可脚本在这里失败，也不要生成一个会在导入期
    `NameError` 的模块。将来有人往模型里加字段用了新类型，这里会立刻拦住。
    """
    tree = ast.parse("\n".join(body))
    # 只看 Load——Store 的名字是类的属性名（id / created_at / ...），不是外部引用
    used = {
        n.id for n in ast.walk(tree)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    }
    # local_names：同一模块里定义的类——`Index(..., Transcript.meeting_id, ...)`
    # 那样在本模块内自引用，不需要也不是导入。
    unknown = used - set(_NAME_IMPORTS) - set(dir(builtins)) - set(local_names)
    if unknown:
        raise SystemExit(
            f"模型正文里出现了未登记的全局名字 {sorted(unknown)}——"
            f"请把它们加进 tools/split_models_3_1.py 的 _NAME_IMPORTS。"
        )
    needed = sorted({_NAME_IMPORTS[name] for name in used if name in _NAME_IMPORTS})
    stdlib = [n for n in needed if n.startswith("from datetime")]
    third = [n for n in needed if n.startswith("from sqlalchemy")]
    ours = [n for n in needed if n.startswith("from app.")]
    parts = [p for p in ("\n".join(stdlib), "\n".join(third), "\n".join(ours)) if p]
    return "\n\n".join(parts) + "\n"


def render(groups, blocks) -> dict[str, str]:
    """生成每个模块文件的完整文本。"""
    result = {}
    for module, classes, indexes in groups:
        body: list[str] = []
        for name in classes + indexes:
            if body:
                body.append("")
            body.extend(blocks[name])
        result[module] = (
            HEADER.format(doc=MODULE_DOC[module])
            + imports_for(body, classes)
            + "\n\n"
            + "\n".join(body)
            + "\n"
        )
    return result


def init_text(groups) -> str:
    """`app/models/__init__.py`：把所有模型重新导出，使调用方仍可一处导入。"""
    lines = [
        '"""ORM 模型包（阶段 3.1 从 `database.py` 拆出）。',
        "",
        "**导入本包即完成全部模型的注册**——`Base.metadata` 因此总是完整的。",
        "这一点是必需的：`declarative_base()` 只创建一个 `Base`，而模型类分散在多个",
        "模块里，只有全部导入过，`metadata.tables` 才包含全部表。",
        "`database.py` 与测试的 `create_all()` 都依赖这个性质。",
        '"""',
        "",
        "from app.models.base import Base",
        "",
    ]
    names = []
    for module, classes, _ in groups:
        for name in classes:
            lines.append(f"from app.models.{module} import {name}")
            names.append(name)
    lines.append("")
    lines.append("__all__ = [")
    lines.append('    "Base",')
    for name in sorted(names):
        lines.append(f'    "{name}",')
    lines.append("]")
    return "\n".join(lines) + "\n"


def base_text() -> str:
    return '''"""`declarative_base()` 的唯一实例。

阶段 3.1 之前它住在 `database.py`。放在这里，是因为它是**所有**模型的共同底座，
而 `database.py` 还兼着引擎、会话、迁移三件事（那三件是阶段 3.2 的对象）。

单独成模块还有一个实际好处：`Base.metadata` 是**进程内唯一**的。原先每重新
导入一次 `database`（测试里用 `module_surgery` 干过这事）就会新造一个 metadata，
现在不会了——重新导入 `database` 只是重新绑定到同一个 `Base`。
"""

from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()
'''


def migrate(text: str, apply: bool) -> tuple[dict[str, str], list[str]]:
    """生成全部新文件内容，并逐字节校验，返回 {路径: 文本} 与问题清单。"""
    blocks = carve(text)
    modules = render(GROUPS, blocks)
    files = {f"app/models/{name}.py": body for name, body in modules.items()}
    files["app/models/__init__.py"] = init_text(GROUPS)
    files["app/models/base.py"] = base_text()
    files["database.py"] = new_database(text)

    problems = verify_slices(files, blocks)
    return files, problems


def body_of(text: str) -> list[str]:
    """取一个模型文件在 import 头之后的正文行（忽略空行）。

    以 `from app.models.base import Base` 这一行为界——它是每个模型文件 import 头
    的最后一行，且只出现一次。
    """
    lines = text.splitlines()
    anchor = lines.index("from app.models.base import Base")
    return [ln for ln in lines[anchor + 1:] if ln.strip()]


def expected_body(blocks: dict[str, list[str]], classes, indexes) -> list[str]:
    out: list[str] = []
    for name in classes + indexes:
        out.extend(ln for ln in blocks[name] if ln.strip())
    return out


def verify_slices(files: dict[str, str], blocks: dict[str, list[str]]) -> list[str]:
    """把每个模型文件的正文与源文件的对应行**按位置**逐字比对。

    只比较非空行：空行怎么摆是排版问题，内容才是承诺。而按位置比较是必要的——
    成员检查（`line in written`）会漏掉顺序错乱与重复，那正是搬错块时的典型症状。
    """
    problems: list[str] = []
    for module, classes, indexes in GROUPS:
        got = body_of(files[f"app/models/{module}.py"])
        want = expected_body(blocks, classes, indexes)
        if got == want:
            continue
        for i, (a, b) in enumerate(zip(got, want)):
            if a != b:
                problems.append(
                    f"{module}.py 第 {i} 行与源不一致：\n      源: {b!r}\n      出: {a!r}"
                )
                break
        else:
            problems.append(
                f"{module}.py 行数不符：源 {len(want)} 行，出 {len(got)} 行"
            )
    return problems


def new_database(text: str) -> str:
    """重写 `database.py`：留下引擎/会话/迁移，模型改为从 `app.models` 转出。

    「转出」而不是「删掉」是有意的：这一步要能证明**行为零变化**，最硬的证明
    就是调用方一行都不用改。
    """
    lines = text.splitlines()
    keep_head = [ln for ln in lines[:24] if "declarative_base" not in ln]
    keep_tail = lines[215:]  # _ensure_transcripts_columns + get_db

    names = [n for _, classes, _ in GROUPS for n in classes]
    reexport = [
        "# 阶段 3.1：模型已搬到 `app/models/`。这里原样转出，使 "
        "`from database import User` 这类",
        "# 既有写法继续有效——本步据此可以声称「调用方零改动」。这层转发是**临时的**，",
        "# 阶段 3.2 搬迁本文件时会连同这些调用方一起收拢，届时删除。",
        "from app.models import (",
    ]
    reexport += [f"    {n}," for n in names]
    reexport += [")", "from app.models.base import Base  # noqa: F401  （Base 的公开位置未变）"]

    return "\n".join(keep_head + reexport + [""] + keep_tail) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="真正写盘（默认只预演）")
    ap.add_argument("--verify", action="store_true",
                    help="对照 git HEAD:database.py 校验现有 app/models/ 是否逐字一致")
    args = ap.parse_args()

    if args.verify:
        return do_verify()

    files, problems = migrate(source_text(None), args.write)

    print(f"将生成 {len(files)} 个文件：")
    for path, body in files.items():
        print(f"  {path:<28} {len(body.splitlines()):>4} 行")
    if problems:
        print("\n校验未通过：")
        for p in problems:
            print("  -", p)
        return 1
    print("\n逐块校验：写出的每一行都能在源文件块中逐字节找到 —— 通过。")

    if not args.write:
        print("\n（预演。加 --write 执行。）")
        return 0

    for path, body in files.items():
        target = ROOT / path
        target.parent.mkdir(parents=True, exist_ok=True)
        # 行尾符交给 .gitattributes（eol=lf）统一，这里固定写 LF
        target.write_text(body, encoding="utf-8", newline="\n")
        print("已写出", path)
    return 0


def do_verify() -> int:
    """搬移之后的复核：app/models/ 的内容是否仍与 HEAD 里的 database.py 逐字一致。"""
    text = source_text("HEAD")
    blocks = carve(text)
    problems = []
    total = 0
    for module, classes, indexes in GROUPS:
        path = MODELS_DIR / f"{module}.py"
        if not path.exists():
            problems.append(f"缺少文件 {path.relative_to(ROOT)}")
            continue
        got = body_of(path.read_text(encoding="utf-8"))
        want = expected_body(blocks, classes, indexes)
        total += len(want)
        if got != want:
            problems.append(f"{module}.py 正文与 HEAD:database.py 不一致")
    if problems:
        print("校验未通过：")
        for p in problems:
            print("  -", p)
        return 1
    print(f"校验通过：{len(GROUPS)} 个模块、{total} 行全部与 HEAD:database.py 逐字一致。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
