import asyncio
import io
import re
from urllib.parse import urljoin
import requests
import urllib3
from bs4 import BeautifulSoup
from pypdf import PdfReader

# Desativa alertas de requisições HTTPS não verificadas (SSL bypass)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class LibgenResolverError(Exception):
    """Exceção para falhas na busca ou download via Libgen."""
    pass


LIBGEN_MIRRORS = [
    "https://libgen.rs/scimag/?q=",
    "https://libgen.st/scimag/?q=",
    "https://libgen.is/scimag/?q=",
    "https://libgen.li/index.php?req=",
]


def get_pdf_bytes_from_libgen(doi: str) -> bytes:
    """
    Consulta espelhos do Libgen Sci-Mag via DOI, acessa o mirror de download e extrai os bytes do PDF.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    response = None
    last_error = None

    # 1. Consulta nos espelhos
    for base_url in LIBGEN_MIRRORS:
        search_url = f"{base_url}{doi}"
        try:
            resp = requests.get(search_url, headers=headers, timeout=10, verify=False)
            if resp.status_code == 200 and ("library.lol" in resp.text or "libgen" in resp.text or "GET" in resp.text):
                response = resp
                break
        except requests.RequestException as err:
            last_error = err
            continue

    if not response:
        raise LibgenResolverError(
            f"Falha ao conectar a todos os mirrors do Libgen. Último erro: {last_error}"
        )

    soup = BeautifulSoup(response.text, "html.parser")

    # 2. Coleta mirrors e resolve URLs relativas
    mirror_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if any(m in href for m in ["library.lol", "libgen.rocks", "sci-hub", "download.php"]):
            full_mirror_url = urljoin(response.url, href)
            mirror_links.append(full_mirror_url)

    if not mirror_links:
        raise LibgenResolverError(f"Artigo não encontrado no Libgen para o DOI: {doi}")

    # Prioriza library.lol se disponível
    mirror_links.sort(key=lambda url: 0 if "library.lol" in url else 1)
    mirror_url = mirror_links[0]

    # 3. Acessa a página do mirror
    try:
        mirror_resp = requests.get(mirror_url, headers=headers, timeout=15, verify=False)
        mirror_resp.raise_for_status()
    except Exception as exc:
        raise LibgenResolverError(f"Erro ao acessar mirror {mirror_url}: {exc}") from exc

    mirror_soup = BeautifulSoup(mirror_resp.text, "html.parser")
    get_link = mirror_soup.find("a", string=re.compile(r"GET", re.I)) or mirror_soup.find("a", href=re.compile(r"\.pdf", re.I))

    if not get_link or not get_link.get("href"):
        raise LibgenResolverError("Não foi possível localizar o link de download direto (.pdf) no mirror.")

    # Converte URL relativa do PDF em URL absoluta completa
    download_url = urljoin(mirror_resp.url, get_link["href"])

    # 4. Efetua o download do arquivo PDF
    try:
        pdf_resp = requests.get(download_url, headers=headers, timeout=25, verify=False)
        pdf_resp.raise_for_status()
    except Exception as exc:
        raise LibgenResolverError(f"Erro no download do arquivo PDF: {exc}") from exc

    content = pdf_resp.content
    if not content.startswith(b"%PDF"):
        raise LibgenResolverError("O arquivo baixado do Libgen não possui um cabeçalho PDF válido.")

    return content


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """Extrai texto dos bytes do PDF usando pypdf."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    page_texts: list[str] = []
    for idx, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        page_texts.append(f"--- PAGE {idx} ---\n{text.strip()}")

    combined = "\n\n".join(page_texts).strip()
    if len("".join(combined.split())) < 20:
        raise LibgenResolverError("Falha ao extrair texto do PDF baixado.")
    return combined


async def get_full_text_via_libgen(doi_or_title: str) -> str:
    """
    Obtém o texto completo do artigo buscando via Libgen Sci-Mag com resolução absoluta de URLs.
    """
    loop = asyncio.get_running_loop()
    pdf_bytes = await loop.run_in_executor(None, get_pdf_bytes_from_libgen, doi_or_title)
    text = await loop.run_in_executor(None, extract_text_from_pdf_bytes, pdf_bytes)
    return text


# Aliases para retrocompatibilidade
get_full_text_via_scihub = get_full_text_via_libgen


def get_full_text_sync(doi_or_title: str) -> str:
    """Versão síncrona para uso em contextos sem asyncio."""
    return asyncio.run(get_full_text_via_libgen(doi_or_title))
