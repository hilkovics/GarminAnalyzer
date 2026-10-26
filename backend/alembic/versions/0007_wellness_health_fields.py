"""daily_wellness health fields (METRICS §12.1)

Revision ID: 5e8c2a7d1f43
Revises: 9b1e6d2f4a87
Create Date: 2026-10-26 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5e8c2a7d1f43'
down_revision: Union[str, Sequence[str], None] = '9b1e6d2f4a87'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FLOATS = ('sleep_stress', 'respiration_sleep')
INTS = ('restless_count', 'bb_charge', 'bb_high', 'stress_high_s', 'intensity_min')


def upgrade() -> None:
    """Upgrade schema (filled from the stored raw JSON by `training recompute`)."""
    with op.batch_alter_table('daily_wellness', schema=None) as batch_op:
        for name in FLOATS:
            batch_op.add_column(sa.Column(name, sa.Float(), nullable=True))
        for name in INTS:
            batch_op.add_column(sa.Column(name, sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('daily_wellness', schema=None) as batch_op:
        for name in (*FLOATS, *INTS):
            batch_op.drop_column(name)
