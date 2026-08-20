import logging
from pathlib import Path
from typing import Any
from alberto.enums import AccessLevel
from alberto.research.fulltext import Resolver, ResolvedDocument
from alberto.research.models import PaperRecord
from curl_cffi import requests
from bs4 import BeautifulSoup
import PyPDF2
import io

logger = logging.getLogger(__name__)

MIRRORS = [
    "https://sci-hub.ren",
    # "https://sci-hub.st",  # exige ALTCHA (captcha)
    # "https://sci-hub.ru",  # certificado SSL inválido
]

class SciHubHttpResolver(Resolver):
    name = "scihub_http"
    priority = 90  # baixa prioridade: será tentado apenas se os legais falharem

    def resolve(self, record: PaperRecord, *, config: dict, storage_dir: Path) -> ResolvedDocument | None:
        if not record.doi:
            return None

        try:
            pdf_url = self._find_pdf_url(record.doi)
            if not pdf_url:
                logger.info(f"SciHubHttp: PDF não encontrado para {record.doi}")
                return None

            pdf_bytes = self._download_pdf(pdf_url)
            text = self._extract_text(pdf_bytes)
            if not text:
                logger.info(f"SciHubHttp: texto vazio para {record.doi}")
                return None

            return ResolvedDocument(
                access_level=AccessLevel.FULL_TEXT,
                source_type="PDF",
                text=text,
                provenance={"resolver": self.name, "doi": record.doi},
            )
        except Exception as e:
            logger.error(f"SciHubHttp falhou para {record.doi}: {type(e).__name__}: {e}")
            return None

    def _find_pdf_url(self, doi: str) -> str | None:
        for mirror in MIRRORS:
            try:
                resp = requests.get(f"{mirror}/{doi}", impersonate="chrome120", timeout=15)
                if resp.status_code != 200:
                    continue
                soup = BeautifulSoup(resp.text, "html.parser")

                # 1. Tenta iframe#pdf (padrão antigo)
                iframe = soup.find("iframe", id="pdf")
                if iframe and iframe.get("src"):
                    return self._normalize_pdf_url(iframe["src"])

                # 2. Qualquer iframe/embed/object com src contendo 'pdf'
                for tag in soup.find_all(["iframe", "embed", "object"]):
                    src = tag.get("src") or tag.get("data")
                    if src and ("pdf" in src.lower() or src.endswith(".pdf")):
                        return self._normalize_pdf_url(src)

                # 3. Links com 'download' ou 'pdf'
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if "pdf" in href.lower() or "download" in href.lower():
                        return self._normalize_pdf_url(href)

            except Exception as e:
                logger.debug(f"Erro ao acessar {mirror}: {e}")
                continue
        return None

    def _normalize_pdf_url(self, url: str) -> str:
        """Converte URLs relativas e remove fragmentos (#...)."""
        if url.startswith("//"):
            url = "https:" + url
        if "#" in url:
            url = url.split("#")[0]
        return url

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
