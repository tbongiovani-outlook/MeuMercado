"""Observabilidade do Meu Mercado: logging em arquivo + OpenTelemetry.

- `setup_logging()`  configura logs para arquivo (rotativo) e console.
- `setup_telemetry(app)` instrumenta FastAPI e httpx com OpenTelemetry,
  exportando os spans para `logs/traces.log` (padrão) ou para um coletor
  OTLP se `OTEL_EXPORTER_OTLP_ENDPOINT` estiver definido.

Tudo é multiplataforma (Windows/macOS) e degrada com segurança caso o
OpenTelemetry não esteja instalado.
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "meu_mercado.log"
TRACES_FILE = LOG_DIR / "traces.log"

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

_logger = logging.getLogger("meu_mercado")


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configura o logging da aplicação (arquivo rotativo + console)."""
    LOG_DIR.mkdir(exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level)

    # Evita duplicar handlers quando o Uvicorn recarrega (--reload).
    already = {type(h) for h in root.handlers}
    if RotatingFileHandler not in already:
        file_handler = RotatingFileHandler(
            LOG_FILE, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        root.addHandler(file_handler)

    if logging.StreamHandler not in already:
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(_LOG_FORMAT))
        root.addHandler(console)

    _logger.info("Logging configurado. Arquivo: %s", LOG_FILE.resolve())
    return _logger


def setup_telemetry(app) -> None:
    """Instrumenta FastAPI e httpx com OpenTelemetry (traces)."""
    try:
        from opentelemetry import trace
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )
    except ImportError:
        _logger.warning("OpenTelemetry não instalado; telemetria desativada.")
        return

    # Não reconfigura em recarregamentos.
    if isinstance(trace.get_tracer_provider(), TracerProvider):
        _logger.debug("TracerProvider já configurado; ignorando.")
        return

    try:
        from . import __version__
    except Exception:  # noqa: BLE001
        __version__ = "0.0.0"

    resource = Resource.create(
        {"service.name": "meu-mercado", "service.version": __version__}
    )
    provider = TracerProvider(resource=resource)

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        exporter = OTLPSpanExporter()
        _logger.info("Telemetria: exportando spans via OTLP para %s", endpoint)
    else:
        LOG_DIR.mkdir(exist_ok=True)
        exporter = ConsoleSpanExporter(
            out=open(TRACES_FILE, "a", encoding="utf-8")  # noqa: SIM115
        )
        _logger.info("Telemetria: exportando spans para %s", TRACES_FILE.resolve())

    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()
    _logger.info("OpenTelemetry ativo (FastAPI + httpx instrumentados).")
