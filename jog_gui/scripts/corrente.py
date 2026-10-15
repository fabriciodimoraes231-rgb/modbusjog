"""Ajusta malha e corrente de pico dos tres drives e grava na memoria.

As correntes ficam na "zona de ajuste" de str6/config.py (CORRENTES_MA), num so
lugar para que este script e desarme_inicial.py nunca divirjam.
"""

import time

from jog_gui.str6 import (
    CORRENTES_MA,
    Drive,
    DriveNaoConfirmou,
    TODOS_OS_DRIVES,
    conectar,
)


def ajustar_corrente_geral():
    """Grava malha (MALHA_PADRAO) + corrente de pico em cada drive do barramento.

    Percorre TODOS_OS_DRIVES em ordem, chamando `Drive.configurar`, que escreve
    o 24 (malha) e o 0 (corrente de pico, mA) e salva (90 = 1, conferido pela
    leitura do proprio 90). Uma escrita nao confirmada aborta o laco: os drives
    ja gravados permanecem gravados, os seguintes mantem a configuracao
    anterior.

    Nao movimenta nada e nao habilita motor -- so configura.
    """
    client = conectar(descricao=__doc__)
    if client is None:
        return

    try:
        for device_id in TODOS_OS_DRIVES:
            Drive(client, device_id).configurar(CORRENTES_MA[device_id])
            time.sleep(0.2)

        print("\nConfiguracoes de corrente gravadas nos {} drives!".format(
            len(TODOS_OS_DRIVES)))

    except DriveNaoConfirmou as e:
        print(f"\n*** AJUSTE ABORTADO: {e}")
        print("Os drives configurados antes da falha ja estao gravados; "
              "os seguintes mantem a configuracao anterior.")
    except Exception as e:
        print(f"Erro Modbus durante o ajuste: {e}")
    finally:
        client.close()


if __name__ == "__main__":
    ajustar_corrente_geral()
