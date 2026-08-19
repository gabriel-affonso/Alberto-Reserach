import os
import asyncio
import logging
from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaDocument
import requests
import PyPDF2
import io

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

API_ID = int(os.getenv('TG_API_ID', '123456'))
API_HASH = os.getenv('TG_API_HASH', 'your_api_hash')
SESSION_NAME = os.getenv('TG_SESSION_NAME', 'scihub_session')
BOT_USERNAME = os.getenv('SCIHUB_BOT_USERNAME', '@scihubot')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SciHubBotClient:
    def __init__(self):
        self.client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
        self.bot_entity = None

    async def start(self):
        await self.client.start()
        self.bot_entity = await self.client.get_entity(BOT_USERNAME)
        logger.info(f"Conectado como {await self.client.get_me()}")

    async def stop(self):
        await self.client.disconnect()

    async def request_article(self, query: str, timeout: int = 60) -> bytes:
        """
        Envia consulta ao bot e retorna o PDF.
        Captura mensagens de falha e retorna erro rapidamente.
        """
        if not self.client.is_connected():
            await self.start()

        await self.client.send_message(self.bot_entity, query)
        logger.info(f"Consulta enviada: {query}")

        # Espera por qualquer mensagem do bot que seja documento, URL ou falha
        response = await self._wait_for_response(timeout)
        if response is None:
            raise TimeoutError(f"Bot não respondeu em {timeout}s para: {query}")

        # Se for documento, baixa
        if isinstance(response.media, MessageMediaDocument):
            logger.info("Documento recebido, baixando...")
            return await self.client.download_media(response, file=bytes)

        text = response.text or ''
        # Se contém URL, baixa o PDF
        if 'http' in text:
            url = text.strip().split()[-1]
            logger.info(f"Baixando PDF da URL: {url}")
            return self._download_pdf(url)

        # Se for mensagem de falha, levanta erro
        raise ValueError(f"Bot respondeu com falha: {text[:200]}")

    async def _wait_for_response(self, timeout: int):
        """
        Aguarda uma mensagem que seja documento, URL ou falha.
        Ignora mensagens como 'I have this article!'.
        """
        response_event = asyncio.Event()
        response_message = None

        def is_terminal(msg) -> bool:
            if isinstance(msg.media, MessageMediaDocument):
                return True
            text = msg.text or ''
            if 'http' in text:
                return True
            lower = text.lower()
            failure_phrases = [
                'not found', 'not available', "don't have", 'do not have',
                'cannot find', 'cannot locate', 'no such article', 'error',
                'failed', 'unavailable', 'could not', 'unable to',
                'não encontrado', 'não tenho', 'não disponível'
            ]
            for phrase in failure_phrases:
                if phrase in lower:
                    return True
            return False

        @self.client.on(events.NewMessage(from_users=self.bot_entity.id))
        async def handler(event):
            nonlocal response_message
            msg = event.message
            if is_terminal(msg):
                response_message = msg
                response_event.set()

        try:
            await asyncio.wait_for(response_event.wait(), timeout=timeout)
        finally:
            self.client.remove_event_handler(handler)

        return response_message

    @staticmethod
    def _download_pdf(url: str) -> bytes:
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.content

    @staticmethod
    def extract_text_from_pdf(pdf_bytes: bytes) -> str:
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
        text = ''
        for page in pdf_reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + '\n'
        return text
