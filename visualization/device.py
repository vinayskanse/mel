"""The link to the board: one TCP line protocol, and a beacon so it can find us.

The FlyBuddy firmware was standalone -- no WiFi, no network, nothing to
configure. This keeps as much of that as possible. The board is not given an
address, a hostname or a port to hold: it joins the WiFi, listens for a UDP
broadcast that says where the laptop is, and opens one socket to it. Unplug the
laptop, move to another network, get a different DHCP lease, and the board finds
it again on its own within a couple of seconds.

The protocol is newline-terminated ASCII, host to board, because everything the
host has to say fits in a word and a number and the firmware then needs no
parser worth the name:

    MOOD <NAME> <seconds>    pull this face; 0 seconds means hold it
    AUTO                     stop overriding, go back to choosing your own
    FEED                     a crumb goes down; it eats, then looks pleased
    SAY <text>               the bubble's first line; empty clears the bubble
    SUB <text>               the bubble's second line
    PING                     keep the socket honest

Board to host is `HELLO <name>` and `PONG`, and nothing else. The board has
never had anything to report that the host did not already know.

Sends never block the caller: a board that has gone to sleep mid-write would
otherwise stall the simulation thread that is writing to it, and the fly's face
is not worth a frame of the brain. A write that fails drops that board.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Any

PORT = 8022
BEACON_PORT = 8023
BEACON_EVERY = 2.0
MAGIC = b"flybuddy"

# The board drops a connection that has said nothing for twenty seconds, which
# is how it notices a laptop that slept rather than hung up. A fly can easily go
# a minute without a face to change, so the silence has to be broken on purpose
# or the board would reconnect every twenty seconds all evening.
PING_EVERY = 6.0

# Moods the firmware knows, from fly.h. Anything else is refused here rather
# than sent and silently ignored at the other end.
MOODS = {"IDLE", "HAPPY", "EXCITED", "EATING", "SLEEPING",
         "DANCING", "CURIOUS", "ANGRY", "LETMEOUT", "LOWBATT"}


def _clean(text: str, width: int = 40) -> str:
    """ASCII only and short, because the board draws into a fixed band with a
    font that has no accents. Cutting here rather than there means the host log
    shows exactly what the fly is showing."""
    out = "".join(ch for ch in text if 32 <= ord(ch) < 127).strip()
    return out if len(out) <= width else out[:width - 1].rstrip() + "~"


class DeviceLink:
    """Every board on the network, and the last thing each was told."""

    def __init__(self, port: int = PORT, beacon_port: int = BEACON_PORT,
                 announce: bool = True):
        self.port = port
        self.beacon_port = beacon_port
        self.announce = announce
        self._boards: dict[socket.socket, str] = {}
        self._lock = threading.Lock()
        # What a board that connects late needs in order to catch up. Only the
        # bubble and the face persist; FEED is a moment, not a state.
        self._state: list[str] = []
        self.started = False

    # ---- lifecycle --------------------------------------------------------
    def start(self) -> None:
        threading.Thread(target=self._accept, daemon=True).start()
        threading.Thread(target=self._heartbeat, daemon=True).start()
        if self.announce:
            threading.Thread(target=self._beacon, daemon=True).start()
        self.started = True

    def _heartbeat(self) -> None:
        while True:
            time.sleep(PING_EVERY)
            if self._boards:
                self.ping()

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._boards)

    def _accept(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind(("0.0.0.0", self.port))
        except OSError as error:
            print(f"[device] cannot listen on {self.port}: {error}")
            return
        srv.listen(4)
        while True:
            try:
                conn, addr = srv.accept()
            except OSError:
                break
            conn.settimeout(5)
            # Nagle would hold a 12-byte MOOD line waiting for company, which on
            # a face that is meant to react is exactly the wrong trade.
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            with self._lock:
                self._boards[conn] = f"{addr[0]}:{addr[1]}"
                catch_up = list(self._state)
            print(f"[device] board at {addr[0]} connected ({self.count} now)")
            for line in catch_up:
                self._write(conn, line)
            threading.Thread(target=self._drain, args=(conn,), daemon=True).start()

    def _drain(self, conn: socket.socket) -> None:
        """Read whatever the board says and throw it away, so a half-closed
        socket is noticed here rather than on the next write."""
        try:
            while True:
                if not conn.recv(128):
                    break
        except OSError:
            pass
        finally:
            self._drop(conn)

    def _drop(self, conn: socket.socket) -> None:
        with self._lock:
            where = self._boards.pop(conn, None)
        try:
            conn.close()
        except OSError:
            pass
        if where:
            print(f"[device] board at {where} gone ({self.count} left)")

    def _beacon(self) -> None:
        """Say where we are, twice a second's worth, forever.

        Broadcast rather than mDNS: an ESP32 can answer a UDP packet in twenty
        lines, and guest networks that block multicast often still pass
        broadcast. Networks with client isolation pass neither, and then the
        board simply never connects -- which is why nothing else depends on it.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        payload = MAGIC + b" " + str(self.port).encode()
        while True:
            try:
                sock.sendto(payload, ("255.255.255.255", self.beacon_port))
            except OSError:
                pass
            time.sleep(BEACON_EVERY)

    # ---- talking ----------------------------------------------------------
    def _write(self, conn: socket.socket, line: str) -> bool:
        try:
            conn.sendall(line.encode("ascii", "ignore") + b"\n")
            return True
        except OSError:
            return False

    def _send(self, lines: list[str], remember: list[str] | None = None) -> None:
        if remember is not None:
            with self._lock:
                self._state = remember
        with self._lock:
            boards = list(self._boards)
        for conn in boards:
            for line in lines:
                if not self._write(conn, line):
                    self._drop(conn)
                    break

    def apply(self, reaction: Any, say: str | None = None,
              sub: str = "") -> list[str]:
        """Turn one Reaction into what the board should be told, and tell it.

        `say` of None leaves whatever is in the bubble alone; "" clears it.
        The distinction matters: a thumbs-up should not wipe the song title off
        the fly's face on its way to making it eat.

        Returns the lines, so a run with no board attached still shows in the
        log exactly what a board would have been sent.
        """
        lines: list[str] = []
        if getattr(reaction, "auto", False):
            lines.append("AUTO")
        mood = getattr(reaction, "mood", "")
        if mood:
            if mood not in MOODS:
                raise ValueError(f"{mood!r} is not one of the faces in fly.h")
            lines.append(f"MOOD {mood} {getattr(reaction, 'hold', 0.0):.1f}")
        if getattr(reaction, "feed", False):
            lines.append("FEED")
        if say is not None:
            lines.append(f"SAY {_clean(say)}")
            lines.append(f"SUB {_clean(sub)}")

        # A crumb is an event and must not be replayed at a board that connects
        # ten minutes later; a face and a bubble are state and must be. A
        # reaction that says nothing about the bubble leaves the remembered
        # SAY/SUB in place rather than dropping them from the catch-up.
        keep = [ln for ln in lines if ln != "FEED"]
        if keep:
            # AUTO cancels a held face, so it also cancels a remembered one --
            # otherwise a board connecting later would be handed a MOOD the fly
            # had already been released from.
            spent = {k.split(" ", 1)[0] for k in keep}
            if "AUTO" in spent:
                spent.add("MOOD")
            with self._lock:
                held = [ln for ln in self._state if ln.split(" ", 1)[0] not in spent]
            self._send(lines, remember=held + keep)
        else:
            self._send(lines)
        return lines

    def ping(self) -> None:
        self._send(["PING"])
