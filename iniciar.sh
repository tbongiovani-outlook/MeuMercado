#!/usr/bin/env bash
# =====================================================================
#  Meu Mercado - inicializador para macOS / Linux
#  Uso:  bash iniciar.sh    (ou ./iniciar.sh apos: chmod +x iniciar.sh)
# =====================================================================
set -e
cd "$(dirname "$0")"

echo "== Meu Mercado =="

# 1) Verifica se o Python esta instalado
if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "Python nao encontrado. Instale em https://www.python.org/downloads/"
    exit 1
fi

# 2) Cria o ambiente virtual (apenas na primeira vez)
if [ ! -d ".venv" ]; then
    echo "Criando ambiente virtual..."
    "$PY" -m venv .venv
fi

# 3) Ativa o ambiente virtual
# shellcheck disable=SC1091
source .venv/bin/activate

# 4) Instala/atualiza as dependencias
echo "Instalando dependencias..."
python -m pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# 5) Garante o arquivo .env com uma chave de sessao aleatoria
if [ ! -f ".env" ]; then cp .env.example .env; fi
if ! grep -q "APP_SECRET_KEY=[^[:space:]]" .env; then
    KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
    python - "$KEY" <<'PYEOF'
import sys, re, pathlib
key = sys.argv[1]
p = pathlib.Path(".env")
text = p.read_text()
if re.search(r'^APP_SECRET_KEY=', text, flags=re.M):
    text = re.sub(r'^APP_SECRET_KEY=.*$', f'APP_SECRET_KEY={key}', text, flags=re.M)
else:
    text = text.rstrip("\n") + f"\nAPP_SECRET_KEY={key}\n"
p.write_text(text)
PYEOF
fi

# 5.5) IA local opcional (Ollama) - so quando MM_COM_IA=1
if [ "$MM_COM_IA" = "1" ]; then
    MODELO="${MM_IA_MODELO:-llama3.2:3b}"
    if ! command -v ollama >/dev/null 2>&1; then
        echo "Instalando a IA local (Ollama) - opcional..."
        if command -v brew >/dev/null 2>&1; then
            brew install ollama || echo "Falha ao instalar o Ollama via Homebrew."
        else
            curl -fsSL https://ollama.com/install.sh | sh || echo "Falha ao instalar o Ollama."
        fi
    fi
    if command -v ollama >/dev/null 2>&1; then
        (ollama serve >/dev/null 2>&1 &) || true
        sleep 2
        echo "Baixando o modelo $MODELO (uma vez)..."
        ollama pull "$MODELO" || echo "Falha ao baixar o modelo $MODELO."
        echo "IA local pronta. Ative em Configuracao > IA local."
    fi
fi

# 6) Abre o navegador (apos um instante) e inicia o aplicativo
(
    sleep 2
    if command -v open >/dev/null 2>&1; then open http://127.0.0.1:8000
    elif command -v xdg-open >/dev/null 2>&1; then xdg-open http://127.0.0.1:8000
    fi
) &
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
