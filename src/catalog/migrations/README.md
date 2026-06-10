# `catalog` migrations

**Status: deferred.** Alembic is wired up here as a placeholder for when
the catalog goes to production, but there are no revisions yet.
`catalog.db.init_schema(engine)` currently calls
`Base.metadata.create_all(engine)` directly — fast, simple, and fine while
the schema is still in flux and no production data exists.

When the catalog ships:

1. Switch `init_schema` back to `alembic upgrade head` (the prior shape of
   that function is in git history).
2. Generate the baseline revision against an empty DB:
   ```bash
   pixi run -e catalog migrate-revision -- "baseline"
   ```
3. On existing prod DBs, `alembic stamp head` to mark them at the baseline
   without re-creating tables.
4. From then on, every ORM change ships as a new revision: edit
   `catalog/orm.py`, run `pixi run -e catalog migrate-revision -- "what changed"`,
   review the diff, commit, and apply with `pixi run -e catalog migrate`.

The `alembic` Python dep, the pixi tasks (`migrate`, `migrate-revision`),
the `alembic.ini`, and the `env.py` are kept so step 1 is a one-line change
when the time comes. The ORM↔Pydantic drift check
(`tests/catalog/test_orm_drift.py`) is what's keeping us honest in
the meantime.

[alembic]: https://alembic.sqlalchemy.org/

## SQLite caveats (for when migrations come back)

- **`render_as_batch=True` is mandatory** for `ALTER TABLE`. SQLite's
  in-place ALTER TABLE is far too narrow (no DROP COLUMN, no ALTER COLUMN
  type), so Alembic's batch mode rebuilds the whole table. That rebuild
  drops any **manual indexes, triggers, and PRAGMAs** not represented in
  the ORM.
- **Autogenerate misses some changes.** It does NOT detect: CHECK
  constraint changes, server-side default changes (sometimes), certain
  composite / functional index changes, or string-length changes on
  SQLite where everything is TEXT.
- **Review every revision diff before committing.** The `versions/`
  files are normal Python; treat them as code.
