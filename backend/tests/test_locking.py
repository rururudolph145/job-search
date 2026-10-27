from app.ingestion.locking import LOCK_KEY, ingestion_lock


class FakeDialect:
    name = "sqlite"


class FakeBind:
    dialect = FakeDialect()


class FakeSession:
    def get_bind(self) -> FakeBind:
        return FakeBind()


def test_lock_yields_true_on_sqlite() -> None:
    with ingestion_lock(FakeSession()) as held:  # type: ignore[arg-type]
        assert held is True


def test_lock_key_is_fixed() -> None:
    assert LOCK_KEY == 0x4A53_0006


class _Result:
    def __init__(self, value: bool) -> None:
        self._value = value

    def scalar(self) -> bool:
        return self._value


class FakePostgresSession:
    """Records every statement so the acquire/release protocol is observable."""

    def __init__(self, acquire: bool) -> None:
        self._acquire = acquire
        self.statements: list[str] = []

    def get_bind(self) -> FakeBind:
        bind = FakeBind()
        bind.dialect.name = "postgresql"  # type: ignore[misc]
        return bind

    def execute(self, statement: object, params: object = None) -> _Result:
        sql = str(getattr(statement, "text", statement))
        self.statements.append(sql)
        if "pg_try_advisory_lock" in sql:
            return _Result(self._acquire)
        return _Result(True)


def test_postgres_unlocks_only_when_acquired() -> None:
    acquired = FakePostgresSession(acquire=True)
    with ingestion_lock(acquired) as held:  # type: ignore[arg-type]
        assert held is True
    assert any("pg_try_advisory_lock" in s for s in acquired.statements)
    assert any("pg_advisory_unlock" in s for s in acquired.statements)


def test_postgres_does_not_unlock_a_lock_it_never_took() -> None:
    denied = FakePostgresSession(acquire=False)
    with ingestion_lock(denied) as held:  # type: ignore[arg-type]
        assert held is False
    assert any("pg_try_advisory_lock" in s for s in denied.statements)
    assert not any("pg_advisory_unlock" in s for s in denied.statements)


def test_lock_releases_on_exception_inside_block() -> None:
    acquired = FakePostgresSession(acquire=True)
    try:
        with ingestion_lock(acquired):  # type: ignore[arg-type]
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert any("pg_advisory_unlock" in s for s in acquired.statements)
