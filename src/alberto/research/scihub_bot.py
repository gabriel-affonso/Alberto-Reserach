import os
import asyncio
import logging
from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaDocument
import requests
import PyPDF2
import io

# Tenta carregar variáveis de ambiente de .env (se python-dotenv estiver instalado)
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
        self._handler_registered = False

    async def start(self):
        await self.client.start()
        self.bot_entity = await self.client.get_entity(BOT_USERNAME)
        logger.info(f"Conectado como {await self.client.get_me()}")

    async def stop(self):
        await self.client.disconnect()

    async def request_article(self, query: str, timeout: int = 60) -> bytes:
        """
        Envia uma consulta ao bot e retorna o conteúdo do PDF.
        Aguarda a mensagem que contém o documento ou URL, ignorando mensagens de texto.
        """
        if not self.client.is_connected():
            await self.start()

        await self.client.send_message(self.bot_entity, query)
        logger.info(f"Consulta enviada: {query}")

        # Define condição para mensagem útil: documento (PDF) ou texto com URL
        def is_article_message(msg) -> bool:
            return isinstance(msg.media, MessageMediaDocument) or ('http' in (msg.text or ''))

        # Aguarda a mensagem correta (ignorando mensagens como "I have this article!")
        response = await self._wait_for_response(timeout, condition=is_article_message)
        if response is None:
            raise TimeoutError(f"Sem resposta útil do bot após {timeout}s para: {query}")

        # Processa a mensagem
        if isinstance(response.media, MessageMediaDocument):
            logger.info("Documento recebido, baixando...")
            pdf_bytes = await self.client.download_media(response, file=bytes)
            return pdf_bytes
        else:
            # Tenta extrair URL do texto
            text = response.text or ''
            if 'http' in text:
                url = text.strip().split()[-1]
                logger.info(f"Baixando PDF da URL: {url}")
                return self._download_pdf(url)
            else:
                # Caso inesperado (não deveria ocorrer devido ao filtro)
                raise ValueError(f"Resposta inesperada: {text[:200]}")

    async def _wait_for_response(self, timeout: int, condition=None):
        """
        Espera por uma mensagem do bot que satisfaça a condição.
        A condição recebe o objeto Message e retorna True se for a desejada.
        Se nenhuma condição for fornecida, aceita qualquer mensagem.
        """
        if condition is None:
            condition = lambda msg: True

        response_event = asyncio.Event()
        response_message = None

        @self.client.on(events.NewMessage(from_users=self.bot_entity.id))
        async def handler(event):
            nonlocal response_message
            msg = event.message
            if condition(msg):
                response_message = msg
                response_event.set()

        self._handler_registered = True
        try:
            await asyncio.wait_for(response_event.wait(), timeout=timeout)
        finally:
            self.client.remove_event_handler(handler)
            self._handler_registered = False

        return response_message

    @staticmethod
    def _download_pdf(url: str) -> bytes:
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.content

    @staticmethod
    def extract_text_from_pdf(pdf_bytes: bytes) -> str:
        """Extrai texto de PDF usando PyPDF2."""
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
        text = ''
        for page in pdf_reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + '\n'
        return text
