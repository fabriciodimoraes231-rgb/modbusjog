"""Monitor periodico: um ciclo por vez e rodizio sem eixos mudos.

Sem janela, sem drive: os mixins rodam sobre um objeto que so registra o que
seria disparado (`_thread_op`) e agendado (`after`).

Rodar da pasta que contem jog_gui/:

    python -m unittest discover -s jog_gui/tests -t . -v
"""
import unittest

from jog_gui.ui.drives import DrivesMixin
from jog_gui.ui.status import StatusMixin


class _Var:
    def __init__(self, valor):
        self.valor = valor

    def get(self):
        return self.valor


class _Janela(StatusMixin, DrivesMixin):
    """O minimo de estado que o monitor usa."""

    def __init__(self, eixos=(1,), ativo=1):
        self._conectado = True
        self._poll_em_voo = False
        self._poll_tick = 0
        self._poll_after = None
        self._secundario_mudo_ate = {}
        self.eixos = {i: None for i in eixos}
        self.slave = _Var(ativo)
        self.disparados = []
        self.ciclos = 0
        self.mudos = set()
        self.lidos = []

    def _thread_op(self, target, *args, slave=None):
        self.disparados.append((target, args))

    def after(self, ms, fn):
        return "after"

    def _do_poll(self, lento):
        self.ciclos += 1

    def _ler_resumo_eixo(self, ident):
        self.lidos.append(ident)
        return None if ident in self.mudos else {"status": 0}

    def _atualizar_linha(self, ident, resumo):
        pass

    def rodar_disparados(self):
        pendentes, self.disparados = self.disparados, []
        for target, args in pendentes:
            target(*args)


class TestUmCicloPorVez(unittest.TestCase):

    def test_nao_dispara_ciclo_novo_com_o_anterior_em_voo(self):
        j = _Janela()
        j._poll_status()
        j._poll_status()
        j._poll_status()
        self.assertEqual(len(j.disparados), 1)

    def test_ciclo_terminado_libera_o_proximo(self):
        j = _Janela()
        j._poll_status()
        j.rodar_disparados()
        self.assertFalse(j._poll_em_voo)
        j._poll_status()
        self.assertEqual(len(j.disparados), 1)
        self.assertEqual(j.ciclos, 1)

    def test_ciclo_que_falha_tambem_libera(self):
        j = _Janela()

        def _quebra(lento):
            raise RuntimeError("porta caiu")

        j._do_poll = _quebra
        j._poll_status()
        with self.assertRaises(RuntimeError):
            j.rodar_disparados()
        self.assertFalse(j._poll_em_voo)


class TestRodizioDosSecundarios(unittest.TestCase):

    def test_eixo_mudo_sai_do_rodizio(self):
        j = _Janela(eixos=(1, 2, 3), ativo=1)
        j.mudos = {2}
        for _ in range(4):
            j._poll_secundarios()
        # o 2 e consultado uma vez, nao responde, e o rodizio fica no 3
        self.assertEqual(j.lidos, [2, 3, 3, 3])

    def test_eixo_volta_ao_rodizio_depois_da_pausa(self):
        j = _Janela(eixos=(1, 2), ativo=1)
        j.mudos = {2}
        j._poll_secundarios()
        j._poll_secundarios()
        self.assertEqual(j.lidos, [2])
        j._secundario_mudo_ate[2] = 0          # pausa vencida
        j.mudos = set()
        j._poll_secundarios()
        self.assertEqual(j.lidos, [2, 2])
        self.assertNotIn(2, j._secundario_mudo_ate)


if __name__ == "__main__":
    unittest.main()
