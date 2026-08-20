import logging
from pathlib import Path
from typing import Any

from alberto.enums import AccessLevel
from alberto.research.fulltext import Resolver, ResolvedDocument
from alberto.research.models import PaperRecord
from alberto.research.libgen_integration import get_full_text_sync, LibgenResolverError

logger = logging.getLogger(__name__)


class LibgenResolver(Resolver):
    """Resolvedor que tenta obter o texto completo via LibGen/Sci-Hub/Anna's Archive."""
    name = "libgen"
    priority = 70  # depois dos principais legais, antes do scihub_http (90)

    def resolve(self, record: PaperRecord, *, config: dict, storage_dir: Path) -> ResolvedDocument | None:
        if not record.doi:
            logger.debug(f"LibgenResolver: sem DOI para {record.title}")
            return None

        try:
            text = get_full_text_sync(record.doi)
            if text:
                return ResolvedDocument(
                    access_level=AccessLevel.FULL_TEXT,
                    source_type="PDF",
                    text=text,
                    provenance={"resolver": self.name, "doi": record.doi},
                )
            else:
                logger.info(f"LibgenResolver: texto vazio para {record.doi}")
                return None
        except LibgenResolverError as e:
            logger.warning(f"LibgenResolver falhou para {record.doi}: {e}")
            return None
        except Exception as e:
            logger.error(f"LibgenResolver erro inesperado para {record.doi}: {type(e).__name__}: {e}")
            return None
