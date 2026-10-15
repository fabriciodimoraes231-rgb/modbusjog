"""Um drive no barramento: endereco de slave + operacoes verificadas.

Toda escrita e conferida. Um drive que nao confirma aborta a rotina em vez de
deixa-la anunciar sucesso: um drive mudo pode estar energizado, em movimento,
ou simplesmente em outro endereco.
"""

import time

from . import config
from .protocolo import (
    BYTES_ECO_ESCRITA,
    build_read_regs,
    build_write_multi,
    build_write_single,
    bytes_resposta_leitura,
    de_palavras_32,
    descrever_excecao,
    palavras_32,
    parse_read_response,
)
from .registradores import (
    CMD_DESACELERAR,
    CMD_FRENTE,
    CMD_PARADA_IMEDIATA,
    CMD_TRAS,
    CORRENTE_MAX_MA,
    CORRENTE_MIN_MA,
    MALHAS,
    REG_ALARME,
    REG_AUTOAJUSTE,
    REG_COMANDO,
    REG_CORRENTE_OPER_PCT,
    REG_CORRENTE_PICO,
    REG_DESACEL_L,
    REG_ENABLE,
    REG_ENCODER_L,
    REG_ID,
    REG_KI,
    REG_KP,
    REG_LIMPA_FALHA,
    REG_MALHA,
    REG_MODO_POSICAO,
    REG_PULSOS_H,
    REG_PULSOS_L,
    REG_SALVAR,
    REG_STATUS,
    REG_TENSAO,
)


class DriveNaoConfirmou(Exception):
    """Uma escrita ou leitura nao foi confirmada pelo drive."""


# Pausa entre as consultas ao 90 em Drive.salvar_parametros, em segundos.
INTERVALO_SALVAR = 0.2


# Fases de Drive.aguardar_religamento
RELIGA_ESPERANDO = "esperando desligar"
RELIGA_DESLIGADO = "desligado"
RELIGA_RELIGADO = "religado"


def comparar_configuracao(esperado, lido):
    """Registradores em que `lido` difere de `esperado`: [(reg, esperado, lido)].

    Um registrador que falta em `lido` conta como divergente (lido = None).
    """
    return [(reg, valor, lido.get(reg)) for reg, valor in sorted(esperado.items())
            if lido.get(reg) != valor]


def aceleracao_da_rampa(vel_pps, rampa_ms):
    """Aceleracao em pulsos/s^2 que leva de 0 a `vel_pps` em `rampa_ms`.

    O STR6 recebe aceleracao, nao tempo de rampa (registradores 62~67). Pensar
    em tempo e o que se mede na bancada; a conversao fica aqui, num lugar so.
    """
    rampa_ms = max(1, int(rampa_ms))
    return max(1, int(abs(vel_pps) * 1000 // rampa_ms))


def perfil_movimento(vel_pps, rampa_ms=config.RAMPA_MS, curso=0):
    """As oito palavras de 62~69: desaceleracao, velocidade, aceleracao e curso.

    Na ordem dos registradores, prontas para um FC16 a partir de 62. A mesma
    rampa vale para acelerar e desacelerar. O curso e sem sinal -- o sentido
    vai no comando (70), nao no numero.
    """
    acel = aceleracao_da_rampa(vel_pps, rampa_ms)
    return (palavras_32(acel) + palavras_32(abs(int(vel_pps)))
            + palavras_32(acel) + palavras_32(abs(int(curso))))


class Drive:
    """Operacoes sobre um drive. Varios Drives compartilham um Barramento."""

    def __init__(self, barramento, slave_id, log=None):
        """Amarra um endereco de slave a um barramento compartilhado.

        Args:
            barramento: o Barramento aberto, o mesmo para todos os drives da
                linha -- RS-485 e half-duplex e nao admite duas requisicoes
                em voo.
            slave_id: endereco do drive (config.SLAVE_MIN~SLAVE_MAX).
            log: callable de um argumento (str). Quando existe, cada ESCRITA
                vai para ele com o quadro enviado e a resposta em hexadecimal.
                As leituras ficam de fora de proposito: o monitor le varias
                vezes por segundo e afogaria o log.

        Raises:
            ValueError: endereco fora da faixa. Barrar aqui e melhor do que
                descobrir na bancada que o quadro foi para um endereco que o
                drive nunca escuta.
        """
        if not config.SLAVE_MIN <= slave_id <= config.SLAVE_MAX:
            raise ValueError(
                "Endereco de slave fora da faixa ({}~{}): {}".format(
                    config.SLAVE_MIN, config.SLAVE_MAX, slave_id))
        self.barramento = barramento
        self.slave_id = slave_id
        self._log = log

    def __repr__(self):
        """Representacao curta, com o endereco -- e o que identifica o drive."""
        return "Drive({})".format(self.slave_id)

    # --- primitivas -----------------------------------------------------------

    def _falhou(self, acao, resp):
        """Monta a DriveNaoConfirmou de uma transacao malsucedida.

        Nao levanta: devolve a excecao para quem chamou fazer `raise`. O motivo
        distingue os tres desfechos que pedem diagnosticos diferentes -- excecao
        Modbus (o drive respondeu recusando), silencio (endereco, fiacao ou
        alimentacao) e resposta invalida (quadro curto ou colidido).
        """
        exc = descrever_excecao(resp)
        motivo = exc if exc else ("sem resposta" if resp is None
                                  else "resposta invalida: " + resp.hex(" ").upper())
        return DriveNaoConfirmou("Drive {}: {} -- {}".format(
            self.slave_id, acao, motivo))

    def _registrar(self, cmd, resp, ok):
        """Leva uma escrita para o log hexadecimal, se houver log."""
        if self._log is None:
            return
        resp_hex = resp.hex(" ").upper() if resp else "sem resposta"
        exc = descrever_excecao(resp)
        if exc:
            resp_hex += "   <- " + exc
        self._log("[{}]  {}  ->  {}".format("TX" if ok else "ERR",
                                            cmd.hex(" ").upper(), resp_hex))

    def escrever(self, reg, valor):
        """FC06. Levanta DriveNaoConfirmou se o drive nao confirmar."""
        cmd = build_write_single(self.slave_id, reg, valor)
        resp = self.barramento.transact(cmd, BYTES_ECO_ESCRITA)
        ok = (resp is not None and len(resp) >= BYTES_ECO_ESCRITA
              and not descrever_excecao(resp))
        self._registrar(cmd, resp, ok)
        if not ok:
            raise self._falhou("recusou reg {} = {}".format(reg, valor), resp)
        time.sleep(config.PAUSA_QUADRO)
        return True

    def escrever_multiplos(self, reg_start, valores):
        """FC16 -- registradores consecutivos num unico quadro."""
        valores = list(valores)
        cmd = build_write_multi(self.slave_id, reg_start, valores)
        resp = self.barramento.transact(cmd, BYTES_ECO_ESCRITA)
        ok = (resp is not None and len(resp) >= BYTES_ECO_ESCRITA
              and not descrever_excecao(resp))
        self._registrar(cmd, resp, ok)
        if not ok:
            raise self._falhou("recusou {} registradores a partir do {}".format(
                len(valores), reg_start), resp)
        time.sleep(config.PAUSA_QUADRO)
        return True

    def ler(self, reg, count=1):
        """FC03 -- devolve a lista de valores. Levanta DriveNaoConfirmou se falhar."""
        cmd = build_read_regs(self.slave_id, reg, count)
        resp = self.barramento.transact(cmd, bytes_resposta_leitura(count))
        vals = parse_read_response(resp, count) if resp else None
        if vals is None:
            raise self._falhou("nao respondeu a leitura do reg {}".format(reg), resp)
        time.sleep(config.PAUSA_QUADRO)
        return vals

    def responde(self):
        """True se o drive responde neste endereco. Nao levanta excecao.

        Le o registrador 31 (numero ID do equipamento). Use para varrer o
        barramento antes de movimentar: um ID mudo e DIP errado, cabo solto ou
        drive sem alimentacao.
        """
        try:
            return self.ler(REG_ID)[0] is not None
        except (DriveNaoConfirmou, IndexError):
            return False

    # --- leituras de conveniencia ---------------------------------------------

    def posicao(self):
        """Contador de pulsos em 32 bits com sinal (39 baixa + 40 alta)."""
        baixa, alta = self.ler(REG_PULSOS_L, 2)
        return de_palavras_32(baixa, alta)

    def encoder(self):
        """Realimentacao do encoder em 32 bits com sinal (41 baixa + 42 alta)."""
        baixa, alta = self.ler(REG_ENCODER_L, 2)
        return de_palavras_32(baixa, alta)

    def status(self):
        """Registrador de status (75) -- ver ST_* em registradores."""
        return self.ler(REG_STATUS)[0]

    def alarme(self):
        """Codigo de alarme (115): 0 = sem alarme."""
        return self.ler(REG_ALARME)[0]

    def tensao_v(self):
        """Tensao do barramento em volts (48, unidade 0,1 V)."""
        return self.ler(REG_TENSAO)[0] / 10.0

    # --- operacoes ------------------------------------------------------------

    def armar(self):
        """Enable (6 = 1). Ver a nota sobre o registrador 6 em registradores."""
        return self.escrever(REG_ENABLE, 1)

    def desarmar(self):
        """Desabilita o motor (6 = 0).

        Com o 7 no padrao de fabrica (0 = motor livre), o eixo fica solto e
        para de esquentar -- num eixo vertical, a carga desce.
        """
        return self.escrever(REG_ENABLE, 0)

    def limpar_falha(self):
        """Escreve 1 no 93; o drive limpa a falha e volta o registrador a 0."""
        return self.escrever(REG_LIMPA_FALHA, 1)

    def zerar_posicao(self):
        """Escreve 1 no 40, que zera o contador de pulsos (manual p. 14 e 18)."""
        return self.escrever(REG_PULSOS_H, 1)

    def parar(self):
        """Desacelera ate parar (70 = 0)."""
        return self.escrever(REG_COMANDO, CMD_DESACELERAR)

    def parar_imediato(self):
        """Parada imediata, sem rampa (70 = 5)."""
        return self.escrever(REG_COMANDO, CMD_PARADA_IMEDIATA)

    def carregar_perfil(self, vel_pps, rampa_ms=config.RAMPA_MS, curso=0):
        """Escreve desaceleracao, velocidade, aceleracao e curso num FC16 so."""
        return self.escrever_multiplos(
            REG_DESACEL_L, perfil_movimento(vel_pps, rampa_ms, curso))

    def mover_relativo(self, pulsos, vel_pps, rampa_ms=config.RAMPA_MS):
        """Movimento de comprimento fixo: positivo = frente (1), negativo = tras (2).

        Garante o modo incremental (72 = 0) antes: no absoluto o curso passaria
        a ser lido como destino.
        """
        self.escrever(REG_MODO_POSICAO, 0)
        self.carregar_perfil(vel_pps, rampa_ms, curso=abs(int(pulsos)))
        return self.escrever(REG_COMANDO, CMD_FRENTE if pulsos >= 0 else CMD_TRAS)

    def salvar_parametros(self, espera=config.ESPERA_SALVAR):
        """Escreve 1 no 90 e espera o drive informar que concluiu.

        A leitura do 90 devolve 0 com o salvamento incompleto e 1 concluido
        (manual p. 16): em vez de esperar um tempo fixo, a rotina pergunta.
        Silencio durante a gravacao e tolerado ate o prazo. Devolve True so
        com a confirmacao.

        O prazo e contado em CONSULTAS ao 90 (uma a cada
        `INTERVALO_SALVAR`, `espera` segundos ao todo num barramento livre),
        nao no relogio: num barramento disputado uma unica leitura pode levar
        mais que o prazo inteiro so esperando a vez, e a rotina desistiria sem
        ter perguntado. Ainda assim termina: uma consulta muda custa no maximo
        o timeout da porta.

        O manual nao diz se o 1 volta a 0 depois. Se o 90 ja estava em 1 antes
        do pedido e continua em 1 sem passar por 0 nem por silencio, o 1 lido
        pode ser o do salvamento anterior: devolve True (o drive aceitou o
        pedido), mas o log avisa. Nos dois casos, o que prova a gravacao e
        desligar e religar o drive -- ver `aguardar_religamento`.
        """
        try:
            antes = self.ler(REG_SALVAR)[0]
        except DriveNaoConfirmou:
            antes = None
        self.escrever(REG_SALVAR, 1)
        viu_ocupado = False          # 0 ou silencio depois do pedido
        for _ in range(max(1, int(espera / INTERVALO_SALVAR))):
            time.sleep(INTERVALO_SALVAR)
            try:
                valor = self.ler(REG_SALVAR)[0]
            except DriveNaoConfirmou:
                viu_ocupado = True
                continue
            if valor == 1:
                if antes == 1 and not viu_ocupado:
                    self._anotar(
                        "[SALVAR] Drive {}: o reg 90 ja estava em 1 antes do "
                        "pedido e nao passou por 0 -- a confirmacao nao separa "
                        "este salvamento do anterior. Prova so religando o "
                        "drive.".format(self.slave_id))
                return True
            viu_ocupado = True
        return False

    def _anotar(self, texto):
        """Leva uma observacao ao log, se houver log."""
        if self._log is not None:
            self._log(texto)

    def ler_configuracao(self):
        """Le os registradores de REGS_CONFIGURACAO: {registrador: valor}.

        0~3 vem num quadro so; 13, 15~16, 24 e 26 em quadros separados. Levanta
        DriveNaoConfirmou se qualquer leitura falhar -- uma conferencia com
        buraco nao prova nada.
        """
        cfg = dict(zip(range(REG_CORRENTE_PICO, REG_CORRENTE_PICO + 4),
                       self.ler(REG_CORRENTE_PICO, 4)))
        cfg[REG_AUTOAJUSTE] = self.ler(REG_AUTOAJUSTE)[0]
        cfg[REG_KP], cfg[REG_KI] = self.ler(REG_KP, 2)
        cfg[REG_MALHA] = self.ler(REG_MALHA)[0]
        cfg[REG_CORRENTE_OPER_PCT] = self.ler(REG_CORRENTE_OPER_PCT)[0]
        return cfg

    def aguardar_religamento(self, prazo=120.0, silencio_min=1.0,
                             estabilizar=1.0, ao_mudar=None, cancelado=None):
        """Espera o drive sumir do barramento e voltar: a prova de que foi
        desligado e religado.

        Pergunta o ID (31) em laco e avisa cada fase por `ao_mudar(fase)`:
        RELIGA_ESPERANDO -> RELIGA_DESLIGADO -> RELIGA_RELIGADO. So conta
        como desligado depois de `silencio_min` segundos seguidos sem
        resposta: um quadro perdido por ruido nao e religamento. Ao voltar,
        espera `estabilizar` segundos para o drive terminar de inicializar.

        Devolve True se viu o ciclo completo; False se o prazo acabou ou se
        `cancelado()` devolveu True.
        """
        def _fase(nome):
            if ao_mudar is not None:
                ao_mudar(nome)

        _fase(RELIGA_ESPERANDO)
        desligado = False
        mudo_desde = None
        limite = time.time() + prazo
        while time.time() < limite:
            if cancelado is not None and cancelado():
                return False
            responde = self.responde()
            agora = time.time()
            if not desligado:
                if responde:
                    mudo_desde = None
                else:
                    mudo_desde = agora if mudo_desde is None else mudo_desde
                    if agora - mudo_desde >= silencio_min:
                        desligado = True
                        _fase(RELIGA_DESLIGADO)
            elif responde:
                time.sleep(estabilizar)
                _fase(RELIGA_RELIGADO)
                return True
            time.sleep(0.3)
        return False

    def configurar(self, corrente_ma, malha=config.MALHA_PADRAO, log=print):
        """Ajusta malha e corrente de pico e grava na memoria do drive."""
        corrente_ma = max(CORRENTE_MIN_MA, min(CORRENTE_MAX_MA, int(corrente_ma)))
        log("[Drive {}] {} e corrente de pico = {} mA...".format(
            self.slave_id, MALHAS.get(malha, malha), corrente_ma))
        self.escrever(REG_MALHA, malha)
        self.escrever(REG_CORRENTE_PICO, corrente_ma)
        if not self.salvar_parametros():
            raise DriveNaoConfirmou(
                "Drive {}: o salvamento (reg 90) nao foi confirmado".format(
                    self.slave_id))
        log("[Drive {}] Configurado e salvo.".format(self.slave_id))
        return True


def desarmar_todos(barramento, drives=config.TODOS_OS_DRIVES, log=print):
    """Parada e desabilitacao em todos os drives. Devolve os que nao confirmaram.

    Nao levanta excecao: esta e a rotina de seguranca, e um drive mudo nao pode
    impedir a tentativa de desarmar os outros. Chame sempre num finally.
    """
    falhas = []
    for slave_id in drives:
        drive = Drive(barramento, slave_id)
        try:
            drive.parar()
        except Exception:
            pass                     # a desabilitacao abaixo e o que importa
        try:
            drive.desarmar()
            log("[Drive {}] Desabilitado.".format(slave_id))
        except Exception as e:
            falhas.append(slave_id)
            log("*** [Drive {}] NAO confirmou a desabilitacao: {}".format(slave_id, e))
        time.sleep(0.2)
    return falhas


def varrer(barramento, faixa=None, log=print):
    """Lista os enderecos que respondem no barramento.

    Rode antes de movimentar: se um ID esperado nao aparece, e DIP errado, cabo
    solto ou drive sem alimentacao. Se aparecem menos IDs do que drives ligados,
    ha enderecos duplicados.
    """
    faixa = faixa or range(config.SLAVE_MIN, config.VARREDURA_MAX + 1)
    encontrados = []
    for slave_id in faixa:
        if Drive(barramento, slave_id).responde():
            encontrados.append(slave_id)
            log("[Drive {}] responde.".format(slave_id))
    return encontrados
