"""Inspetor de registrador: a vigilancia so compara valores do proprio endereco.

Sem janela, sem drive: o mixin roda sobre um objeto que devolve leituras
roteirizadas e registra o que seria pintado.

Rodar da pasta que contem jog_gui/:

    python -m unittest discover -s jog_gui/tests -t . -v
"""
import unittest

from jog_gui.ui import inspetor as modulo_inspetor
from jog_gui.ui.inspetor import InspetorMixin


class _Janela(InspetorMixin):

    def __init__(self, leituras):
        self.leituras = list(leituras)
        self.reg_vigiando = True
        self._conectado = True
        self.reg_intervalo = None
        self._reg_ultimo = None
        self._reg_ultimo_end = None
        self._reg_mudancas = 0
        self.pintados = []
        self.ao_ler = None
        self.movendo = []     # um bool por volta do laco; vazio = parado
        self.logs = []
        self.lidos = 0

    def _ivar(self, var, padrao=0):
        return padrao

    def _movimento_em_curso(self):
        return self.movendo.pop(0) if self.movendo else False

    def _ler_regs(self, reg, count):
        self.lidos += 1
        if not self.leituras:
            self.reg_vigiando = False
            return None
        valor = self.leituras.pop(0)
        if self.ao_ler is not None:
            self.ao_ler(self)
        return [valor]

    def after(self, ms, fn):
        fn()

    def _reg_mostra(self, reg, valor, anterior=None):
        self.pintados.append((reg, valor, anterior))

    def _log(self, msg):
        self.logs.append(msg)


class TestVigilancia(unittest.TestCase):

    def setUp(self):
        self._sleep = modulo_inspetor.time.sleep
        modulo_inspetor.time.sleep = lambda s: None

    def tearDown(self):
        modulo_inspetor.time.sleep = self._sleep

    def test_ler_outro_endereco_nao_vira_mudanca_falsa(self):
        # Vigiando o 75 em 160; no meio, "Ler agora" do 73 deixa 3 em
        # _reg_ultimo. Antes isso aparecia como "75 mudou: 3 -> 160".
        j = _Janela([160, 160, 160])

        def _ler_agora_73(janela):
            janela._reg_ultimo, janela._reg_ultimo_end = 3, 73

        j.ao_ler = _ler_agora_73
        j._reg_loop_vigia(75)
        self.assertEqual(j.pintados, [(75, 160, None)])
        self.assertEqual(j._reg_mudancas, 0)

    def test_mudanca_de_verdade_e_anunciada(self):
        j = _Janela([128, 160, 128])
        j._reg_loop_vigia(75)
        self.assertEqual(j.pintados, [(75, 128, None), (75, 160, 128),
                                      (75, 128, 160)])
        self.assertEqual(j._reg_mudancas, 2)

    def test_espera_enquanto_um_movimento_usa_o_barramento(self):
        # Uma requisicao por vez: durante o movimento so a rotina dele le.
        j = _Janela([128, 160])
        j.movendo = [False, True, True, False]
        j._reg_loop_vigia(75)
        self.assertEqual(j.pintados, [(75, 128, None), (75, 160, 128)])
        self.assertEqual(j.lidos, 3)          # 2 leituras + a que encerra
        self.assertTrue(any("em espera" in m for m in j.logs))
        self.assertTrue(any("retomada" in m for m in j.logs))


if __name__ == "__main__":
    unittest.main()
