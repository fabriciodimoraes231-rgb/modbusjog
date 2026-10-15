"""Testes do catalogo de sensores e do campo sensor_tipo do Eixo.

Nao abrem janela: `ui.sensores` e `ui.eixo` nao dependem de Tk.

Rodar da pasta que contem jog_gui/:

    python -m unittest discover -s jog_gui/tests -t . -v
"""
import unittest

from jog_gui.str6 import VEL_MAX_PPS
from jog_gui.ui import sensores
from jog_gui.ui.eixo import VERSAO_CADASTRO, Eixo


class TestCatalogo(unittest.TestCase):
    """As invariantes do catalogo: padrao valido, procedencia e coerencia.

    Inclui a trava dos numeros de partida do UX954-WR, o sensor da bancada.
    """

    def test_o_padrao_existe_no_catalogo(self):
        # Eixo usa sensores.PADRAO como valor de fabrica do campo: se o nome
        # nao existisse, todo eixo novo nasceria apontando para nada.
        self.assertIn(sensores.PADRAO, sensores.SENSORES)

    def test_sem_sensor_existe_e_nao_tem_origem(self):
        self.assertIn(sensores.SEM_SENSOR, sensores.SENSORES)
        self.assertFalse(sensores.tem_origem(sensores.SEM_SENSOR))

    def test_todos_os_outros_tem_origem(self):
        for nome, s in sensores.SENSORES.items():
            if nome == sensores.SEM_SENSOR:
                continue
            with self.subTest(sensor=nome):
                self.assertTrue(s.tem_origem)

    def test_nomes_preserva_a_ordem_de_cadastro(self):
        self.assertEqual(sensores.nomes(), list(sensores.SENSORES))

    def test_nenhum_modelo_com_origem_esta_marcado_como_confirmado(self):
        # Trava de procedencia: confirmado=True significa numero MEDIDO nesta
        # bancada com este drive. Nenhum modelo tem: as velocidades vem da
        # faixa generica de homing em dois estagios. Medir o homing e o que
        # autoriza devolver o True -- e trocar este teste junto.
        confirmados = {n for n, s in sensores.SENSORES.items()
                       if s.confirmado and s.tem_origem}
        self.assertEqual(confirmados, set())

    def test_todo_sensor_tem_texto_de_fiacao(self):
        for nome, s in sensores.SENSORES.items():
            with self.subTest(sensor=nome):
                self.assertTrue(s.fiacao.strip())

    def test_sugeridos_traz_as_tres_chaves_do_card(self):
        for nome, s in sensores.SENSORES.items():
            with self.subTest(sensor=nome):
                self.assertEqual(set(s.sugeridos),
                                 {"home_filtro", "home_v_apr", "home_v_ras"})

    def test_sugeridos_dos_sensores_reais_sao_positivos(self):
        # Velocidade ou filtro zero num eixo com sensor significaria um homing
        # que nunca sai do lugar ou uma borda tomada de ruido.
        for nome, s in sensores.SENSORES.items():
            if not s.tem_origem:
                continue
            with self.subTest(sensor=nome):
                self.assertGreater(s.v_aproximacao, 0)
                self.assertGreater(s.v_rastejo, 0)
                self.assertGreater(s.filtro_ms, 0)

    def test_rastejo_nunca_e_maior_que_a_aproximacao(self):
        # O rastejo e o refino na borda: mais rapido que a aproximacao
        # inverteria o proposito das duas velocidades.
        for nome, s in sensores.SENSORES.items():
            if not s.tem_origem:
                continue
            with self.subTest(sensor=nome):
                self.assertLessEqual(s.v_rastejo, s.v_aproximacao)

    def test_valores_do_ux954_batem_com_o_documentado(self):
        # Filtro de partida da bancada; velocidades da faixa generica de
        # homing em dois estagios sobre o teto de VEL_MAX_PPS.
        s = sensores.obter(sensores.PADRAO)
        self.assertEqual(s.filtro_ms, 2)
        self.assertEqual(s.v_aproximacao, 6000)
        self.assertEqual(s.v_rastejo, 1000)

    def test_velocidades_dentro_da_faixa_de_homing_em_dois_estagios(self):
        # Aproximacao 10-20% da maxima, rastejo 2-5%, razao de 5:1 a 10:1.
        maxima = VEL_MAX_PPS
        for nome, s in sensores.SENSORES.items():
            if not s.tem_origem:
                continue
            with self.subTest(sensor=nome):
                self.assertLessEqual(s.v_aproximacao, 0.20 * maxima)
                self.assertGreaterEqual(s.v_aproximacao, 0.10 * maxima)
                self.assertLessEqual(s.v_rastejo, 0.05 * maxima)
                self.assertGreaterEqual(s.v_rastejo, 0.02 * maxima)
                razao = s.v_aproximacao / s.v_rastejo
                self.assertGreaterEqual(razao, 5)
                self.assertLessEqual(razao, 10)


class TestObter(unittest.TestCase):
    """`obter` nunca devolve None: nome desconhecido cai no padrao.

    Um eixos.json de versao anterior nao tem o campo, e um editado a mao pode
    trazer qualquer coisa -- nada disso pode derrubar a janela.
    """

    def test_devolve_o_sensor_pedido(self):
        self.assertEqual(sensores.obter(sensores.SEM_SENSOR).nome,
                         sensores.SEM_SENSOR)

    def test_nome_desconhecido_cai_no_padrao_sem_estourar(self):
        # eixos.json de versao anterior nao tem o campo, e um editado a mao
        # pode trazer qualquer coisa: nenhum dos dois pode derrubar a janela.
        for ruim in ("", "nao existe", None, 0, []):
            with self.subTest(valor=ruim):
                self.assertEqual(sensores.obter(ruim).nome, sensores.PADRAO)

    def test_tem_origem_de_nome_desconhecido_segue_o_padrao(self):
        self.assertTrue(sensores.tem_origem("nao existe"))


class TestCampoNoEixo(unittest.TestCase):
    """O campo `sensor_tipo` sobrevive ao ciclo Eixo -> JSON -> Eixo."""

    def test_eixo_novo_nasce_com_o_sensor_padrao(self):
        self.assertEqual(Eixo(1).config["sensor_tipo"], sensores.PADRAO)

    def test_sobrevive_ao_json(self):
        e = Eixo(3)
        e.atualizar({"sensor_tipo": sensores.SEM_SENSOR})
        volta = Eixo.de_json(e.para_json())
        self.assertEqual(volta.config["sensor_tipo"], sensores.SEM_SENSOR)

    def test_eixo_sem_o_campo_ganha_o_padrao(self):
        # Uma entrada editada a mao, sem o campo.
        sem_campo = {"id": 11, "apelido": "eixo 11", "config": {"jog_velocidade": 60}}
        self.assertEqual(Eixo.de_json(sem_campo).config["sensor_tipo"],
                         sensores.PADRAO)

    def test_cadastro_de_outra_versao_so_aproveita_id_apelido_e_sensor(self):
        # Outra versao tem outras unidades: uma velocidade ou um limite de la
        # significaria outra coisa aqui.
        antigo = {"id": 12, "apelido": "z", "config": {
            "sensor_tipo": sensores.SEM_SENSOR, "jog_velocidade": 60,
            "limite_pos": 5000}}
        e = Eixo.de_json(antigo, versao=VERSAO_CADASTRO - 1)
        self.assertEqual((e.slave, e.apelido), (12, "z"))
        self.assertEqual(e.config["sensor_tipo"], sensores.SEM_SENSOR)
        self.assertEqual(e.config["jog_velocidade"], Eixo(1).config["jog_velocidade"])
        self.assertEqual(e.config["limite_pos"], 0)

    def test_valor_invalido_no_arquivo_nao_derruba_o_eixo(self):
        e = Eixo(4)
        e.atualizar({"sensor_tipo": 12345})
        # atualizar() aceita como texto; quem protege a interface e obter().
        self.assertEqual(sensores.obter(e.config["sensor_tipo"]).nome,
                         sensores.PADRAO)


    def test_a_configuracao_de_movimento_traz_a_origem_do_catalogo(self):
        # A recusa de homing e de limites num eixo sem sensor e da camada de
        # movimento; e daqui que ela fica sabendo.
        e = Eixo(5)
        self.assertTrue(e.config_movimento().sensor_tem_origem)
        e.atualizar({"sensor_tipo": sensores.SEM_SENSOR})
        self.assertFalse(e.config_movimento().sensor_tem_origem)


if __name__ == "__main__":
    unittest.main()
