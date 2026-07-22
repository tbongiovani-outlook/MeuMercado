# Changelog

Registro das mudanças implementadas (gerado automaticamente a cada merge na `main`).

<!-- novas-entradas -->
## 2026-07-22

- feat: modo escuro, atalhos de teclado, PWA/notificacoes e retentativa 429 (#17) (cd76ba1)

## 2026-07-21

- feat: link para abrir o anuncio no sistema nas telas que o referenciam (#15) (ebfc717)

## 2026-07-21

- feat: caixa de entrada unificada (para resolver hoje) (#13) (38f1ecd)

## 2026-07-21

- deps: atualiza dependencias e actions (apontamentos do Dependabot) (#11) (5c2014d)

## 2026-07-21

- test: suite pytest (cobertura 82%) + CI GitHub Actions (#1) (b756771)


## 2026-07-21 — Base

- Suíte de testes automatizados (pytest) com cobertura mínima de 80%
- Pipeline de CI: lint (Ruff), testes em Ubuntu/Windows/macOS, segurança (pip-audit + gitleaks)
- Automação deste CHANGELOG a cada merge na `main`
- Proteção CSRF, páginas de erro 404/500 e cache das telas de Anúncios/Promoções
- Fluxo de branches `main`/`develop` protegidas (PR + revisão do CODEOWNER)
