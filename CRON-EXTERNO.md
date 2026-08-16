# 🔁 Atualização frequente do GitHub Pages (agendador externo)

O GitHub Actions agenda workflows por cron **no mínimo a cada 5 min** e, mesmo
assim, de forma *best-effort*: execuções agendadas podem atrasar vários minutos
ou **simplesmente não acontecer** (observado neste projeto em 15/08/2026 —
nenhuma execução agendada disparou em mais de 40 minutos, enquanto `push` e
`workflow_dispatch` disparavam na hora).

Para atualizações **confiáveis a cada 2 minutos** (ou até 1 min), use um
agendador externo gratuito que chama o endpoint de `workflow_dispatch` do GitHub.
Este repositório é **público**, então os minutos do Actions usados são gratuitos.

## Passo 1 — criar um token do GitHub

1. GitHub → avatar → **Settings** → **Developer settings** → **Fine-grained
   tokens** → **Generate new token**.
2. **Repository access:** *Only select repositories* → `halleybr/livebetscanner`.
3. **Permissions → Repository permissions → Actions:** *Read and write*.
4. Copie o token (ele só aparece uma vez).

> Alternativa: um *classic token* com o escopo `workflow` também funciona.

## Passo 2 — criar o job no cron-job.org

1. Crie uma conta grátis em **cron-job.org** (plano grátis permite intervalo
   a partir de 1 minuto).
2. **Create cronjob** com:
   - **URL:**
     ```
     https://api.github.com/repos/halleybr/livebetscanner/actions/workflows/pages.yml/dispatches
     ```
   - **Request method:** `POST`
   - **Custom headers:**
     ```
     Authorization: Bearer <SEU_TOKEN>
     Accept: application/vnd.github+json
     Content-Type: application/json
     ```
   - **Request body:** `{"ref":"main"}`
   - **Schedule:** a cada 2 minutos (minuto 0 e minuto 2, ou `*/2`).
3. Salve e ative o job.

## Como funciona

> ✅ **Já validado em 15/08/2026:** o endpoint de dispatch respondeu **HTTP 204**
> e o workflow disparado completou com sucesso, publicando dados novos no site
> em ~1 minuto. O teste usou `POST` com `Authorization: Bearer <token>` e corpo
> `{"ref":"main"}` — exatamente o que o cron-job.org fará.

A cada 2 min o cron-job.org chama a API do GitHub, que dispara o workflow
**Deploy GitHub Pages** (`workflow_dispatch`). O workflow gera os dados
(`python build.py`), persiste o histórico green/red em `data/entries.json`
(commitado de volta ao repositório) e publica o site.

O resultado: o `api/scanner.json` publicado é regenerado a cada ~2 min, e o
frontend (que consulta a cada 30 s) mostra os dados novos quase em seguida.

> O cron nativo do workflow continua configurado como *backup* (best-effort) —
> ele pode atrasar ou não rodar, mas não atrapalha. O agendador externo é o que
> garante o ritmo.
