"""Turn traces: a plain record of how a turn ran, scrubbed, then sent to Langfuse without waiting.

Only redacted text, ids, tool names, outcome, tokens, cost and timings go into a trace; model
messages, reasoning notes and tool arguments never do. The secret conversation id never does.
"""

import base64
import dataclasses
import logging
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

from langfuse import LangfuseOtelSpanAttributes as Attr
from langfuse import __version__ as langfuse_version
from langfuse._client.attributes import (
    create_generation_attributes,
    create_span_attributes,
    create_trace_attributes,
)
from opentelemetry import trace as otel
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from app.logs import log_event, mask_digit_runs
from app.settings import Settings

ID_REMOVED = "[id removed]"


@dataclass
class Observation:
    name: str
    kind: Literal["generation", "tool", "span"]
    start: datetime
    end: datetime
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    level: Literal["DEFAULT", "WARNING", "ERROR"] = "DEFAULT"
    status: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TurnTrace:
    session_id: str
    name: str
    start: datetime
    end: datetime
    input: str
    output: str
    metadata: dict[str, Any]
    observations: list[Observation]


def _clean(value: Any, secret_id: str) -> Any:
    if isinstance(value, str):
        return mask_digit_runs(
            value.replace(secret_id, ID_REMOVED) if secret_id else value
        )
    if isinstance(value, float):
        return round(value, 8)
    if isinstance(value, list | tuple):
        return [_clean(v, secret_id) for v in value]
    if isinstance(value, dict):
        return {_clean(k, secret_id): _clean(v, secret_id) for k, v in value.items()}
    return value


def scrub(trace: TurnTrace, secret_id: str) -> TurnTrace:
    """Mask runs of 13+ digits and the secret id in every text field; the session id stays as is."""
    observations = [
        dataclasses.replace(
            o,
            name=_clean(o.name, secret_id),
            status=_clean(o.status, secret_id),
            cost_usd=_clean(o.cost_usd, secret_id),
            metadata=_clean(o.metadata, secret_id),
        )
        for o in trace.observations
    ]
    return dataclasses.replace(
        trace,
        name=_clean(trace.name, secret_id),
        input=_clean(trace.input, secret_id),
        output=_clean(trace.output, secret_id),
        metadata=_clean(trace.metadata, secret_id),
        observations=observations,
    )


class Tracer(Protocol):
    def send(self, trace: TurnTrace, on_sent: Callable[[str], None]) -> None:
        """Hand the trace over without blocking; call on_sent(trace id) once it is stored."""
        ...

    def flush(self, timeout_s: float) -> None: ...


class RecordingTracer:
    """The in-memory test double: keeps every trace and confirms it at once."""

    def __init__(self) -> None:
        self.traces: list[TurnTrace] = []

    def send(self, trace: TurnTrace, on_sent: Callable[[str], None]) -> None:
        self.traces.append(trace)
        on_sent(uuid.uuid4().hex)

    def flush(self, timeout_s: float) -> None:
        return None


def _ns(moment: datetime) -> int:
    return int(moment.timestamp() * 1_000_000_000)


def _attributes(o: Observation, session_id: str) -> dict[str, Any]:
    common: dict[str, Any] = {
        "metadata": o.metadata or None,
        "level": o.level,
        "status_message": o.status,
    }
    if o.kind == "span":
        attrs = create_span_attributes(**common)
    else:
        usage = {
            k: v
            for k, v in (("input", o.input_tokens), ("output", o.output_tokens))
            if v is not None
        }
        attrs = create_generation_attributes(
            **common,
            model=o.model,
            usage_details=usage or None,
            cost_details={"total": o.cost_usd} if o.cost_usd is not None else None,
        )
        attrs[Attr.OBSERVATION_TYPE] = o.kind
    return {**attrs, Attr.TRACE_SESSION_ID: session_id}


class LangfuseTracer:
    """Exports each trace as OpenTelemetry spans to Langfuse on one background worker."""

    def __init__(
        self,
        base_url: str,
        public_key: str,
        secret_key: str,
        timeout_s: float = 5.0,
        exporter: SpanExporter | None = None,
    ) -> None:
        auth = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
        self._exporter = exporter or OTLPSpanExporter(
            endpoint=base_url.rstrip("/") + "/api/public/otel/v1/traces",
            headers={
                "Authorization": f"Basic {auth}",
                "x-langfuse-sdk-name": "python",
                "x-langfuse-sdk-version": langfuse_version,
                "x-langfuse-public-key": public_key,
            },
            timeout=timeout_s,
        )
        self._finished = InMemorySpanExporter()
        provider = TracerProvider(shutdown_on_exit=False)
        provider.add_span_processor(SimpleSpanProcessor(self._finished))
        self._tracer = provider.get_tracer(
            "langfuse-sdk", langfuse_version, attributes={"public_key": public_key}
        )
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="trace")
        # The one warning per failed send is ours; the exporter's own retry logs stay quiet.
        logging.getLogger("opentelemetry.exporter.otlp").setLevel(logging.CRITICAL)

    def send(self, trace: TurnTrace, on_sent: Callable[[str], None]) -> None:
        self._worker.submit(self._deliver, trace, on_sent)

    def flush(self, timeout_s: float) -> None:
        try:
            self._worker.submit(lambda: None).result(timeout=timeout_s)
        except Exception:  # noqa: BLE001 - flushing is best effort
            return

    def _deliver(self, trace: TurnTrace, on_sent: Callable[[str], None]) -> None:
        try:
            root = self._tracer.start_span(
                trace.name,
                start_time=_ns(trace.start),
                attributes={
                    **create_trace_attributes(input=trace.input, output=trace.output),
                    **create_span_attributes(
                        input=trace.input, output=trace.output, metadata=trace.metadata
                    ),
                    Attr.TRACE_NAME: trace.name,
                    Attr.TRACE_SESSION_ID: trace.session_id,
                },
            )
            parent = otel.set_span_in_context(root)
            for o in trace.observations:
                span = self._tracer.start_span(
                    o.name,
                    context=parent,
                    start_time=_ns(o.start),
                    attributes=_attributes(o, trace.session_id),
                )
                span.end(end_time=_ns(o.end))
            root.end(end_time=_ns(trace.end))
            trace_id = otel.format_trace_id(root.get_span_context().trace_id)
            spans = self._finished.get_finished_spans()
            self._finished.clear()
            outcome = self._exporter.export(spans)
        except Exception as exc:  # noqa: BLE001 - tracing never breaks a turn
            self._finished.clear()
            log_event(
                "trace_send_failed", level="warning", error_type=type(exc).__name__
            )
            return
        if outcome is not SpanExportResult.SUCCESS:
            log_event("trace_send_failed", level="warning", error_type="export_failed")
            return
        try:
            on_sent(trace_id)
        except Exception as exc:  # noqa: BLE001 - a lost trace id never breaks a turn
            log_event(
                "trace_id_save_failed", level="warning", error_type=type(exc).__name__
            )


def tracer_for(settings: Settings, timeout_s: float = 5.0) -> Tracer | None:
    """Langfuse when both keys are set; otherwise tracing is off."""
    if settings.LANGFUSE_PUBLIC_KEY is None or settings.LANGFUSE_SECRET_KEY is None:
        return None
    return LangfuseTracer(
        settings.LANGFUSE_BASE_URL,
        settings.LANGFUSE_PUBLIC_KEY.get_secret_value(),
        settings.LANGFUSE_SECRET_KEY.get_secret_value(),
        timeout_s=timeout_s,
    )


def send_turn_trace(
    tracer: Tracer | None,
    trace: TurnTrace,
    secret_id: str,
    on_sent: Callable[[str], None],
) -> None:
    """Scrub the trace and hand it to the tracer; any failure is one warning, never an error."""
    if tracer is None:
        return
    try:
        tracer.send(scrub(trace, secret_id), on_sent)
    except Exception as exc:  # noqa: BLE001 - tracing never breaks a turn
        log_event("trace_send_failed", level="warning", error_type=type(exc).__name__)
