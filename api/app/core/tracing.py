"""Optional OpenTelemetry tracing setup.
SPDX-License-Identifier: BUSL-1.1
"""
from __future__ import annotations

from fastapi import FastAPI
from .config import settings


def setup_tracing(app: FastAPI) -> None:
    if not settings.otel_enabled:
        return
    try:
        # Local imports to avoid hard dependency when disabled
        from opentelemetry import trace  # type: ignore
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource  # type: ignore
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore
        from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter  # type: ignore
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # type: ignore
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased  # type: ignore

        resource = Resource.create({SERVICE_NAME: settings.otel_service_name})
        provider = TracerProvider(resource=resource, sampler=TraceIdRatioBased(max(0.0, min(1.0, float(settings.otel_sample_ratio)))))
        trace.set_tracer_provider(provider)

        endpoint = settings.otel_exporter_otlp_endpoint or "http://127.0.0.1:4318/v1/traces"
        exporter = OTLPSpanExporter(endpoint=endpoint)
        span_processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(span_processor)

        # Instrument FastAPI app
        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    except Exception:
        # Do not fail the app if tracing setup fails
        pass
