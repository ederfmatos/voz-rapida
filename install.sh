#!/usr/bin/env bash
# Instala o Voz Rápida para o usuário atual (Linux ou macOS). Não usa sudo.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HOME/.local/bin"
OS="$(uname -s)"

say()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m  %s\n' "$*" >&2; }
die()  { printf '\033[1;31mxx\033[0m  %s\n' "$*" >&2; exit 1; }

case "$OS" in
  Linux)  DATA="${XDG_DATA_HOME:-$HOME/.local/share}/voz-rapida" ;;
  Darwin) DATA="$HOME/Library/Application Support/VozRapida" ;;
  *)      die "Sistema não suportado: $OS (use Linux ou macOS)." ;;
esac
VENV="$DATA/venv"
mkdir -p "$DATA" "$BIN"

# ---------- pré-requisitos ----------
if [ "$OS" = Linux ]; then
  PY=/usr/bin/python3
  [ -x "$PY" ] || PY="$(command -v python3 || true)"
  [ -n "$PY" ] || die "python3 não encontrado."
  if ! "$PY" -c "import gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk" 2>/dev/null; then
    die "Faltam as bibliotecas GTK para Python. Instale e rode de novo:
     Debian/Ubuntu/Mint/Zorin/Pop!_OS: sudo apt install python3-gi gir1.2-gtk-3.0 python3-venv
     Fedora:                          sudo dnf install python3-gobject gtk3
     Arch/Manjaro:                    sudo pacman -S python-gobject gtk3"
  fi
  if ! command -v pw-record >/dev/null && ! command -v arecord >/dev/null; then
    die "Nenhum gravador de áudio encontrado. Instale o pw-record (PipeWire) ou o arecord (ALSA):
     Debian/Ubuntu: sudo apt install pipewire-bin   (ou alsa-utils)
     Fedora:        sudo dnf install pipewire-utils
     Arch:          sudo pacman -S pipewire"
  fi
  VENV_FLAGS=(--system-site-packages)   # reaproveita o PyGObject do sistema
else
  PY="$(command -v python3 || true)"
  [ -n "$PY" ] || die "python3 não encontrado. Instale com: brew install python  (ou pelo python.org)"
  VENV_FLAGS=()
fi
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
  || die "É preciso Python 3.10 ou mais novo (encontrado: $("$PY" --version))."

# ---------- ambiente Python ----------
say "Criando ambiente em $VENV"
if command -v uv >/dev/null; then
  uv venv -q --allow-existing "${VENV_FLAGS[@]}" -p "$PY" "$VENV"
  uv pip install -q -p "$VENV/bin/python" --reinstall-package voz-rapida "$REPO"
else
  "$PY" -m venv "${VENV_FLAGS[@]}" "$VENV" \
    || die "Falha ao criar o venv. No Debian/Ubuntu: sudo apt install python3-venv"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q --force-reinstall --no-deps "$REPO"
  "$VENV/bin/pip" install -q "$REPO"
fi

# ---------- comando voz-rapida ----------
LAUNCHER="$BIN/voz-rapida"
if [ "$OS" = Linux ]; then
  cat > "$LAUNCHER" <<EOF
#!/bin/sh
# voz-rapida: sem argumentos alterna a gravação (inicia o app se preciso).
if [ \$# -eq 0 ] || [ "\$1" = "--toggle" ]; then
  gdbus call --session --dest com.ederfmatos.VozRapida --object-path /com/ederfmatos/VozRapida \\
    --method org.gtk.Actions.Activate toggle '[]' '{}' >/dev/null 2>&1 && exit 0
  set -- --toggle
fi
exec "$VENV/bin/python" -m voz_rapida "\$@"
EOF
else
  cat > "$LAUNCHER" <<EOF
#!/bin/sh
# voz-rapida: sem argumentos alterna a gravação (inicia o app se preciso).
[ \$# -eq 0 ] && set -- --toggle
exec "$VENV/bin/python" -m voz_rapida "\$@"
EOF
fi
chmod +x "$LAUNCHER"
say "Comando instalado: $LAUNCHER"
case ":$PATH:" in *":$BIN:"*) ;; *) warn "$BIN não está no PATH; adicione-o ao seu shell." ;; esac

# ---------- integração com o sistema ----------
if [ "$OS" = Linux ]; then
  APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
  AUTOSTART="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
  mkdir -p "$APPS" "$AUTOSTART"
  cat > "$APPS/voz-rapida.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Voz Rápida
Comment=Ditado local em tempo real (Ctrl+Alt+Espaço)
Exec=$LAUNCHER --toggle
Icon=audio-input-microphone
Terminal=false
Categories=Utility;Audio;
Keywords=transcrição;ditado;voz;fala;speech;dictation;
EOF
  cat > "$AUTOSTART/voz-rapida.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Voz Rápida
Exec=$LAUNCHER --daemon
Icon=audio-input-microphone
Terminal=false
X-GNOME-Autostart-Delay=5
EOF
  say "Atalho no menu de aplicativos e início automático configurados"

  if command -v gsettings >/dev/null && gsettings list-schemas | grep -qx org.gnome.settings-daemon.plugins.media-keys; then
    "$PY" - "$LAUNCHER" <<'EOF'
import ast, subprocess, sys
base = "org.gnome.settings-daemon.plugins.media-keys"
path = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/voz-rapida/"
get = lambda *a: subprocess.run(["gsettings", "get", *a], capture_output=True, text=True).stdout.strip()
raw = get(base, "custom-keybindings")
current = [] if raw.startswith("@as") else ast.literal_eval(raw)
if path not in current:
    current.append(path)
    subprocess.run(["gsettings", "set", base, "custom-keybindings", str(current)], check=True)
key = f"{base}.custom-keybinding:{path}"
for k, v in (("name", "Voz Rápida"), ("command", sys.argv[1] + " --toggle"),
             ("binding", "<Control><Alt>space")):
    subprocess.run(["gsettings", "set", key, k, v], check=True)
EOF
    say "Atalho global Ctrl+Alt+Espaço configurado (GNOME)"
  else
    warn "Configure um atalho de teclado no seu ambiente gráfico executando: $LAUNCHER --toggle"
  fi
else
  PLIST="$HOME/Library/LaunchAgents/com.ederfmatos.vozrapida.plist"
  mkdir -p "$(dirname "$PLIST")"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.ederfmatos.vozrapida</string>
  <key>ProgramArguments</key>
  <array><string>$VENV/bin/python</string><string>-m</string><string>voz_rapida</string><string>--daemon</string></array>
  <key>EnvironmentVariables</key>
  <dict><key>VOZ_RAPIDA_HOTKEY</key><string>${VOZ_RAPIDA_HOTKEY:-ctrl+alt+space}</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><false/>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$DATA/voz-rapida.log</string>
  <key>StandardErrorPath</key><string>$DATA/voz-rapida.log</string>
</dict>
</plist>
EOF
  say "Início automático configurado ($PLIST)"
fi

# ---------- modelo ----------
say "Baixando o modelo de transcrição (~670 MB, só na primeira vez)…"
"$VENV/bin/python" -c "from voz_rapida.core import Engine; Engine().load()" 2>&1 \
  | grep -v -i 'unauthenticated\|HF_TOKEN' || true

# ---------- iniciar ----------
"$LAUNCHER" --quit >/dev/null 2>&1 || true
if [ "$OS" = Linux ]; then
  nohup "$LAUNCHER" --daemon >"$DATA/voz-rapida.log" 2>&1 &
else
  launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
fi

say "Pronto! O Voz Rápida está rodando."
if [ "$OS" = Linux ]; then
  echo "    Aperte Ctrl+Alt+Espaço (ou clique no ícone de microfone) para ditar."
else
  echo "    Aperte ${VOZ_RAPIDA_HOTKEY:-ctrl+alt+space} (ou clique no 🎙 da barra de menus) para ditar."
  echo "    Na primeira vez, autorize em Ajustes do Sistema → Privacidade e Segurança:"
  echo "      • Microfone  • Monitoramento de Entrada (para o atalho global)"
fi
