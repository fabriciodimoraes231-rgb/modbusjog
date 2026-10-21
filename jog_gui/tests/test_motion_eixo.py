"""Testes de motion.eixo -- com um drive falso, sem porta serial nem hardware.

Rodar da pasta que contem jog_gui/:

    python -m unittest discover -s jog_gui/tests -t . -v

O DriveFalso para no nivel de `Drive`, com registradores num dicionario, e nao
monta quadros Modbus. Serve para provar a LOGICA de movimento contra o que o
manual do STR6 descreve; nao substitui a validacao em bancada, e os pontos em
aberto do manual (bit 7 do status, enable no reg 6) tem caso proprio aqui.
"""
import unittest

from jog_gui.motion import (
    CAUSA_ALARME,
    CAUSA_CANCELADO,
    CAUSA_DRIVE_MUDO,
    CAUSA_FORA_DA_FAIXA,
    CAUSA_LIMITE,
    CAUSA_MOTOR_OFF,
    CAUSA_NAO_PARTIU,
    CAUSA_RECUSADO,
    CAUSA_SEM_SENSOR,
    CAUSA_TIMEOUT,
    CAUSA_ZERO_INVALIDO,
    ENTRADA_LIM_NEG,
    ENTRADA_LIM_POS,
    FRENTE,
    TRAS,
    ConfigEixo,
    EixoMovimento,
    MovimentoRecusado,
)
from jog_gui.str6 import (
    CMD_CONTINUO_FRENTE,
    CMD_CONTINUO_TRAS,
    CMD_DESACELERAR,
    CMD_FRENTE,
    CMD_OCIOSO,
    CMD_PARADA_IMEDIATA,
    CMD_TRAS,
    DriveNaoConfirmou,
    HOME_LIMITE_NEG,
    HOME_LIMITE_POS,
    HOME_SAIR,
    REG_ALARME,
    REG_COMANDO,
    REG_CURSO_H,
    REG_CURSO_L,
    REG_DESACEL_L,
    REG_ENABLE,
    REG_HOME,
    REG_LIMPA_FALHA,
    REG_MODO_POSICAO,
    REG_PULSOS_H,
    REG_PULSOS_L,
    REG_STATUS,
    REG_VEL_HOME,
    REG_VEL_L,
    ST_LIMITE_NEG,
    ST_LIMITE_POS,
    ST_SOBRECORRENTE,
    VEL_MAX_PPS,
    bit7_para,
    palavras_32,
)


class DriveFalso:
    """Um STR6 de mentira no nivel de `Drive`: registradores num dicionario.

    O que ele encena:

      - comando (70): 1/2 andam o curso de 68/69 para frente/tras, 3/4 andam
        sem parar, 0 e 5 param. Depois de aceito o registrador volta a 6;
      - `frente_soma`: se o comando "frente" soma ou subtrai pulsos -- e o que
        o "Detectar sentido +" descobre na bancada;
      - status (75): bit 7 conforme BIT7_UM_E_CONCLUIDO (bit7_para), bits 4/5
        com o came na fenda do sensor, bit 0 em sobrecorrente. `bit7_preso`
        encena a polaridade errada: o bit 7 diz "em movimento" com o eixo
        parado (o manual se contradiz sobre o bit);
      - retorno a zero (71): anda ate a borda do came e para;
      - silencio: `mudo_por` faz N leituras seguidas falharem.

    O tempo e virtual: o eixo anda um passo a cada leitura do status.
    """

    def __init__(self, posicao=0, avancar_por_leitura=0, frente_soma=True):
        self.regs = {}
        self.posicao = posicao
        self.avancar_por_leitura = avancar_por_leitura
        self.frente_soma = frente_soma
        self.continuo = 0             # +1 / -1 / 0, no sentido da contagem
        self.passo_continuo = 1       # pulsos por leitura no movimento continuo
        self.alarme = 0
        self.status_extra = 0
        self.bit7_preso = False
        self.ignorar_comandos = False  # aceita e nao anda
        self.encurtar = []            # fracao do curso andada, por comando fixo
        self.zerar_funciona = True
        # Janela de posicao em que o came esta na fenda do sensor, ou None.
        self.came = None
        self.bit_sensor = ST_LIMITE_NEG
        self.mudo_por = 0
        self.escritas = []            # (reg, valor), na ordem
        self.recusar = set()          # registradores que respondem com recusa
        self._restante = 0
        self._home_alvo = None

    # --- a interface que EixoMovimento usa ---------------------------------

    def escrever(self, reg, valor):
        if reg in self.recusar:
            raise DriveNaoConfirmou("Drive falso: recusou reg {}".format(reg))
        self.escritas.append((reg, valor))
        self.regs[reg] = valor
        if reg == REG_COMANDO:
            self._comando(valor)
            self.regs[reg] = CMD_OCIOSO
        elif reg == REG_PULSOS_H and valor == 1 and self.zerar_funciona:
            self.posicao = 0
        elif reg == REG_HOME:
            self._retorno_a_zero(valor)
        elif reg == REG_LIMPA_FALHA and valor == 1:
            self.alarme = 0
            self.status_extra = 0
        return True

    def escrever_multiplos(self, reg, valores):
        if reg in self.recusar:
            raise DriveNaoConfirmou("Drive falso: recusou reg {}".format(reg))
        for i, valor in enumerate(valores):
            self.escritas.append((reg + i, valor))
            self.regs[reg + i] = valor
        return True

    def ler(self, reg, count=1):
        if self.mudo_por > 0:
            self.mudo_por -= 1
            raise DriveNaoConfirmou("Drive falso: sem resposta")
        if reg == REG_STATUS:
            self._avancar()           # o tempo passa entre duas leituras
            return [self._status()]
        if reg == REG_ALARME:
            return [self.alarme]
        if reg == REG_PULSOS_L:
            return (palavras_32(self.posicao) * 2)[:count]
        return [self.regs.get(reg + i, 0) for i in range(count)]

    # --- comportamento -----------------------------------------------------

    def _sinal(self, frente):
        """+1 se o sentido pedido soma pulsos neste drive."""
        return 1 if frente == self.frente_soma else -1

    def _comando(self, valor):
        if self.ignorar_comandos and valor not in (CMD_DESACELERAR,
                                                   CMD_PARADA_IMEDIATA):
            return
        if valor in (CMD_FRENTE, CMD_TRAS):
            curso = (self.regs.get(REG_CURSO_H, 0) << 16) | self.regs.get(REG_CURSO_L, 0)
            if self.encurtar:
                curso = int(curso * self.encurtar.pop(0))
            self._restante = self._sinal(valor == CMD_FRENTE) * curso
            self.continuo = 0
        elif valor in (CMD_CONTINUO_FRENTE, CMD_CONTINUO_TRAS):
            self.continuo = self._sinal(valor == CMD_CONTINUO_FRENTE)
            self._restante = 0
        elif valor in (CMD_DESACELERAR, CMD_PARADA_IMEDIATA):
            self.continuo = 0
            self._restante = 0
            self._home_alvo = None

    def _retorno_a_zero(self, valor):
        if valor == HOME_SAIR:
            self._home_alvo = None
            self.continuo = 0
            return
        if self.came is None:
            # Sem came no caminho: anda ate alguem desistir
            self.continuo = self._sinal(valor == HOME_LIMITE_POS)
        else:
            self._home_alvo = self.came[0]

    def _no_came(self):
        return self.came is not None and self.came[0] <= self.posicao <= self.came[1]

    def _status(self):
        movendo = bool(self._restante or self.continuo
                       or self._home_alvo is not None or self.bit7_preso)
        st = self.status_extra | bit7_para(movendo)
        if self._no_came():
            st |= self.bit_sensor
        return st

    def _avancar(self):
        """Move o eixo um passo virtual por leitura do status."""
        if self._home_alvo is not None:
            passo = self.avancar_por_leitura or 50
            dif = self._home_alvo - self.posicao
            self.posicao += max(-passo, min(passo, dif))
            if self.posicao == self._home_alvo:
                self._home_alvo = None
        elif self._restante:
            passo = self.avancar_por_leitura or abs(self._restante)
            passo = min(passo, abs(self._restante))
            sinal = 1 if self._restante > 0 else -1
            self.posicao += sinal * passo
            self._restante -= sinal * passo
        elif self.continuo:
            self.posicao += self.continuo * self.passo_continuo

    def passar_tempo(self, segundos):
        """Espera longa sem leitura (ex.: o 1 s do detectar sentido).

        So as esperas de meio segundo para cima movem o eixo continuo: as
        curtas, entre leituras dos lacos, ja sao cobertas pelo passo por
        leitura, e conta-las duas vezes faria o eixo pular a fenda do came.
        """
        if segundos >= 0.5 and self.continuo:
            self.posicao += self.continuo * self.passo_continuo * int(segundos / 0.06)

    # --- conveniencias dos testes ------------------------------------------

    def comandos(self):
        """Os valores escritos no reg 70, na ordem."""
        return [v for r, v in self.escritas if r == REG_COMANDO]


class RelogioVirtual:
    """Um relogio que so anda quando alguem dorme.

    Sem isto, um caso que exercita um timeout de 60 s ficaria 60 s de CPU em
    busy-wait. Com o relogio virtual o laco roda em milissegundos e o
    resultado deixa de depender da velocidade da maquina.
    """

    def __init__(self, ao_dormir=None):
        self.t = 1000.0
        self._ao_dormir = ao_dormir or (lambda segundos: None)

    def agora(self):
        return self.t

    def dormir(self, segundos):
        self.t += segundos
        self._ao_dormir(segundos)


def _eixo(drive=None, armado=True, zero=False, logs=None, **cfg):
    """Um EixoMovimento sobre o DriveFalso, com relogio virtual."""
    drive = drive or DriveFalso()
    config = ConfigEixo(1, "teste", **cfg)
    eixo = EixoMovimento(drive, config,
                         log=(logs.append if logs is not None else None))
    relogio = RelogioVirtual(drive.passar_tempo)
    eixo._dormir = relogio.dormir
    eixo._agora = relogio.agora
    eixo.armado = armado
    eixo.zero_valido = zero
    return eixo, drive


class TestArmarDesarmar(unittest.TestCase):

    def test_armar_grava_enable_e_marca_o_estado(self):
        eixo, drive = _eixo(armado=False)
        self.assertTrue(eixo.armar().ok)
        self.assertIn((REG_ENABLE, 1), drive.escritas)
        self.assertTrue(eixo.armado)

    def test_armar_carimba_a_hora_da_habilitacao(self):
        # A janela descarta leitura de "desabilitado" mais velha que isto:
        # sem o carimbo, um ciclo do monitor anterior ao MOTOR ON desmarcava
        # o eixo recem-habilitado.
        eixo, _ = _eixo(armado=False)
        antes = eixo._agora()
        eixo._dormir(1.0)
        eixo.armar()
        self.assertGreater(eixo.armado_em, antes)

    def test_armar_recusado_nao_marca_o_estado(self):
        drive = DriveFalso()
        drive.recusar.add(REG_ENABLE)
        eixo, _ = _eixo(drive, armado=False)
        res = eixo.armar()
        self.assertFalse(res.ok)
        self.assertEqual(res.causa, CAUSA_DRIVE_MUDO)
        self.assertFalse(eixo.armado)

    def test_desarmar_zera_o_enable(self):
        eixo, drive = _eixo()
        self.assertTrue(eixo.desarmar().ok)
        self.assertEqual(drive.escritas[-1], (REG_ENABLE, 0))
        self.assertFalse(eixo.armado)

    def test_sem_drive_nada_levanta(self):
        # O eixo nasce sem barramento na GUI; ate conectar, tudo falha calado.
        eixo = EixoMovimento(None, ConfigEixo(1))
        self.assertFalse(eixo.armar().ok)
        self.assertIsNone(eixo.ler_posicao())

    def test_limpar_alarme_escreve_93(self):
        eixo, drive = _eixo()
        drive.alarme = 6
        self.assertTrue(eixo.limpar_alarme().ok)
        self.assertIn((REG_LIMPA_FALHA, 1), drive.escritas)


class TestParadaSegura(unittest.TestCase):

    def test_primeiro_degrau_basta_quando_confirma(self):
        eixo, drive = _eixo()
        self.assertTrue(eixo.parada_segura("teste"))
        self.assertEqual(drive.comandos(), [CMD_DESACELERAR])
        self.assertNotIn((REG_ENABLE, 0), drive.escritas)

    def test_escala_para_parada_imediata_e_desabilita(self):
        drive = DriveFalso()
        drive.recusar.add(REG_COMANDO)
        eixo, _ = _eixo(drive)
        self.assertFalse(eixo.parada_segura("teste"))
        self.assertIn((REG_ENABLE, 0), drive.escritas)
        self.assertFalse(eixo.armado)

    def test_eixo_vertical_nao_desabilita_o_motor(self):
        drive = DriveFalso()
        drive.recusar.add(REG_COMANDO)
        eixo, _ = _eixo(drive, soltar_em_emergencia=False)
        self.assertFalse(eixo.parada_segura("teste"))
        self.assertNotIn((REG_ENABLE, 0), drive.escritas)
        self.assertTrue(eixo.armado)


class TestPerfilEComando(unittest.TestCase):
    """O perfil vai num FC16 so (62~69) e o comando sai por ultimo."""

    def test_perfil_inteiro_num_quadro_e_comando_por_ultimo(self):
        eixo, drive = _eixo()
        ok, _ = eixo.armar_movimento(80000, 6000)
        self.assertTrue(ok)
        regs = [r for r, _ in drive.escritas]
        self.assertEqual(regs[0], REG_MODO_POSICAO)          # incremental antes
        self.assertEqual(regs[1:9], list(range(REG_DESACEL_L, REG_CURSO_H + 1)))
        self.assertEqual(drive.escritas[-1], (REG_COMANDO, CMD_FRENTE))
        # curso de 80000 = 14464 baixa + 1 alta (manual p. 19)
        self.assertEqual(drive.regs[REG_CURSO_L], 14464)
        self.assertEqual(drive.regs[REG_CURSO_H], 1)
        self.assertEqual(drive.regs[REG_VEL_L], 6000)

    def test_rampa_vira_aceleracao(self):
        # 6000 p/s em 200 ms -> 30000 p/s^2, na desaceleracao e na aceleracao
        eixo, drive = _eixo(rampa_ms=200)
        eixo.armar_movimento(100, 6000)
        self.assertEqual(drive.regs[REG_DESACEL_L], 30000)
        self.assertEqual(drive.regs[REG_DESACEL_L + 4], 30000)

    def test_passo_negativo_vai_como_tras_com_curso_positivo(self):
        eixo, drive = _eixo()
        eixo.armar_movimento(-500, 1000)
        self.assertEqual(drive.regs[REG_CURSO_L], 500)
        self.assertEqual(drive.escritas[-1], (REG_COMANDO, CMD_TRAS))

    def test_sentido_pos_tras_inverte_o_comando(self):
        # Se quem soma pulsos e o TRAS, um passo positivo sai como comando 2.
        eixo, drive = _eixo(sentido_pos=TRAS)
        eixo.armar_movimento(500, 1000)
        self.assertEqual(drive.escritas[-1], (REG_COMANDO, CMD_TRAS))

    def test_velocidade_e_limitada_ao_teto(self):
        eixo, drive = _eixo()
        eixo.armar_movimento(100, VEL_MAX_PPS * 10)
        self.assertEqual(drive.regs[REG_VEL_L] | (drive.regs[REG_VEL_L + 1] << 16),
                         VEL_MAX_PPS)


class TestMoverPulsos(unittest.TestCase):

    def test_movimento_completo_devolve_a_posicao_final(self):
        eixo, drive = _eixo(DriveFalso(avancar_por_leitura=100))
        res = eixo.mover_pulsos(1000, 3000)
        self.assertTrue(res.ok, res)
        self.assertEqual(res.posicao, 1000)

    def test_bit7_preso_em_1_nao_impede_o_fim_no_destino(self):
        # Ponto em aberto do manual: a polaridade do bit 7. Se ele disser "em
        # movimento" com o eixo parado, a chegada ao destino encerra.
        drive = DriveFalso(avancar_por_leitura=100)
        drive.bit7_preso = True
        eixo, _ = _eixo(drive)
        res = eixo.mover_pulsos(1000, 3000)
        self.assertTrue(res.ok, res)
        self.assertEqual(res.posicao, 1000)

    def test_eixo_parado_antes_de_partir_nao_encerra(self):
        # Antes de o drive comecar a andar, a posicao repete e o bit 7 pode
        # estar em 0: isso nao pode ser lido como "terminou".
        drive = DriveFalso(avancar_por_leitura=100)
        eixo, _ = _eixo(drive)
        res = eixo.mover_pulsos(1000, 3000)
        self.assertEqual(res.posicao, 1000)

    def test_falha_durante_o_movimento_para_o_eixo(self):
        drive = DriveFalso(avancar_por_leitura=10)
        eixo, _ = _eixo(drive)
        drive.alarme = 7
        res = eixo.mover_pulsos(1000, 3000)
        self.assertEqual(res.causa, CAUSA_ALARME)
        self.assertIn("rotor travado", res.detalhe)
        self.assertIn(CMD_DESACELERAR, drive.comandos())

    def test_sobrecorrente_no_status_tambem_para(self):
        drive = DriveFalso(avancar_por_leitura=10)
        drive.status_extra = ST_SOBRECORRENTE
        eixo, _ = _eixo(drive)
        res = eixo.mover_pulsos(1000, 3000)
        self.assertEqual(res.causa, CAUSA_ALARME)
        self.assertIn("sobrecorrente", res.detalhe)

    def test_drive_que_nao_sai_do_lugar_e_repetido_uma_vez(self):
        drive = DriveFalso()
        drive.ignorar_comandos = True
        eixo, _ = _eixo(drive)
        res = eixo.mover_pulsos(1000, 3000)
        self.assertEqual(res.causa, CAUSA_NAO_PARTIU)
        self.assertEqual(drive.comandos().count(CMD_FRENTE), 2)

    def test_silencio_curto_nao_mata_o_movimento(self):
        drive = DriveFalso(avancar_por_leitura=100)
        eixo, _ = _eixo(drive)
        drive.mudo_por = 3
        res = eixo.mover_pulsos(500, 3000)
        self.assertTrue(res.ok, res)

    def test_posicao_ilegivel_recusa_sem_disparar(self):
        drive = DriveFalso()
        drive.mudo_por = 10_000
        eixo, _ = _eixo(drive)
        res = eixo.mover_pulsos(500, 3000)
        self.assertEqual(res.causa, CAUSA_DRIVE_MUDO)
        self.assertEqual(drive.comandos(), [])

    def test_cancelar_no_meio_do_movimento_para_o_eixo(self):
        drive = DriveFalso(avancar_por_leitura=10)
        eixo, _ = _eixo(drive)
        original = eixo.on_progress

        def _cancela(dados):
            original(dados)
            if dados.get("pos", 0) >= 50:
                eixo.cancelar()
        eixo.on_progress = _cancela
        res = eixo.mover_pulsos(1000, 3000)
        self.assertEqual(res.causa, CAUSA_CANCELADO)
        self.assertEqual(drive.comandos()[-1], CMD_DESACELERAR)

    def test_cancelado_antes_de_partir_nao_dispara(self):
        eixo, drive = _eixo()
        eixo.cancelar()
        res = eixo.mover_pulsos(1000, 3000)
        self.assertFalse(res.ok)
        self.assertNotIn(CMD_FRENTE, drive.comandos())


class TestPasso(unittest.TestCase):

    def test_passo_exige_motor_armado(self):
        eixo, drive = _eixo(armado=False)
        with self.assertRaises(MovimentoRecusado) as ctx:
            eixo.passo(+1)
        self.assertEqual(ctx.exception.causa, CAUSA_MOTOR_OFF)
        self.assertEqual(drive.escritas, [])

    def test_passo_positivo_anda_o_tamanho_configurado(self):
        eixo, drive = _eixo(passo_pulsos=300)
        res = eixo.passo(+1)
        self.assertTrue(res.ok, res)
        self.assertEqual(drive.posicao, 300)

    def test_passo_negativo_usa_o_sinal(self):
        eixo, drive = _eixo()
        res = eixo.passo(-1, pulsos=250)
        self.assertTrue(res.ok, res)
        self.assertEqual(drive.posicao, -250)

    def test_passo_segue_a_contagem_mesmo_com_frente_invertida(self):
        # Drive em que "frente" subtrai: com sentido_pos = TRAS cadastrado,
        # o passo + continua somando pulsos.
        drive = DriveFalso(frente_soma=False)
        eixo, _ = _eixo(drive, sentido_pos=TRAS)
        res = eixo.passo(+1, pulsos=400)
        self.assertTrue(res.ok, res)
        self.assertEqual(drive.posicao, 400)

    def test_passo_zero_nao_fala_com_o_drive(self):
        eixo, drive = _eixo()
        self.assertTrue(eixo.passo(+1, pulsos=0).ok)
        self.assertEqual(drive.escritas, [])

    def test_passo_fora_da_faixa_e_recusado_sem_mover(self):
        eixo, drive = _eixo(DriveFalso(posicao=900), zero=True,
                            limite_pos=1000, limite_neg=1000,
                            limites_ativos=True)
        res = eixo.passo(+1, pulsos=500)
        self.assertEqual(res.causa, CAUSA_FORA_DA_FAIXA)
        self.assertEqual(drive.comandos(), [])

    def test_passo_fora_da_faixa_que_volta_e_liberado(self):
        eixo, drive = _eixo(DriveFalso(posicao=1500), zero=True,
                            limite_pos=1000, limite_neg=1000,
                            limites_ativos=True)
        res = eixo.passo(-1, pulsos=200)
        self.assertTrue(res.ok, res)
        self.assertEqual(drive.posicao, 1300)

    def test_sem_zero_os_limites_nao_valem(self):
        eixo, drive = _eixo(DriveFalso(posicao=900), zero=False,
                            limite_pos=1000, limite_neg=1000,
                            limites_ativos=True)
        res = eixo.passo(+1, pulsos=500)
        self.assertTrue(res.ok, res)


class TestIrPara(unittest.TestCase):

    def test_alvo_alcancado_dentro_da_tolerancia(self):
        eixo, drive = _eixo(DriveFalso(avancar_por_leitura=500))
        res = eixo.ir_para(3000)
        self.assertTrue(res.ok, res)
        self.assertEqual(drive.posicao, 3000)

    def test_ja_no_alvo_nao_dispara_movimento(self):
        eixo, drive = _eixo(DriveFalso(posicao=3000))
        self.assertTrue(eixo.ir_para(3000).ok)
        self.assertEqual(drive.comandos(), [])

    def test_dentro_da_tolerancia_conta_como_chegada(self):
        eixo, drive = _eixo(DriveFalso(posicao=2990), tolerancia=20)
        self.assertTrue(eixo.ir_para(3000).ok)
        self.assertEqual(drive.comandos(), [])

    def test_alvo_fora_da_faixa_recusado_sem_escrever(self):
        eixo, drive = _eixo(zero=True, limite_pos=1000, limite_neg=1000)
        with self.assertRaises(MovimentoRecusado) as ctx:
            eixo.ir_para(5000)
        self.assertEqual(ctx.exception.causa, CAUSA_FORA_DA_FAIXA)
        self.assertEqual(drive.escritas, [])

    def test_limites_ativos_sem_zero_recusam(self):
        eixo, drive = _eixo(limite_pos=1000, limite_neg=1000,
                            limites_ativos=True)
        with self.assertRaises(MovimentoRecusado) as ctx:
            eixo.ir_para(500)
        self.assertEqual(ctx.exception.causa, CAUSA_ZERO_INVALIDO)

    def test_eixo_sem_sensor_tem_mensagem_propria(self):
        eixo, _ = _eixo(limite_pos=1000, limite_neg=1000, limites_ativos=True,
                        sensor_tem_origem=False)
        with self.assertRaises(MovimentoRecusado) as ctx:
            eixo.ir_para(500)
        self.assertEqual(ctx.exception.causa, CAUSA_SEM_SENSOR)

    def test_faixa_zerada_nao_limita_o_alvo(self):
        eixo, drive = _eixo()
        self.assertTrue(eixo.ir_para(50000).ok)
        self.assertEqual(drive.posicao, 50000)

    def test_erro_residual_e_corrigido_em_segunda_tentativa(self):
        drive = DriveFalso()
        drive.encurtar = [0.9]          # o primeiro movimento fica 10% curto
        eixo, _ = _eixo(drive)
        res = eixo.ir_para(10000)
        self.assertTrue(res.ok, res)
        self.assertEqual(drive.posicao, 10000)
        self.assertEqual(drive.comandos().count(CMD_FRENTE), 2)

    def test_julga_pela_posicao_final(self):
        drive = DriveFalso()
        drive.encurtar = [0.5, 0.5, 0.5]   # nunca chega
        eixo, _ = _eixo(drive)
        res = eixo.ir_para(10000)
        self.assertFalse(res.ok)
        self.assertEqual(res.posicao, drive.posicao)


class TestJog(unittest.TestCase):

    def test_jog_exige_motor_armado(self):
        eixo, drive = _eixo(armado=False)
        with self.assertRaises(MovimentoRecusado):
            eixo.jog_iniciar(3000, FRENTE)
        self.assertEqual(drive.escritas, [])

    def test_jog_frente_e_comando_3(self):
        eixo, drive = _eixo()
        self.assertTrue(eixo.jog_iniciar(3000, FRENTE).ok)
        self.assertEqual(drive.comandos(), [CMD_CONTINUO_FRENTE])
        self.assertEqual(drive.regs[REG_VEL_L], 3000)

    def test_jog_tras_e_comando_4(self):
        eixo, drive = _eixo()
        self.assertTrue(eixo.jog_iniciar(3000, TRAS).ok)
        self.assertEqual(drive.comandos(), [CMD_CONTINUO_TRAS])

    def test_jog_bloqueado_no_limite_nao_parte(self):
        eixo, drive = _eixo(DriveFalso(posicao=995), zero=True,
                            limite_pos=1000, limite_neg=1000,
                            limites_ativos=True, antecipacao=20)
        with self.assertRaises(MovimentoRecusado) as ctx:
            eixo.jog_iniciar(3000, FRENTE)
        self.assertEqual(ctx.exception.causa, CAUSA_LIMITE)
        self.assertEqual(drive.comandos(), [])

    def test_jog_no_limite_libera_o_sentido_oposto(self):
        eixo, drive = _eixo(DriveFalso(posicao=995), zero=True,
                            limite_pos=1000, limite_neg=1000,
                            limites_ativos=True, antecipacao=20)
        self.assertTrue(eixo.jog_iniciar(3000, TRAS).ok)

    def test_jog_parar_desacelera(self):
        eixo, drive = _eixo()
        eixo.jog_iniciar(3000, FRENTE)
        self.assertTrue(eixo.jog_parar().ok)
        self.assertEqual(drive.comandos()[-1], CMD_DESACELERAR)
        self.assertEqual(drive.continuo, 0)


class TestVigiarMovimento(unittest.TestCase):
    """Watchdog do JOG: comunicacao, falha e limite, um ciclo por chamada."""

    def test_tudo_bem_devolve_none(self):
        eixo, _ = _eixo()
        eixo.jog_iniciar(3000, FRENTE)
        self.assertIsNone(eixo.vigiar_movimento())

    def test_duas_leituras_mudas_param_o_eixo(self):
        eixo, drive = _eixo()
        eixo.jog_iniciar(3000, FRENTE)
        drive.mudo_por = 2
        self.assertIsNone(eixo.vigiar_movimento())
        res = eixo.vigiar_movimento()
        self.assertEqual(res.causa, CAUSA_DRIVE_MUDO)
        self.assertEqual(drive.comandos()[-1], CMD_DESACELERAR)

    def test_falha_para_o_eixo_na_hora(self):
        eixo, drive = _eixo()
        eixo.jog_iniciar(3000, FRENTE)
        drive.alarme = 1
        res = eixo.vigiar_movimento()
        self.assertEqual(res.causa, CAUSA_ALARME)
        self.assertEqual(drive.continuo, 0)

    def test_limite_atingido_para_o_eixo(self):
        drive = DriveFalso(posicao=970)
        drive.passo_continuo = 20
        eixo, _ = _eixo(drive, zero=True, limite_pos=1000, limite_neg=1000,
                        limites_ativos=True, antecipacao=20)
        eixo.jog_iniciar(3000, FRENTE)
        res = None
        for _ in range(5):
            res = eixo.vigiar_movimento()
            if res is not None:
                break
        self.assertEqual(res.causa, CAUSA_LIMITE)
        self.assertEqual(drive.continuo, 0)


class TestHomingSoftware(unittest.TestCase):
    """Os cinco passos do homing por software, com o came entrando e saindo."""

    def _eixo_home(self, posicao=2000, came=(-50, 50), **cfg):
        drive = DriveFalso(posicao=posicao)
        drive.passo_continuo = 25
        drive.came = came
        cfg.setdefault("home_entrada", ENTRADA_LIM_NEG)
        return _eixo(drive, **cfg)

    def test_homing_sem_sensor_e_recusado(self):
        eixo, drive = self._eixo_home(sensor_tem_origem=False)
        with self.assertRaises(MovimentoRecusado) as ctx:
            eixo.homing_software()
        self.assertEqual(ctx.exception.causa, CAUSA_SEM_SENSOR)
        self.assertEqual(drive.escritas, [])

    def test_homing_exige_motor_armado(self):
        eixo, _ = self._eixo_home(armado=False)
        with self.assertRaises(MovimentoRecusado) as ctx:
            eixo.homing_software()
        self.assertEqual(ctx.exception.causa, CAUSA_MOTOR_OFF)

    def test_homing_concluido_zera_a_posicao_e_valida_o_zero(self):
        eixo, drive = self._eixo_home()
        res = eixo.homing_software()
        self.assertTrue(res.ok, res)
        self.assertEqual(drive.posicao, 0)
        self.assertTrue(eixo.zero_valido)
        self.assertIn((REG_PULSOS_H, 1), drive.escritas)
        # Sensor no limite -: a busca sai para TRAS (comando 4)
        self.assertEqual(drive.comandos()[0], CMD_CONTINUO_TRAS)

    def test_sensor_no_limite_positivo_busca_para_frente(self):
        drive = DriveFalso(posicao=-2000)
        drive.passo_continuo = 25
        drive.came = (-50, 50)
        drive.bit_sensor = ST_LIMITE_POS
        eixo, _ = _eixo(drive, home_entrada=ENTRADA_LIM_POS)
        res = eixo.homing_software()
        self.assertTrue(res.ok, res)
        self.assertEqual(drive.comandos()[0], CMD_CONTINUO_FRENTE)

    def test_came_ja_na_fenda_recua_antes_de_buscar(self):
        eixo, drive = self._eixo_home(posicao=0)
        res = eixo.homing_software()
        self.assertTrue(res.ok, res)
        # Primeiro movimento e o recuo (oposto da busca: FRENTE)
        self.assertEqual(drive.comandos()[0], CMD_CONTINUO_FRENTE)

    def test_sensor_ilegivel_invalida_o_zero(self):
        eixo, drive = self._eixo_home(zero=True)
        drive.mudo_por = 10
        res = eixo.homing_software()
        self.assertEqual(res.causa, CAUSA_DRIVE_MUDO)
        self.assertFalse(eixo.zero_valido)

    def test_homing_cancelado_invalida_o_zero(self):
        eixo, drive = self._eixo_home(zero=True)

        def _cancela(dados):
            eixo.cancelar()
        eixo.on_progress = _cancela
        res = eixo.homing_software()
        self.assertEqual(res.causa, CAUSA_CANCELADO)
        self.assertFalse(eixo.zero_valido)
        self.assertEqual(drive.continuo, 0)

    def test_sensor_nunca_encontrado_da_timeout(self):
        eixo, drive = self._eixo_home(came=None)
        res = eixo.homing_software()
        self.assertEqual(res.causa, CAUSA_TIMEOUT)
        self.assertFalse(eixo.zero_valido)
        self.assertEqual(drive.continuo, 0)

    def test_alarme_durante_a_busca_para_o_eixo_e_nao_vira_timeout(self):
        eixo, drive = self._eixo_home(came=None)
        drive.alarme = 6
        res = eixo.homing_software()
        self.assertEqual(res.causa, CAUSA_ALARME)
        self.assertEqual(drive.continuo, 0)

    def test_recusa_do_movimento_e_relatada_como_recusa_nao_como_timeout(self):
        eixo, drive = self._eixo_home()
        drive.recusar.add(REG_DESACEL_L)
        res = eixo.homing_software()
        self.assertEqual(res.causa, CAUSA_DRIVE_MUDO)

    def test_contador_que_nao_zera_nao_conta_como_homing(self):
        eixo, drive = self._eixo_home()
        drive.zerar_funciona = False
        res = eixo.homing_software()
        self.assertEqual(res.causa, CAUSA_RECUSADO)
        self.assertFalse(eixo.zero_valido)


class TestHomingNativo(unittest.TestCase):
    """Retorno a zero do drive (71) com acompanhamento e zeragem (40 = 1)."""

    def test_homing_nativo_conclui_e_zera(self):
        drive = DriveFalso(posicao=3000, avancar_por_leitura=100)
        drive.came = (500, 600)
        eixo, _ = _eixo(drive, home_v_apr=6000, home_v_ras=800)
        res = eixo.homing_nativo()
        self.assertTrue(res.ok, res)
        self.assertTrue(eixo.zero_valido)
        self.assertEqual(drive.posicao, 0)
        self.assertIn((REG_VEL_HOME, 800), drive.escritas)
        self.assertIn((REG_HOME, HOME_LIMITE_NEG), drive.escritas)

    def test_entrada_positiva_usa_o_modo_1(self):
        drive = DriveFalso(posicao=0, avancar_por_leitura=100)
        drive.came = (2000, 2100)
        eixo, _ = _eixo(drive, home_entrada=ENTRADA_LIM_POS)
        self.assertTrue(eixo.homing_nativo().ok)
        self.assertIn((REG_HOME, HOME_LIMITE_POS), drive.escritas)

    def test_parametro_recusado_aborta_sem_disparar(self):
        drive = DriveFalso()
        drive.recusar.add(REG_VEL_HOME)
        eixo, _ = _eixo(drive)
        res = eixo.homing_nativo()
        self.assertEqual(res.causa, CAUSA_RECUSADO)
        self.assertNotIn(REG_HOME, [r for r, _ in drive.escritas])

    def test_timeout_sai_do_retorno_a_zero_e_invalida(self):
        drive = DriveFalso(posicao=0)
        drive.came = None             # anda para sempre
        drive.passo_continuo = 50
        eixo, _ = _eixo(drive, zero=True)
        res = eixo.homing_nativo()
        self.assertEqual(res.causa, CAUSA_TIMEOUT)
        self.assertFalse(eixo.zero_valido)
        self.assertIn((REG_HOME, HOME_SAIR), drive.escritas)

    def test_drive_que_nao_parte_e_relatado(self):
        drive = DriveFalso(posicao=0)
        drive.came = (0, 10)          # ja no alvo: nunca anda
        eixo, _ = _eixo(drive)
        res = eixo.homing_nativo()
        self.assertEqual(res.causa, CAUSA_NAO_PARTIU)
        self.assertFalse(eixo.zero_valido)


class TestDetectarSentido(unittest.TestCase):

    def test_frente_que_soma_devolve_frente(self):
        drive = DriveFalso()
        drive.passo_continuo = 100
        eixo, _ = _eixo(drive)
        res = eixo.detectar_sentido(3000)
        self.assertTrue(res.ok, res)
        self.assertEqual(res.valor, FRENTE)

    def test_frente_que_subtrai_devolve_tras(self):
        drive = DriveFalso(frente_soma=False)
        drive.passo_continuo = 100
        eixo, _ = _eixo(drive)
        res = eixo.detectar_sentido(3000)
        self.assertTrue(res.ok, res)
        self.assertEqual(res.valor, TRAS)

    def test_eixo_que_nao_anda_nao_decide(self):
        drive = DriveFalso()
        drive.passo_continuo = 0
        eixo, _ = _eixo(drive)
        res = eixo.detectar_sentido(3000)
        self.assertEqual(res.causa, CAUSA_NAO_PARTIU)


class TestConfigEixo(unittest.TestCase):
    """Traducao do bloco `config` do eixos.json para ConfigEixo."""

    def _cfg(self, valores):
        return ConfigEixo.de_dict(11, "eixo 11", valores)

    def test_aplicar_vira_limites_ativos(self):
        self.assertTrue(self._cfg({"aplicar": 1}).limites_ativos)

    def test_entrada_em_texto_vira_codigo(self):
        self.assertEqual(self._cfg({"home_entrada": "Limite + (IN2)"}).home_entrada,
                         ENTRADA_LIM_POS)
        self.assertEqual(self._cfg({"home_entrada": "Limite - (IN1)"}).home_entrada,
                         ENTRADA_LIM_NEG)

    def test_sentido_do_homing_decorre_da_entrada(self):
        self.assertEqual(self._cfg({"home_entrada": "IN2"}).home_sentido, FRENTE)
        self.assertEqual(self._cfg({"home_entrada": "IN1"}).home_sentido, TRAS)

    def test_modo_software_e_reconhecido(self):
        self.assertEqual(
            self._cfg({"home_modo": "Software - busca pelo sensor"}).home_modo,
            "software")
        self.assertEqual(
            self._cfg({"home_modo": "Nativo do drive (reg 71)"}).home_modo,
            "nativo")

    def test_cadastro_vazio_entra_com_padroes_conservadores(self):
        c = self._cfg({})
        self.assertEqual((c.limite_pos, c.limite_neg), (0, 0))
        self.assertFalse(c.limites_ativos)
        self.assertTrue(c.soltar_em_emergencia)
        # Decisao de 16/10/2026: o nativo pode travar o motor.
        self.assertEqual(c.home_modo, "software")

    def test_campo_estragado_cai_no_padrao(self):
        c = self._cfg({"jog_velocidade": "abc", "tolerancia": None})
        self.assertEqual(c.jog_velocidade, 3000)
        self.assertEqual(c.tolerancia, 40)

    def test_sentido_invalido_cai_no_padrao(self):
        c = self._cfg({"sentido_pos": "CW", "jog_sentido": "tras"})
        self.assertEqual(c.sentido_pos, FRENTE)
        self.assertEqual(c.jog_sentido, TRAS)

    def test_apelido_vazio_recebe_um_padrao(self):
        self.assertEqual(ConfigEixo(7).apelido, "eixo 7")

    def test_sentido_oposto(self):
        self.assertEqual(ConfigEixo(1, sentido_pos=FRENTE).sentido_oposto_pos, TRAS)
        self.assertEqual(ConfigEixo(1, sentido_pos=TRAS).sentido_oposto_pos, FRENTE)


if __name__ == "__main__":
    unittest.main()
