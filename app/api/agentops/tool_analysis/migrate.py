"""Incremental migration; independent of the existing-user bootstrap early return."""

import hashlib
from pathlib import Path

from sqlalchemy import text

from agentops.common.orm import get_engine


def migrate():
    source = Path(__file__).with_name('001.sql').read_text(encoding='utf-8')
    checksum = hashlib.sha256(source.encode()).hexdigest()
    with get_engine().begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(1734829102)'))
        conn.execute(
            text('''CREATE TABLE IF NOT EXISTS public.tool_analysis_schema_versions (
            version integer PRIMARY KEY, checksum char(64) NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT now())''')
        )
        old = conn.execute(
            text('SELECT checksum FROM public.tool_analysis_schema_versions WHERE version=1')
        ).scalar()
        if old:
            if old != checksum:
                raise RuntimeError('Tool analysis migration checksum mismatch')
            return
        for statement in source.split(';'):
            if statement.strip():
                conn.execute(text(statement))
        conn.execute(
            text('INSERT INTO public.tool_analysis_schema_versions(version,checksum) VALUES(1,:checksum)'),
            {'checksum': checksum},
        )


if __name__ == '__main__':
    migrate()
