# API Instagram para Power BI

API Python/FastAPI somente de leitura para as seis tabelas do esquema `public` enviado. Todas as colunas são retornadas, incluindo campos JSON como texto JSON, nulos, datas ISO 8601 e timestamps com fuso. O esquema real é consultado no PostgreSQL. Não cria nem altera tabelas.

## Executar no Windows

Instale Python 3.11 ou superior e execute nesta pasta:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edite `.env`: preencha `PGHOST`, `PGPORT` (padrão 5432), `PGDATABASE`, `PGUSER`, `PGPASSWORD` e `API_TOKEN` (token aleatório longo). A senha é enviada diretamente ao driver e não precisa de codificação URL. Se contiver `#` ou espaços, coloque o valor entre aspas no `.env`. Use um usuário PostgreSQL com `USAGE` no esquema e `SELECT` nas seis tabelas, sem permissões de escrita. Para banco remoto, configure TLS conforme o provedor (preferencialmente `PGSSLMODE=verify-full` e `PGSSLROOTCERT` e certificado).

```powershell
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Documentação interativa: http://localhost:8000/docs. O valor de `API_TOKEN` autentica as requisições. A API aceita esse valor via `X-API-Key` ou `api_key` para compatibilidade com a credencial API da Web do Power BI. Não registre URLs com chaves nos logs do servidor/proxy. Ao hospedar, use HTTPS, guarde `.env` fora do Git e desative ou mascare access logs com query strings (Uvicorn: `--no-access-log`).

## Endpoints

- `GET /health`: verifica se o processo responde; não verifica o banco.
- `GET /api/tables`: lista as seis tabelas autorizadas.
- `GET /api/data/{table}`: lê todas as colunas, ordenadas por `id`.

Parâmetros: `limit` (1 a 10000), `after_id`, `until_id`, `date_from` e `date_to`. As datas filtram `data_coleta`, inclusive. Sem datas, retorna todo o histórico ao percorrer as páginas. A resposta contém `columns`, `data`, `next_after_id` e `until_id`. Use o próximo cursor até ele ser nulo, mantendo `until_id` da primeira página. O teto evita incluir novos IDs durante a importação; alterações e exclusões entre páginas ainda podem afetar o resultado. As seis tabelas são importadas separadamente, sem snapshot transacional entre elas.

Inteiros bigint e valores numeric são transmitidos como strings para evitar arredondamento no transporte. A função M converte bigint em Int64 e numeric em número do Power BI; numeric com alta precisão pode perder precisão nessa conversão. Para precisão decimal integral, mantenha essa coluna como texto na função M.

## Power BI

1. Transformar dados → Nova fonte → Consulta em branco → Editor avançado.
2. Cole `powerbi.m`, nomeie a consulta `fnInstagram` e altere a URL literal para a URL da sua API.
3. Configure a fonte com autenticação **API da Web**, informando somente o valor de `API_TOKEN`.
4. Crie seis consultas em branco e cole uma expressão por consulta:

```powerquery
= fnInstagram("instagram_daily_insights")
= fnInstagram("instagram_demographic_breakdowns")
= fnInstagram("instagram_demographics")
= fnInstagram("instagram_media_insight_failures")
= fnInstagram("instagram_media_insights")
= fnInstagram("instagram_media_snapshots")
```

Para filtrar: `fnInstagram("instagram_daily_insights", #date(2026, 1, 1), #date(2026, 12, 31))`.

JSON é mantido como texto; transforme com `Json.Document` e expanda no Power Query quando necessário. A paginação importa todas as linhas existentes, mesmo acima de 5000. Filtros de data são explícitos; atualização incremental automática não está configurada.

Power BI Service precisa alcançar a API: se estiver local ou em rede privada, configure um gateway apropriado; se estiver hospedada, informe uma URL HTTPS acessível. Hospedagem e atualização agendada precisam ser validadas no seu ambiente. `localhost` serve para Power BI Desktop na mesma máquina.

Referência da consulta M: [Microsoft Web.Contents](https://learn.microsoft.com/powerquery-m/web-contents).

## VPS Hostinger: 187.127.14.158

Execução direta com Python e systemd. Os comandos abaixo assumem Ubuntu/Debian com Python 3.11 ou superior; ajuste a instalação de pacotes se a VPS usar outra distribuição.

```bash
sudo apt update
sudo apt install -y python3 python3-venv git
sudo useradd --system --user-group --home-dir /opt/api-bi-marketing --shell /usr/sbin/nologin api-bi
sudo mkdir -p /opt/api-bi-marketing
sudo chown api-bi:api-bi /opt/api-bi-marketing
```

Crie o usuário `api-bi` apenas na primeira instalação. O serviço mantém a API em execução e inicia automaticamente após reiniciar a VPS.

Se PostgreSQL estiver na mesma VPS, use `127.0.0.1` em `PGHOST`, com a porta real do banco. Configure o usuário de leitura e sua autenticação no PostgreSQL.

Ainda necessários: nome/porta/host do banco, usuário de leitura e domínio da API. A senha deve ser configurada diretamente no `.env` da VPS. Estes arquivos preparam a implantação; não houve acesso nem publicação na VPS.

### Publicar pelo GitHub

No computador, publique estes arquivos no seu repositório GitHub com `git push`. Não publique `.env`; ele já está ignorado. Na VPS, substitua a URL abaixo pela URL real do seu repositório:

```bash
sudo -u api-bi git clone https://github.com/SEU_USUARIO/SEU_REPOSITORIO.git /opt/api-bi-marketing
cd /opt/api-bi-marketing
sudo -u api-bi python3 -m venv .venv
sudo -u api-bi .venv/bin/python -m pip install -r requirements.txt
sudo -u api-bi cp .env.example .env
sudo -u api-bi nano .env
sudo chmod 600 .env
sudo cp deploy/api-bi-marketing.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now api-bi-marketing
curl http://127.0.0.1:8000/health
```

Nas atualizações, após o `git push` no computador, execute dentro da pasta do projeto na VPS:

```bash
cd /opt/api-bi-marketing
sudo -u api-bi git pull --ff-only
sudo -u api-bi .venv/bin/python -m pip install -r requirements.txt
sudo systemctl restart api-bi-marketing
sudo systemctl status api-bi-marketing --no-pager
```

O `.env` criado na VPS permanece local durante as atualizações. Em repositório privado, configure autenticação Git para o usuário `api-bi`, preferencialmente com chave de deploy de leitura.

Para diagnosticar falhas: `sudo journalctl -u api-bi-marketing -n 100 --no-pager`.

Configure Nginx/Caddy como proxy reverso para `127.0.0.1:8000`, com domínio e HTTPS, e use esse domínio na função M. Desative logs de query strings no proxy, pois `api_key` é enviado na URL. O serviço escuta apenas no loopback; o acesso externo depende desse proxy.

## Executar testes

```powershell
python -m unittest discover -s tests -v
```

Testes usam banco simulado; conexão e compatibilidade com os dados reais precisam ser verificadas após configurar `.env`.
