"""A janela principal: layout, ciclo de vida e montagem dos cards.

Cada card vive no seu modulo, como mixin. Sao mixins e nao componentes
separados porque os widgets ainda sao atributos da janela -- a divisao aqui e
do CODIGO, nao do estado. O estado de cada eixo mora no Eixo (ui/eixo.py) e a
regra de movimento em jog_gui.motion.
"""


from tkinter import ttk
import threading
import tkinter as tk

from jog_gui.motion import FRENTE
from jog_gui.str6 import MALHA_ABERTA, RAMPA_MS

from .tema import (
    ACCENT,
    BG,
    BG2,
    BORDER,
    FONT_BOLD,
    FONT_TITLE,
    GREEN,
    RED,
    TEXT_DIM,
    YELLOW,
)

from .eixo import HOME_ENTRADA_NEG, HOME_MODO_NATIVO
from .sensores import PADRAO as SENSOR_PADRAO
from .conexao import ConexaoMixin
from .drives import DrivesMixin
from .motor import MotorMixin
from .corrente import CorrenteMixin
from .jog import JogMixin
from .status import StatusMixin
from .homing import HomingMixin
from .curso import CursoMixin
from .inspetor import InspetorMixin
from .log import LogMixin


class JogApp(DrivesMixin, ConexaoMixin, MotorMixin, CorrenteMixin, JogMixin,
             StatusMixin, HomingMixin, CursoMixin, InspetorMixin, LogMixin,
             tk.Tk):
    """A janela unica da aplicacao: um card por mixin, um eixo ativo por vez.

    Herda de todos os mixins de card. Cada um contribui com:

      - um metodo _card_<nome>(parent) que monta os widgets;
      - os metodos de acao daquele card;
      - os widgets que ele cria, como atributos desta janela.

    Consequencia da heranca multipla: um nome definido em dois mixins seria
    resolvido silenciosamente pela ordem da MRO. Hoje nao ha nenhum, e
    tests/test_mixins.py existe para manter assim.

    O estado que pertence a UM eixo (configuracao, homing, limites, armado,
    zero) vive no Eixo correspondente e chega aqui por propriedades do
    DrivesMixin -- `self.motor_on` grava no eixo certo. O que e global de
    verdade fica em atributos desta classe: a porta serial, o barramento, o
    inspetor e as flags de operacao em curso.

    Toda thread que fala com o drive deve nascer de `self._thread_op(...)`,
    nunca de `threading.Thread(...)` direto: e o que congela o endereco do
    drive pela duracao da operacao.
    """

    def __init__(self):
        """Monta o estado, os cards e a janela, nesta ordem.

        O cadastro de eixos e carregado ANTES de `_build_ui`, porque a barra de
        visao geral e o card de drives sao montados a partir dele. O
        dimensionamento da janela fica para um `after`: chamado direto daqui, o
        Tk ainda nao mapeou os widgets e a janela abria no minsize.
        """
        super().__init__()
        self.title("STR6-RS485  JOG + Homing  |  Modbus RTU RS485")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(640, 400)

        # Estado
        self.bus = None
        self.slave        = tk.IntVar(value=1)
        self.port_var     = tk.StringVar()
        self.baud_var     = tk.StringVar(value="9600")
        self.speed_var    = tk.IntVar(value=3000)     # pulsos/s do JOG
        self.direction    = tk.StringVar(value=FRENTE)
        self.rampa_ms     = tk.IntVar(value=RAMPA_MS)  # rampa de acel/desacel
        # motor_on, zero_valido, _malha_lida e _status_lido sao propriedades
        # delegadas ao eixo ativo (DrivesMixin) -- sao estado DELE, nao da
        # janela.
        self.jog_active   = False
        self._poll_after  = None
        self._poll_tick   = 0
        self._poll_em_voo = False      # um ciclo do monitor ainda rodando?
        self._secundario_mudo_ate = {}  # eixo -> hora em que volta ao rodizio
        self._jog_lock    = threading.Lock()
        # Endereco do drive congelado por operacao (ver _thread_op)
        self._slave_local = threading.local()
        # Fila de movimento: uma unica thread envia os comandos de JOG, na ordem
        self._mov_lock    = threading.Lock()
        self._mov_alvo    = None
        self._mov_evt     = threading.Event()
        # Thread perpetua: nao usa _thread_op porque nao ha uma operacao cujo
        # endereco congelar - cada pedido na fila carrega o seu.
        threading.Thread(target=self._loop_movimento, daemon=True).start()

        # Configuracao do drive (registradores 1, 2, 3, 13, 15, 16, 24, 26).
        # A corrente se ajusta pelo 26; o 0 so e lido (ver registradores).
        self.corr_oper_pct = tk.IntVar(value=50)     # % (reg 26)
        self.corr_standby  = tk.IntVar(value=50)     # %
        self.standby_ms    = tk.IntVar(value=300)    # ms
        self.modo_malha    = tk.IntVar(value=MALHA_ABERTA)
        self.autoajuste    = tk.IntVar(value=1)
        # Kp/Ki so sao gravaveis com o autoajuste desligado (manual p. 13), e
        # um ganho errado desregula a malha de corrente: a gravacao fica atras
        # de uma trava, e a leitura e livre.
        self.ganho_p       = tk.IntVar(value=1000)
        self.ganho_i       = tk.IntVar(value=200)
        self.ganhos_edit   = tk.IntVar(value=0)

        # Homing (retorno ao zero) com o sensor numa entrada de limite
        self.sensor_tipo  = tk.StringVar(value=SENSOR_PADRAO)
        self.home_modo    = tk.StringVar(value=HOME_MODO_NATIVO)
        self.home_entrada = tk.StringVar(value=HOME_ENTRADA_NEG)
        self.home_inv     = tk.IntVar(value=0)     # nivel invertido (reg 73)
        # Filtro baixo de proposito: o garfo responde rapido e a janela de
        # deteccao e estreita (bandeira dentro dos 5 mm).
        self.home_filtro  = tk.IntVar(value=2)     # ms (reg 74, x 50 us)
        self.home_v_apr   = tk.IntVar(value=6000)  # p/s de aproximacao (64/65)
        self.home_v_ras   = tk.IntVar(value=1000)  # p/s de rastejo (60)
        self.home_ativo   = False
        self.teste_ativo  = False                  # teste do sensor em andamento
        self._teste_grav_ativo = False             # teste de religamento em andamento
        self._monitor_pausado_teste = False        # o teste parou o monitor?
        self._mov_home    = None                   # EixoMovimento do homing em curso

        # Curso e limites por software (em pulsos, contados a partir do zero)
        self.lim_pos      = tk.IntVar(value=0)     # pulsos acima do zero
        self.lim_neg      = tk.IntVar(value=0)     # pulsos abaixo do zero
        self.lim_ppr      = tk.IntVar(value=6000)  # pulsos/volta (reg 1)
        self.lim_margem   = tk.IntVar(value=400)   # antecipacao da parada
        self.lim_tol      = tk.IntVar(value=40)    # tolerancia no alvo
        self.lim_ativo    = tk.IntVar(value=0)     # aplicar os limites
        self.curso_sent_pos = tk.StringVar(value=FRENTE)  # sentido que soma
        self.curso_alvo   = tk.IntVar(value=0)     # alvo do posicionamento
        self.curso_v_rap  = tk.IntVar(value=20000) # p/s longe do alvo
        self.curso_v_len  = tk.IntVar(value=6000)  # p/s dentro da janela
        self.curso_janela = tk.IntVar(value=1500)  # pulsos em que passa ao lento
        self.passo_pulsos = tk.IntVar(value=200)   # tamanho do jog por pulsos
        self.passo_vel    = tk.IntVar(value=3000)  # p/s do jog por pulsos
        self.curso_mov    = False                  # posicionamento em andamento
        self._mov_curso   = None                   # EixoMovimento em curso
        self._curso_pos_atual = None               # ultima posicao conhecida
        self._curso_pos_ts = 0.0                   # quando ela foi lida
        self._btns_atalho_curso = []

        # Seguranca: o ultimo degrau da parada escalonada desabilita o motor,
        # o que num eixo vertical derruba a carga. Por eixo.
        self.soltar_emerg = tk.IntVar(value=1)

        # Inspetor de registrador: acompanha um endereco especifico e avisa
        # quando o valor muda (inclusive quando muda sem ninguem escrever)
        self.reg_endereco   = tk.StringVar(value="24")
        self.reg_intervalo  = tk.IntVar(value=500)
        self.reg_vigiando   = False
        self._reg_ultimo    = None
        self._reg_ultimo_end = None   # a qual endereco o ultimo valor pertence
        self._reg_mudancas  = 0

        # O cadastro alimenta o card de drives e a barra de eixos,
        # entao precisa estar carregado antes da UI existir.
        self._carregar_eixos()
        self._build_ui()
        self._refresh_ports()
        # Depois que o Tk mapeia a janela: chamado direto no __init__, o tamanho
        # era descartado e a janela abria no minsize
        self.after(60, self._ajustar_janela)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # --- UI -------------------------------------------------------------------

    def _build_ui(self):
        """Monta cabecalho, barra de eixos, area rolavel e as tres colunas.

        A barra de eixos fica FORA do canvas rolavel, de proposito: ela e a
        visao geral do barramento e precisa continuar visivel enquanto o painel
        detalhado rola.
        """
        # Header
        hdr = tk.Frame(self, bg=BG, pady=10)
        hdr.pack(fill="x", padx=20)
        tk.Label(hdr, text="  STR6-RS485  JOG Control", font=FONT_TITLE,
                 bg=BG, fg=ACCENT).pack(side="left")
        self.lbl_status = tk.Label(hdr, text="Desconectado", font=FONT_BOLD,
                                   bg=BG, fg=RED)
        self.lbl_status.pack(side="right")

        sep = tk.Frame(self, bg=BORDER, height=1)
        sep.pack(fill="x", padx=20)

        # Visao geral dos eixos: fixa, fora do canvas, para continuar visivel
        # enquanto o painel detalhado do eixo ativo rola.
        self._barra_eixos(self)

        # Area rolavel: em telas baixas os cards nao cabem de uma vez, e sem isso
        # o que sobra fica inacessivel
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True)
        self._canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0)
        barra_v = ttk.Scrollbar(wrap, orient="vertical", command=self._canvas.yview)
        barra_h = ttk.Scrollbar(wrap, orient="horizontal", command=self._canvas.xview)
        barra_v.pack(side="right", fill="y")
        barra_h.pack(side="bottom", fill="x")
        self._canvas.pack(side="left", fill="both", expand=True)
        self._canvas.configure(yscrollcommand=barra_v.set, xscrollcommand=barra_h.set)

        main = tk.Frame(self._canvas, bg=BG)
        self._main = main       # medido em _ajustar_janela (o canvas nao propaga)
        self._topo = (hdr, sep)
        self._janela_main = self._canvas.create_window((0, 0), window=main, anchor="nw")
        main.bind("<Configure>", lambda e: self._canvas.configure(
            scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", self._on_canvas_resize)
        self.bind_all("<MouseWheel>", self._on_mousewheel)

        # Tres colunas: com duas, a da direita sozinha passava da altura da tela.
        # expand=False de proposito: com expand, o pack redistribui a largura e
        # espremia o card de homing (o mais largo), cortando os campos.
        col1 = tk.Frame(main, bg=BG)
        col1.pack(side="left", fill="y", anchor="n", padx=(20, 5), pady=10)
        col2 = tk.Frame(main, bg=BG)
        col2.pack(side="left", fill="y", anchor="n", padx=5, pady=10)
        col3 = tk.Frame(main, bg=BG)
        col3.pack(side="left", fill="y", anchor="n", padx=(5, 20), pady=10)

        self._card_drives(col1)
        self._card_conexao(col1)
        self._card_motor(col1)
        self._card_corrente(col1)

        self._card_jog(col2)
        self._card_status(col2)
        self._card_inspetor(col2)
        self._card_log(col2)

        # O card de curso fica embaixo do homing, e nao em uma quarta coluna:
        # com quatro colunas a janela passava da largura da tela.
        self._card_homing(col3)
        # o card acabou de nascer: traz a fiacao e o bloqueio do eixo ativo
        self._atualizar_painel_sensor()
        self._card_curso(col3)

    def _on_canvas_resize(self, event):
        """
        Acompanha a largura da janela sem nunca espremer o conteudo: se a janela
        for menor que os cards, o canvas rola na horizontal em vez de cortar.
        """
        self._canvas.itemconfigure(
            self._janela_main, width=max(event.width, self._main.winfo_reqwidth()))

    def _on_mousewheel(self, event):
        """Roda do mouse rola a pagina - menos sobre o log, que rola sozinho."""
        alvo = self.winfo_containing(event.x_root, event.y_root)
        w = alvo
        while w is not None:
            if w is self.txt_log:
                return
            w = getattr(w, "master", None)
        self._canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def _ajustar_janela(self):
        """
        Dimensiona a janela pelo que os cards pedem, sem passar do que a tela
        comporta (com folga para barra de tarefas e bordas).
        """
        self.update_idletasks()
        self.update_idletasks()   # a primeira passada ainda traz medidas antigas
        larg_tela = self.winfo_screenwidth()
        alt_tela  = self.winfo_screenheight()
        # O conteudo vive dentro do canvas, que nao repassa o tamanho pedido.
        # As folgas cobrem as barras de rolagem e a borda da janela.
        conteudo_larg = self._main.winfo_reqwidth() + 40
        conteudo_alt  = self._main.winfo_reqheight() + 44 + sum(
            w.winfo_reqheight() for w in self._topo)
        larg = min(conteudo_larg, int(larg_tela * 0.95))
        alt  = min(conteudo_alt, int(alt_tela * 0.90))
        x = max(0, (larg_tela - larg) // 2)
        y = max(0, (alt_tela - alt) // 3)
        self.geometry("{}x{}+{}+{}".format(larg, alt, x, y))

    def _card(self, parent, title):
        """Cria o LabelFrame padrao de um card e o empacota no `parent`.

        Todo card da tela passa por aqui -- e o que garante a mesma moldura,
        cor e titulo centralizado em todos eles.
        """
        frame = tk.LabelFrame(parent, text="  {}  ".format(title), bg=BG2,
                              fg=ACCENT, font=FONT_BOLD,
                              relief="solid", bd=1,
                              highlightbackground=BORDER,
                              labelanchor="n", pady=8, padx=10)
        frame.pack(fill="x", pady=6)
        return frame

    @staticmethod
    def _ivar(var, padrao=0) -> int:
        """
        Valor de um Spinbox como inteiro, sem quebrar com o campo vazio.

        Enquanto se digita, o campo passa por estados invalidos ("" ou "-") e
        IntVar.get() levanta TclError. Isso abortaria o Salvar limites no
        meio, deixando o arquivo sem o valor recem-digitado.
        """
        try:
            return int(var.get())
        except (tk.TclError, ValueError):
            return padrao

    def _set_connected(self, connected: bool):
        """Liga ou desliga, em bloco, tudo que so faz sentido com o drive aberto.

        Conectando, habilita os botoes de operacao e devolve o comando a
        `_aplicar_restricao_sensor`: um eixo marcado como "Sem sensor" nao pode
        sair daqui com o homing clicavel.

        Desconectando, faz mais do que desabilitar botoes -- zera as flags de
        operacao (jog, homing, teste, posicionamento, vigilancia) e invalida o
        zero. Sem isso, uma rotina interrompida pela queda da porta continuaria
        se achando em andamento na proxima conexao.
        """
        botoes = [self.btn_motor_on, self.btn_motor_off, self.btn_poll,
                  self.btn_reset_alarm, self.btn_ler_corr, self.btn_gravar_corr,
                  self.btn_testar_grav, self.btn_grava_di, self.btn_home, self.btn_teste_di,
                  self.btn_le_di, self.btn_cap_pos, self.btn_cap_neg,
                  self.btn_detectar, self.btn_ir, self.btn_reg_ler,
                  self.btn_reg_vigiar] + self._btns_atalho_curso
        if connected:
            self.lbl_status.config(text="Conectado", fg=GREEN)
            self.btn_connect.config(text="DESCONECTAR", bg=RED)
            for w in botoes:
                w.config(state="normal")
            self.btn_home_stop.config(state="disabled")
            self.btn_ir_stop.config(state="disabled")
            # Liga tudo em bloco; um eixo sem sensor de origem nao pode sair
            # daqui com o homing habilitado.
            self._aplicar_restricao_sensor()
        else:
            self.motor_on = False
            self.jog_active = False
            self.home_ativo = False
            self.teste_ativo = False
            self._teste_grav_ativo = False
            self.curso_mov = False
            self.reg_vigiando = False
            for eixo in self.eixos.values():
                eixo.zero_valido = False
                eixo.armado = False
            self._desligar_drives()
            self.bus = None
            self.lbl_status.config(text="Desconectado", fg=RED)
            self.btn_connect.config(text="CONECTAR", bg=ACCENT)
            for w in botoes + [self.btn_jog, self.btn_home_stop, self.btn_ir_stop]:
                w.config(state="disabled")
            self.btn_home.config(text="INICIAR HOMING")
            self.btn_teste_di.config(text="TESTAR SENSOR", bg=YELLOW)
            self.lbl_motor_state.config(text="Motor: ---", fg=TEXT_DIM)
            self.lbl_jog_state.config(text="JOG: parado", fg=TEXT_DIM)
            self.lbl_sensor.config(text="Sensor: --- (ligue o monitor)", fg=TEXT_DIM)
            self.lbl_curso_pos.config(text="Posicao: ---  (ligue o monitor)",
                                      fg=TEXT_DIM)
            self.lbl_curso_status.config(text="Curso: parado", fg=TEXT_DIM)
            self._malha_lida = None
            self._badge_malha()
            self._curso_resumo()

    # --- FECHAMENTO -----------------------------------------------------------

    def _on_close(self):
        """Desabilita todos os eixos, desconecta, salva o cadastro e fecha.

        A desabilitacao vai ANTES de desconectar, enquanto ainda ha porta
        aberta: fechar a janela deixando um eixo armado significa motor
        energizado e esquentando sem ninguem olhando.

        Atencao nesta mecanica: o eixo e vertical. Desabilitar o motor corta
        o torque de retencao e a carga desce.
        """
        if self._conectado:
            self._desarmar_todos_silencioso()
            self._disconnect()
        self._salvar_eixos()
        self.destroy()
