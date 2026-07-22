# =====================================================================
#  Meu Mercado - Instalador automatico (Windows)
#  Faz tudo sozinho: instala o Python (se faltar), baixa o aplicativo,
#  prepara o ambiente, cria um atalho e abre o site.
#
#  Nao precisa de permissao de administrador (instala so para o usuario).
# =====================================================================
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Owner  = "tbongiovani-outlook"
$Repo   = "MeuMercado"
$Branch = "main"
$ZipUrl = "https://github.com/$Owner/$Repo/archive/refs/heads/$Branch.zip"
$Dest   = Join-Path $env:LOCALAPPDATA $Repo
$Porta  = 8000
$Url    = "http://127.0.0.1:$Porta"

function Escrever($txt, $cor = "Gray") { Write-Host $txt -ForegroundColor $cor }

Escrever "" 
Escrever "==================================================" "Cyan"
Escrever "        Instalador do Meu Mercado" "Cyan"
Escrever "==================================================" "Cyan"

function Atualizar-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

function Resolver-Python {
    # Retorna o caminho de um python.exe versao >= 3.10, ou $null.
    $cands = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try { $cands += (& py -3 -c "import sys;print(sys.executable)" 2>$null) } catch {}
    }
    foreach ($n in "python", "python3") {
        $c = Get-Command $n -ErrorAction SilentlyContinue
        if ($c) { $cands += $c.Source }
    }
    $cands += (Get-ChildItem "$env:LocalAppData\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue | ForEach-Object FullName)
    foreach ($exe in ($cands | Select-Object -Unique)) {
        if ($exe -and (Test-Path $exe)) {
            try {
                $v = & $exe -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
                if ($v -match "^\d+\.(\d+)$" -and [int]$Matches[1] -ge 10) { return $exe }
            } catch {}
        }
    }
    return $null
}

function Instalar-Python {
    Escrever "Python nao encontrado. Instalando (isso pode levar alguns minutos)..." "Yellow"
    $wg = Get-Command winget -ErrorAction SilentlyContinue
    if ($wg) {
        try {
            winget install --id Python.Python.3.12 -e --silent --scope user `
                --accept-package-agreements --accept-source-agreements | Out-Null
        } catch { Escrever "winget falhou, tentando o instalador oficial..." "Yellow" }
    }
    Atualizar-Path
    if (-not (Resolver-Python)) {
        $url = "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"
        $inst = Join-Path $env:TEMP "python-setup.exe"
        Escrever "Baixando o Python..." 
        Invoke-WebRequest -UseBasicParsing $url -OutFile $inst
        Escrever "Instalando o Python (silencioso)..."
        Start-Process -Wait -FilePath $inst -ArgumentList `
            "/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1"
        Atualizar-Path
    }
}

function Instalar-Ollama {
    # IA local opcional (Ollama). So roda se o usuario pedir: $env:MM_COM_IA = "1".
    # Silencioso e sem admin. O app funciona sem isso (cai na sugestao por palavras-chave).
    $modelo = if ($env:MM_IA_MODELO) { $env:MM_IA_MODELO } else { "llama3.2:3b" }
    Escrever "Instalando a IA local (Ollama) - opcional, pode baixar ~2 GB..." "Yellow"
    if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
        $wg = Get-Command winget -ErrorAction SilentlyContinue
        if ($wg) {
            try {
                winget install --id Ollama.Ollama -e --silent `
                    --accept-package-agreements --accept-source-agreements | Out-Null
            } catch { Escrever "winget falhou, tentando o instalador oficial do Ollama..." "Yellow" }
        }
        Atualizar-Path
        if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
            $ollamaExe = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
            if (-not (Test-Path $ollamaExe)) {
                $inst = Join-Path $env:TEMP "OllamaSetup.exe"
                try {
                    Invoke-WebRequest -UseBasicParsing "https://ollama.com/download/OllamaSetup.exe" -OutFile $inst
                    Start-Process -Wait -FilePath $inst -ArgumentList "/VERYSILENT", "/NORESTART"
                    Atualizar-Path
                } catch { Escrever "Nao foi possivel instalar o Ollama automaticamente." "Red"; return }
            }
        }
    }
    $ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source
    if (-not $ollama) { $ollama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe" }
    if (Test-Path $ollama) {
        Escrever "Baixando o modelo $modelo (uma vez)..."
        try { & $ollama pull $modelo } catch { Escrever "Falha ao baixar o modelo $modelo." "Yellow" }
        Escrever "IA local pronta. Ative em Configuracao > IA local." "Green"
    }
}

# ---------------------------------------------------------------------
# 1) Garante o Python
# ---------------------------------------------------------------------
$py = Resolver-Python
if (-not $py) {
    Instalar-Python
    $py = Resolver-Python
}
if (-not $py) {
    Escrever "Nao foi possivel instalar o Python automaticamente." "Red"
    Escrever "Instale manualmente em https://www.python.org/downloads/ (marque 'Add to PATH') e rode de novo." "Red"
    Read-Host "Pressione Enter para sair"
    exit 1
}
Escrever "Python OK: $py" "Green"

# ---------------------------------------------------------------------
# 2) Baixa o aplicativo (preserva .env e banco em atualizacoes)
# ---------------------------------------------------------------------
Escrever "Baixando o aplicativo..."
$zip = Join-Path $env:TEMP "MeuMercado.zip"
Invoke-WebRequest -UseBasicParsing $ZipUrl -OutFile $zip
$tmp = Join-Path $env:TEMP ("MM_" + [guid]::NewGuid().ToString("N"))
Expand-Archive -Path $zip -DestinationPath $tmp -Force
$raiz = Get-ChildItem $tmp -Directory | Select-Object -First 1
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
Copy-Item -Path (Join-Path $raiz.FullName "*") -Destination $Dest -Recurse -Force
Remove-Item $zip, $tmp -Recurse -Force -ErrorAction SilentlyContinue
Escrever "Aplicativo em: $Dest" "Green"

# ---------------------------------------------------------------------
# 3) Ambiente virtual + dependencias
# ---------------------------------------------------------------------
$venvPy = Join-Path $Dest ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Escrever "Criando ambiente virtual..."
    & $py -m venv (Join-Path $Dest ".venv")
}
Escrever "Instalando dependencias..."
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install --quiet -r (Join-Path $Dest "requirements.txt")

# ---------------------------------------------------------------------
# 3.5) IA local opcional (Ollama) - so quando MM_COM_IA=1
# ---------------------------------------------------------------------
if ($env:MM_COM_IA -eq "1") {
    try { Instalar-Ollama } catch { Escrever "IA local ignorada (opcional): $_" "Yellow" }
}

# ---------------------------------------------------------------------
# 4) Arquivo .env com chave de sessao aleatoria
# ---------------------------------------------------------------------
$envPath = Join-Path $Dest ".env"
if (-not (Test-Path $envPath)) { Copy-Item (Join-Path $Dest ".env.example") $envPath }
$conteudo = Get-Content $envPath -Raw
if ($conteudo -notmatch "APP_SECRET_KEY=\S" -or $conteudo -match "troque-por-uma-chave") {
    $chave = & $venvPy -c "import secrets;print(secrets.token_urlsafe(48))"
    if ($conteudo -match "APP_SECRET_KEY=") {
        (Get-Content $envPath) -replace "^APP_SECRET_KEY=.*", "APP_SECRET_KEY=$chave" | Set-Content $envPath
    } else {
        Add-Content $envPath "APP_SECRET_KEY=$chave"
    }
}

# ---------------------------------------------------------------------
# 5) Atalho na area de trabalho para reabrir depois
# ---------------------------------------------------------------------
try {
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "Meu Mercado.lnk"))
    $lnk.TargetPath = Join-Path $Dest "iniciar.bat"
    $lnk.WorkingDirectory = $Dest
    $lnk.Description = "Abrir o Meu Mercado"
    $lnk.Save()
    Escrever "Atalho 'Meu Mercado' criado na area de trabalho." "Green"
} catch { }

# ---------------------------------------------------------------------
# 6) Inicia o servidor e abre o site
# ---------------------------------------------------------------------
Escrever "Iniciando o aplicativo..." "Green"
Start-Process -FilePath $venvPy `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$Porta" `
    -WorkingDirectory $Dest -WindowStyle Minimized

# Espera o servidor responder antes de abrir o navegador
$ok = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        Invoke-WebRequest -UseBasicParsing "$Url" -TimeoutSec 2 | Out-Null
        $ok = $true; break
    } catch { }
}
Start-Process $Url

Escrever "" 
Escrever "==================================================" "Cyan"
Escrever " Pronto! O Meu Mercado esta rodando em $Url" "Green"
Escrever " Para abrir de novo, use o atalho 'Meu Mercado'." "Gray"
Escrever "==================================================" "Cyan"
if (-not $ok) {
    Escrever "Se o site nao abrir, aguarde alguns segundos e acesse $Url" "Yellow"
}
if ($env:MM_COM_IA -ne "1") {
    Escrever " Dica: para sugestoes de resposta com IA local (gratis), instale o Ollama" "Gray"
    Escrever "       (https://ollama.com) e ative em Configuracao > IA local." "Gray"
}
