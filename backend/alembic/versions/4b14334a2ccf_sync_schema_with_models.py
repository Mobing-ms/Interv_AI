"""sync schema with models

Revision ID: 4b14334a2ccf
Revises: fcb8b598a2e6
Create Date: 2026-10-26 15:55:44.030916

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4b14334a2ccf'
down_revision: Union[str, Sequence[str], None] = 'fcb8b598a2e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _insp():
    return sa.inspect(op.get_bind())


def _create_table(name, *cols, **kw):
    if name not in _insp().get_table_names():
        op.create_table(name, *cols, **kw)


def _create_index(name, table, cols, **kw):
    insp = _insp()
    if table in insp.get_table_names() and name not in {i["name"] for i in insp.get_indexes(table)}:
        op.create_index(name, table, cols, **kw)


def _add_column(table, column):
    insp = _insp()
    if table in insp.get_table_names() and column.name not in {c["name"] for c in insp.get_columns(table)}:
        op.add_column(table, column)


def _alter_column(table, column, nullable, **kw):
    insp = _insp()
    if table not in insp.get_table_names():
        return
    cols = {c["name"]: c for c in insp.get_columns(table)}
    if column not in cols or cols[column]["nullable"] == nullable:
        return
    kw.pop("existing_server_default", None)
    with op.batch_alter_table(table) as batch:
        batch.alter_column(column, nullable=nullable, **kw)


def upgrade() -> None:
    """
    Brings any database up to the models as of this revision. Every operation is
    guarded, so it is safe on: a fresh database (the earlier revisions were empty
    or partial), and on databases previously built by Base.metadata.create_all.
    """
    _create_table('email_otps',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('otp', sa.String(length=6), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    _create_index(op.f('ix_email_otps_email'), 'email_otps', ['email'], unique=False)
    _create_index(op.f('ix_email_otps_id'), 'email_otps', ['id'], unique=False)
    _create_table('guest_ip_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ip_address', sa.String(length=64), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    _create_index(op.f('ix_guest_ip_logs_id'), 'guest_ip_logs', ['id'], unique=False)
    _create_index(op.f('ix_guest_ip_logs_ip_address'), 'guest_ip_logs', ['ip_address'], unique=False)
    _create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=True),
    sa.Column('auth_provider', sa.String(length=50), nullable=False),
    sa.Column('is_verified', sa.Boolean(), nullable=False),
    sa.Column('onboarding_status', sa.String(length=50), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    _create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    _create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)
    _create_table('cv_documents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('is_guest', sa.Boolean(), nullable=False),
    sa.Column('file_key', sa.String(length=255), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('file_size', sa.Integer(), nullable=False),
    sa.Column('mime_type', sa.String(length=100), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('raw_text', sa.Text(), nullable=True),
    sa.Column('error_code', sa.String(length=50), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('structured_data', sa.JSON(), nullable=True),
    sa.Column('cross_check_flags', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('extracted_at', sa.DateTime(), nullable=True),
    sa.Column('parsed_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    _create_index(op.f('ix_cv_documents_file_key'), 'cv_documents', ['file_key'], unique=True)
    _create_index(op.f('ix_cv_documents_id'), 'cv_documents', ['id'], unique=False)
    _create_index(op.f('ix_cv_documents_is_guest'), 'cv_documents', ['is_guest'], unique=False)
    _create_index(op.f('ix_cv_documents_user_id'), 'cv_documents', ['user_id'], unique=False)
    _create_table('education_profiles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('degree', sa.String(length=100), nullable=False),
    sa.Column('branch', sa.String(length=100), nullable=False),
    sa.Column('college', sa.String(length=255), nullable=False),
    sa.Column('graduation_year', sa.Integer(), nullable=False),
    sa.Column('cgpa', sa.Float(), nullable=True),
    sa.Column('cgpa_scale', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    _create_index(op.f('ix_education_profiles_id'), 'education_profiles', ['id'], unique=False)
    _create_index(op.f('ix_education_profiles_user_id'), 'education_profiles', ['user_id'], unique=True)
    _create_table('target_profiles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('target_role', sa.String(length=150), nullable=False),
    sa.Column('company_type', sa.String(length=50), nullable=False),
    sa.Column('experience_level', sa.String(length=50), nullable=False),
    sa.Column('job_description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    _create_index(op.f('ix_target_profiles_id'), 'target_profiles', ['id'], unique=False)
    _create_index(op.f('ix_target_profiles_user_id'), 'target_profiles', ['user_id'], unique=True)
    _create_table('profiles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('structured_data', sa.JSON(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('cv_document_id', sa.Integer(), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['cv_document_id'], ['cv_documents.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    _create_index(op.f('ix_profiles_id'), 'profiles', ['id'], unique=False)
    _create_index(op.f('ix_profiles_user_id'), 'profiles', ['user_id'], unique=False)
    _create_table('integrity_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('question_id', sa.Integer(), nullable=True),
    sa.Column('type', sa.String(length=64), nullable=False),
    sa.Column('start_time', sa.Float(), nullable=False),
    sa.Column('end_time', sa.Float(), nullable=True),
    sa.Column('duration_seconds', sa.Float(), nullable=False),
    sa.Column('severity', sa.String(length=20), nullable=False),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['interview_sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    _create_index(op.f('ix_integrity_events_id'), 'integrity_events', ['id'], unique=False)
    _create_index(op.f('ix_integrity_events_question_id'), 'integrity_events', ['question_id'], unique=False)
    _create_index(op.f('ix_integrity_events_session_id'), 'integrity_events', ['session_id'], unique=False)
    _create_index(op.f('ix_integrity_events_type'), 'integrity_events', ['type'], unique=False)
    _create_table('session_analysis_jobs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('job_id', sa.String(length=100), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('progress', sa.Integer(), nullable=False),
    sa.Column('current_step', sa.String(length=100), nullable=False),
    sa.Column('is_partial', sa.Boolean(), nullable=False),
    sa.Column('missing_sections', sa.JSON(), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('retry_count', sa.Integer(), nullable=False),
    sa.Column('max_retries', sa.Integer(), nullable=False),
    sa.Column('aligned_data', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['session_id'], ['interview_sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    _create_index(op.f('ix_session_analysis_jobs_id'), 'session_analysis_jobs', ['id'], unique=False)
    _create_index(op.f('ix_session_analysis_jobs_job_id'), 'session_analysis_jobs', ['job_id'], unique=True)
    _create_index(op.f('ix_session_analysis_jobs_session_id'), 'session_analysis_jobs', ['session_id'], unique=True)
    _create_table('session_reports',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('is_guest', sa.Boolean(), nullable=False),
    sa.Column('report_data', sa.JSON(), nullable=False),
    sa.Column('is_grounded', sa.Boolean(), nullable=False),
    sa.Column('grounding_stats', sa.JSON(), nullable=False),
    sa.Column('regeneration_rounds', sa.Integer(), nullable=False),
    sa.Column('dropped_claims_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['interview_sessions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    _create_index(op.f('ix_session_reports_id'), 'session_reports', ['id'], unique=False)
    _create_index(op.f('ix_session_reports_is_guest'), 'session_reports', ['is_guest'], unique=False)
    _create_index(op.f('ix_session_reports_session_id'), 'session_reports', ['session_id'], unique=True)
    _create_index(op.f('ix_session_reports_user_id'), 'session_reports', ['user_id'], unique=False)
    _create_table('session_results',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('is_guest', sa.Boolean(), nullable=False),
    sa.Column('round_type', sa.String(length=50), nullable=False),
    sa.Column('role', sa.String(length=150), nullable=True),
    sa.Column('overall_score', sa.Float(), nullable=True),
    sa.Column('content_score', sa.Float(), nullable=True),
    sa.Column('speech_score', sa.Float(), nullable=True),
    sa.Column('face_score', sa.Float(), nullable=True),
    sa.Column('classification', sa.String(length=50), nullable=False),
    sa.Column('weights_used', sa.JSON(), nullable=False),
    sa.Column('per_question_scores', sa.JSON(), nullable=False),
    sa.Column('comparisons', sa.JSON(), nullable=False),
    sa.Column('weak_areas', sa.JSON(), nullable=False),
    sa.Column('strengths', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['interview_sessions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    _create_index(op.f('ix_session_results_id'), 'session_results', ['id'], unique=False)
    _create_index(op.f('ix_session_results_is_guest'), 'session_results', ['is_guest'], unique=False)
    _create_index(op.f('ix_session_results_session_id'), 'session_results', ['session_id'], unique=True)
    _create_index(op.f('ix_session_results_user_id'), 'session_results', ['user_id'], unique=False)
    _create_table('signal_time_series',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('question_id', sa.Integer(), nullable=False),
    sa.Column('timestamp', sa.Float(), nullable=False),
    sa.Column('metric', sa.String(length=64), nullable=False),
    sa.Column('value', sa.Float(), nullable=False),
    sa.Column('extra_data', sa.String(length=255), nullable=True),
    sa.ForeignKeyConstraint(['session_id'], ['interview_sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    _create_index('ix_signal_sess_metric', 'signal_time_series', ['session_id', 'metric'], unique=False)
    _create_index('ix_signal_sess_q_ts', 'signal_time_series', ['session_id', 'question_id', 'timestamp'], unique=False)
    _create_index(op.f('ix_signal_time_series_id'), 'signal_time_series', ['id'], unique=False)
    _create_index(op.f('ix_signal_time_series_metric'), 'signal_time_series', ['metric'], unique=False)
    _create_index(op.f('ix_signal_time_series_question_id'), 'signal_time_series', ['question_id'], unique=False)
    _create_index(op.f('ix_signal_time_series_session_id'), 'signal_time_series', ['session_id'], unique=False)
    _create_index(op.f('ix_signal_time_series_timestamp'), 'signal_time_series', ['timestamp'], unique=False)
    _add_column('interview_configs', sa.Column('is_guest', sa.Boolean(), nullable=False, server_default=sa.false()))
    _alter_column('interview_configs', 'user_id',
               existing_type=sa.INTEGER(),
               nullable=True)
    _create_index(op.f('ix_interview_configs_is_guest'), 'interview_configs', ['is_guest'], unique=False)
    _add_column('interview_sessions', sa.Column('is_guest', sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column('interview_sessions', sa.Column('guest_id', sa.String(length=100), nullable=True))
    _add_column('interview_sessions', sa.Column('audio_file_key', sa.String(length=500), nullable=True))
    _add_column('interview_sessions', sa.Column('video_file_key', sa.String(length=500), nullable=True))
    _add_column('interview_sessions', sa.Column('aligned_data_key', sa.String(length=500), nullable=True))
    _alter_column('interview_sessions', 'user_id',
               existing_type=sa.INTEGER(),
               nullable=True)
    _create_index(op.f('ix_interview_sessions_guest_id'), 'interview_sessions', ['guest_id'], unique=False)
    _create_index(op.f('ix_interview_sessions_is_guest'), 'interview_sessions', ['is_guest'], unique=False)
    _alter_column('session_calibrations', 'user_id',
               existing_type=sa.INTEGER(),
               nullable=True)
    _alter_column('session_calibrations', 'background_noise_level_db',
               existing_type=sa.FLOAT(),
               nullable=True,
               existing_server_default=sa.text("'-50.0'"))
    _add_column('user_consents', sa.Column('is_guest', sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column('user_consents', sa.Column('guest_id', sa.String(length=100), nullable=True))
    _alter_column('user_consents', 'user_id',
               existing_type=sa.INTEGER(),
               nullable=True)
    _create_index(op.f('ix_user_consents_guest_id'), 'user_consents', ['guest_id'], unique=False)
    _create_index(op.f('ix_user_consents_is_guest'), 'user_consents', ['is_guest'], unique=False)

    # Scores/noise floor become nullable ("not measured") on databases where these
    # tables already existed with NOT NULL.
    for col in ("overall_score", "content_score", "speech_score", "face_score"):
        _alter_column("session_results", col, existing_type=sa.Float(), nullable=True)
    _alter_column("session_calibrations", "background_noise_level_db", existing_type=sa.Float(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_user_consents_is_guest'), table_name='user_consents')
    op.drop_index(op.f('ix_user_consents_guest_id'), table_name='user_consents')
    op.alter_column('user_consents', 'user_id',
               existing_type=sa.INTEGER(),
               nullable=False)
    op.drop_column('user_consents', 'guest_id')
    op.drop_column('user_consents', 'is_guest')
    op.alter_column('session_calibrations', 'background_noise_level_db',
               existing_type=sa.FLOAT(),
               nullable=False,
               existing_server_default=sa.text("'-50.0'"))
    op.alter_column('session_calibrations', 'user_id',
               existing_type=sa.INTEGER(),
               nullable=False)
    op.drop_index(op.f('ix_interview_sessions_is_guest'), table_name='interview_sessions')
    op.drop_index(op.f('ix_interview_sessions_guest_id'), table_name='interview_sessions')
    op.alter_column('interview_sessions', 'user_id',
               existing_type=sa.INTEGER(),
               nullable=False)
    op.drop_column('interview_sessions', 'aligned_data_key')
    op.drop_column('interview_sessions', 'video_file_key')
    op.drop_column('interview_sessions', 'audio_file_key')
    op.drop_column('interview_sessions', 'guest_id')
    op.drop_column('interview_sessions', 'is_guest')
    op.drop_index(op.f('ix_interview_configs_is_guest'), table_name='interview_configs')
    op.alter_column('interview_configs', 'user_id',
               existing_type=sa.INTEGER(),
               nullable=False)
    op.drop_column('interview_configs', 'is_guest')
    op.drop_index(op.f('ix_signal_time_series_timestamp'), table_name='signal_time_series')
    op.drop_index(op.f('ix_signal_time_series_session_id'), table_name='signal_time_series')
    op.drop_index(op.f('ix_signal_time_series_question_id'), table_name='signal_time_series')
    op.drop_index(op.f('ix_signal_time_series_metric'), table_name='signal_time_series')
    op.drop_index(op.f('ix_signal_time_series_id'), table_name='signal_time_series')
    op.drop_index('ix_signal_sess_q_ts', table_name='signal_time_series')
    op.drop_index('ix_signal_sess_metric', table_name='signal_time_series')
    op.drop_table('signal_time_series')
    op.drop_index(op.f('ix_session_results_user_id'), table_name='session_results')
    op.drop_index(op.f('ix_session_results_session_id'), table_name='session_results')
    op.drop_index(op.f('ix_session_results_is_guest'), table_name='session_results')
    op.drop_index(op.f('ix_session_results_id'), table_name='session_results')
    op.drop_table('session_results')
    op.drop_index(op.f('ix_session_reports_user_id'), table_name='session_reports')
    op.drop_index(op.f('ix_session_reports_session_id'), table_name='session_reports')
    op.drop_index(op.f('ix_session_reports_is_guest'), table_name='session_reports')
    op.drop_index(op.f('ix_session_reports_id'), table_name='session_reports')
    op.drop_table('session_reports')
    op.drop_index(op.f('ix_session_analysis_jobs_session_id'), table_name='session_analysis_jobs')
    op.drop_index(op.f('ix_session_analysis_jobs_job_id'), table_name='session_analysis_jobs')
    op.drop_index(op.f('ix_session_analysis_jobs_id'), table_name='session_analysis_jobs')
    op.drop_table('session_analysis_jobs')
    op.drop_index(op.f('ix_integrity_events_type'), table_name='integrity_events')
    op.drop_index(op.f('ix_integrity_events_session_id'), table_name='integrity_events')
    op.drop_index(op.f('ix_integrity_events_question_id'), table_name='integrity_events')
    op.drop_index(op.f('ix_integrity_events_id'), table_name='integrity_events')
    op.drop_table('integrity_events')
    op.drop_index(op.f('ix_profiles_user_id'), table_name='profiles')
    op.drop_index(op.f('ix_profiles_id'), table_name='profiles')
    op.drop_table('profiles')
    op.drop_index(op.f('ix_target_profiles_user_id'), table_name='target_profiles')
    op.drop_index(op.f('ix_target_profiles_id'), table_name='target_profiles')
    op.drop_table('target_profiles')
    op.drop_index(op.f('ix_education_profiles_user_id'), table_name='education_profiles')
    op.drop_index(op.f('ix_education_profiles_id'), table_name='education_profiles')
    op.drop_table('education_profiles')
    op.drop_index(op.f('ix_cv_documents_user_id'), table_name='cv_documents')
    op.drop_index(op.f('ix_cv_documents_is_guest'), table_name='cv_documents')
    op.drop_index(op.f('ix_cv_documents_id'), table_name='cv_documents')
    op.drop_index(op.f('ix_cv_documents_file_key'), table_name='cv_documents')
    op.drop_table('cv_documents')
    op.drop_index(op.f('ix_users_id'), table_name='users')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
    op.drop_index(op.f('ix_guest_ip_logs_ip_address'), table_name='guest_ip_logs')
    op.drop_index(op.f('ix_guest_ip_logs_id'), table_name='guest_ip_logs')
    op.drop_table('guest_ip_logs')
    op.drop_index(op.f('ix_email_otps_id'), table_name='email_otps')
    op.drop_index(op.f('ix_email_otps_email'), table_name='email_otps')
    op.drop_table('email_otps')
    # ### end Alembic commands ###
