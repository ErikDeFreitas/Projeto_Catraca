import importlib
import sys
from pathlib import Path

from sistema_catraca import dados


def test_catraca_dados_substitui_a_pasta(monkeypatch, tmp_path):
    monkeypatch.setenv("CATRACA_DADOS", str(tmp_path / "x"))
    assert dados.pasta_dados() == tmp_path / "x"


def test_sem_variavel_usa_localappdata(monkeypatch, tmp_path):
    monkeypatch.delenv("CATRACA_DADOS", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert dados.pasta_dados() == tmp_path / "SistemaCatraca"
    assert dados.NOME_APLICACAO == "SistemaCatraca"


def test_importar_nao_cria_pasta(monkeypatch, tmp_path):
    alvo = tmp_path / "nao_criar"
    monkeypatch.setenv("CATRACA_DADOS", str(alvo))
    original = sys.modules.pop("sistema_catraca.dados")
    try:
        novo = importlib.import_module("sistema_catraca.dados")
        assert isinstance(novo.PASTA, Path)
        assert novo.PASTA == alvo
        assert not alvo.exists()
    finally:
        sys.modules["sistema_catraca.dados"] = original


def test_configuracoes_usa_tcm_sistemacatraca():
    config = dados.configuracoes()
    assert config.organizationName() == "TCM"
    assert config.applicationName() == "SistemaCatraca"
