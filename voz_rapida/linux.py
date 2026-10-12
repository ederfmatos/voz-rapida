"""Interface Linux: ícone na bandeja (GTK) + widget flutuante."""

import os
import sys
import threading

# O ícone de bandeja (XEmbed) e o posicionamento do widget precisam de X11;
# no Wayland o app roda via XWayland.
os.environ.setdefault("GDK_BACKEND", "x11")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from .core import Engine, Session, history_path, save_history  # noqa: E402

APP_ID = "com.ederfmatos.VozRapida"
HOTKEY_HINT = "Ctrl+Alt+Espaço"


class Overlay(Gtk.Window):
    """Widget flutuante: mostra o texto ao vivo; clique para parar."""

    def __init__(self, on_click):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.stick()
        visual = self.get_screen().get_rgba_visual()
        if visual and self.get_screen().is_composited():
            self.set_visual(visual)
            self.set_app_paintable(True)
            self.connect("draw", self._clear)

        css = Gtk.CssProvider()
        css.load_from_data(b"""
            .vr-box { background: rgba(28,28,30,0.94); border-radius: 14px;
                      padding: 10px 14px; }
            .vr-box label { color: #f2f2f2; }
            .vr-status { font-weight: bold; }
            .vr-box .vr-dot { color: #ff453a; font-size: 14px; }
            .vr-box .vr-dot.idle { color: #30d158; }
            .vr-box .vr-dot.busy { color: #ffd60a; }
            .vr-stop { background: #ff453a; color: white; border: none;
                       border-radius: 8px; padding: 2px 12px; box-shadow: none;
                       background-image: none; text-shadow: none; }
            .vr-stop label { color: white; font-weight: bold; }
        """)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        events = Gtk.EventBox()
        events.set_visible_window(False)
        events.connect("button-press-event", lambda *_: on_click())
        self.add(events)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.get_style_context().add_class("vr-box")
        events.add(box)

        top = Gtk.Box(spacing=8)
        self.dot = Gtk.Label(label="●")
        self.dot.get_style_context().add_class("vr-dot")
        self.status = Gtk.Label(xalign=0)
        self.status.get_style_context().add_class("vr-status")
        self.button = Gtk.Button(label="■ Parar")
        self.button.get_style_context().add_class("vr-stop")
        self.button.set_can_focus(False)
        self.button.connect("clicked", lambda *_: on_click())
        top.pack_start(self.dot, False, False, 0)
        top.pack_start(self.status, True, True, 0)
        top.pack_end(self.button, False, False, 0)
        box.pack_start(top, False, False, 0)

        self.text = Gtk.Label(xalign=0, yalign=0)
        self.text.set_line_wrap(True)
        self.text.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.text.set_max_width_chars(60)
        self.text.set_width_chars(60)
        self.text.set_lines(4)
        self.text.set_ellipsize(Pango.EllipsizeMode.START)
        box.pack_start(self.text, False, False, 0)

    @staticmethod
    def _clear(widget, cr):
        import cairo
        cr.set_source_rgba(0, 0, 0, 0)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        return False

    def place(self):
        display = Gdk.Display.get_default()
        mon = display.get_primary_monitor() or display.get_monitor(0)
        geo = mon.get_workarea()
        w, h = self.get_size()
        self.move(geo.x + (geo.width - w) // 2, geo.y + geo.height - h - 24)

    def set_state(self, state, status):
        ctx = self.dot.get_style_context()
        for c in ("idle", "busy"):
            ctx.remove_class(c)
        if state != "rec":
            ctx.add_class(state)
        self.status.set_text(status)
        self.button.set_visible(state == "rec")

    def set_text(self, committed, partial):
        tail = committed[-400:]
        markup = GLib.markup_escape_text(tail)
        if partial:
            sep = " " if tail else ""
            markup += sep + '<span alpha="60%">' + GLib.markup_escape_text(partial) + "</span>"
        self.text.set_markup(markup or '<span alpha="60%">Fale…</span>')


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.engine = Engine()
        self.session = None
        self.hide_timer = 0

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.hold()
        for name, cb in (("toggle", self.toggle), ("quit", self.quit)):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda *_, cb=cb: cb())
            self.add_action(action)

        self.overlay = Overlay(self.toggle)
        self.tray = Gtk.StatusIcon()
        self.tray.set_title("Voz Rápida")
        self.tray.connect("activate", lambda *_: self.toggle())
        self.tray.connect("popup-menu", self._menu)
        self._tray_state("loading")
        threading.Thread(target=self._load_model, daemon=True).start()

    def do_command_line(self, cmdline):
        args = cmdline.get_arguments()[1:]
        if "--quit" in args:
            self.quit()
        elif "--toggle" in args:
            self.toggle()
        elif "--record" in args and not self.session:
            self.toggle()
        return 0

    def _load_model(self):
        self.engine.load()
        GLib.idle_add(self._model_ready)

    def _model_ready(self):
        if not self.session:
            self._tray_state("idle")
        elif self.session.recording:
            self._tray_state("rec")

    # ---- bandeja ----
    def _tray_state(self, state):
        icon, tip = {
            "loading": ("content-loading-symbolic", "Voz Rápida — carregando modelo…"),
            "idle": ("audio-input-microphone-symbolic",
                     f"Voz Rápida — clique ou {HOTKEY_HINT} para ditar"),
            "rec": ("media-record", "Voz Rápida — gravando (clique para parar)"),
            "busy": ("content-loading-symbolic", "Voz Rápida — transcrevendo…"),
        }[state]
        self.tray.set_from_icon_name(icon)
        self.tray.set_tooltip_text(tip)

    def _menu(self, icon, button, time_):
        menu = Gtk.Menu()
        label = "Parar e copiar" if self.session else "Gravar"
        for text, cb in ((label, self.toggle), ("Abrir histórico", self._history),
                         ("Sair", self.quit)):
            item = Gtk.MenuItem(label=text)
            item.connect("activate", lambda *_, cb=cb: cb())
            menu.append(item)
        menu.show_all()
        menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, time_)
        self._menu_ref = menu

    def _history(self):
        path = history_path()
        if os.path.exists(path):
            Gio.AppInfo.launch_default_for_uri(GLib.filename_to_uri(path), None)

    # ---- gravação ----
    def toggle(self):
        s = self.session
        if s is None:
            self._start()
        elif s.recording:
            s.stop()
            self._tray_state("busy")
            self._show("busy", "Transcrevendo o final…")

    def _start(self):
        if self.hide_timer:
            GLib.source_remove(self.hide_timer)
            self.hide_timer = 0
        s = self.session = Session(
            self.engine,
            on_update=lambda t, p: GLib.idle_add(self.overlay.set_text, t, p),
            on_done=lambda t: GLib.idle_add(self._done, t))
        self._tray_state("rec")
        self.overlay.set_text("", "")
        self._show("rec", self._rec_status(s))
        GLib.timeout_add(250, self._tick, s)

    def _rec_status(self, s):
        secs = s.elapsed()
        status = f"Gravando {secs // 60}:{secs % 60:02d}"
        if s.segmenter.saturated:
            status += "  ⚠ microfone saturado — reduza o volume de entrada"
        elif not self.engine.ready.is_set():
            status += " (carregando modelo…)"
        return status

    def _tick(self, s):
        if s is not self.session or not s.recording:
            return False
        self.overlay.set_state("rec", self._rec_status(s))
        return True

    def _done(self, text):
        self.session = None
        self._tray_state("idle")
        self.overlay.set_text(text, "")
        if text:
            for sel in (Gdk.SELECTION_CLIPBOARD, Gdk.SELECTION_PRIMARY):
                cb = Gtk.Clipboard.get(sel)
                cb.set_text(text, -1)
                cb.store()
            save_history(text)
            self._show("idle", "Copiado ✓  (Ctrl+V para colar)")
        else:
            self._show("idle", "Nada reconhecido")
        self.hide_timer = GLib.timeout_add(2500, self._hide)

    def _show(self, state, status):
        self.overlay.set_state(state, status)
        self.overlay.show_all()
        self.overlay.button.set_visible(state == "rec")
        self.overlay.place()

    def _hide(self):
        self.hide_timer = 0
        self.overlay.hide()
        return False


def main(args):
    return App().run([sys.argv[0], *args])
