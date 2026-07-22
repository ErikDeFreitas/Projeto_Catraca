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

### 1) Solicitar o relatório

```
POST /relatorio
Content-Type: application/json

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
```

Retorna o arquivo CSV diretamente (`Content-Type: text/csv`), pronto para
download pelo navegador.

### Exemplo em JavaScript (fetch)

```js
async function gerarRelatorio(dataInicio, dataFim) {
  const { job_id } = await fetch("https://SEU-DOMINIO-OU-IP:8000/relatorio", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ data_inicio: dataInicio, data_fim: dataFim }),
  }).then(r => r.json());

  // polling
  while (true) {
    const status = await fetch(`https://SEU-DOMINIO-OU-IP:8000/relatorio/${job_id}`).then(r => r.json());

    if (status.status === "concluido") {
      window.location.href = `https://SEU-DOMINIO-OU-IP:8000${status.download_url}`;
      break;
    }
    if (status.status === "erro") {
      alert("Erro ao gerar relatório: " + status.erro);
      break;
    }
    await new Promise(res => setTimeout(res, 3000)); // espera 3s e tenta de novo
  }
}
```

## Como subir a API (na máquina local com acesso à catraca)

```bash
pip install -r requirements.txt
cp .env.example .env
# edite o .env com IP/usuario/senha da catraca e o(s) domínio(s) do site
uvicorn app:app --host 0.0.0.0 --port 8000
```

Documentação interativa (Swagger) fica disponível em `/docs` automaticamente.

## Pontos de atenção para colocar em produção

- **Sem autenticação por enquanto** (definido assim por vocês). Se a API vai
  ficar exposta na internet, considerar no futuro uma API Key simples no
  header, para não ficar aberta para qualquer um gerar relatórios.
- **CORS**: no `.env`, trocar `ORIGENS_PERMITIDAS=*` pelo domínio real do
  site (ex: `https://www.tcmlogistica.com.br`).
- **Exposição da máquina**: como a catraca só é acessível localmente, essa
  API precisa ficar acessível pela internet de alguma forma (porta liberada
  no roteador/firewall, um túnel reverso, ou VPN entre o site e a rede local).
  Isso depende da infra de vocês — não está coberto por este código.
- **Jobs em memória**: se a API cair/reiniciar, jobs em andamento se perdem
  (o site precisa lidar com isso reenviando o pedido). Para um volume maior
  de uso, vale migrar para um banco simples (SQLite) ou fila (Redis/RQ).
- Os CSVs gerados ficam salvos em `./relatorios` (configurável no `.env`) e
  não são apagados automaticamente — vale criar uma limpeza periódica.
