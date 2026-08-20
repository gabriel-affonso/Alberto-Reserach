import logging
import re
import io
from pathlib import Path
from typing import Any

from alberto.enums import AccessLevel
from alberto.research.fulltext import Resolver, ResolvedDocument
from alberto.research.models import PaperRecord
from curl_cffi import requests
from bs4 import BeautifulSoup
import PyPDF2

logger = logging.getLogger(__name__)

MIRROR = "https://www.tesble.com"
PDF_LINK_RE = re.compile(r'(https?://[^"\'\s]+?\.pdf[^"\'\s]*)', re.IGNORECASE)
NOT_FOUND_MARKER = "no matching proxies found"


class TesbleResolver(Resolver):
    name = "tesble"
    priority = 80  # ajuste conforme desejado

    def resolve(self, record: PaperRecord, *, config: dict, storage_dir: Path) -> ResolvedDocument | None:
        if not record.doi:
            return None

        try:
            pdf_url = self._find_pdf_url(record.doi)
            if not pdf_url:
                logger.info(f"Tesble: PDF não encontrado para {record.doi}")
                return None

            pdf_bytes = self._download_pdf(pdf_url)
            if not pdf_bytes.startswith(b"%PDF"):
                logger.warning(f"Tesble: arquivo baixado não é PDF para {record.doi}")
                return None

            text = self._extract_text(pdf_bytes)
            if not text:
                logger.info(f"Tesble: texto vazio para {record.doi}")
                return None

            return ResolvedDocument(
                access_level=AccessLevel.FULL_TEXT,
                source_type="PDF",
                text=text,
                provenance={"resolver": self.name, "doi": record.doi},
            )
        except Exception as e:
            logger.error(f"Tesble falhou para {record.doi}: {type(e).__name__}: {e}")
            return None

    def _find_pdf_url(self, doi: str) -> str | None:
        url = f"{MIRROR}/{doi}"
        try:
            resp = requests.get(url, impersonate="chrome120", timeout=20)
            if resp.status_code != 200:
                return None
            html = resp.text
            if NOT_FOUND_MARKER in html:
                return None
            match = PDF_LINK_RE.search(html)
            if match:
                return match.group(1)
            # fallback com BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a", href=True):
                if "pdf" in a["href"].lower():
                    return a["href"]
        except Exception as e:
            logger.debug(f"Erro ao acessar {url}: {e}")
        return None

    def _download_pdf(self, url: str) -> bytes:
        resp = requests.get(url, impersonate="chrome120", timeout=30)
        resp.raise_for_status()
        return resp.content

    def _extract_text(self, pdf_bytes: bytes) -> str:
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
        text = ""
        for page in pdf_reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        return text
