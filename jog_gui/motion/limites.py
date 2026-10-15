"""Faixa de trabalho do eixo em pulsos -- funcoes puras, sem I/O e sem tela.

Os limites sao contados em PULSOS a partir do zero, e o zero e onde o sensor de
origem e acionado. Nada aqui vai para a memoria do drive: e requisito do
projeto nao envolver a gravacao de parametros do STR6 nessa funcao.

Os sentidos chegam como texto (FRENTE/TRAS) e so sao comparados entre si, entao
nada aqui depende de qual comando do drive corresponde a cada um.
"""


def faixa(limite_neg, limite_pos):
    """Faixa permitida em pulsos: (minimo negativo, maximo positivo).

    O `limite_neg` e guardado como valor positivo na configuracao e aplicado
    como negativo -- e o que a tela pede ao operador ("quantos pulsos pode
    descer abaixo do zero").
    """
    return (-abs(limite_neg), abs(limite_pos))


def margens(neg, pmax, margem):
    """Antecipacao efetiva de cada lado: no maximo metade do lado.

    Com o lado positivo curto (ex.: limite + de 32 pulsos) e uma antecipacao
    maior que ele, a conta "pos >= pmax - margem" daria verdadeira na origem e
    bloquearia o sentido + em qualquer posicao. Limitar por lado mantem a folga
    de desaceleracao sem eliminar o curso.
    """
    margem = max(0, margem)
    return (min(margem, abs(neg) // 2), min(margem, abs(pmax) // 2))


def limite_atingido(pos, sentido, neg, pmax, margem, sent_pos):
    """Descreve o limite atingido no sentido em curso, ou None.

    Args:
        pos: posicao atual em pulsos.
        sentido: o sentido do movimento em curso.
        neg, pmax: a faixa, como `faixa` devolve.
        margem: antecipacao em pulsos (limitada por `margens`).
        sent_pos: qual sentido soma pulsos neste eixo, do cadastro.

    Recebe a faixa por parametro de proposito: quem vigia um movimento leu a
    faixa uma vez, no inicio, e nao deve reconsultar configuracao a cada ciclo.
    """
    m_neg, m_pos = margens(neg, pmax, margem)
    sobe = (sentido == sent_pos)
    if sobe and pos >= pmax - m_pos:
        return "Limite + atingido (posicao {}, limite {})".format(pos, pmax)
    if not sobe and pos <= neg + m_neg:
        return "Limite - atingido (posicao {}, limite {})".format(pos, neg)
    return None


def violacao(pos, neg, pmax):
    """Quantos pulsos a posicao esta fora da faixa (0 = dentro)."""
    return max(0, pos - pmax, neg - pos)


def passo_permitido(p0, passo, neg, pmax):
    """Motivo para recusar o passo, ou None se liberado.

    Com o eixo ja fora da faixa, um passo que o traga de volta e liberado:
    recusar qualquer movimento deixaria o JOG como unico jeito de voltar para
    dentro do curso, e o card ficaria inutilizavel.
    """
    destino = p0 + passo
    if violacao(destino, neg, pmax) == 0:
        return None
    if violacao(destino, neg, pmax) < violacao(p0, neg, pmax):
        return None
    return ("passo de {:+d} levaria o eixo a {} pulsos, fora da faixa "
            "({} a {})".format(passo, destino, neg, pmax))


def faixa_vazia(neg, pmax):
    """True quando nao ha o que proteger: faixa de tamanho zero ou negativo.

    Um eixo nunca configurado entra com a faixa zerada, e nesse estado os
    limites nao podem valer -- sem faixa, `limite_atingido` bloquearia os dois
    sentidos na origem.
    """
    return (pmax - neg) <= 0
