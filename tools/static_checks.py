"""静态检查小工具（被测试直接导入，不参与运行时）。

目前只有一个：`free_globals()` —— 找出模块里**被当作全局名使用、却在本模块
既没有定义也没有导入**的名字。

为什么需要它
------------
把一个函数从 A 模块搬到 B 模块时，函数体一个字都不用改就可能坏掉：它引用的
某个名字原来是 **A 的模块级全局**（`import re`、`from datetime import datetime`
之类），搬到 B 之后 B 里没人提供它。后果是**运行到那条分支才 NameError**，
而外层若恰好有 `try/except Exception`（本仓库的路由处理器普遍如此），它会被
吞成 `{"status":"error"}` 的**200 响应**——测试若只覆盖"别的"路由，就一路全绿。

这类写法不是"导入失败"，而是静默的运行时错。AST 层面的 import 清单看不出来
（有的是"新模块缺一行"，有的是"看起来有"——函数体内的局部导入对别的函数不可见），
所以改用 `symtable`——它就是编译器自己做作用域分析用的那套，语义与运行时一致。

判据
----
收集**所有子作用域**里形如"全局查找"（`is_global()`）的被引用名字，减去
模块作用域绑定过的名字、内置名字、以及导入系统隐式提供的名字。剩下就是
运行到就会 NameError 的名字。空集才算通过。
"""

import builtins
import symtable
from ast import ImportFrom, Import, walk, parse

# 导入系统隐式提供的模块级名字（不入 symtable 的绑定表，但运行时一定存在）。
IMPLICIT_MODULE_GLOBALS = frozenset(
    {
        "__file__",
        "__name__",
        "__doc__",
        "__package__",
        "__loader__",
        "__spec__",
        "__builtins__",
        "__path__",
        "__debug__",
    }
)

_BUILTIN_NAMES = frozenset(dir(builtins))


def has_star_import(source: str) -> bool:
    """模块里是否有 `from X import *`。

    星号导入绑定的名字**静态不可知**，因此这类模块不能据此判定（调用方应跳过）。
    """
    for node in walk(parse(source)):
        if isinstance(node, ImportFrom):
            if any(alias.name == "*" for alias in node.names):
                return True
        elif isinstance(node, Import):
            if any(alias.name == "*" for alias in node.names):
                return True
    return False


def free_globals(source: str, filename: str = "<unknown>") -> set[str]:
    """返回在模块内被全局查找、却没有任何模块级绑定的名字。

    空集 = 这个模块里不存在"未定义全局名"这类潜在 NameError。
    """
    table = symtable.symtable(source, filename, "exec")

    bound: set[str] = set()
    for symbol in table.get_symbols():
        name = symbol.get_name()
        if (
            symbol.is_assigned()
            or symbol.is_imported()
            or symbol.is_namespace()
            or symbol.is_parameter()
        ):
            bound.add(name)

    looked_up: set[str] = set()

    def walk_tables(scope: symtable.SymbolTable) -> None:
        for symbol in scope.get_symbols():
            # 只看"全局查找"：绑定在外层函数作用域里的 free 变量不算，它由闭包负责。
            if symbol.is_referenced() and symbol.is_global():
                looked_up.add(symbol.get_name())
        for child in scope.get_children():
            walk_tables(child)

    walk_tables(table)

    return looked_up - bound - _BUILTIN_NAMES - IMPLICIT_MODULE_GLOBALS
