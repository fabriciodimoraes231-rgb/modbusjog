"""Card CONTROLE JOG: jog continuo, watchdog e a fila de movimento."""

from tkinter import messagebox
import time
import tkinter as tk

from jog_gui.motion import CAUSA_DRIVE_MUDO, FRENTE, TRAS, MovimentoRecusado
from jog_gui.str6 import VEL_MAX_PPS

from .tema import (
    ACCENT,
    BG2,
    BG3,
    FONT_BOLD,
    FONT_JOG,
    FONT_LABEL,
    JOG_ACTIVE,
    JOG_CLR,
    RED,
    TEXT,
    TEXT_DIM,
    YELLOW,
    fonte,
    vel_txt,
)


class JogMixin:
    """Card CONTROLE JOG: jog continuo, watchdog e a fila de movimento."""


    def _card_jog(self, parent):
        """Monta o card: sentido, velocidade, rampa e o botao de JOG continuo.

        O botao nao tem `command`: ele reage a pressionar e soltar
        (<ButtonPress-1>/<ButtonRelease-1>), porque o eixo so deve andar
        enquanto o operador mantiver o dedo nele.
        """
        f = self._card(parent, "CONTROLE JOG")

        row_dir = tk.Frame(f, bg=BG2)
        row_dir.pack(fill="x", pady=3)
        tk.Label(row_dir, text="Sentido:", bg=BG2, fg=TEXT, font=FONT_LABEL, width=10, anchor="w").pack(side="left")
        for txt, val in [("<<  TRAS", TRAS), ("FRENTE  >>", FRENTE)]:
            rb = tk.Radiobutton(row_dir, text=txt, variable=self.direction, value=val,
                                bg=BG2, fg=TEXT, selectcolor=BG3, activebackground=BG2,
                                font=FONT_LABEL)
            rb.pack(side="left", padx=6)

        row_spd = tk.Frame(f, bg=BG2)
        row_spd.pack(fill="x", pady=3)
        tk.Label(row_spd, text="Velocidade:", bg=BG2, fg=TEXT, font=FONT_LABEL, width=10, anchor="w").pack(side="left")
        self.lbl_speed_val = tk.Label(row_spd, text="", bg=BG2, fg=ACCENT,
                                      font=FONT_BOLD, width=20)
        self.lbl_speed_val.pack(side="right")
        self.sl_speed = tk.Scale(row_spd, from_=100, to=VEL_MAX_PPS, resolution=100,
                                 orient="horizontal",
                                 variable=self.speed_var, bg=BG2, fg=TEXT,
                                 troughcolor=BG3, highlightthickness=0,
                                 sliderlength=18, showvalue=False,
                                 command=self._on_speed_change)
        self.sl_speed.pack(side="left", fill="x", expand=True)
        self._on_speed_change(self._ivar(self.speed_var, 3000))
        # O rpm do rotulo depende dos pulsos por volta, que mudam ao ler o drive
        self.lim_ppr.trace_add("write", lambda *_: self._on_speed_change(
            self._ivar(self.speed_var, 3000)))

        row_rampa = tk.Frame(f, bg=BG2)
        row_rampa.pack(fill="x", pady=3)
        tk.Label(row_rampa, text="Rampa:", bg=BG2, fg=TEXT, font=FONT_LABEL,
                 width=10, anchor="w").pack(side="left")
        tk.Spinbox(row_rampa, from_=10, to=5000, increment=10,
                   textvariable=self.rampa_ms, width=7, bg=BG3, fg=TEXT,
                   buttonbackground=BG3, insertbackground=TEXT, relief="flat",
                   font=FONT_LABEL).pack(side="left")
        tk.Label(row_rampa, text="ms de 0 ate a velocidade (acel = desacel)",
                 bg=BG2, fg=TEXT_DIM, font=FONT_LABEL).pack(side="left", padx=4)

        self.btn_jog = tk.Button(f, text="JOG\n(pressione e segure)",
                                 font=FONT_JOG,
                                 bg=JOG_CLR, fg="white", bd=0,
                                 pady=20, cursor="hand2",
                                 state="disabled")
        self.btn_jog.pack(fill="x", pady=(10, 2))
        self.btn_jog.bind("<ButtonPress-1>",   self._jog_start)
        self.btn_jog.bind("<ButtonRelease-1>", self._jog_stop)

        self.lbl_jog_state = tk.Label(f, text="JOG: parado", bg=BG2, fg=TEXT_DIM,
                                      font=FONT_LABEL)
        self.lbl_jog_state.pack()

        tk.Label(f, text="Watchdog: o eixo para se o drive parar de responder, "
                         "entrar em falha\nou atingir o limite de curso",
                 bg=BG2, fg=TEXT_DIM, font=fonte(8)).pack()

    # --- VELOCIDADE -------------------------------------------------------------

    def _on_speed_change(self, val):
        """Acompanha o slider no rotulo de velocidade. Nao fala com o drive."""
        self.lbl_speed_val.config(
            text=vel_txt(int(float(val)), self._ivar(self.lim_ppr, 6000)))

    # --- WATCHDOG DO JOG ------------------------------------------------------

    _WD_INTERVALO = 0.03   # s de folga entre ciclos (cada ciclo le 3 quadros)

    def _jog_watchdog(self, mov):
        """Vigia o JOG ate o eixo parar. Roda em thread propria.

        Cada ciclo e um `EixoMovimento.vigiar_movimento`: drive mudo duas
        vezes seguidas, falha no drive ou limite de curso param o eixo. Sem
        isso, uma queda do RS-485 com o drive em movimento continuo deixaria o
        eixo girando, porque o comando e retido pelo drive e nao depende de
        novas mensagens.
        """
        while self.jog_active and self._conectado:
            time.sleep(self._WD_INTERVALO)
            if not self.jog_active:      # parada normal (botao solto)
                return
            res = mov.vigiar_movimento()
            if res is not None:
                # A parada ja foi comandada por vigiar_movimento
                self._jog_falhou(res.detalhe)
                if res.causa == CAUSA_DRIVE_MUDO:
                    # O log diz de que tipo foram as falhas (mudo, CRC...)
                    self.after(0, lambda: self._resumo_com(agora_mesmo=True))
                return

    def _jog_falhou(self, motivo: str, mov=None):
        """Encerra o JOG por falha e devolve a UI ao estado parado.

        Com `mov`, comanda a parada escalonada nele antes. Sem `mov`, quem
        chamou ja parou o eixo. O eixo vem por parametro, e nao do eixo ativo,
        porque isto roda nas threads da fila e do watchdog -- que nao podem
        ler variavel Tk.
        """
        self.jog_active = False
        if mov is not None:
            mov.parada_segura(motivo)

        def _ui():
            self.btn_jog.config(bg=JOG_CLR, text="JOG\n(pressione e segure)")
            self.lbl_jog_state.config(text="JOG: PARADO - {}".format(motivo), fg=RED)
            if not self.motor_on:
                self.btn_jog.config(state="disabled")
                self.lbl_motor_state.config(text="Motor: DESABILITADO (watchdog)",
                                            fg=RED)
        self.after(0, _ui)

    # --- BOTAO JOG ------------------------------------------------------------

    def _jog_start(self, event=None):
        """Comeca o JOG ao pressionar o botao, se nada impedir.

        Confere aqui o que nao exige o barramento: motor habilitado, nenhum
        homing ou posicionamento em curso. A faixa de curso e conferida por
        `EixoMovimento.jog_iniciar` na thread da fila -- ler a posicao aqui
        seguraria a tela no timeout da porta.
        """
        if not self.motor_on or self.home_ativo or not self._check_conn():
            return
        if self.curso_mov:
            return
        with self._jog_lock:
            if self.jog_active:
                return
            self.jog_active = True

        mov = self._preparar_mov()
        pps = self._ivar(self.speed_var, 3000)
        dire = self.direction.get()
        self.btn_jog.config(bg=JOG_ACTIVE, text="JOG ATIVO\n(solte para parar)")
        self.lbl_jog_state.config(text="JOG: {}  {} p/s".format(dire, pps), fg=YELLOW)
        self._log("[JOG] START -> {}  {} p/s".format(dire, pps))
        self._pedir_movimento(("jog", mov, pps, dire))

    def _jog_stop(self, event=None):
        """Para o JOG ao soltar o botao, enfileirando a desaceleracao.

        Passa pela mesma fila da partida: e o que garante que o "parar" nunca
        chegue ao drive antes do "andar" de um clique rapido anterior.
        """
        with self._jog_lock:
            if not self.jog_active:
                return
            self.jog_active = False

        self.btn_jog.config(bg=JOG_CLR, text="JOG\n(pressione e segure)")
        self.lbl_jog_state.config(text="JOG: parado", fg=TEXT_DIM)
        self._log("[JOG] STOP -> desacelerando")
        self._pedir_movimento(("stop", self._mov()))

    def _jog_recusado(self, mensagem):
        """O JOG nao partiu (limite, motor desabilitado): avisa e repoe o botao."""
        self.jog_active = False
        self.btn_jog.config(bg=JOG_CLR, text="JOG\n(pressione e segure)")
        self.lbl_jog_state.config(text="JOG: bloqueado", fg=RED)
        messagebox.showwarning("JOG bloqueado", mensagem)

    # --- fila de movimento ----------------------------------------------------
    #
    # Todo comando de JOG passa por uma unica thread. Com uma thread por clique,
    # cliques rapidos empilhariam sequencias disputando o barramento, e um
    # "andar" poderia chegar ao drive DEPOIS do "parar" -- o eixo ficaria
    # girando com o botao ja solto. Aqui vale o ultimo pedido: se o operador
    # soltar o botao antes da partida sair, so o stop e enviado.

    def _pedir_movimento(self, alvo):
        """Enfileira um pedido de movimento. Vale sempre o ultimo.

        Args:
            alvo: ("jog", mov, pps, sentido) ou ("stop", mov). O EixoMovimento
                viaja junto -- ele ja sabe o endereco do drive, entao a thread
                perpetua da fila nao precisa congelar nada.
        """
        with self._mov_lock:
            self._mov_alvo = alvo
        self._mov_evt.set()

    def _loop_movimento(self):
        """Thread perpetua que serializa os comandos de JOG do barramento.

        So ha um consumidor, e ele sempre pega o pedido mais recente. Nasce em
        `JogApp.__init__` como daemon e vive ate a janela fechar.
        """
        while True:
            self._mov_evt.wait()
            self._mov_evt.clear()
            with self._mov_lock:
                pedido, self._mov_alvo = self._mov_alvo, None
            if not pedido:
                continue
            try:
                if pedido[0] == "jog":
                    self._executar_jog(*pedido[1:])
                elif pedido[0] == "stop":
                    res = pedido[1].jog_parar()
                    if not res.ok:
                        self._jog_falhou(res.detalhe, pedido[1])
            except Exception as e:
                self._log("[ERR] fila de movimento: {}".format(e))

    def _executar_jog(self, mov, pps, sentido):
        """Parte o JOG e sobe o watchdog. Roda na thread da fila."""
        if not self.jog_active:           # o botao ja foi solto
            return
        try:
            res = mov.jog_iniciar(pps, sentido)
        except MovimentoRecusado as e:
            self.after(0, lambda m=e.mensagem: self._jog_recusado(m))
            return
        if not res.ok:
            self._jog_falhou(res.detalhe, mov)
            return
        if not self.jog_active:
            # Soltaram durante a partida: o stop pode ter sido consumido antes
            # do "andar" chegar ao drive. Para de novo, por garantia.
            mov.jog_parar()
            return
        # Watchdog em thread propria: rodando aqui, ele bloquearia a fila e o
        # comando de parada so sairia no fim do JOG
        self._thread_op(self._jog_watchdog, mov, slave=mov.config.slave)
