"""Add album.ignored

Revision ID: bb1854a2dbf8
Revises: 5807c663b37
Create Date: 2016-08-29 12:39:46.110029

"""

# revision identifiers, used by Alembic.
revision = 'bb1854a2dbf8'
down_revision = '5807c663b37'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('album', sa.Column('ignored', sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column('album', 'ignored')
