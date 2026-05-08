# Alunos
- Ivan Mateus Azevedo Martinotto - 822410
- Kailayni Rodrigues Janez - 824751
- Lucas Fujii - 814291
- Matheus Minasse - 813278
- Samuel Gerga Martins - 821772

# Sistema de Videoconferência Distribuído

Sistema de videoconferência peer-to-peer com áudio, vídeo e texto, construído sobre **ZeroMQ**, com arquitetura distribuída tolerante a falhas: múltiplos brokers cooperando em malha sem loops, descoberta dinâmica de serviços, garantia de entrega de texto e migração automática de clientes em caso de falha.

Este documento descreve a evolução do MVP inicial (1 broker centralizado) para um sistema distribuído com múltiplos brokers, service discovery, failover automático, suporte a salas e — após o último ciclo de melhorias — entrega confiável de texto, mesh sem loop arquitetural, autodetecção de IP RADMIN e operação cross-PC.

---

## Sumário

- [Arquitetura](#arquitetura)
- [Componentes](#componentes)
- [Layout de portas (10 por broker)](#layout-de-portas-10-por-broker)
- [Padrões ZeroMQ utilizados](#padrões-zeromq-utilizados)
- [Formato de mensagens](#formato-de-mensagens)
- [Mesh sem loops](#mesh-sem-loops)
- [Tolerância a falhas](#tolerância-a-falhas)
- [Garantia de entrega de texto](#garantia-de-entrega-de-texto)
- [Controle de Qualidade (QoS)](#controle-de-qualidade-qos)
- [Identidade, salas e presença](#identidade-salas-e-presença)
- [Como executar](#como-executar)
- [Setup multi-PC com RADMIN VPN](#setup-multi-pc-com-radmin-vpn)
- [Comandos do cliente](#comandos-do-cliente)
- [Demonstração de failover](#demonstração-de-failover)
- [Decisões de design relevantes](#decisões-de-design-relevantes)
- [Mudanças vs versão anterior](#mudanças-vs-versão-anterior)

---

## Arquitetura

```
                       ┌────────────────────┐
                       │  Discovery Service │  REP socket (porta 5570)
                       │   discovery.py     │  registry de brokers vivos
                       └─────────┬──────────┘
                                 │ REGISTER, HEARTBEAT, LIST
            ┌────────────────────┼────────────────────┐
            │                    │                    │
            ▼                    ▼                    ▼
   ┌──────────────┐      ┌──────────────┐      ┌──────────────┐
   │  Broker B1   │ mesh │  Broker B2   │ mesh │  Broker BN   │
   │  XSUB/XPUB   │◄────►│  XSUB/XPUB   │◄────►│  XSUB/XPUB   │
   │  + mesh PUB  │      │  + mesh PUB  │      │  + mesh PUB  │
   │  + control   │      │  + control   │      │  + control   │
   │  + history   │      │  + history   │      │  + history   │
   └──────┬───────┘      └──────┬───────┘      └──────┬───────┘
          │                     │                     │
       clientes              clientes              clientes
```

Cada **broker** é um proxy XSUB/XPUB com 4 canais independentes (vídeo, áudio, texto, presença), mais um socket PUB dedicado para o **mesh** e um socket REP para **controle** (consulta de histórico e estado). Os brokers se descobrem via **discovery** e formam uma malha completa, mas a propagação de mensagens é **estruturalmente livre de loops** (ver seção dedicada).

Os **clientes** consultam o discovery, escolhem um broker aleatoriamente e mantêm um **watchdog** que monitora a saúde do broker atual. Se o broker cair, o cliente migra automaticamente para outro broker disponível.

Toda comunicação faz `bind` em `tcp://*` (todas as interfaces). O IP RADMIN é detectado automaticamente (`detect_radmin_ip` procura interface `26.x.x.x`) e usado apenas para anunciar o endereço aos peers.

---

## Componentes

| Arquivo | Responsabilidade |
|---------|------------------|
| `common.py` | Constantes compartilhadas, helpers de tópico/payload, autodetecção de IP RADMIN |
| `discovery.py` | Service Discovery via REP socket. Mantém registry com timeout por heartbeat |
| `broker.py` | Proxy XSUB/XPUB local + mesh forwarder + mesh receiver + log de texto + REP de controle |
| `member.py` | Cliente. Captura/render de mídia, conexão via discovery, watchdog, salas, presença, texto confiável |
| `launch.py` | Orquestrador. Sobe discovery + N brokers + M clientes locais; imprime IP para PCs remotos |

---

## Layout de portas (10 por broker)

Cada broker ocupa **10 portas consecutivas** a partir de `--base-port`:

| Offset | Socket | Quem usa | Função |
|---|---|---|---|
| `+0` | XSUB | Clientes (PUB) | Entrada do canal vídeo |
| `+1` | XPUB | Clientes (SUB) | Saída do canal vídeo |
| `+2` / `+3` | XSUB / XPUB | Clientes | áudio |
| `+4` / `+5` | XSUB / XPUB | Clientes | texto |
| `+6` / `+7` | XSUB / XPUB | Clientes | presença |
| `+8` | PUB | Brokers peer (SUB) | **Mesh out** — somente mensagens originadas localmente |
| `+9` | REP | Clientes / brokers peer | **Controle** — `HISTORY`, `INFO` |

Distância mínima entre `--base-port` de brokers diferentes: **10**. Default do `launch.py`: brokers em `5555`, `5565`, `5575`, etc.

---

## Padrões ZeroMQ utilizados

| Padrão | Onde | Por quê |
|--------|------|---------|
| **PUB/SUB** | Cliente ↔ broker (4 canais) | Disseminação 1:N. Filtro por tópico |
| **XSUB/XPUB** | Frontend/backend do proxy | `zmq.proxy` propaga subscriptions automaticamente |
| **REQ/REP** | Discovery + controle do broker | Comunicação síncrona com timeout, ideal para registro, heartbeat, histórico |
| **PUB/SUB (mesh)** | Mesh out (PUB) → mesh in (SUB) entre brokers | Fan-in many-to-one. Cada broker assina o `mesh out` de todos os outros |

A diferença fundamental para a versão anterior: o mesh **não conecta mais ao XPUB do peer**. Ele conecta a um socket PUB dedicado (porta `+8`) que carrega **somente** mensagens locais. Detalhe na próxima seção.

---

## Formato de mensagens

Toda mensagem trafega como `multipart` com 2 frames:

```
Frame 1 (tópico):   "{canal}:{broker_origem}:{sala}:{user_id}"
Frame 2 (payload):  bytes específicos do canal
```

Para **texto** o frame 2 é um envelope JSON com `msg_id`, `sender`, `text`, `ts` — usado para deduplicação, ACK por eco e histórico:

```
Tópico:  "text:B1:A:Ivan"
Payload: {"msg_id":"Ivan-42","sender":"Ivan","text":"olá","ts":1730000000.123}
```

Demais canais permanecem com payload binário (`<JPEG>`, `<PCM int16>`, `JOIN`/`LEAVE`/`WHOIS`).

`make_topic`, `parse_topic`, `make_text_payload` e `parse_text_payload` em `common.py`.

---

## Mesh sem loops

O design anterior (cada broker SUB nos XPUBs dos peers + reinjeção) sofria de multiplicação exponencial de mensagens com **N ≥ 3 brokers**: cada peer reinjetava mensagens recebidas, que eram redistribuídas pelos seus próprios XPUBs para os demais peers, e assim sucessivamente. O filtro `origin == my_id` só quebrava o ciclo no caso de 2 brokers.

A solução adotada separa o tráfego "para clientes locais" do tráfego "para outros brokers":

1. Cada broker tem um socket **PUB dedicado ao mesh** na porta `base+8` (`mesh_forwarder_thread`).
2. Esse forwarder assina os 4 XPUBs locais e republica no `mesh PUB`, **mas apenas se** `topic.origin == my_id`.
3. Mensagens injetadas por peers (origin ≠ my_id) chegam aos clientes locais via XPUB local, mas **nunca** alcançam o `mesh PUB`.
4. Cada broker faz SUB no `mesh PUB` de todos os peers e injeta o que recebe no próprio XSUB local (loopback `127.0.0.1`).

Resultado: cada mensagem trafega exatamente uma vez direto da origem para cada broker. Não há reinjeção em cadeia. Suporta N brokers sem multiplicação de tráfego.

---

## Tolerância a falhas

### Detecção de broker morto

Discovery mantém `last_seen` por broker. Heartbeats a cada `1.5s`. Sem heartbeat por `5s` → removido da listagem.

### Migração automática do cliente (failover)

Cada cliente roda um `watchdog` que, a cada `2s`:
1. Pergunta ao discovery a lista de brokers vivos.
2. Se o broker atual sumiu, escolhe outro aleatoriamente e dispara `Conn.swap()`.

`Conn.swap()`:
1. Cria um **novo `zmq.Context`** (não reutiliza).
2. Cria os 8 sockets novos no novo context, conecta no broker novo.
3. Aguarda `0.5s` para subscriptions propagarem.
4. Substitui referências atomicamente sob lock.
5. Fecha sockets antigos e destrói o context antigo (`destroy(linger=0)`).
6. **Republica todas as mensagens de texto pendentes** (garantia de entrega).
7. **Busca histórico de texto** do novo broker para a sala atual.
8. Publica burst de `JOIN` + `WHOIS` para se reanunciar.

### Detecção de peer morto entre brokers

`mesh_bridge` consulta o discovery a cada `3s`. Quando aparece um peer novo, abre conexão SUB e **faz backfill de histórico de texto** via REP de controle. Peers que somem: nada é feito — ZMQ reconecta sozinho quando voltam.

---

## Garantia de entrega de texto

A entrega confiável de texto é construída em camadas:

1. **`msg_id` único**: cada mensagem do remetente recebe `msg_id = "{member_id}-{seq}"`.
2. **Fila pendente**: o remetente guarda a mensagem em `pending_text` até receber ACK.
3. **ACK por eco**: o broker propaga a mensagem pelo XPUB, o remetente recebe seu próprio eco e remove o `msg_id` de `pending_text`.
4. **Retry em background**: a cada `~1s`, mensagens pendentes há mais de `TEXT_RETRY_INTERVAL` (2s) são republicadas. Limite: `TEXT_MAX_RETRIES` (5).
5. **Re-envio em failover**: ao trocar de broker, `resend_pending_text()` republica todas as pendentes no novo broker.
6. **Histórico no broker**: `text_logger_thread` em cada broker armazena toda mensagem de texto vista (até 500 por sala) com dedup por `msg_id`.
7. **Backfill em mesh**: quando um broker novo se conecta a um peer, busca o histórico via REP `CMD_HISTORY` para se sincronizar.
8. **Backfill no cliente**: ao trocar de sala (ou após failover), o cliente busca o histórico da nova sala via REP, deduplicando com `seen_text_msg_ids`.
9. **Drain antes de trocar de sala**: ao executar `/room`, o cliente espera até 1s para drenar mensagens pendentes da sala antiga antes de enviar `LEAVE` e migrar.
10. **Dedup no receptor**: receptores filtram por `msg_id` em `seen_text_msg_ids` antes de exibir.

Combinadas, essas camadas garantem que mensagens de texto:
- Não se perdem em falha de broker;
- Não se perdem em troca de sala;
- Não aparecem duplicadas (mesmo após replay/backfill);
- São entregues a peers conectados em brokers diferentes (via mesh).

---

## Controle de Qualidade (QoS)

| Canal | RCVHWM | SNDHWM | Estratégia | Justificativa |
|-------|--------|--------|------------|---------------|
| **Vídeo** | 5 | 5 | `send_multipart(NOBLOCK)` + drop. 12 FPS, JPEG q55, 480×360 | Frame antigo é inútil; preferimos perder frames a acumular latência |
| **Áudio** | 20 | 20 | `send_multipart(NOBLOCK)` + drop | Latência baixa é crítica; perda pequena gera estalo, não trava |
| **Texto** | 5000 | 5000 | Buffer alto + `msg_id` + retry + histórico | Entrega garantida (ver seção dedicada) |
| **Presença** | 5000 | 5000 | Buffer alto + re-anúncio periódico | Estado online não pode se perder |

---

## Identidade, salas e presença

### Identidade

`member_id` único via `--id` ou UUID curto gerado. Aparece em todas as mensagens publicadas (no tópico).

### Salas

11 salas: `A` a `K`. Filtro de sala feito **em código** (não via `SUBSCRIBE`) — assinar `text:B1:A:`, `text:B2:A:`, … cresceria com brokers dinâmicos.

Comandos:
- `--room A` na inicialização
- `/room B` em runtime: drena pendentes → `LEAVE` antiga → fetch histórico nova → `JOIN`/`WHOIS` na nova

### Presença

Quarto canal PUB/SUB. Cada cliente:
- `JOIN` ao entrar e a cada `3s` (re-anúncio periódico, `PRESENCE_INTERVAL`)
- `LEAVE` ao sair (graceful)
- `WHOIS` após failover ou troca de sala — peers respondem com `JOIN` imediato
- Set local de membros vistos com timeout de `12s` (4× re-anúncio)

`/who` exibe lista atual.

---

## Como executar

### Pré-requisitos

```
python -m pip install pyzmq opencv-python numpy sounddevice
```

(no Windows: pode ser necessário Visual C++ Redistributable para o `sounddevice`)

### Modo simples (tudo em um PC)

```
python launch.py
```

Defaults: 2 brokers (B1, B2) + 3 clientes locais (M1, M2, M3) na sala A. Aguarda ENTER para matar B1 (demo de failover) e novo ENTER para encerrar.

### Customizando

```
python launch.py --brokers 3 --members 0
python launch.py --brokers 2 --members 5 --room B
python launch.py --brokers 2 --members 2 --names Ivan,Anna
python launch.py --base-port 6000 --port-step 10 --brokers 2
```

Args do `launch.py`:
- `--brokers N` (default 2)
- `--members N` (default 3) — clientes locais para teste; use `0` se PCs remotos vão rodar os clientes
- `--room A..K` — sala dos clientes locais
- `--base-port` — porta inicial do primeiro broker (default 5555)
- `--port-step` — espaçamento entre brokers (default 10, mínimo `NUM_PORTS_PER_BROKER`)
- `--names` — lista CSV de nomes de membros (ex: `--names Ivan,Anna,Fuji`)

### Rodar componentes manualmente

Em terminais separados:

```
python discovery.py
python broker.py --id B1 --base-port 5555
python broker.py --id B2 --base-port 5565
python member.py --id Ivan --room A
python member.py --id Anna --room A
```

### Argumentos relevantes

**broker.py**
- `--id` — identificador único (obrigatório)
- `--base-port` — porta inicial; ocupa `base..base+9` (10 portas)
- `--discovery` — endereço do discovery (default: `tcp://<radmin-ip>:5570`)
- `--host` — IP anunciado a clientes (default: RADMIN auto-detectado)

**member.py**
- `--id` — identificador (default: UUID curto)
- `--room` — sala inicial A–K (default: A)
- `--discovery` — endereço do discovery (default: `tcp://<radmin-ip>:5570`)
- `--no-video` — desabilita captura de vídeo (útil em VMs sem câmera)
- `--no-audio` — desabilita captura de áudio

**discovery.py**
- `--port` — porta REP (default: 5570)
- `--bind` — interface (default: `*` = todas)

---

## Setup multi-PC com RADMIN VPN

A configuração típica de demo em sala:

1. **PC host** (1 máquina): roda `discovery` + N `brokers`.
2. **PCs remotos** (várias máquinas): cada um roda 1 `member`.

### Passo a passo

**No PC host:**
```
python launch.py --brokers 2 --members 0
```

O launcher imprime algo como:

```
======================================================================
[launcher] host RADMIN IP detected: 26.51.162.220
[launcher] discovery will be at:    tcp://26.51.162.220:5570
[launcher] remote PC command:
           python member.py --id <name> --discovery tcp://26.51.162.220:5570
======================================================================
```

**Anote o endereço impresso.**

**Em cada PC remoto:**
```
python member.py --id Alice --discovery tcp://26.51.162.220:5570
python member.py --id Bob   --discovery tcp://26.51.162.220:5570 --room B
```

Substitua `26.51.162.220` pelo IP impresso no host.

### Notas

- Todos os sockets fazem `bind` em `tcp://*`, então qualquer interface (RADMIN, LAN ou loopback) funciona simultaneamente.
- O host detecta automaticamente o IP `26.x.x.x` (faixa típica do RADMIN). Se a máquina tiver mais de uma interface RADMIN ou se quiser forçar um IP, passe `--host <ip>` ao `broker.py`.
- Se o RADMIN bloquear broadcast, isso não afeta o sistema — toda comunicação é unicast TCP direto.
- Latência típica em RADMIN VPN é ~30–100ms; o sistema tolera bem (texto e presença têm buffer alto; áudio/vídeo trocam latência por drop).

---

## Comandos do cliente

Dentro de uma sessão do `member.py`:

| Comando | Efeito |
|---------|--------|
| `<texto>` | Envia mensagem de texto para a sala |
| `/who` | Lista membros online na sala atual |
| `/room X` | Muda para a sala X (A–K). Drena pendentes da sala antiga, busca histórico da nova |
| `exit` | Encerra o cliente (publica `LEAVE` antes) |

Na janela de vídeo:
- `b` — sair pela janela
- `m` — toggle mute do áudio recebido

---

## Demonstração de failover

Roteiro:

1. **Setup**: discovery + 2 brokers + 3+ clientes na sala A.
2. **Conversa estável**: clientes trocam texto, áudio, vídeo. `/who` mostra todos.
3. **Falha do broker**: `Ctrl+C` (ou `taskkill`) em B1 — ou simplesmente ENTER no `launch.py`, que mata B1.
4. **Detecção**: em até `5s`, discovery imprime `[discovery] TIMEOUT B1`.
5. **Migração**: em até `2s` adicionais, watchdogs detectam ausência e disparam `swap()`. Cada cliente imprime `[client] connected to B2 ... — context recreated`.
6. **Re-envio**: `[client] re-sending N pending text msg(s)` (se havia mensagens pendentes).
7. **Backfill**: `[client] backfilled N historic text msg(s) for room A`.
8. **Recuperação completa**: clientes republicam `WHOIS`, `/who` volta a listar todos.
9. **Conversa retomada**: mensagens, áudio e vídeo voltam a fluir via B2.

Tempo total típico de recuperação: **7–10 segundos**. Mensagens de texto enviadas durante a janela de falha não se perdem — são reenviadas após o swap e/ou recuperadas pelo backfill de histórico.

---

## Decisões de design relevantes

### Por que recriar o `zmq.Context` no failover?

Em testes com múltiplos clientes migrando simultaneamente, observamos que reaproveitar o context produzia subscriptions inconsistentes — clientes deixavam de receber mensagens mesmo após `setsockopt(SUBSCRIBE)`. Recriar o context resolve definitivamente. Custo é mínimo (poucos ms).

### Por que mesh com PUB/SUB e não ROUTER/DEALER?

PUB/SUB é mais simples e a malha completa garante propagação direta. ROUTER/DEALER seria adequado para topologia em árvore ou roteamento condicional, mas adicionaria complexidade sem ganho prático para nosso caso.

### Como o mesh evita loops sem perder propagação?

Cada broker tem **dois caminhos de saída separados**:
- XPUB local (porta `+1`/`+3`/`+5`/`+7`): visto por clientes locais; recebe **toda** mensagem (locais + injetadas por peers).
- Mesh PUB (porta `+8`): visto por brokers peer; recebe **somente** mensagens com `origin == my_id`.

Como peers só assinam o mesh PUB, mensagens reinjetadas por um broker (origin ≠ my_id) não chegam aos demais peers — ficam apenas nos clientes locais daquele broker. Loop estruturalmente impossível.

### Por que o filtro de sala é em código e não via SUBSCRIBE?

ZMQ filtra por prefixo. Filtrar sala via SUBSCRIBE exigiria assinar `text:B1:A:`, `text:B2:A:`, … — um prefixo por broker. Como brokers são dinâmicos, manter subscriptions atualizadas seria custoso. Filtrar sala em código tem custo desprezível porque mensagens descartadas chegam só do canal já filtrado.

### Por que `bind tcp://*` e não no IP específico?

Bind em `tcp://*` aceita conexões em todas as interfaces (LAN, RADMIN, loopback). O IP RADMIN é apenas anunciado via discovery para clientes saberem onde conectar. Bind em IP específico quebrava cross-PC — clientes em outras interfaces não conseguiam alcançar o broker.

### Por que ACK por eco e não REQ/REP?

PUB/SUB já entrega cópia da mensagem ao próprio remetente (todos que têm `SUBSCRIBE "text:"` recebem). Aproveitar isso como ACK evita um socket extra e mantém o caminho de delivery uniforme. O custo é receber a própria mensagem (ignorada após ACK).

### Por que histórico apenas de texto?

Texto tem requisito de entrega garantida; áudio/vídeo são best-effort por natureza (frame antigo é inútil). Armazenar 500 mensagens de texto por sala custa pouca memória; armazenar 500 frames de vídeo seria proibitivo.

---

## Mudanças vs versão anterior

Resumo das diferenças em relação à versão MVP do mesh:

| Área | Antes | Agora |
|---|---|---|
| **Bind dos sockets** | IP fixo hardcoded (`tcp://26.51.162.220:port`) | `tcp://*` em todos; IP RADMIN apenas anunciado |
| **Mesh injection** | PUB conectava em IP errado (`26.78.64.226`, hardcoded) | Loopback `127.0.0.1` |
| **Mesh com N≥3** | Loop exponencial (cada peer reinjeta para todos) | Mesh PUB dedicado por broker; loop estruturalmente impossível |
| **Texto: entrega** | `NOBLOCK` simples — podia perder em falha de broker / troca de sala | `msg_id` + retry + histórico + backfill + drain antes de trocar sala |
| **Texto: payload** | String `"sender|texto"` | JSON `{"msg_id","sender","text","ts"}` |
| **Histórico de texto** | Inexistente | Per-sala no broker (500 msgs) + sync entre peers + REP `CMD_HISTORY` |
| **Detecção de IP** | Hardcoded ou `socket.gethostbyname(socket.gethostname())` | `detect_radmin_ip()` (procura `26.x.x.x`) com fallback |
| **Portas por broker** | 8 (4 canais × 2) | 10 (4 canais × 2 + mesh + control) |
| **Launcher** | 2 brokers + 3 nomes hardcoded; ENTER para failover | Parametrizado `--brokers N --members N --room X --names a,b,c`; imprime endereço para PCs remotos |
| **Throttle de vídeo** | Sem throttle explícito (~30 FPS) | 12 FPS, JPEG q55, 480×360 |
| **Args de membro** | `--id`, `--room` | + `--discovery`, `--no-video`, `--no-audio` |
