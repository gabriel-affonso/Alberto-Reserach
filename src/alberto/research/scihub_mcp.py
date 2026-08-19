from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

import requests

from alberto.enums import AccessLevel
from alberto.research.models import PaperRecord

logger = logging.getLogger(__name__)


class MCPSciHubResolver:
    priority = 20
    """Resolvedor que obtém PDF via servidor HTTP Sci-Hub."""

    name = "scihub_mcp"

    def __init__(self, server_url: str = "http://127.0.0.1:8000", timeout: int = 60):
        self.server_url = server_url
        self.timeout = timeout

    def resolve(
        self,
        record: PaperRecord,
        *,
        config: dict,
        storage_dir: Path,
    ) -> Any:
        doi = record.doi
        print(f"🔍 MCPSciHubResolver: CHAMADO para DOI {doi}")
        if not doi:
            return None

        enabled = config.get("enable_scihub_mcp", True)
        if not enabled:
            logger.debug("MCPSciHubResolver: desabilitado por configuração")
            return None

        logger.info(f"MCPSciHubResolver: tentando obter PDF para {doi} via MCP")

        try:
            response = requests.post(
                f"{self.server_url}/fetch",
                json={"doi": doi},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.warning(f"MCPSciHubResolver: chamada MCP falhou para {doi}: {exc}")
            return None

        if not payload.get("pdf"):
            logger.info(f"MCPSciHubResolver: MCP não retornou PDF para {doi}")
            return None

        # Decodifica base64
        try:
            pdf_bytes = base64.b64decode(payload["pdf"])
        except Exception as exc:
            logger.error(f"MCPSciHubResolver: erro ao decodificar PDF para {doi}: {exc}")
            return None

        # Importações tardias para evitar circular import
        from alberto.research.fulltext import (
            extract_pdf_text,
            sha256_bytes,
            store_pdf,
            validate_pdf_response,
            ResolvedDocument,
        )

        try:
            validate_pdf_response(pdf_bytes, "application/pdf")
        except Exception as exc:
            logger.warning(f"MCPSciHubResolver: PDF inválido para {doi}: {exc}")
            return None

        safe_doi = doi.replace("/", "_").replace(":", "_")
        source_id = f"scihub_mcp-{safe_doi[:30]}"

        try:
            local_path = store_pdf(pdf_bytes, storage_dir, source_id=source_id)
        except Exception as exc:
            logger.error(f"MCPSciHubResolver: falha ao persistir PDF para {doi}: {exc}")
            return None

        try:
            extracted = extract_pdf_text(local_path)
            extracted_text = extracted.text
            pages = extracted.pages
        except Exception as exc:
            logger.error(f"MCPSciHubResolver: falha ao extrair texto de {doi}: {exc}")
            extracted_text = ""
            pages = 0

        logger.info(f"MCPSciHubResolver: SUCESSO para {doi}, PDF salvo em {local_path}")

        return ResolvedDocument(
            access_level=AccessLevel.FULL_TEXT,
            source_type="PDF",
            text=extracted_text,
            uri=f"{self.server_url}/fetch?doi={doi}",
            local_path=local_path,
            checksum_sha256=sha256_bytes(pdf_bytes),
            pages=pages,
            provenance={
                "resolver": self.name,
                "source_url": self.server_url,
                "doi": doi,
            },
        )
