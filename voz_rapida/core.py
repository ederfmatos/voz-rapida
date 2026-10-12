"""Núcleo multiplataforma: captura de áudio, segmentação e transcrição.

A fala é cortada em trechos nas pausas e cada trecho é transcrito enquanto
você ainda fala. Ao parar, só falta transcrever o último trecho.
"""

import collections
import os
import queue
import shutil
import subprocess
import sys
import threading
import time

import numpy as np

MODEL = "nemo-parakeet-tdt-0.6b-v3"
RATE = 16000
CHUNK = RATE // 10                 # 100 ms
PREROLL_CHUNKS = 3                 # áudio guardado antes da fala começar
PAUSE_CHUNKS = 6                   # 600 ms de silêncio fecha um trecho
MIN_SPEECH_CHUNKS = 3              # trechos com menos fala são ruído
MAX_SEG_CHUNKS = 200               # 20 s: força corte no ponto mais quieto
FORCE_CUT_FROM = 120               # ...procurando a partir de 12 s
PARTIAL_INTERVAL = 1.0             # s entre prévias do trecho atual
PARTIAL_MAX_CHUNKS = 120           # não gasta CPU com prévias de trechos longos

STOP = object()


def data_dir():
    if sys.platform == "darwin":
        path = os.path.expanduser("~/Library/Application Support/VozRapida")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        path = os.path.join(base, "voz-rapida")
    os.makedirs(path, exist_ok=True)
    return path


def history_path():
    return os.path.join(data_dir(), "historico.txt")


def save_history(text):
    with open(history_path(), "a", encoding="utf-8") as f:
        f.write(time.strftime("[%Y-%m-%d %H:%M] ") + text + "\n")


class Segmenter:
    """Detector de fala por energia com piso de ruído adaptativo."""

    def __init__(self, emit):
        self.emit = emit
        self.lock = threading.Lock()
        self.floor = None
        self.preroll = collections.deque(maxlen=PREROLL_CHUNKS)
        self.seg = []
        self.speech = 0
        self.silence = 0
        self.seg_id = 0

    def feed(self, x):
        rms = float(np.sqrt(np.mean(x * x)) + 1e-9)
        if self.floor is None:
            self.floor = rms
        elif rms < self.floor:
            self.floor = 0.7 * self.floor + 0.3 * rms
        else:
            self.floor = 0.995 * self.floor + 0.005 * rms
        is_speech = rms > max(3.0 * self.floor, 0.004)

        with self.lock:
            if not self.seg:
                if is_speech:
                    self.seg = list(self.preroll) + [x]
                    self.speech, self.silence = 1, 0
                else:
                    self.preroll.append(x)
                return

            self.seg.append(x)
            if is_speech:
                self.speech += 1
                self.silence = 0
            else:
                self.silence += 1

            if self.silence >= PAUSE_CHUNKS:
                keep = len(self.seg) - self.silence + 2
                if self.speech >= MIN_SPEECH_CHUNKS:
                    self._emit(self.seg[:keep])
                self._reset(self.seg[-PREROLL_CHUNKS:])
            elif len(self.seg) >= MAX_SEG_CHUNKS:
                tail = self.seg[FORCE_CUT_FROM:]
                cut = FORCE_CUT_FROM + int(np.argmin([np.mean(c * c) for c in tail])) + 1
                self._emit(self.seg[:cut])
                self.seg = self.seg[cut:]
                self.speech = len(self.seg)
                self.silence = 0

    def _emit(self, chunks):
        self.seg_id += 1
        self.emit(np.concatenate(chunks))

    def _reset(self, preroll):
        self.seg = []
        self.speech = self.silence = 0
        self.preroll = collections.deque(preroll, maxlen=PREROLL_CHUNKS)

    def snapshot(self):
        """(seg_id, áudio do trecho em andamento) para a prévia."""
        with self.lock:
            if self.speech < 5 or len(self.seg) > PARTIAL_MAX_CHUNKS:
                return self.seg_id, None
            return self.seg_id, np.concatenate(self.seg)

    def flush(self):
        with self.lock:
            if self.seg and self.speech >= 2:
                self._emit(self.seg[: len(self.seg) - max(self.silence - 2, 0)])
            self._reset([])


class Recorder:
    """Entrega blocos de 100 ms (float32, 16 kHz, mono) para on_chunk.

    Linux: pw-record (PipeWire) ou arecord (ALSA). macOS e fallback:
    sounddevice (PortAudio), reamostrando da taxa nativa do microfone.
    """

    def __init__(self, on_chunk, on_end):
        self.on_chunk = on_chunk
        self.on_end = on_end
        self.proc = None
        self.stream = None
        cmd = self._command()
        if cmd:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL)
            threading.Thread(target=self._read_pipe, daemon=True).start()
        else:
            self._start_sounddevice()

    @staticmethod
    def _command():
        if not sys.platform.startswith("linux"):
            return None
        if shutil.which("pw-record"):
            return ["pw-record", "--rate", str(RATE), "--channels", "1",
                    "--format", "s16", "--media-role", "Communication", "-"]
        if shutil.which("arecord"):
            return ["arecord", "-q", "-f", "S16_LE", "-r", str(RATE),
                    "-c", "1", "-t", "raw"]
        return None

    def _read_pipe(self):
        nbytes = CHUNK * 2
        buf = b""
        while True:
            data = self.proc.stdout.read(nbytes - len(buf))
            if not data:
                break
            buf += data
            if len(buf) == nbytes:
                self.on_chunk(np.frombuffer(buf, np.int16).astype(np.float32) / 32768.0)
                buf = b""
        self.on_end()

    def _start_sounddevice(self):
        import sounddevice as sd

        rate = int(sd.query_devices(kind="input")["default_samplerate"])
        blocks = queue.Queue()
        self._blocks = blocks

        def callback(indata, frames, t, status):
            blocks.put(indata[:, 0].copy())

        self.stream = sd.InputStream(samplerate=rate, channels=1,
                                     dtype="float32", callback=callback)
        self.stream.start()
        threading.Thread(target=self._read_blocks, args=(rate,), daemon=True).start()

    def _read_blocks(self, rate):
        pending = np.zeros(0, np.float32)    # na taxa nativa
        out = np.zeros(0, np.float32)        # já em 16 kHz
        step = rate / RATE
        while True:
            block = self._blocks.get()
            if block is None:
                break
            pending = np.concatenate([pending, block])
            n = int(len(pending) / step)
            if n:
                pos = np.arange(n) * step
                out = np.concatenate([out, np.interp(pos, np.arange(len(pending)),
                                                     pending).astype(np.float32)])
                pending = pending[int(n * step):]
            while len(out) >= CHUNK:
                self.on_chunk(out[:CHUNK])
                out = out[CHUNK:]
        self.on_end()

    def stop(self):
        if self.proc:
            self.proc.terminate()
        else:
            self.stream.stop()
            self.stream.close()
            self._blocks.put(None)


class Engine:
    """Modelo carregado uma vez e mantido em memória."""

    def __init__(self):
        self.model = None
        self.ready = threading.Event()
        self.lock = threading.Lock()

    def load(self):
        import onnx_asr
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = os.cpu_count() or 4
        self.model = onnx_asr.load_model(MODEL, quantization="int8",
                                         sess_options=opts)
        # aquece o modelo para a primeira transcrição não ser lenta
        self.model.recognize(np.zeros(RATE, np.float32), sample_rate=RATE)
        self.ready.set()

    def recognize(self, audio):
        self.ready.wait()
        try:
            with self.lock:
                return self.model.recognize(audio, sample_rate=RATE).strip()
        except Exception as e:  # noqa: BLE001
            print("erro na transcrição:", e, file=sys.stderr)
            return ""


class Session:
    """Uma gravação. on_update(texto, prévia) e on_done(texto) são chamados
    a partir de uma thread de trabalho — a interface deve repassá-los para
    a thread principal."""

    def __init__(self, engine, on_update=None, on_done=None):
        self.engine = engine
        self.on_update = on_update or (lambda *_: None)
        self.on_done = on_done or (lambda *_: None)
        self.queue = queue.Queue()
        self.segmenter = Segmenter(self.queue.put)
        self.committed = []
        self.partial = ""
        self.started = time.monotonic()
        self.recording = True
        self.done = False
        self.recorder = Recorder(self.segmenter.feed, self._audio_end)
        threading.Thread(target=self._work, daemon=True).start()

    def _audio_end(self):
        self.segmenter.flush()
        self.queue.put(STOP)

    def stop(self):
        if self.recording:
            self.recording = False
            self.recorder.stop()

    def elapsed(self):
        return int(time.monotonic() - self.started)

    def text(self):
        return " ".join(t for t in self.committed if t).strip()

    def _work(self):
        self.engine.ready.wait()
        last_partial = 0.0
        last_partial_len = 0
        while True:
            try:
                item = self.queue.get(timeout=0.1)
            except queue.Empty:
                if not self.recording or time.monotonic() - last_partial < PARTIAL_INTERVAL:
                    continue
                seg_id, audio = self.segmenter.snapshot()
                if audio is None or len(audio) - last_partial_len < RATE // 2:
                    continue
                text = self.engine.recognize(audio)
                last_partial = time.monotonic()
                last_partial_len = len(audio)
                if seg_id == self.segmenter.seg_id and self.queue.empty():
                    self.partial = text
                    self.on_update(self.text(), self.partial)
                continue

            if item is STOP:
                self.partial = ""
                self.done = True
                self.on_done(self.text())
                return
            self.committed.append(self.engine.recognize(item))
            self.partial = ""
            last_partial_len = 0
            self.on_update(self.text(), "")
