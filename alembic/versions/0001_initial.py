"""initial schema with pgvector

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("public_call_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("customer_name", sa.String(length=256), nullable=True),
        sa.Column("rep_name", sa.String(length=256), nullable=True),
        sa.Column("call_direction", sa.String(length=32), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=True),
        sa.Column("recording_mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("terminal_outcome", sa.String(length=32), nullable=True),
        sa.Column("failure_kind", sa.String(length=32), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("pyai_job_id", sa.String(length=128), nullable=True),
        sa.Column("stereo_seller_channel", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_calls"),
        sa.UniqueConstraint("public_call_id", name="uq_calls_public_call_id"),
    )
    op.create_index("ix_calls_public_call_id", "calls", ["public_call_id"])
    op.create_index("ix_calls_status", "calls", ["status"])
    op.create_index("ix_calls_pyai_job_id", "calls", ["pyai_job_id"])

    op.create_table(
        "audio_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("bucket", sa.String(length=128), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"], name="fk_audio_assets_call_id_calls", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_audio_assets"),
    )
    op.create_index("ix_audio_assets_call_id", "audio_assets", ["call_id"])

    op.create_table(
        "speakers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("provider_speaker_id", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("manually_overridden", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("channel", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"], name="fk_speakers_call_id_calls", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_speakers"),
        sa.UniqueConstraint("call_id", "provider_speaker_id", name="uq_speakers_call_provider"),
    )
    op.create_index("ix_speakers_call_id", "speakers", ["call_id"])

    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("provider_segment_id", sa.String(length=128), nullable=False),
        sa.Column("speaker_id", sa.Uuid(), nullable=True),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.ForeignKeyConstraint(
            ["call_id"], ["calls.id"], name="fk_transcript_segments_call_id_calls", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["speaker_id"], ["speakers.id"], name="fk_transcript_segments_speaker_id_speakers", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_transcript_segments"),
    )
    op.create_index("ix_transcript_segments_call_id", "transcript_segments", ["call_id"])
    op.create_index("ix_transcript_segments_speaker_id", "transcript_segments", ["speaker_id"])

    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "model_manifest",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"], name="fk_analysis_runs_call_id_calls", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_analysis_runs"),
        sa.UniqueConstraint("call_id", "version", name="uq_analysis_runs_call_version"),
    )
    op.create_index("ix_analysis_runs_call_id", "analysis_runs", ["call_id"])

    op.create_table(
        "insights",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("evidence_status", sa.String(length=32), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            ["analysis_runs.id"],
            name="fk_insights_analysis_run_id_analysis_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_insights"),
    )
    op.create_index("ix_insights_analysis_run_id", "insights", ["analysis_run_id"])
    op.create_index("ix_insights_type", "insights", ["type"])

    op.create_table(
        "evidence_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("insight_id", sa.Uuid(), nullable=False),
        sa.Column("transcript_segment_id", sa.Uuid(), nullable=False),
        sa.Column("relationship", sa.String(length=64), nullable=False, server_default="supports"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["insight_id"], ["insights.id"], name="fk_evidence_links_insight_id_insights", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["transcript_segment_id"],
            ["transcript_segments.id"],
            name="fk_evidence_links_transcript_segment_id_transcript_segments",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evidence_links"),
        sa.UniqueConstraint(
            "insight_id", "transcript_segment_id", "relationship", name="uq_evidence_insight_segment_rel"
        ),
    )
    op.create_index("ix_evidence_links_insight_id", "evidence_links", ["insight_id"])
    op.create_index("ix_evidence_links_transcript_segment_id", "evidence_links", ["transcript_segment_id"])

    op.create_table(
        "recap_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("provider_status", sa.String(length=64), nullable=False),
        sa.Column("headline", sa.String(length=1024), nullable=True),
        sa.Column("tldr", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "raw_record", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"], name="fk_recap_records_call_id_calls", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_recap_records"),
        sa.UniqueConstraint("call_id", name="uq_recap_records_call_id"),
    )

    op.create_table(
        "call_metrics",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column(
            "talk_ratio", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "longest_monologue",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "question_rate",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "keyword_hits",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"], name="fk_call_metrics_call_id_calls", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_call_metrics"),
        sa.UniqueConstraint("call_id", name="uq_call_metrics_call_id"),
    )

    embedding_type = sa.JSON()
    if bind.dialect.name == "postgresql":
        from pgvector.sqlalchemy import Vector

        embedding_type = Vector(384)

    op.create_table(
        "transcript_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("start_segment_id", sa.Uuid(), nullable=False),
        sa.Column("end_segment_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", embedding_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["call_id"], ["calls.id"], name="fk_transcript_chunks_call_id_calls", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["start_segment_id"],
            ["transcript_segments.id"],
            name="fk_transcript_chunks_start_segment_id_transcript_segments",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["end_segment_id"],
            ["transcript_segments.id"],
            name="fk_transcript_chunks_end_segment_id_transcript_segments",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_transcript_chunks"),
    )
    op.create_index("ix_transcript_chunks_call_id", "transcript_chunks", ["call_id"])

    op.create_table(
        "processing_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "details", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["call_id"], ["calls.id"], name="fk_processing_events_call_id_calls", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_processing_events"),
    )
    op.create_index("ix_processing_events_call_id", "processing_events", ["call_id"])
    op.create_index("ix_processing_events_stage", "processing_events", ["stage"])

    op.create_table(
        "share_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"], name="fk_share_links_call_id_calls", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_share_links"),
        sa.UniqueConstraint("token_hash", name="uq_share_links_token_hash"),
    )
    op.create_index("ix_share_links_call_id", "share_links", ["call_id"])
    op.create_index("ix_share_links_token_hash", "share_links", ["token_hash"])

    op.create_table(
        "tracked_terms",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=True),
        sa.Column("organization_scope", sa.String(length=128), nullable=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("value", sa.String(length=256), nullable=False),
        sa.Column(
            "aliases", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"], name="fk_tracked_terms_call_id_calls", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_tracked_terms"),
    )
    op.create_index("ix_tracked_terms_call_id", "tracked_terms", ["call_id"])
    op.create_index("ix_tracked_terms_organization_scope", "tracked_terms", ["organization_scope"])


def downgrade() -> None:
    op.drop_table("tracked_terms")
    op.drop_table("share_links")
    op.drop_table("processing_events")
    op.drop_table("transcript_chunks")
    op.drop_table("call_metrics")
    op.drop_table("recap_records")
    op.drop_table("evidence_links")
    op.drop_table("insights")
    op.drop_table("analysis_runs")
    op.drop_table("transcript_segments")
    op.drop_table("speakers")
    op.drop_table("audio_assets")
    op.drop_table("calls")
