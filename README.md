# API - Relatório de Acessos (Catraca ControlID)

API que roda na máquina local conectada à catraca (rede interna) e gera
relatórios de acesso em CSV, para o site consumir remotamente.

## Como o dev do site deve integrar

O fluxo é **assíncrono** (a extração na catraca pode demorar):

```
1) POST /relatorio            → cria o pedido, retorna um job_id
2) GET  /relatorio/{job_id}   → consulta o status (fazer polling a cada 2-5s)
3) GET  /relatorio/{job_id}/download → baixa o CSV quando status = "concluido"
```

**Todas as chamadas abaixo exigem o header `X-API-Key` com a chave configurada
no `.env` do servidor.** Sem ela (ou com valor errado), a API responde `401`.

### 1) Solicitar o relatório

```
POST /relatorio
Content-Type: application/json
X-API-Key: <chave-combinada-com-voces>

{
  "data_inicio": "2026-07-01",
  "data_fim": "2026-07-20"
}
```

Resposta (imediata):
```json
{
  "job_id": "3f2a1b0c-...",
  "status": "pendente"
}
```

### 2) Consultar status

```
GET /relatorio/3f2a1b0c-...
X-API-Key: <chave-combinada-com-voces>
```

Resposta enquanto processa:
```json
{
  "job_id": "3f2a1b0c-...",
  "status": "processando",
  "criado_em": "2026-07-20T10:15:00",
  "data_inicio": "2026-07-01",
  "data_fim": "2026-07-20",
  "total_registros": null,
  "sem_registro": null,
  "download_url": null,
  "erro": null
}
```

Resposta quando pronto:
```json
{
  "job_id": "3f2a1b0c-...",
  "status": "concluido",
  "total_registros": 342,
  "sem_registro": ["Robert"],
  "download_url": "/relatorio/3f2a1b0c-.../download",
  "erro": null
}
```

Possíveis valores de `status`: `pendente`, `processando`, `concluido`, `erro`.
Se der erro, o campo `erro` vem preenchido com a mensagem.

### 3) Baixar o CSV

```
GET /relatorio/3f2a1b0c-.../download
X-API-Key: <chave-combinada-com-voces>
```

Retorna o arquivo CSV diretamente (`Content-Type: text/csv`), pronto para
download pelo navegador.

> A API Key é secreta: o `fetch` do download **não deve** ser feito direto
> do navegador do visitante do site (isso exporia a chave). O ideal é o
> backend do site fazer essa chamada e repassar o arquivo pro navegador,
> ou gerar um link assinado. Se precisar de ajuda para montar esse
> "proxy" no backend do site, é só pedir.

### Exemplo em JavaScript (fetch, rodando no backend do site)

```js
const API_KEY = process.env.CATRACA_API_KEY; // nunca no frontend
const BASE_URL = "https://relatorios.seudominio.com.br"; // dominio do Cloudflare Tunnel

async function gerarRelatorio(dataInicio, dataFim) {
  const { job_id } = await fetch(`${BASE_URL}/relatorio`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": API_KEY,
    },
    body: JSON.stringify({ data_inicio: dataInicio, data_fim: dataFim }),
  }).then(r => r.json());

  // polling
  while (true) {
    const status = await fetch(`${BASE_URL}/relatorio/${job_id}`, {
      headers: { "X-API-Key": API_KEY },
    }).then(r => r.json());

    if (status.status === "concluido") {
      return fetch(`${BASE_URL}${status.download_url}`, {
        headers: { "X-API-Key": API_KEY },
      }); // repassar o CSV pro navegador do usuario a partir daqui
    }
    if (status.status === "erro") {
      throw new Error("Erro ao gerar relatório: " + status.erro);
    }
    await new Promise(res => setTimeout(res, 3000)); // espera 3s e tenta de novo
  }
}
```

## Como subir a API (na máquina local com acesso à catraca)

### Windows

Foram incluídos dois arquivos prontos para dar duplo clique:

1. **`instalar.bat`** — roda uma única vez. Cria o ambiente virtual, instala
   as dependências, cria o `.env` a partir do `.env.example` e já abre o
   Notepad para você preencher IP/usuário/senha da catraca.
2. **`iniciar_api.bat`** — sobe a API na porta 8000. Deixe a janela aberta
   enquanto quiser que a API fique no ar (fechar a janela derruba a API).

Pré-requisito: ter o **Python 3** instalado ([python.org/downloads](https://www.python.org/downloads/)),
marcando a opção "Add Python to PATH" durante a instalação.

**Liberar a porta no Firewall do Windows** (se o site for acessar por fora
desta máquina), rodando como Administrador no PowerShell:
```powershell
New-NetFirewallRule -DisplayName "API Catraca" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
```

**Deixar rodando sem depender de janela aberta / reiniciar sozinha após
reboot:** o jeito mais simples é usar o [NSSM](https://nssm.cc/) para
registrar `iniciar_api.bat` como um Serviço do Windows. Isso não está
incluído aqui pois depende de como vocês preferem administrar a máquina —
mas é só avisar que eu monto esse passo a passo também.

### Linux / macOS

```bash
pip install -r requirements.txt
cp .env.example .env
# edite o .env com IP/usuario/senha da catraca e o(s) domínio(s) do site
uvicorn app:app --host 0.0.0.0 --port 8000
```

### Em qualquer sistema

Documentação interativa (Swagger) fica disponível em `/docs` automaticamente,
ex: `http://localhost:8000/docs`.

## Publicando na internet a partir do Mini PC (Docker + Cloudflare Tunnel)

Como a catraca só é acessível na rede local, a API precisa rodar numa
máquina dessa mesma rede (o Mini PC) — não dá pra jogar isso num VPS na
nuvem sem uma VPN de volta pra rede local. A forma mais simples de publicar
a partir do Mini PC é com **Cloudflare Tunnel**: ele expõe a API na internet
com HTTPS, sem precisar abrir porta no roteador nem configurar Firewall.

### 1) Criar o túnel na Cloudflare (uma vez só)

1. Precisa de um domínio cadastrado na Cloudflare (pode ser um subdomínio
   qualquer, tipo `relatorios.seudominio.com.br`).
2. No painel: **Zero Trust → Networks → Tunnels → Create a tunnel**
   (tipo Cloudflared).
3. Dê um nome (ex: `catraca-api`) e copie o **token** gerado.
4. Em **Public Hostname**, aponte o subdomínio escolhido para
   `http://api:8000` (esse `api` é o nome do serviço no `docker-compose.yml`).

### 2) Configurar e subir no Mini PC

```bash
# instale o Docker no Mini PC, se ainda nao tiver (docker.com/get-started)

cp .env.example .env
# preencha no .env:
#   - CATRACA_IP / CATRACA_USUARIO / CATRACA_SENHA
#   - API_KEY (gere uma: python -c "import secrets; print(secrets.token_urlsafe(32))")
#   - CLOUDFLARE_TUNNEL_TOKEN (o token copiado no passo anterior)
#   - ORIGENS_PERMITIDAS com o dominio real do site

docker compose up -d --build
```

Isso sobe dois containers: a API (`api`) e o túnel (`cloudflared`), que juntos
publicam `https://relatorios.seudominio.com.br` já com HTTPS, sem expor
nenhuma porta do Mini PC diretamente pra internet.

Pra ver os logs: `docker compose logs -f`
Pra parar: `docker compose down`
Pra atualizar depois de alguma mudança no código: `docker compose up -d --build`

## Pontos de atenção para colocar em produção

- **Autenticação por API Key já implementada** (header `X-API-Key`,
  configurada via `.env`). Guarde essa chave com o mesmo cuidado de uma
  senha — quem tiver ela consegue gerar relatórios pela API.
- **CORS**: no `.env`, trocar `ORIGENS_PERMITIDAS=*` pelo domínio real do
  site (ex: `https://www.tcmlogistica.com.br`).
- **Exposição da máquina**: resolvida via Cloudflare Tunnel (seção acima) —
  não precisa abrir porta no roteador nem expor IP público do Mini PC.
- **Jobs em memória**: se a API cair/reiniciar, jobs em andamento se perdem
  (o site precisa lidar com isso reenviando o pedido). Para um volume maior
  de uso, vale migrar para um banco simples (SQLite) ou fila (Redis/RQ).
- Os CSVs gerados ficam salvos em `./relatorios` (configurável no `.env`) e
  não são apagados automaticamente — vale criar uma limpeza periódica.
