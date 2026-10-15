"""Um eixo de passo no STR6-RS485: mover, referenciar, parar. Sem Tkinter.

E a unica camada que junta o mapa de registradores com o driver, e onde mora a
regra de movimento. A GUI (jog_gui.ui) e os scripts usam a mesma logica daqui,
em vez de cada um manter a sua -- duas implementacoes do mesmo movimento
acabam divergindo, e a correcao de bancada entra so numa delas.

O que este arquivo NAO faz, de proposito:

  - nao decide nada sobre concorrencia entre eixos. Um Barramento e half-duplex
    e quem arbitra quem fala e o chamador (a janela, ou o script);
  - nao guarda a configuracao do operador. Ela chega como ConfigEixo e e lida
    UMA vez, no inicio de cada operacao -- nunca reconsultada no meio de um
    laco;
  - nao trata parada de emergencia de verdade. Isso e hardware.

Como o STR6 move (manual p. 14-15):

  - perfil em 62~69: desaceleracao, velocidade, aceleracao e curso, 32 bits
    cada, palavra baixa primeiro. Vai num unico FC16;
  - comando em 70: 1/2 comprimento fixo para frente/tras, 3/4 continuo,
    0 desacelera ate parar, 5 para na hora. Depois de aceito o registrador
    volta sozinho para 6, entao repetir o mesmo comando dispara de novo;
  - status em 75: bit 7 "envio de pulsos nao concluido", bits 4/5 os sinais de
    limite (onde fica o sensor de origem), bits 0/1 sobrecorrente/sobretensao;
  - alarme em 115 e contador de pulsos em 39/40.

Bloqueante. Todo laco consulta `self._cancelado` e tem prazo proprio, e toda
espera passa por `_dormir`/`_agora` -- os testes trocam os dois por um relogio
virtual.
"""

import time

from jog_gui.str6 import (
    CMD_CONTINUO_FRENTE,
    CMD_CONTINUO_TRAS,
    CMD_DESACELERAR,
    CMD_FRENTE,
    CMD_PARADA_IMEDIATA,
    CMD_TRAS,
    DriveNaoConfirmou,
    HOME_LIMITE_NEG,
    HOME_LIMITE_POS,
    HOME_SAIR,
    REG_ALARME,
    REG_COMANDO,
    REG_DESACEL_L,
    REG_ENABLE,
    REG_HOME,
    REG_LIMPA_FALHA,
    REG_MODO_POSICAO,
    REG_PULSOS_H,
    REG_PULSOS_L,
    REG_STATUS,
    REG_VEL_HOME,
    ST_EM_MOVIMENTO,
    ST_FALHA,
    ST_LIMITE_NEG,
    ST_LIMITE_POS,
    ST_SOBRECORRENTE,
    ST_SOBRETENSAO,
    VEL_MAX_PPS,
    de_palavras_32,
    nome_alarme,
    perfil_movimento,
)

from . import limites
from .config import ENTRADA_LIM_POS, FRENTE, oposto


# --- resultado de uma operacao ------------------------------------------------

# As causas sao enumeradas, e nao texto livre, para que quem chama possa
# distinguir "fim de curso batido", "alarme do drive" e "movimento abortado"
# sem interpretar mensagem.
CAUSA_OK = ""
CAUSA_MOTOR_OFF = "MOTOR_OFF"
CAUSA_FORA_DA_FAIXA = "FORA_DA_FAIXA"
CAUSA_ZERO_INVALIDO = "ZERO_INVALIDO"
CAUSA_SEM_SENSOR = "SEM_SENSOR"
CAUSA_DRIVE_MUDO = "DRIVE_MUDO"
CAUSA_ALARME = "ALARME"
CAUSA_TIMEOUT = "TIMEOUT"
CAUSA_NAO_PARTIU = "NAO_PARTIU"
CAUSA_CANCELADO = "CANCELADO"
CAUSA_RECUSADO = "RECUSADO"
CAUSA_LIMITE = "LIMITE"


def em_falha(status, alarme):
    """True quando o drive sinaliza falha: codigo em 115 ou bit 0/1 de 75."""
    return bool(alarme) or bool(status & ST_FALHA)


def motivo_falha(status, alarme):
    """Texto da falha, distinguindo o que o 115 nao explica.

    O status (75) tem bits proprios de sobrecorrente e sobretensao. Se um
    deles subir com o 115 em zero, `nome_alarme` diria "sem alarme" --
    exatamente o oposto do que aconteceu.
    """
    if alarme:
        return nome_alarme(alarme)
    if status & ST_SOBRECORRENTE:
        return "sobrecorrente sinalizada no status (75 bit 0)"
    if status & ST_SOBRETENSAO:
        return "sobretensao sinalizada no status (75 bit 1)"
    return nome_alarme(alarme)


class Resultado:
    """O desfecho de uma operacao: ok, a causa quando nao, e o que foi medido.

    Existe para que nenhuma operacao devolva apenas True/False: uma recusa que
    nao diz o motivo nao se distingue de um drive mudo.
    """

    __slots__ = ("ok", "causa", "detalhe", "posicao", "valor")

    def __init__(self, ok, causa=CAUSA_OK, detalhe="", posicao=None, valor=None):
        self.ok = bool(ok)
        self.causa = causa
        self.detalhe = detalhe
        self.posicao = posicao
        self.valor = valor          # dado proprio da operacao (ex.: sentido)

    def __bool__(self):
        """`if resultado:` le como "deu certo".

        CUIDADO: por causa disto, uma variavel que guarda UMA FALHA tambem e
        falsa, e `if falha:` nunca dispara. Quem recebe "um Resultado quando
        deu errado, ou None quando deu certo" -- como `_esperar_sensor` --
        precisa testar `is not None`.
        """
        return self.ok

    def __repr__(self):
        if self.ok:
            return "Resultado(ok, {!r})".format(self.detalhe)
        return "Resultado(falha, {}, {!r})".format(self.causa, self.detalhe)


class MovimentoRecusado(Exception):
    """Pedido invalido, recusado ANTES de qualquer escrita no drive.

    Separado de DriveNaoConfirmou de proposito: aqui nada foi para o fio, e o
    eixo nao se moveu.
    """

    def __init__(self, causa, mensagem):
        super().__init__(mensagem)
        self.causa = causa
        self.mensagem = mensagem


# --- o eixo -------------------------------------------------------------------

class EixoMovimento:
    """Um eixo do barramento: as operacoes de movimento, sem tela.

    Uso tipico:

        eixo = EixoMovimento(Drive(bus, 1), ConfigEixo(1, "socket"))
        eixo.armar()
        res = eixo.ir_para(5000)
        if not res:
            print(res.causa, res.detalhe)

    `drive` pode ser None enquanto nao ha barramento: toda escrita falha e toda
    leitura devolve None, sem excecao. A GUI cria o eixo no cadastro e so liga
    o drive ao conectar.
    """

    # --- constantes de tempo -------------------------------------------------

    POLL = 0.06              # s entre leituras durante um movimento
    PASSO_TIMEOUT = 60.0     # s ate desistir de um passo
    # Silencio tolerado numa leitura: o drive pode calar enquanto grava
    # parametros, e um movimento pedido logo em seguida nao pode morrer por
    # isso
    SILENCIO = 8.0
    # Folga para considerar o eixo parado entre duas leituras: exigir posicao
    # identica nunca fecharia com a contagem oscilando 1 pulso.
    PASSO_ESTAVEL = 2        # pulsos
    # Tempo dado ao drive para sair do lugar depois do comando. Passado isso
    # sem pulso nenhum, o comando e repetido uma vez em vez de esperar o
    # timeout inteiro.
    PASSO_PARTIDA = 2.0      # s
    HOME_TIMEOUT = 120.0     # s ate desistir do retorno ao zero
    HOME_POLL = 0.03         # s entre leituras do sensor durante a busca
    # Retorno a zero nativo: eixo parado por este tempo, depois de ter
    # partido, conta como fim -- o manual nao diz como o drive sinaliza a
    # conclusao, e o bit 7 de 75 tem descricao ambigua.
    HOME_PARADO = 1.5        # s
    HOME_PARTIDA = 3.0       # s
    WD_FALHAS_MAX = 2        # leituras seguidas sem resposta antes de parar

    def __init__(self, drive, config, log=None, on_progress=None):
        """Amarra um Drive a uma ConfigEixo.

        Args:
            drive: str6.Drive sobre o Barramento compartilhado, ou None.
            config: ConfigEixo com os ajustes do operador.
            log: callable de um argumento (str). O padrao descarta -- a janela
                passa o painel de log, os testes passam uma lista.
            on_progress: callable(dict) chamado a cada leitura de um movimento,
                com posicao, status e etapa. Quem desenha decide como.

        `log`, `on_progress` e `drive` sao atributos publicos: a janela os
        troca ao conectar e a cada operacao.
        """
        self.drive = drive
        self.config = config
        self.log = log or (lambda msg: None)
        self.on_progress = on_progress or (lambda dados: None)

        # Estado de runtime -- daqui para baixo e do EIXO, nao da configuracao
        self.armado = False
        # Quando o enable foi confirmado. Uma leitura de "desabilitado" feita
        # ANTES disso e velha e nao pode desmarcar o eixo -- ver ui/status.py.
        self.armado_em = 0.0
        self.zero_valido = False
        self.sentido_mov = None
        self._cancelado = False
        self._falhas_leitura = 0

    def __repr__(self):
        return "EixoMovimento({}, {!r})".format(
            self.config.slave, self.config.apelido)

    # --- primitivas de comunicacao -------------------------------------------
    #
    # O Drive levanta DriveNaoConfirmou; a logica aqui testa `if not
    # escreveu`. Estes wrappers fazem a ponte e ainda aproveitam a validacao
    # de slave e CRC que Barramento.transact ja faz.

    def _escrever(self, reg, valor):
        """FC06. True se o drive confirmou; False e logado, nunca levanta."""
        if self.drive is None:
            return False
        try:
            self.drive.escrever(reg, valor)
            return True
        except DriveNaoConfirmou as erro:
            self.log("[ERR] {}".format(erro))
            return False

    def _escrever_retry(self, reg, valor, tentativas=3):
        """FC06 com retentativa -- para os comandos que nao podem falhar."""
        for _ in range(max(1, tentativas)):
            if self._escrever(reg, valor):
                return True
            self._dormir(0.05)
        return False

    def _escrever_multi(self, reg, valores):
        """FC16 -- registradores consecutivos num quadro so."""
        if self.drive is None:
            return False
        try:
            self.drive.escrever_multiplos(reg, valores)
            return True
        except DriveNaoConfirmou as erro:
            self.log("[ERR] {}".format(erro))
            return False

    def _ler(self, reg, count=1):
        """FC03. Devolve a lista de valores, ou None se o drive nao respondeu."""
        if self.drive is None:
            return None
        try:
            return self.drive.ler(reg, count)
        except DriveNaoConfirmou:
            return None

    def _dormir(self, segundos):
        """Ponto unico de espera, para os testes poderem acelerar o tempo."""
        time.sleep(segundos)

    def _agora(self):
        """Ponto unico de leitura do relogio, pela mesma razao que `_dormir`.

        Todo prazo deste arquivo passa por aqui, entao um teste troca os dois
        por um relogio virtual e um laco de 60 s roda em milissegundos.
        """
        return time.time()

    # --- cancelamento --------------------------------------------------------

    def cancelar(self):
        """Pede que a operacao em curso termine na proxima verificacao.

        Nao para o eixo por si: quem para e o laco que observa a bandeira, e
        ele chama parada_segura. Chamar isto com o eixo parado nao faz nada.
        """
        self._cancelado = True

    def _reiniciar_cancelamento(self):
        """Limpa a bandeira no inicio de cada operacao."""
        self._cancelado = False

    @property
    def cancelado(self):
        """True quando `cancelar` foi chamado e a operacao ainda nao terminou."""
        return self._cancelado

    # --- leituras ------------------------------------------------------------

    def ler_posicao(self):
        """Contador de pulsos (39/40), com sinal. None se o drive nao respondeu."""
        vals = self._ler(REG_PULSOS_L, 2)
        return None if vals is None else de_palavras_32(vals[0], vals[1])

    def ler_posicao_espera(self, segundos=None):
        """Le a posicao insistindo enquanto o drive estiver mudo.

        Com a desistencia na primeira leitura sem resposta, um movimento
        pedido logo apos gravar parametros morreria com "posicao nao pode ser
        lida" embora o barramento estivesse intacto.
        """
        limite = self._agora() + (self.SILENCIO if segundos is None else segundos)
        while self._agora() < limite:
            if self._cancelado:
                return None
            pos = self.ler_posicao()
            if pos is not None:
                return pos
            self._dormir(self.POLL)
        return None

    def status(self):
        """Registrador de status (75) cru, ou None."""
        vals = self._ler(REG_STATUS, 1)
        return None if vals is None else vals[0]

    def estado(self):
        """Status (75), alarme (115) e posicao (39/40), ou None.

        Sao tres quadros: os registradores nao sao vizinhos, e ler a faixa
        inteira de 39 a 115 passaria por enderecos que o manual nao lista. Os
        tres saem em sequencia, sem pausa entre eles alem da do barramento.

        Devolve (status, alarme, posicao).
        """
        st = self._ler(REG_STATUS, 1)
        if st is None:
            return None
        alm = self._ler(REG_ALARME, 1)
        if alm is None:
            return None
        pos = self._ler(REG_PULSOS_L, 2)
        if pos is None:
            return None
        return st[0], alm[0], de_palavras_32(pos[0], pos[1])

    def _bit_sensor(self):
        """O bit de 75 em que aparece o sensor de origem deste eixo."""
        return (ST_LIMITE_POS if self.config.home_entrada == ENTRADA_LIM_POS
                else ST_LIMITE_NEG)

    def ler_sensor(self):
        """Estado do sensor de origem: True/False, ou None se falhar."""
        st = self.status()
        return None if st is None else bool(st & self._bit_sensor())

    def ler_entradas(self):
        """Os dois sinais de limite como (limite_pos, limite_neg), ou None."""
        st = self.status()
        if st is None:
            return None
        return bool(st & ST_LIMITE_POS), bool(st & ST_LIMITE_NEG)

    # --- armar e desarmar ----------------------------------------------------

    def armar(self):
        """Enable (6 = 1). Atualiza `armado` so se o drive confirmar."""
        if self._escrever(REG_ENABLE, 1):
            self.armado = True
            self.armado_em = self._agora()
            self.log("[MOTOR] {} habilitado".format(self.config.apelido))
            return Resultado(True, detalhe="habilitado")
        return Resultado(False, CAUSA_DRIVE_MUDO, "o drive nao confirmou o enable")

    def desarmar(self):
        """Desabilita o motor (6 = 0): eixo livre e parando de esquentar.

        ATENCAO: num eixo vertical isto DERRUBA A CARGA.
        """
        if self._escrever(REG_ENABLE, 0):
            self.armado = False
            self.sentido_mov = None
            self.log("[MOTOR] {} desabilitado".format(self.config.apelido))
            return Resultado(True, detalhe="desabilitado")
        return Resultado(False, CAUSA_DRIVE_MUDO,
                         "o drive nao confirmou a desabilitacao")

    def limpar_alarme(self):
        """Limpa a falha (93 = 1)."""
        if self._escrever(REG_LIMPA_FALHA, 1):
            return Resultado(True, detalhe="falha limpa")
        return Resultado(False, CAUSA_DRIVE_MUDO, "o drive nao confirmou")

    # --- parada --------------------------------------------------------------

    def parada_segura(self, motivo):
        """Para o eixo da forma mais confiavel disponivel, escalonando.

        Desaceleracao (70 = 0) -> parada imediata (70 = 5) -> desabilitar o
        motor (6 = 0), que corta o torque. Devolve True se alguma das duas
        paradas foi confirmada.

        O ULTIMO degrau derruba a carga num eixo vertical. Por isso ele e
        condicionado a `config.soltar_em_emergencia`: com ele em False, a
        parada tem um recurso menos e o eixo fica com torque de retencao.

        Isto NAO substitui parada de emergencia, que e hardware: se o processo
        morrer ou o cabo cair, nada aqui roda e o drive segue o ultimo comando
        continuo que recebeu.
        """
        self.log("[STOP] {} -> parando o eixo {}".format(
            motivo, self.config.apelido))
        self.sentido_mov = None
        if self._escrever_retry(REG_COMANDO, CMD_DESACELERAR):
            return True
        self.log("[STOP] sem confirmacao -> parada imediata (70 = 5)")
        if self._escrever_retry(REG_COMANDO, CMD_PARADA_IMEDIATA):
            return True
        if not self.config.soltar_em_emergencia:
            self.log("[STOP] sem confirmacao, e este eixo NAO desabilita o motor "
                     "em emergencia (soltar_em_emergencia desligado). O eixo "
                     "pode continuar em movimento -- use a parada de "
                     "emergencia em hardware.")
            return False
        self.log("[STOP] sem confirmacao -> desabilitando o motor (derruba a carga)")
        if self._escrever_retry(REG_ENABLE, 0):
            self.armado = False
        return False

    # --- perfil e comandos ---------------------------------------------------

    def _vel(self, pps):
        """Velocidade limitada a 1~VEL_MAX_PPS pulsos/s."""
        return max(1, min(VEL_MAX_PPS, abs(int(pps))))

    def _carregar_perfil(self, pps, curso=0):
        """Desaceleracao, velocidade, aceleracao e curso num FC16 so (62~69).

        A rampa e a do cadastro do eixo e vale para os dois lados.
        """
        return self._escrever_multi(
            REG_DESACEL_L, perfil_movimento(pps, self.config.rampa_ms, curso))

    def _mover_continuo(self, pps, sentido):
        """Movimento continuo (70 = 3/4), SEM conferir limites.

        Usado pelo jog, depois da conferencia, e pelo homing -- la o zero
        ainda nao existe, entao nao ha faixa que faca sentido conferir.
        """
        self.sentido_mov = sentido
        if not self._carregar_perfil(self._vel(pps)):
            return False
        cmd = CMD_CONTINUO_FRENTE if sentido == FRENTE else CMD_CONTINUO_TRAS
        return self._escrever_retry(REG_COMANDO, cmd, tentativas=2)

    # --- jog continuo --------------------------------------------------------

    def jog_iniciar(self, pps=None, sentido=None):
        """Poe o eixo em movimento continuo no sentido pedido.

        Nao vigia nada: quem acompanha limites e comunicacao e
        `vigiar_movimento`, chamado pelo dono do eixo.

        Levanta MovimentoRecusado, sem escrever nada, com o motor desabilitado
        ou o eixo ja no limite daquele sentido.
        """
        pps = self.config.jog_velocidade if pps is None else pps
        sentido = self.config.jog_sentido if sentido is None else sentido

        bloqueio = self.bloqueio_de_partida(sentido)
        if bloqueio:
            raise MovimentoRecusado(bloqueio[0], bloqueio[1])

        self._reiniciar_cancelamento()
        self._falhas_leitura = 0
        pps = self._vel(pps)
        if not self._mover_continuo(pps, sentido):
            self.sentido_mov = None
            return Resultado(False, CAUSA_DRIVE_MUDO,
                             "o drive nao confirmou o inicio do JOG")
        self.log("[JOG] {} {} p/s no eixo {}".format(
            sentido, pps, self.config.apelido))
        return Resultado(True, detalhe="jog {} {} p/s".format(sentido, pps))

    def jog_parar(self):
        """Desacelera ate parar (70 = 0), com retentativa."""
        self.sentido_mov = None
        if self._escrever_retry(REG_COMANDO, CMD_DESACELERAR):
            return Resultado(True, detalhe="desacelerando")
        return Resultado(False, CAUSA_DRIVE_MUDO,
                         "comando de parada sem resposta")

    def vigiar_movimento(self):
        """Um ciclo de vigilancia do JOG: limites, falha e comunicacao.

        Devolve None quando esta tudo bem, ou um Resultado de falha quando o
        eixo precisa parar -- e nesse caso a parada JA foi comandada.

        Junta o watchdog (2 leituras sem resposta param o eixo, porque o
        comando continuo e retido pelo drive e nao depende de novas mensagens)
        com a vigilancia de curso (parada por software na borda da faixa, e e
        por isso que a antecipacao existe).

        Feito para ser chamado em laco pelo dono do eixo. Nao tem laco proprio
        de proposito: quem chama decide o ritmo.
        """
        est = self.estado()
        if est is None:
            self._falhas_leitura += 1
            self.log("[WD] drive sem resposta ({}/{})".format(
                self._falhas_leitura, self.WD_FALHAS_MAX))
            if self._falhas_leitura >= self.WD_FALHAS_MAX:
                self.parada_segura("Comunicacao perdida durante o movimento")
                return Resultado(False, CAUSA_DRIVE_MUDO,
                                 "comunicacao perdida durante o movimento")
            return None
        self._falhas_leitura = 0

        st, alm, pos = est
        self.on_progress({"etapa": "jog", "pos": pos, "status": st})

        if em_falha(st, alm):
            self.parada_segura("Falha no drive durante o movimento")
            return Resultado(False, CAUSA_ALARME, motivo_falha(st, alm),
                             posicao=pos)

        motivo = self.limite_atingido(pos, self.sentido_mov)
        if motivo:
            self.log("[CURSO] {} -> parando".format(motivo))
            self.parada_segura(motivo)
            return Resultado(False, CAUSA_LIMITE, motivo, posicao=pos)
        return None

    # --- limites -------------------------------------------------------------

    @property
    def faixa(self):
        """A faixa deste eixo em pulsos, como (negativo, positivo)."""
        return limites.faixa(self.config.limite_neg, self.config.limite_pos)

    def limites_valendo(self):
        """True quando os limites podem realmente valer.

        Exige as tres coisas juntas: limites ativos na configuracao, zero
        estabelecido, e faixa nao vazia. Sem o zero os numeros nao tem
        referencia; sem faixa nao ha o que proteger.
        """
        neg, pos = self.faixa
        return bool(self.config.limites_ativos and self.zero_valido
                    and not limites.faixa_vazia(neg, pos))

    def limite_atingido(self, pos, sentido):
        """Descreve o limite atingido no sentido em curso, ou None.

        Devolve None quando os limites nao estao valendo -- nao ha o que vigiar.
        """
        if not self.limites_valendo() or not sentido:
            return None
        neg, pmax = self.faixa
        return limites.limite_atingido(pos, sentido, neg, pmax,
                                       self.config.antecipacao,
                                       self.config.sentido_pos)

    def bloqueio_de_partida(self, sentido):
        """Motivo para nao deixar o eixo partir neste sentido, ou None.

        Devolve (causa, mensagem). O limite e conferido ANTES de partir porque
        parar depois de arrancar custa os pulsos da desaceleracao -- no
        extremo, isso e batida.
        """
        if not self.armado:
            return (CAUSA_MOTOR_OFF,
                    "o motor do eixo {} esta desabilitado: habilite antes de "
                    "mover".format(self.config.apelido))
        if not self.config.limites_ativos:
            return None
        neg, pmax = self.faixa
        if limites.faixa_vazia(neg, pmax):
            return None
        if not self.zero_valido:
            if not self.config.sensor_tem_origem:
                return (CAUSA_SEM_SENSOR,
                        "eixo sem sensor de origem: nao ha como estabelecer o "
                        "zero, entao os limites por software nao tem "
                        "referencia. Desligue os limites ou corrija o modelo "
                        "do sensor")
            return (CAUSA_ZERO_INVALIDO,
                    "os limites estao ativos mas o zero ainda nao foi "
                    "estabelecido: faca o homing ou desligue os limites")
        pos = self.ler_posicao()
        if pos is None:
            return (CAUSA_DRIVE_MUDO,
                    "nao foi possivel ler a posicao para conferir os limites")
        motivo = limites.limite_atingido(pos, sentido, neg, pmax,
                                         self.config.antecipacao,
                                         self.config.sentido_pos)
        return (CAUSA_LIMITE, motivo) if motivo else None

    # --- movimento de comprimento fixo ---------------------------------------

    def _comando_fixo(self, passo):
        """Comando 1 ou 2 que faz o contador andar `passo` (com sinal).

        Positivo = o sentido que SOMA pulsos neste eixo (`sentido_pos`). Nao e
        fixo em "frente" porque a direcao do motor e invertivel no drive
        (registrador 51) e a relacao entre comando e contagem e medida na
        bancada pelo "Detectar sentido +".
        """
        sentido = (self.config.sentido_pos if passo > 0
                   else oposto(self.config.sentido_pos))
        return CMD_FRENTE if sentido == FRENTE else CMD_TRAS

    def armar_movimento(self, passo, pps):
        """Carrega o perfil e dispara o movimento relativo de `passo` pulsos.

        Devolve (ok, mensagem). Garante o modo incremental (72 = 0): no
        absoluto o curso seria lido como destino.
        """
        pps = self._vel(pps)
        ok = (self._escrever(REG_MODO_POSICAO, 0)
              and self._carregar_perfil(pps, curso=abs(int(passo))))
        if not ok:
            return False, "drive nao aceitou os parametros do movimento"
        if not self._escrever_retry(REG_COMANDO, self._comando_fixo(passo),
                                    tentativas=2):
            return False, "drive nao confirmou o inicio do movimento"
        return True, "ok"

    def mover_pulsos(self, passo, pps):
        """Anda exatamente `passo` pulsos em movimento de comprimento fixo.

        Devolve um Resultado com a posicao final. E o mesmo caminho para o jog
        por pulsos e para o posicionamento.

        O fim do movimento exige o eixo PARADO (mesma posicao, dentro da folga,
        em duas leituras seguidas) e mais uma de duas coisas: o bit 7 de 75
        desligado ("envio de pulsos concluido") ou a posicao no destino. O bit
        sozinho nao basta porque o manual da 1 como valor padrao dele, e a
        posicao sozinha nao basta porque um eixo travado no meio do caminho
        tambem fica parado.
        """
        p0 = self.ler_posicao_espera()
        if p0 is None:
            return Resultado(False, CAUSA_DRIVE_MUDO,
                             "posicao nao pode ser lida")
        if self._cancelado:
            return Resultado(False, CAUSA_CANCELADO, "interrompido", posicao=p0)

        ok, msg = self.armar_movimento(passo, pps)
        if not ok:
            self.parada_segura(msg.capitalize())
            return Resultado(False, CAUSA_DRIVE_MUDO, msg, posicao=p0)

        destino = p0 + passo
        prazo = self._agora() + self.PASSO_TIMEOUT
        silencio = None
        estavel = 0
        anterior = None
        pos = p0
        partiu = abs(passo) <= self.PASSO_ESTAVEL   # passo menor que a folga
        rearmado = False
        t_gatilho = self._agora()
        self._dormir(0.15)

        while not self._cancelado:
            # O prazo e conferido no topo: com o teste no fim do laco, um drive
            # que respondesse errado sempre cairia no `continue` e o timeout
            # nunca seria avaliado.
            if self._agora() > prazo:
                self.parada_segura("Timeout no movimento")
                return Resultado(
                    False, CAUSA_TIMEOUT,
                    "o movimento nao terminou em {:.0f} s".format(
                        self.PASSO_TIMEOUT), posicao=pos)

            est = self.estado()
            if est is None:
                # Silencio e medido em TEMPO, nao em numero de leituras
                silencio = silencio or self._agora()
                if self._agora() - silencio > self.SILENCIO:
                    self.parada_segura("Comunicacao perdida durante o movimento")
                    return Resultado(False, CAUSA_DRIVE_MUDO,
                                     "comunicacao perdida durante o movimento",
                                     posicao=pos)
                self._dormir(self.POLL)
                continue
            silencio = None

            st, alm, pos = est
            if em_falha(st, alm):
                self.parada_segura("Falha no drive durante o movimento")
                return Resultado(False, CAUSA_ALARME, motivo_falha(st, alm),
                                 posicao=pos)
            self.on_progress({"etapa": "posicionando", "pos": pos,
                              "status": st, "destino": destino})

            movendo = bool(st & ST_EM_MOVIMENTO)
            if not partiu and (movendo or abs(pos - p0) > self.PASSO_ESTAVEL):
                partiu = True

            # Drive parado no lugar depois do comando: repete UMA vez e, se
            # continuar imovel, desiste com o motivo em vez de deixar o
            # chamador preso ate o timeout.
            if not partiu and self._agora() - t_gatilho > self.PASSO_PARTIDA:
                if rearmado:
                    self.parada_segura("Drive nao iniciou o movimento")
                    return Resultado(
                        False, CAUSA_NAO_PARTIU,
                        "o drive nao saiu do lugar depois do comando de "
                        "{:+d} pulsos".format(passo), posicao=pos)
                self.log("[CURSO] drive imovel {:.1f} s depois do comando -> "
                         "repetindo".format(self.PASSO_PARTIDA))
                ok, msg = self.armar_movimento(passo, pps)
                if not ok:
                    self.parada_segura(msg.capitalize())
                    return Resultado(False, CAUSA_DRIVE_MUDO, msg, posicao=pos)
                rearmado = True
                t_gatilho = self._agora()
                anterior = None
                estavel = 0
                self._dormir(0.15)
                continue

            parado = (anterior is not None
                      and abs(pos - anterior) <= self.PASSO_ESTAVEL)
            chegou = abs(pos - destino) <= self.PASSO_ESTAVEL
            if partiu and parado and (not movendo or chegou):
                estavel += 1
                if estavel >= 2:
                    return Resultado(True, detalhe="ok", posicao=pos)
            else:
                estavel = 0
            anterior = pos
            self._dormir(self.POLL)

        self.parada_segura("Movimento cancelado")
        return Resultado(False, CAUSA_CANCELADO, "interrompido", posicao=pos)

    def passo(self, sinal=None, pulsos=None, pps=None):
        """Anda um numero exato de pulsos para + ou para -.

        Args:
            sinal: +1 ou -1. Usado com `pulsos` do cadastro.
            pulsos: tamanho do passo; o padrao vem da configuracao.
            pps: velocidade; o padrao vem da configuracao.
        """
        if not self.armado:
            raise MovimentoRecusado(
                CAUSA_MOTOR_OFF,
                "o motor do eixo {} esta desabilitado: habilite antes de mover"
                .format(self.config.apelido))

        tamanho = abs(self.config.passo_pulsos if pulsos is None else pulsos)
        passo = int((1 if sinal is None else sinal) * tamanho)
        if passo == 0:
            return Resultado(True, detalhe="passo zero, nada a fazer")
        pps = self.config.passo_vel if pps is None else pps

        self._reiniciar_cancelamento()
        p0 = self.ler_posicao_espera()
        if p0 is None:
            return Resultado(False, CAUSA_DRIVE_MUDO,
                             "posicao nao pode ser lida")

        # Com limites valendo, o destino e conferido ANTES de sair: o movimento
        # de comprimento fixo vai ate o fim sem consultar nada no caminho.
        if self.limites_valendo():
            neg, pmax = self.faixa
            motivo = limites.passo_permitido(p0, passo, neg, pmax)
            if motivo:
                return Resultado(False, CAUSA_FORA_DA_FAIXA, motivo, posicao=p0)

        res = self.mover_pulsos(passo, pps)
        if not res.ok:
            return res

        andou = res.posicao - p0
        # A diferenca entre o pedido e o andado e o que denuncia perda de passo
        dentro = abs(andou - passo) <= max(2, abs(passo) // 100)
        detalhe = "passo {:+d} -> andou {:+d} pulsos ({} para {})".format(
            passo, andou, p0, res.posicao)
        self.log("[CURSO] {}".format(detalhe))
        if dentro:
            return Resultado(True, detalhe=detalhe, posicao=res.posicao)
        return Resultado(False, CAUSA_NAO_PARTIU, detalhe, posicao=res.posicao)

    def ir_para(self, alvo):
        """Leva o eixo ao alvo absoluto, em pulsos contados do zero.

        O deslocamento vai como numero de pulsos para o drive, que desacelera
        e para sozinho; o que sobra de erro e corrigido em ate duas tentativas
        e conferido contra a tolerancia.

        Levanta MovimentoRecusado sem escrever nada quando o alvo esta fora da
        faixa ou quando os limites estao ativos sem zero estabelecido.
        """
        alvo = int(alvo)
        if not self.armado:
            raise MovimentoRecusado(
                CAUSA_MOTOR_OFF,
                "o motor do eixo {} esta desabilitado: habilite antes de mover"
                .format(self.config.apelido))

        neg, pmax = self.faixa
        if not limites.faixa_vazia(neg, pmax) and not (neg <= alvo <= pmax):
            raise MovimentoRecusado(
                CAUSA_FORA_DA_FAIXA,
                "o alvo {} pulsos esta fora da faixa permitida ({} a {})"
                .format(alvo, neg, pmax))

        if self.config.limites_ativos and not self.zero_valido:
            if not self.config.sensor_tem_origem:
                raise MovimentoRecusado(
                    CAUSA_SEM_SENSOR,
                    "eixo sem sensor: nao ha zero a estabelecer, e a contagem "
                    "do drive nao corresponde a nenhuma faixa conhecida. "
                    "Desligue os limites ou corrija o modelo do sensor")
            raise MovimentoRecusado(
                CAUSA_ZERO_INVALIDO,
                "faca o homing antes de posicionar por pulsos: sem o zero no "
                "sensor, a contagem do drive nao corresponde a faixa "
                "configurada")

        self._reiniciar_cancelamento()
        tol = max(1, self.config.tolerancia)
        janela = self.config.janela_lenta
        v_rap = self.config.vel_rapida
        v_len = self.config.vel_lenta

        pos = None
        for tentativa in range(3):
            pos = self.ler_posicao_espera()
            if pos is None:
                return Resultado(False, CAUSA_DRIVE_MUDO,
                                 "posicao nao pode ser lida")
            self.on_progress({"etapa": "indo", "pos": pos, "alvo": alvo})
            erro = alvo - pos
            if abs(erro) <= tol:
                break
            # Longe do alvo usa a velocidade rapida; a correcao final vai na
            # lenta, que e onde a perda de passo apareceria
            pps = v_rap if abs(erro) > janela and tentativa == 0 else v_len
            self.log("[CURSO] indo para {}: faltam {:+d} pulsos a {} p/s"
                     .format(alvo, erro, pps))
            res = self.mover_pulsos(erro, pps)
            if not res.ok:
                return res
            pos = res.posicao

        erro = alvo - pos
        # O resultado e julgado pela posicao FINAL, nao pela ultima leitura
        # durante o movimento
        detalhe = "posicao {} (alvo {}, erro {:+d}, tolerancia {})".format(
            pos, alvo, erro, tol)
        self.log("[CURSO] {}".format(detalhe))
        if abs(erro) <= tol:
            return Resultado(True, detalhe=detalhe, posicao=pos)
        return Resultado(False, CAUSA_TIMEOUT, detalhe, posicao=pos)

    def detectar_sentido(self, pps, segundos=1.0, tolerancia=None):
        """Gira em FRENTE por um instante e ve se a contagem sobe ou desce.

        Devolve um Resultado com `valor` = o sentido que SOMA pulsos. Sem isso,
        um limite guardado do lado errado faria a vigilancia parar o eixo no
        extremo oposto ao esperado -- e o passo andaria ao contrario.
        """
        if not self.armado:
            raise MovimentoRecusado(
                CAUSA_MOTOR_OFF,
                "habilite o motor do eixo {} antes de detectar o sentido"
                .format(self.config.apelido))
        self._reiniciar_cancelamento()
        tolerancia = self.config.tolerancia if tolerancia is None else tolerancia

        p0 = self.ler_posicao_espera()
        if p0 is None:
            return Resultado(False, CAUSA_DRIVE_MUDO, "posicao nao pode ser lida")
        if not self._mover_continuo(pps, FRENTE):
            self.parada_segura("Drive nao aceitou o movimento")
            return Resultado(False, CAUSA_DRIVE_MUDO,
                             "drive nao aceitou o movimento")
        self._dormir(segundos)
        self.jog_parar()
        self._dormir(0.5)
        p1 = self.ler_posicao_espera()
        if p1 is None:
            return Resultado(False, CAUSA_DRIVE_MUDO,
                             "posicao nao pode ser lida apos o movimento")
        delta = p1 - p0
        if abs(delta) <= tolerancia:
            return Resultado(False, CAUSA_NAO_PARTIU,
                             "o eixo quase nao andou ({} pulsos) - suba a "
                             "velocidade e repita".format(delta), posicao=p1)
        sentido = FRENTE if delta > 0 else oposto(FRENTE)
        return Resultado(True, detalhe="sentido de + = {} (delta {} pulsos)"
                         .format(sentido, delta), posicao=p1, valor=sentido)

    # --- homing --------------------------------------------------------------

    def _exigir_homing_possivel(self):
        """Recusa o homing sem sensor ou com o motor desabilitado."""
        if not self.config.sensor_tem_origem:
            raise MovimentoRecusado(
                CAUSA_SEM_SENSOR,
                "eixo {} esta marcado como SEM SENSOR de origem: nao ha zero a "
                "estabelecer".format(self.config.apelido))
        if not self.armado:
            raise MovimentoRecusado(
                CAUSA_MOTOR_OFF,
                "habilite o motor do eixo {} antes do homing"
                .format(self.config.apelido))

    def _sensor_e_falha(self):
        """Sensor de origem, status e alarme -- ou None se o drive calou.

        O sensor sai do mesmo quadro do status (75): ler so o sensor deixaria
        o homing cego para sobrecorrente e sobretensao. O alarme (115) vem num
        segundo quadro porque e o unico que traz rotor travado.

        Devolve (sensor, status, alarme).
        """
        st = self._ler(REG_STATUS, 1)
        if st is None:
            return None
        alm = self._ler(REG_ALARME, 1)
        if alm is None:
            return None
        return bool(st[0] & self._bit_sensor()), st[0], alm[0]

    def _esperar_sensor(self, alvo, timeout, etapa):
        """Espera o sensor chegar ao estado `alvo` enquanto o eixo se move.

        Para o eixo e devolve um Resultado de falha em timeout, falha do
        drive, perda de comunicacao ou cancelamento. Devolve None quando deu
        certo -- o eixo ja esta parando.
        """
        limite = self._agora() + timeout
        falhas = 0
        while not self._cancelado:
            leitura = self._sensor_e_falha()
            if leitura is None:
                falhas += 1
                if falhas >= self.WD_FALHAS_MAX:
                    self.parada_segura(
                        "Comunicacao perdida durante {}".format(etapa))
                    return Resultado(False, CAUSA_DRIVE_MUDO,
                                     "comunicacao perdida em {}".format(etapa))
            else:
                falhas = 0
                sensor, st, alm = leitura
                # A falha vem ANTES do sensor: com o drive em falha, o eixo ja
                # nao esta andando e esperar a borda seria esperar o timeout.
                if em_falha(st, alm):
                    self.parada_segura("Falha no drive durante {}".format(etapa))
                    return Resultado(False, CAUSA_ALARME, motivo_falha(st, alm))
                self.on_progress({"etapa": etapa, "sensor": sensor, "status": st})
                if sensor == alvo:
                    self.jog_parar()
                    return None
            if self._agora() > limite:
                self.jog_parar()
                return Resultado(
                    False, CAUSA_TIMEOUT,
                    "timeout em {} ({:.0f} s)".format(etapa, timeout))
            self._dormir(self.HOME_POLL)
        self.parada_segura("Homing cancelado")
        return Resultado(False, CAUSA_CANCELADO, "interrompido em {}".format(etapa))

    def _gravar_zero(self, origem):
        """Zera o contador (40 = 1) e confere se a posicao de fato zerou.

        `zero_valido` so vira True com a confirmacao por leitura: um homing
        cujo zero nao pegou deixaria os limites apontando para um ponto
        qualquer do eixo.
        """
        self._escrever_retry(REG_PULSOS_H, 1)
        self._dormir(0.2)
        pos = self.ler_posicao()
        self.log("[HOME] verificacao: posicao = {}".format(
            "?" if pos is None else pos))
        if pos is not None and abs(pos) <= 10:
            self.zero_valido = True
            self.sentido_mov = None
            detalhe = "zero {} (posicao = {})".format(origem, pos)
            self.log("[HOME] concluido - {}".format(detalhe))
            return Resultado(True, detalhe=detalhe, posicao=pos)
        return self._homing_falhou(Resultado(
            False, CAUSA_RECUSADO,
            "o eixo parou no sensor, mas o contador nao zerou (posicao = {})"
            .format("?" if pos is None else pos), posicao=pos))

    def homing_software(self):
        """Homing conduzido pelo programa, para sensor de garfo.

        Cinco passos, com o came entrando e saindo da fenda:

          0. Se o came ja estiver na fenda, recua ate liberar
          1. Busca na velocidade de aproximacao ate o came entrar na fenda
          2. Recua no rastejo ate sair da fenda
          3. Reaproxima no rastejo e para na borda de entrada
          4. Zera o contador (40 = 1) e confere

        O sensor e lido pelos bits de limite do status (75): no STR6 ele so
        pode ocupar IN1 (limite -) ou IN2 (limite +). Como e entrada de
        limite, o proprio drive pode parar o eixo ao ver o sensor -- o que nao
        atrapalha nenhum passo daqui, porque todos param na borda de qualquer
        jeito.

        A parada e por software, entao a precisao depende do periodo de leitura
        e da velocidade de rastejo -- use rastejo baixo.
        """
        self._exigir_homing_possivel()
        self._reiniciar_cancelamento()
        self.zero_valido = False

        sentido = self.config.home_sentido
        v_apr = self._vel(self.config.home_v_apr)
        v_ras = self._vel(min(self.config.home_v_ras, v_apr))

        self.log("[HOME-SW] eixo {}: busca no {}, {} a {} p/s, rastejo {} p/s"
                 .format(self.config.apelido, self.config.home_entrada,
                         sentido, v_apr, v_ras))

        estado = self.ler_sensor()
        if estado is None:
            return self._homing_falhou(
                Resultado(False, CAUSA_DRIVE_MUDO, "sensor nao pode ser lido"))

        etapas = []
        if estado:
            self.log("[HOME-SW] came ja na fenda; recuando para liberar")
            etapas.append((v_ras, oposto(sentido), False, 30.0,
                           "a saida da fenda"))
        etapas += [
            (v_apr, sentido, True, self.HOME_TIMEOUT, "a busca do sensor"),
            (v_ras, oposto(sentido), False, 30.0, "a saida da fenda"),
            (v_ras, sentido, True, 30.0, "a reaproximacao"),
        ]

        for pps, para, alvo, prazo, etapa in etapas:
            # O retorno do comando e conferido: com o movimento recusado o eixo
            # fica parado e _esperar_sensor gastaria o prazo inteiro esperando
            # uma transicao que nao pode acontecer, relatando TIMEOUT em vez
            # da recusa que de fato ocorreu.
            if not self._mover_continuo(pps, para):
                self.parada_segura("Drive nao aceitou o comando de movimento")
                return self._homing_falhou(Resultado(
                    False, CAUSA_DRIVE_MUDO,
                    "drive nao aceitou o comando de movimento"))
            falha = self._esperar_sensor(alvo, prazo, etapa)
            if falha is not None:
                return self._homing_falhou(falha)
            self._dormir(0.4)

        self.log("[HOME-SW] passo 4: zerando o contador nesta posicao")
        return self._gravar_zero("no sensor")

    def homing_nativo(self):
        """Retorno a zero do proprio drive (71 = 1 ou 2), com acompanhamento.

        Pelo manual (p. 18) o drive vai ate o sinal de limite na velocidade e
        aceleracao de 62~67, desacelera, e volta ate o sinal na velocidade do
        registrador 60. Depois disso o cliente zera o contador (40 = 1).

        O manual nao diz como o drive sinaliza o fim. Aqui o fim e o eixo
        imovel por HOME_PARADO segundos depois de ter andado (o dobro, se o
        bit 7 de 75 ainda disser "em movimento").
        """
        self._exigir_homing_possivel()
        self._reiniciar_cancelamento()
        self.zero_valido = False

        v_apr = self._vel(self.config.home_v_apr)
        v_ras = self._vel(min(self.config.home_v_ras, v_apr))
        modo = (HOME_LIMITE_POS if self.config.home_entrada == ENTRADA_LIM_POS
                else HOME_LIMITE_NEG)
        self.log("[HOME] eixo {}: retorno a zero do drive, 71 = {} ({}), "
                 "aproximacao {} p/s, retorno {} p/s".format(
                     self.config.apelido, modo, self.config.home_entrada,
                     v_apr, v_ras))

        if not (self._escrever(REG_VEL_HOME, min(v_ras, 0xFFFF))
                and self._carregar_perfil(v_apr)):
            return self._homing_falhou(Resultado(
                False, CAUSA_RECUSADO,
                "o drive recusou os parametros do retorno a zero"))
        if not self._escrever(REG_HOME, modo):
            return self._homing_falhou(Resultado(
                False, CAUSA_DRIVE_MUDO,
                "drive nao aceitou o comando de retorno a zero"))
        self.sentido_mov = self.config.home_sentido
        res = self._acompanhar_homing()
        if res is not None:
            return res
        return self._gravar_zero("do retorno a zero do drive")

    def _sair_do_homing(self, motivo):
        """Tira o drive do retorno a zero (71 = 0) e para o eixo."""
        self._escrever_retry(REG_HOME, HOME_SAIR)
        self.parada_segura(motivo)

    def _acompanhar_homing(self):
        """Acompanha o retorno a zero nativo. None quando concluiu.

        Mesmo criterio do watchdog do JOG: falha no drive ou duas leituras
        seguidas sem resposta interrompem o movimento.
        """
        inicio = self._agora()
        limite = inicio + self.HOME_TIMEOUT
        falhas = 0
        andou = False
        anterior = None
        parado_desde = None
        while not self._cancelado:
            self._dormir(self.POLL)
            est = self.estado()
            if est is None:
                falhas += 1
                self.log("[HOME] drive sem resposta ({}/{})".format(
                    falhas, self.WD_FALHAS_MAX))
                if falhas >= self.WD_FALHAS_MAX:
                    self._sair_do_homing("Comunicacao perdida durante o homing")
                    return self._homing_falhou(Resultado(
                        False, CAUSA_DRIVE_MUDO, "comunicacao perdida"))
                continue
            falhas = 0
            st, alm, pos = est
            if em_falha(st, alm):
                self._sair_do_homing("Falha no drive durante o homing")
                return self._homing_falhou(Resultado(
                    False, CAUSA_ALARME, motivo_falha(st, alm), posicao=pos))
            self.on_progress({"etapa": "homing", "pos": pos, "status": st})

            # O fim exige que o eixo TENHA ANDADO e depois ficado imovel por
            # HOME_PARADO -- nao basta uma leitura parada: o drive para no
            # limite e reverte, e essa pausa nao e o fim. Com o bit 7 ainda
            # dizendo "em movimento" a espera dobra, que e o que cobre o caso
            # de o bit ficar em 1 com o eixo parado (valor padrao 1 no manual).
            movendo = bool(st & ST_EM_MOVIMENTO)
            if anterior is not None and abs(pos - anterior) > self.PASSO_ESTAVEL:
                andou = True
                parado_desde = None
            elif parado_desde is None:
                parado_desde = self._agora()

            if andou:
                espera = self.HOME_PARADO * (2 if movendo else 1)
                if (parado_desde is not None
                        and self._agora() - parado_desde >= espera):
                    self.sentido_mov = None
                    self.log("[HOME] eixo parado no fim do retorno a zero "
                             "(status 0x{:04X}, posicao {})".format(st, pos))
                    return None
            elif self._agora() - inicio > self.HOME_PARTIDA:
                self._sair_do_homing("Drive nao iniciou o retorno a zero")
                return self._homing_falhou(Resultado(
                    False, CAUSA_NAO_PARTIU,
                    "o drive nao saiu do lugar depois do comando de retorno a "
                    "zero", posicao=pos))
            anterior = pos

            if self._agora() > limite:
                self._sair_do_homing("Timeout do homing ({:.0f} s)".format(
                    self.HOME_TIMEOUT))
                return self._homing_falhou(Resultado(
                    False, CAUSA_TIMEOUT, "referencia nao encontrada",
                    posicao=pos))
        self._sair_do_homing("Homing cancelado")
        return self._homing_falhou(Resultado(
            False, CAUSA_CANCELADO, "interrompido pelo operador"))

    def _homing_falhou(self, resultado):
        """Registra o desfecho ruim de um homing e invalida o zero.

        Homing interrompido ou com falha deixa a contagem em ponto arbitrario:
        os limites de curso ficam INVALIDOS ate um homing concluir de novo.
        """
        self.zero_valido = False
        self.sentido_mov = None
        self.log("[HOME] {}: {}".format(resultado.causa, resultado.detalhe))
        return resultado
