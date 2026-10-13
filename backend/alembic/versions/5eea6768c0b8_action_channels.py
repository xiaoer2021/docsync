'action channels'

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '5eea6768c0b8'
down_revision: str | None = '47ebbbdc2e94'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:

    with op.batch_alter_table('dd_action', schema=None) as batch_op:
        batch_op.add_column(sa.Column('channels', sa.JSON(), nullable=True))
        batch_op.alter_column('kind',
               existing_type=sa.VARCHAR(length=32),
               nullable=True)

def downgrade() -> None:

    with op.batch_alter_table('dd_action', schema=None) as batch_op:
        batch_op.alter_column('kind',
               existing_type=sa.VARCHAR(length=32),
               nullable=False)
        batch_op.drop_column('channels')
