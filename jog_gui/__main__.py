"""STR6-RS485 - Controle JOG via Modbus RTU (RS485)
==================================================
Funcionalidades:
  - Selecionar porta COM e baud rate
  - Conectar / Desconectar
  - Varios eixos no mesmo barramento, um ativo por vez
  - MOTOR ON / MOTOR OFF (reg 6) e limpar falha (reg 93)
  - JOG continuo para FRENTE / TRAS (reg 70 = 3/4), com watchdog
  - Monitor em tempo real (status 75, alarme 115, posicao 39/40, encoder)
  - Homing pelo sensor numa entrada de limite (IN1/IN2): retorno a zero do
    drive (reg 71) ou busca por software
  - Limites de curso por software e posicionamento por pulsos
  - Log de comunicacao hexadecimal

Executar, da pasta que CONTEM jog_gui/:

    python -m jog_gui

ou, de qualquer pasta, apontando para este arquivo:

    python caminho/para/jog_gui/__main__.py
"""

if __package__ in (None, ""):
    # Rodado como script (python __main__.py, ou o botao Run do editor): o
    # Python so poe ESTA pasta no caminho de importacao, e o pacote jog_gui
    # precisa da pasta de cima. Sem isto: "No module named 'jog_gui'".
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jog_gui.ui import JogApp, apply_styles


def main():
    """Abre a janela."""
    app = JogApp()
    apply_styles()
    app.mainloop()


if __name__ == "__main__":
    main()
