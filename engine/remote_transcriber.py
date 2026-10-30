"""Runs the Transcriber in a child process, so the AI libraries and model memory live outside the UI
process. A hung GPU call is fixed by killing the child, and unload() gives every byte back to Windows."""
import itertools
import multiprocessing as mp
import threading
import time

_SPAWN = mp.get_context("spawn")
_PARTIAL_WAIT_S = 2.0
_CALL_BASE_S = 120.0       # a call on a loaded engine that takes longer than this has hung
_FIRST_CALL_S = 1200.0     # the first call may download and load a model


def _serve(conn, kwargs):
    """Child process: own a real Transcriber and answer requests, one thread per request."""
    from .transcriber import Transcriber
    t = Transcriber(preload=False, **kwargs)
    send_lock = threading.Lock()

    def send(msg):
        with send_lock:
            conn.send(msg)

    def state():
        return {"device": t.device, "model_size": t.model_size, "compute_type": t.compute_type,
                "language": t.language, "loaded": t.model is not None, "loading": t.is_loading}

    t.on_status = lambda m: send(("status", m))
    t.on_progress = lambda p, n: send(("progress", p, n))

    def handle(cid, name, args):
        try:
            send(("ok", cid, getattr(t, name)(*args), state()))
        except Exception as e:
            send(("err", cid, repr(e), state()))

    while True:
        try:
            cid, name, args = conn.recv()
        except (EOFError, OSError):
            return  # the app is gone
        threading.Thread(target=handle, args=(cid, name, args), daemon=True).start()


class RemoteTranscriber:
    """Same surface the app uses on Transcriber; the child starts on first real use."""

    def __init__(self, model_size, device, compute_type, language):
        self.model_size, self.device, self.compute_type, self.language = model_size, device, compute_type, language
        self.on_status = None
        self.on_progress = None
        self.is_loading = False
        self._loaded = False
        self._proc = self._conn = None
        self._pending = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()       # spawn / kill
        self._send_lock = threading.Lock()

    @property
    def model(self):
        return True if self._loaded else None

    # -- process plumbing ---------------------------------------------------

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.is_alive()

    def _ensure(self):
        with self._lock:
            if self._alive():
                return
            kwargs = dict(model_size=self.model_size, device=self.device,
                          compute_type=self.compute_type, language=self.language)
            parent, child = _SPAWN.Pipe()
            proc = _SPAWN.Process(target=_serve, args=(child, kwargs), daemon=True, name="openflow-engine")
            proc.start()
            child.close()
            self._proc, self._conn = proc, parent
            threading.Thread(target=self._read, args=(parent,), daemon=True, name="openflow-engine-reader").start()

    def _read(self, conn):
        try:
            while True:
                msg = conn.recv()
                if msg[0] == "status":
                    if self.on_status:
                        self.on_status(msg[1])
                elif msg[0] == "progress":
                    if self.on_progress:
                        self.on_progress(msg[1], msg[2])
                else:
                    kind, cid, value, st = msg
                    self.device, self.model_size, self.compute_type = st["device"], st["model_size"], st["compute_type"]
                    self.language, self._loaded, self.is_loading = st["language"], st["loaded"], st["loading"]
                    slot = self._pending.pop(cid, None)
                    if slot:
                        slot[1] = (kind, value)
                        slot[0].set()
        except (EOFError, OSError):
            pass
        finally:
            if self._conn is conn:  # this child is gone: fail whoever still waits and forget its state
                self._loaded = self.is_loading = False
                for slot in list(self._pending.values()):
                    slot[1] = ("err", "engine stopped")
                    slot[0].set()
                self._pending.clear()

    def _kill(self):
        with self._lock:
            proc, self._proc, self._conn = self._proc, None, None
        self._loaded = self.is_loading = False
        if proc is not None:
            proc.kill()
            proc.join(2)

    def _call(self, name, args, timeout):
        """Round trip to the child; None timeout waits for the answer however long it takes."""
        self._ensure()
        cid, slot = next(self._ids), [threading.Event(), None]
        self._pending[cid] = slot
        try:
            with self._send_lock:
                self._conn.send((cid, name, args))
        except (OSError, AttributeError):
            self._pending.pop(cid, None)
            raise RuntimeError("engine stopped")
        if not slot[0].wait(timeout):
            self._pending.pop(cid, None)
            raise TimeoutError(f"engine call {name} timed out")
        kind, value = slot[1][0], slot[1][1]
        if kind == "err":
            raise RuntimeError(value)
        return value

    # -- Transcriber surface ------------------------------------------------

    def reload(self, model_size, device="cuda", compute_type="float16", language=None):
        self.model_size, self.device, self.compute_type = model_size, device, compute_type
        self.language = language or self.language
        self.is_loading = True
        try:
            self._call("reload", (model_size, device, compute_type, language), None)
        finally:
            self.is_loading = False

    def unload(self):
        self._kill()

    def reset_preview_budget(self):
        if self._alive():
            try:
                self._call("reset_preview_budget", (), 1.0)
            except Exception:
                pass

    def transcribe_partial(self, audio) -> str:
        if not self._loaded or not self._alive():
            return ""
        try:
            return self._call("transcribe_partial", (audio,), _PARTIAL_WAIT_S)
        except Exception:
            return ""  # a slow or dead preview must never hold up the dictation

    def transcribe(self, audio, language=None, initial_prompt=None):
        limit = (_CALL_BASE_S + 2 * len(audio) / 16000) if self._loaded else _FIRST_CALL_S
        try:
            return self._call("transcribe", (audio, language, initial_prompt), limit)
        except TimeoutError:
            print("[OpenFlow] Engine stopped responding; restarting it")
            self._kill()
            raise
