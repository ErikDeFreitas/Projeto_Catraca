"""MODULO do Sistema Catraca para a casca e o avulso. Leve: só dados e a fábrica (sem requests nem Qt widgets)."""

from tcm_ui.modulo import Contexto, Modulo, Pagina

from sistema_catraca import __version__, dados


def criar(contexto: Contexto):
    from sistema_catraca.instancia import Catraca  # import pesado só quando o módulo é aberto
    return Catraca(contexto)


MODULO = Modulo(
    id="sistema_catraca",
    nome="Sistema Catraca",
    icone="porta",
    versao=__version__,
    grupo_ad="SF-Catraca",
    repositorio="ErikDeFreitas/Projeto_Catraca",
    nome_exe="SistemaCatraca.exe",
    pasta_dados=dados.PASTA,
    paginas=(
        Pagina("relatorio", "Relatório de acessos", "Consulte os acessos do período e salve em CSV.", "arquivo"),
        Pagina("usuarios", "Usuários", "Escolha quem entra no relatório.", "usuarios"),
    ),
    criar=criar,
)
