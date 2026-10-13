'app recipe：把「网页取数」的元素库和步骤存在应用上。'

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'f1a2b3c4d5e6'
down_revision: str | None = 'e5a3c9f17b28'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    with op.batch_alter_table('dd_app', schema=None) as batch_op:
        batch_op.add_column(sa.Column('recipe', sa.JSON(), nullable=True))

def downgrade() -> None:
    with op.batch_alter_table('dd_app', schema=None) as batch_op:
        batch_op.drop_column('recipe')
