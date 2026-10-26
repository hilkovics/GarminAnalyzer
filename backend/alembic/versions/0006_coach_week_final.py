"""coach_week.final: week numbers are final after the Monday sync (METRICS §11.3)

Revision ID: 9b1e6d2f4a87
Revises: 3d9a4c71e2b5
Create Date: 2026-10-26 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9b1e6d2f4a87'
down_revision: Union[str, Sequence[str], None] = '3d9a4c71e2b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # existing rows are not final: they are derived again on next use
    with op.batch_alter_table('coach_week', schema=None) as batch_op:
        batch_op.add_column(sa.Column('final', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('coach_week', schema=None) as batch_op:
        batch_op.drop_column('final')
