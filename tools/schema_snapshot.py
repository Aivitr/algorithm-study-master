"""给 `Base.metadata` 拍一张完整的结构快照，用于比对「搬迁前后是否同一套表」。

阶段 3.1 的承诺是「调用方零改动、行为零变化」。测试全绿只是弱证据——测试只覆盖
只读路由，模型定义错了（字段类型、可空性、默认值、外键、索引）多半不会让任何
一条测试变红。

所以这里直接把 `Base.metadata` 逐表逐列**序列化**出来，在「HEAD 的代码」与
「搬迁后的代码」两个 checkout 上各跑一次，再比对两份 JSON。这是针对模型这一层
能做到的最直接的等价证明。

用法
----
    快照.py 必须在**被快照的那个 checkout 的根目录下**运行（脚本会把 cwd 加进
    sys.path），且要用本仓库的 venv——它才是装着正确 SQLAlchemy 版本的解释器。

    # 1. 把 HEAD 导出到临时目录
    mkdir -p /tmp/orighead && git archive HEAD | tar -x -C /tmp/orighead

    # 2. 两边各拍一张
    PY=./venv/Scripts/python.exe
    (cd /tmp/orighead            && $PY $PWD/tools/schema_snapshot.py > /tmp/head.json)
    (cd <当前 checkout 根>        && $PY tools/schema_snapshot.py      > /tmp/new.json)

    # 3. 比对。**务必先确认两份都非空**——空文件 diff 也会"通过"，
    #    那正是本仓库反复出现的静默失效。
    diff /tmp/head.json /tmp/new.json

阶段 3.1 的实测结果：1781 行、逐字节相同。
"""

import json
import os
import sys
from pathlib import Path

# 本脚本用绝对路径被调用，而 `config` / `database` 在**当前工作目录**下。
# 脚本所在目录会被 Python 自动放进 sys.path[0]，cwd 不会——必须显式加，
# 否则导入直接失败（而失败若被当成"两边一样"，就是假阳性）。
sys.path.insert(0, os.getcwd())


def _import_compat(name: str):
    """按两种布局导入：`app.core.X`（搬迁后）优先，退回根级 `X`（搬迁前）。

    本工具要能同时跑在**两个 checkout** 上——HEAD 那棵树里 `config.py` 还在根
    目录，当前树里它已在 `app/core/`。写死任一种都会让另一边失败，而失败若被
    当成"两边一致"，比对就成了假阳性。

    用**文件是否存在**判断，而不是 try/except ImportError：后者会把模块内部
    真实的导入错误也吞掉、悄悄退回另一种布局，那就又是一种静默失效。
    """
    root = Path(os.getcwd())
    for module_name, rel in ((f"app.core.{name}", f"app/core/{name}.py"), (name, f"{name}.py")):
        if (root / rel).is_file():
            import importlib

            return importlib.import_module(module_name)
    raise SystemExit(f"两种布局下都找不到 {name}（cwd={root}）")


# 必须在导入 database 之前设定：database.py 在导入期就用它建 engine。
# 指向 sqlite 同时意味着 _ensure_transcripts_columns() 找不到 transcripts 表、
# 直接 return——不会对任何真实库发 DDL。
os.environ["DATABASE_URL"] = "sqlite:///./__schema_dump__.db"

config = _import_compat("config")  # 先加载 .env，与原逻辑一致
database = _import_compat("database")

def _default_repr(default):
    if default is None:
        return None
    arg = default.arg
    if callable(arg):
        # datetime.now → "callable:datetime.now"；list → "callable:list"
        return f"callable:{getattr(arg, '__module__', '')}.{getattr(arg, '__qualname__', arg)}"
    return repr(arg)


metadata = database.Base.metadata

tables = []
for name in sorted(metadata.tables):
    table = metadata.tables[name]
    tables.append({
        "table": name,
        "columns": [
            {
                "name": col.name,
                "type": str(col.type),
                "nullable": bool(col.nullable),
                # default 可能是标量，也可能是 datetime.now / list / dict 这类可调用。
                # 可调用**不能**直接 str()——那会带上内存地址，两次运行必然不同，
                # 于是比对永远报差异，等于没有比对。取 __name__ 才是稳定的。
                "default": _default_repr(col.default),
                "primary_key": bool(col.primary_key),
                "foreign_keys": sorted(
                    f"{fk.column.table.name}.{fk.column.name}" for fk in col.foreign_keys
                ),
                "index": bool(col.index),
                "unique": bool(col.unique),
            }
            for col in table.columns
        ],
        "indexes": sorted(
            ({"name": idx.name, "columns": [c.name for c in idx.columns]}
             for idx in table.indexes),
            key=lambda d: (d["name"] or "", d["columns"]),
        ),
        "foreign_key_targets": sorted(
            f"{fk.parent.name}->{fk.column.table.name}.{fk.column.name}"
            for fk in table.foreign_keys
        ),
    })

# 同时记录各模型的公开属性，确认 `relationship` 等描述符仍在
descriptors = {}
for attr in ("User", "Meeting", "Transcript", "EmotionLog", "KnowledgeGraph",
             "GraphNode", "GraphEdge", "LearningReport", "Exercise", "StudentAnswer",
             "MentalHealthAssessment", "ViewpointVote", "MemberConnection",
             "ReportTemplate", "AIInsight"):
    cls = getattr(database, attr, None)
    descriptors[attr] = None if cls is None else sorted(
        k for k in vars(cls) if not k.startswith("_")
    )

print(json.dumps({"tables": tables, "descriptors": descriptors},
                 ensure_ascii=False, indent=1, sort_keys=True))
