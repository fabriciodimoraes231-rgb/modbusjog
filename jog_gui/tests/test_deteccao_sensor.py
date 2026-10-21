"""TESTAR SENSOR: deteccao da entrada (IN1/IN2) e do nivel do reg 73.

Sem janela e sem drive: o mixin roda sobre um objeto que devolve leituras
roteirizadas do 73 e do 75 e anota o que seria aplicado na tela.

Rodar da pasta que contem jog_gui/:

    python -m unittest discover -s jog_gui/tests -t . -v
"""
import unittest

from jog_gui.str6 import REG_CONTROLE, REG_STATUS
from jog_gui.ui.homing import HomingMixin


class _Janela(HomingMixin):
    """O minimo que o teste do sensor usa."""

    _TESTE_INTERVALO = 0.0

    def __init__(self, reg73, leituras_75):
        self.reg73 = reg73
        self.leituras_75 = list(leituras_75)
        self.teste_ativo = True
        self.fim = None
        self.aplicado = None
        self.log = []

    def _ler_regs(self, reg, count):
        if reg == REG_CONTROLE:
            return [self.reg73]
        if reg == REG_STATUS:
            if not self.leituras_75:
                self.teste_ativo = False      # acabou o roteiro: "PARAR TESTE"
                return [0x0080]
            return [self.leituras_75.pop(0)]
        raise AssertionError("leitura inesperada do reg {}".format(reg))

    def _log(self, msg):
        self.log.append(msg)

    def after(self, ms, fn):
        fn()

    def _teste_ui(self, idx, st, bordas, restante):
        pass

    def _teste_fim(self, msg, ok):
        self.fim = (msg, ok)
        self.teste_ativo = False

    def _aplicar_deteccao(self, det, invertido, reg73, novo_73):
        self.aplicado = (det, invertido, reg73, novo_73)


class TestDeteccao(unittest.TestCase):

    def test_sensor_em_in2_lido_invertido_propoe_o_nivel_de_fabrica(self):
        # O caso da bancada: 73 = 0x0002 e, com a lamina fora, 75 = 0x0090.
        j = _Janela(0x0002, [0x0090, 0x0080, 0x0090])
        j._do_teste_sensor(0)
        self.assertTrue(j.fim[1], j.fim)
        self.assertEqual(j.aplicado, (1, False, 0x0002, 0x0003))

    def test_sensor_em_in1_ja_certo_nao_muda_o_73(self):
        j = _Janela(0x0003, [0x0080, 0x00A0, 0x0080])
        j._do_teste_sensor(1)
        self.assertEqual(j.aplicado, (0, False, 0x0003, 0x0003))

    def test_sensor_que_conduz_em_repouso_pede_nivel_invertido(self):
        # Sensor NF em IN2 com o 73 de fabrica: repouso lido como acionado.
        j = _Janela(0x0003, [0x0090, 0x0080, 0x0090])
        j._do_teste_sensor(1)
        self.assertEqual(j.aplicado, (1, True, 0x0003, 0x0002))

    def test_termina_sozinho_depois_de_entrar_e_sair(self):
        j = _Janela(0x0003, [0x0080, 0x0090, 0x0080, 0x0090, 0x0080])
        j._do_teste_sensor(1)
        self.assertEqual(j.leituras_75, [0x0090, 0x0080])

    def test_nenhuma_entrada_mudou_nao_aplica_nada(self):
        j = _Janela(0x0003, [0x0080] * 5)
        j._do_teste_sensor(0)
        self.assertIsNone(j.aplicado)
        self.assertFalse(j.fim[1])

    def test_as_duas_mudaram_nao_aplica_nada(self):
        j = _Janela(0x0003, [0x0080, 0x00B0, 0x0080])
        j._do_teste_sensor(0)
        self.assertIsNone(j.aplicado)
        self.assertIn("duas entradas", j.fim[0])

    def test_sem_ler_o_73_nao_comeca(self):
        j = _Janela(None, [0x0080])
        j._ler_regs = lambda reg, count: None
        j._do_teste_sensor(0)
        self.assertIsNone(j.aplicado)
        self.assertIn("reg 73", j.fim[0])


if __name__ == "__main__":
    unittest.main()
