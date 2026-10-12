# 🎙 Voz Rápida

Ditado por voz **100% local e gratuito** para Linux e macOS.

Aperte um atalho (ou clique no ícone), fale, e veja o texto aparecer **enquanto você fala**. Clique em **Parar** e, em cerca de 1–3 segundos, a transcrição já está na área de transferência, pronta para colar com `Ctrl+V` / `⌘V`.

- **Offline e privado:** o áudio nunca sai do seu computador.
- **Rápido em CPU comum:** não precisa de GPU.
- **Pontuação e maiúsculas automáticas**, em português e mais 24 idiomas europeus (detecção automática).
- Guarda um **histórico** de tudo que você ditou.

| Sistema | Interface | Atalho padrão |
|---|---|---|
| Linux | Ícone na bandeja + widget flutuante com o texto ao vivo e botão **■ Parar** | `Ctrl+Alt+Espaço` (GNOME, configurado automaticamente) |
| macOS | 🎙 na barra de menus, com o tempo e o texto ao vivo no próprio título | `⌃⌥Espaço` (configurável) |

## Como funciona

O modelo usado é o [**Parakeet TDT 0.6B v3**](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) da NVIDIA, quantizado em int8 e rodando via [ONNX Runtime](https://onnxruntime.ai/) pela biblioteca [onnx-asr](https://github.com/istupakov/onnx-asr). Em CPU ele é bem mais rápido que o Whisper, com precisão parecida.

```
microfone ─► detector de pausas ─► trechos de fala ─► Parakeet (CPU) ─► texto
               (corta a cada ~0,6 s     │                                  │
                de silêncio)            └─ prévia do trecho atual ◄────────┘
```

A fala é dividida nas pausas, e cada trecho é transcrito **enquanto você ainda está falando**. Ao parar, só falta processar o último trecho. Por isso o texto fica pronto quase na hora, mesmo em gravações longas.

Num Intel i7-7500U (2017, sem GPU), cada trecho leva cerca de 0,35 a 0,45 s de processamento por segundo de áudio.

## Instalação

São necessários **Python 3.10+** e cerca de **700 MB** livres para o modelo, que é baixado uma única vez.

```bash
git clone https://github.com/ederfmatos/voz-rapida.git
cd voz-rapida
./install.sh
```

O instalador não usa `sudo`: tudo vai para a sua pasta de usuário. Ele cria um ambiente Python isolado, baixa o modelo, configura o início automático e já deixa o app rodando. Se você tiver o [uv](https://docs.astral.sh/uv/), ele é usado automaticamente e a instalação fica mais rápida.

### Linux

Pré-requisitos (o instalador avisa se faltar algo):

```bash
# Debian / Ubuntu / Mint / Zorin / Pop!_OS
sudo apt install python3-gi gir1.2-gtk-3.0 python3-venv pipewire-bin

# Fedora
sudo dnf install python3-gobject gtk3 pipewire-utils

# Arch / Manjaro
sudo pacman -S python-gobject gtk3 pipewire
```

- **Áudio:** usa o `pw-record` (PipeWire). Se ele não existir, usa o `arecord` (ALSA).
- **Ícone na bandeja:** no GNOME, precisa da extensão **AppIndicator** (já vem no Ubuntu e no Zorin). Ative "legacy tray icons" se o ícone não aparecer. Em KDE, XFCE, Cinnamon e MATE funciona direto.
- **Wayland:** o app roda via XWayland, para o ícone e o widget flutuante funcionarem.
- **Atalho:** no GNOME, `Ctrl+Alt+Espaço` é registrado automaticamente. Em outros ambientes, crie um atalho de teclado que execute:
  ```bash
  ~/.local/bin/voz-rapida --toggle
  ```

### macOS

> ⚠️ **Experimental:** o suporte a macOS ainda não foi testado em um Mac de verdade. Se encontrar problemas, [abra uma issue](https://github.com/ederfmatos/voz-rapida/issues).

1. Instale o Python 3.10+, pelo [Homebrew](https://brew.sh/) (`brew install python`) ou pelo [python.org](https://www.python.org/downloads/macos/).
2. Rode `./install.sh`, como mostrado acima. Funciona em Apple Silicon e Intel.
3. Na primeira gravação, autorize o Python em **Ajustes do Sistema → Privacidade e Segurança**:
   - **Microfone:** para gravar.
   - **Monitoramento de Entrada:** para o atalho global. Depois de autorizar, reinicie o app com `voz-rapida --quit && voz-rapida --daemon &`.

**Trocar o atalho:** `⌃⌥Espaço` conflita com a troca de idioma do teclado se você tiver mais de uma fonte de entrada. Para usar outro, reinstale passando o atalho desejado:

```bash
VOZ_RAPIDA_HOTKEY="cmd+shift+d" ./install.sh
```

São aceitos os modificadores `ctrl`, `alt`/`option`, `cmd` e `shift`, combinados com uma tecla `a`–`z`, `space` ou `f1`–`f12`.

O app inicia junto com o sistema via LaunchAgent (`~/Library/LaunchAgents/com.ederfmatos.vozrapida.plist`).

## Uso

| Ação | Como |
|---|---|
| Começar a gravar | Atalho, clique no ícone ou `voz-rapida` no terminal |
| Parar e copiar | Atalho de novo, botão **■ Parar** / clique no widget (Linux) ou **Parar e copiar** no menu (macOS) |
| Colar | `Ctrl+V` / `⌘V` |
| Ver histórico | Menu do ícone → **Abrir histórico** |

Linha de comando:

```bash
voz-rapida            # alterna gravação (inicia o app se preciso)
voz-rapida --toggle   # idem
voz-rapida --record   # só começa a gravar
voz-rapida --daemon   # só inicia o app
voz-rapida --quit     # encerra
```

O histórico fica em:
- **Linux:** `~/.local/share/voz-rapida/historico.txt`
- **macOS:** `~/Library/Application Support/VozRapida/historico.txt`

## Dicas

- Fale normalmente e faça pequenas pausas entre as frases. São elas que permitem transcrever durante a fala.
- Com o app aberto, o modelo fica carregado na memória (cerca de 1–1,5 GB de RAM). É isso que permite começar a gravar instantaneamente.
- Falar mais de 20 s sem nenhuma pausa força um corte no ponto mais silencioso, o que pode gerar um ponto final no meio da frase.

## Desinstalar

```bash
./uninstall.sh        # mantém o histórico e o modelo baixado
./uninstall.sh --all  # apaga tudo
```

## Solução de problemas

| Problema | Solução |
|---|---|
| Ícone não aparece (GNOME) | Instale ou ative a extensão *AppIndicator and KStatusNotifierItem Support* |
| "Nada reconhecido" | Confira o microfone padrão nas configurações de som. No macOS, a permissão de Microfone |
| Atalho não funciona (macOS) | Permissão de *Monitoramento de Entrada* + reiniciar o app |
| Logs | Linux: `~/.local/share/voz-rapida/voz-rapida.log` · macOS: `~/Library/Application Support/VozRapida/voz-rapida.log` |

## Licença

[MIT](LICENSE). O modelo Parakeet TDT 0.6B v3 é distribuído pela NVIDIA sob a licença [CC-BY-4.0](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3).
