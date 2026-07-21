# Changelog

Registro das mudanças implementadas (gerado automaticamente a cada merge na `main`).

<!-- novas-entradas -->

## 2026-07-21 — Base

- Suíte de testes automatizados (pytest) com cobertura mínima de 80%
- Pipeline de CI: lint (Ruff), testes em Ubuntu/Windows/macOS, segurança (pip-audit + gitleaks)
- Automação deste CHANGELOG a cada merge na `main`
- Proteção CSRF, páginas de erro 404/500 e cache das telas de Anúncios/Promoções
- Fluxo de branches `main`/`develop` protegidas (PR + revisão do CODEOWNER)
