@echo off
REM ===================================================================
REM  Meu Mercado - atalho para Windows (duplo clique)
REM  Executa o script PowerShell ignorando a politica de execucao.
REM ===================================================================
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0iniciar.ps1"
pause
