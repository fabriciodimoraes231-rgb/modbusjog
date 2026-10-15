"""Card CONFIGURACAO DO DRIVE: corrente, standby, malha, subdivisao e ganhos."""

import time
import tkinter as tk
from tkinter import messagebox

from jog_gui.str6 import (
    MALHA_ABERTA,
    MALHA_FECHADA,
    MALHAS,
    PULSOS_VOLTA_MAX,
    PULSOS_VOLTA_MIN,
    REG_AUTOAJUSTE,
    REG_CORRENTE_EFETIVA,
    REG_CORRENTE_OPER_PCT,
    REG_CORRENTE_PICO,
    REG_ENABLE,
    REG_KI,
    REG_KP,
    REG_MALHA,
    REG_PULSOS_VOLTA,
    REG_SALVAR,
    REG_STANDBY_PCT,
    REG_STANDBY_TEMPO,
    RELIGA_DESLIGADO,
    RELIGA_ESPERANDO,
    RELIGA_RELIGADO,
    STANDBY_TEMPO_MAX,
    STANDBY_TEMPO_MIN,
    DriveNaoConfirmou,
    comparar_configuracao,
)

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
    amperes_txt,
)

# Nome curto de cada registrador gravado por este card, para o log.
_NOMES = {
    REG_MALHA: "Malha",
    REG_CORRENTE_PICO: "Corrente de pico",
    REG_CORRENTE_OPER_PCT: "Corrente operacional",
    REG_PULSOS_VOLTA: "Pulsos por volta",
    REG_STANDBY_TEMPO: "Tempo de standby",
    REG_STANDBY_PCT: "Corrente de standby",
    REG_AUTOAJUSTE: "Autoajuste",
    REG_KP: "Kp",
    REG_KI: "Ki",
}

# Tempo que o teste de gravacao da ao operador para desligar e religar o drive.
PRAZO_RELIGA = 120.0


class CorrenteMixin:
    """Card CONFIGURACAO DO DRIVE: corrente, standby, malha, subdivisao e ganhos."""


    def _card_corrente(self, parent):
        """Monta o card: malha, corrente de pico, standby, subdivisao e ganhos.

        A faixa de malha confirmada (`lbl_malha_badge`) fica separada dos
        radios de proposito: o radio mostra o que SERA gravado, a faixa mostra
        o que o drive tem.
        """
        f = self._card(parent, "CONFIGURACAO DO DRIVE")

        def _linha(texto):
            row = tk.Frame(f, bg=BG2)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=texto, bg=BG2, fg=TEXT, font=FONT_LABEL,
                     width=16, anchor="w").pack(side="left")
            return row

        def _spin(row, var, de, ate, sufixo, incremento=1):
            tk.Spinbox(row, from_=de, to=ate, increment=incremento,
                       textvariable=var, width=8, bg=BG3, fg=TEXT,
                       buttonbackground=BG3, insertbackground=TEXT,
                       relief="flat", font=FONT_LABEL).pack(side="left")
            tk.Label(row, text=sufixo, bg=BG2, fg=TEXT_DIM,
                     font=FONT_LABEL).pack(side="left", padx=4)

        # Malha (24)
        row = _linha("Malha (reg 24):")
        for txt, val in [("Aberta", MALHA_ABERTA), ("Fechada", MALHA_FECHADA)]:
            tk.Radiobutton(row, text=txt, variable=self.modo_malha, value=val,
                           bg=BG2, fg=TEXT, selectcolor=BG3, activebackground=BG2,
                           font=FONT_LABEL).pack(side="left", padx=6)

        self.lbl_malha_badge = tk.Label(f, text="MALHA: ?  -  clique em Ler do Drive",
                                        bg=BG3, fg=TEXT_DIM,
                                        font=("Segoe UI", 11, "bold"), pady=6)
        self.lbl_malha_badge.pack(fill="x", pady=(4, 2))
        self.lbl_malha_aviso = tk.Label(f, text="", bg=BG2, fg=YELLOW,
                                        font=FONT_LABEL, wraplength=300)
        self.lbl_malha_aviso.pack(fill="x")
        self.modo_malha.trace_add("write", lambda *_: self._badge_malha())

        # Corrente: ajustada pelo 26. Na bancada o drive ecoa a escrita no 0 e
        # mantem o valor, e o 0 muda quando se escreve o 26 -- entao a tela
        # grava o 26 e mostra o 0 que o drive informa. A relacao entre os dois
        # nao esta no manual: o pico mostrado e sempre o LIDO, nunca calculado.
        row = _linha("Corrente:")
        _spin(row, self.corr_oper_pct, 0, 100, "%  (reg 26)")
        row = _linha("Pico (reg 0):")
        self.lbl_corr_pico = tk.Label(row, text="?  -  Ler do Drive", bg=BG2,
                                      fg=ACCENT, font=FONT_BOLD, anchor="w")
        self.lbl_corr_pico.pack(side="left")
        tk.Label(row, text="lido do drive", bg=BG2, fg=TEXT_DIM,
                 font=FONT_LABEL).pack(side="left", padx=6)

        row = _linha("Standby:")
        _spin(row, self.corr_standby, 0, 100, "%  (reg 3)")
        row = _linha("Entra em standby:")
        _spin(row, self.standby_ms, STANDBY_TEMPO_MIN, STANDBY_TEMPO_MAX,
              "ms parado  (reg 2)", incremento=50)
        row = _linha("Pulsos por volta:")
        _spin(row, self.lim_ppr, PULSOS_VOLTA_MIN, PULSOS_VOLTA_MAX,
              "(reg 1)", incremento=200)

        tk.Label(f, text="Standby: o drive reduz a corrente com o eixo parado.\n"
                         "Pulsos por volta mudam o sentido de TODO numero em\n"
                         "pulsos (limites, zero, velocidades) - grave com cuidado.",
                 bg=BG2, fg=TEXT_DIM, font=("Segoe UI", 8),
                 justify="center").pack(pady=(4, 0))

        # --- malha de corrente (13, 15, 16) ------------------------------------
        sep_g = tk.Frame(f, bg=BORDER, height=1)
        sep_g.pack(fill="x", pady=(8, 4))
        tk.Checkbutton(f, text="Autoajuste da malha de corrente (reg 13)",
                       variable=self.autoajuste, bg=BG2, fg=TEXT,
                       selectcolor=BG3, activebackground=BG2,
                       font=FONT_LABEL).pack(anchor="w")
        tk.Label(f, text="Com o autoajuste ligado, Kp e Ki sao somente leitura",
                 bg=BG2, fg=TEXT_DIM, font=("Segoe UI", 8)).pack()

        row = _linha("Kp:")
        _spin(row, self.ganho_p, 10, 32767, "(reg 15)")
        row = _linha("Ki:")
        _spin(row, self.ganho_i, 0, 32767, "(reg 16)")

        row_g = tk.Frame(f, bg=BG2)
        row_g.pack(fill="x", pady=(2, 0))
        tk.Checkbutton(row_g, text="permitir gravar os ganhos",
                       variable=self.ganhos_edit, bg=BG2, fg=TEXT,
                       selectcolor=BG3, activebackground=BG2,
                       font=FONT_LABEL).pack(side="left")
        tk.Button(row_g, text="Padrao 1000/200", font=FONT_LABEL,
                  bg=BG3, fg=TEXT_DIM, bd=0, padx=6, pady=3, cursor="hand2",
                  command=self._ganhos_padrao).pack(side="right")

        # Botoes Ler / Gravar
        row_btns = tk.Frame(f, bg=BG2)
        row_btns.pack(fill="x", pady=(8, 2))
        self.btn_ler_corr = tk.Button(row_btns, text="Ler do Drive", font=FONT_BOLD,
                                      bg=ACCENT2, fg="white", bd=0,
                                      padx=14, pady=6, cursor="hand2",
                                      command=self._ler_correntes, state="disabled")
        self.btn_ler_corr.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.btn_gravar_corr = tk.Button(row_btns, text="Gravar e Salvar", font=FONT_BOLD,
                                         bg=GREEN, fg="white", bd=0,
                                         padx=14, pady=6, cursor="hand2",
                                         command=self._gravar_correntes, state="disabled")
        self.btn_gravar_corr.pack(side="right", expand=True, fill="x")

        self.btn_testar_grav = tk.Button(f, text="Testar gravacao (religar drive)",
                                         font=FONT_LABEL, bg=BG3, fg=ACCENT, bd=0,
                                         padx=10, pady=4, cursor="hand2",
                                         command=self._testar_gravacao,
                                         state="disabled")
        self.btn_testar_grav.pack(fill="x", pady=(2, 2))

        self.lbl_corr_status = tk.Label(f, text="", bg=BG2, fg=TEXT_DIM,
                                        font=FONT_LABEL, wraplength=300)
        self.lbl_corr_status.pack()

    def _badge_malha(self, lida=None, slave=None):
        """
        Mostra em destaque a malha confirmada pelo drive e avisa quando o radio
        da tela diverge dela (ou seja, ha uma troca pendente de gravacao).

        Args:
            lida: o 24 que acabou de voltar do drive, se houver.
            slave: a QUEM esse valor pertence. Obrigatorio quando a chamada vem
                de um `after(0, ...)` agendado por uma thread de operacao: o
                callback roda na thread da interface, onde o congelamento de
                endereco ja nao vale.

        A PINTURA e sempre a do eixo ativo -- e o que o operador esta vendo.
        """
        if lida is not None:
            self._runtime_de(self._slave_operacao() if slave is None else slave,
                             "malha_lida", lida, escrever=True)
        if not hasattr(self, "lbl_malha_badge"):
            return

        if self._malha_lida is None:
            self.lbl_malha_badge.config(text="MALHA: ?  -  clique em Ler do Drive",
                                        bg=BG3, fg=TEXT_DIM)
            self.lbl_malha_aviso.config(text="")
            return

        aberta = (self._malha_lida == MALHA_ABERTA)
        self.lbl_malha_badge.config(
            text="{}   (reg 24 = {})".format(
                MALHAS.get(self._malha_lida, "MALHA ?").upper(), self._malha_lida),
            bg=ACCENT if aberta else ACCENT2, fg="white")

        selecionada = self._ivar(self.modo_malha)
        if selecionada != self._malha_lida:
            self.lbl_malha_aviso.config(
                text="Selecionado: {}  ->  clique em Gravar e Salvar para "
                     "aplicar".format(MALHAS.get(selecionada, "?")))
        else:
            self.lbl_malha_aviso.config(text="")

    def _ppr_lido_do_drive(self, slave, ppr):
        """Registra os pulsos/volta que o drive informou e alinha a tela.

        O campo da tela e o que converte p/s em rpm e o que o cadastro guarda.
        Divergindo do drive, ele passa a mostrar o valor do drive -- e o log
        diz que mudou, porque limites anotados com outra subdivisao deixaram
        de significar a mesma distancia.
        """
        self._runtime_de(slave, "ppr_lido", ppr, escrever=True)
        if self._slave_operacao() != slave:
            return
        tela = self._ivar(self.lim_ppr)
        if tela != ppr:
            self._log("[CONFIG] Eixo {}: pulsos/volta do cadastro ({}) diferem do "
                      "drive ({}); a tela passa a usar {}. Confira os limites de "
                      "curso, que estao em pulsos.".format(slave, tela, ppr, ppr))
            self.lim_ppr.set(ppr)

    # --- LEITURA ----------------------------------------------------------------

    def _ler_correntes(self):
        """Le a configuracao do drive em thread e atualiza o card."""
        if not self._check_conn():
            return
        self.lbl_corr_status.config(text="Lendo...", fg=YELLOW)
        self._thread_op(self._do_ler_correntes)

    def _do_ler_correntes(self):
        """Le 0~3, 13, 15~16, 22, 24 e 26, aplica na tela e so entao libera gravar.

        A leitura e o que marca `corrente_lida`: enquanto ela nao acontecer, o
        que esta na tela e o padrao e nao o que este drive tem.

        0~3 sao vizinhos e vem num quadro so; os demais vem separados. Se o
        drive recusar um deles, o essencial (corrente) ja chegou. Roda em
        thread.
        """
        self._log("[CFG-R] Lendo configuracao do drive")
        base, motivo = self._ler_regs_espera(REG_CORRENTE_PICO, 4)
        if base is None:
            self._log("[CFG-R] ERRO: {}".format(motivo))
            self.after(0, lambda: self.lbl_corr_status.config(
                text="Erro ao ler!", fg=RED))
            return
        pico, ppr, standby_ms, standby_pct = base
        malha = self._ler_regs(REG_MALHA, 1)
        auto = self._ler_regs(REG_AUTOAJUSTE, 1)
        ganhos = self._ler_regs(REG_KP, 2)
        efetiva = self._ler_regs(REG_CORRENTE_EFETIVA, 1)
        oper = self._ler_regs(REG_CORRENTE_OPER_PCT, 1)

        self._log("[CFG-R] Corrente={} (reg 26) -> pico={} | Pulsos/volta={} | "
                  "Standby={}% apos {} ms | Malha={} | Autoajuste={} | Kp/Ki={} | "
                  "Corrente efetiva={}".format(
                      "?" if oper is None else "{}%".format(oper[0]),
                      amperes_txt(pico), ppr, standby_pct, standby_ms,
                      "?" if malha is None else MALHAS.get(malha[0], malha[0]),
                      "?" if auto is None else auto[0],
                      "?" if ganhos is None else "{}/{}".format(*ganhos),
                      "?" if efetiva is None else "{} mA".format(efetiva[0])))
        alvo = self._slave_atual

        def _apply():
            # O que foi LIDO pertence ao eixo `alvo`, sempre. Ja a TELA mostra
            # o eixo ativo: se o operador trocou de eixo enquanto o quadro
            # estava em voo, pintar aqui encheria o painel do eixo novo com a
            # configuracao do antigo -- e `corrente_lida` liberaria a gravacao
            # desses numeros no drive errado.
            self._runtime_de(alvo, "corrente_lida", True, escrever=True)
            self._runtime_de(alvo, "ppr_lido", ppr, escrever=True)
            self._runtime_de(alvo, "pico_lido", pico, escrever=True)
            if malha is not None:
                self._runtime_de(alvo, "malha_lida", malha[0], escrever=True)
            if self._slave_operacao() != alvo:
                self._log("[CFG-R] Leitura do eixo {} concluida, mas o painel "
                          "ja mostra o eixo {} - tela nao atualizada".format(
                              alvo, self._slave_operacao()))
                return
            self._mostrar_pico()
            if oper is not None:
                self.corr_oper_pct.set(oper[0])
            self.corr_standby.set(standby_pct)
            self.standby_ms.set(standby_ms)
            self._ppr_lido_do_drive(alvo, ppr)
            if malha is not None:
                self.modo_malha.set(malha[0])
                self._badge_malha(malha[0], slave=alvo)
            if auto is not None:
                self.autoajuste.set(1 if auto[0] else 0)
            if ganhos is not None:
                self.ganho_p.set(ganhos[0])
                self.ganho_i.set(ganhos[1])
            self.lbl_corr_status.config(
                text="Lido: corrente {} -> pico {:.2f} A | {} p/volta | "
                     "standby {}%".format(
                         "?" if oper is None else "{}%".format(oper[0]),
                         pico / 1000.0, ppr, standby_pct), fg=GREEN)
        self.after(0, _apply)

    def _mostrar_pico(self):
        """Pinta a corrente de pico (0) que o drive do eixo ativo informou.

        E leitura, nunca o que a tela pediu: o 0 e o efeito do 26 no drive.
        Na thread da interface.
        """
        if not hasattr(self, "lbl_corr_pico"):
            return
        pico = self._runtime("pico_lido")
        self.lbl_corr_pico.config(
            text="?  -  Ler do Drive" if pico is None else amperes_txt(pico))

    def _ganhos_padrao(self):
        """Repoe os valores de fabrica do manual (p. 13) nos campos da tela."""
        self.ganho_p.set(1000)
        self.ganho_i.set(200)
        self.lbl_corr_status.config(
            text="Ganhos nos valores de fabrica (1000/200) - grave para aplicar",
            fg=TEXT_DIM)

    # --- GRAVACAO ---------------------------------------------------------------

    def _gravar_correntes(self):
        """Confere o que vai ser gravado, pede confirmacao quando preciso e
        dispara a gravacao em thread.

        So com o motor desabilitado e nada em movimento.

        Duas confirmacoes, ambas na thread da interface:
          - configuracao que nao veio de uma leitura deste drive;
          - troca de pulsos por volta, que muda o significado de todo numero
            em pulsos do eixo e invalida o zero.

        O monitor fica pausado durante a gravacao: cada ciclo dele disputa o
        barramento com as escritas e com a espera do salvamento.
        """
        if not self._check_conn():
            return
        if (self.motor_on or self.jog_active or self.home_ativo
                or self.teste_ativo or self.curso_mov or self._teste_grav_ativo):
            messagebox.showwarning(
                "Gravar e Salvar",
                "Pare o movimento e desabilite o motor (MOTOR OFF) antes de "
                "gravar a configuracao.\n\nNum eixo vertical, apoie a carga "
                "antes do MOTOR OFF.")
            return

        pct = max(0, min(100, self._ivar(self.corr_oper_pct, 50)))
        if not self.corrente_lida:
            if not messagebox.askyesno(
                    "Gravar sem ter lido",
                    "A configuracao na tela do eixo {} nao veio de uma leitura "
                    "deste drive.\n\nGravar agora escreve corrente {}% (reg "
                    "26) e {}.\n\nSe esses numeros nao foram medidos para "
                    "este motor, use 'Ler do Drive' antes.\n\nGravar mesmo "
                    "assim?".format(self.slave.get(), pct,
                                    MALHAS.get(self._ivar(self.modo_malha), "?"))):
                self.lbl_corr_status.config(
                    text="Gravacao cancelada - leia do drive primeiro", fg=YELLOW)
                return

        ppr_tela = self._ivar(self.lim_ppr, 6000)
        ppr_drive = self._runtime("ppr_lido")
        gravar_ppr = False
        if ppr_drive is not None and ppr_tela != ppr_drive:
            if not (PULSOS_VOLTA_MIN <= ppr_tela <= PULSOS_VOLTA_MAX):
                messagebox.showwarning(
                    "Pulsos por volta",
                    "Use um valor de {} a {}.".format(PULSOS_VOLTA_MIN,
                                                      PULSOS_VOLTA_MAX))
                return
            gravar_ppr = messagebox.askyesno(
                "Trocar pulsos por volta",
                "O drive esta com {} pulsos/volta e a tela pede {}.\n\n"
                "Todo numero em pulsos deste eixo (limites, alvo, velocidades) "
                "passa a significar outra distancia, e o zero deixa de "
                "valer.\n\nGravar os novos pulsos por volta?".format(
                    ppr_drive, ppr_tela))
            if not gravar_ppr:
                self.lim_ppr.set(ppr_drive)

        cfg = {
            "malha": self._ivar(self.modo_malha, MALHA_ABERTA),
            "corrente_pct": pct,
            "ppr": ppr_tela if gravar_ppr else None,
            "standby_ms": max(STANDBY_TEMPO_MIN, min(STANDBY_TEMPO_MAX,
                                                     self._ivar(self.standby_ms, 300))),
            "standby_pct": max(0, min(100, self._ivar(self.corr_standby, 50))),
            "auto": 1 if self._ivar(self.autoajuste) else 0,
            "ganhos": bool(self._ivar(self.ganhos_edit)),
            "kp": max(10, min(32767, self._ivar(self.ganho_p, 1000))),
            "ki": max(0, min(32767, self._ivar(self.ganho_i, 200))),
        }
        self.lbl_corr_status.config(text="Gravando...", fg=YELLOW)
        self._thread_op(self._do_gravar_correntes, cfg, self._pausar_monitor())

    def _do_gravar_correntes(self, cfg, monitor_pausado):
        """Grava e confere (`_gravar_e_conferir`) e devolve o monitor. Em thread."""
        try:
            self._gravar_e_conferir(cfg)
        finally:
            self.after(0, lambda: self._retomar_monitor(monitor_pausado))

    def _gravar_e_conferir(self, cfg):
        """Grava a configuracao, salva (90) e confere por leitura.

        Os ganhos 15/16 so entram com a trava liberada E o autoajuste desligado
        -- com ele ligado o manual os declara somente leitura.

        Cada registrador e relido logo depois de escrito. O eco do FC06 so
        prova que o quadro chegou; a releitura imediata separa "o drive nao
        aceitou o valor" de "o salvamento desfez o valor".

        Escrita RECUSADA (excecao ou silencio) barra o salvamento: nao se sabe
        o que o drive ficou tendo. Valor NAO ACEITO (eco ok, releitura com o
        valor antigo) nao barra: o drive manteve um valor conhecido, e barrar
        deixaria todos os outros registradores sem salvar -- na bancada o reg 0
        nunca aceita, e assim nada sobrevivia a um religamento. O log e a
        mensagem nomeiam o registrador que ficou com o valor do drive.

        Depois do salvamento, rele tudo e compara com o que foi pedido. Os
        campos passam a mostrar o valor real do drive, nao o digitado.
        Roda em thread.
        """
        regs = [
            (REG_MALHA, cfg["malha"]),
            (REG_CORRENTE_OPER_PCT, cfg["corrente_pct"]),
            (REG_STANDBY_TEMPO, cfg["standby_ms"]),
            (REG_STANDBY_PCT, cfg["standby_pct"]),
            (REG_AUTOAJUSTE, cfg["auto"]),
        ]
        if cfg["ppr"] is not None:
            regs.append((REG_PULSOS_VOLTA, cfg["ppr"]))
        if cfg["ganhos"]:
            if cfg["auto"]:
                self._log("[CFG-W] Ganhos NAO gravados: com o autoajuste ligado "
                          "o drive os trata como somente leitura")
            else:
                # Depois do 13 de proposito: so com o autoajuste ja desligado
                # o drive aceita escrever Kp/Ki.
                regs += [(REG_KP, cfg["kp"]), (REG_KI, cfg["ki"])]
                self._log("[CFG-W] Gravacao dos ganhos liberada pelo operador")

        # O MOTOR OFF da tela e estado desta sessao; o drive pode estar
        # habilitado mesmo assim (o 6 vem de fabrica em 1). Fica no log como
        # registro da condicao da gravacao.
        enable = self._ler_regs(REG_ENABLE, 1)
        enable = None if enable is None else enable[0]
        self._log("[CFG-W] Enable (reg 6) antes de gravar: {}".format(
            "sem resposta" if enable is None else enable))

        erros = 0
        nao_aceitos = []             # [(reg, pedido, lido)] na releitura imediata
        for reg, val in regs:
            ok = self._write_reg(reg, val)
            lido = self._ler_regs(reg, 1) if ok else None
            if not ok:
                estado = "FALHOU"
                erros += 1
            elif lido is None:
                estado = "OK (eco), mas a releitura nao respondeu"
            elif lido[0] != val:
                estado = "eco OK, mas o drive manteve {}".format(
                    _texto_valor(reg, lido[0]))
                nao_aceitos.append((reg, val, lido[0]))
            else:
                estado = "OK (relido)"
            self._log("[CFG-W] {} (reg {}) = {}: {}".format(
                _NOMES[reg], reg, _texto_valor(reg, val), estado))

        # O 0 nao e escrito: e o efeito do 26. Le-lo aqui mostra no log o
        # que a corrente pedida virou no drive.
        pico = self._ler_regs(REG_CORRENTE_PICO, 1)
        self._log("[CFG-W] Corrente de pico resultante (reg 0): {}".format(
            "sem resposta" if pico is None else amperes_txt(pico[0])))

        if erros:
            # Salvar agora levaria para a memoria uma configuracao pela metade
            # -- por exemplo a malha nova com a corrente antiga.
            ok_save = False
            self._log("[CFG-W] {} escrita(s) recusada(s): o salvamento (reg 90) "
                      "NAO foi feito. O que o drive aceitou vale so ate ele ser "
                      "desligado.".format(erros))
        else:
            if nao_aceitos:
                self._log("[CFG-W] Salvando o que o drive aceitou; {} fica(m) "
                          "com o valor do drive".format(", ".join(
                              "reg {} = {}".format(r, _texto_valor(r, lido))
                              for r, _, lido in nao_aceitos)))
            ok_save = self._salvar_parametros()
        alvo = self._slave_atual
        if cfg["ppr"] is not None:
            # Todo numero em pulsos mudou de escala: o zero nao vale mais.
            self._runtime_de(alvo, "zero_valido", False, escrever=True)
            self._runtime_de(alvo, "ppr_lido", cfg["ppr"], escrever=True)

        # Le de volta o que o drive realmente guardou
        pedido = dict(regs)
        conferido = {}
        base, _ = self._ler_regs_espera(REG_CORRENTE_PICO, 4)
        if base:
            for i, reg in enumerate((REG_CORRENTE_PICO, REG_PULSOS_VOLTA,
                                     REG_STANDBY_TEMPO, REG_STANDBY_PCT)):
                conferido[reg] = base[i]
        for reg in (REG_MALHA, REG_AUTOAJUSTE, REG_CORRENTE_OPER_PCT):
            v = self._ler_regs(reg, 1)
            if v is not None:
                conferido[reg] = v[0]
        ganhos = self._ler_regs(REG_KP, 2)
        if ganhos is not None:
            conferido[REG_KP], conferido[REG_KI] = ganhos

        divergentes = [(reg, pedido[reg], conferido[reg]) for reg in pedido
                       if reg in conferido and conferido[reg] != pedido[reg]]
        for reg, ped, lido in divergentes:
            self._log("[CFG-V] reg {}: pedido {} mas o drive guardou {}".format(
                reg, ped, lido))

        if conferido:
            self.after(0, lambda: self._mostrar_configuracao(alvo, conferido))

        # A releitura mostra o que o drive tem AGORA, na memoria de trabalho.
        # Que isso sobrevive a desligar o drive, so o teste de religamento
        # prova -- a mensagem nao promete mais do que isso.
        if erros:
            msg, cor = "{} erro(s) ao gravar - nada foi salvo na memoria".format(
                erros), RED
        elif nao_aceitos:
            nomes = ", ".join("reg {}".format(r) for r, _, _ in nao_aceitos)
            msg, cor = ("{} nao aceitou o valor (ficou o do drive); o resto foi "
                        "{}".format(nomes, "salvo (reg 90)" if ok_save else
                                    "gravado, mas o salvamento (reg 90) nao "
                                    "confirmou")), YELLOW
        elif divergentes:
            nomes = ", ".join("reg {}".format(r) for r, _, _ in divergentes)
            msg, cor = ("{} voltou diferente na conferencia depois do "
                        "salvamento".format(nomes)), YELLOW
        elif ok_save:
            msg, cor = ("Aceito e salvo (reg 90). Para provar que ficou na "
                        "memoria: Testar gravacao"), GREEN
        else:
            msg, cor = "Gravado, mas o salvamento (reg 90) nao confirmou", YELLOW
        self._log("[CFG-W] {}".format(msg))
        self.after(0, lambda: self.lbl_corr_status.config(text=msg, fg=cor))

    def _mostrar_configuracao(self, alvo, conferido):
        """Poe na tela a configuracao que o drive `alvo` informou.

        So pinta se `alvo` ainda for o eixo ativo. Na thread da interface.
        """
        if self._slave_operacao() != alvo:
            return
        for reg, var in ((REG_CORRENTE_OPER_PCT, self.corr_oper_pct),
                         (REG_STANDBY_TEMPO, self.standby_ms),
                         (REG_STANDBY_PCT, self.corr_standby),
                         (REG_MALHA, self.modo_malha),
                         (REG_AUTOAJUSTE, self.autoajuste),
                         (REG_KP, self.ganho_p),
                         (REG_KI, self.ganho_i)):
            if reg in conferido:
                var.set(conferido[reg])
        if REG_PULSOS_VOLTA in conferido:
            self._ppr_lido_do_drive(alvo, conferido[REG_PULSOS_VOLTA])
        if REG_MALHA in conferido:
            self._badge_malha(conferido[REG_MALHA], slave=alvo)
        if REG_CORRENTE_PICO in conferido:
            self._runtime_de(alvo, "pico_lido", conferido[REG_CORRENTE_PICO],
                             escrever=True)
            self._mostrar_pico()
        self._curso_resumo()

    # --- TESTE DE GRAVACAO (religamento) ---------------------------------------

    def _testar_gravacao(self):
        """Botao Testar gravacao: inicia o teste de religamento, ou o cancela.

        Ler o registrador logo depois de salvar so mostra a memoria de
        trabalho. A prova de que a corrente ficou gravada e o drive voltar
        com ela depois de perder a alimentacao.

        So com o motor desabilitado e nada em movimento: o operador vai cortar
        a alimentacao do drive.
        """
        if self._teste_grav_ativo:
            self._teste_grav_ativo = False
            self.lbl_corr_status.config(text="Cancelando o teste...", fg=YELLOW)
            return
        if not self._check_conn():
            return
        if (self.motor_on or self.jog_active or self.home_ativo
                or self.teste_ativo or self.curso_mov):
            messagebox.showwarning(
                "Testar gravacao",
                "Pare o movimento e desabilite o motor (MOTOR OFF) antes: o "
                "teste pede para desligar a alimentacao do drive.")
            return
        if not messagebox.askokcancel(
                "Testar gravacao",
                "O teste le a configuracao do eixo {}, espera voce DESLIGAR a "
                "alimentacao do drive e RELIGAR, e le de novo.\n\nValor que "
                "voltar diferente nao estava gravado na memoria.\n\nSe a fonte "
                "for comum, os outros drives tambem desligam. O zero dos eixos "
                "religados deixa de valer.\n\nComecar?".format(self.slave.get())):
            return
        self._teste_grav_ativo = True
        # Com o drive desligado o monitor so colecionaria timeouts, e cada um
        # segura o barramento que o teste usa para perceber a volta.
        self._monitor_pausado_teste = self._pausar_monitor()
        self.btn_testar_grav.config(text="Cancelar teste")
        self.lbl_corr_status.config(text="Lendo a configuracao atual...", fg=YELLOW)
        self._thread_op(self._do_testar_gravacao)

    def _do_testar_gravacao(self):
        """Le a configuracao, espera o religamento, rele e compara. Em thread."""
        alvo = self._slave_atual

        def _status(texto, cor):
            self.after(0, lambda: self.lbl_corr_status.config(text=texto, fg=cor))

        def _fim(texto, cor):
            self._log("[GRAV] {}".format(texto))
            _status(texto, cor)

        try:
            drive = self._drive()
            try:
                antes = drive.ler_configuracao() if drive else None
            except DriveNaoConfirmou as e:
                self._log("[GRAV] {}".format(e))
                antes = None
            if antes is None:
                _fim("Erro ao ler a configuracao - teste nao iniciado", RED)
                return
            self._log("[GRAV] Eixo {} antes de desligar: {}".format(
                alvo, _resumo_configuracao(antes)))

            fases = {
                RELIGA_ESPERANDO: ("DESLIGUE agora a alimentacao do drive {} "
                                   "(prazo {} s)".format(alvo, int(PRAZO_RELIGA)),
                                   YELLOW),
                RELIGA_DESLIGADO: ("Drive {} desligado - RELIGUE a "
                                   "alimentacao".format(alvo), YELLOW),
                RELIGA_RELIGADO: ("Drive {} religado - conferindo...".format(alvo),
                                  YELLOW),
            }

            def _fase(fase):
                texto, cor = fases[fase]
                self._log("[GRAV] {}".format(texto))
                _status(texto, cor)

            voltou = drive.aguardar_religamento(
                prazo=PRAZO_RELIGA, ao_mudar=_fase,
                cancelado=lambda: not (self._teste_grav_ativo and self._conectado))
            if not voltou:
                _fim("Teste cancelado" if not self._teste_grav_ativo else
                     "Teste encerrado: o drive nao foi desligado e religado "
                     "dentro do prazo", YELLOW)
                return

            # Religado, o drive recomeca a contagem: o zero nao vale mais, e a
            # habilitacao da tela tambem nao.
            self._runtime_de(alvo, "zero_valido", False, escrever=True)
            self._runtime_de(alvo, "armado", False, escrever=True)

            depois = None
            for _ in range(5):
                try:
                    depois = drive.ler_configuracao()
                    break
                except DriveNaoConfirmou as e:
                    self._log("[GRAV] {}".format(e))
                    time.sleep(0.5)
            if depois is None:
                _fim("O drive voltou, mas a configuracao nao pode ser lida", RED)
                return
            self._log("[GRAV] Eixo {} depois de religar: {}".format(
                alvo, _resumo_configuracao(depois)))

            # Dois pontos em aberto do manual que o religamento esclarece de
            # graca: se o flag do 90 volta a 0 e como o reg 6 acorda.
            salvar = self._ler_regs(REG_SALVAR, 1)
            enable = self._ler_regs(REG_ENABLE, 1)
            self._log("[GRAV] Apos religar: reg 90 = {} | reg 6 (enable) = {}  "
                      "(anote: sao pontos em aberto do manual)".format(
                          "?" if salvar is None else salvar[0],
                          "?" if enable is None else enable[0]))

            self.after(0, lambda: self._mostrar_configuracao(alvo, depois))
            divergentes = comparar_configuracao(antes, depois)
            for reg, era, voltou_com in divergentes:
                self._log("[GRAV] {} (reg {}): era {} e voltou {}".format(
                    _NOMES[reg], reg, era, voltou_com))
            if divergentes:
                nomes = ", ".join(_NOMES[r] for r, _, _ in divergentes)
                _fim("NAO ficou gravado: {} voltou diferente apos "
                     "religar".format(nomes), RED)
            else:
                _fim("Gravacao comprovada: corrente {} e os outros {} parametros "
                     "voltaram iguais apos religar".format(
                         amperes_txt(depois[REG_CORRENTE_PICO]),
                         len(depois) - 1), GREEN)
        finally:
            self.after(0, self._fim_teste_gravacao_ui)

    def _fim_teste_gravacao_ui(self):
        """Devolve o botao e o monitor ao estado de antes do teste."""
        self._teste_grav_ativo = False
        self.btn_testar_grav.config(text="Testar gravacao (religar drive)")
        self._retomar_monitor(self._monitor_pausado_teste)
        self._monitor_pausado_teste = False


def _texto_valor(reg, valor):
    """O valor de um registrador deste card como o log mostra."""
    if reg == REG_CORRENTE_PICO:
        return amperes_txt(valor)
    if reg == REG_MALHA:
        return "{} ({})".format(valor, MALHAS.get(valor, "?"))
    if reg == REG_CORRENTE_OPER_PCT:
        return "{}%".format(valor)
    return str(valor)


def _resumo_configuracao(cfg):
    """Uma linha com a configuracao lida, para o log."""
    return ("corrente {}% -> pico {} | {} p/volta | standby {}% apos {} ms | {} "
            "| autoajuste {} | Kp/Ki {}/{}".format(
                cfg[REG_CORRENTE_OPER_PCT],
                amperes_txt(cfg[REG_CORRENTE_PICO]), cfg[REG_PULSOS_VOLTA],
                cfg[REG_STANDBY_PCT], cfg[REG_STANDBY_TEMPO],
                MALHAS.get(cfg[REG_MALHA], cfg[REG_MALHA]), cfg[REG_AUTOAJUSTE],
                cfg[REG_KP], cfg[REG_KI]))
