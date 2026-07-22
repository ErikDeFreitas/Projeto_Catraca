"""
Interface grafica - Relatorio de acessos ControlID
Identidade visual: TCM Logistica & Transporte
====================================================

Roda localmente (tkinter, ja vem com o Python).
Permite escolher o periodo, ver o progresso e salvar o CSV onde quiser.

Como rodar:
    python relatorio_controlid_gui.py

Dependencias:
    pip install requests pillow

IMPORTANTE: mantenha o arquivo "logo_tcm.png" na mesma pasta deste script
para a logo aparecer na interface. Sem ele, a interface funciona normalmente,
so que sem a imagem da logo.
"""

import os
import csv
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime, timedelta
from calendar import monthrange

import requests
from requests.adapters import HTTPAdapter, Retry

try:
    from PIL import Image, ImageTk
    PIL_DISPONIVEL = True
except ImportError:
    PIL_DISPONIVEL = False


# ======================================
# IDENTIDADE VISUAL TCM
# ======================================

AZUL_TCM = "#18337B"
AZUL_TCM_ESCURO = "#0E2158"
VERMELHO_TCM = "#C8161D"
VERMELHO_TCM_HOVER = "#A81217"
CINZA_TCM = "#D1D2D4"
CINZA_CLARO = "#F4F5F7"
BRANCO = "#FFFFFF"
TEXTO_ESCURO = "#242424"

CAMINHO_LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo_tcm.png")

FONTE_TITULO = ("Segoe UI", 17, "bold")
FONTE_SUBTITULO = ("Segoe UI", 10)
FONTE_SECAO = ("Segoe UI", 10, "bold")
FONTE_BASE = ("Segoe UI", 9)


# ======================================
# LISTA DE USUARIOS (edite aqui se precisar)
# ======================================

USUARIOS = [
    "Agdo",
    "Aline",
    "Andreza",
    "Dario",
    "Edneya",
    "Equiberto",
    "Erivelto",
    "Gabriel Correa",
    "Givaldo",
    "Joao",
    "Marcos Oliveira",
    "Richard",
    "Robert",
    "Tiago Torre",
    "Wellington Souza",
]


# ======================================
# LOGICA DE ACESSO A API (mesma da versao anterior)
# ======================================

def cria_sessao_http():
    sessao = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    sessao.mount("http://", HTTPAdapter(max_retries=retries))
    sessao.mount("https://", HTTPAdapter(max_retries=retries))
    return sessao


def login(http, ip, usuario, senha, log_fn):
    log_fn(f"Conectando em {ip}...")
    resp = http.post(
        f"http://{ip}/login.fcgi",
        json={"login": usuario, "password": senha},
        timeout=30,
    )
    resp.raise_for_status()
    session_id = resp.json()["session"]
    log_fn(f"Sessao iniciada: {session_id}")
    return session_id


def consulta_acessos(http, ip, sessao, inicio_ts, fim_ts, log_fn):
    payload = {
        "object": "access_logs",
        "delimiter": ";",
        "line_break": "\r\n",
        "header": "Nome;Data/Hora",
        "where": [
            {
                "object": "access_logs",
                "field": "time",
                "operator": ">=",
                "value": inicio_ts,
                "connector": "AND",
            },
            {
                "object": "access_logs",
                "field": "time",
                "operator": "<=",
                "value": fim_ts,
            },
        ],
        "columns": [
            {"type": "object_field", "object": "users", "field": "name"},
            {
                "type": "object_field",
                "object": "access_logs",
                "field": "time",
                "format": {"format": "%d/%m/%Y %H:%M:%S"},
            },
        ],
    }

    log_fn("Consultando todos os acessos do periodo...")
    r = http.post(
        f"http://{ip}/report_generate.fcgi?session={sessao}",
        json=payload,
        timeout=300,
    )
    r.raise_for_status()
    r.encoding = r.encoding or "utf-8"
    linhas = r.text.splitlines()

    if not linhas:
        log_fn("Aviso: consulta nao retornou nenhuma linha.")
        return []

    reader = csv.reader(linhas[1:], delimiter=";")
    return list(reader)


def gerar_relatorio(ip, usuario, senha, data_inicio, data_fim, arquivo_saida, log_fn):
    inicio_ts = int(datetime.strptime(data_inicio, "%Y-%m-%d").timestamp())
    fim_ts = int(
        (
            datetime.strptime(data_fim, "%Y-%m-%d")
            + timedelta(hours=23, minutes=59, seconds=59)
        ).timestamp()
    )

    http = cria_sessao_http()
    sessao = login(http, ip, usuario, senha, log_fn)
    todas_linhas = consulta_acessos(http, ip, sessao, inicio_ts, fim_ts, log_fn)

    usuarios_lower = {u.lower(): u for u in USUARIOS}
    contagem = {u: 0 for u in USUARIOS}
    linhas_filtradas = []

    for linha in todas_linhas:
        if not linha:
            continue
        nome_lower = linha[0].strip().lower()
        if nome_lower in usuarios_lower:
            nome_original = usuarios_lower[nome_lower]
            contagem[nome_original] += 1
            linhas_filtradas.append(linha)

    with open(arquivo_saida, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter=";", lineterminator="\r\n")
        writer.writerow(["Nome", "Data/Hora"])
        writer.writerows(linhas_filtradas)

    log_fn(f"Relatorio salvo em: {arquivo_saida}")
    log_fn(f"Total de registros: {len(linhas_filtradas)}")
    log_fn("")
    log_fn("Registros por pessoa:")
    for nome, qtd in contagem.items():
        marcador = "  " if qtd > 0 else "  [SEM REGISTRO] "
        log_fn(f"{marcador}{nome}: {qtd}")

    sem_registro = [u for u, c in contagem.items() if c == 0]
    return sem_registro


# ======================================
# UTILITARIOS DE DATA
# ======================================

def quinzena_atual():
    hoje = datetime.now()
    ultimo_dia = monthrange(hoje.year, hoje.month)[1]
    if hoje.day <= 15:
        ini = hoje.replace(day=1)
        fim = hoje.replace(day=15)
    else:
        ini = hoje.replace(day=16)
        fim = hoje.replace(day=ultimo_dia)
    return ini.strftime("%Y-%m-%d"), fim.strftime("%Y-%m-%d")


# ======================================
# INTERFACE GRAFICA
# ======================================

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TCM Logistica & Transporte  |  Relatorio de Acessos")
        self.geometry("660x640")
        self.minsize(660, 640)
        self.configure(bg=CINZA_CLARO)

        self.fila_log = queue.Queue()
        self.arquivo_saida = tk.StringVar(value="Relatorio_ControlID.csv")

        self._configurar_estilo()
        self._montar_cabecalho()
        self._montar_widgets()
        self._montar_rodape()
        self._processa_fila_log()

    # ------------------------------------------------------------
    # ESTILO (ttk theme customizado com as cores da TCM)
    # ------------------------------------------------------------
    def _configurar_estilo(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure(
            "TLabelframe",
            background=CINZA_CLARO,
            bordercolor=CINZA_TCM,
            relief="solid",
            borderwidth=1,
        )
        style.configure(
            "TLabelframe.Label",
            background=CINZA_CLARO,
            foreground=AZUL_TCM,
            font=FONTE_SECAO,
        )
        style.configure("TFrame", background=CINZA_CLARO)
        style.configure("TLabel", background=CINZA_CLARO, foreground=TEXTO_ESCURO, font=FONTE_BASE)
        style.configure("TEntry", fieldbackground=BRANCO, bordercolor=CINZA_TCM, padding=4)

        # Botao principal (vermelho TCM)
        style.configure(
            "TCM.TButton",
            background=VERMELHO_TCM,
            foreground=BRANCO,
            font=("Segoe UI", 11, "bold"),
            padding=(14, 10),
            borderwidth=0,
        )
        style.map(
            "TCM.TButton",
            background=[("active", VERMELHO_TCM_HOVER), ("disabled", CINZA_TCM)],
            foreground=[("disabled", "#8a8a8a")],
        )

        # Botoes secundarios (azul TCM, contorno)
        style.configure(
            "TCMSecundario.TButton",
            background=BRANCO,
            foreground=AZUL_TCM,
            font=("Segoe UI", 9, "bold"),
            padding=(8, 6),
            bordercolor=AZUL_TCM,
            borderwidth=1,
        )
        style.map(
            "TCMSecundario.TButton",
            background=[("active", CINZA_CLARO)],
        )

        # Barra de progresso
        style.configure(
            "TCM.Horizontal.TProgressbar",
            background=VERMELHO_TCM,
            troughcolor=CINZA_TCM,
            bordercolor=CINZA_TCM,
            lightcolor=VERMELHO_TCM,
            darkcolor=VERMELHO_TCM,
        )

    # ------------------------------------------------------------
    # CABECALHO (logo + faixa azul/vermelha, como no papel timbrado)
    # ------------------------------------------------------------
    def _montar_cabecalho(self):
        topo = tk.Frame(self, bg=AZUL_TCM, height=6)
        topo.pack(fill="x", side="top")

        cabecalho = tk.Frame(self, bg=BRANCO)
        cabecalho.pack(fill="x", side="top")

        interno = tk.Frame(cabecalho, bg=BRANCO)
        interno.pack(fill="x", padx=20, pady=14)

        self._logo_img = None
        if PIL_DISPONIVEL and os.path.exists(CAMINHO_LOGO):
            try:
                img = Image.open(CAMINHO_LOGO).convert("RGBA")
                altura_alvo = 56
                proporcao = altura_alvo / img.height
                img = img.resize((int(img.width * proporcao), altura_alvo))
                self._logo_img = ImageTk.PhotoImage(img)
                tk.Label(interno, image=self._logo_img, bg=BRANCO).pack(side="left")
            except Exception:
                self._logo_img = None

        if self._logo_img is None:
            tk.Label(
                interno, text="TCM", bg=BRANCO, fg=VERMELHO_TCM,
                font=("Segoe UI", 26, "bold italic"),
            ).pack(side="left")

        bloco_titulo = tk.Frame(interno, bg=BRANCO)
        bloco_titulo.pack(side="left", padx=16)
        tk.Label(
            bloco_titulo, text="Relatorio de Acessos", bg=BRANCO, fg=AZUL_TCM,
            font=FONTE_TITULO,
        ).pack(anchor="w")
        tk.Label(
            bloco_titulo, text="Catraca ControlID  -  TCM Logistica & Transporte",
            bg=BRANCO, fg="#666666", font=FONTE_SUBTITULO,
        ).pack(anchor="w")

        faixa = tk.Frame(self, height=4, bg=VERMELHO_TCM)
        faixa.pack(fill="x", side="top")

    # ------------------------------------------------------------
    # RODAPE (faixa dupla igual ao topo, remete ao padrao TCM)
    # ------------------------------------------------------------
    def _montar_rodape(self):
        faixa_vermelha = tk.Frame(self, height=4, bg=VERMELHO_TCM)
        faixa_vermelha.pack(fill="x", side="bottom")
        faixa_azul = tk.Frame(self, height=6, bg=AZUL_TCM)
        faixa_azul.pack(fill="x", side="bottom")

    # ------------------------------------------------------------
    # CORPO PRINCIPAL
    # ------------------------------------------------------------
    def _montar_widgets(self):
        pad = {"padx": 10, "pady": 6}

        corpo = ttk.Frame(self)
        corpo.pack(fill="both", expand=True, padx=16, pady=10)

        # --- Conexao ---
        frame_conexao = ttk.LabelFrame(corpo, text="  Conexao com a catraca  ")
        frame_conexao.pack(fill="x", pady=(0, 8))

        ttk.Label(frame_conexao, text="IP:").grid(row=0, column=0, sticky="w", **pad)
        self.ip_var = tk.StringVar(value="192.168.0.130")
        ttk.Entry(frame_conexao, textvariable=self.ip_var, width=20).grid(
            row=0, column=1, sticky="w", **pad
        )

        ttk.Label(frame_conexao, text="Usuario:").grid(row=0, column=2, sticky="w", **pad)
        self.usuario_var = tk.StringVar(value="admin")
        ttk.Entry(frame_conexao, textvariable=self.usuario_var, width=15).grid(
            row=0, column=3, sticky="w", **pad
        )

        ttk.Label(frame_conexao, text="Senha:").grid(row=1, column=2, sticky="w", **pad)
        self.senha_var = tk.StringVar(value="")
        ttk.Entry(frame_conexao, textvariable=self.senha_var, show="*", width=15).grid(
            row=1, column=3, sticky="w", **pad
        )

        # --- Periodo ---
        frame_periodo = ttk.LabelFrame(corpo, text="  Periodo do relatorio  ")
        frame_periodo.pack(fill="x", pady=8)

        ini, fim = quinzena_atual()

        ttk.Label(frame_periodo, text="Data inicial (AAAA-MM-DD):").grid(
            row=0, column=0, sticky="w", **pad
        )
        self.inicio_var = tk.StringVar(value=ini)
        ttk.Entry(frame_periodo, textvariable=self.inicio_var, width=14).grid(
            row=0, column=1, sticky="w", **pad
        )

        ttk.Label(frame_periodo, text="Data final (AAAA-MM-DD):").grid(
            row=0, column=2, sticky="w", **pad
        )
        self.fim_var = tk.StringVar(value=fim)
        ttk.Entry(frame_periodo, textvariable=self.fim_var, width=14).grid(
            row=0, column=3, sticky="w", **pad
        )

        atalhos = ttk.Frame(frame_periodo)
        atalhos.grid(row=1, column=0, columnspan=4, sticky="w", padx=6, pady=(0, 8))
        ttk.Button(
            atalhos, text="Quinzena atual", style="TCMSecundario.TButton",
            command=self._preencher_quinzena_atual,
        ).pack(side="left", padx=4)
        ttk.Button(
            atalhos, text="Mes atual completo", style="TCMSecundario.TButton",
            command=self._preencher_mes_atual,
        ).pack(side="left", padx=4)
        ttk.Button(
            atalhos, text="Ultimos 15 dias", style="TCMSecundario.TButton",
            command=self._preencher_ultimos_15,
        ).pack(side="left", padx=4)

        # --- Arquivo de saida ---
        frame_saida = ttk.LabelFrame(corpo, text="  Arquivo de saida  ")
        frame_saida.pack(fill="x", pady=8)
        ttk.Entry(frame_saida, textvariable=self.arquivo_saida, width=45).grid(
            row=0, column=0, sticky="w", **pad
        )
        ttk.Button(
            frame_saida, text="Escolher...", style="TCMSecundario.TButton",
            command=self._escolher_arquivo,
        ).grid(row=0, column=1, **pad)

        # --- Botao gerar ---
        self.btn_gerar = ttk.Button(
            corpo, text="GERAR RELATORIO", style="TCM.TButton",
            command=self._ao_clicar_gerar,
        )
        self.btn_gerar.pack(pady=10)

        self.progress = ttk.Progressbar(corpo, mode="indeterminate", style="TCM.Horizontal.TProgressbar")
        self.progress.pack(fill="x")

        # --- Log ---
        frame_log = ttk.LabelFrame(corpo, text="  Andamento  ")
        frame_log.pack(fill="both", expand=True, pady=(10, 0))
        self.texto_log = tk.Text(
            frame_log, height=12, state="disabled", bg=BRANCO, fg=TEXTO_ESCURO,
            insertbackground=TEXTO_ESCURO, relief="flat", font=("Consolas", 9),
            highlightthickness=1, highlightbackground=CINZA_TCM,
        )
        self.texto_log.pack(fill="both", expand=True, padx=6, pady=6)

    # --- atalhos de data ---
    def _preencher_quinzena_atual(self):
        ini, fim = quinzena_atual()
        self.inicio_var.set(ini)
        self.fim_var.set(fim)

    def _preencher_mes_atual(self):
        hoje = datetime.now()
        ultimo_dia = monthrange(hoje.year, hoje.month)[1]
        self.inicio_var.set(hoje.replace(day=1).strftime("%Y-%m-%d"))
        self.fim_var.set(hoje.replace(day=ultimo_dia).strftime("%Y-%m-%d"))

    def _preencher_ultimos_15(self):
        hoje = datetime.now()
        self.inicio_var.set((hoje - timedelta(days=15)).strftime("%Y-%m-%d"))
        self.fim_var.set(hoje.strftime("%Y-%m-%d"))

    def _escolher_arquivo(self):
        caminho = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile=self.arquivo_saida.get(),
        )
        if caminho:
            self.arquivo_saida.set(caminho)

    # --- log thread-safe ---
    def _log(self, mensagem):
        self.fila_log.put(mensagem)

    def _processa_fila_log(self):
        try:
            while True:
                msg = self.fila_log.get_nowait()
                self.texto_log.configure(state="normal")
                self.texto_log.insert("end", msg + "\n")
                self.texto_log.see("end")
                self.texto_log.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(150, self._processa_fila_log)

    # --- acao principal ---
    def _ao_clicar_gerar(self):
        ip = self.ip_var.get().strip()
        usuario = self.usuario_var.get().strip()
        senha = self.senha_var.get()
        inicio = self.inicio_var.get().strip()
        fim = self.fim_var.get().strip()
        saida = self.arquivo_saida.get().strip()

        try:
            datetime.strptime(inicio, "%Y-%m-%d")
            datetime.strptime(fim, "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Data invalida", "Use o formato AAAA-MM-DD nas datas.")
            return

        if not usuario or not senha:
            messagebox.showerror("Faltam dados", "Preencha usuario e senha da catraca.")
            return

        self.btn_gerar.configure(state="disabled")
        self.progress.start(10)
        self.texto_log.configure(state="normal")
        self.texto_log.delete("1.0", "end")
        self.texto_log.configure(state="disabled")

        thread = threading.Thread(
            target=self._executar_em_thread,
            args=(ip, usuario, senha, inicio, fim, saida),
            daemon=True,
        )
        thread.start()

    def _executar_em_thread(self, ip, usuario, senha, inicio, fim, saida):
        try:
            sem_registro = gerar_relatorio(
                ip, usuario, senha, inicio, fim, saida, self._log
            )
            self._log("")
            self._log("Concluido com sucesso.")
            self.after(0, lambda: self._ao_terminar(sucesso=True, sem_registro=sem_registro))
        except requests.RequestException as e:
            self._log(f"ERRO de conexao/API: {e}")
            self.after(0, lambda: self._ao_terminar(sucesso=False))
        except Exception as e:
            self._log(f"ERRO inesperado: {e}")
            self.after(0, lambda: self._ao_terminar(sucesso=False))

    def _ao_terminar(self, sucesso, sem_registro=None):
        self.progress.stop()
        self.btn_gerar.configure(state="normal")
        if sucesso:
            aviso = ""
            if sem_registro:
                aviso = (
                    "\n\nSem nenhum registro no periodo (confira o nome cadastrado):\n"
                    + ", ".join(sem_registro)
                )
            messagebox.showinfo(
                "Relatorio gerado", f"Arquivo salvo em:\n{self.arquivo_saida.get()}{aviso}"
            )
        else:
            messagebox.showerror(
                "Falha ao gerar relatorio",
                "Confira o log na tela principal para detalhes do erro.",
            )


if __name__ == "__main__":
    App().mainloop()