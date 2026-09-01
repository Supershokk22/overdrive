<div align="center">

# 🔫 OVERDRIVER

### Arma 3 External ESP — Engenharia Reversa de Sistemas de Baixo Nível

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Windows](https://img.shields.io/badge/Windows-10%2F11-0078D6?style=for-the-badge&logo=windows&logoColor=white)
![License](https://img.shields.io/badge/License-Educational-yellow?style=for-the-badge)

*Sistema externo de ESP para Arma 3 Build 2.22 — detecção de players via heap scanning, projeção W2S matemática e overlay 3D com transparência per-pixel.*

---

[![Sistema](https://img.shields.io/badge/Status-DESENVOLVIMENTO-orange?style=flat-square)]()
[![Engine](https://img.shields.io/badge/Engine-W2S_Math-green?style=flat-square)]()
[![Overlay](https://img.shields.io/badge/Overlay-DIB%2BULW-blue?style=flat-square)]()

</div>

---

## 📋 Visão Geral

```
┌──────────────────────────────────────────────────────────────┐
│                     PIPELINE DE DADOS                        │
│                                                              │
│  ┌─────────┐    IOCTL     ┌──────────┐   JSON    ┌────────┐ │
│  │  KPRL   │ ──────────→ │  Engine  │ ───────→ │Overlay │ │
│  │ Driver  │  leitura     │   ESP    │ esp_final│  3D    │ │
│  │ Ring 0  │  passiva     │  Ring 3  │   .json  │ Ring 3 │ │
│  └─────────┘              └──────────┘          └────────┘ │
│                                                              │
│  → Heap scan por vtable    → Projeção W2S     → DIB + ULW  │
│  → ~116 players detectados → Yaw brute-force  → Wireframe  │
│  → Filtro anti-false-pos   → ~5ms/frame       → 30 FPS     │
└──────────────────────────────────────────────────────────────┘
```

---

## 🏗️ Arquitetura

### Stack Tecnológica

| Camada | Componente | Tecnologia |
|--------|-----------|------------|
| **Ring 0** | KPRL Driver | IOCTL, leitura passiva de memória |
| **Ring 3** | W2S Engine | Python, numpy, vtable scan |
| **Ring 3** | Overlay 3D | GDI, DIB Section, UpdateLayeredWindow |

### Fluxo de Dados

```
1. Driver KPRL lê a heap do processo arma3_x64.exe (passivo, sem hook)
                    ↓
2. Engine escaneia por vtable pattern (MOD + 0x1C18CA8 em +0x0D0)
                    ↓
3. Para cada player encontrado: lê posição (X, Z, Y) = 12 bytes
                    ↓
4. Filtra outliers (cluster analysis) → remove falsos positivos
                    ↓
5. Projeta 3D→2D via W2S matemático (yaw, fov, perspective)
                    ↓
6. Salva esp_final.json → Overlay lê e desenha boxes 3D
```

---

## 🎯 Como Funciona

### 1. Detecção de Players (Heap Scan)

O engine busca o **vtable pattern** `MOD + 0x1C18CA8` em toda a heap do jogo:

```
Player Struct Layout (Build 2.22):
┌─────────────────────────────────────────┐
│ +0x000 │ X  (float) │ East position    │
│ +0x004 │ Z  (float) │ Height (Up)      │
│ +0x008 │ Y  (float) │ North position   │
│   ...  │            │                  │
│ +0x0D0 │ VTABLE PTR │ → MOD+0x1C18CA8  │
└─────────────────────────────────────────┘
```

**Filtros aplicados:**
- Range de coordenadas: |X| < 100k, |Y| < 100k, 0 ≤ Z ≤ 2000
- Cluster analysis: remove outliers > 3× distância mediana do centróide
- Resultado: ~100-130 players reais por scan

### 2. World-to-Screen (Projeção Matemática)

Em vez de encontrar a ViewProjection Matrix na memória (instável entre builds), usamos **projeção analítica**:

```python
# Arma 3 coordinate system: X=East, Z=Up, Y=North
# Yaw: 0°=North, 90°=East, 180°=South

def w2s(eye, yaw, fov, world_pos, screen):
    dx = world.x - eye.x          # differential East
    dy = world.z - eye.z          # differential Up
    dz = world.y - eye.y          # differential North
    
    # Rotation by yaw
    rx = dx * cos(yaw) - dz * sin(yaw)
    rz = dx * sin(yaw) + dz * cos(yaw)
    
    # Perspective projection
    focal = 1 / tan(fov / 2)
    sx = (rx * focal / aspect) / rz * (sw/2) + (sw/2)
    sy = sh/2 - (dy * focal / rz) * (sh/2)
    return sx, sy
```

### 3. Yaw Detection (Orientação da Câmera)

O yaw é o ângulo horizontal da câmera. Métodos implementados:

| Método | Precisão | Velocidade | Status |
|--------|----------|------------|--------|
| Camera Controller offset | Alta | Instantâneo | ⚠️ Instável entre builds |
| Brute-force (0-359°) | Média | ~100ms/frame | ✅ Funcional |
| Dynamic snapshot (diff) | Alta | ~3s | 🔬 Em teste |

### 4. Overlay 3D (Desenho)

Janela transparente via `DIB Section + UpdateLayeredWindow`:

```
CreateWindowEx → CreateDIBSection → Bresenham Lines → UpdateLayeredWindow
     ↑                                                        ↓
     └────────────── WS_EX_TOPMOST + LWA_COLORKEY ───────────┘
```

**Wireframe 3D:** 8 cantos do cubo projetados via W2S, 12 arestas desenhadas com Bresenham.

**Cores por distância:**

| Cor | Distância | Significado |
|-----|-----------|-------------|
| 🟢 Verde | < 100m | Inimigo próximo |
| 🔵 Ciano | 100-500m | Distância média |
| 🟡 Amarelo | 500-2000m | Distância longa |
| 🔴 Vermelho | > 2000m | Muito longe |

---

## 📁 Estrutura do Projeto

```
overdriver/
├── w2s_fast.py          # 🚀 Engine principal (scan + projeção + yaw)
├── w2s_engine.py        # 📦 Engine alternativa (vtable scan CHUNK)
├── w2s_math.py          # 🧮 Núcleo matemático W2S
├── overlay_3d.py        # 🖥️ Overlay 3D com DIB + UpdateLayeredWindow
├── overlay_gdi.py       # 🖼️ Overlay 2D (versão simplificada)
├── runner.py            # 🔄 Runner integrado (engine loop + overlay)
├── mem_core.py          # 💾 API de leitura de memória via driver KPRL
├── kprl.sys             # ⚙️ Driver Ring 0 (leitura passiva)
├── esp_final.json       # 📊 Dados ESP em tempo real
├── docs/                # 📚 Documentação técnica
│   └── plan_kernel.md   #    Planos de desenvolvimento
└── github_repo/         # 📖 Este README
```

---

## 🔧 Build & Run

### Pré-requisitos

- **OS:** Windows 10/11 (x64)
- **Python:** 3.10+
- **Dependências:** `numpy`
- **Driver:** KPRL carregado (requer admin)

### Instalação

```bash
git clone https://github.com/Supershokk22/overdriver.git
cd overdriver
pip install numpy
```

### Execução

```bash
# Opção 1: Engine + Overlay separados
python w2s_fast.py      # Terminal 1: Engine ESP
python overlay_3d.py    # Terminal 2: Overlay 3D

# Opção 2: Runner integrado
python runner.py        # Inicia engine loop + overlay
```

### Ordem de Execução

```
1. Carregar driver KPRL (requer admin)
2. Iniciar Arma 3 → entrar no mapa
3. python w2s_fast.py (aguardar ~90s para primeiro scan)
4. python overlay_3d.py (após o scan completar)
```

---

## 🔬 Descobertas de Engenharia Reversa

### Player Struct (Build 2.22)

```
Offset  Tipo     Descrição
──────  ───────  ─────────────────────────
+0x000  float    X position (East)
+0x004  float    Z height (Up)
+0x008  float    Y position (North)
+0x0C8  ptr      Camera Controller
+0x0D0  qword    VTABLE → MOD + 0x1C18CA8
+0x2F8  ptr      Orientation data
```

### Camera Controller

```
Build 2.22 (single-player):
  +0x1C8: Eye Position (X, Z_height, Y)
  +0x1EC: Forward Vector (unitário)
  +0x2BC: FOV half-angle (0.5)

Build 2.22 (multiplayer):
  Mesma vtable (0x7FF70A58D0E8), mas offsets internos ZERADOS.
  Causa provável: lazy initialization ou layout diferente.
```

### Vtable Detection

```python
VTABLE_RVA  = 0x1C18CA8
VT_OFF      = 0x0D0  # offset do vtable pointer no player struct
VTABLE_ABS  = MOD + VTABLE_RVA  # 0x7FF70A4D8CA8
```

---

## ⚠️ Limitações

| Item | Status | Notas |
|------|--------|-------|
| Scan inicial | ~90s | Vtable scan de ~3000 regiões |
| Yaw dinâmico | Brute-force | Não detecta câmera real, maximiza spread |
| Overlay 3D | Funcional | Wireframe 8 cantos, 12 arestas |
| BattlEye | ⚠️ Risco | Leitura passiva pode ser detectada |
| Build 2.22 | Parcial | Offsets de câmera instáveis |

---

## 🛠️ TODO

- [ ] Encontrar offsets estáveis da câmera via scan dinâmico (2 snapshots + diff)
- [ ] Otimizar scan para < 5s (entity list discovery)
- [ ] Adicionar snapline (linha do centro até cada player)
- [ ] Adicionar distância e nome na box
- [ ] Suporte a múltiplas resoluções
- [ ] Engine loop integrado (sem necessidade de 2 terminais)

---

## 📄 Licença

Este projeto é para fins **educacionais e de pesquisa** em engenharia reversa de sistemas de baixo nível.

---

<div align="center">

**Feito com** 💻 **Python** + 🔍 **Engenharia Reversa** + 🎮 **Arma 3**

</div>
