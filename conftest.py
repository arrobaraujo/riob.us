import sys
import os

# Garante que o diretório raiz do projeto está no sys.path
# para que os módulos locais sejam encontrados pelo pytest.
sys.path.insert(0, os.path.dirname(__file__))

# Antecipa a migração para pacote src sem quebrar imports atuais.
src_path = os.path.join(os.path.dirname(__file__), "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)
