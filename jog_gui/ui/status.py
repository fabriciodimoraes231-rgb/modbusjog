"""Card STATUS DO DRIVE: monitor periodico de status, alarme, posicao e enable."""

import time
import tkinter as tk

from jog_gui.motion import em_falha, motivo_falha
from jog_gui.str6 import (
    REG_ALARME,
    REG_CORRENTE_EFETIVA,
    REG_ENABLE,
    REG_PULSOS_L,
    REG_STATUS,
    REG_TENSAO,
    ST_FALHA,
    ST_LIMITE_NEG,
    ST_LIMITE_POS,
    de_palavras_32,
    nomes_status,
)

from .eixo import HOME_ENTRADA_POS
from .tema import (
    ACCENT2,
    BG2,
    FONT_BOLD,
    FONT_LABEL,
    GREEN,
    RED,
    TEXT,
    TEXT_DIM,
    YELLOW,
)


class StatusMixin:
    """Card STATUS DO DRIVE: monitor periodico de status, alarme, posicao e enable."""

    # Tensao e corrente efetiva mudam devagar: sao lidas a cada N ticks, para
    # nao somar dois quadros a todo ciclo do monitor.
    _POLL_LENTO = 5

    # Segundos que um eixo secundario que nao respondeu fica fora do rodizio.
    _PAUSA_MUDO_S = 10.0

    # Leituras seguidas sem resposta antes de a barra dizer "sem resposta". Um
    # quadro perdido por ruido nao e drive desligado: com 1, a linha piscava
    # "sem resposta" e voltava, e o eixo secundario sumia do rodizio por 10 s.
    _FALHAS_PARA_MUDO = 2

    # De quantos em quantos segundos o log recebe o resumo do barramento.
    _RESUMO_COM_S = 30.0

    def _card_status(self, parent):
        """Monta o card: os rotulos de leitura e o botao do monitor."""
        f = self._card(parent, "STATUS DO DRIVE")

        grid = tk.Frame(f, bg=BG2)
        grid.pack(fill="x")

        labels = [
            ("Status (75):",      "lbl_sw"),
            ("Alarme (115):",     "lbl_err"),
            ("Enable (6):",       "lbl_enable"),
            ("Posicao (39/40):",  "lbl_pos"),
            ("Encoder (41/42):",  "lbl_enc"),
            ("Barramento (48):",  "lbl_tensao"),
            ("Corrente (22):",    "lbl_corr_ef"),
            ("Zero (origem):",    "lbl_zero"),
        ]
        for i, (txt, attr) in enumerate(labels):
            tk.Label(grid, text=txt, bg=BG2, fg=TEXT_DIM, font=FONT_LABEL,
                     anchor="w", width=15).grid(row=i, column=0, sticky="w", pady=2)
            lbl = tk.Label(grid, text="---", bg=BG2, fg=TEXT, font=FONT_BOLD, anchor="w")
            lbl.grid(row=i, column=1, sticky="w", padx=8)
            setattr(self, attr, lbl)

        self.btn_poll = tk.Button(f, text="Iniciar Monitor", font=FONT_BOLD,
                                  bg=ACCENT2, fg="white", bd=0,
                                  padx=10, pady=5, cursor="hand2",
                                  command=self._toggle_poll, state="disabled")
        self.btn_poll.pack(pady=(8, 2))

    # --- MONITORAMENTO --------------------------------------------------------

    def _toggle_poll(self):
        """Liga ou desliga o monitor periodico.

        O monitor e a fonte de quase tudo que a tela mostra ao vivo: posicao,
        estado do sensor, regua do curso e a barra de visao geral. Com ele
        desligado, os rotulos congelam na ultima leitura.
        """
        if self._poll_after:
            self.after_cancel(self._poll_after)
            self._poll_after = None
            self.btn_poll.config(text="Iniciar Monitor")
        else:
            self.btn_poll.config(text="Parar Monitor")
            self._poll_status()

    def _poll_status(self):
        """Dispara uma leitura e reagenda a proxima em 600 ms.

        O reagendamento e por `after`, nao por laco em thread: assim o monitor
        morre junto com a janela. A leitura em si vai para uma thread, para nao
        segurar a interface no timeout da porta.

        So sai um ciclo novo depois que o anterior terminou. Um ciclo com eixo
        mudo leva mais que 600 ms (1 s de timeout por quadro); disparando a
        cada tick, as threads se empilhavam na fila do barramento e qualquer
        outra operacao -- gravacao, salvamento, a vigilancia do JOG -- passava
        a esperar dezenas de segundos pela vez.
        """
        if not self._conectado:
            return
        self._resumo_com()
        if not self._poll_em_voo and not self._movimento_em_curso():
            self._poll_tick += 1
            self._poll_em_voo = True
            self._thread_op(self._do_poll_ciclo,
                            self._poll_tick % self._POLL_LENTO == 1)
        self._poll_after = self.after(600, self._poll_status)

    def _do_poll_ciclo(self, lento):
        """Um ciclo do monitor; libera o proximo ao terminar, de qualquer jeito."""
        try:
            self._do_poll(lento)
        finally:
            self._poll_em_voo = False

    def _movimento_em_curso(self):
        """True enquanto JOG, homing, posicionamento ou teste do sensor rodam.

        Nesses momentos a rotina do movimento ja le status, alarme e posicao
        em laco, e e ela que precisa da resposta a tempo: o watchdog para o
        eixo com duas leituras perdidas. Ela passa a ser a UNICA a falar com o
        drive -- o monitor e a vigilancia do inspetor esperam, e a tela segue
        pelo progresso do proprio movimento (`_progresso_mov`).
        """
        return any(getattr(self, nome, False) for nome in
                   ("jog_active", "home_ativo", "teste_ativo", "curso_mov"))

    def _conta_falha(self, ident):
        """Soma uma leitura sem resposta do eixo `ident`.

        Devolve True quando ja sao _FALHAS_PARA_MUDO seguidas; so entao o
        eixo e mostrado como "sem resposta". Uma leitura boa zera a conta
        (`self._falhas_seguidas.pop`).
        """
        n = self._falhas_seguidas.get(ident, 0) + 1
        self._falhas_seguidas[ident] = n
        return n >= self._FALHAS_PARA_MUDO

    def _resumo_com(self, agora_mesmo=False):
        """A cada _RESUMO_COM_S, leva ao log as falhas do barramento, se houve.

        `agora_mesmo` ignora o intervalo: e o que se quer logo depois de uma
        rotina parar por "comunicacao perdida", para o log dizer de que tipo
        foram as falhas.

        Separa os desfechos (Barramento.estatisticas): "sem resposta" aponta
        endereco, alimentacao ou pedido atropelado; CRC aponta ruido no cabo;
        "de outro endereco" aponta colisao ou dois drives no mesmo endereco.
        Na thread da interface.
        """
        agora = time.time()
        desde = agora - getattr(self, "_resumo_com_em", agora)
        if not agora_mesmo and desde < self._RESUMO_COM_S:
            if not hasattr(self, "_resumo_com_em"):
                self._resumo_com_em = agora
            return
        self._resumo_com_em = agora
        bus = getattr(self, "bus", None)
        if bus is None or not hasattr(bus, "estatisticas"):
            return
        partes = []
        for slave, c in sorted(bus.estatisticas().items()):
            falhas = [(n, nome) for nome, n in (
                ("sem resposta", c["mudo"]), ("CRC", c["crc"]),
                ("de outro endereco", c["outro_slave"]),
                ("erro de porta", c["erro"])) if n]
            if falhas:
                partes.append("drive {}: {} ok, {}".format(
                    slave, c["ok"],
                    ", ".join("{} {}".format(n, nome) for n, nome in falhas)))
        if partes:
            self._log("[COM] ultimos {:.0f} s: {}".format(
                desde, " | ".join(partes)))

    def _pausar_monitor(self):
        """Para o monitor, se estiver rodando. Devolve True se parou.

        Um ciclo que ja estava em voo termina sozinho; quem pausou espera no
        maximo por ele na fila do barramento.
        """
        if not self._poll_after:
            return False
        self._toggle_poll()
        return True

    def _retomar_monitor(self, pausado):
        """Religa o monitor se `pausado` e a conexao ainda existir."""
        if pausado and self._conectado and not self._poll_after:
            self._toggle_poll()

    def _do_poll(self, lento):
        """Le status, alarme, posicao+encoder e enable do eixo ativo.

        Sao quatro quadros (os registradores nao sao vizinhos), mais tensao e
        corrente efetiva quando `lento`. Roda em thread.
        """
        ativo = self._slave_atual
        lido_em = time.time()      # antes da leitura: ver o enable abaixo
        st = self._ler_regs(REG_STATUS, 1)
        if st is None:
            if self._conta_falha(ativo):
                self.after(0, lambda: self._atualizar_linha(ativo, None))
            return
        self._falhas_seguidas.pop(ativo, None)
        alm = self._ler_regs(REG_ALARME, 1)
        contagem = self._ler_regs(REG_PULSOS_L, 4)
        enable = self._ler_regs(REG_ENABLE, 1)
        tensao = self._ler_regs(REG_TENSAO, 1) if lento else None
        efetiva = self._ler_regs(REG_CORRENTE_EFETIVA, 1) if lento else None
        if alm is None or contagem is None or enable is None:
            return

        st, alm, en = st[0], alm[0], enable[0]
        pos = de_palavras_32(contagem[0], contagem[1])
        enc = de_palavras_32(contagem[2], contagem[3])
        self._status_lido = st

        # O drive e a fonte de verdade so para DESABILITAR: um 0 no reg 6 tira
        # o "habilitado" da tela. O contrario nao vale -- o eixo so passa a
        # aceitar movimento depois de um MOTOR ON nesta sessao.
        # So vale leitura feita DEPOIS da habilitacao: um ciclo do monitor que
        # leu 0 antes do MOTOR ON terminar desmarcaria o eixo recem-habilitado,
        # e os movimentos seriam recusados com a tela dizendo "HABILITADO".
        if not en and self._desabilitado_depois_de_armar(ativo, lido_em):
            self._runtime_de(ativo, "armado", False, escrever=True)
            self.after(0, lambda: self._motor_desabilitado_pelo_drive(ativo))

        if em_falha(st, alm) and self._runtime_de(ativo, "armado"):
            self.after(0, lambda: self.lbl_motor_state.config(
                text="Motor: FALHA ATIVA!", fg=RED))

        self.after(0, lambda: self._update_status_labels(
            ativo, st, alm, en, pos, enc, tensao, efetiva))
        self.after(0, lambda: self._curso_ui(pos))
        # A leitura que acabou de sair serve tambem para a linha do eixo ativo
        # na barra de visao geral -- sem custar outra transacao.
        self.after(0, lambda: self._atualizar_linha(
            ativo, {"status": st, "alarme": alm, "enable": en, "pos": pos,
                    "lido_em": lido_em}))

        # E, a cada tick, um dos outros eixos entra no rodizio.
        self._poll_secundarios()

    def _desabilitado_depois_de_armar(self, slave, lido_em):
        """True se o eixo esta marcado como habilitado e a leitura e mais nova
        que a habilitacao -- so assim um enable 0 lido pode desmarca-lo."""
        eixo = self.eixos.get(slave)
        return bool(eixo is not None and eixo.armado
                    and lido_em > eixo.mov.armado_em)

    def _motor_desabilitado_pelo_drive(self, slave):
        """O drive informou enable 0 num eixo que a tela tinha como habilitado."""
        self._log("[MOTOR] Eixo {}: o drive informa enable = 0 - marcado como "
                  "desabilitado".format(slave))
        if self._slave_operacao() == slave:
            self.btn_jog.config(state="disabled")
            self.lbl_motor_state.config(text="Motor: DESABILITADO (lido do drive)",
                                        fg=RED)

    def _poll_secundarios(self):
        """Rele um eixo que NAO e o ativo, para manter a barra de visao geral.

        Um por tick, em rodizio: com 5 eixos e o monitor em 600 ms cada um
        atualiza a cada ~3 s.
        """
        ident = self._proximo_secundario()
        if ident is None:
            return
        resumo = self._ler_resumo_eixo(ident)
        if resumo is None:
            if not self._conta_falha(ident):
                return       # falha isolada: a linha fica com a ultima leitura
            # Cada consulta a um eixo mudo custa 1 s de barramento: ele sai do
            # rodizio por um tempo. A linha dele continua "sem resposta".
            self._secundario_mudo_ate[ident] = time.time() + self._PAUSA_MUDO_S
        else:
            self._falhas_seguidas.pop(ident, None)
            self._secundario_mudo_ate.pop(ident, None)
        self.after(0, lambda: self._atualizar_linha(ident, resumo))

    def _update_status_labels(self, slave, st, alm, en, pos, enc, tensao, efetiva):
        """Pinta os rotulos do card e o do sensor. So na thread da interface."""
        if self._slave_operacao() != slave:
            return                       # leitura de um eixo que ja saiu da tela
        bits = nomes_status(st)
        self.lbl_sw.config(text="0x{:04X}  {}".format(st, "  ".join(bits) or "ok"),
                           fg=RED if st & ST_FALHA else TEXT)
        if em_falha(st, alm):
            self.lbl_err.config(text=motivo_falha(st, alm), fg=RED)
        else:
            self.lbl_err.config(text="sem alarme", fg=TEXT)
        self.lbl_enable.config(text="1 (habilitado)" if en else "0 (desabilitado)",
                               fg=GREEN if en else TEXT_DIM)
        self.lbl_pos.config(text="{} pulsos".format(pos))
        self.lbl_enc.config(text="{}".format(enc))
        if tensao is not None:
            self.lbl_tensao.config(text="{:.1f} V".format(tensao[0] / 10.0))
        if efetiva is not None:
            self.lbl_corr_ef.config(text="{} mA".format(efetiva[0]))
        zero = self.zero_valido
        self.lbl_zero.config(text="estabelecido" if zero else "NAO estabelecido",
                             fg=GREEN if zero else YELLOW)

        # Estado do sensor de origem. As DUAS entradas aparecem: com o fio no
        # terminal errado, e a outra que muda ao passar a lamina -- a selecionada
        # vai entre colchetes e decide a cor.
        positivo = self.home_entrada.get() == HOME_ENTRADA_POS
        acionado = bool(st & (ST_LIMITE_POS if positivo else ST_LIMITE_NEG))
        if self._eixo_tem_origem():
            def _estado(nome, bit, selecionada):
                txt = "{}: {}".format(nome, "ACIONADO" if st & bit else "livre")
                return "[{}]".format(txt) if selecionada else txt
            self.lbl_sensor.config(
                text="{}   {}   (75 = 0x{:04X})".format(
                    _estado("IN1", ST_LIMITE_NEG, not positivo),
                    _estado("IN2", ST_LIMITE_POS, positivo), st),
                fg=GREEN if acionado else TEXT_DIM)
