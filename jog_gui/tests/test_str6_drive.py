"""Testes de str6.drive com um barramento falso -- sem porta serial.

Rodar da pasta que contem jog_gui/:

    python -m unittest discover -s jog_gui/tests -t . -v

O BarramentoFalso responde quadro a quadro como um drive faria: eco nas
escritas, valores do dicionario nas leituras, excecao 02h em registrador
recusado. Exercita a montagem real dos quadros, ao contrario do DriveFalso
de test_motion_eixo, que para no nivel de Drive.
"""
import struct
import unittest

from jog_gui.str6 import (
    CMD_FRENTE,
    CMD_TRAS,
    REG_COMANDO,
    REG_CORRENTE_PICO,
    REG_CURSO_H,
    REG_CURSO_L,
    REG_ENABLE,
    REG_ID,
    REG_MALHA,
    REG_MODO_POSICAO,
    REG_PULSOS_L,
    REG_SALVAR,
    REGS_CONFIGURACAO,
    RELIGA_DESLIGADO,
    RELIGA_ESPERANDO,
    RELIGA_RELIGADO,
    Drive,
    DriveNaoConfirmou,
    comparar_configuracao,
    crc16,
    desarmar_todos,
    palavras_32,
)
from jog_gui.str6 import drive as modulo_drive


# Padrao de fabrica dos registradores de configuracao (manual p. 13)
# O manual nao da o padrao do 26: o 100 e so do simulador.
FABRICA = {0: 3000, 1: 6000, 2: 300, 3: 50, 13: 1, 15: 1000, 16: 200, 24: 2,
           26: 100}


class BarramentoFalso:
    """Responde aos quadros como um STR6 no endereco `slave`.

    Simula tambem a memoria permanente: `memoria` guarda o que o 90 salvou, e
    `religar()` devolve o drive ao padrao de fabrica sobreposto por ela -- o
    que um drive de verdade faz ao voltar a ser alimentado.
    """

    def __init__(self, slave=1):
        self.slave = slave
        self.memoria = {}
        self.regs = {}
        self.religar()
        self.recusar = set()
        self.quadros = []
        # Leituras do 90 que ainda devolvem 0 antes de o salvamento concluir
        self.salvar_demora = 0
        # False: o 90 fica em 1 depois do primeiro salvamento (ponto em aberto)
        self.flag_90_volta_a_zero = True
        # False: o 90 confirma, mas nada chega a memoria permanente
        self.grava_de_verdade = True
        self.ligado = True
        # Chamado antes de cada quadro -- para roteirizar desligamentos
        self.ao_transacionar = None

    def religar(self):
        """O drive volta da falta de alimentacao: fabrica + o que foi salvo."""
        self.regs = dict(FABRICA)
        self.regs.update(self.memoria)
        self.regs[REG_ID] = self.slave

    def _resp(self, corpo):
        return corpo + crc16(corpo)

    def transact(self, cmd, expected_bytes):
        if self.ao_transacionar is not None:
            self.ao_transacionar(self)
        self.quadros.append(cmd)
        slave, fc = cmd[0], cmd[1]
        if slave != self.slave or not self.ligado:
            return None
        reg = struct.unpack(">H", cmd[2:4])[0]
        if reg in self.recusar:
            return self._resp(bytes([slave, fc | 0x80, 0x02]))
        if fc == 0x06:
            valor = struct.unpack(">H", cmd[4:6])[0]
            self.regs[reg] = valor
            if reg == REG_SALVAR:
                if self.grava_de_verdade:
                    self.memoria = {r: self.regs[r] for r in REGS_CONFIGURACAO}
                if self.flag_90_volta_a_zero:
                    self.regs[REG_SALVAR] = 0
            return cmd[:6] + crc16(cmd[:6])
        if fc == 0x10:
            n = struct.unpack(">H", cmd[4:6])[0]
            for i in range(n):
                self.regs[reg + i] = struct.unpack(">H", cmd[7 + 2 * i:9 + 2 * i])[0]
            return self._resp(cmd[:6])
        if fc == 0x03:
            n = struct.unpack(">H", cmd[4:6])[0]
            if reg == REG_SALVAR and self.regs.get(REG_SALVAR) == 0:
                if self.salvar_demora:
                    self.salvar_demora -= 1
                else:
                    self.regs[REG_SALVAR] = 1
            corpo = bytes([slave, 0x03, n * 2])
            for i in range(n):
                corpo += struct.pack(">H", self.regs.get(reg + i, 0) & 0xFFFF)
            return self._resp(corpo)
        return None


class SemEspera(unittest.TestCase):
    """Troca o sleep do modulo por um no-op: os testes nao esperam de verdade."""

    def setUp(self):
        self._sleep = modulo_drive.time.sleep
        modulo_drive.time.sleep = lambda s: None

    def tearDown(self):
        modulo_drive.time.sleep = self._sleep


class TestDrive(SemEspera):

    def test_faixa_de_endereco(self):
        with self.assertRaises(ValueError):
            Drive(BarramentoFalso(), 0)
        with self.assertRaises(ValueError):
            Drive(BarramentoFalso(), 248)

    def test_escrita_confirmada_e_levada_ao_log(self):
        log = []
        bus = BarramentoFalso()
        Drive(bus, 1, log=log.append).armar()
        self.assertEqual(bus.regs[REG_ENABLE], 1)
        self.assertTrue(log[0].startswith("[TX]  01 06 00 06 00 01"))

    def test_recusa_vira_excecao_com_o_motivo(self):
        bus = BarramentoFalso()
        bus.recusar.add(REG_ENABLE)
        with self.assertRaises(DriveNaoConfirmou) as ctx:
            Drive(bus, 1).armar()
        self.assertIn("02h", str(ctx.exception))

    def test_responde_le_o_id(self):
        self.assertTrue(Drive(BarramentoFalso(slave=5), 5).responde())
        self.assertFalse(Drive(BarramentoFalso(slave=5), 6).responde())

    def test_posicao_com_sinal_e_palavra_baixa_primeiro(self):
        bus = BarramentoFalso()
        baixa, alta = palavras_32(-70000)
        bus.regs[REG_PULSOS_L], bus.regs[REG_PULSOS_L + 1] = baixa, alta
        self.assertEqual(Drive(bus, 1).posicao(), -70000)

    def test_mover_relativo_garante_incremental_e_usa_o_sinal(self):
        bus = BarramentoFalso()
        bus.regs[REG_MODO_POSICAO] = 1
        Drive(bus, 1).mover_relativo(-80000, 6000)
        self.assertEqual(bus.regs[REG_MODO_POSICAO], 0)
        self.assertEqual((bus.regs[REG_CURSO_L], bus.regs[REG_CURSO_H]), (14464, 1))
        self.assertEqual(bus.regs[REG_COMANDO], CMD_TRAS)
        Drive(bus, 1).mover_relativo(100, 6000)
        self.assertEqual(bus.regs[REG_COMANDO], CMD_FRENTE)

    def test_salvar_espera_a_confirmacao_do_reg_90(self):
        bus = BarramentoFalso()
        bus.salvar_demora = 3
        self.assertTrue(Drive(bus, 1).salvar_parametros())
        leituras = [q for q in bus.quadros if q[1] == 0x03]
        # uma antes do pedido + tres com 0 + a que confirma
        self.assertEqual(len(leituras), 5)

    def test_salvar_avisa_quando_o_1_pode_ser_do_salvamento_anterior(self):
        bus = BarramentoFalso()
        bus.flag_90_volta_a_zero = False
        bus.regs[REG_SALVAR] = 1
        log = []
        self.assertTrue(Drive(bus, 1, log=log.append).salvar_parametros())
        self.assertTrue(any("ja estava em 1" in m for m in log))

    def test_salvar_nao_avisa_quando_o_90_passa_por_0(self):
        bus = BarramentoFalso()
        bus.regs[REG_SALVAR] = 1     # sobra de um salvamento anterior
        bus.salvar_demora = 1
        log = []
        self.assertTrue(Drive(bus, 1, log=log.append).salvar_parametros())
        self.assertFalse(any("ja estava em 1" in m for m in log))

    def test_ler_configuracao_traz_os_registradores_da_configuracao(self):
        bus = BarramentoFalso()
        bus.regs[REG_CORRENTE_PICO] = 1500
        cfg = Drive(bus, 1).ler_configuracao()
        self.assertEqual(sorted(cfg), sorted(REGS_CONFIGURACAO))
        self.assertEqual(cfg[REG_CORRENTE_PICO], 1500)

    def test_ler_configuracao_com_buraco_levanta(self):
        bus = BarramentoFalso()
        bus.recusar.add(REG_MALHA)
        with self.assertRaises(DriveNaoConfirmou):
            Drive(bus, 1).ler_configuracao()

    def test_comparar_configuracao(self):
        self.assertEqual(comparar_configuracao({0: 1500, 24: 1}, {0: 1500, 24: 1}), [])
        self.assertEqual(comparar_configuracao({0: 1500, 24: 1}, {0: 3000}),
                         [(0, 1500, 3000), (24, 1, None)])

    def test_salvar_sem_confirmacao_devolve_false(self):
        bus = BarramentoFalso()
        bus.salvar_demora = 10 ** 9
        self.assertFalse(Drive(bus, 1).salvar_parametros(espera=0.0))

    def test_salvar_desiste_depois_das_consultas_do_prazo(self):
        bus = BarramentoFalso()
        bus.salvar_demora = 10 ** 9
        self.assertFalse(Drive(bus, 1).salvar_parametros(espera=1.0))
        leituras = [q for q in bus.quadros if q[1] == 0x03]
        # uma antes do pedido + 1,0 s / 0,2 s de consultas
        self.assertEqual(len(leituras), 1 + 5)

    def test_salvar_nao_desiste_pelo_relogio(self):
        # Barramento disputado: cada consulta passa 60 s na fila. Com o prazo
        # no relogio, a rotina desistia sem ter ouvido o drive confirmar.
        bus = BarramentoFalso()
        bus.salvar_demora = 3
        relogio = [0.0]

        def _agora():
            relogio[0] += 60.0
            return relogio[0]

        original = modulo_drive.time.time
        modulo_drive.time.time = _agora
        try:
            self.assertTrue(Drive(bus, 1).salvar_parametros(espera=1.0))
        finally:
            modulo_drive.time.time = original

    def test_configurar_limita_a_corrente_a_faixa_do_manual(self):
        bus = BarramentoFalso()
        Drive(bus, 1).configurar(99999, log=lambda m: None)
        self.assertEqual(bus.regs[REG_CORRENTE_PICO], 7800)
        self.assertEqual(bus.regs[REG_MALHA], 1)

    def test_desarmar_todos_nao_para_no_primeiro_mudo(self):
        bus = BarramentoFalso(slave=2)
        falhas = desarmar_todos(bus, drives=(1, 2, 3), log=lambda m: None)
        self.assertEqual(falhas, [1, 3])
        self.assertEqual(bus.regs[REG_ENABLE], 0)


class RelogioFalso:
    """Substitui o modulo `time` dentro de str6.drive: sleep avanca o relogio."""

    def __init__(self):
        self.t = 0.0

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += s


class TestReligamento(unittest.TestCase):
    """Drive.aguardar_religamento e a prova de gravacao que ele permite."""

    def setUp(self):
        self._time = modulo_drive.time
        self.relogio = RelogioFalso()
        modulo_drive.time = self.relogio

    def tearDown(self):
        modulo_drive.time = self._time

    def _desligar_entre(self, bus, de, ate):
        """O drive fica sem alimentacao de `de` a `ate` segundos."""
        def _roteiro(b):
            desligado = de <= self.relogio.t < ate
            if b.ligado and desligado:
                b.ligado = False
            elif not b.ligado and not desligado:
                b.religar()
                b.ligado = True
        bus.ao_transacionar = _roteiro

    def test_corrente_salva_sobrevive_ao_religamento(self):
        bus = BarramentoFalso()
        drive = Drive(bus, 1)
        drive.escrever(REG_CORRENTE_PICO, 1500)
        self.assertTrue(drive.salvar_parametros())
        antes = drive.ler_configuracao()

        fases = []
        self._desligar_entre(bus, self.relogio.t + 2, self.relogio.t + 6)
        self.assertTrue(drive.aguardar_religamento(ao_mudar=fases.append))
        self.assertEqual(fases, [RELIGA_ESPERANDO, RELIGA_DESLIGADO, RELIGA_RELIGADO])

        depois = drive.ler_configuracao()
        self.assertEqual(depois[REG_CORRENTE_PICO], 1500)
        self.assertEqual(comparar_configuracao(antes, depois), [])

    def test_corrente_sem_salvar_e_perdida_no_religamento(self):
        bus = BarramentoFalso()
        drive = Drive(bus, 1)
        drive.escrever(REG_CORRENTE_PICO, 1500)
        antes = drive.ler_configuracao()
        self._desligar_entre(bus, 1, 4)
        self.assertTrue(drive.aguardar_religamento())
        self.assertEqual(comparar_configuracao(antes, drive.ler_configuracao()),
                         [(REG_CORRENTE_PICO, 1500, 3000)])

    def test_90_que_confirma_sem_gravar_e_desmascarado(self):
        bus = BarramentoFalso()
        bus.grava_de_verdade = False
        drive = Drive(bus, 1)
        drive.escrever(REG_CORRENTE_PICO, 1500)
        self.assertTrue(drive.salvar_parametros())   # o 90 diz que salvou...
        antes = drive.ler_configuracao()
        self._desligar_entre(bus, self.relogio.t + 1, self.relogio.t + 4)
        self.assertTrue(drive.aguardar_religamento())
        # ...e o religamento mostra que nao
        self.assertNotEqual(comparar_configuracao(antes, drive.ler_configuracao()), [])

    def test_quadro_perdido_nao_conta_como_desligamento(self):
        bus = BarramentoFalso()
        self._desligar_entre(bus, 1.0, 1.4)       # menos que silencio_min
        fases = []
        self.assertFalse(Drive(bus, 1).aguardar_religamento(
            prazo=10, ao_mudar=fases.append))
        self.assertEqual(fases, [RELIGA_ESPERANDO])

    def test_prazo_sem_religar(self):
        bus = BarramentoFalso()
        self._desligar_entre(bus, 1, 10 ** 6)     # desligado e nunca religado
        fases = []
        self.assertFalse(Drive(bus, 1).aguardar_religamento(
            prazo=30, ao_mudar=fases.append))
        self.assertEqual(fases, [RELIGA_ESPERANDO, RELIGA_DESLIGADO])

    def test_cancelado(self):
        bus = BarramentoFalso()
        self.assertFalse(Drive(bus, 1).aguardar_religamento(
            cancelado=lambda: self.relogio.t > 3))
        self.assertLess(self.relogio.t, 5)


if __name__ == "__main__":
    unittest.main()
