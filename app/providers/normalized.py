"""Internal normalized transcription and recap models. No PyAI field names leak past here."""

from __future__ import annotations

from pydantic import BaseModel, Field


class NormalizedWord(BaseModel):
    start_ms: int
    end_ms: int
    word: str


class NormalizedSegment(BaseModel):
    provider_segment_id: str
    provider_speaker_id: str
    start_ms: int
    end_ms: int
    text: str
    words: list[NormalizedWord] = Field(default_factory=list)
    channel: int | None = None


class NormalizedSpeaker(BaseModel):
    provider_speaker_id: str
    channel: int | None = None
    label: str | None = None


class NormalizedTranscript(BaseModel):
    language: str | None = None
    duration_ms: int | None = None
    text: str = ""
    speakers: list[NormalizedSpeaker] = Field(default_factory=list)
    segments: list[NormalizedSegment] = Field(default_factory=list)
    recording_mode: str = "mono"
    srt_url: str | None = None
    vtt_url: str | None = None
    job_id: str | None = None
    raw: dict[str, object] = Field(default_factory=dict)


class RecapActionItem(BaseModel):
    text: str
    owner: str | None = None
    due_text: str | None = None
    side: str | None = None


class RecapMoment(BaseModel):
    title: str
    summary: str | None = None
    start_ms: int | None = None
    kind: str | None = None


class NormalizedRecap(BaseModel):
    status: str
    headline: str | None = None
    tldr: str | None = None
    summary: str | None = None
    decisions: list[str] = Field(default_factory=list)
    action_items: list[RecapActionItem] = Field(default_factory=list)
    next_steps: list[RecapActionItem] = Field(default_factory=list)
    important_moments: list[RecapMoment] = Field(default_factory=list)
    call_signals: dict[str, object] = Field(default_factory=dict)
    structured: dict[str, object] = Field(default_factory=dict)
    capability_warning: str | None = None
    raw: dict[str, object] = Field(default_factory=dict)


class TranscriptionJobHandle(BaseModel):
    job_id: str
    status: str
    public_call_id: str
