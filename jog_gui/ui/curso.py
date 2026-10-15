"""Card CURSO E LIMITES: faixa de trabalho em pulsos e movimentacao por pulsos."""

from tkinter import messagebox
import time
import tkinter as tk

from jog_gui.motion import (
    CAUSA_CANCELADO,
    FRENTE,
    TRAS,
    MovimentoRecusado,
    limites,
)
from jog_gui.str6 import VEL_MAX_PPS

from .tema import (
    ACCENT,
    ACCENT2,
    BG2,
    BG3,
    BORDER,
    FONT_BOLD,
    FONT_LABEL,
    GREEN,
    RED,
    TEXT,
    TEXT_DIM,
    YELLOW,
)


class CursoMixin:
    """Card CURSO E LIMITES: faixa de trabalho em pulsos e movimentacao por pulsos."""


    # ==========================================================================
    # CURSO E LIMITES DE SOFTWARE
    # ==========================================================================
    #
    # PARA QUE SERVE
    #   Define a faixa de trabalho do eixo em pulsos, a partir da origem: o
    #   ponto onde o sensor e acionado e onde o homing zera o contador.
    #   "Limite +" = quantos pulsos o eixo pode subir acima do zero.
    #   "Limite -" = quantos pulsos pode descer abaixo do zero (guardado como
    #   valor positivo e aplicado como negativo).
    #
    # ONDE OS LIMITES FICAM GUARDADOS
    #   Somente no eixos.json. Este card NAO grava parametro no drive nem
    #   dispara o salvamento (90): e requisito do projeto nao envolver a
    #   memoria do drive nessa funcao. Os registradores que ele toca
    #   (62~70, 72) sao de operacao.
    #
    # ALCANCE DA PROTECAO  (importante para quem for integrar)
    #   Os limites valem enquanto ESTA TELA conduz o eixo. Um comando vindo de
    #   outro software ou de um CLP nao passa por aqui e nao e barrado. O STR6
    #   oferece limite de curso por entrada fisica (IN1 = limite -, IN2 =
    #   limite +), e nesta bancada uma delas e o sensor de origem. Protecao
    #   independente de software exige um sensor por extremo nessas entradas.
    #
    # COMO O EIXO E MOVIMENTADO (tudo em jog_gui.motion.EixoMovimento)
    #   - JOG: movimento continuo (70 = 3/4), parada por software. A
    #     vigilancia le a posicao a cada ciclo e manda parar na borda da
    #     faixa -- dai a "antecipacao" em pulsos, que cobre a desaceleracao.
    #   - Jog por pulsos e "Ir para a posicao": movimento de comprimento fixo
    #     (70 = 1/2, curso em 68/69). O drive desacelera e para sozinho, entao
    #     o resultado nao depende do periodo de leitura.

    def _card_curso(self, parent):
        """Monta o card: limites, antecipacao, regua, passos e posicionamento.

        Os botoes de atalho (Zero / Limite + / Limite -) e os de passo sao
        guardados em `_btns_atalho_curso` para que `_set_connected` e
        `_curso_fim` os liguem e desliguem junto com os demais.
        """
        f = self._card(parent, "CURSO E LIMITES (SOFTWARE)")

        def _linha(texto, largura=15):
            row = tk.Frame(f, bg=BG2)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=texto, bg=BG2, fg=TEXT, font=FONT_LABEL,
                     width=largura, anchor="w").pack(side="left")
            return row

        def _spin(row, var, de, ate, sufixo="", largura=10, incremento=1):
            tk.Spinbox(row, from_=de, to=ate, increment=incremento,
                       textvariable=var, width=largura, bg=BG3, fg=TEXT,
                       buttonbackground=BG3, insertbackground=TEXT,
                       relief="flat", font=FONT_LABEL).pack(side="left")
            if sufixo:
                tk.Label(row, text=sufixo, bg=BG2, fg=TEXT_DIM,
                         font=FONT_LABEL).pack(side="left", padx=4)

        tk.Label(f, text="Zero = ponto do sensor (definido pelo homing).\n"
                         "Limite + : quanto o eixo pode subir acima do zero.\n"
                         "Limite - : quanto pode descer abaixo do zero.",
                 bg=BG2, fg=TEXT_DIM, font=("Segoe UI", 8),
                 justify="left").pack(fill="x", pady=(0, 4))

        # --- faixa permitida ---------------------------------------------------
        row = _linha("Limite +:")
        _spin(row, self.lim_pos, 0, 2147483647, "pulsos acima")
        row = _linha("Limite -:")
        _spin(row, self.lim_neg, 0, 2147483647, "pulsos abaixo")

        row = _linha("Antecipacao:")
        _spin(row, self.lim_margem, 0, 1000000, "pulsos antes do limite")
        row = _linha("Tolerancia:")
        _spin(row, self.lim_tol, 1, 1000000, "pulsos no alvo")

        row = _linha("Sentido de +:")
        for txt, val in [("FRENTE  >>", FRENTE), ("<<  TRAS", TRAS)]:
            tk.Radiobutton(row, text=txt, variable=self.curso_sent_pos, value=val,
                           bg=BG2, fg=TEXT, selectcolor=BG3, activebackground=BG2,
                           font=FONT_LABEL).pack(side="left", padx=4)

        self.lbl_curso_faixa = tk.Label(f, text="", bg=BG2, fg=TEXT,
                                        font=FONT_LABEL, justify="left")
        self.lbl_curso_faixa.pack(fill="x", pady=(2, 0))
        for v in (self.lim_pos, self.lim_neg, self.lim_ppr,
                  self.lim_ativo, self.lim_margem):
            v.trace_add("write", lambda *_: self._curso_resumo())

        # --- jog por pulsos ----------------------------------------------------
        sep_passo = tk.Frame(f, bg=BORDER, height=1)
        sep_passo.pack(fill="x", pady=(6, 4))
        tk.Label(f, text="Jog por pulsos - passo exato, contado pelo drive "
                         "(use para acertar o limite)",
                 bg=BG2, fg=TEXT_DIM, font=("Segoe UI", 8),
                 justify="left").pack(fill="x")

        row = _linha("Passo:")
        _spin(row, self.passo_pulsos, 1, 10000000, "pulsos")
        row = _linha("Vel. do passo:")
        _spin(row, self.passo_vel, 10, VEL_MAX_PPS, "p/s", incremento=100)

        row_passo = tk.Frame(f, bg=BG2)
        row_passo.pack(fill="x", pady=(2, 4))
        self.btn_passo_neg = tk.Button(row_passo, text="<<  - passo",
                                       font=FONT_BOLD, bg=BG3, fg=YELLOW, bd=0,
                                       padx=6, pady=6, cursor="hand2",
                                       state="disabled",
                                       command=lambda: self._jog_passo(-1))
        self.btn_passo_neg.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.btn_passo_pos = tk.Button(row_passo, text="+ passo  >>",
                                       font=FONT_BOLD, bg=BG3, fg=YELLOW, bd=0,
                                       padx=6, pady=6, cursor="hand2",
                                       state="disabled",
                                       command=lambda: self._jog_passo(+1))
        self.btn_passo_pos.pack(side="right", expand=True, fill="x")
        self._btns_atalho_curso.extend([self.btn_passo_neg, self.btn_passo_pos])

        row_cap = tk.Frame(f, bg=BG2)
        row_cap.pack(fill="x", pady=(4, 2))
        self.btn_cap_pos = tk.Button(row_cap, text="Posicao atual = limite +",
                                     font=FONT_BOLD, bg=BG3, fg=ACCENT, bd=0,
                                     padx=6, pady=5, cursor="hand2",
                                     command=lambda: self._capturar_limite("+"),
                                     state="disabled")
        self.btn_cap_pos.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.btn_cap_neg = tk.Button(row_cap, text="Posicao atual = limite -",
                                     font=FONT_BOLD, bg=BG3, fg=ACCENT, bd=0,
                                     padx=6, pady=5, cursor="hand2",
                                     command=lambda: self._capturar_limite("-"),
                                     state="disabled")
        self.btn_cap_neg.pack(side="right", expand=True, fill="x")

        row_cfg = tk.Frame(f, bg=BG2)
        row_cfg.pack(fill="x", pady=(0, 4))
        tk.Button(row_cfg, text="Salvar limites", font=FONT_BOLD,
                  bg=ACCENT2, fg="white", bd=0, padx=6, pady=5, cursor="hand2",
                  command=self._salvar_limites).pack(side="left", expand=True,
                                                     fill="x", padx=(0, 4))
        tk.Button(row_cfg, text="Recarregar", font=FONT_BOLD,
                  bg=BG3, fg=TEXT_DIM, bd=0, padx=6, pady=5, cursor="hand2",
                  command=self._carregar_limites).pack(side="left", expand=True,
                                                       fill="x", padx=(0, 4))
        self.btn_detectar = tk.Button(row_cfg, text="Detectar sentido +",
                                      font=FONT_BOLD, bg=YELLOW, fg="white", bd=0,
                                      padx=6, pady=5, cursor="hand2",
                                      command=self._detectar_sentido,
                                      state="disabled")
        self.btn_detectar.pack(side="right", expand=True, fill="x")

        # --- vigilancia --------------------------------------------------------
        tk.Checkbutton(f, text="Aplicar limites (para o eixo ao atingir a faixa)",
                       variable=self.lim_ativo, bg=BG2, fg=TEXT, selectcolor=BG3,
                       activebackground=BG2, font=FONT_BOLD,
                       command=self._curso_resumo).pack(anchor="w", pady=(4, 0))

        # --- regua do curso ----------------------------------------------------
        self.cv_curso = tk.Canvas(f, height=46, bg=BG3, highlightthickness=0)
        self.cv_curso.pack(fill="x", pady=(4, 2))
        self.cv_curso.bind("<Configure>", lambda e: self._desenhar_regua())

        self.lbl_curso_pos = tk.Label(f, text="Posicao: ---  (ligue o monitor)",
                                      bg=BG2, fg=TEXT_DIM, font=FONT_BOLD)
        self.lbl_curso_pos.pack()

        # --- posicionamento ----------------------------------------------------
        sep = tk.Frame(f, bg=BORDER, height=1)
        sep.pack(fill="x", pady=6)

        row = _linha("Ir para:")
        _spin(row, self.curso_alvo, -2147483647, 2147483647, "pulsos")
        row = _linha("Vel. rapida:")
        _spin(row, self.curso_v_rap, 100, VEL_MAX_PPS, "p/s", incremento=100)
        row = _linha("Vel. lenta:")
        _spin(row, self.curso_v_len, 10, VEL_MAX_PPS, "p/s", incremento=100)
        row = _linha("Janela lenta:")
        _spin(row, self.curso_janela, 0, 10000000, "pulsos antes do alvo")

        row_ir = tk.Frame(f, bg=BG2)
        row_ir.pack(fill="x", pady=(6, 2))
        self.btn_ir = tk.Button(row_ir, text="IR PARA A POSICAO", font=FONT_BOLD,
                                bg=ACCENT, fg="white", bd=0, padx=8, pady=8,
                                cursor="hand2", command=self._ir_para_alvo,
                                state="disabled")
        self.btn_ir.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.btn_ir_stop = tk.Button(row_ir, text="PARAR", font=FONT_BOLD,
                                     bg=RED, fg="white", bd=0, padx=8, pady=8,
                                     cursor="hand2", command=self._parar_curso,
                                     state="disabled")
        self.btn_ir_stop.pack(side="right", expand=True, fill="x")

        row_at = tk.Frame(f, bg=BG2)
        row_at.pack(fill="x", pady=(0, 2))
        for txt, obtem in [("Zero", lambda: 0),
                           ("Limite +", lambda: self._faixa()[1]),
                           ("Limite -", lambda: self._faixa()[0])]:
            b = tk.Button(row_at, text=txt, font=FONT_LABEL, bg=BG3, fg=ACCENT,
                          bd=0, padx=6, pady=4, cursor="hand2", state="disabled",
                          command=lambda o=obtem: self._ir_para_alvo(o()))
            b.pack(side="left", expand=True, fill="x", padx=2)
            self._btns_atalho_curso.append(b)

        self.lbl_curso_status = tk.Label(f, text="Curso: parado",
                                         bg=BG2, fg=TEXT_DIM, font=FONT_LABEL,
                                         wraplength=310, justify="left")
        self.lbl_curso_status.pack(fill="x")

        self._curso_resumo()

    def _faixa(self):
        """Faixa permitida em pulsos, lida dos campos: (negativo, positivo)."""
        return limites.faixa(self._ivar(self.lim_neg), self._ivar(self.lim_pos))

    def _pulsos_txt(self, pulsos: int) -> str:
        """Formata pulsos com a volta equivalente, pelos pulsos/volta da tela.

        O campo "pulsos por volta" vem do registrador 1 quando o drive e lido
        (card de configuracao); sem leitura, e o valor do cadastro.
        """
        ppr = max(1, self._ivar(self.lim_ppr, 1))
        return "{} pulsos ({:+.2f} volta)".format(pulsos, pulsos / float(ppr))

    def _curso_resumo(self):
        """Reescreve a faixa, o curso total e a regua a partir dos campos.

        Torna visivel a antecipacao EFETIVA quando ela difere da pedida: numa
        faixa curta o valor pedido nao cabe e e limitado a metade de cada
        lado, senao o eixo ficaria bloqueado na origem sem explicacao.
        """
        if not hasattr(self, "lbl_curso_faixa"):
            return
        neg, pos = self._faixa()
        estado = ("APLICADOS" if self._ivar(self.lim_ativo)
                  else "apenas informativos")
        margem = self._ivar(self.lim_margem)
        m_neg, m_pos = limites.margens(neg, pos, margem)
        aviso = ""
        if (m_neg, m_pos) != (margem, margem):
            aviso = "\nAntecipacao em uso: -{} / +{} (pedida {})".format(
                m_neg, m_pos, margem)
        self.lbl_curso_faixa.config(
            text="Faixa: {} ate {}\nCurso total: {}  |  limites {}{}".format(
                self._pulsos_txt(neg), self._pulsos_txt(pos),
                self._pulsos_txt(pos - neg), estado, aviso),
            fg=TEXT if self._ivar(self.lim_ativo) else TEXT_DIM)
        self._desenhar_regua()

    def _desenhar_regua(self, pos=None):
        """Desenha a faixa permitida e onde o eixo esta dentro dela."""
        if not hasattr(self, "cv_curso"):
            return
        if pos is None:
            pos = self._curso_pos_atual
        cv = self.cv_curso
        cv.delete("all")
        larg = max(cv.winfo_width(), 140)
        x0, x1 = 16, larg - 16
        y = 24
        neg, pmax = self._faixa()
        span = pmax - neg
        cv.create_line(x0, y, x1, y, fill=BORDER, width=6)

        def _x(p):
            if span <= 0:
                return (x0 + x1) / 2.0
            frac = (p - neg) / float(span)
            return x0 + max(0.0, min(1.0, frac)) * (x1 - x0)

        if span > 0:
            cv.create_line(x0, y, x1, y, fill=ACCENT2, width=6)
            for p, cor, txt in [(neg, RED, "-"), (0, GREEN, "0"), (pmax, RED, "+")]:
                xp = _x(p)
                cv.create_line(xp, y - 9, xp, y + 9, fill=cor, width=2)
                cv.create_text(xp, y + 16, text="{} {}".format(txt, p), fill=cor,
                               font=("Segoe UI", 7))
        else:
            cv.create_text((x0 + x1) / 2.0, y + 16, text="faixa nao definida",
                           fill=TEXT_DIM, font=("Segoe UI", 7))

        if pos is not None:
            fora = span > 0 and (pos < neg or pos > pmax)
            xp = _x(pos)
            cor = RED if fora else YELLOW
            cv.create_polygon(xp, y - 3, xp - 6, y - 13, xp + 6, y - 13,
                              fill=cor, outline="")
            cv.create_text(xp, y - 14, text=str(pos), fill=cor,
                           font=("Segoe UI", 7), anchor="s")

    def _curso_ui(self, pos: int):
        """Chamado pelo monitor e pelos movimentos: atualiza regua e rotulo."""
        self._curso_pos_atual = pos
        self._curso_pos_ts = time.time()
        neg, pmax = self._faixa()
        if limites.faixa_vazia(neg, pmax):
            txt, cor = "Posicao: {}".format(self._pulsos_txt(pos)), TEXT
        elif limites.violacao(pos, neg, pmax):
            txt = "Posicao: {}  ->  FORA DA FAIXA".format(self._pulsos_txt(pos))
            cor = RED
        else:
            txt = "Posicao: {}   (resta +{} / -{})".format(
                self._pulsos_txt(pos), pmax - pos, pos - neg)
            cor = TEXT
        self.lbl_curso_pos.config(text=txt, fg=cor)
        self._desenhar_regua(pos)

    # --- persistencia dos limites ----------------------------------------------

    # Os limites sao POR EIXO e moram no Eixo, junto com a configuracao e o
    # homing (ver ui/eixo.py). Estes dois metodos sao so a ponte para os botoes
    # do card: a gravacao em arquivo e a do cadastro inteiro, num unico
    # eixos.json.

    def _salvar_limites(self, silencioso: bool = False):
        """Guarda a tela no eixo ativo e grava o cadastro."""
        ok = self._salvar_eixos()
        if not ok:
            if not silencioso:
                messagebox.showerror(
                    "Salvar limites",
                    "Nao foi possivel gravar {}. Veja o log."
                    .format(self._EIXOS_ARQ))
            return
        self._log("[CURSO] Limites do eixo {} salvos".format(self.slave.get()))
        if not silencioso:
            self.lbl_curso_status.config(
                text="Curso: limites do eixo {} salvos".format(self.slave.get()),
                fg=GREEN)

    def _carregar_limites(self):
        """Descarta o que esta na tela e traz de volta o eixo ativo salvo.

        Le do arquivo, nao do objeto em memoria: o botao existe justamente para
        desfazer uma edicao que ainda nao foi gravada.
        """
        eixo = self.eixo_ativo
        if eixo is None:
            return
        salvo = self._ler_json(self._EIXOS_ARQ) or {}
        for item in salvo.get("eixos", []):
            if item.get("id") == eixo.slave:
                eixo.atualizar(item.get("config") or {})
                break
        eixo.aplicar(self)
        self._atualizar_painel_sensor()
        self.ganhos_edit.set(0)
        self._log("[CURSO] Limites do eixo {} recarregados".format(eixo.slave))
        self._curso_resumo()

    # --- captura e deteccao de sentido ------------------------------------------

    def _capturar_limite(self, qual: str):
        """
        Usa a posicao atual do eixo como limite + ou -.

        A thread so le a posicao no drive; a decisao e a escrita nos campos
        acontecem na thread da interface -- Tk nao aceita variavel lida ou
        escrita de outra thread.
        """
        if not self._check_conn():
            return
        mov = self._mov()

        def _tarefa():
            pos = mov.ler_posicao()
            self.after(0, lambda: self._aplicar_captura(qual, pos))

        self._thread_op(_tarefa)

    def _aplicar_captura(self, qual: str, pos):
        """Valida e grava o limite capturado. Roda na thread da interface."""
        if pos is None:
            self._log("[CURSO] Nao foi possivel ler a posicao")
            self.lbl_curso_status.config(text="Curso: posicao nao pode ser lida",
                                         fg=RED)
            return

        # Capturar um limite do lado errado do zero inverteria a faixa.
        if (qual == "+" and pos < 0) or (qual == "-" and pos > 0):
            lado = (self.curso_sent_pos.get() if qual == "+" else
                    (TRAS if self.curso_sent_pos.get() == FRENTE else FRENTE))
            self._log("[CURSO] Captura do limite {} recusada: posicao {} esta do "
                      "lado oposto ao limite".format(qual, pos))
            self.lbl_curso_status.config(
                text="Curso: captura do limite {} recusada - posicao {} do lado "
                     "oposto (veja o aviso)".format(qual, pos), fg=RED)
            messagebox.showwarning(
                "Limite {}".format(qual),
                "A posicao atual e {} pulsos, do lado oposto ao limite {}.\n\n"
                "Leve o eixo para o outro lado com o JOG no sentido {} e capture "
                "de novo, ou digite o valor direto no campo Limite {}.\n\n"
                "Se o eixo nao consegue sair do zero nesse sentido, lembre que o "
                "sensor ocupa uma entrada de LIMITE do drive (IN1/IN2): com o "
                "sensor acionado, o proprio drive pode bloquear o movimento "
                "naquele sentido.".format(pos, qual, lado, qual))
            return

        valor = abs(pos)
        (self.lim_pos if qual == "+" else self.lim_neg).set(valor)
        self.lbl_curso_status.config(
            text="Curso: limite {} = {} pulsos (posicao atual) - use Salvar "
                 "limites para guardar".format(qual, valor), fg=GREEN)
        self._curso_resumo()
        self._log("[CURSO] Limite {} capturado em {} pulsos".format(qual, pos))

    def _detectar_sentido(self):
        """
        Move o eixo por um instante em FRENTE e observa a contagem para
        descobrir qual sentido aumenta a posicao. Sem isso, um limite guardado
        do lado errado faria a vigilancia parar o eixo no extremo oposto ao
        esperado -- e o passo andaria ao contrario.
        """
        if not self._check_conn() or not self._curso_livre():
            return
        if not self.motor_on:
            messagebox.showwarning("Motor desabilitado",
                                   "Habilite o motor antes de detectar o sentido.")
            return
        pps = self._ivar(self.curso_v_len, 6000)
        if not messagebox.askokcancel(
                "Detectar sentido",
                "O eixo vai girar por cerca de 1 s a {} p/s para FRENTE.\n\n"
                "Confirme que ha curso livre nos dois lados.".format(pps)):
            return

        mov = self._preparar_mov()

        def _tarefa():
            res = mov.detectar_sentido(pps)
            if res.ok:
                self.after(0, lambda: self.curso_sent_pos.set(res.valor))
            return res

        self._curso_iniciar(mov, "detectando o sentido positivo...")
        self._thread_op(self._tarefa_curso, mov, _tarefa)

    # --- estado do card durante um movimento ------------------------------------

    def _curso_livre(self) -> bool:
        """True se nenhum outro movimento esta em andamento."""
        if self.curso_mov:
            # Um return silencioso aqui deixaria os botoes do card sem
            # resposta se a tarefa de movimento morresse sem repor o estado.
            messagebox.showwarning(
                "Movimento em andamento",
                "Ja existe um movimento do card de curso em andamento.\n\n"
                "Espere terminar ou use o botao PARAR.")
            return False
        if self.home_ativo:
            messagebox.showwarning("Homing ativo", "Aguarde o fim do homing.")
            return False
        if self.jog_active:
            messagebox.showwarning("JOG ativo", "Solte o botao JOG primeiro.")
            return False
        if self.teste_ativo:
            messagebox.showwarning("Teste ativo", "Aguarde o fim do teste do sensor.")
            return False
        return True

    def _curso_iniciar(self, mov, msg: str):
        """Poe o card em estado de movimento: so o PARAR continua clicavel.

        Desliga tambem o botao de JOG -- um movimento de comprimento fixo e um
        JOG continuo disputariam o mesmo eixo.
        """
        self.curso_mov = True
        self._mov_curso = mov
        self.btn_ir.config(state="disabled")
        self.btn_ir_stop.config(state="normal")
        self.btn_detectar.config(state="disabled")
        self.btn_jog.config(state="disabled")
        for b in self._btns_atalho_curso:
            b.config(state="disabled")
        self.lbl_curso_status.config(text="Curso: {}".format(msg), fg=YELLOW)

    def _tarefa_curso(self, mov, tarefa):
        """
        Roda uma tarefa de movimento do card garantindo a volta ao repouso.

        `tarefa` devolve um Resultado. Toda saida -- ok, falha, recusa antes de
        mover, excecao -- passa por `_curso_fim`: com `curso_mov` preso em
        True os botoes do card ficariam mudos ate reiniciar o programa.
        """
        try:
            res = tarefa()
        except MovimentoRecusado as e:
            self._curso_fim(e.mensagem, False)
            return
        except Exception as e:
            mov.parada_segura("Falha na tarefa de movimento")
            self._curso_fim("falha: {}".format(e), False)
            return
        if res.causa == CAUSA_CANCELADO:
            self._curso_fim("interrompido pelo operador", False)
        else:
            self._curso_fim(res.detalhe, res.ok)

    def _curso_fim(self, msg: str, ok: bool):
        """Encerra o movimento, mostra o desfecho e devolve os botoes."""
        self.curso_mov = False
        self._mov_curso = None
        self._log("[CURSO] {}".format(msg))

        def _ui():
            conectado = bool(self._conectado)
            estado = "normal" if conectado else "disabled"
            self.btn_ir.config(state=estado)
            self.btn_detectar.config(state=estado)
            self.btn_ir_stop.config(state="disabled")
            for b in self._btns_atalho_curso:
                b.config(state=estado)
            if self.motor_on and conectado:
                self.btn_jog.config(state="normal")
            self.lbl_curso_status.config(text="Curso: {}".format(msg),
                                         fg=GREEN if ok else RED)
        self.after(0, _ui)

    def _parar_curso(self):
        """Interrompe o posicionamento a pedido do operador.

        Marca o cancelamento -- o laco do movimento para o eixo na proxima
        leitura e encerra com CANCELADO -- e manda a parada ja, sem esperar
        esse ciclo.
        """
        mov = self._mov_curso
        if not self.curso_mov or mov is None:
            return
        self.lbl_curso_status.config(text="Curso: parando...", fg=YELLOW)
        mov.cancelar()
        self._thread_op(mov.parada_segura, "Posicionamento interrompido",
                        slave=mov.config.slave)

    # --- jog por pulsos e posicionamento ----------------------------------------

    def _jog_passo(self, sinal: int):
        """Anda um numero exato de pulsos para + ou para -.

        O sinal e o da contagem: + e o sentido que soma pulsos neste eixo
        ("Sentido de +"), entao o passo segue o contador e nao o rotulo.
        """
        if not self._check_conn() or not self._curso_livre():
            return
        if not self.motor_on:
            messagebox.showwarning("Motor desabilitado",
                                   "Habilite o motor (MOTOR ON) antes de mover.")
            return
        pulsos = abs(self._ivar(self.passo_pulsos, 200))
        if pulsos == 0:
            return
        pps = self._ivar(self.passo_vel, 3000)
        mov = self._preparar_mov()
        self._curso_iniciar(mov, "passo de {:+d} pulsos a {} p/s...".format(
            sinal * pulsos, pps))
        self._thread_op(self._tarefa_curso, mov,
                        lambda: mov.passo(sinal, pulsos, pps))

    def _ir_para_alvo(self, alvo=None):
        """Dispara o posicionamento em thread.

        Args:
            alvo: posicao em pulsos a partir do zero. None usa o campo da tela;
                um valor explicito (os atalhos Zero / Limite +/-) tambem e
                escrito no campo.

        A validacao (faixa, zero, motor) e de `EixoMovimento.ir_para`, que
        recusa ANTES de escrever qualquer coisa -- a recusa volta como
        mensagem no card.
        """
        if not self._check_conn() or not self._curso_livre():
            return
        if not self.motor_on:
            messagebox.showwarning("Motor desabilitado",
                                   "Habilite o motor (MOTOR ON) antes de mover.")
            return
        if alvo is None:
            alvo = self._ivar(self.curso_alvo)
        else:
            self.curso_alvo.set(alvo)

        mov = self._preparar_mov()
        self._curso_iniciar(mov, "indo para {} pulsos...".format(alvo))
        self._thread_op(self._tarefa_curso, mov, lambda: mov.ir_para(alvo))
