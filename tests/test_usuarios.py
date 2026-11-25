import json

import pytest

from sistema_catraca import catraca_core as core
from sistema_catraca.usuarios import ListaUsuarios


def _salvar(config, nomes=None, marcados=None):
    if nomes is not None:
        config.setValue("colaboradores", json.dumps(nomes, ensure_ascii=False))
    if marcados is not None:
        config.setValue("selecionados", json.dumps(marcados, ensure_ascii=False))
    config.sync()


def test_sem_nada_salvo_usa_padrao_e_todos_marcados(configuracoes, monkeypatch):
    monkeypatch.setattr(core, "COLABORADORES_PADRAO", ("Ana Teste", "Bruno Teste"))
    lista = ListaUsuarios(configuracoes)
    assert lista.nomes == ["Ana Teste", "Bruno Teste"]
    assert lista.marcados == ["Ana Teste", "Bruno Teste"]
    assert configuracoes.value("colaboradores") is None


def test_le_lista_e_marcacao_da_versao_1(configuracoes):
    _salvar(configuracoes, ["Ana Teste", "José Teste", "Bruno Teste"], ["José Teste"])
    lista = ListaUsuarios(configuracoes)
    assert lista.nomes == ["Ana Teste", "José Teste", "Bruno Teste"]
    assert lista.marcados == ["José Teste"]
    assert lista.esta_marcado("JOSÉ TESTE")
    assert not lista.esta_marcado("Ana Teste")


@pytest.mark.parametrize("bruto", ["{nao e json", '{"a": 1}', '["a", 2]'])
def test_json_invalido_cai_no_padrao(configuracoes, monkeypatch, bruto):
    monkeypatch.setattr(core, "COLABORADORES_PADRAO", ("Ana Teste",))
    configuracoes.setValue("colaboradores", bruto)
    assert ListaUsuarios(configuracoes).nomes == ["Ana Teste"]


def test_adicionar_entra_marcado_e_recusa_repetido(configuracoes):
    _salvar(configuracoes, ["Ana Teste"], [])
    lista = ListaUsuarios(configuracoes)
    avisos = []
    lista.mudou.connect(lambda: avisos.append("mudou"))
    lista.adicionar("  Maria   Teste ")
    assert lista.nomes == ["Ana Teste", "Maria Teste"]
    assert lista.marcados == ["Maria Teste"]
    assert avisos == ["mudou"]
    with pytest.raises(ValueError):
        lista.adicionar("ANA TESTE")
    with pytest.raises(ValueError):
        lista.adicionar("   ")


def test_mesclar_novos_entram_desmarcados(configuracoes):
    _salvar(configuracoes, ["Ana Teste"], ["Ana Teste"])
    lista = ListaUsuarios(configuracoes)
    novos = lista.mesclar(["ANA TESTE", "Bruno Teste", "bruno teste"])
    assert novos == ["Bruno Teste"]
    assert lista.nomes == ["Ana Teste", "Bruno Teste"]
    assert lista.marcados == ["Ana Teste"]
    assert lista.mesclar(["Ana Teste"]) == []


def test_remover_tira_da_marcacao(configuracoes):
    _salvar(configuracoes, ["Ana Teste", "Bruno Teste"], ["Ana Teste", "Bruno Teste"])
    lista = ListaUsuarios(configuracoes)
    lista.remover("Ana Teste")
    assert lista.nomes == ["Bruno Teste"]
    assert lista.marcados == ["Bruno Teste"]
    assert json.loads(configuracoes.value("selecionados")) == ["Bruno Teste"]


def test_grava_no_mesmo_formato(configuracoes):
    lista = ListaUsuarios(configuracoes)
    lista.adicionar("José Teste")
    lista.adicionar("Ana Teste")
    lista.marcar(["Ana Teste"], False)
    configuracoes.sync()
    bruto = str(configuracoes.value("colaboradores"))
    assert "José" in bruto  # acento preservado, sem é
    assert json.loads(bruto) == ["José Teste", "Ana Teste"]
    assert json.loads(str(configuracoes.value("selecionados"))) == ["José Teste"]


def test_marcar_persiste_e_avisa(configuracoes):
    _salvar(configuracoes, ["Ana Teste", "José Teste", "Bruno Teste"])
    lista = ListaUsuarios(configuracoes)
    avisos = []
    lista.marcacao_mudou.connect(lambda: avisos.append(1))

    lista.marcar(["JOSÉ TESTE", "Ana Teste"], False)  # compara sem diferenciar maiúsculas
    assert lista.marcados == ["Bruno Teste"] and len(avisos) == 1
    configuracoes.sync()
    assert json.loads(configuracoes.value("selecionados")) == ["Bruno Teste"]
    assert json.loads(configuracoes.value("colaboradores")) == ["Ana Teste", "José Teste", "Bruno Teste"]  # a lista não muda

    lista.marcar(["Ana Teste"], True)
    assert lista.marcados == ["Ana Teste", "Bruno Teste"] and len(avisos) == 2
    configuracoes.sync()
    assert json.loads(configuracoes.value("selecionados")) == ["Ana Teste", "Bruno Teste"]
    assert ListaUsuarios(configuracoes).marcados == ["Ana Teste", "Bruno Teste"]  # relê o que gravou

    lista.marcar(["Ana Teste"], True)  # nada mudou: não grava nem avisa
    lista.marcar(["Fulano Inexistente"], False)
    assert len(avisos) == 2
