"""合成数据必须完全确定——两次播种的结果逐字节相同。

背景（实测发现）：
    模型里多数时间列写作 `Column(DateTime, default=datetime.now)`
    （如 `app/models/transcript.py` 的 `Transcript.created_at`、
    `app/models/user.py` 的 `User.created_at`）。若 fixtures 不显式
    赋值，SQLAlchemy 会在 INSERT 时填入**当下的墙钟时间**。

    后果是：基线里的 digest 每次运行都不同。这不是被测路由的缺陷——路由行为
    本来就该随数据变化；缺陷在 fixtures 一侧，是它没有把数据钉死。

因此这里不再依赖"人工核对列清单"，而是用两条断言从结构上封死：
    1. 播种结果中不得出现任何贴近当前时刻的时间值
       （今后新增模型/新增时间列时，若忘记赋值，测试会直接失败）
    2. 两次独立播种的结果必须逐行一致
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

# 合成数据的时间基准远早于运行时刻，用一个宽松阈值即可可靠区分
WALL_CLOCK_PROXIMITY = timedelta(days=1)


@pytest.fixture
def fresh_session(tmp_path):
    """在一个全新的空库上建表并返回会话（与全局测试库相互独立）。"""
    from app.models import Base

    engine = create_engine(f"sqlite:///{(tmp_path / 'probe.db').as_posix()}")
    Base.metadata.create_all(engine)
    session = Session(bind=engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def second_session(tmp_path):
    """第二个独立空库，用于对比两次播种。"""
    from app.models import Base

    engine = create_engine(f"sqlite:///{(tmp_path / 'probe2.db').as_posix()}")
    Base.metadata.create_all(engine)
    session = Session(bind=engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _mapped_classes() -> dict:
    """{表名: ORM 类}——经 mapper 解析，不依赖类名与表名是否相同。"""
    from app.models import Base

    return {mapper.class_.__table__.name: mapper.class_ for mapper in Base.registry.mappers}


def _iter_scalar_cells(session):
    """遍历库中所有 (表名.列名, 单元格取值)。"""
    for table, cls in sorted(_mapped_classes().items()):
        for row in session.query(cls).all():
            for col in inspect(cls).mapper.columns:
                yield f"{table}.{col.key}", getattr(row, col.key)


def _dump_all_rows(session) -> dict:
    """把整个库倒成 {表名: [行字典, ...]}，行按主键排序。"""
    dump = {}
    for table, cls in sorted(_mapped_classes().items()):
        pk = list(inspect(cls).mapper.primary_key)[0].key
        columns = [c.key for c in inspect(cls).mapper.columns]
        rows = [
            {key: repr(getattr(row, key)) for key in columns}
            for row in session.query(cls).all()
        ]
        rows.sort(key=lambda r: r[pk])
        dump[table] = rows
    return dump


def test_no_wall_clock_values_in_seed(fresh_session):
    """播种结果里不得有任何"刚刚生成"的时间值。

    漏设某个 `default=datetime.now` 的列时，该列会在 INSERT 时被填成当下，
    无论那列是否被路由读取——这条断言在**播种阶段**就把它拦下。
    """
    from fixtures import seed_all

    seed_all(fresh_session)
    fresh_session.flush()

    now = datetime.now()
    offenders = [
        f"{where}: {value.isoformat()}"
        for where, value in _iter_scalar_cells(fresh_session)
        if isinstance(value, datetime) and abs(now - value) < WALL_CLOCK_PROXIMITY
    ]

    assert not offenders, (
        "以下时间值来自 INSERT 时的墙钟时间（datetime.now），"
        "会导致基线 digest 每次运行都变化。请在 fixtures.py 中显式赋值：\n  "
        + "\n  ".join(sorted(offenders))
    )


def test_meeting_timestamps_are_distinct(fresh_session):
    """几场课堂的 `created_at` 必须互不相同。

    为什么单拎这一列
    ----------------
    `/api/class-history/{user_id}`（`server.py:4838`）结尾用

        history.sort(key=lambda x: x["created_at"], reverse=True)   # :4902

    排序。若两场课堂的 `created_at` 相同，这个 key 就分不出先后，稳定排序于是
    **保留列表原序**；而原序来自 `server.py:4854`：

        all_meetings = list(set(user_meetings + created_meetings))

    `set` 对 ORM 实例按 `id()` 散列，迭代顺序取决于对象的内存地址——**每次进程
    启动都可能不同**。两者叠加，响应里两条记录的先后就变成一个未定义值。

    实测：两个进程各跑一次，约各占一半
        [[2, ...], [1, ...]]  与  [[1, ...], [2, ...]]
    在整套测试中约每 5 次复现 1 次，表现为 `/api/class-history/2` 的 digest 变化
    而 length 与 shape 完全一致——只看断言信息极易误判为"内容变了"。

    真实数据里两场课堂不会同时同分同秒创建，这个平局是**合成数据自己造的**。
    所以修在 fixtures 一侧，不动 `server.py`。
    """
    from fixtures import seed_all

    seed_all(fresh_session)
    fresh_session.flush()

    from app.models import Meeting

    stamps = [(m.id, m.created_at) for m in fresh_session.query(Meeting).all()]
    assert len(stamps) > 1, "只有一场课堂时这条守卫没有意义"

    seen = {}
    for meeting_id, created_at in stamps:
        seen.setdefault(created_at, []).append(meeting_id)

    ties = {k: v for k, v in seen.items() if len(v) > 1}
    assert not ties, (
        "以下课堂的 created_at 相同，会让 /api/class-history 的返回顺序"
        "变成未定义值（server.py:4854 的 set 迭代序 × :4902 的稳定排序）：\n  "
        + "\n  ".join(f"{k.isoformat()} → meeting_id {sorted(v)}" for k, v in ties.items())
    )


def test_two_seeds_are_byte_identical(fresh_session, second_session):
    """两次独立播种的结果必须逐行一致。

    比上一条更强：上一条只盯时间，这一条覆盖**任何**不确定性来源
    （随机 ID、自增顺序、随机化的默认值等）。
    """
    from fixtures import seed_all

    seed_all(fresh_session)
    fresh_session.flush()
    first = _dump_all_rows(fresh_session)

    seed_all(second_session)
    second_session.flush()
    second = _dump_all_rows(second_session)

    assert set(first) == set(second), "两次播种涉及的表集合不同"

    diffs = {
        table: {
            "仅在第一次": [r for r in first[table] if r not in second[table]][:3],
            "仅在第二次": [r for r in second[table] if r not in first[table]][:3],
        }
        for table in first
        if first[table] != second[table]
    }
    assert not diffs, "两次播种结果不一致：\n" + repr(diffs)
