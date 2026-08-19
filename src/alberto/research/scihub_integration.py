import asyncio
from .scihub_bot import SciHubBotClient

async def get_full_text_via_scihub(doi_or_title: str) -> str:
    """
    Obtém o texto completo de um artigo usando o bot do Sci-Hub.
    Retorna uma string com o texto extraído do PDF.
    """
    client = SciHubBotClient()
    try:
        await client.start()
        pdf_bytes = await client.request_article(doi_or_title)
        text = client.extract_text_from_pdf(pdf_bytes)
        return text
    finally:
        await client.stop()

def get_full_text_sync(doi_or_title: str) -> str:
    """Versão síncrona para uso em contextos sem asyncio."""
    return asyncio.run(get_full_text_via_scihub(doi_or_title))
