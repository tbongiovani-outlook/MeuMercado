# =====================================================================
#  Meu Mercado - inicializador para Windows (PowerShell)
#  Uso: clique com o botao direito e "Executar com PowerShell"
#       ou execute:  .\iniciar.ps1
# =====================================================================
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "== Meu Mercado ==" -ForegroundColor Cyan

# 1) Verifica se o Python esta instalado
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $python) {
    Write-Host "Python nao encontrado." -ForegroundColor Red
    Write-Host "Instale em https://www.python.org/downloads/ e marque 'Add Python to PATH'."
    Read-Host "Pressione Enter para sair"
    exit 1
}

# 2) Cria o ambiente virtual (apenas na primeira vez)
if (-not (Test-Path ".venv")) {
    Write-Host "Criando ambiente virtual..."
    & $python.Source -m venv .venv
}

# 3) Ativa o ambiente virtual
. .\.venv\Scripts\Activate.ps1

# 4) Instala/atualiza as dependencias
Write-Host "Instalando dependencias..."
python -m pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# 5) Garante o arquivo .env com uma chave de sessao aleatoria
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
$envContent = Get-Content ".env" -Raw
if ($envContent -notmatch "APP_SECRET_KEY=\S") {
    $key = python -c "import secrets; print(secrets.token_urlsafe(48))"
    if ($envContent -match "APP_SECRET_KEY=") {
        (Get-Content ".env") -replace '^APP_SECRET_KEY=.*', "APP_SECRET_KEY=$key" | Set-Content ".env"
    } else {
        Add-Content ".env" "APP_SECRET_KEY=$key"
    }
}

# 6) Abre o navegador e inicia o aplicativo
Write-Host "Abrindo http://127.0.0.1:8000 ..." -ForegroundColor Green
Start-Process "http://127.0.0.1:8000"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
