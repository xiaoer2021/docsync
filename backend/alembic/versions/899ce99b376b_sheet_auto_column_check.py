'sheet auto column check'

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '899ce99b376b'
down_revision: str | None = 'a968ef2f3ed3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    with op.batch_alter_table("dd_doc_sheet", schema=None) as batch_op:

        batch_op.add_column(
            sa.Column("auto_column_check", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(sa.Column("last_column_check_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("column_drift", sa.Text(), nullable=True))

def downgrade() -> None:
    with op.batch_alter_table("dd_doc_sheet", schema=None) as batch_op:
        batch_op.drop_column("column_drift")
        batch_op.drop_column("last_column_check_at")
        batch_op.drop_column("auto_column_check")
