"""Interface macOS: item na barra de menus (rumps) + atalho global (Quartz)."""

import os
import socket
import subprocess
import sys
import threading
import time

import rumps

from .core import Engine, Session, data_dir, history_path, save_history

SOCKET = os.path.join(data_dir(), "voz-rapida.sock")
LOG = os.path.join(data_dir(), "voz-rapida.log")
DEFAULT_HOTKEY = "ctrl+alt+space"

MODIFIERS = {"ctrl": 1 << 18, "control": 1 << 18, "alt": 1 << 19, "option": 1 << 19,
             "cmd": 1 << 20, "command": 1 << 20, "shift": 1 << 17}
# códigos de tecla virtuais (layout ANSI) — independem do idioma do teclado
KEYCODES = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "o": 31, "u": 32,
    "i": 34, "p": 35, "l": 37, "j": 38, "k": 40, "n": 45, "m": 46, "space": 49,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98,
    "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
}


def parse_hotkey(spec):
    """'ctrl+alt+space' -> (máscara de modificadores, keycode)."""
    *mods, key = [p.strip().lower() for p in spec.split("+")]
    return sum(MODIFIERS[m] for m in mods), KEYCODES[key]


def send(command):
    """Envia um comando para a instância em execução. True se havia uma."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect(SOCKET)
            s.sendall(command.encode())
        return True
    except OSError:
        return False


def copy(text):
    env = dict(os.environ, LANG="en_US.UTF-8")
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), env=env, check=False)


class VozRapida(rumps.App):
    def __init__(self, record=False):
        super().__init__("Voz Rápida", title="⌛", quit_button=None)
        self.engine = Engine()
        self.session = None
        self.commands = []                # preenchido por outras threads
        self.flash_until = 0.0
        if record:
            self.commands.append("record")

        self.toggle_item = rumps.MenuItem("Gravar", callback=lambda _: self.toggle())
        self.live_item = rumps.MenuItem("")
        self.menu = [self.toggle_item, self.live_item, None,
                     rumps.MenuItem("Abrir histórico", callback=self._history),
                     rumps.MenuItem("Sair", callback=lambda _: rumps.quit_application())]

        try:  # sem ícone no Dock
            from AppKit import NSApplication
            NSApplication.sharedApplication().setActivationPolicy_(1)
        except Exception:  # noqa: BLE001
            pass

        threading.Thread(target=self.engine.load, daemon=True).start()
        threading.Thread(target=self._serve, daemon=True).start()
        self._install_hotkey(os.environ.get("VOZ_RAPIDA_HOTKEY", DEFAULT_HOTKEY))
        self.timer = rumps.Timer(self._tick, 0.15)
        self.timer.start()

    # ---- comandos externos (voz-rapida --toggle) ----
    def _serve(self):
        if os.path.exists(SOCKET):
            os.unlink(SOCKET)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(SOCKET)
        srv.listen(4)
        while True:
            conn, _ = srv.accept()
            with conn:
                self.commands.append(conn.recv(64).decode(errors="ignore").strip())

    # ---- atalho global ----
    def _install_hotkey(self, spec):
        try:
            import Quartz
            from CoreFoundation import (CFMachPortCreateRunLoopSource, CFRunLoopAddSource,
                                        CFRunLoopGetMain, kCFRunLoopCommonModes)
            mods, keycode = parse_hotkey(spec)
        except (ImportError, KeyError) as e:
            print(f"atalho desativado ({e})", file=sys.stderr)
            return

        relevant = sum(set(MODIFIERS.values()))

        def callback(proxy, type_, event, refcon):
            if type_ in (Quartz.kCGEventTapDisabledByTimeout,
                         Quartz.kCGEventTapDisabledByUserInput):
                Quartz.CGEventTapEnable(self._tap, True)
            elif (type_ == Quartz.kCGEventKeyDown
                  and Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode) == keycode
                  and Quartz.CGEventGetFlags(event) & relevant == mods
                  and not Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventAutorepeat)):
                self.commands.append("toggle")
            return event

        try:
            Quartz.CGRequestListenEventAccess()
        except AttributeError:
            pass
        self._tap_callback = callback
        self._tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown), callback, None)
        if self._tap is None:
            print("atalho global indisponível: permita o app em Ajustes do Sistema → "
                  "Privacidade e Segurança → Monitoramento de Entrada", file=sys.stderr)
            return
        source = CFMachPortCreateRunLoopSource(None, self._tap, 0)
        CFRunLoopAddSource(CFRunLoopGetMain(), source, kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(self._tap, True)

    # ---- laço da interface (thread principal) ----
    def _tick(self, _):
        while self.commands:
            cmd = self.commands.pop(0)
            if cmd == "toggle":
                self.toggle()
            elif cmd == "record" and not self.session:
                self.toggle()
            elif cmd == "quit":
                rumps.quit_application()

        s = self.session
        if s and s.done:
            self._done(s.text())
            s = None
        if s and s.recording:
            secs = s.elapsed()
            live = (s.text() + " " + s.partial).strip()
            tail = ("…" + live[-28:]) if len(live) > 28 else live
            self.title = f"🔴 {secs // 60}:{secs % 60:02d} {tail}".rstrip()
            self.live_item.title = ("⚠ Microfone saturado — reduza o volume de entrada"
                                    if s.segmenter.saturated else live[-80:] or "Fale…")
        elif s:
            self.title = "⏳"
        elif time.monotonic() < self.flash_until:
            pass
        else:
            self.title = "🎙" if self.engine.ready.is_set() else "⌛"
            self.live_item.title = ""
        self.toggle_item.title = "Parar e copiar" if s else "Gravar"

    def toggle(self):
        s = self.session
        if s is None:
            self.session = Session(self.engine)
        elif s.recording:
            s.stop()

    def _done(self, text):
        self.session = None
        if text:
            copy(text)
            save_history(text)
            self.title = "✅ Copiado"
            self.live_item.title = text[-80:]
        else:
            self.title = "🤷 Nada reconhecido"
        self.flash_until = time.monotonic() + 2.5

    def _history(self, _):
        if os.path.exists(history_path()):
            subprocess.run(["open", history_path()], check=False)


def main(args):
    for flag in ("--toggle", "--record", "--quit"):
        if flag in args and "--daemon" not in args:
            if send(flag[2:]) or flag == "--quit":
                return 0
            # nenhuma instância rodando: inicia uma em segundo plano já gravando
            with open(LOG, "a") as log:
                subprocess.Popen([sys.executable, "-m", "voz_rapida", "--daemon", "--record"],
                                 stdout=log, stderr=log, start_new_session=True)
            return 0
    if send("ping"):
        print("Voz Rápida já está rodando.")
        return 0
    VozRapida(record="--record" in args).run()
    return 0
