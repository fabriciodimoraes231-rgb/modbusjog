# jog_gui — interface de controle do STR6-RS485

Interface gráfica para operar drives de passo de malha fechada **STR6-RS485**
(Kalatec) por Modbus RTU (RS-485): JOG, configuração do drive, homing pelo
sensor de origem e limites de curso do eixo em pulsos.

Referência única do hardware: `Manual-DRIVER-STR6-RS485.pdf` (Kalatec, rev. 1.0).
O manual é do fabricante e não é distribuído neste repositório. Toda página
citada neste documento é desse manual.

> **Validação:** esta versão foi escrita a partir do manual e testada só contra
> um drive simulado. Antes de usar o equipamento em processo controlado, ela
> precisa passar por ensaio em bancada e por revisão de pessoa qualificada,
> distinta de quem a redigiu — ver [Pontos em aberto](#pontos-em-aberto).

| Arquivo | O que é |
|---|---|
| `__main__.py` | ponto de entrada — só abre a janela (`python -m jog_gui`) |
| `str6/` | a biblioteca que fala com o drive — compartilhada com os scripts |
| `motion/` | a lógica de movimento de um eixo, **sem interface** |
| `ui/` | a interface: um módulo por card da tela |
| `scripts/` | rotinas de bancada (pick and place, corrente, desabilitação) |
| `tests/` | testes sem drive, sem porta e sem display |
| `eixos.json` | o cadastro dos eixos e toda a configuração de cada um |

## Como rodar

Da pasta que **contém** `jog_gui/`:

```powershell
python -m jog_gui
```

Dependência: `pyserial`. A porta COM é escolhida na própria tela — não há
porta padrão.

Testes:

```powershell
python -m unittest discover -s jog_gui/tests -t . -v
```

## Arquitetura

### `str6/` — o drive

| Módulo | Conteúdo |
|---|---|
| `registradores.py` | endereços `REG_*` (em **decimal**, como no manual), comandos e bits — **nenhum literal de registrador fora daqui** |
| `config.py` | zona de ajuste: baud rate, IDs, correntes, teto de velocidade, rampa |
| `protocolo.py` | CRC, montagem e parse de quadros, palavras de 32 bits — funções puras |
| `barramento.py` | a porta serial compartilhada, o lock e a transação validada |
| `drive.py` | um drive: escritas verificadas, perfil de movimento, salvamento |

**Valores de 32 bits** (velocidade, aceleração, curso, contador) ocupam dois
registradores com a palavra **baixa no endereço menor** — é o que o exemplo de
FC16 do manual mostra (p. 19: 14464 em 68 e 1 em 69 = 80 000 pulsos). Os testes
de protocolo usam os quadros desse exemplo como vetores.

### `motion/` — a regra de movimento

| Módulo | Conteúdo |
|---|---|
| `config.py` | `ConfigEixo`: os ajustes de um eixo, lidos do `eixos.json` |
| `limites.py` | faixa de trabalho em pulsos — funções puras, sem I/O |
| `eixo.py` | `EixoMovimento`: habilitar, jog, passo, `ir_para`, homing, parar |

É a única camada que junta o mapa de registradores com o drive. A interface
**usa esta camada para todo movimento** — não há uma segunda cópia da lógica nos
cards. Também dá para exercitar um eixo por script:

```python
from jog_gui.str6 import conectar, Drive
from jog_gui.motion import ConfigEixo, EixoMovimento

bus = conectar()
eixo = EixoMovimento(Drive(bus, 1), ConfigEixo(1, "socket"), log=print)
try:
    eixo.armar()
    r = eixo.passo(+1, pulsos=1500)
    print(r.ok, r.causa, r.detalhe)
finally:
    eixo.desarmar()
    bus.close()
```

Nenhuma operação devolve apenas `True`/`False`: todas devolvem um `Resultado`
com `ok`, `causa` (enumerada) e `detalhe`. Pedido inválido, recusado **antes**
de qualquer escrita, levanta `MovimentoRecusado`. `_dormir()` e `_agora()` são
os únicos pontos de espera e de relógio, para os testes trocarem por um relógio
virtual.

### `ui/` — a interface

| Módulo | Conteúdo |
|---|---|
| `app.py` | a janela `JogApp`: layout em três colunas, ciclo de vida |
| `tema.py` | cores, fontes, estilos ttk e formatação de corrente/velocidade |
| `conexao.py` | porta, baud rate, ping e as primitivas de transação |
| `drives.py` | cadastro dos eixos, varredura, barra de visão geral, parada geral |
| `eixo.py` | a classe `Eixo`: o estado que pertence a um drive |
| `motor.py` | habilitar/desabilitar e limpar falha |
| `corrente.py` | configuração do drive: corrente, standby, malha, subdivisão, ganhos |
| `jog.py` | jog contínuo, watchdog e a fila de movimento |
| `status.py` | monitor periódico |
| `sensores.py` | catálogo dos modelos de sensor de origem |
| `homing.py` | entrada do sensor (IN1/IN2), teste do sensor e retorno ao zero |
| `curso.py` | faixa de trabalho em pulsos e movimentação por pulsos |
| `inspetor.py` | lê e vigia um registrador qualquer |
| `log.py` | o painel de log hexadecimal |

Cada card é um **mixin** e `JogApp` herda de todos. Um nome definido em dois
mixins seria resolvido em silêncio pela ordem de herança; `tests/test_mixins.py`
trava isso.

## Cards da interface

| Card | Função |
|---|---|
| EIXOS DO BARRAMENTO | cadastro (ID + apelido), varredura de 1 a 31 |
| CONEXÃO RS485 | porta, baud rate e o eixo ativo |
| MOTOR | habilita/desabilita (reg 6), limpa falha (reg 93), trava do último degrau da parada |
| CONFIGURAÇÃO DO DRIVE | corrente de pico (0), pulsos/volta (1), standby (2, 3), autoajuste e Kp/Ki (13, 15, 16), malha (24) |
| CONTROLE JOG | sentido FRENTE/TRÁS, velocidade em pulsos/s, rampa e o botão de JOG contínuo |
| STATUS DO DRIVE | status (75), alarme (115), enable (6), contador (39/40), encoder (41/42), tensão (48), corrente efetiva (22) |
| HOMING | modelo e entrada do sensor, nível (73), filtro (74), teste do sensor, retorno ao zero |
| CURSO E LIMITES | faixa de trabalho, jog por pulsos, posicionamento |
| INSPETOR DE REGISTRADOR | lê/vigia um endereço (decimal, como no manual) |
| LOG HEX MODBUS | toda escrita, quadro a quadro, e os descartes |

## Endereçamento e chaves DIP

Manual p. 11–12. O endereço vem de **S1~S5** e só vale depois de religar o drive:
`ID = 1·S1 + 2·S2 + 4·S3 + 8·S4 + 16·S5`, com **on = 0 e off = 1**.

- **S1~S5 todos em ON não é o endereço 1** — é o "reservado (padrão)", ID 0
  (broadcast). Para o ID 1: S1 off, S2~S5 on.
- **SW6/SW7** escolhem o baud: on/on = 9600 (padrão), off/on = 19200,
  on/off = 38400, off/off = 115200. Todos os drives da linha precisam do mesmo.
- **SW8 on** liga o resistor de terminação — obrigatório no drive da ponta da rede.
- Por software o manual aceita ID até 255; a tela aceita 1~247 (o Modbus RTU
  reserva 248~255) e a varredura cobre 1~31, a faixa dos DIP.

A conexão faz um *ping* lendo o reg 31 (o drive devolve o próprio ID), a tensão
do barramento (48), a corrente efetiva (22) e os pulsos por volta (1).

## Como o eixo é movimentado

Tudo em `motion/eixo.py` (manual p. 14–15):

- **Perfil** em 62~69 — desaceleração, velocidade, aceleração e curso, 32 bits
  cada — num **único FC16**. A rampa é configurada em **ms** (tempo de 0 até a
  velocidade) e convertida em pulsos/s² por `str6.perfil_movimento`.
- **Comando** em 70: 1/2 comprimento fixo para frente/trás, 3/4 contínuo,
  0 desacelera até parar, 5 para imediatamente. Depois de aceito o registrador
  volta sozinho para 6, então repetir o mesmo comando dispara de novo.
- **JOG**: contínuo (3/4), parada por software. A vigilância lê status, alarme
  e posição a cada ciclo e para o eixo na borda da faixa — daí a `Antecipação`.
- **Jog por pulsos** e **Ir para a posição**: comprimento fixo (1/2) em modo
  incremental (72 = 0). O drive desacelera e para sozinho; o que sobra de erro
  é corrigido em até duas tentativas.
- O fim de um movimento exige o eixo **parado** em duas leituras e, além disso,
  o bit 7 do status desligado **ou** a posição no destino (ver pontos em aberto).
- **Sentido de +**: qual comando (FRENTE ou TRÁS) **soma** pulsos no contador.
  O botão *Detectar sentido +* descobre girando ~1 s para FRENTE. Um passo "+"
  sai sempre no sentido que soma, então segue o contador e não o rótulo.

Velocidades em **pulsos/s** em toda a interface, com o equivalente em rpm só
para leitura (depende dos pulsos por volta do reg 1). Teto: `VEL_MAX_PPS`
(40 000 p/s = 400 rpm a 6000 pulsos/volta), em `str6/config.py`.

## Configuração do drive

O card **CONFIGURAÇÃO DO DRIVE** lê e grava, e **toda gravação termina em
"Salvar parâmetros" (90 = 1) e em leitura de conferência**. O drive informa o
fim do salvamento pela leitura do próprio 90 (manual p. 16), então a rotina
pergunta em vez de esperar um tempo fixo.

**O que cada etapa prova:**

| Etapa | Prova | Não prova |
|---|---|---|
| Escrita confirmada (eco do FC06) | o quadro chegou | que o drive aplicou o valor |
| Releitura logo após cada escrita | o drive aceitou o valor | que ele foi salvo |
| 90 lido em 1 | o drive diz que o salvamento terminou | que o 1 é **deste** salvamento (ver ponto em aberto 9) |
| Releitura logo após salvar | o valor está na memória de trabalho | que sobrevive a desligar o drive |
| **Testar gravação (religar drive)** | o valor voltou depois de faltar alimentação | — |

- **Gravar e Salvar** só roda com o motor desabilitado (MOTOR OFF) e nada em
  movimento. Na bancada, o drive ecoou a escrita do reg 0 com o motor
  habilitado e manteve o valor antigo; se a causa é o motor habilitado ainda
  não está confirmado. O monitor é pausado durante a gravação e retomado no fim.
- Se **qualquer** escrita for recusada (exceção ou silêncio), o salvamento
  **não é feito**: salvar levaria para a memória uma configuração pela metade
  (por exemplo, a malha nova com a corrente antiga). O que o drive aceitou vale
  só até ele ser desligado.
- Se o drive ecoar a escrita mas a releitura mostrar o valor antigo, o resto
  **é salvo** e o log nomeia o registrador que ficou com o valor do drive. Na
  bancada o reg 0 nunca aceita; barrar o salvamento por ele fazia todos os
  outros valores se perderem ao religar.
- A espera pelo 90 conta **consultas** (uma a cada 0,2 s, `ESPERA_SALVAR` ao
  todo), não relógio: tempo na fila do barramento não esgota o prazo.
- Se o 90 já estava em 1 antes do pedido e continua em 1 sem passar por 0, o
  log avisa que a confirmação é ambígua.
- **Testar gravação** só roda com o motor desabilitado e nada em movimento. Lê
  os 8 registradores da tabela abaixo, pede para **desligar e religar a
  alimentação** do drive (prazo de 120 s), percebe o religamento pelo próprio
  barramento — só conta como desligado depois de 1 s seguido sem resposta — e
  compara registrador por registrador. O monitor é pausado durante o teste e
  retomado no fim. Depois do teste o zero do eixo deixa de valer. O log
  registra também o 90 e o 6 lidos após religar, que ajudam a fechar os
  pontos em aberto 1 e 9.

| Registrador | Campo | Faixa / fábrica |
|---|---|---|
| 0 | corrente de pico | 50~7800 mA / 3000 |
| 1 | pulsos por volta | 200~51 200 / 6000 |
| 2 | tempo até o standby | 100~10 000 ms / 300 |
| 3 | corrente de standby | 0~100 % / 50 |
| 13 | autoajuste da malha de corrente | 0/1 / 1 |
| 15, 16 | Kp, Ki da malha de corrente | 10~32 767 / 1000; 0~32 767 / 200 |
| 24 | malha | 1 aberta, 2 fechada / 2 |

- **Gravar exige ter lido antes**: sem leitura daquele drive, a gravação pede
  confirmação explícita mostrando a corrente que seria escrita.
- **Kp/Ki** só são gravados com a trava *"permitir gravar os ganhos"* **e** o
  autoajuste desligado — com ele ligado o manual os declara somente leitura.
- **Pulsos por volta** só são gravados se diferirem do lido e com confirmação:
  todo número em pulsos do eixo muda de significado, e o zero deixa de valer.
- Malha fechada exige encoder ligado; sem ele o drive alarma (LED vermelho com
  7 piscadas, p. 7). Os scripts configuram **malha aberta** (`MALHA_PADRAO`).

## Homing

O STR6 só lê sensor nas entradas de **limite** (p. 8): **IN1 = limite −** e
**IN2 = limite +**, com anodo comum em **IN+** (5~24 V). Um sensor NPN drena
corrente: IN+ no +24 V e a saída do sensor em IN1 ou IN2. O estado aparece nos
bits 5 (limite −) e 4 (limite +) do status (75).

- **Entrada do sensor** decide também o sentido da busca: IN1 → TRÁS, IN2 → FRENTE.
- **Nível do sinal** (reg 73, bit 1 para IN1 e bit 0 para IN2): em 1 (fábrica)
  o limite ocorre com o optoacoplador **conduzindo**. *Ativo com o opto
  desligado* zera o bit — para sensor NF.
- **Filtro do limite** (reg 74) em unidades de 50 µs; a tela mostra em ms.
- **TESTAR SENSOR** lê o 75 por até 30 s sem energizar o motor e diz qual
  entrada comutou — inclusive se o fio está na entrada errada.

Dois modos:

| Modo | Como funciona |
|---|---|
| **Nativo do drive (reg 71)** — padrão | 71 = 2 (IN1) ou 1 (IN2). O drive vai até o sinal na velocidade/aceleração de 62~67, desacelera, e volta até o sinal na velocidade do reg 60 (p. 18). O fim é o eixo imóvel por 1,5 s depois de ter andado. Depois, 40 = 1 zera o contador. |
| **Software — busca pelo sensor** | o programa procura o came em contínuo, sai da fenda, reaproxima no rastejo e para na borda; depois 40 = 1. |

O zero só vale com o contador **confirmado** em zero por leitura. Homing
interrompido ou com falha invalida o zero e, com ele, os limites de curso.

### Sensores

Cada eixo aponta para um modelo de `ui/sensores.py` (campo `sensor_tipo`), que
decide se o eixo tem origem física, os valores sugeridos (filtro, aproximação,
rastejo) e o texto de fiação. **Nenhum modelo tem velocidade medida com este
drive** — todos estão com `confirmado=False` e a tela avisa antes de aplicar.
Marcar `Sem sensor` desliga o homing do eixo, e sem zero os limites por
software não têm referência.

## Limites de curso

Faixa de trabalho em **pulsos** a partir da origem, guardada **só no
`eixos.json`** — nada vai para a memória do drive.

| Campo | O que é |
|---|---|
| `Limite +` / `Limite -` | pulsos acima/abaixo do zero (o − é guardado positivo) |
| `Antecipação` | pulsos antes do limite em que a parada do JOG é comandada; limitada a metade de cada lado |
| `Tolerância` | erro aceito ao chegar num alvo |
| `Sentido de +` | qual comando soma pulsos |
| `Passo` / `Vel. do passo` | tamanho e velocidade do jog por pulsos |

Com *Aplicar limites*, o JOG é recusado no sentido que já está no limite e a
vigilância para o eixo na borda. Os limites só valem com zero estabelecido.

**Alcance da proteção:** os limites valem **enquanto esta tela conduz o eixo**.
Comando vindo de outro software ou de um CLP não passa por aqui. Proteção
independente de software exige um sensor por extremo em IN1/IN2.

## Vários eixos no mesmo barramento

A barra do topo mostra **todos** os eixos cadastrados; o painel detalhado opera
**um por vez** — o eixo ativo. Trocar de eixo captura a tela no eixo que sai e
aplica o do que entra; a troca é **recusada** com JOG, posicionamento, homing ou
teste de sensor em andamento.

- O estado de runtime (`armado`, `zero_valido`) mora no `EixoMovimento` de cada
  eixo. O drive é fonte de verdade só para **desabilitar**: um enable 0 lido no
  reg 6 tira o "habilitado" da tela; o contrário exige MOTOR ON nesta sessão.
- O endereço é **congelado por operação** (`_thread_op`): trocar o eixo ativo
  no meio de uma rotina não redireciona os comandos dela. **Toda thread que fala
  com o drive deve ser criada por `self._thread_op(...)`.**
- Todo quadro passa por `Barramento.transact`, que confere **endereço e CRC**.
  Quadro descartado aparece no log como `[DESCARTE]`.

**Orçamento do barramento:** o monitor lê, a cada 600 ms, quatro quadros do eixo
ativo (status, alarme, contador+encoder, enable) — mais tensão e corrente a cada
cinco ciclos — e quatro de **um** eixo secundário, em rodízio. Um eixo em
movimento lê três quadros por ciclo. É por isso que **esta bancada move um eixo
por vez**.

- Um ciclo novo do monitor só começa depois que o anterior terminou. Sem isso,
  ciclos lentos (1 s de timeout por quadro de eixo mudo) se empilhavam na fila
  do barramento, e gravação, salvamento e a vigilância do JOG esperavam
  dezenas de segundos pela vez.
- Eixo secundário que não responde sai do rodízio por 10 s (`_PAUSA_MUDO_S`);
  a linha dele na barra continua "sem resposta".

### Arquivo `eixos.json`

Guarda versão (`4`), eixo ativo e uma entrada por eixo com `id`, `apelido` e
`config`. É gravado ao trocar de eixo, em *Salvar limites* e ao fechar a janela.
Um arquivo de **outra versão** tem outras unidades: dele só se aproveitam `id`,
`apelido` e `sensor_tipo`; o resto entra com os padrões (o log avisa).

## Segurança

A aplicação movimenta um eixo real, **vertical**, com garra na extremidade.
Antes de operar, confirme que a área está livre e que há como cortar a energia
rapidamente. O manual (p. 3) lembra que o drive não foi projetado como proteção
pessoal contra o sistema mecânico.

- **Watchdog do JOG:** duas leituras sem resposta, uma falha no drive ou o
  limite de curso param o eixo. Sem isso, uma queda do RS-485 com o drive em
  movimento contínuo deixaria o eixo girando.
- **Parada escalonada** (`parada_segura`): desacelera (70 = 0) → parada
  imediata (70 = 5) → desabilita o motor (6 = 0).
- **O último degrau derruba a carga num eixo vertical.** Por isso ele pode ser
  desligado por eixo no card MOTOR (*"Parada: desabilitar o motor como último
  recurso"*, campo `soltar_em_emergencia`).
- **PARADA GERAL:** parada e desabilitação em todos os eixos; não aborta no
  primeiro que falhar e nomeia quem não confirmou.
- Fechar a janela desabilita todos os eixos antes de desconectar.
- Correntes dos scripts em `CORRENTES_MA` (`str6/config.py`): 1000 mA nos NEMA17
  e 200 mA no motor spin — **ponto de partida conservador, não medido com este
  drive**. Não aumente para diagnosticar hesitação ou perda de passo: investigue
  velocidade, rampa e carga primeiro.

## Pontos em aberto

O manual deixa estas questões sem resposta, e o código foi escrito para ser
seguro em qualquer das leituras. Cada uma precisa de confirmação em bancada:

1. **Registrador 6** ("Nível de Habilitação"): tratado como enable por software
   (1 habilita, 0 desabilita), porque o conector não tem entrada ENA. Confirmar
   antes de confiar no MOTOR OFF como liberação do eixo.
2. **Bit 7 do status (75)**: a descrição diz 0 = concluído, mas o "valor padrão"
   é 1. Por isso o fim de movimento nunca depende só dele.
3. **IN1/IN2/IN3**: o conector (p. 8) diz IN1 = limite −, IN2 = limite +, IN3
   reservado; a tabela do reg 73 (p. 17) cita IN3 como limite negativo. O código
   segue o conector. Rodar o TESTAR SENSOR resolve.
4. **Contador 39/40**: o manual o chama de "pulsos externos recebidos", mas manda
   zerá-lo após o homing (p. 18), o que sugere que conta também o movimento
   interno. Comparar com o encoder (41/42) no card de status. O sinal (32 bits
   com sinal) também não é declarado.
5. **Fim do retorno a zero nativo**: o manual não diz como o drive sinaliza a
   conclusão; o código espera o eixo imóvel por 1,5 s depois de ter andado.
6. **Sensor em entrada de limite**: com o sensor acionado, o drive pode bloquear
   o movimento naquele sentido. Se o eixo não sair do zero para o lado do
   sensor, este é o motivo.
7. **Código de alarme 0** (115) não está na tabela; é tratado como "sem alarme".
8. **Correntes, velocidades e filtro** padrão são pontos de partida, não medidas.
9. **Salvar parâmetros (90)**: o manual diz que a leitura devolve 0 com o
   salvamento incompleto e 1 concluído, mas não se o 1 volta a 0 depois, nem
   que é preciso escrever 1 para salvar (inferido pelo padrão do 91 e do 93).
   O atributo do registrador 0 (corrente de pico) também está em branco na
   tabela (p. 13). Que a corrente fica gravada só está demonstrado contra o
   drive simulado; no drive real, rodar o *Testar gravação* e guardar as linhas
   `[GRAV]` do log como registro.
