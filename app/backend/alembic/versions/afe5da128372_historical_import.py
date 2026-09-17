"""historical meeting data import

Revision ID: afe5da128372
Revises: bec253a6d1fe
Create Date: 2026-09-17 00:00:00.000000

Adds support for the Historical Meeting Data Import feature: batch import
jobs, per-file outcomes, and imported-document metadata, plus additive
columns on `meetings` (is_historical) and `ai_sources` (document citation
metadata: source_file/file_type/document_type/page_number/sheet_name/
slide_number/section). No existing table's semantics change — every column
added here is nullable or has a safe default, and no existing column is
altered or dropped. Portable across SQLite and Azure SQL — no
PostgreSQL-specific types or raw SQL, consistent with
docs/MIGRATION_FROM_POSTGRES.md.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'afe5da128372'
down_revision: Union[str, None] = 'bec253a6d1fe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('meetings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_historical', sa.Boolean(), server_default='0', nullable=False))

    with op.batch_alter_table('ai_sources', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source_file', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('file_type', sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column('document_type', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('page_number', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('sheet_name', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('slide_number', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('section', sa.String(length=500), nullable=True))

    op.create_table(
        'historical_import_jobs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('tenant_id', sa.String(length=36), nullable=False),
        sa.Column('created_by', sa.String(length=36), nullable=False),
        sa.Column(
            'status',
            sa.Enum('queued', 'processing', 'completed', 'completed_with_warnings', 'failed', name='importjobstatus'),
            nullable=False,
        ),
        sa.Column('total_files', sa.Integer(), nullable=False),
        sa.Column('processed_files', sa.Integer(), nullable=False),
        sa.Column('successful_files', sa.Integer(), nullable=False),
        sa.Column('skipped_files', sa.Integer(), nullable=False),
        sa.Column('failed_files', sa.Integer(), nullable=False),
        sa.Column('current_file', sa.String(length=1024), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_historical_import_jobs_tenant_id'), 'historical_import_jobs', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_historical_import_jobs_status'), 'historical_import_jobs', ['status'], unique=False)

    op.create_table(
        'imported_file_results',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('import_job_id', sa.String(length=36), nullable=False),
        sa.Column('filename', sa.String(length=500), nullable=False),
        sa.Column('relative_path', sa.String(length=1024), nullable=False),
        sa.Column('file_type', sa.String(length=16), nullable=False),
        sa.Column(
            'status', sa.Enum('success', 'skipped', 'failed', 'duplicate', name='importfilestatus'), nullable=False
        ),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('recommended_action', sa.String(length=500), nullable=True),
        sa.Column('document_id', sa.String(length=128), nullable=True),
        sa.Column('meeting_id', sa.String(length=36), nullable=True),
        sa.Column('chunk_count', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['import_job_id'], ['historical_import_jobs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['meeting_id'], ['meetings.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_imported_file_results_job', 'imported_file_results', ['import_job_id'], unique=False)

    op.create_table(
        'historical_documents',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('tenant_id', sa.String(length=36), nullable=False),
        sa.Column('meeting_id', sa.String(length=36), nullable=True),
        sa.Column('import_job_id', sa.String(length=36), nullable=True),
        sa.Column('source_file', sa.String(length=500), nullable=False),
        sa.Column('relative_path', sa.String(length=1024), nullable=False),
        sa.Column('file_type', sa.String(length=16), nullable=False),
        sa.Column('document_type', sa.String(length=32), nullable=False),
        sa.Column('file_hash', sa.String(length=64), nullable=False),
        sa.Column('blob_path', sa.String(length=1024), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('chunk_count', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['import_job_id'], ['historical_import_jobs.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['meeting_id'], ['meetings.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'file_hash', name='uq_historical_documents_tenant_hash'),
    )
    op.create_index(op.f('ix_historical_documents_tenant_id'), 'historical_documents', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_historical_documents_meeting_id'), 'historical_documents', ['meeting_id'], unique=False)
    op.create_index(op.f('ix_historical_documents_file_hash'), 'historical_documents', ['file_hash'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_historical_documents_file_hash'), table_name='historical_documents')
    op.drop_index(op.f('ix_historical_documents_meeting_id'), table_name='historical_documents')
    op.drop_index(op.f('ix_historical_documents_tenant_id'), table_name='historical_documents')
    op.drop_table('historical_documents')

    op.drop_index('ix_imported_file_results_job', table_name='imported_file_results')
    op.drop_table('imported_file_results')

    op.drop_index(op.f('ix_historical_import_jobs_status'), table_name='historical_import_jobs')
    op.drop_index(op.f('ix_historical_import_jobs_tenant_id'), table_name='historical_import_jobs')
    op.drop_table('historical_import_jobs')

    with op.batch_alter_table('ai_sources', schema=None) as batch_op:
        batch_op.drop_column('section')
        batch_op.drop_column('slide_number')
        batch_op.drop_column('sheet_name')
        batch_op.drop_column('page_number')
        batch_op.drop_column('document_type')
        batch_op.drop_column('file_type')
        batch_op.drop_column('source_file')

    with op.batch_alter_table('meetings', schema=None) as batch_op:
        batch_op.drop_column('is_historical')
