"""Rotina de movimento com perfil de velocidade parametrizavel."""

import time

from jog_gui.str6 import (
    ID_NEMA1_SOCKET,
    ID_SPIN_MOTOR,
    Drive,
    DriveNaoConfirmou,
    conectar,
    desarmar_todos,
)

from .pick_place import graus_para_pulsos, rpm_para_pps


def inicializar_bancada(client):
    """Passo 1: desabilita todos os motores assim que o software abre."""
    print("Inicializando barramento e soltando eixos...")
    falhas = desarmar_todos(client)
    if falhas:
        print(f"*** Drives sem desabilitacao confirmada: {falhas}. "
              "Verifique-os manualmente!")
    else:
        print("Motores desabilitados e seguros contra aquecimento.")


def executar_movimento_seguro(client, slave_id, graus, rampa_ms, vel_rpm, tempo_espera):
    """Passo 2: habilita, move com o perfil pedido e desabilita.

    A desabilitacao acontece no finally, garantindo que o motor nunca fique
    energizado se ocorrer erro ou interrupcao (Ctrl+C).

    O STR6 recebe aceleracao em pulsos/s^2 (62~67); `rampa_ms` e o tempo para
    ir de 0 ate a velocidade, e a conversao fica em str6.perfil_movimento.

    Levanta DriveNaoConfirmou se alguma escrita nao for confirmada, para que o
    roteiro nao siga para o proximo movimento as cegas.
    """
    drive = Drive(client, slave_id)
    try:
        print(f"\n--- [Drive {slave_id}] Preparando movimento ---")

        drive.armar()
        time.sleep(0.1)

        drive.mover_relativo(graus_para_pulsos(graus), rpm_para_pps(vel_rpm),
                             rampa_ms=rampa_ms)

        time.sleep(tempo_espera)

        print(f"[Drive {slave_id}] Movimento concluido.")

    finally:
        try:
            drive.desarmar()
            print(f"[Drive {slave_id}] Finalizado e desabilitado.")
        except Exception as e:
            print(f"[Drive {slave_id}] ATENCAO: falha ao desabilitar ({e}). "
                  "Verifique o motor manualmente!")


def main():
    """Roteiro de bancada: desarma tudo, testa o soquete e depois o motor spin.

    Serve para conferir o perfil de velocidade (rampa e regime) sem o ciclo de
    pick and place inteiro: os parametros de cada movimento vao explicitos na
    chamada, para serem mexidos aqui mesmo.
    """
    client = conectar(descricao=__doc__)
    if client is None:
        return

    try:
        # 1. Garante que ninguem vai esquentar se a fonte acabou de ser ligada
        inicializar_bancada(client)
        time.sleep(1.0)

        # 2. Teste do Drive 1 (soquete): 1/4 de volta para um lado e de volta
        executar_movimento_seguro(
            client, slave_id=ID_NEMA1_SOCKET, graus=-90,
            rampa_ms=300, vel_rpm=120, tempo_espera=1.5
        )

        time.sleep(0.5)

        executar_movimento_seguro(
            client, slave_id=ID_NEMA1_SOCKET, graus=90,
            rampa_ms=300, vel_rpm=120, tempo_espera=1.5
        )

        time.sleep(0.5)

        # 3. Teste do Motor Spin (Drive 3): volta completa, com dinamica suave
        # por causa do atrito.
        executar_movimento_seguro(
            client, slave_id=ID_SPIN_MOTOR, graus=360,
            rampa_ms=500, vel_rpm=40, tempo_espera=2.5
        )

    except KeyboardInterrupt:
        print("\nInterrompido pelo usuario. Desabilitando motores por seguranca...")
    except DriveNaoConfirmou as e:
        print(f"\n*** ROTEIRO ABORTADO: {e}")
    finally:
        # Rede de seguranca final: desabilita todos os drives do barramento,
        # inclusive os que este roteiro nao movimentou.
        falhas = desarmar_todos(client)
        if falhas:
            print(f"\n*** ATENCAO: drives sem desabilitacao confirmada: {falhas}")
            print("*** Pode haver motor energizado. Confira na bancada e, se "
                  "necessario, corte a energia.")
        client.close()


if __name__ == "__main__":
    main()
