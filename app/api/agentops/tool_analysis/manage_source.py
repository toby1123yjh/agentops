"""Register an explicit project/tenant binding from the API container."""

import argparse
from uuid import UUID

from sqlalchemy import text

from agentops.common.orm import get_engine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project-id', required=True, type=UUID)
    parser.add_argument('--source-instance-id', required=True, type=UUID)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--tenant-id', type=UUID)
    group.add_argument('--tenant-none', action='store_true')
    parser.add_argument('--name', required=True)
    args = parser.parse_args()
    with get_engine().begin() as conn:
        if not conn.execute(
            text('SELECT id FROM public.projects WHERE id=:id FOR UPDATE'), {'id': args.project_id}
        ).scalar():
            raise ValueError('Project not found')
        tenants = (
            conn.execute(
                text('SELECT tenant_id FROM public.tool_analysis_sources WHERE project_id=:id'),
                {'id': args.project_id},
            )
            .scalars()
            .all()
        )
        if any(tenant != args.tenant_id for tenant in tenants):
            raise ValueError('A project must contain exactly one tenant/environment')
        conn.execute(
            text('''INSERT INTO public.tool_analysis_sources
            (project_id,source_instance_id,source_system,tenant_id,name)
            VALUES(:project,:source,'cestc-claw',:tenant,:name)
            ON CONFLICT(project_id,source_instance_id) DO UPDATE SET name=EXCLUDED.name'''),
            {
                'project': args.project_id,
                'source': args.source_instance_id,
                'tenant': args.tenant_id,
                'name': args.name,
            },
        )


if __name__ == '__main__':
    main()
