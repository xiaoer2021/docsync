'init schema'

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '47ebbbdc2e94'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:

    op.create_table('dd_action',
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('config', sa.JSON(), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('remark', sa.Text(), nullable=True),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('dd_app',
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('app_key', sa.String(length=128), nullable=False),
    sa.Column('app_secret_enc', sa.Text(), nullable=False),
    sa.Column('default_operator_union_id', sa.String(length=128), nullable=True),
    sa.Column('default_operator_name', sa.String(length=64), nullable=True),
    sa.Column('token_expires_at', sa.DateTime(), nullable=True),
    sa.Column('last_token_at', sa.DateTime(), nullable=True),
    sa.Column('last_token_error', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('remark', sa.Text(), nullable=True),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('dd_contact',
    sa.Column('app_id', sa.Integer(), nullable=False),
    sa.Column('union_id', sa.String(length=128), nullable=False),
    sa.Column('user_id', sa.String(length=128), nullable=True),
    sa.Column('name', sa.String(length=64), nullable=True),
    sa.Column('mobile', sa.String(length=32), nullable=True),
    sa.Column('dept', sa.String(length=255), nullable=True),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('raw', sa.JSON(), nullable=True),
    sa.Column('synced_at', sa.DateTime(), nullable=True),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('app_id', 'union_id', name='uq_dd_contact_app_union')
    )
    op.create_table('dd_datasource',
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('db_type', sa.String(length=16), nullable=False),
    sa.Column('host', sa.String(length=255), nullable=False),
    sa.Column('port', sa.Integer(), nullable=False),
    sa.Column('database', sa.String(length=128), nullable=False),
    sa.Column('username', sa.String(length=128), nullable=False),
    sa.Column('password_enc', sa.Text(), nullable=False),
    sa.Column('extra', sa.JSON(), nullable=True),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('remark', sa.Text(), nullable=True),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('dd_doc_group',
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('remark', sa.Text(), nullable=True),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('dd_template',
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=True),
    sa.Column('remark', sa.Text(), nullable=True),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('sys_audit',
    sa.Column('user_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('username', sa.String(length=64), nullable=True),
    sa.Column('action', sa.String(length=32), nullable=False),
    sa.Column('target_type', sa.String(length=32), nullable=False),
    sa.Column('target_id', sa.String(length=64), nullable=True),
    sa.Column('detail', sa.JSON(), nullable=True),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('sys_audit', schema=None) as batch_op:
        batch_op.create_index('ix_sys_audit_created', ['created_at'], unique=False)

    op.create_table('sys_user',
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('display_name', sa.String(length=64), nullable=True),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('remark', sa.Text(), nullable=True),
    sa.Column('last_login_at', sa.DateTime(), nullable=True),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('username')
    )
    op.create_table('dd_doc',
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('doc_type', sa.String(length=16), nullable=False),
    sa.Column('node_id', sa.String(length=128), nullable=False),
    sa.Column('source_url', sa.String(length=1024), nullable=True),
    sa.Column('app_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('operator_union_id', sa.String(length=128), nullable=True),
    sa.Column('group_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('remark', sa.Text(), nullable=True),
    sa.Column('watch_enabled', sa.Boolean(), nullable=False),
    sa.Column('watch_cron', sa.String(length=64), nullable=True),
    sa.Column('next_watch_at', sa.DateTime(), nullable=True),
    sa.Column('last_probe_at', sa.DateTime(), nullable=True),
    sa.Column('last_probe_ok', sa.Boolean(), nullable=True),
    sa.Column('last_probe_error', sa.Text(), nullable=True),
    sa.Column('structure_hash', sa.String(length=64), nullable=True),
    sa.Column('structure_drift', sa.Text(), nullable=True),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['app_id'], ['dd_app.id'], ),
    sa.ForeignKeyConstraint(['group_id'], ['dd_doc_group.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('app_id', 'node_id', name='uq_dd_doc_app_node')
    )
    with op.batch_alter_table('dd_doc', schema=None) as batch_op:
        batch_op.create_index('ix_dd_doc_group', ['group_id'], unique=False)

    op.create_table('dd_doc_sheet',
    sa.Column('doc_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('sheet_id', sa.String(length=128), nullable=False),
    sa.Column('sheet_name', sa.String(length=255), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('field_count', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(), nullable=True),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['doc_id'], ['dd_doc.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('doc_id', 'sheet_id', name='uq_dd_doc_sheet')
    )
    with op.batch_alter_table('dd_doc_sheet', schema=None) as batch_op:
        batch_op.create_index('ix_dd_doc_sheet_doc', ['doc_id'], unique=False)

    op.create_table('dd_task',
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('doc_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('sheet_id', sa.String(length=128), nullable=False),
    sa.Column('sheet_name', sa.String(length=255), nullable=True),
    sa.Column('engine', sa.String(length=16), nullable=False),
    sa.Column('template_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('group_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('source_config', sa.JSON(), nullable=True),
    sa.Column('columns', sa.JSON(), nullable=True),
    sa.Column('dedupe', sa.JSON(), nullable=True),
    sa.Column('target', sa.JSON(), nullable=True),
    sa.Column('post_actions', sa.JSON(), nullable=True),
    sa.Column('schedule', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('remark', sa.Text(), nullable=True),
    sa.Column('last_run_at', sa.DateTime(), nullable=True),
    sa.Column('last_run_status', sa.String(length=16), nullable=True),
    sa.Column('last_success_at', sa.DateTime(), nullable=True),
    sa.Column('next_run_at', sa.DateTime(), nullable=True),
    sa.Column('last_summary', sa.JSON(), nullable=True),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['doc_id'], ['dd_doc.id'], ),
    sa.ForeignKeyConstraint(['group_id'], ['dd_doc_group.id'], ),
    sa.ForeignKeyConstraint(['template_id'], ['dd_template.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code', name='uq_dd_task_code'),
    sa.UniqueConstraint('doc_id', 'sheet_id', name='uq_dd_task_doc_sheet')
    )
    with op.batch_alter_table('dd_task', schema=None) as batch_op:
        batch_op.create_index('ix_dd_task_doc', ['doc_id'], unique=False)
        batch_op.create_index('ix_dd_task_next_run', ['next_run_at', 'status'], unique=False)

    op.create_table('dd_run',
    sa.Column('task_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('trigger_type', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('queued_at', sa.DateTime(), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('rows_read', sa.Integer(), nullable=False),
    sa.Column('rows_written', sa.Integer(), nullable=False),
    sa.Column('rows_inserted', sa.Integer(), nullable=False),
    sa.Column('rows_updated', sa.Integer(), nullable=False),
    sa.Column('rows_unchanged', sa.Integer(), nullable=False),
    sa.Column('rows_failed', sa.Integer(), nullable=False),
    sa.Column('batches', sa.Integer(), nullable=False),
    sa.Column('dry_run', sa.Boolean(), nullable=False),
    sa.Column('row_limit', sa.Integer(), nullable=True),
    sa.Column('log_path', sa.String(length=512), nullable=True),
    sa.Column('log_bytes', sa.Integer(), nullable=False),
    sa.Column('triggered_by', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('stats', sa.JSON(), nullable=True),
    sa.Column('error_type', sa.String(length=64), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('cancel_requested', sa.Boolean(), nullable=False),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['task_id'], ['dd_task.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('dd_run', schema=None) as batch_op:
        batch_op.create_index('ix_dd_run_status', ['status'], unique=False)
        batch_op.create_index('ix_dd_run_task_started', ['task_id', 'started_at'], unique=False)

    op.create_table('dd_run_action',
    sa.Column('run_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('action_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('action_name', sa.String(length=128), nullable=True),
    sa.Column('kind', sa.String(length=32), nullable=True),
    sa.Column('trigger_on', sa.String(length=16), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('http_status', sa.Integer(), nullable=True),
    sa.Column('request_digest', sa.Text(), nullable=True),
    sa.Column('response_digest', sa.Text(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['dd_run.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('dd_run_action', schema=None) as batch_op:
        batch_op.create_index('ix_dd_run_action_run', ['run_id'], unique=False)

    op.create_table('dd_run_issue',
    sa.Column('run_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('row_no', sa.Integer(), nullable=True),
    sa.Column('column', sa.String(length=128), nullable=True),
    sa.Column('reason', sa.String(length=255), nullable=False),
    sa.Column('raw', sa.JSON(), nullable=True),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['dd_run.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('dd_run_issue', schema=None) as batch_op:
        batch_op.create_index('ix_dd_run_issue_run', ['run_id'], unique=False)

    op.create_table('dd_run_log',
    sa.Column('run_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('ts', sa.DateTime(), nullable=False),
    sa.Column('stream', sa.String(length=8), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['dd_run.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('dd_run_log', schema=None) as batch_op:
        batch_op.create_index('ix_dd_run_log_run_seq', ['run_id', 'seq'], unique=False)

def downgrade() -> None:

    with op.batch_alter_table('dd_run_log', schema=None) as batch_op:
        batch_op.drop_index('ix_dd_run_log_run_seq')

    op.drop_table('dd_run_log')
    with op.batch_alter_table('dd_run_issue', schema=None) as batch_op:
        batch_op.drop_index('ix_dd_run_issue_run')

    op.drop_table('dd_run_issue')
    with op.batch_alter_table('dd_run_action', schema=None) as batch_op:
        batch_op.drop_index('ix_dd_run_action_run')

    op.drop_table('dd_run_action')
    with op.batch_alter_table('dd_run', schema=None) as batch_op:
        batch_op.drop_index('ix_dd_run_task_started')
        batch_op.drop_index('ix_dd_run_status')

    op.drop_table('dd_run')
    with op.batch_alter_table('dd_task', schema=None) as batch_op:
        batch_op.drop_index('ix_dd_task_next_run')
        batch_op.drop_index('ix_dd_task_doc')

    op.drop_table('dd_task')
    with op.batch_alter_table('dd_doc_sheet', schema=None) as batch_op:
        batch_op.drop_index('ix_dd_doc_sheet_doc')

    op.drop_table('dd_doc_sheet')
    with op.batch_alter_table('dd_doc', schema=None) as batch_op:
        batch_op.drop_index('ix_dd_doc_group')

    op.drop_table('dd_doc')
    op.drop_table('sys_user')
    with op.batch_alter_table('sys_audit', schema=None) as batch_op:
        batch_op.drop_index('ix_sys_audit_created')

    op.drop_table('sys_audit')
    op.drop_table('dd_template')
    op.drop_table('dd_doc_group')
    op.drop_table('dd_datasource')
    op.drop_table('dd_contact')
    op.drop_table('dd_app')
    op.drop_table('dd_action')
