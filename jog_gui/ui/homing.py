"""Card HOMING: configuracao da entrada do sensor e retorno ao zero."""

from tkinter import messagebox
from tkinter import ttk
import time
import tkinter as tk

from jog_gui.motion import CAUSA_CANCELADO, MovimentoRecusado
from jog_gui.str6 import (
    CTRL_NIVEL_LIM_NEG,
    CTRL_NIVEL_LIM_POS,
    FILTRO_LIMITE_US,
    REG_CONTROLE,
    REG_FILTRO_LIMITE,
    REG_STATUS,
    REG_VEL_HOME,
    ST_LIMITE_NEG,
    ST_LIMITE_POS,
    VEL_MAX_PPS,
)

from .eixo import (
    HOME_ENTRADA_POS,
    HOME_ENTRADAS,
    HOME_MODO_SOFTWARE,
    HOME_MODOS,
)
from .tema import (
    ACCENT,
    ACCENT2,
    BG2,
    BG3,
    FONT_BOLD,
    FONT_LABEL,
    GREEN,
    RED,
    TEXT,
    TEXT_DIM,
    YELLOW,
)

from . import sensores

# As duas entradas que o STR6 le como limite, com o bit do status (75) e o do
# registrador de controle (73) de cada uma.
_ENTRADAS = (
    ("IN1 (lim -)", ST_LIMITE_NEG, CTRL_NIVEL_LIM_NEG),
    ("IN2 (lim +)", ST_LIMITE_POS, CTRL_NIVEL_LIM_POS),
)


def _filtro_ms_para_reg(ms):
    """Filtro em ms -> registrador 74 (unidade 50 us), dentro de 1~65535."""
    return max(1, min(0xFFFF, int(ms) * 1000 // FILTRO_LIMITE_US))


def _filtro_reg_para_ms(valor):
    """Registrador 74 (unidade 50 us) -> ms, arredondado."""
    return int(round(valor * FILTRO_LIMITE_US / 1000.0))


class HomingMixin:
    """Card HOMING: configuracao da entrada do sensor e retorno ao zero."""


    def _card_homing(self, parent):
        """Monta o card inteiro: sensor, entrada, parametros e acionamento.

        O modelo do sensor vem antes da entrada de proposito: "Sem sensor"
        desliga o resto do card, e nao ha por que escolher a entrada de um
        sensor que nao existe.
        """
        f = self._card(parent, "HOMING  (RETORNO AO ZERO)")

        def _linha(texto, largura=17):
            row = tk.Frame(f, bg=BG2)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=texto, bg=BG2, fg=TEXT, font=FONT_LABEL,
                     width=largura, anchor="w").pack(side="left")
            return row

        def _spin(row, var, de, ate, sufixo="", incremento=1):
            tk.Spinbox(row, from_=de, to=ate, increment=incremento,
                       textvariable=var, width=7, bg=BG3, fg=TEXT,
                       buttonbackground=BG3, insertbackground=TEXT,
                       relief="flat", font=FONT_LABEL).pack(side="left")
            if sufixo:
                tk.Label(row, text=sufixo, bg=BG2, fg=TEXT_DIM,
                         font=FONT_LABEL).pack(side="left", padx=4)

        # --- sensor de origem ------------------------------------------------
        row = _linha("Modelo do sensor:")
        cb_sensor = ttk.Combobox(row, textvariable=self.sensor_tipo,
                                 state="readonly", width=28,
                                 values=sensores.nomes())
        cb_sensor.pack(side="left")
        cb_sensor.bind("<<ComboboxSelected>>",
                       lambda _e: self._sensor_trocado())

        self.btn_sensor_sug = tk.Button(
            f, text="Aplicar valores sugeridos deste sensor",
            font=FONT_LABEL, bg=BG3, fg=ACCENT, bd=0, padx=8, pady=3,
            cursor="hand2", command=self._aplicar_sugeridos_sensor)
        self.btn_sensor_sug.pack(fill="x", pady=(0, 4))

        # O STR6 so le sensor nas entradas de limite: IN1 (limite -) e IN2
        # (limite +). A entrada decide tambem o sentido da busca.
        row = _linha("Entrada do sensor:")
        cb_ent = ttk.Combobox(row, textvariable=self.home_entrada,
                              state="readonly", width=16,
                              values=list(HOME_ENTRADAS))
        cb_ent.pack(side="left")
        cb_ent.bind("<<ComboboxSelected>>", lambda _e: self._entrada_trocada())
        self.lbl_home_sentido = tk.Label(row, text="", bg=BG2, fg=TEXT_DIM,
                                         font=FONT_LABEL)
        self.lbl_home_sentido.pack(side="left", padx=6)

        row = _linha("Nivel do sinal:")
        tk.Checkbutton(row, text="ativo com o opto DESLIGADO (reg 73)",
                       variable=self.home_inv,
                       bg=BG2, fg=TEXT, selectcolor=BG3, activebackground=BG2,
                       font=FONT_LABEL).pack(side="left")
        row = _linha("Filtro do limite:")
        _spin(row, self.home_filtro, 0, 3000, "ms   (reg 74, x 50 us)")

        # Estado ao vivo do sensor: so atualiza com o monitor ligado, e e a forma
        # pratica de conferir a fiacao (acione o sensor e veja o rotulo mudar)
        self.lbl_sensor = tk.Label(f, text="Sensor: --- (ligue o monitor)",
                                   bg=BG2, fg=TEXT_DIM, font=FONT_BOLD)
        self.lbl_sensor.pack(pady=(2, 2))

        # Fiacao do modelo escolhido -- o texto vem do catalogo (ui/sensores.py)
        self.lbl_sensor_fiacao = tk.Label(
            f, text="", bg=BG2, fg=TEXT_DIM, font=("Segoe UI", 8),
            justify="center")
        self.lbl_sensor_fiacao.pack(pady=(0, 4))

        row_di = tk.Frame(f, bg=BG2)
        row_di.pack(fill="x", pady=(0, 6))
        self.btn_le_di = tk.Button(row_di, text="Ler do drive",
                                   font=FONT_BOLD, bg=BG3, fg=ACCENT, bd=0,
                                   padx=8, pady=5, cursor="hand2",
                                   command=self._ler_config_di, state="disabled")
        self.btn_le_di.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.btn_grava_di = tk.Button(row_di, text="Gravar e salvar",
                                      font=FONT_BOLD, bg=ACCENT2, fg="white", bd=0,
                                      padx=8, pady=5, cursor="hand2",
                                      command=self._gravar_config_di, state="disabled")
        self.btn_grava_di.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.btn_teste_di = tk.Button(row_di, text="TESTAR SENSOR",
                                      font=FONT_BOLD, bg=YELLOW, fg="white", bd=0,
                                      padx=8, pady=5, cursor="hand2",
                                      command=self._testar_sensor, state="disabled")
        self.btn_teste_di.pack(side="right", expand=True, fill="x")

        # --- parametros do homing ----------------------------------------------
        row = _linha("Modo:")
        ttk.Combobox(row, textvariable=self.home_modo, state="readonly", width=28,
                     values=list(HOME_MODOS)).pack(side="left")

        row = _linha("Aproximacao:")
        _spin(row, self.home_v_apr, 100, VEL_MAX_PPS, "p/s   (reg 64/65)", 100)
        row = _linha("Rastejo / retorno:")
        _spin(row, self.home_v_ras, 10, VEL_MAX_PPS, "p/s   (reg 60)", 50)
        tk.Label(f, text="Nativo: o drive vai ate o sensor na aproximacao e volta\n"
                         "ate o sinal no rastejo (manual p. 18). Zero: reg 40 = 1.",
                 bg=BG2, fg=TEXT_DIM, font=("Segoe UI", 8),
                 justify="center").pack(pady=(2, 0))

        # --- acionamento --------------------------------------------------------
        row_btns = tk.Frame(f, bg=BG2)
        row_btns.pack(fill="x", pady=(8, 2))
        self.btn_home = tk.Button(row_btns, text="INICIAR HOMING", font=FONT_BOLD,
                                  bg=ACCENT, fg="white", bd=0, padx=12, pady=8,
                                  cursor="hand2", command=self._iniciar_homing,
                                  state="disabled")
        self.btn_home.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.btn_home_stop = tk.Button(row_btns, text="PARAR", font=FONT_BOLD,
                                       bg=RED, fg="white", bd=0, padx=12, pady=8,
                                       cursor="hand2", command=self._parar_homing,
                                       state="disabled")
        self.btn_home_stop.pack(side="right", expand=True, fill="x")

        self.lbl_home_status = tk.Label(f, text="Homing: nao executado",
                                        bg=BG2, fg=TEXT_DIM, font=FONT_LABEL,
                                        wraplength=330)
        self.lbl_home_status.pack()

    # --- SENSOR DE ORIGEM ------------------------------------------------------

    # Widgets que so fazem sentido num eixo com sensor. Ficam numa lista para
    # que o bloqueio e a reconexao nao saiam de sincronia: _set_connected liga
    # tudo em bloco e chama _aplicar_restricao_sensor logo depois.
    _BTNS_DEPENDEM_SENSOR = ("btn_le_di", "btn_grava_di", "btn_teste_di",
                             "btn_home", "btn_home_stop")

    def _sensor_atual(self):
        """O objeto Sensor do modelo escolhido na tela."""
        return sensores.obter(self.sensor_tipo.get())

    def _eixo_tem_origem(self) -> bool:
        """Este eixo consegue estabelecer um zero?"""
        return self._sensor_atual().tem_origem

    def _entrada_indice(self) -> int:
        """0 para IN1 (limite -), 1 para IN2 (limite +) -- indice de _ENTRADAS."""
        return 1 if self.home_entrada.get() == HOME_ENTRADA_POS else 0

    def _entrada_trocada(self):
        """Atualiza o sentido da busca mostrado ao lado da entrada."""
        if hasattr(self, "lbl_home_sentido"):
            self.lbl_home_sentido.config(
                text="busca para {}".format(
                    "FRENTE" if self._entrada_indice() else "TRAS"))

    def _sensor_trocado(self):
        """Reage a troca do modelo no combobox.

        NAO escreve os valores sugeridos: filtro, aproximacao e rastejo custam
        horas de medicao, e uma troca de modelo por engano nao pode apaga-los.
        Quem aplica e o botao ao lado.
        """
        self._atualizar_painel_sensor()
        s = self._sensor_atual()
        self._log("[SENSOR] Modelo do eixo {}: {}{}".format(
            self.slave.get(), s.nome,
            "" if s.tem_origem else " - sem origem: homing indisponivel"))

    def _atualizar_painel_sensor(self):
        """Sincroniza rotulo de fiacao, sentido da busca, sugeridos e bloqueio.

        Pode ser chamado antes de o card existir: _carregar_eixos roda dentro
        de __init__, antes de _card_homing montar os widgets.
        """
        if not hasattr(self, "lbl_sensor_fiacao"):
            return
        s = self._sensor_atual()
        self.lbl_sensor_fiacao.config(text=s.fiacao)
        self.btn_sensor_sug.config(
            state="normal" if s.tem_origem else "disabled")
        self._entrada_trocada()
        self._aplicar_restricao_sensor()

    def _aplicar_restricao_sensor(self):
        """Desliga o que depende de origem fisica quando nao ha sensor.

        Chamado tambem no fim de _set_connected(True), que habilita os botoes
        em bloco -- sem isso um eixo sem sensor voltaria da conexao com
        INICIAR HOMING clicavel.
        """
        if not hasattr(self, "lbl_home_status"):
            return
        s = self._sensor_atual()
        if not s.tem_origem:
            for nome in self._BTNS_DEPENDEM_SENSOR:
                w = getattr(self, nome, None)
                if w is not None:
                    w.config(state="disabled")
            self.lbl_home_status.config(
                text="Homing indisponivel: eixo sem sensor de origem",
                fg=TEXT_DIM)
            self.lbl_sensor.config(text="Sensor: nao ha", fg=TEXT_DIM)
            return
        # Com sensor: desfaz o rotulo do bloqueio e devolve os botoes, desde
        # que haja conexao e nada esteja rodando.
        if self.lbl_home_status.cget("text").startswith("Homing indisponivel"):
            self.lbl_home_status.config(text="Homing: nao executado", fg=TEXT_DIM)
        if not getattr(self, "_conectado", False):
            return
        if getattr(self, "home_ativo", False) or getattr(self, "teste_ativo", False):
            return                      # rotina em curso manda no estado
        for nome in self._BTNS_DEPENDEM_SENSOR:
            if nome == "btn_home_stop":
                continue                # so vive enquanto o homing roda
            w = getattr(self, nome, None)
            if w is not None:
                w.config(state="normal")

    def _aplicar_sugeridos_sensor(self):
        """Escreve na tela os valores de partida do modelo, sob confirmacao."""
        s = self._sensor_atual()
        if not s.tem_origem:
            return
        sug = s.sugeridos
        aviso = ("" if s.confirmado else
                 "\n\nATENCAO: estes valores NAO foram medidos nesta bancada. "
                 "Sao um ponto de partida derivado do tipo de sensor e "
                 "precisam de validacao em bancada antes de valer para "
                 "producao.")
        pergunta = (
            "Substituir na tela os parametros do homing pelos sugeridos "
            "para {}?\n\n"
            "  filtro        {} ms\n"
            "  aproximacao   {} p/s\n"
            "  rastejo       {} p/s\n\n"
            "Repetibilidade: {}\n\n"
            "Isto altera so a tela - nada vai para o drive ate voce "
            "gravar.{}".format(
                s.nome, sug["home_filtro"], sug["home_v_apr"],
                sug["home_v_ras"], s.repetibilidade, aviso))
        if not messagebox.askyesno("Aplicar valores sugeridos", pergunta):
            return
        self.home_filtro.set(sug["home_filtro"])
        self.home_v_apr.set(sug["home_v_apr"])
        self.home_v_ras.set(sug["home_v_ras"])
        self._log("[SENSOR] Sugeridos de {} aplicados na tela "
                  "(filtro {} ms, apr {} p/s, ras {} p/s){}".format(
                      s.nome, sug["home_filtro"], sug["home_v_apr"],
                      sug["home_v_ras"],
                      "" if s.confirmado else " - NAO validados em bancada"))

    # --- CONFIGURACAO DA ENTRADA (73, 74, 60) ------------------------------------

    def _ler_config_di(self):
        """Traz para a tela o que esta gravado no drive, em vez do que se pretende."""
        if not self._check_conn():
            return
        self.btn_le_di.config(state="disabled")
        self._thread_op(self._do_ler_config_di, self._entrada_indice())

    def _do_ler_config_di(self, idx):
        """Le o controle (73), o filtro dos limites (74) e a velocidade de
        retorno a zero (60). Roda em thread."""
        nome, _, bit_ctrl = _ENTRADAS[idx]
        ctrl = self._ler_regs(REG_CONTROLE, 1)
        filtro = self._ler_regs(REG_FILTRO_LIMITE, 1)
        v_home = self._ler_regs(REG_VEL_HOME, 1)
        if ctrl is None or filtro is None:
            self._log("[DI] ERRO ao ler reg 73/74")
            self.after(0, lambda: self.lbl_home_status.config(
                text="Erro ao ler a config. da entrada!", fg=RED))
            self.after(0, lambda: self.btn_le_di.config(state="normal"))
            return

        invertido = not (ctrl[0] & bit_ctrl)
        filtro_ms = _filtro_reg_para_ms(filtro[0])
        self._log("[DI] No drive: reg 73 = 0x{:04X} ({} ativo com o opto {}) | "
                  "reg 74 = {} (~{} ms) | reg 60 = {}".format(
                      ctrl[0], nome, "DESLIGADO" if invertido else "conduzindo",
                      filtro[0], filtro_ms,
                      "?" if v_home is None else "{} p/s".format(v_home[0])))

        def _apply():
            self.home_inv.set(1 if invertido else 0)
            self.home_filtro.set(filtro_ms)
            if v_home is not None:
                self.home_v_ras.set(v_home[0])
            self.lbl_home_status.config(
                text="No drive: {} ativo com o opto {} | filtro ~{} ms".format(
                    nome, "DESLIGADO" if invertido else "conduzindo", filtro_ms),
                fg=GREEN)
            self.btn_le_di.config(state="normal")
        self.after(0, _apply)

    def _gravar_config_di(self):
        """Grava nivel, filtro e velocidade de retorno. A escrita vai em thread."""
        if not self._check_conn():
            return
        if self.home_ativo:
            messagebox.showwarning("Homing em curso",
                                   "Espere o homing terminar antes de gravar.")
            return
        cfg = (self._entrada_indice(), bool(self._ivar(self.home_inv)),
               self._ivar(self.home_filtro, 2),
               max(1, min(0xFFFF, self._ivar(self.home_v_ras, 1000))))
        self.btn_grava_di.config(state="disabled")
        self._thread_op(self._do_gravar_config_di, *cfg)

    def _do_gravar_config_di(self, idx, invertido, filtro_ms, v_home):
        """
        Ajusta o nivel do sinal da entrada do sensor no reg 73, o filtro dos
        limites (74) e a velocidade de retorno a zero (60), e salva (90).

        O 73 e lido antes e so o bit desta entrada muda: os demais bits (nivel
        da outra entrada, movimento por IO) ficam como estao.

        O sensor NPN drena corrente: com IN+ em +24 V, o optoacoplador conduz
        quando o sensor aciona -- e esse e o padrao de fabrica (bit em 1).
        Um sensor NF inverte a leitura, e ai entra o nivel invertido. Confira
        no rotulo "Sensor:" com o monitor ligado ANTES de mandar o eixo andar.
        """
        nome, _, bit_ctrl = _ENTRADAS[idx]
        ctrl = self._ler_regs(REG_CONTROLE, 1)
        if ctrl is None:
            self._log("[DI] reg 73 nao pode ser lido - nada foi gravado")
            self.after(0, lambda: self.lbl_home_status.config(
                text="Erro ao ler o reg 73 - nada gravado", fg=RED))
            self.after(0, lambda: self.btn_grava_di.config(state="normal"))
            return
        novo = ctrl[0] & ~bit_ctrl & 0xFFFF if invertido else ctrl[0] | bit_ctrl

        ok_ctrl = self._write_reg_retry(REG_CONTROLE, novo)
        self._log("[DI] Controle (reg 73) = 0x{:04X} ({} ativo com o opto {}): {}"
                  .format(novo, nome, "DESLIGADO" if invertido else "conduzindo",
                          "OK" if ok_ctrl else "FALHOU"))
        reg_filtro = _filtro_ms_para_reg(filtro_ms)
        ok_flt = self._write_reg_retry(REG_FILTRO_LIMITE, reg_filtro)
        self._log("[DI] Filtro dos limites (reg 74) = {} (~{} ms): {}".format(
            reg_filtro, filtro_ms, "OK" if ok_flt else "FALHOU"))
        ok_vel = self._write_reg_retry(REG_VEL_HOME, v_home)
        self._log("[DI] Velocidade de retorno a zero (reg 60) = {} p/s: {}".format(
            v_home, "OK" if ok_vel else "FALHOU"))

        ok = ok_ctrl and ok_flt and ok_vel and self._salvar_parametros()
        conferido = self._ler_regs(REG_CONTROLE, 1)
        if conferido is not None and conferido[0] != novo:
            ok = False
            self._log("[DI] reg 73: pedido 0x{:04X} mas o drive guardou 0x{:04X}"
                      .format(novo, conferido[0]))

        msg = "Entrada configurada e salva." if ok else "Erro ao configurar a entrada!"
        self.after(0, lambda: self.lbl_home_status.config(
            text=msg, fg=GREEN if ok else RED))
        self.after(0, lambda: self.btn_grava_di.config(state="normal"))

    # --- TESTE DO SENSOR (sem mover o eixo) -----------------------------------

    _TESTE_DURACAO   = 30.0   # s de duracao maxima do teste
    _TESTE_INTERVALO = 0.1    # s entre leituras do 75

    def _testar_sensor(self):
        """
        Le o status (75) em rajada para provar que o drive enxerga o sensor,
        sem energizar o motor. O operador passa a bandeira pela ranhura com a
        mao e o teste conta as transicoes.
        """
        if self.teste_ativo:
            self.teste_ativo = False
            return
        if not self._check_conn():
            return
        self.teste_ativo = True
        self.btn_teste_di.config(text="PARAR TESTE", bg=RED)
        self.btn_home.config(state="disabled")
        self._thread_op(self._do_teste_sensor, self._entrada_indice())

    def _do_teste_sensor(self, idx):
        """Le o 75 a cada 100 ms por ate 30 s e diagnostica a fiacao.

        Conta as bordas das DUAS entradas de limite, nao so da selecionada: se
        o fio estiver no terminal errado, o log diz em qual ele comutou -- que
        e a pergunta que o operador tem nesse momento.

        Tres desfechos: a entrada escolhida comutou (OK, resta confirmar que o
        "acionado" e o came DENTRO da fenda); a outra comutou (terminal
        errado); nenhuma comutou (24 V, fio ou IN+). Roda em thread e nao
        energiza o motor.
        """
        t0         = time.time()
        ultimo_t   = t0
        anterior   = None
        primeiro   = None   # primeira leitura: estado de repouso do teste
        t_acionado = 0.0
        bordas     = [0, 0]
        falhas     = 0
        bit_sel    = _ENTRADAS[idx][1]

        self._log("[TESTE] Lendo o reg 75 por {:.0f} s - passe a bandeira pela "
                  "ranhura do sensor".format(self._TESTE_DURACAO))

        while self.teste_ativo and (time.time() - t0) < self._TESTE_DURACAO:
            vals = self._ler_regs(REG_STATUS, 1)
            agora = time.time()
            if vals is None:
                falhas += 1
                if falhas >= 5:
                    self._teste_fim("Drive sem resposta - teste abortado", False)
                    return
                time.sleep(self._TESTE_INTERVALO)
                continue
            falhas = 0
            st = vals[0]
            if primeiro is None:
                primeiro = st

            if anterior is not None:
                for i, (nome, bit, _) in enumerate(_ENTRADAS):
                    if (st ^ anterior) & bit:
                        bordas[i] += 1
                        self._log("[TESTE] {}{}: {} -> {}".format(
                            "* " if i == idx else "  ", nome,
                            int(bool(anterior & bit)), int(bool(st & bit))))
            if st & bit_sel:
                t_acionado += agora - ultimo_t
            ultimo_t = agora
            anterior = st

            restante = self._TESTE_DURACAO - (agora - t0)
            self.after(0, lambda s=st, b=bordas[idx], r=restante:
                       self._teste_ui(idx, s, b, r))
            time.sleep(self._TESTE_INTERVALO)

        def _bit(valor, bit):
            return "acionado" if valor is not None and valor & bit else "livre"

        nome_sel = _ENTRADAS[idx][0]
        outro = 1 - idx
        if bordas[idx]:
            ok = True
            msg = ("OK: {} comutou {}x (repouso={}, fim={}, {:.1f} s acionado) "
                   "- confirme que 'acionado' e o came DENTRO da fenda".format(
                       nome_sel, bordas[idx], _bit(primeiro, bit_sel),
                       _bit(anterior, bit_sel), t_acionado))
        elif bordas[outro]:
            ok = False
            msg = ("{} nao comutou; quem comutou foi {} ({}x) - selecione essa "
                   "entrada na tela ou mova o fio".format(
                       nome_sel, _ENTRADAS[outro][0], bordas[outro]))
        else:
            ok = False
            msg = ("Nenhuma entrada mudou - confira alimentacao 24 V, o fio do "
                   "sinal em IN1/IN2 e IN+ em +24 V")
        self._teste_fim(msg, ok)

    def _teste_ui(self, idx, st, bordas, restante):
        """Mostra o estado ao vivo do sensor durante o teste. Thread da interface."""
        nome, bit, _ = _ENTRADAS[idx]
        acionado = bool(st & bit)
        self.lbl_sensor.config(
            text="Sensor {}: {}   (75 = 0x{:04X})".format(
                nome, "ACIONADO" if acionado else "livre", st),
            fg=GREEN if acionado else TEXT_DIM)
        self.lbl_home_status.config(
            text="Teste: {:.0f} s restantes  |  {} transicoes".format(restante, bordas),
            fg=YELLOW)

    def _teste_fim(self, msg: str, ok: bool):
        """Encerra o teste do sensor e devolve os botoes ao estado de repouso."""
        self.teste_ativo = False
        self._log("[TESTE] {}".format(msg))

        def _ui():
            self.btn_teste_di.config(text="TESTAR SENSOR", bg=YELLOW)
            if self._conectado:
                self.btn_home.config(state="normal")
            self.lbl_home_status.config(text=msg, fg=GREEN if ok else RED)
        self.after(0, _ui)

    # --- HOMING (RETORNO AO ZERO) ---------------------------------------------

    def _iniciar_homing(self):
        """Confirma com o operador e dispara o retorno ao zero.

        A confirmacao mostra quantos GRAUS o eixo gira dentro do filtro da
        entrada, na aproximacao e no rastejo: o sensor de garfo so enxerga a
        bandeira dentro dos 5 mm, e filtro alto com velocidade alta passa
        batido pela referencia sem que nada acuse erro.

        Escolhe entre `homing_software` (busca conduzida pelo programa) e
        `homing_nativo` (retorno a zero do drive, reg 71) conforme o modo.
        """
        if not self._check_conn():
            return
        if not self.motor_on:
            messagebox.showwarning(
                "Motor desabilitado",
                "Habilite o motor (MOTOR ON) antes de iniciar o homing.")
            return
        if self.jog_active or self.curso_mov:
            messagebox.showwarning("Movimento em curso",
                                   "Pare o JOG ou o posicionamento antes do homing.")
            return

        software = self.home_modo.get() == HOME_MODO_SOFTWARE
        ppr = max(1, self._ivar(self.lim_ppr, 6000))
        filtro_s = self._ivar(self.home_filtro, 2) / 1000.0
        v_apr = self._ivar(self.home_v_apr, 6000)
        v_ras = self._ivar(self.home_v_ras, 1000)
        graus_apr = v_apr * filtro_s / ppr * 360.0
        graus_ras = v_ras * filtro_s / ppr * 360.0
        entrada = self.home_entrada.get()
        detalhe = "{} no {}, buscando para {}".format(
            "Busca por software" if software else "Retorno a zero do drive (reg 71)",
            entrada, "FRENTE" if self._entrada_indice() else "TRAS")
        if not messagebox.askokcancel(
                "Confirmar homing",
                "O eixo vai se movimentar ate encontrar a referencia.\n\n"
                "{}\n"
                "Aproximacao: {} p/s   |   Rastejo: {} p/s\n"
                "Filtro da entrada: {} ms  ->  o eixo gira {:.1f} graus na "
                "aproximacao e {:.1f} graus no rastejo antes do drive "
                "reconhecer o sensor.\n\n"
                "Confirme que a area esta livre e que ha como cortar a energia "
                "rapidamente.".format(detalhe, v_apr, v_ras,
                                      self._ivar(self.home_filtro, 2),
                                      graus_apr, graus_ras)):
            return

        mov = self._preparar_mov()
        self._mov_home = mov
        self.home_ativo = True
        self.btn_home.config(state="disabled", text="HOMING...")
        self.btn_home_stop.config(state="normal")
        self.btn_jog.config(state="disabled")
        self.lbl_home_status.config(text="Homing: em andamento...", fg=YELLOW)
        self._thread_op(self._do_homing, mov, software)

    def _do_homing(self, mov, software):
        """Roda o homing escolhido e devolve a UI ao repouso. Roda em thread."""
        try:
            res = mov.homing_software() if software else mov.homing_nativo()
        except MovimentoRecusado as e:
            self._homing_fim(False, e.mensagem)
            return
        except Exception as e:
            mov.parada_segura("Falha na rotina de homing")
            self._homing_fim(False, "falha: {}".format(e))
            return
        if res.causa == CAUSA_CANCELADO:
            self._homing_fim(False, "Interrompido pelo operador")
        else:
            self._homing_fim(res.ok, res.detalhe)

    def _parar_homing(self):
        """Interrompe o retorno ao zero a pedido do operador.

        Marca o cancelamento -- o laco do homing para o eixo na proxima
        leitura e encerra com CANCELADO -- e manda a parada ja, sem esperar
        esse ciclo.
        """
        if not self.home_ativo:
            return
        mov = getattr(self, "_mov_home", None)
        self.lbl_home_status.config(text="Homing: parando...", fg=YELLOW)
        if mov is not None:
            mov.cancelar()
            self._thread_op(mov.parada_segura, "Homing interrompido pelo operador",
                            slave=mov.config.slave)

    def _homing_fim(self, ok: bool, msg: str):
        """Devolve a UI ao estado de repouso apos o homing.

        O zero ja foi decidido pelo EixoMovimento: valido so com o contador
        confirmado em zero, invalido em qualquer outro desfecho.
        """
        self.home_ativo = False
        self._log("[HOME] {}".format(msg))

        def _ui():
            self.btn_home.config(state="normal", text="INICIAR HOMING")
            self.btn_home_stop.config(state="disabled")
            if self.motor_on:
                self.btn_jog.config(state="normal")
            else:
                self.lbl_motor_state.config(text="Motor: DESABILITADO", fg=RED)
            self.lbl_home_status.config(text="Homing: {}".format(msg),
                                        fg=GREEN if ok else RED)
            self._curso_resumo()
            if not ok and self._ivar(self.lim_ativo):
                self.lbl_curso_status.config(
                    text="Curso: zero invalido - refaca o homing antes de usar "
                         "os limites", fg=YELLOW)
        self.after(0, _ui)
