from __future__ import annotations

import gc
from types import SimpleNamespace

from beanie import PydanticObjectId

from ege_notifier.services.results import ResultsService


def _service() -> ResultsService:
    # Конструктор ничего не делает с БД — достаточно заглушек.
    stub = SimpleNamespace()
    return ResultsService(stub, stub, stub)  # ty: ignore[invalid-argument-type]


def test_lock_for_returns_same_lock_for_same_id():
    svc = _service()
    oid = PydanticObjectId()
    assert svc._lock_for(oid) is svc._lock_for(oid)


def test_locks_do_not_accumulate():
    # WeakValueDictionary освобождает запись, как только блокировку никто не держит
    # — иначе по одному Lock на каждого когда-либо проверенного ученика копилось бы.
    svc = _service()
    oid = PydanticObjectId()
    lock = svc._lock_for(oid)
    assert oid in svc._locks
    del lock
    gc.collect()
    assert oid not in svc._locks
