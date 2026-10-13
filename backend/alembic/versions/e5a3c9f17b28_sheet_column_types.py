'sheet column types snapshot'

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'e5a3c9f17b28'
down_revision: str | None = 'd7c2f4a1e839'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    with op.batch_alter_table('dd_doc_sheet', schema=None) as batch_op:
        batch_op.add_column(sa.Column('column_types', sa.JSON(), nullable=True))

def downgrade() -> None:
    with op.batch_alter_table('dd_doc_sheet', schema=None) as batch_op:
        batch_op.drop_column('column_types')
