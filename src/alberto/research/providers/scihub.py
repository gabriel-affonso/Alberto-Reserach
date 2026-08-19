from alberto.enums import AccessLevel
from alberto.research.fulltext import Resolver, ResolvedDocument
from alberto.research.models import PaperRecord
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class SciHubResolver(Resolver):
    name = "scihub"
    priority = 10  # prioridade alta, tentar primeiro

    def resolve(self, record: PaperRecord, *, config: dict, storage_dir: Path) -> ResolvedDocument | None:
        """Tenta obter o texto completo via Sci-Hub."""
        if not record.doi:
            logger.debug(f"SciHubResolver: sem DOI para {record.title}")
            return None

        try:
            from alberto.research.scihub_integration import get_full_text_sync
            text = get_full_text_sync(record.doi)
            if text:
                return ResolvedDocument(
                    access_level=AccessLevel.FULL_TEXT,
                    source_type="PDF",
                    text=text,
                    provenance={"resolver": self.name, "doi": record.doi},
                )
            else:
                logger.info(f"SciHub não retornou texto para {record.doi}")
                return None
        except ImportError:
            logger.error("Módulo scihub_integration não encontrado. Verifique se o arquivo existe.")
            return None
        except Exception as e:
            logger.error(f"SciHub falhou para {record.doi}: {type(e).__name__}: {e}")
            return None
