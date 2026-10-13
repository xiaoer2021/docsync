'doc group many-to-many'

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'd7c2f4a1e839'
down_revision: str | None = 'c4a1e8b70f52'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.create_table(
        "dd_doc_group_link",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "doc_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "group_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("doc_id", "group_id", name="uq_doc_group_link"),
    )
    op.create_index("ix_dd_doc_group_link_doc", "dd_doc_group_link", ["doc_id"])
    op.create_index("ix_dd_doc_group_link_group", "dd_doc_group_link", ["group_id"])

    op.execute(
        """
        INSERT INTO dd_doc_group_link (doc_id, group_id, created_at, updated_at)
        SELECT id, group_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM dd_doc
        WHERE group_id IS NOT NULL
        """
    )

def downgrade() -> None:
    op.drop_index("ix_dd_doc_group_link_group", table_name="dd_doc_group_link")
    op.drop_index("ix_dd_doc_group_link_doc", table_name="dd_doc_group_link")
    op.drop_table("dd_doc_group_link")
