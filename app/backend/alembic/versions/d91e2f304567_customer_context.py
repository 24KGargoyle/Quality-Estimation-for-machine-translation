"""Persist the selected operational customer on conversations."""
from alembic import op
import sqlalchemy as sa

revision = 'd91e2f304567'
down_revision = '857fa319ae8c'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('conversations', sa.Column('customer_id', sa.String(100), nullable=True))


def downgrade():
    op.drop_column('conversations', 'customer_id')
