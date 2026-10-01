"""不许再教人用 MySQL 时代的数据库栈（2026-10-01 订正）。

本系统早已从 MySQL 迁到 **SQL Server 2022**：`app/` 里没有一处 pymysql，
`requirements.txt` 装的是 `pymssql`（走 TDS）。但仓库里还留着几处**照做就错**的
指令，且都不是史料，而是**活文件**——今天照抄就会得到一个起不来的系统：

  * `deploy/smartclass1.env.example` 给出 `mysql+pymysql://` 的 `DATABASE_URL`；
  * `deploy/deploy.sh` 的兜底依赖清单里装 `pymysql`（正确驱动是 `pymssql`）。

这两处比已经订正的三份文档**更危险**：它们是模板与脚本，读者复制粘贴即中招。

判据：只看代码块，不看正文
---------------------------
最直接的写法是"全仓库搜 pymysql"，但它**当场就会误报**——`README.md` 那句

    > `docs/DEPLOYMENT.md` 是**陈旧史料**：内容是 MySQL/pymysql/3308 时代的……

正是在**指出错误**，而不是发出指令。这与 `test_paths_anchor.py::_path_file_uses`
记录的教训同源：**文本匹配分不清"描述"与"声明"**（`test_readme_routes.py` 因正则
命中 `unrouted.py` 的注释而误红，就是同一个坑的第三次实例）。

分得清的不是更好的正则，而是**结构**：指令写在围栏代码块里，描述写在正文里。
故 `.md` 只扫 ``` / ~~~ 围栏内的内容；脚本与配置模板本身通篇是指令，整份扫。

`pymssql` 不是 `pymysql`
------------------------
同样不能用子串匹配：`pymssql` 里含 `pymysql` 吗？不含；但反过来，裸搜 `pymysql`
会命中……正确驱动名里的 `mssql` 段吗？也不会。真正会出事的写法是搜 `mysql`——
它会同时命中 `pymssql`、`mssql+pymssql://` 这些**正确**的东西。故这里用定长
后顾 `(?<!mss)pymysql` 精确锁定，不搞"命中后再排除"的补丁式豁免。
"""

import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 不扫的目录。`archive/` 是**刻意保留的史料**（含 dev-docs 与 ops-scripts），
# 与 docs/DEPLOYMENT.md 同性质：留档，不是让人照做。
_EXCLUDED_DIRS = frozenset({
    ".git", ".github", "archive", "node_modules", "venv", ".venv", "env",
    "static", "storage", "__pycache__", ".pytest_cache", ".codegraph",
})

# Markdown 走"只看围栏代码块"；其余后缀整份都是指令。
_DOC_SUFFIXES = frozenset({".md", ".markdown"})
_INSTRUCTION_SUFFIXES = frozenset({
    ".md", ".markdown", ".sh", ".bash", ".ps1", ".bat",
    ".example", ".service", ".conf", ".env", ".yml", ".yaml", ".txt",
})

# 围栏：开合标记必须同类同长（``` 配 ```，~~~ 配 ~~~）。
_FENCE = re.compile(r"^([`~]{3,})[^\n]*\n(.*?)^\1[ \t]*$", re.DOTALL | re.MULTILINE)

# 每一条都写成 `(人话标签, 正则)`。正则而非子串——理由见模块 docstring。
_MYSQL_ERA = (
    ("真·pymysql 驱动（本项目用的是 pymssql）", re.compile(r"(?<!mss)pymysql")),
    ("mysqldump（SQL Server 没有这个命令）", re.compile(r"mysqldump")),
    ("mysql+pymysql 等 MySQL 方言 URL", re.compile(r"mysql\+")),
    ("mysql 命令行客户端", re.compile(r"\bmysql\s+-")),
)

# 允许保留错误原文的文件。**每一份都必须仍然真的需要这条豁免**——
# 下面 test_every_allowlisted_file_still_needs_its_exemption 会盯着，
# 免得它退化成一张"看着烦就放行"的名单。
_ALLOWLIST = {
    "docs/DEPLOYMENT.md":
        "陈旧史料：整篇描述 MySQL/3308 时代的部署方式，README 已明写不要照做。"
        "它是**刻意留档的错**，不是待修的活文件；里面那些 `pip install … pymysql` "
        "与 `mysql+pymysql://` 连接串正是它该有的样子。",
}


def _fenced_blocks(text: str) -> list[str]:
    """取出所有围栏代码块的内容（正文与行内 `code` 一律不算）。"""
    return [m.group(2) for m in _FENCE.finditer(text)]


def _chunks_for(path: Path) -> list[str]:
    """该文件里"算作指令"的片段。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in _DOC_SUFFIXES:
        return _fenced_blocks(text)
    return [text]


def _hits_in(chunks: list[str]) -> set[str]:
    return {label for label, rx in _MYSQL_ERA if any(rx.search(c) for c in chunks)}


def _iter_instruction_files() -> list[Path]:
    """遍历全仓库的"指令型"文本文件。

    用 `os.walk` 而不是 `rglob`：后者会**先走进 `venv/` 再过滤**（那里几万个文件），
    一条守卫因此要跑三十秒。`dirnames[:]` 原地剪枝才是正确的写法——被剪掉的目录
    根本不会被访问。
    """
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = sorted(d for d in dirnames if d not in _EXCLUDED_DIRS)
        for name in sorted(filenames):
            if Path(name).suffix.lower() in _INSTRUCTION_SUFFIXES:
                out.append(Path(dirpath) / name)
    return out


def _scan() -> dict[str, set[str]]:
    """返回 `相对路径 -> 命中的标签集合`，**不含**豁免文件。"""
    found: dict[str, set[str]] = {}
    for path in _iter_instruction_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in _ALLOWLIST:
            continue
        hits = _hits_in(_chunks_for(path))
        if hits:
            found[rel] = hits
    return found


def test_no_live_file_tells_you_to_use_the_mysql_stack():
    """活文件里不许出现 MySQL 时代的库、命令或连接串。"""
    offenders = _scan()
    assert not offenders, (
        "以下文件仍在教人用 MySQL 时代的栈，而本系统跑的是 SQL Server 2022：\n"
        + "\n".join(f"  {rel}  -> {sorted(labels)}" for rel, labels in sorted(offenders.items()))
        + "\n\n若某一处确实是**描述**（「某某文档是陈旧的」）而非**指令**，把它写进正文、"
          "别放进代码块；若确实是需要留档的史料，加进 _ALLOWLIST 并写清理由。"
    )


def test_the_scanner_actually_reaches_the_files_it_is_supposed_to_guard():
    """两侧都不能空——不然上面那条断言平凡成立（"空集等于空集"）。

    本仓库在"空输入 == 通过"上栽过不止一次：围栏提取器哪天只返回空列表，
    或后缀集合写错导致一个文件都没扫到，上面的断言都会安静地变绿。
    """
    scanned = {p.relative_to(REPO_ROOT).as_posix() for p in _iter_instruction_files()}
    for must in (
        "deploy/deploy.sh",
        "deploy/smartclass1.env.example",
        "deploy/README.md",
        "README.md",
    ):
        assert must in scanned, f"{must} 没被扫到——后缀集合或排除目录写错了？"

    # 围栏提取器自检：正确栈的指令（sqlcmd）必须能被它读出来。
    with_sqlcmd = [
        rel for rel in sorted(scanned)
        if rel.endswith(".md")
        and any("sqlcmd" in b for b in _fenced_blocks(
            (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")))
    ]
    assert with_sqlcmd, (
        "没有一个 .md 的围栏代码块里读得到 sqlcmd——围栏正则失效了，"
        "于是 test_no_live_file_tells_you_to_use_the_mysql_stack 会平凡通过。"
    )


def test_the_guard_catches_an_offender_and_spares_a_lookalike():
    """守卫自己的正反对照：该抓的抓得住，正确的写法不许误伤。"""
    # 反面：这些今天照抄就会起不来
    assert _hits_in(["DATABASE_URL=mysql+pymysql://u:p@h:3306/db?charset=utf8mb4"])
    assert _hits_in(["mysql -h 127.0.0.1 -u root -p"])
    assert _hits_in(["mysqldump -u root cscl_db > backup.sql"])

    # 正面：正确驱动与正确连接串，一个都不许报
    assert not _hits_in(["DATABASE_URL=mssql+pymssql://sa:pw@db:1433/cscl_db?charset=utf8"])
    assert not _hits_in(["pip install sqlalchemy pymssql opencv-python"])
    assert not _hits_in(["sqlcmd -S host,1433 -U user -P pw -d cscl_db -C -Q \"SELECT 1\""])

    # 代码块才算指令；正文里的"某某文档是陈旧的"不算。
    prose_only = "说明：旧文档里的 `mysqldump` 命令对 SQL Server 无效。\n"
    in_fence = prose_only + "\n```bash\nmysqldump -u root cscl_db > backup.sql\n```\n"
    assert not _hits_in(_fenced_blocks(prose_only)), "正文里的描述不该被判为指令"
    assert _hits_in(_fenced_blocks(in_fence)), "代码块里的指令必须判出来"


def test_every_allowlisted_file_still_needs_its_exemption():
    """豁免名单会自我清算：哪天某份史料改好了，它必须从名单里消失。

    少了这条，`_ALLOWLIST` 会慢慢变成一张"有理由的放行条收集册"——每一条单独看
    都合理，合起来却把整个断言架空了。
    """
    for rel, reason in _ALLOWLIST.items():
        path = REPO_ROOT / rel
        assert path.is_file(), f"_ALLOWLIST 里的 {rel} 已不存在（{reason}），请删掉这一条"
        assert _hits_in(_chunks_for(path)), (
            f"{rel} 已经不需要豁免了（代码块里不再有 MySQL 时代的东西）。\n"
            f"  当初的理由：{reason}\n"
            f"  请把它从 _ALLOWLIST 里删掉——留着只会掩盖将来真正的回归。"
        )


def test_the_systemd_deploy_template_points_at_sql_server():
    """`deploy/smartclass1.env.example` 是唯一一份入库的 systemd 侧配置模板。

    `deploy/README.md` §5 让人 `cp` 它。它得**照抄就能用**，否则读者拿到的报错
    会出现在完全无关的地方：

      * `DATABASE_URL` 必须是 SQL Server 形状 —— pymssql 说的是 TDS 协议，物理上
        连不上 MySQL，写 `mysql+pymysql://` 得到的是一个必然失败的连接串；
      * 五个 `DB_*` 必须在场 —— `/api/register` 与 `/api/login` **不走 ORM**，
        它们 `pymssql.connect(DB_HOST, DB_PORT, ...)`，压根不读 `DATABASE_URL`。
        这份模板原先只有 `DATABASE_URL`，照它部署出来注册与登录是死的。
    """
    path = REPO_ROOT / "deploy" / "smartclass1.env.example"
    assert path.is_file(), "systemd 部署模板不见了"
    text = path.read_text(encoding="utf-8")

    values = dict(re.findall(r"^([A-Z_]+)=(.*)$", text, re.MULTILINE))

    for key in ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME"):
        assert values.get(key), (
            f"模板缺 {key}。`/api/register`、`/api/login` 直连 pymssql，只读 DB_*，"
            f"不读 DATABASE_URL（app/routers/auth.py 文件头）——少了它注册就失败。"
        )

    url = values.get("DATABASE_URL", "")
    assert url.startswith("mssql+pymssql://"), (
        f"模板的 DATABASE_URL 不是 SQL Server 形状：{url}\n"
        f"  正确形式见 .env.dev.example 与 .env.prod.example。"
    )

    # 两处端口必须一致。这个模板里端口写了两次（DB_PORT 与 URL 里那份），
    # 而它们漂移过一次就是"注册连 3433、ORM 连 1433"这种最难查的错。
    assert f":{values['DB_PORT']}/" in url, (
        f"DB_PORT={values['DB_PORT']} 与 DATABASE_URL 里的端口对不上：{url}"
    )
