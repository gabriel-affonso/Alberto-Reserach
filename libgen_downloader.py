import re
import sys
import requests
from bs4 import BeautifulSoup

def get_libgen_pdf_url(doi: str) -> str | None:
    """Busca o link direto do PDF no Libgen Sci-Mag através do DOI."""
    search_url = f"https://libgen.is/scimag/?q={doi}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    try:
        response = requests.get(search_url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        mirror_link = None
        for a in soup.find_all('a', href=True):
            if 'library.lol' in a['href'] or 'libgen.rocks' in a['href']:
                mirror_link = a['href']
                break
        
        if not mirror_link:
            return None
            
        mirror_resp = requests.get(mirror_link, headers=headers, timeout=10)
        mirror_soup = BeautifulSoup(mirror_resp.text, 'html.parser')
        
        get_link = mirror_soup.find('a', string=re.compile(r'GET', re.I))
        if get_link and get_link.get('href'):
            return get_link['href']
            
    except Exception as e:
        print(f"Erro ao buscar o DOI {doi}: {e}", file=sys.stderr)
        
    return None

def download_paper_by_doi(doi: str, output_path: str = "artigo.pdf") -> bool:
    """Baixa o artigo PDF correspondente ao DOI."""
    print(f"Buscando DOI: {doi}...")
    pdf_url = get_libgen_pdf_url(doi)
    if not pdf_url:
        print(f"Artigo com DOI '{doi}' não foi encontrado no Libgen.")
        return False
        
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    res = requests.get(pdf_url, headers=headers, stream=True)
    
    if res.status_code == 200:
        with open(output_path, 'wb') as f:
            for chunk in res.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"Download concluído com sucesso: {output_path}")
        return True
        
    print(f"Falha ao baixar o arquivo (Status HTTP: {res.status_code}).")
    return False

if __name__ == "__main__":
    if len(sys.argv) > 1:
        target_doi = sys.argv[1]
        out_file = sys.argv[2] if len(sys.argv) > 2 else "artigo.pdf"
        download_paper_by_doi(target_doi, out_file)
    else:
        print("Uso: python libgen_downloader.py <DOI> [nome_arquivo.pdf]")
