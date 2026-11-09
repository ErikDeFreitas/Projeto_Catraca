"""Testes das regras de negócio, com uma catraca simulada em um servidor HTTP local."""

import json
import sys
import tempfile
import threading
import unittest
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import catraca_core as core


class FakeCatraca(BaseHTTPRequestHandler):
    session = "sessao-teste"
    login_status = 200
    login_body = b'{"session": "sessao-teste"}'
    report_status = 200
    report_body = b""
    report_headers = {"Content-Type": "text/csv"}
    users_body = b'{"users": []}'
    received: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).received.append((self.path, body))
        if self.path == "/login.fcgi":
            self._reply(self.login_status, self.login_body, {"Content-Type": "application/json"})
        elif self.path.startswith("/load_objects.fcgi"):
            self._reply(200, self.users_body, {"Content-Type": "application/json"})
        else:
            self._reply(self.report_status, self.report_body, self.report_headers)

    def _reply(self, status, body, headers):
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        self.handler = type("Handler", (FakeCatraca,), {"received": []})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.ip = f"127.0.0.1:{self.server.server_address[1]}"
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def gerar(self, colaboradores=("Aline", "Braz", "Robert")):
        return core.gerar_relatorio(
            self.ip, "admin", "segredo", date(2026, 10, 1), date(2026, 10, 15), colaboradores
        )


class GerarRelatorioTests(ServerTestCase):
    def test_envia_login_e_periodo_iguais_ao_programa_original(self):
        self.handler.report_body = b"Nome;Data/Hora\r\n"
        self.gerar()
        (login_path, login), (report_path, report) = self.handler.received
        self.assertEqual(login_path, "/login.fcgi")
        self.assertEqual(login, {"login": "admin", "password": "segredo"})
        self.assertEqual(report_path, "/report_generate.fcgi?session=sessao-teste")
        self.assertEqual(report["object"], "access_logs")
        self.assertEqual(report["header"], "Nome;Data/Hora")
        inicio, fim = report["where"]
        self.assertEqual(inicio["value"], int(datetime(2026, 10, 1).timestamp()))
        self.assertEqual(fim["value"], int(datetime(2026, 10, 15, 23, 59, 59).timestamp()))

    def test_filtra_pela_lista_ignorando_maiusculas_e_espacos(self):
        self.handler.report_body = (
            "Nome;Data/Hora\r\n"
            "Aline;01/10/2026 08:00:00\r\n"
            "Visitante;01/10/2026 08:10:00\r\n"
            " ALINE ;02/10/2026 17:00:00\r\n"
            "braz;03/10/2026 07:30:00\r\n"
        ).encode()
        relatorio = self.gerar()
        self.assertEqual(relatorio.total_registros, 3)
        self.assertEqual(relatorio.sem_registro, ["Robert"])
        aline, braz, robert = relatorio.resumos
        self.assertEqual((aline.nome, aline.total), ("Aline", 2))
        self.assertEqual(aline.primeiro, datetime(2026, 10, 1, 8, 0))
        self.assertEqual(aline.ultimo, datetime(2026, 10, 2, 17, 0))
        self.assertEqual((braz.nome, braz.total), ("Braz", 1))
        self.assertEqual((robert.total, robert.primeiro), (0, None))

    def test_nome_acentuado_coincide_mesmo_sem_charset_no_cabecalho(self):
        self.handler.report_body = "Nome;Data/Hora\r\nJoão;01/10/2026 08:00:00\r\n".encode("utf-8")
        relatorio = self.gerar(["João"])
        self.assertEqual(relatorio.total_registros, 1)

    def test_data_inesperada_nao_perde_o_registro(self):
        self.handler.report_body = b"Nome;Data/Hora\r\nAline;ontem\r\nAline\r\n"
        relatorio = self.gerar(["Aline"])
        self.assertEqual(relatorio.total_registros, 2)
        self.assertEqual(relatorio.acessos[0].data_hora, None)
        self.assertEqual(relatorio.acessos[0].texto_original, "ontem")
        self.assertEqual(relatorio.resumos[0].primeiro, None)

    def test_catraca_sem_nenhuma_linha(self):
        self.handler.report_body = b""
        relatorio = self.gerar(["Aline"])
        self.assertEqual(relatorio.total_registros, 0)
        self.assertEqual(relatorio.sem_registro, ["Aline"])

    def test_login_recusado_tem_mensagem_clara(self):
        self.handler.login_status = 401
        self.handler.login_body = b'{"error": "invalid"}'
        with self.assertRaisesRegex(core.CatracaError, "usuário e a senha"):
            self.gerar()

    def test_login_sem_sessao(self):
        self.handler.login_body = b"nao eh json"
        with self.assertRaisesRegex(core.CatracaError, "sessão válida"):
            self.gerar()

    def test_periodo_invertido_nao_chega_a_conectar(self):
        with self.assertRaisesRegex(core.CatracaError, "data final"):
            core.gerar_relatorio(self.ip, "a", "b", date(2026, 10, 2), date(2026, 10, 1), [])
        self.assertEqual(self.handler.received, [])

    def test_senha_nunca_aparece_no_progresso(self):
        self.handler.report_body = b"Nome;Data/Hora\r\n"
        mensagens = []
        core.gerar_relatorio(
            self.ip, "admin", "segredo", date(2026, 10, 1), date(2026, 10, 1), ["Aline"],
            mensagens.append,
        )
        self.assertTrue(mensagens)
        self.assertFalse(any("segredo" in m or "sessao-teste" in m for m in mensagens))


class ListarUsuariosTests(ServerTestCase):
    def test_busca_os_nomes_sem_repetidos_e_em_ordem(self):
        self.handler.users_body = json.dumps({"users": [
            {"id": 1, "name": "Robert", "registration": ""},
            {"id": 2, "name": "  aline  "},
            {"id": 3, "name": "ALINE"},
            {"id": 4, "name": ""},
            {"id": 5},
            {"id": 6, "name": "João"},
        ]}).encode("utf-8")
        nomes = core.listar_usuarios(self.ip, "admin", "segredo")
        self.assertEqual(nomes, ["aline", "João", "Robert"])
        (_login, _), (path, body) = self.handler.received
        self.assertEqual(path, "/load_objects.fcgi?session=sessao-teste")
        self.assertEqual(body, {"object": "users"})

    def test_resposta_inesperada_tem_mensagem_clara(self):
        for body in (b"nao eh json", b'{"erro": 1}', b'{"users": [1, 2]}'):
            self.handler.users_body = body
            with self.assertRaisesRegex(core.CatracaError, "formato inesperado"):
                core.listar_usuarios(self.ip, "admin", "segredo")

    def test_login_recusado(self):
        self.handler.login_status = 401
        with self.assertRaisesRegex(core.CatracaError, "usuário e a senha"):
            core.listar_usuarios(self.ip, "admin", "errada")


class SemRedeTests(unittest.TestCase):
    def test_catraca_inacessivel_tem_mensagem_clara(self):
        # Sem as novas tentativas, para o teste não esperar os intervalos entre elas.
        original = core.criar_sessao_http
        core.criar_sessao_http = lambda: core.requests.Session()
        self.addCleanup(setattr, core, "criar_sessao_http", original)
        with self.assertRaisesRegex(core.CatracaError, "Confira o IP"):
            core.gerar_relatorio(
                "127.0.0.1:9", "a", "b", date(2026, 10, 1), date(2026, 10, 1), ["Aline"]
            )


class SalvarCsvTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.pasta = Path(temp.name)

    def test_formato_identico_ao_original(self):
        relatorio = core.montar_relatorio(
            [["Aline", "01/10/2026 08:00:00"], ["Visitante", "01/10/2026 08:01:00"],
             ["Braz", "01/10/2026 08:02:00"]],
            ["Aline", "Braz"], date(2026, 10, 1), date(2026, 10, 1),
        )
        destino = self.pasta / "r.csv"
        core.salvar_csv(relatorio, destino)
        self.assertEqual(
            destino.read_bytes(),
            b"Nome;Data/Hora\r\nAline;01/10/2026 08:00:00\r\nBraz;01/10/2026 08:02:00\r\n",
        )

    def test_pasta_inexistente_tem_mensagem_clara(self):
        relatorio = core.montar_relatorio([], [], date(2026, 1, 1), date(2026, 1, 1))
        with self.assertRaises(core.CatracaError):
            core.salvar_csv(relatorio, self.pasta / "nao" / "existe.csv")


class PeriodosTests(unittest.TestCase):
    def test_quinzena(self):
        self.assertEqual(core.quinzena_de(date(2026, 2, 15)), (date(2026, 2, 1), date(2026, 2, 15)))
        self.assertEqual(core.quinzena_de(date(2026, 2, 16)), (date(2026, 2, 16), date(2026, 2, 28)))

    def test_quinzena_anterior(self):
        self.assertEqual(
            core.quinzena_anterior(date(2026, 11, 3)), (date(2026, 10, 16), date(2026, 10, 31))
        )
        self.assertEqual(
            core.quinzena_anterior(date(2026, 11, 20)), (date(2026, 11, 1), date(2026, 11, 15))
        )
        self.assertEqual(
            core.quinzena_anterior(date(2026, 1, 10)), (date(2025, 12, 16), date(2025, 12, 31))
        )

    def test_mes_anterior_e_virada_de_ano(self):
        self.assertEqual(core.mes_anterior(date(2026, 3, 31)), (date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(core.mes_anterior(date(2026, 1, 5)), (date(2025, 12, 1), date(2025, 12, 31)))

    def test_ultimos_15_dias(self):
        self.assertEqual(core.ultimos_15_dias(date(2026, 11, 9)), (date(2026, 10, 25), date(2026, 11, 9)))

    def test_nome_sugerido_segue_o_padrao_dos_arquivos(self):
        self.assertEqual(
            core.nome_sugerido(date(2026, 8, 1), date(2026, 8, 15)), "Relatório 1° Quinzena Agosto.csv"
        )
        self.assertEqual(
            core.nome_sugerido(date(2026, 10, 16), date(2026, 10, 31)),
            "Relatório 2° Quinzena Outubro.csv",
        )
        self.assertEqual(core.nome_sugerido(date(2026, 3, 1), date(2026, 3, 31)), "Relatório Março.csv")
        self.assertEqual(
            core.nome_sugerido(date(2026, 3, 2), date(2026, 3, 9)),
            "Relatório 02-03-2026 a 09-03-2026.csv",
        )


class ColaboradoresTests(unittest.TestCase):
    def test_adiciona_normalizando_espacos(self):
        self.assertEqual(core.adicionar_colaborador(["Aline"], "  Maria   Silva "), ["Aline", "Maria Silva"])

    def test_recusa_vazio_e_repetido(self):
        with self.assertRaises(ValueError):
            core.adicionar_colaborador(["Aline"], "   ")
        with self.assertRaises(ValueError):
            core.adicionar_colaborador(["Aline"], "ALINE")

    def test_mesclar_mantem_a_ordem_e_ignora_repetidos(self):
        lista, novos = core.mesclar_usuarios(["Aline", "Braz"], ["BRAZ", " Carla  Dias ", "", "carla dias"])
        self.assertEqual(lista, ["Aline", "Braz", "Carla Dias"])
        self.assertEqual(novos, ["Carla Dias"])

    def test_lista_padrao_e_a_mais_recente_e_sem_repetidos(self):
        self.assertEqual(len(core.COLABORADORES_PADRAO), 20)
        self.assertIn("Nathalia Cezar", core.COLABORADORES_PADRAO)
        self.assertEqual(len({n.casefold() for n in core.COLABORADORES_PADRAO}), 20)


if __name__ == "__main__":
    unittest.main()
