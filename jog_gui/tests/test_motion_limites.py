"""Testes de motion.limites -- funcoes puras, nao precisam de drive nem porta.

Rodar da pasta que contem jog_gui/:

    python -m unittest discover -s jog_gui/tests -t . -v

Cada teste aqui corresponde a uma regra de faixa de curso registrada em
comentario em motion/limites.py.
"""
import unittest

from jog_gui.motion import FRENTE, TRAS, limites


class TestFaixa(unittest.TestCase):
    """O limite negativo e guardado positivo e aplicado como negativo."""

    def test_negativo_e_aplicado_com_sinal(self):
        self.assertEqual(limites.faixa(60, 160), (-60, 160))

    def test_aceita_negativo_ja_com_sinal(self):
        """Quem editar o JSON a mao pode escrever -60; o resultado e o mesmo."""
        self.assertEqual(limites.faixa(-60, 160), (-60, 160))

    def test_faixa_zerada_e_vazia(self):
        """Eixo nunca configurado entra com a faixa zerada."""
        self.assertTrue(limites.faixa_vazia(0, 0))

    def test_faixa_com_curso_nao_e_vazia(self):
        self.assertFalse(limites.faixa_vazia(-60, 160))


class TestMargens(unittest.TestCase):
    """A antecipacao nao pode comer o curso inteiro de um lado curto.

    Caso real: com o limite + de 32 pulsos e a antecipacao no valor de bancada
    (200), a conta "pos >= pmax - margem" dava verdadeira na origem e bloqueava
    o sentido + em QUALQUER posicao.
    """

    def test_margem_limitada_a_metade_do_lado(self):
        m_neg, m_pos = limites.margens(-60, 32, 200)
        self.assertEqual(m_pos, 16)     # metade de 32, nao 200
        self.assertEqual(m_neg, 30)     # metade de 60

    def test_margem_pequena_passa_inteira(self):
        self.assertEqual(limites.margens(-1000, 1000, 200), (200, 200))

    def test_margem_negativa_vira_zero(self):
        self.assertEqual(limites.margens(-100, 100, -5), (0, 0))

    def test_lado_curto_nao_bloqueia_a_origem(self):
        """A regressao que o limite por lado conserta, verificada de ponta."""
        self.assertIsNone(
            limites.limite_atingido(0, FRENTE, -60, 32, 200, FRENTE))


class TestLimiteAtingido(unittest.TestCase):
    """Qual limite foi atingido depende do sentido do movimento em curso."""

    FAIXA = (-60, 160)
    MARGEM = 0

    def _atingido(self, pos, sentido, sent_pos=FRENTE):
        neg, pmax = self.FAIXA
        return limites.limite_atingido(pos, sentido, neg, pmax, self.MARGEM,
                                       sent_pos)

    def test_no_meio_da_faixa_nada_atingido(self):
        self.assertIsNone(self._atingido(50, FRENTE))
        self.assertIsNone(self._atingido(50, TRAS))

    def test_limite_positivo_no_sentido_que_soma(self):
        motivo = self._atingido(160, FRENTE)
        self.assertIsNotNone(motivo)
        self.assertIn("Limite +", motivo)

    def test_limite_positivo_nao_bloqueia_o_sentido_oposto(self):
        """No limite +, ainda se pode voltar."""
        self.assertIsNone(self._atingido(160, TRAS))

    def test_limite_negativo_no_sentido_que_subtrai(self):
        motivo = self._atingido(-60, TRAS)
        self.assertIsNotNone(motivo)
        self.assertIn("Limite -", motivo)

    def test_sentido_positivo_invertido_troca_os_lados(self):
        """Com sentido_pos = TRAS, quem soma pulsos e o TRAS."""
        motivo = limites.limite_atingido(160, TRAS, -60, 160, 0, TRAS)
        self.assertIn("Limite +", motivo)
        self.assertIsNone(limites.limite_atingido(160, FRENTE, -60, 160, 0, TRAS))

    def test_antecipacao_bloqueia_antes_do_limite(self):
        """A antecipacao cobre a desaceleracao da parada por software."""
        neg, pmax = self.FAIXA
        self.assertIsNotNone(
            limites.limite_atingido(150, FRENTE, neg, pmax, 20, FRENTE))
        self.assertIsNone(
            limites.limite_atingido(150, FRENTE, neg, pmax, 0, FRENTE))


class TestViolacao(unittest.TestCase):
    """Quantos pulsos a posicao esta fora da faixa."""

    def test_dentro_da_faixa_nao_viola(self):
        self.assertEqual(limites.violacao(50, -60, 160), 0)

    def test_nas_bordas_nao_viola(self):
        self.assertEqual(limites.violacao(-60, -60, 160), 0)
        self.assertEqual(limites.violacao(160, -60, 160), 0)

    def test_acima_do_maximo(self):
        self.assertEqual(limites.violacao(200, -60, 160), 40)

    def test_abaixo_do_minimo(self):
        self.assertEqual(limites.violacao(-100, -60, 160), 40)


class TestPassoPermitido(unittest.TestCase):
    """Com o eixo fora da faixa, um passo que o traga de volta e liberado.

    Antes qualquer movimento era recusado, e o unico jeito de voltar para
    dentro do curso era o JOG -- o card ficava inutilizavel.
    """

    FAIXA = (-60, 160)

    def _permitido(self, p0, passo):
        neg, pmax = self.FAIXA
        return limites.passo_permitido(p0, passo, neg, pmax)

    def test_passo_dentro_da_faixa_e_liberado(self):
        self.assertIsNone(self._permitido(0, 100))

    def test_passo_que_sai_da_faixa_e_recusado(self):
        motivo = self._permitido(100, 100)
        self.assertIsNotNone(motivo)
        self.assertIn("fora da faixa", motivo)

    def test_fora_da_faixa_passo_que_volta_e_liberado(self):
        """Posicao 200 (40 fora), passo -50 -> 150: dentro. Liberado."""
        self.assertIsNone(self._permitido(200, -50))

    def test_fora_da_faixa_passo_que_aproxima_e_liberado(self):
        """Posicao 200 (40 fora), passo -20 -> 180 (20 fora): melhorou."""
        self.assertIsNone(self._permitido(200, -20))

    def test_fora_da_faixa_passo_que_afasta_e_recusado(self):
        """Posicao 200 (40 fora), passo +20 -> 220 (60 fora): piorou."""
        self.assertIsNotNone(self._permitido(200, 20))

    def test_fora_da_faixa_passo_que_nao_melhora_e_recusado(self):
        """Passo zero nao melhora nada, e nao pode passar por liberado."""
        self.assertIsNotNone(self._permitido(200, 0))

    def test_passo_exatamente_ate_a_borda_e_liberado(self):
        self.assertIsNone(self._permitido(60, 100))   # 60 + 100 = 160 = pmax


if __name__ == "__main__":
    unittest.main()
