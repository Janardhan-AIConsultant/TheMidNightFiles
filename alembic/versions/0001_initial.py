"""initial business schema (spec section 11; no log tables)

Revision ID: 0001
Revises:
"""
from alembic import op

from backend.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Initial snapshot of the business schema. Later migrations must be explicit.
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
