"""PyAI REST client, webhook verification, and response normalization.

Only this package may know PyAI response shapes.
"""

from __future__ import annotations

import json
import time
from typing import Any
from uuid import UUID

import httpx

from app.core.enums import TERMINAL_PYAI_JOB_STATUSES, AudioInputMode, PyAIJobStatus
from app.core.errors import (
    PyAIAuthFailed,
    PyAIJobCancelled,
    PyAIJobFailed,
    PyAIJobTimeout,
    PyAIRecapFailed,
    PyAIRecapPendingTimeout,
    PyAIResultFetchFailed,
    PyAIScopeMissing,
    PyAISubmitFailed,
    PyAIWebhookSignatureInvalid,
)
from app.core.security import verify_hmac_hex
from app.core.settings import Settings
from app.providers.normalized import (
    NormalizedRecap,
    NormalizedSegment,
    NormalizedSpeaker,
    NormalizedTranscript,
    NormalizedWord,
    RecapActionItem,
    RecapMoment,
    TranscriptionJobHandle,
)

_TRANSIENT_HTTP = {408, 429, 500, 502, 503, 504}


def verify_pyai_webhook_signature(secret: bytes, raw_body: bytes, header_value: str | None) -> None:
    if not header_value:
        raise PyAIWebhookSignatureInvalid("Missing X-PyAI-Signature header")
    if not secret:
        raise PyAIWebhookSignatureInvalid("Webhook secret is not configured")
    if not verify_hmac_hex(secret, raw_body, header_value):
        raise PyAIWebhookSignatureInvalid("Invalid PyAI webhook signature")


def _ms(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        # PyAI may send seconds as floats.
        if isinstance(value, float) and value < 10_000:
            return int(value * 1000)
        return int(value)
    return 0


def normalize_transcript(payload: dict[str, Any], *, recording_mode: str) -> NormalizedTranscript:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    if not isinstance(result, dict):
        result = {}
    segments_raw = result.get("segments") or result.get("utterances") or payload.get("segments") or []
    speakers: dict[str, NormalizedSpeaker] = {}
    segments: list[NormalizedSegment] = []
    for index, item in enumerate(segments_raw):
        if not isinstance(item, dict):
            continue
        speaker_id = str(item.get("speaker") or item.get("speaker_id") or item.get("channel") or "speaker_0")
        channel = item.get("channel")
        channel_i = int(channel) if isinstance(channel, int) else None
        start_ms = _ms(item.get("start_ms", item.get("start")))
        end_ms = _ms(item.get("end_ms", item.get("end")))
        text = str(item.get("text") or item.get("transcript") or "").strip()
        words: list[NormalizedWord] = []
        for word in item.get("words") or []:
            if not isinstance(word, dict):
                continue
            words.append(
                NormalizedWord(
                    start_ms=_ms(word.get("start_ms", word.get("start"))),
                    end_ms=_ms(word.get("end_ms", word.get("end"))),
                    word=str(word.get("word") or word.get("text") or ""),
                )
            )
        provider_segment_id = str(item.get("id") or item.get("segment_id") or index)
        segments.append(
            NormalizedSegment(
                provider_segment_id=provider_segment_id,
                provider_speaker_id=speaker_id,
                start_ms=start_ms,
                end_ms=end_ms,
                text=text,
                words=words,
                channel=channel_i,
            )
        )
        speakers.setdefault(
            speaker_id,
            NormalizedSpeaker(provider_speaker_id=speaker_id, channel=channel_i, label=item.get("speaker_label")),
        )
    duration = result.get("duration_ms") or result.get("duration") or payload.get("duration_ms")
    text = str(result.get("text") or payload.get("text") or " ".join(s.text for s in segments))
    outputs = result.get("outputs") if isinstance(result.get("outputs"), dict) else {}
    return NormalizedTranscript(
        language=result.get("language") or payload.get("language"),
        duration_ms=_ms(duration) if duration is not None else (segments[-1].end_ms if segments else None),
        text=text,
        speakers=list(speakers.values()),
        segments=segments,
        recording_mode=recording_mode,
        srt_url=(outputs or {}).get("srt_url") or result.get("srt_url"),
        vtt_url=(outputs or {}).get("vtt_url") or result.get("vtt_url"),
        job_id=str(payload.get("id") or payload.get("job_id") or "") or None,
        raw=payload,
    )


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _action(item: Any) -> RecapActionItem:
    if isinstance(item, str):
        return RecapActionItem(text=item)
    if isinstance(item, dict):
        return RecapActionItem(
            text=str(item.get("text") or item.get("action") or item.get("title") or ""),
            owner=item.get("owner") or item.get("assignee"),
            due_text=item.get("due") or item.get("due_text") or item.get("due_date"),
            side=item.get("side") or item.get("party"),
        )
    return RecapActionItem(text=str(item))


def normalize_recap(payload: dict[str, Any], *, capability_warning: str | None = None) -> NormalizedRecap:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        data = {}
    summary = data.get("summary") or data.get("summary_draft")
    moments: list[RecapMoment] = []
    for item in _as_list(data.get("important_moments") or data.get("moments")):
        if isinstance(item, dict):
            moments.append(
                RecapMoment(
                    title=str(item.get("title") or item.get("label") or "moment"),
                    summary=item.get("summary") or item.get("text"),
                    start_ms=_ms(item.get("start_ms", item.get("start")))
                    if item.get("start_ms", item.get("start"))
                    else None,
                    kind=item.get("kind") or item.get("type"),
                )
            )
        elif isinstance(item, str):
            moments.append(RecapMoment(title=item))
    return NormalizedRecap(
        status=str(data.get("status") or payload.get("status") or "unknown"),
        headline=data.get("headline"),
        tldr=data.get("tldr") or data.get("tl_dr"),
        summary=summary if isinstance(summary, str) else None,
        decisions=[
            str(d) if not isinstance(d, dict) else str(d.get("text") or d) for d in _as_list(data.get("decisions"))
        ],
        action_items=[_action(i) for i in _as_list(data.get("action_items") or data.get("actions"))],
        next_steps=[_action(i) for i in _as_list(data.get("next_steps"))],
        important_moments=moments,
        call_signals=data["call_signals"] if isinstance(data.get("call_signals"), dict) else {},
        structured=data["structured"] if isinstance(data.get("structured"), dict) else {},
        capability_warning=capability_warning,
        raw=payload,
    )


class PyAITranscriptionProvider:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.Client(timeout=60.0)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._settings.pyai_api_key}",
            "Accept": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _raise_for_status(self, response: httpx.Response, *, submit: bool = False) -> None:
        if response.status_code in {401, 403}:
            raise PyAIAuthFailed("PyAI authentication failed")
        if response.status_code in _TRANSIENT_HTTP:
            raise (
                PyAISubmitFailed("PyAI request failed with a transient error")
                if submit
                else PyAIResultFetchFailed("PyAI request failed with a transient error")
            )
        if response.status_code >= 400:
            if submit:
                raise PyAISubmitFailed("PyAI job submission failed", details={"status_code": response.status_code})
            raise PyAIResultFetchFailed("PyAI request failed", details={"status_code": response.status_code})

    def submit_job(
        self,
        *,
        call_id: UUID,
        public_call_id: str,
        audio_url: str | None,
        audio_stream: tuple[bytes, str, str] | None,
        call_direction: str,
        customer_name: str | None,
        recording_mode: str,
        webhook_url: str | None,
        idempotency_key: str,
    ) -> TranscriptionJobHandle:
        stereo = recording_mode == "stereo"
        body: dict[str, Any] = {
            "call_id": public_call_id,
            "call_direction": call_direction,
            "pack_id": self._settings.pyai_recap_pack_id,
            "numerals": True,
            "output_formats": ["json", "srt", "vtt"],
        }
        if customer_name:
            body["customer_name"] = customer_name
        if stereo:
            body["channel"] = True
        else:
            body["diarize"] = True
        if webhook_url:
            body["webhook_url"] = webhook_url
        url = f"{self._settings.pyai_base_url.rstrip('/')}/transcription/jobs"
        try:
            if self._settings.pyai_audio_input_mode == AudioInputMode.MULTIPART and audio_stream:
                data_bytes, filename, content_type = audio_stream
                files = {"audio": (filename, data_bytes, content_type)}
                if audio_url:
                    body["audio_url"] = audio_url
                response = self._client.post(
                    url,
                    data={k: json.dumps(v) if isinstance(v, (list, dict, bool)) else v for k, v in body.items()},
                    files=files,
                    headers=self._headers(idempotency_key),
                )
            else:
                if not audio_url:
                    raise PyAISubmitFailed("audio_url is required when PYAI_AUDIO_INPUT_MODE=audio_url")
                body["audio_url"] = audio_url
                response = self._client.post(url, json=body, headers=self._headers(idempotency_key))
        except httpx.HTTPError as exc:
            raise PyAISubmitFailed("PyAI submit request failed") from exc
        self._raise_for_status(response, submit=True)
        payload = response.json()
        job_id = str(payload.get("id") or payload.get("job_id") or "")
        if not job_id:
            raise PyAISubmitFailed("PyAI submit response missing job id")
        return TranscriptionJobHandle(
            job_id=job_id,
            status=str(payload.get("status") or "queued"),
            public_call_id=public_call_id,
        )

    def get_job(self, job_id: str) -> dict[str, object]:
        url = f"{self._settings.pyai_base_url.rstrip('/')}/transcription/jobs/{job_id}"
        try:
            response = self._client.get(url, headers=self._headers())
        except httpx.HTTPError as exc:
            raise PyAIResultFetchFailed("Failed to fetch PyAI job") from exc
        self._raise_for_status(response)
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def _load_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("result") and isinstance(payload["result"], dict):
            return payload
        result_url = payload.get("result_url")
        if isinstance(result_url, str) and result_url:
            try:
                response = self._client.get(result_url, headers=self._headers())
            except httpx.HTTPError as exc:
                raise PyAIResultFetchFailed("Failed to fetch offloaded PyAI result") from exc
            self._raise_for_status(response)
            offloaded = response.json()
            merged = dict(payload)
            merged["result"] = offloaded if isinstance(offloaded, dict) else {"raw": offloaded}
            return merged
        return payload

    def fetch_normalized(self, job_id: str) -> NormalizedTranscript:
        payload = self.get_job(job_id)
        status = str(payload.get("status") or "").lower()
        if status == PyAIJobStatus.FAILED.value:
            raise PyAIJobFailed("PyAI transcription job failed", details={"job_id": job_id})
        if status == PyAIJobStatus.CANCELLED.value:
            raise PyAIJobCancelled("PyAI transcription job was cancelled", details={"job_id": job_id})
        loaded = self._load_result(payload)
        recording_mode = "stereo" if loaded.get("channel") or (loaded.get("result") or {}).get("channel") else "mono"
        return normalize_transcript(loaded, recording_mode=recording_mode)

    def poll_until_complete(self, job_id: str) -> NormalizedTranscript:
        deadline = time.monotonic() + self._settings.pyai_poll_deadline_seconds
        while time.monotonic() < deadline:
            payload = self.get_job(job_id)
            status = str(payload.get("status") or "").lower()
            try:
                mapped = PyAIJobStatus(status)
            except ValueError:
                mapped = None
            if mapped in TERMINAL_PYAI_JOB_STATUSES:
                return self.fetch_normalized(job_id)
            time.sleep(self._settings.pyai_poll_interval_seconds)
        raise PyAIJobTimeout("PyAI transcription job timed out", details={"job_id": job_id})


class PyAIRecapProvider:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.Client(timeout=60.0)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def get_recap(self, call_id: UUID, public_call_id: str) -> NormalizedRecap:
        url = f"{self._settings.pyai_base_url.rstrip('/')}/recap/calls/{public_call_id}"
        headers = {
            "Authorization": f"Bearer {self._settings.pyai_api_key}",
            "Accept": "application/json",
        }
        try:
            response = self._client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise PyAIRecapFailed("Failed to fetch PyAI Recap") from exc
        if response.status_code in {401, 403}:
            raise PyAIAuthFailed("PyAI authentication failed")
        if response.status_code == 404:
            raise PyAIScopeMissing(
                "PyAI Recap is unavailable for this call or account",
                details={"public_call_id": public_call_id},
            )
        if response.status_code in {402, 412}:
            raise PyAIScopeMissing("PyAI Recap is not enabled for this account")
        if response.status_code in _TRANSIENT_HTTP:
            raise PyAIRecapPendingTimeout("PyAI Recap request failed transiently")
        if response.status_code >= 400:
            raise PyAIRecapFailed("PyAI Recap request failed", details={"status_code": response.status_code})
        payload = response.json()
        if not isinstance(payload, dict):
            raise PyAIRecapFailed("PyAI Recap response was not an object")
        recap = normalize_recap(payload)
        status = recap.status.lower()
        if status in {"pending", "processing", "queued"}:
            recap.capability_warning = recap.capability_warning or "PYAI_RECAP_PENDING"
        return recap

    def poll_until_ready(self, call_id: UUID, public_call_id: str) -> NormalizedRecap:
        deadline = time.monotonic() + self._settings.pyai_poll_deadline_seconds
        last: NormalizedRecap | None = None
        while time.monotonic() < deadline:
            try:
                recap = self.get_recap(call_id, public_call_id)
            except PyAIScopeMissing as exc:
                return NormalizedRecap(
                    status="unavailable",
                    capability_warning="PYAI_SCOPE_MISSING",
                    raw={"error": exc.code},
                )
            last = recap
            if recap.status.lower() in {"completed", "ready", "succeeded", "success", "done"}:
                return recap
            if recap.status.lower() in {"failed", "error"}:
                raise PyAIRecapFailed("PyAI Recap failed")
            time.sleep(self._settings.pyai_poll_interval_seconds)
        raise PyAIRecapPendingTimeout(
            "PyAI Recap did not complete before the deadline",
            details={"last_status": last.status if last else None},
        )


class PyAITraceProvider:
    def __init__(self, settings: Settings) -> None:
        self.enabled = settings.pyai_trace_enabled
        self._settings = settings

    def trace_event(self, *, call_id: UUID, event: str, payload: dict[str, object]) -> None:
        if not self.enabled:
            return
        # Feature-flagged no-op client: Trace must never block P0.
        return None
