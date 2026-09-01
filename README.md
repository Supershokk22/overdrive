# Overdriver — Arma 3 External ESP

Sistema externo de ESP (Extra Sensory Perception) para Arma 3 Build 2.22, desenvolvido como projeto de engenharia reversa de sistemas de baixo nível.

> **Aviso**: Este projeto é puramente educacional e de pesquisa em engenharia reversa. Não se destina a uso em servidores multiplayer competitivos.

---

## O que é

Um overlay transparente que se sobrepõe ao jogo Arma 3 e desenha boxes 3D (wireframe) ao redor dos jogadores detectados, mostrando posição, distância e profundidade em tempo real.

```
┌─────────────────────────────────────┐
│          Arma 3 (jogo)              │
│                                     │
│    ┌───┐          ┌───┐             │
│    │ □ │          │ □ │ ← boxes 3D │
│    └─┬─┘          └─┬─┘   overlay  │
│      │              │               │
│   [player]      [player]           │
└─────────────────────────────────────┘
```

---

## Arquitetura do Sistema

```
┌──────────────┐    leitura     ┌──────────────┐    JSON     ┌──────────────┐
│  KPRL Driver │ ──────────────→│  W2S Engine  │ ──────────→ │   Overlay    │
│  (Ring 0)    │  memória do    │  (Ring 3)    │  esp_final  │  (Ring 3)    │
│              │  processo      │              │  .json      │  GDI/DIB     │
└──────────────┘               └──────────────┘             └──────────────┘
       │                             │                           │
       │                             │                           │
  Leitura passiva             Scan de players              Desenho de
  de memória do               via vtable +                boxes 3D via
  processo do jogo            projeção W2S                UpdateLayeredWindow
```

### Componentes

| Componente | Tipo | Descrição |
|------------|------|-----------|
| **kprl.sys** | Driver Ring 0 | Leitura passiva de memória do processo alvo via IOCTL |
| **mem_core.py** | API Python | Interface com o driver KPRL para leitura de memória |
| **w2s_fast.py** | Engine ESP | Scan de players + projeção World-to-Screen + yaw brute-force |
| **overlay_3d.py** | Overlay Ring 3 | Janela transparente com DIB + UpdateLayeredWindow |

---

## Como Funciona

### 1. Detecção de Players (Heap Scan)

O engine escaneia a heap do processo `arma3_x64.exe` procurando um padrão específico:

```
Player Struct Layout (Build 2.22):
  +0x000: X (float, East)
  +0x004: Z (float, Up/height)
  +0x008: Y (float, North)
  ...
  +0x0D0: VTABLE pointer → MOD + 0x1C18CA8
```

O scan busca o valor `MOD + 0x1C18CA8` na heap. Cada ocorrência indica um potencial player struct. O offset `+0x0D0` contém o ponteiro da vtable, confirmando que é um objeto válido do tipo player.

**Filtro anti-falso-positivo**: Remove players muito distantes do cluster principal (outliers > 3x distância mediana do centróide).

### 2. Identificação do Local vs Amigos

```python
# Local = player mais próximo do centróide de todos os players
cx = mean(p['x'] for p in players)
cy = mean(p['y'] for p in players)
local = closest_to(players, cx, cy)
```

### 3. World-to-Screen (Projeção Matemática)

Em vez de encontrar a ViewProjection Matrix na memória (que mudou nesta build), usamos projeção analítica:

```python
def project(eye, yaw, fov, world_pos, screen_size):
    # 1. Calcula differencial mundo-eye
    dx, dy, dz = world - eye
    
    # 2. Rotação por yaw (ângulo horizontal da câmera)
    rx = dx * cos(yaw) - dz * sin(yaw)
    rz = dx * sin(yaw) + dz * cos(yaw)
    
    # 3. Projeção perspectiva
    fz = 1 / tan(fov/2)
    sx = (rx * fz / aspect) / rz * (sw/2) + sw/2
    sy = sh/2 - (dy * fz / rz) * (sh/2)
    return sx, sy
```

**Convenções do Arma 3**:
- X = East (Leste)
- Z = Up (Altura/vertical)
- Y = North (Norte)
- Yaw: 0° = Norte, 90° = Leste, 180° = Sul

### 4. Yaw (Orientação da Câmera)

O yaw é o ângulo horizontal que a câmera do jogador está apontando. Encontrar este valor na memória é o maior desafio de RE.

**Abordagens tentadas**:
1. **Camera Controller** (+0x0C8 do player → offset interno): Funcionou na sessão anterior (forward em +0x1EC), mas os offsets mudaram na build multiplayer atual
2. **Brute-force**: Testa todos os ângulos 0-359° e escolhe o que mais espalha os players na tela — funciona mas não é ideal
3. **Scan dinâmico** (2 snapshots + diff): Detecta campos que mudam quando a câmera gira — método mais confiável para encontrar offsets

### 5. Overlay (Desenho)

O overlay usa a API Windows GDI com DIB Section + UpdateLayeredWindow para transparência per-pixel:

```
┌─ CreateWindowEx (STATIC, WS_POPUP, WS_EX_LAYERED | WS_EX_TOPMOST)
│
├─ CreateDIBSection (buffer BGRA 32bpp)
│  └─ buf[y * W + x] = cor do pixel
│
├─ Para cada player:
│  ├─ Calcula 8 cantos do cubo 3D (mundo → tela via W2S)
│  ├─ Desenha 12 arestas (Bresenham line) no buffer
│  └─ Cor baseada na distância (verde/ciano/amarelo/vermelho)
│
└─ UpdateLayeredWindow (mostra buffer com transparência)
```

**Escala de cores por distância**:
- Verde: < 100m (perto)
- Ciano: 100-500m
- Amarelo: 500-2000m
- Vermelho: > 2000m

---

## Arquivos Principais

```
overdriver/
├── mem_core.py          # API de leitura de memória via driver KPRL
├── w2s_fast.py          # Engine principal (scan + projeção + yaw brute-force)
├── w2s_engine.py        # Engine anterior (vtable scan por CHUNK)
├── overlay_3d.py        # Overlay 3D com DIB + UpdateLayeredWindow
├── overlay_gdi.py       # Overlay 2D anterior (GDI simples)
├── w2s_math.py          # Núcleo matemático de projeção W2S
├── esp_final.json       # Dados ESP em tempo real (gerado pelo engine)
├── overlay_heartbeat.json  # Heartbeat do overlay
├── kprl.sys             # Driver KPRL (leitura de memória)
├── kill_orphans.ps1     # Script para matar processos órfãos
├── docs/                # Documentação técnica
│   └── plan_kernel.md   # Planos de desenvolvimento do driver
└── github_repo/         # Este README
    └── README.md
```

---

## Descobertas de Engenharia Reversa

### Camera Controller (Build 2.22 antiga)
```
Player +0x0C8 → Camera Controller
  +0x1C8: Eye Position (X, Z_height, Y)
  +0x1EC: Forward Vector (unitário: east, up, north)
  +0x2BC: FOV (half-angle = 0.5)
  +0x224: Far clip plane (1.000.000.000)
```

### Camera Controller (Build 2.22 multiplayer — offsets diferentes)
Os offsets acima **não funcionam** nesta sessão multiplayer. O controller existe (mesma vtable `0x7FF70A58D0E8`) mas os campos internos estão zerados.

### Vtable Pattern
```
Vtable RVA: 0x1C18CA8
Offset no player: +0x0D0
Vtable value: MOD + 0x1C18CA8 = 0x7FF70A4D8CA8
```

---

## Build & Run

### Pré-requisitos
- Windows 10/11
- Python 3.10+
- numpy
- Driver KPRL carregado (para leitura de memória)

### Execução
```bash
# 1. Carregar o driver (requer admin)
# 2. Iniciar o Arma 3 e entrar no mapa

# 3. Rodar o engine (scan + projeção)
python w2s_fast.py

# 4. Rodar o overlay (em outro terminal)
python overlay_3d.py
```

### Ou usar o runner integrado:
```bash
python runner.py
```

---

## Limitações Conhecidos

1. **Scan inicial lento** (~90s para vtable scan completo)
2. **Yaw via brute-force** — não detecta direção real da câmera, apenas maximiza spread
3. **Offsets de câmera mudam** entre sessões multiplayer (requer RE dinâmico)
4. **BattlEye** pode detectar leitura de memória (risco de ban em multiplayer)

---

## Tecnologias Utilizadas

- **Python 3** — linguagem principal
- **ctypes** — interface com APIs Windows (GDI, kernel32, user32)
- **numpy** — processamento rápido de arrays de float
- **Windows API** — CreateWindowEx, UpdateLayeredWindow, DIBSection, GDI drawing
- **Driver KPRL** — leitura passiva de memória via IOCTL

---

## Licença

Este projeto é para fins **educacionais e de pesquisa** em engenharia reversa de sistemas de baixo nível. Não se destina a uso em servidores multiplayer competitivos.
