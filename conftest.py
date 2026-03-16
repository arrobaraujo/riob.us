import sys
import os

# Garante que o diretório raiz do projeto está no sys.path
# para que os módulos locais sejam encontrados pelo pytest.
sys.path.insert(0, os.path.dirname(__file__))
