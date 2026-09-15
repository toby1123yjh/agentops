"""Initialize only the dedicated local databases, reusing upstream ClickHouse DDL."""

from pathlib import Path
import re

from agentops.local_auth import bootstrap
from agentops.common.local_mode import validate_local_settings
from agentops.api.db.clickhouse_client import get_clickhouse


def statements(source: str) -> list[str]:
    # Repository migrations contain simple SQL statements (no procedural SQL).
    return [part.strip() for part in re.sub(r"(?m)^--.*$", "", source).split(';') if part.strip()]


def initialize_clickhouse() -> None:
    validate_local_settings()
    root = Path(__file__).resolve().parents[1] / 'clickhouse' / 'migrations'
    if not root.exists():
        root = Path(__file__).resolve().parents[2] / 'clickhouse' / 'migrations'
    seed = root / '0004_seed_model_costs_full.sql'
    if not seed.is_file():
        raise RuntimeError('Local ClickHouse migrations are missing')
    client = get_clickhouse()
    try:
        existing = {row[0] for row in client.query("SHOW TABLES FROM otel_2").result_rows}
        if existing and 'local_schema_versions' not in existing:
            raise RuntimeError("Local ClickHouse initialization requires an empty dedicated database")
        client.command("CREATE TABLE IF NOT EXISTS otel_2.local_schema_versions (version UInt32) ENGINE=MergeTree ORDER BY version")
        if client.query("SELECT count() FROM otel_2.local_schema_versions WHERE version=1").result_rows[0][0]:
            return
        for migration in sorted(root.glob('*.sql')):
            source = migration.read_text(encoding='utf-8')
            # Local dictionaries read the local table without cloud/server login configuration.
            source = source.replace("HOST 'localhost' PORT 9000 USER 'default' DB", "DB")
            for statement in statements(source):
                statement = re.sub(r'^CREATE (TABLE|MATERIALIZED VIEW) (?!IF NOT EXISTS)', r'CREATE \1 IF NOT EXISTS ', statement)
                if migration.name.startswith(('0003_', '0004_')):
                    # Cost seeds are data, not accumulated measurements; retries must not duplicate them.
                    continue
                client.command(statement)
        client.command('TRUNCATE TABLE otel_2.model_costs_source')
        for statement in statements(seed.read_text(encoding='utf-8')):
            client.command(statement)
        client.command('SYSTEM RELOAD DICTIONARY otel_2.model_costs_dict')
        client.command('INSERT INTO otel_2.local_schema_versions VALUES (1)')
    finally:
        client.close()


if __name__ == '__main__':
    bootstrap()
    initialize_clickhouse()
    print('Local PostgreSQL and ClickHouse initialized; existing user credentials are unchanged.')
