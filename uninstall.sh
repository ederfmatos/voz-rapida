#!/usr/bin/env bash
# Remove o Voz Rápida. O histórico e o modelo baixado são mantidos,
# a menos que você passe --all.
set -euo pipefail

OS="$(uname -s)"
case "$OS" in
  Linux)  DATA="${XDG_DATA_HOME:-$HOME/.local/share}/voz-rapida" ;;
  Darwin) DATA="$HOME/Library/Application Support/VozRapida" ;;
  *)      echo "Sistema não suportado: $OS" >&2; exit 1 ;;
esac

"$HOME/.local/bin/voz-rapida" --quit >/dev/null 2>&1 || true
rm -f "$HOME/.local/bin/voz-rapida"
rm -rf "$DATA/venv"

if [ "$OS" = Linux ]; then
  rm -f "${XDG_DATA_HOME:-$HOME/.local/share}/applications/voz-rapida.desktop" \
        "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/voz-rapida.desktop"
  if command -v gsettings >/dev/null && gsettings list-schemas | grep -qx org.gnome.settings-daemon.plugins.media-keys; then
    python3 - <<'EOF'
import ast, subprocess
base = "org.gnome.settings-daemon.plugins.media-keys"
path = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/voz-rapida/"
raw = subprocess.run(["gsettings", "get", base, "custom-keybindings"], capture_output=True, text=True).stdout.strip()
current = [] if raw.startswith("@as") else ast.literal_eval(raw)
if path in current:
    current.remove(path)
    subprocess.run(["gsettings", "set", base, "custom-keybindings", str(current) if current else "@as []"], check=True)
subprocess.run(["gsettings", "reset-recursively", f"{base}.custom-keybinding:{path}"])
EOF
  fi
else
  PLIST="$HOME/Library/LaunchAgents/com.ederfmatos.vozrapida.plist"
  launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
fi

if [ "${1:-}" = "--all" ]; then
  rm -rf "$DATA"
  rm -rf "${HF_HOME:-$HOME/.cache/huggingface}/hub/models--istupakov--parakeet-tdt-0.6b-v3-onnx"
  echo "Voz Rápida removido, incluindo histórico e modelo."
else
  echo "Voz Rápida removido. Histórico mantido em: $DATA"
  echo "(use ./uninstall.sh --all para apagar também o histórico e o modelo)"
fi
