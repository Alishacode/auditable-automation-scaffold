"""add classifying to jobstage enum

Revision ID: 3706181727b6
Revises: 5e23161c598f
Create Date: 2026-09-21 09:01:13.554469

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3706181727b6'
down_revision: Union[str, Sequence[str], None] = '5e23161c598f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE jobstage ADD VALUE IF NOT EXISTS 'CLASSIFYING'")


def downgrade() -> None:
    pass  # Postgres doesn't support removing enum values easily — leaving as a no-op
