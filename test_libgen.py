import asyncio
import sys
from pathlib import Path

# Adiciona a pasta src ao path para localizar o módulo
sys.path.insert(0, str(Path(__file__).parent / "src"))

from alberto.research.scihub_integration import get_full_text_via_libgen

async def main():
    # DOI de teste público (ex: artigo do Nature)
    test_doi = "10.1038/nature12373"
    
    print(f"🔍 Testando busca para o DOI: {test_doi}...")
    
    try:
        texto = await get_full_text_via_libgen(test_doi)
        print("\n✅ Download e extração concluídos com sucesso!")
        print(f"📄 Total de caracteres extraídos: {len(texto)}")
        print("\n--- Trecho inicial do artigo ---")
        print(texto[:500])
        print("\n--------------------------------")
    except Exception as e:
        print(f"\n❌ Falha no teste: {e}")

if __name__ == "__main__":
    asyncio.run(main())
