import os
import subprocess
import sys
from importlib.metadata import entry_points
from pathlib import Path

import sistema_catraca
from sistema_catraca import dados
from sistema_catraca.modulo import MODULO


def test_valores_do_modulo():
    assert (MODULO.id, MODULO.nome, MODULO.icone) == ("sistema_catraca", "Sistema Catraca", "porta")
    assert (MODULO.grupo_ad, MODULO.repositorio, MODULO.nome_exe) == (
        "SF-Catraca", "ErikDeFreitas/Projeto_Catraca", "SistemaCatraca.exe")
    assert MODULO.versao == sistema_catraca.__version__ == "2.0.1"
    assert MODULO.pasta_dados == dados.PASTA
    assert MODULO.aplicacao_settings == "SistemaCatraca"
    assert [(p.chave, p.titulo, p.subtitulo, p.icone) for p in MODULO.paginas] == [
        ("relatorio", "Relatório de acessos", "Consulte os acessos do período e salve em CSV.", "arquivo"),
        ("usuarios", "Usuários", "Escolha quem entra no relatório.", "usuarios"),
    ]


def test_entry_point_carrega_o_modulo():
    eps = {ep.name: ep for ep in entry_points(group="sistema_financeiro.modulos")}
    assert eps["sistema_catraca"].load() is MODULO


def test_modulo_e_leve(tmp_path):
    codigo = ("import sys, sistema_catraca.modulo; "
              "print(*[m in sys.modules for m in ('requests', 'sistema_catraca.catraca_core', "
              "'sistema_catraca.instancia')])")
    env = {**os.environ, "CATRACA_DADOS": str(tmp_path / "nao_criar")}
    saida = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, env=env, check=True)
    assert saida.stdout.split() == ["False"] * 3
    assert not Path(tmp_path / "nao_criar").exists()


def test_criar_devolve_a_instancia(contexto):
    instancia = MODULO.criar(contexto)
    assert instancia.widget("relatorio") is not None
