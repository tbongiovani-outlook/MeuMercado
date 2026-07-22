# Changelog

Registro das mudanças implementadas (gerado automaticamente a cada merge na `main`).

<!-- novas-entradas -->
## 2026-07-22

- fix(ia): reforca regra anti-alucinacao de specs na descricao (926602a)
- fix(ia): descricao nao ecoa mais a instrucao do prompt (627ade0)
- feat: modelo de IA padrao passa a ser qwen2.5:3b (melhor PT-BR) (b96aae2)

## 2026-07-22

- feat: descricao IA com especificacoes tecnicas e hashtags; maxlength 10000 (4631b08)

## 2026-07-22

- fix: titulo IA nao termina com conector solto e prompt pede titulo mais curto (2fc9506)

## 2026-07-22

- fix: campo Descricao na tela de Publicar e titulo IA sem cortar palavra (5677cd0)

## 2026-07-22

- feat: formata resposta do assistente e resumo (markdown: negrito, listas, paragrafos) (7bf2118)

## 2026-07-22

- docs: marca titulo SEO, variacao de resposta e assistente como entregues (d379b5a)
- feat: mais 3 features com IA local (titulo SEO, variacao de resposta, assistente de vendas) (cb7a6b9)

## 2026-07-22

- docs: marca descricao, resumo do dia e resposta a reclamacao como entregues (7186504)
- feat: 3 novas features com IA local (descricao, resumo do dia, resposta a reclamacao) (6f8fbcb)

## 2026-07-22

- docs: adiciona backlog de features com IA local (Ollama) e central de ajuda no README (f564643)
- feat: pagina de Ajuda com guia de configuracao e ajuste do Ollama (569a03a)

## 2026-07-22

- docs: documenta sugestao de resposta com IA local (Ollama) no README (11f378e)
- feat: sugestao de resposta com IA local (Ollama) + toggle em Configuracao (0b8090f)

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
