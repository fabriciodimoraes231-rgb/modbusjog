"""Trava estrutural dos mixins da janela.

`JogApp` herda de um mixin por card. O README avisa do risco: um nome
definido em dois mixins seria resolvido em silencio pela ordem de heranca, e o
card perdedor passaria a chamar o metodo do outro sem nenhum erro. Hoje nao ha
colisao nenhuma, e este teste existe para que continue assim -- principalmente
enquanto os modulos grandes (`curso`, `homing`, `drives`) forem divididos.

Nao abre janela: inspeciona as CLASSES, nao instancias. `import tkinter` basta,
e nao e preciso display nem drive.

Rodar da pasta que contem jog_gui/:

    python -m unittest discover -s jog_gui/tests -t . -v
"""
import inspect
import unittest

from jog_gui.ui.app import JogApp
from jog_gui.ui.conexao import ConexaoMixin
from jog_gui.ui.corrente import CorrenteMixin
from jog_gui.ui.curso import CursoMixin
from jog_gui.ui.drives import DrivesMixin
from jog_gui.ui.homing import HomingMixin
from jog_gui.ui.inspetor import InspetorMixin
from jog_gui.ui.jog import JogMixin
from jog_gui.ui.log import LogMixin
from jog_gui.ui.motor import MotorMixin
from jog_gui.ui.status import StatusMixin

MIXINS = (ConexaoMixin, CorrenteMixin, CursoMixin, DrivesMixin, HomingMixin,
          InspetorMixin, JogMixin, LogMixin, MotorMixin, StatusMixin)


def _proprios(cls):
    """Nomes definidos NA classe (metodos e atributos de classe), sem dunder."""
    return {n for n in vars(cls) if not n.startswith("__")}


class TestSemColisaoEntreMixins(unittest.TestCase):
    """Nenhum nome pode ser definido por dois mixins, e todos entram na janela.

    Uma colisao nao daria erro: a MRO escolheria um dos dois em silencio e o
    card perdedor passaria a chamar o metodo do outro.
    """

    def test_nenhum_nome_e_definido_por_dois_mixins(self):
        dono = {}
        colisoes = {}
        for cls in MIXINS:
            for nome in _proprios(cls):
                if nome in dono:
                    colisoes.setdefault(nome, [dono[nome]]).append(cls.__name__)
                else:
                    dono[nome] = cls.__name__
        self.assertEqual(
            colisoes, {},
            "nome(s) definidos em mais de um mixin -- a ordem de heranca "
            "decidiria em silencio qual vale: {}".format(colisoes))

    def test_todo_mixin_entra_na_janela(self):
        # Um mixin fora da lista de bases de JogApp nao seria erro nenhum:
        # o card simplesmente sumiria da tela sem aviso.
        mro = set(JogApp.__mro__)
        for cls in MIXINS:
            with self.subTest(mixin=cls.__name__):
                self.assertIn(cls, mro)

    def test_a_lista_deste_teste_cobre_as_bases_reais(self):
        # Se alguem criar um mixin novo e esquecer de registra-lo aqui, a trava
        # de colisao passaria a ignora-lo justamente quando ela mais serve.
        bases = {b for b in JogApp.__bases__
                 if b.__name__.endswith("Mixin")}
        self.assertEqual(bases, set(MIXINS))


class TestContratoDosCards(unittest.TestCase):
    """Cada mixin monta o seu card, e a janela chama todos.

    Um card cujo _card_* deixasse de ser chamado em _build_ui sumiria da tela
    sem erro nenhum -- e os botoes que ele cria, referenciados por nome em
    _set_connected, so quebrariam na hora de conectar.
    """

    def test_cada_mixin_monta_o_seu_card(self):
        # LogMixin e DrivesMixin montam areas, nao um card no mesmo padrao.
        sem_card = {"LogMixin", "DrivesMixin"}
        for cls in MIXINS:
            if cls.__name__ in sem_card:
                continue
            with self.subTest(mixin=cls.__name__):
                metodos = [n for n in _proprios(cls) if n.startswith("_card_")]
                self.assertTrue(
                    metodos,
                    "{} nao define nenhum _card_*".format(cls.__name__))

    def test_os_metodos_de_card_sao_chamados_pela_janela(self):
        fonte = inspect.getsource(JogApp)
        for cls in MIXINS:
            for nome in _proprios(cls):
                if not nome.startswith("_card_"):
                    continue
                with self.subTest(card=nome):
                    self.assertIn(
                        "self.{}(".format(nome), fonte,
                        "{} existe mas a janela nunca o monta".format(nome))


class TestDependenciaDeSensor(unittest.TestCase):
    """O bloqueio do eixo sem sensor depende de nomes que precisam existir."""

    def test_os_botoes_listados_sao_criados_no_card(self):
        fonte = inspect.getsource(HomingMixin)
        for nome in HomingMixin._BTNS_DEPENDEM_SENSOR:
            with self.subTest(botao=nome):
                self.assertIn("self.{} = tk.Button".format(nome), fonte)

    def test_status_consulta_a_origem_pelo_metodo_do_homing(self):
        # _eixo_tem_origem vive em HomingMixin e e usado pelo monitor para nao
        # pintar estado de sensor num eixo sem sensor. A trava de colisao acima
        # garante que so existe uma definicao dele.
        self.assertIn("_eixo_tem_origem", _proprios(HomingMixin))
        self.assertIn("_eixo_tem_origem", inspect.getsource(StatusMixin))


if __name__ == "__main__":
    unittest.main()
