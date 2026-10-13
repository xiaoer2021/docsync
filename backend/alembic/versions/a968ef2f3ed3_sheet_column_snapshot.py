'sheet column snapshot'

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'a968ef2f3ed3'
down_revision: str | None = '5eea6768c0b8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:

    with op.batch_alter_table('dd_doc', schema=None) as batch_op:
        batch_op.add_column(sa.Column('last_column_check_at', sa.DateTime(), nullable=True))

    with op.batch_alter_table('dd_doc_sheet', schema=None) as batch_op:
        batch_op.add_column(sa.Column('column_names', sa.JSON(), nullable=True))

def downgrade() -> None:

    with op.batch_alter_table('dd_doc_sheet', schema=None) as batch_op:
        batch_op.drop_column('column_names')

    with op.batch_alter_table('dd_doc', schema=None) as batch_op:
        batch_op.drop_column('last_column_check_at')
