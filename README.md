# Sistema Catraca

Consulta os acessos da catraca ControlID e exporta o relatório em CSV. Usa o design system
TCM (`Tcm-ui`, PySide6) e roda de duas formas: sozinho (`SistemaCatraca.exe`) ou como um dos módulos
do Sistema Financeiro.

## O que faz

- **Relatório de acessos**: consulta a catraca, mostra os acessos por colaborador e salva o relatório
  em CSV.
- **Usuários**: define quem entra no relatório e busca na catraca os usuários cadastrados.

## Como usar

1. Abra `SistemaCatraca.exe`. O computador precisa estar na rede da catraca.
2. Em **Relatório de acessos**, informe o endereço (IP) da catraca e o usuário, digite a senha e
   escolha o período.
3. Clique em **Gerar relatório**. O resultado aparece por colaborador; clique em um nome para ver os
   acessos dele.
4. Clique em **Salvar CSV**. O nome é sugerido no padrão `Relatório 2° Quinzena Outubro.csv`.

Na página **Usuários**, marque ou desmarque cada nome (clique na linha ou tecla Espaço) para
escolher quem entra no relatório. **Buscar na catraca** traz todos os usuários cadastrados nela;
os novos chegam desmarcados, e o aviso final lista os nomes da lista que não existem na catraca.
Também dá para adicionar um nome à mão (já entra marcado).

A **senha nunca é salva**. Endereço, usuário, lista de nomes, marcações, tema e última pasta ficam
nas configurações do usuário do Windows (organização `TCM`, aplicação `SistemaCatraca`). O programa
não traz nenhum endereço, usuário ou nome pré-preenchido: na primeira vez, digite o endereço e o
usuário e busque os nomes na catraca.

### Vindo da versão 1.0.0

Quem já alterou o endereço ou o usuário na 1.0.0 mantém esses valores, a lista de nomes e as
marcações. Quem nunca os alterou não os tem salvos (a 1.0.0 não gravava os valores padrão) e precisa
digitá-los uma vez na primeira abertura da 2.0.0. A preferência de tema é migrada sozinha.

## Regras mantidas da 1.0.0

- Mesma consulta à catraca (`login.fcgi` e `report_generate.fcgi`) e mesmo filtro: nome igual ao da
  lista, sem diferenciar maiúsculas nem espaços nas pontas.
- O CSV continua igual: `Nome;Data/Hora`, separador `;`, fim de linha CRLF, UTF-8 e as linhas na ordem
  em que a catraca devolveu.

## Desenvolver

```
python -m venv .venv
.venv\Scripts\activate
pip install -e ..\Tcm-ui            # ou: pip install -r requirements.txt
pip install -e ".[dev]" pyinstaller
python main.py                      # roda pelo código-fonte
python -m pytest                    # testes, com uma catraca simulada
```

Para não mexer nos dados reais, defina `CATRACA_DADOS` com uma pasta temporária antes de rodar.

| Pasta ou arquivo | Papel |
|---|---|
| `src/sistema_catraca/catraca_core.py` | Regras de negócio: consulta, filtro, períodos e CSV. Sem interface |
| `src/sistema_catraca/` (demais) | Módulo para a casca e o avulso: páginas, lista de usuários, tarefa em segundo plano |
| `main.py` | Ponto de entrada do `.exe` avulso |
| `build.ps1` | Gera `dist\SistemaCatraca.exe` e o `.sha256` |

## Lançar uma versão

1. Suba `__version__` em `src/sistema_catraca/__init__.py`.
2. Crie a tag igual à versão (ex.: `v2.0.0`) e envie para o GitHub.

`.github/workflows/release.yml` confere tag e versão, roda os testes, gera o executável e publica a
Release com `SistemaCatraca.exe` e `SistemaCatraca.exe.sha256`. O programa procura atualização nas
Releases de `ErikDeFreitas/Projeto_Catraca`, sem autenticação; por isso o repositório precisa ser
público.

## Módulo da casca

O Sistema Financeiro carrega este pacote pelo ponto de entrada `sistema_financeiro.modulos`
(`sistema_catraca.modulo:MODULO`). O acesso é liberado pelo grupo do AD `SF-Catraca`.
