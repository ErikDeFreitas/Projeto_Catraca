# Sistema Catraca

Consulta os acessos da catraca ControlID e exporta o relatório em CSV. Substitui o programa em
Tkinter da pasta `Projeto_Catraca_V1.0`, com o Design System TCM (PySide6 + QSS).

## Como usar

1. Abra `dist\SistemaCatraca.exe`. O computador precisa estar na rede da catraca.
2. Em **Relatório de acessos**, confira IP e usuário, digite a senha e escolha o período.
3. Clique em **Gerar relatório**. O resultado aparece por colaborador; clique em um nome para ver os
   acessos dele.
4. Clique em **Salvar CSV**. O nome é sugerido no padrão `Relatório 2° Quinzena Outubro.csv`.

Quem entra no relatório é escolhido na página **Usuários**: marque ou desmarque cada nome (clique na
linha ou tecla Espaço). **Buscar na catraca** traz todos os usuários cadastrados nela (`load_objects.fcgi`);
os novos chegam desmarcados, e o aviso final lista os nomes da lista que não existem na catraca.
Também dá para adicionar um nome à mão (já entra marcado).

A lista e as marcações ficam salvas no usuário do Windows (junto com IP, usuário, tema e última
pasta). Sem marcação salva, todos os nomes entram, como na V1.0. A **senha nunca é salva**.

## Regras mantidas da V1.0

- Mesma consulta à catraca (`login.fcgi` e `report_generate.fcgi`) e mesmo filtro: nome igual ao da
  lista, sem diferenciar maiúsculas nem espaços nas pontas.
- O CSV continua igual: `Nome;Data/Hora`, separador `;`, fim de linha CRLF, UTF-8 e as linhas na ordem
  em que a catraca devolveu.

## Desenvolvimento

```
pip install -r requirements.txt pyinstaller
python main.py                        # roda pelo código-fonte
python -m unittest discover -s tests  # testes, com uma catraca simulada
python build.py                       # gera dist\SistemaCatraca.exe e o .sha256
```

| Arquivo | Papel |
|---|---|
| `catraca_core.py` | Regras de negócio: consulta, filtro, períodos e CSV. Sem interface |
| `main.py` | Janela e páginas de relatório e usuários |
| `themes.py`, `styles.qss`, `components.py`, `icons.py` | Design System |
| `updater.py`, `update_ui.py`, `version.py` | Atualização automática pelas Releases do GitHub |
| `build.py`, `SistemaCatraca.spec` | Geração do executável |

## Publicação

Enviar uma tag `vX.Y.Z` igual a `version.py` dispara `.github/workflows/release.yml`, que testa, gera o
executável e publica a Release. Commits sem tag não geram Release.

O programa procura atualização nas Releases de `ErikDeFreitas/Projeto_Catraca`; enquanto não houver
nenhuma, a verificação apenas não encontra nada. Ela lê as Releases sem autenticação, por isso o
repositório precisa ser público.
