"""Configura correntes/malha dos drives e os deixa desabilitados (livres).

Rode antes de energizar ou mexer no conjunto. As correntes ficam na "zona de
ajuste" de str6/config.py (CORRENTES_MA).
"""

import time

from jog_gui.str6 import (
    CORRENTES_MA,
    Drive,
    DriveNaoConfirmou,
    TODOS_OS_DRIVES,
    conectar,
    desarmar_todos,
)


def configurar_e_desarmar():
    """Configura os drives e, aconteca o que acontecer, desabilita todos.

    O desarme e a funcao de seguranca deste script e por isso mora num
    `finally`: mesmo que a gravacao das correntes aborte no meio, todos os
    eixos saem livres. Os drives que nao confirmarem sao nomeados no
    terminal -- um motor energizado que ninguem viu e o pior desfecho.
    """
    client = conectar(descricao=__doc__)
    if client is None:
        return

    try:
        try:
            print("=== 1. CONFIGURANDO CORRENTES E MALHA ===")
            for device_id in TODOS_OS_DRIVES:
                Drive(client, device_id).configurar(CORRENTES_MA[device_id])
                time.sleep(0.2)
        finally:
            # O desarme e a funcao de seguranca deste script: acontece mesmo
            # que a configuracao acima tenha falhado no meio.
            print("\n=== 2. DESABILITANDO OS MOTORES ===")
            falhas = desarmar_todos(client)
            if falhas:
                print(f"\n*** Drives sem desabilitacao confirmada: {falhas}")
                print("*** NAO considere o conjunto seguro. Verifique a fiacao, "
                      "os IDs e, se necessario, corte a energia.")
            else:
                print("Desabilitacao confirmada: os motores estao livres.")

    except DriveNaoConfirmou as e:
        print(f"\n*** CONFIGURACAO ABORTADA: {e}")
    except Exception as e:
        print(f"Erro Modbus durante a execucao: {e}")
    finally:
        client.close()


if __name__ == "__main__":
    configurar_e_desarmar()
