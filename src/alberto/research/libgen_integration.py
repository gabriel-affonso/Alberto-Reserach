import asyncio
import io
import logging
import re
from typing import Optional

import requests
from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

logger = logging.getLogger(__name__)


class LibgenResolverError(Exception):
    """Erro base para falhas no resolver LibGen/Sci-Hub."""


class LibgenDownloader:
    """Faz o download de PDFs a partir de mirrors do Sci-Hub e LibGen."""

    SCIHUB_MIRRORS = [
        "https://sci-hub.ren",
        "https://sci-hub.st",
        "https://sci-hub.ru",
    ]

    LIBGEN_URL = "https://libgen.is/scimag/"

    def __init__(self, timeout: int = 25, user_agent: str = "AlbertoResearch/1.0"):
        self.timeout = timeout
        self.headers = {"User-Agent": user_agent}

    def fetch_pdf_bytes(self, doi: str) -> bytes:
        """
        Busca o PDF correspondente ao DOI e retorna seus bytes.
        Lança LibgenResolverError se não conseguir.
        """
        # 1. Tenta Sci-Hub
        for mirror in self.SCIHUB_MIRRORS:
            try:
                pdf_url = self._find_pdf_url_scihub(mirror, doi)
                if pdf_url:
                    pdf_bytes = self._download_pdf(pdf_url)
                    if self._is_valid_pdf(pdf_bytes):
                        return pdf_bytes
            except Exception as e:
                logger.debug(f"Sci-Hub mirror {mirror} falhou: {e}")

        # 2. Tenta LibGen
        try:
            pdf_url = self._find_pdf_url_libgen(doi)
            if pdf_url:
                pdf_bytes = self._download_pdf(pdf_url)
                if self._is_valid_pdf(pdf_bytes):
                    return pdf_bytes
        except Exception as e:
            logger.debug(f"LibGen falhou: {e}")

        raise LibgenResolverError(f"Não foi possível obter PDF para {doi} em nenhum mirror")

    def _find_pdf_url_scihub(self, mirror: str, doi: str) -> Optional[str]:
        """Extrai a URL do PDF da página do Sci-Hub usando curl_cffi."""
        url = f"{mirror.rstrip('/')}/{doi}"
        try:
            resp = cffi_requests.get(url, impersonate="chrome120", timeout=self.timeout)
            if resp.status_code != 200:
                return None
            soup = BeautifulSoup(resp.text, "html.parser")
            # Procura embed/iframe com src contendo .pdf
            for tag in soup.find_all(["embed", "iframe", "object"]):
                src = tag.get("src") or tag.get("data")
                if src and "pdf" in src.lower():
                    if src.startswith("//"):
                        return "https:" + src
                    elif src.startswith("/"):
                        return mirror + src
                    return src
            # Procura links com 'pdf' no href
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "pdf" in href.lower():
                    if href.startswith("//"):
                        return "https:" + href
                    elif href.startswith("/"):
                        return mirror + href
                    return href
        except Exception as e:
            logger.debug(f"Erro ao acessar {url}: {e}")
        return None

    def _find_pdf_url_libgen(self, doi: str) -> Optional[str]:
        """Tenta encontrar o PDF no LibGen usando a API de busca."""
        try:
            # Exemplo: https://libgen.is/scimag/?doi=10.1038/nature12373
            search_url = f"{self.LIBGEN_URL}?doi={doi}"
            resp = requests.get(search_url, headers=self.headers, timeout=self.timeout)
            if resp.status_code != 200:
                return None
            soup = BeautifulSoup(resp.text, "html.parser")
            # Procura link para a página do arquivo
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "book" in href or "article" in href or "download" in href:
                    # Constrói URL absoluta
                    detail_url = href if href.startswith("http") else f"https://libgen.is{href}"
                    pdf_url = self._get_libgen_download_link(detail_url)
                    if pdf_url:
                        return pdf_url
        except Exception as e:
            logger.debug(f"Erro na busca LibGen: {e}")
        return None

    def _get_libgen_download_link(self, detail_url: str) -> Optional[str]:
        """Acessa a página de detalhe e extrai o link de download."""
        try:
            resp = requests.get(detail_url, headers=self.headers, timeout=self.timeout)
            if resp.status_code != 200:
                return None
            soup = BeautifulSoup(resp.text, "html.parser")
            # Procura links com 'download' ou 'pdf'
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "download" in href.lower() or href.lower().endswith(".pdf"):
                    if href.startswith("//"):
                        return "https:" + href
                    elif href.startswith("/"):
                        return "https://libgen.is" + href
                    return href
        except Exception as e:
            logger.debug(f"Erro ao acessar detalhe LibGen: {e}")
        return None

    def _download_pdf(self, pdf_url: str) -> bytes:
        # Tenta primeiro com curl_cffi (para sites com TLS fingerprinting)
        try:
            resp = cffi_requests.get(pdf_url, impersonate="chrome120", timeout=self.timeout)
            if resp.status_code == 200:
                return resp.content
        except Exception:
            pass
        # Fallback com requests padrão
        resp = requests.get(pdf_url, headers=self.headers, timeout=self.timeout)
        resp.raise_for_status()
        return resp.content

    def _is_valid_pdf(self, data: bytes) -> bool:
        return data.startswith(b"%PDF") and len(data) > 1000


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """Extrai texto de bytes de PDF usando pypdf."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    return "\n".join(pages)


async def get_full_text_via_libgen(doi: str) -> str:
    """Versão assíncrona: roda a busca em thread separada e extrai texto."""
    loop = asyncio.get_running_loop()
    downloader = LibgenDownloader()
    pdf_bytes = await loop.run_in_executor(None, downloader.fetch_pdf_bytes, doi)
    text = await loop.run_in_executor(None, extract_text_from_pdf_bytes, pdf_bytes)
    return text


def get_full_text_sync(doi: str) -> str:
    """Versão síncrona para uso em resolvedores que não são assíncronos."""
    return asyncio.run(get_full_text_via_libgen(doi))
