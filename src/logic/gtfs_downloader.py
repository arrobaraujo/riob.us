import os
import json
import time
import zipfile
import requests

GTFS_URL = os.environ.get(
    "GTFS_URL",
    "https://www.arcgis.com/sharing/rest/content/items/8ffe62ad3b2f42e49814bf941654ea6c/data"
)
GTFS_LOCAL_PATH = "gtfs/gtfs.zip"
GTFS_ETAG_PATH = "gtfs/.gtfs_etag"

def download_gtfs(max_retries=3, timeout=120):
    """
    Faz download do GTFS da API ArcGIS com suporte a cache HTTP.
    
    Tenta baixar o arquivo e salvar atomicamente. Se falhar após
    max_retries tentativas, usa o arquivo local se existir.
    """
    os.makedirs(os.path.dirname(GTFS_LOCAL_PATH), exist_ok=True)
    
    headers = {}
    etag_data = {}
    
    # Carrega ETag anterior se existir
    if os.path.exists(GTFS_ETAG_PATH) and os.path.exists(GTFS_LOCAL_PATH):
        try:
            with open(GTFS_ETAG_PATH, "r") as f:
                etag_data = json.load(f)
            if "etag" in etag_data:
                headers["If-None-Match"] = etag_data["etag"]
            if "last-modified" in etag_data:
                headers["If-Modified-Since"] = etag_data["last-modified"]
        except Exception as e:
            print(f"Aviso: Falha ao ler ETag cache: {e}")

    print(f"Verificando atualizações do GTFS em {GTFS_URL}...")
    
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(
                GTFS_URL, 
                headers=headers, 
                stream=True, 
                timeout=timeout
            )
            
            if response.status_code == 304:
                print("GTFS não foi modificado (304 Not Modified). Usando cache local.")
                return True
                
            response.raise_for_status()
            
            # Download atômico
            tmp_path = f"{GTFS_LOCAL_PATH}.tmp"
            with open(tmp_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    
            # Valida o ZIP antes de substituir
            if not zipfile.is_zipfile(tmp_path):
                raise ValueError("O arquivo baixado não é um ZIP válido")
                
            # Substitui arquivo
            if os.path.exists(GTFS_LOCAL_PATH):
                os.replace(tmp_path, GTFS_LOCAL_PATH)
            else:
                os.rename(tmp_path, GTFS_LOCAL_PATH)
                
            # Salva novos cabeçalhos ETag
            new_etag_data = {}
            if "etag" in response.headers:
                new_etag_data["etag"] = response.headers["etag"]
            if "last-modified" in response.headers:
                new_etag_data["last-modified"] = response.headers["last-modified"]
                
            if new_etag_data:
                with open(GTFS_ETAG_PATH, "w") as f:
                    json.dump(new_etag_data, f)
                    
            print(f"Download do GTFS concluído com sucesso ({os.path.getsize(GTFS_LOCAL_PATH)} bytes).")
            return True
            
        except Exception as e:
            print(f"Tentativa {attempt}/{max_retries} falhou: {e}")
            if os.path.exists(f"{GTFS_LOCAL_PATH}.tmp"):
                try:
                    os.remove(f"{GTFS_LOCAL_PATH}.tmp")
                except Exception:
                    pass
            if attempt < max_retries:
                delay = 2 ** attempt
                print(f"Aguardando {delay}s antes de tentar novamente...")
                time.sleep(delay)
            
    print("ERRO: Falha ao atualizar o GTFS após múltiplas tentativas.")
    if os.path.exists(GTFS_LOCAL_PATH):
        print("Continuando com o arquivo GTFS local existente.")
        return True
        
    print("CRÍTICO: Nenhum arquivo GTFS local disponível!")
    return False
