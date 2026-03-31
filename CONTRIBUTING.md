# Contribuindo com o RioB.us

## Requisitos de desenvolvimento

- Docker instalado e funcional.
- Nao usar runtime nativo como fluxo principal.

## Fluxo recomendado

1. Criar branch de feature.
2. Subir ambiente com `docker compose up --build`.
3. Implementar mudancas pequenas e focadas.
4. Executar testes (`pytest`).
5. Validar smoke em `/health` e `/status`.
6. Abrir PR com descricao de risco/regressao.

## Convencoes

- Preferir alteracoes incrementais e com baixo risco.
- Evitar refatoracoes amplas sem cobertura de testes.
- Manter retrocompatibilidade durante migracao para `src/`.
- Evitar mudancas de estilo em massa sem necessidade funcional.

## Testes

- Sempre executar ao menos os testes impactados.
- Para mudancas de runtime/infra, executar suite completa.

## Documentacao

Ao alterar comportamento funcional, atualizar:

- `README.md`
- `ARCHITECTURE.md` (quando a arquitetura mudar)
- exemplos de comando e variaveis de ambiente relevantes
- `.gitignore` e `.dockerignore` quando surgirem novos artefatos locais/runtime

## Commits separados (recomendado)

Use commits pequenos por tema para facilitar revisao e rollback.

Exemplo de estrategia:

1. `fix:` para correcao funcional isolada.
2. `refactor:` para migracao estrutural sem alterar comportamento.
3. `chore:` para hygiene/infra (`.gitignore`, `.dockerignore`, compose, Dockerfile).
4. `docs:` para documentacao (README/arquitetura/contribuicao).

Comandos uteis:

```powershell
# Revisar historico recente
git log --oneline -5

# Revisar um commit especifico
git show --stat <hash>

# Publicar commits locais para o remoto
git push origin main

# Aplicar commit especifico em outra branch
git cherry-pick <hash>
```
