@echo off
title Instalador do Meu Mercado
echo.
echo  Instalando o Meu Mercado. Isso pode levar alguns minutos...
echo  (Se aparecer um aviso do Windows, clique em "Mais informacoes" e "Executar assim mesmo".)
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; iex ((New-Object Net.WebClient).DownloadString('https://raw.githubusercontent.com/tbongiovani-outlook/MeuMercado/main/instalar.ps1'))"
echo.
echo  Se o site nao abrir sozinho, acesse: http://127.0.0.1:8000
echo.
pause
