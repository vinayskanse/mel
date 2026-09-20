"""HTTP and TCP boundary for audio adapters, guesses, teachers and rewards.

Run from the repository root with:

    python -m learning.service

Two ways in, because there are two kinds of caller.

HTTP on FLY_PORT (8020) is for anything on the desk: arm the ears, ask for a
name now, post a clip, see what the fly remembers. Clips are raw mono PCM16 at
16 kHz in the request body, which is what the board records and what ffmpeg
gives you, so `curl --data-binary` is enough to drive the whole thing.

Plain TCP on FLY_PORT + 1 is for the board, and speaks the deskbuddy's song
protocol so the firmware is a port rather than a rewrite:

    board -> host   1 = audio chunk (16 kHz mono PCM16), 2 = end
    host  -> board  1 = four lines - mood, what to show, title, artist -
                        or empty when there is nothing to say

The fourth line is new. The deskbuddy sent back "title\\nartist" and drew it
under the face; the fly also needs to know which face to pull while the bubble
is up, and that is cheaper to send than to work out twice.
"""

from __future__ import annotations

import json
import os
import socketserver
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import audio
from .ears import Ears
from .memory import LearningMemory
from .models import Reward
from .providers import ShazamTeacher, SongTeacher, StaticTeacher, Teacher

MAX_CLIP = 16 * audio.BOARD_RATE * 2      # refuse more than sixteen seconds


class LearningApp:
    def __init__(self, memory: LearningMemory, teacher: Teacher, ears: Ears | None = None):
        self.memory = memory
        self.teacher = teacher
        self.ears = ears

    def hear(self, fingerprint: str) -> dict[str, Any]:
        """The string-keyed path: no audio, just a name for a made-up key."""
        local = self.memory.lookup(fingerprint)
        if local is not None:
            return {"mode": "guess", "answer": local.as_dict()}

        label = self.teacher.identify(fingerprint)
        if label is None:
            return {"mode": "unknown", "answer": None}
        taught = self.memory.remember(fingerprint, label, "teacher")
        return {"mode": "teach", "answer": taught.as_dict()}

    def clip(self, pcm: bytes, rate: int = audio.BOARD_RATE) -> dict[str, Any]:
        """The audio path: guess, ask if the guess failed, remember either way."""
        if self.ears is None:
            return {"error": "no ears: the service was started without audio"}
        return self.ears.hear(pcm, rate).as_dict()

    def reward(self, fingerprint: str, kind: str, amount: float = 1.0) -> dict[str, Any]:
        updated = self.memory.reward(Reward(fingerprint, kind, amount))
        return {"answer": updated.as_dict()}


def make_handler(app: LearningApp):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, payload: dict[str, Any], status: int = 200) -> None:
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send({"ok": True, "memories": len(app.memory),
                            "ears": app.ears is not None,
                            "armed": bool(app.ears and app.ears.armed)})
                return
            if self.path == "/memories":
                self._send({"memories": [item.as_dict() for item in app.memory.all()]})
                return
            self._send({"error": "not found"}, 404)

        def do_POST(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > MAX_CLIP:
                    self._send({"error": "clip too long"}, 413)
                    return
                raw = self.rfile.read(length)

                # A click on `+`: ears on or off. A double click: name it now.
                if self.path == "/listen":
                    if app.ears is None:
                        self._send({"error": "no ears"}, 400)
                        return
                    body = json.loads(raw) if raw else {}
                    said = app.ears.arm(bool(body.get("arm", True)))
                    self._send({"armed": app.ears.armed, "say": said.as_dict()})
                    return
                if self.path == "/identify":
                    if app.ears is None:
                        self._send({"error": "no ears"}, 400)
                        return
                    app.ears.ask_now()
                    self._send({"armed": True, "asking": True})
                    return
                if self.path == "/clip":
                    rate = int(self.headers.get("X-Sample-Rate", audio.BOARD_RATE))
                    self._send(app.clip(raw, rate))
                    return

                body = json.loads(raw)
                if self.path == "/hear":
                    self._send(app.hear(body["fingerprint"]))
                    return
                if self.path == "/reward":
                    self._send(app.reward(body["fingerprint"], body["kind"],
                                          float(body.get("amount", 1.0))))
                    return
                self._send({"error": "not found"}, 404)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                self._send({"error": str(error)}, 400)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


# ---- the board's own port ---------------------------------------------------

def recv_exactly(conn, n: int) -> bytes:
    out = bytearray()
    while len(out) < n:
        piece = conn.recv(n - len(out))
        if not piece:
            raise ConnectionError("board went away")
        out += piece
    return bytes(out)


def send_frame(conn, kind: int, payload: bytes) -> None:
    conn.sendall(struct.pack(">BI", kind, len(payload)) + payload)


def make_song_handler(app: LearningApp):
    class SongHandler(socketserver.BaseRequestHandler):
        """One clip from the board in, one thing to show out."""

        def handle(self) -> None:
            conn = self.request
            conn.settimeout(15)
            pcm = bytearray()
            try:
                while True:
                    kind, length = struct.unpack(">BI", recv_exactly(conn, 5))
                    payload = recv_exactly(conn, length) if length else b""
                    if kind == 1:
                        pcm += payload
                        if len(pcm) > MAX_CLIP:
                            break
                    elif kind == 2:
                        break
            except (ConnectionError, OSError) as error:
                print(f"[song] dropped while recording: {error}")
                return

            seconds = len(pcm) / (audio.BOARD_RATE * 2)
            result = app.clip(bytes(pcm))
            say = result.get("say") or {}
            print(f"[song] {seconds:.1f}s -> {result.get('mode')}: "
                  f"{say.get('text', '')!r}"
                  + ("  (asked Shazam)" if result.get("asked") else ""),
                  flush=True)   # so a piped log keeps up with the session
            lines = "\n".join([say.get("mood", "IDLE"), say.get("text", ""),
                               say.get("title", ""), say.get("artist", "")])
            try:
                send_frame(conn, 1, lines.encode("ascii", "ignore")
                           if say.get("text") else b"")
            except OSError as error:
                print(f"  board went away: {error}")

    return SongHandler


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    path = Path(os.environ.get("FLY_MEMORY", "learning/data/memories.json"))
    port = int(os.environ.get("FLY_PORT", "8020"))
    memory = LearningMemory(path)

    shazam = ShazamTeacher.from_env()
    ears = Ears(memory, shazam)
    ears.arm(True)                       # the desk has no buttons; start listening
    app = LearningApp(memory, StaticTeacher({}), ears)

    songs = Server(("0.0.0.0", port + 1), make_song_handler(app))
    threading.Thread(target=songs.serve_forever, daemon=True).start()

    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(app))
    print(f"learning service on http://0.0.0.0:{port}  ({len(memory)} songs remembered)")
    print(f"board song protocol on port {port + 1}"
          + ("" if shazam.ready else "  (no SHAZAM_API_KEY in .env: guesses only)"))
    server.serve_forever()


if __name__ == "__main__":
    main()
