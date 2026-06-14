#!/usr/bin/env python3
"""
LNCP - Local Network Chat Protocol (version 1.0).

Shared library defining the protocol constants, message builders, and TCP
framing used by both the Initiator and Recipient apps. See
PROTOCOL_SPECIFICATION.md for the full design.
"""

from __future__ import annotations

import json
import socket
import struct
import uuid as _uuid
from datetime import datetime, timezone

PROTO_NAME    = "LNCP"
PROTO_VERSION = "1.0"
PROTO         = f"{PROTO_NAME}/{PROTO_VERSION}"

UDP_PORT      = 54321        # well-known port recipients listen on for DISCOVER
ENCODING      = "utf-8"
BUFFER_SIZE   = 4096
MAX_FRAME     = 1 << 20      # 1 MiB cap on a single TCP message (anti-DoS guard)

DISCOVER = "DISCOVER"
HELLO    = "HELLO"
ACCEPT   = "ACCEPT"
REJECT   = "REJECT"
TEXT     = "TEXT"
ACK      = "ACK"
BYE      = "BYE"

ERR_UNKNOWN_UUID     = "UNKNOWN_UUID"
ERR_DEADLINE_EXPIRED = "DEADLINE_EXPIRED"
ERR_VERSION_MISMATCH = "VERSION_MISMATCH"
ERR_PROTOCOL         = "PROTOCOL_ERROR"


class ProtocolError(Exception):
    """Raised when a received message violates the LNCP wire format."""


def new_uuid() -> str:
    return str(_uuid.uuid4())


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _base(msg_type: str, request_id: str) -> dict:
    return {
        "proto": PROTO,
        "type":  msg_type,
        "id":    request_id,
        "ts":    now_iso(),
    }


def make_discover(recipient: str, deadline_ts: float, tcp_port: int,
                  request_id: str) -> dict:
    msg = _base(DISCOVER, request_id)
    msg.update(recipient=recipient, deadline=deadline_ts, tcp_port=tcp_port)
    return msg


def make_hello(request_id: str, sender: str) -> dict:
    msg = _base(HELLO, request_id)
    msg.update(sender=sender)
    return msg


def make_accept(request_id: str, info: str = "Handshake accepted.") -> dict:
    msg = _base(ACCEPT, request_id)
    msg.update(info=info)
    return msg


def make_reject(request_id: str, code: str, reason: str) -> dict:
    msg = _base(REJECT, request_id)
    msg.update(code=code, reason=reason)
    return msg


def make_text(request_id: str, seq: int, body: str) -> dict:
    msg = _base(TEXT, request_id)
    msg.update(seq=seq, body=body)
    return msg


def make_ack(request_id: str, seq: int) -> dict:
    msg = _base(ACK, request_id)
    msg.update(seq=seq)
    return msg


def make_bye(request_id: str, reason: str = "Session closed.") -> dict:
    msg = _base(BYE, request_id)
    msg.update(reason=reason)
    return msg


def send_frame(sock: socket.socket, msg: dict) -> None:
    raw = json.dumps(msg).encode(ENCODING)
    if len(raw) > MAX_FRAME:
        raise ProtocolError(f"Outgoing message too large ({len(raw)} bytes).")
    sock.sendall(struct.pack(">I", len(raw)) + raw)


def recv_frame(sock: socket.socket) -> dict:
    header = _recv_exact(sock, 4)
    (length,) = struct.unpack(">I", header)
    if length == 0 or length > MAX_FRAME:
        raise ProtocolError(f"Illegal frame length: {length}.")
    raw = _recv_exact(sock, length)
    try:
        msg = json.loads(raw.decode(ENCODING))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProtocolError(f"Frame payload is not valid JSON: {exc}") from exc
    if not isinstance(msg, dict) or "type" not in msg:
        raise ProtocolError("Frame is not a valid LNCP message object.")
    return msg


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Connection closed by peer.")
        buf.extend(chunk)
    return bytes(buf)
