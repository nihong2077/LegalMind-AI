"""T0.9 LangGraph Checkpointer 单测（fake pool/saver，不依赖真实 PG）。"""
import pytest

import sys
sys.path.insert(0, ".")

from app.core import checkpoint as cp


# ---------- fakes ----------

class FakeSaver:
    setup_calls = 0

    def __init__(self, conn, **kw):
        self.conn = conn

    async def setup(self):
        FakeSaver.setup_calls += 1


class _FakePool:
    def __init__(self, dsn, *, open=False, min_size=1, max_size=10, kwargs=None,
                 setup_raises=None):
        self.dsn = dsn
        self.opened = False
        self.max_size = max_size
        self.conn_kwargs = kwargs or {}
        self.closed = False
        self._setup_raises = setup_raises

    async def open(self, wait=True):
        self.opened = True

    async def close(self):
        self.closed = True


def _patch(monkeypatch, *, saver_setup_raises=None, pool=None):
    created_pools = []

    def pool_factory(dsn, **kwargs):
        p = pool or _FakePool(dsn, **kwargs)
        created_pools.append(p)
        return p

    def saver_factory(conn, **kw):
        s = FakeSaver(conn)
        if saver_setup_raises:
            async def boom():
                FakeSaver.setup_calls += 1
                raise saver_setup_raises
            s.setup = boom
        return s

    monkeypatch.setattr(cp, "AsyncConnectionPool", pool_factory)
    monkeypatch.setattr(cp, "AsyncPostgresSaver", saver_factory)
    return created_pools


@pytest.fixture(autouse=True)
def _reset_globals():
    cp._pool = None
    cp._checkpointer = None
    FakeSaver.setup_calls = 0
    yield
    cp._pool = None
    cp._checkpointer = None


pytestmark = pytest.mark.asyncio


# ---------- DSN 转换 ----------

@pytest.mark.parametrize("raw,expected", [
    ("postgresql+asyncpg://u:p@h:5432/db", "postgresql://u:p@h:5432/db"),
    ("postgresql+psycopg2://u@h/db", "postgresql://u@h/db"),
    ("postgresql://u@h/db", "postgresql://u@h/db"),
])
def test_dsn_conversion(raw, expected):
    assert cp.to_psycopg_dsn(raw) == expected


# ---------- 初始化 ----------

async def test_init_creates_pool_with_required_kwargs_and_calls_setup(monkeypatch):
    from psycopg.rows import dict_row
    pools = _patch(monkeypatch)

    saver = await cp.init_checkpointer(
        dsn="postgresql+asyncpg://u:p@h:5432/legalmind_app", pool_max_size=4
    )
    pool = pools[0]

    assert pool.opened is True
    assert pool.max_size == 4
    assert pool.dsn == "postgresql://u:p@h:5432/legalmind_app"
    assert pool.conn_kwargs["autocommit"] is True
    assert pool.conn_kwargs["prepare_threshold"] == 0
    assert pool.conn_kwargs["row_factory"] is dict_row
    assert FakeSaver.setup_calls == 1
    assert isinstance(saver, FakeSaver)
    assert cp.get_checkpointer() is saver


async def test_init_idempotent_single_pool(monkeypatch):
    pools = _patch(monkeypatch)
    s1 = await cp.init_checkpointer(dsn="postgresql://u@h/db")
    s2 = await cp.init_checkpointer(dsn="postgresql://u@h/db")
    assert s1 is s2
    assert len(pools) == 1
    assert FakeSaver.setup_calls == 1


async def test_setup_failure_closes_pool_and_resets_globals(monkeypatch):
    pools = _patch(monkeypatch, saver_setup_raises=RuntimeError("DDL denied"))

    with pytest.raises(RuntimeError, match="DDL denied"):
        await cp.init_checkpointer(dsn="postgresql://u@h/db")

    assert pools[0].closed is True          # 失败时回收连接池
    assert cp.get_checkpointer() is None


async def test_close_without_init_is_safe():
    await cp.close_checkpointer()
    assert cp.get_checkpointer() is None


async def test_close_after_init(monkeypatch):
    pools = _patch(monkeypatch)
    await cp.init_checkpointer(dsn="postgresql://u@h/db")
    await cp.close_checkpointer()
    assert pools[0].closed is True
    assert cp.get_checkpointer() is None
    # 再次关闭幂等不炸
    await cp.close_checkpointer()
