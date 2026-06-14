#!/usr/bin/env python3
"""
LNCP (Local Network Chat Protocol) - Initiator Application.

The Initiator broadcasts a UDP DISCOVER request, listens on a TCP port,
validates the recipient's handshake, exchanges turn-based text messages, and
closes the session. See PROTOCOL_SPECIFICATION.md for the full design.

Usage:
    python initiator.py <recipient_nickname> [--port PORT] [--deadline SECS]
"""

from __future__ import annotations

import argparse
import json
import socket
import time

import lncp


class Initiator:
    def __init__(self, recipient: str, tcp_port: int, deadline_secs: int):
        self.recipient     = recipient
        self.tcp_port      = tcp_port
        self.deadline_secs = deadline_secs
        self.request_id    = lncp.new_uuid()
        self.deadline_ts   = time.time() + deadline_secs
        self.seq           = 0

    def send_broadcast(self) -> None:
        msg = lncp.make_discover(self.recipient, self.deadline_ts,
                                 self.tcp_port, self.request_id)
        raw = json.dumps(msg).encode(lncp.ENCODING)

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            sock.sendto(raw, ("<broadcast>", lncp.UDP_PORT))
            print(f"[INITIATOR] DISCOVER broadcast sent -> recipient='{self.recipient}', "
                  f"id={self.request_id}, deadline={self.deadline_secs}s, "
                  f"tcp_port={self.tcp_port}")
        finally:
            sock.close()

    def listen_for_connection(self) -> socket.socket | None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("", self.tcp_port))
        server.listen(1)

        timeout = max(0.0, self.deadline_ts - time.time())
        server.settimeout(timeout)
        print(f"[INITIATOR] Listening on TCP port {self.tcp_port} "
              f"(deadline in {timeout:.1f}s)...")

        try:
            conn, addr = server.accept()
            print(f"[INITIATOR] TCP connection accepted from {addr[0]}:{addr[1]}")
            return conn
        except socket.timeout:
            print("[INITIATOR] Deadline expired - no recipient connected.")
            return None
        finally:
            server.close()

    def perform_handshake(self, sock: socket.socket) -> bool:
        try:
            msg = lncp.recv_frame(sock)
        except (lncp.ProtocolError, ConnectionError, OSError) as exc:
            print(f"[INITIATOR] Failed to receive HELLO: {exc}")
            return False

        if msg.get("type") != lncp.HELLO:
            print(f"[INITIATOR] Expected HELLO, got '{msg.get('type')}'. Rejecting.")
            _try_send(sock, lncp.make_reject(self.request_id,
                                             lncp.ERR_PROTOCOL,
                                             "Expected HELLO handshake."))
            return False

        if not str(msg.get("proto", "")).startswith(lncp.PROTO_NAME + "/"):
            print("[INITIATOR] Unknown protocol family. Rejecting.")
            _try_send(sock, lncp.make_reject(self.request_id,
                                             lncp.ERR_VERSION_MISMATCH,
                                             "Unsupported protocol."))
            return False

        if msg.get("id") != self.request_id:
            print("[INITIATOR] UUID mismatch. Rejecting.")
            _try_send(sock, lncp.make_reject(self.request_id,
                                             lncp.ERR_UNKNOWN_UUID,
                                             "UUID does not match request."))
            return False

        if time.time() > self.deadline_ts:
            print("[INITIATOR] Deadline expired during handshake. Rejecting.")
            _try_send(sock, lncp.make_reject(self.request_id,
                                             lncp.ERR_DEADLINE_EXPIRED,
                                             "Response deadline has passed."))
            return False

        lncp.send_frame(sock, lncp.make_accept(self.request_id,
                                               "Handshake accepted. Welcome!"))
        print(f"[INITIATOR] Handshake ACCEPTED with '{msg.get('sender', 'unknown')}'.")
        return True

    def exchange_messages(self, sock: socket.socket) -> None:
        print("\n[INITIATOR] Session open. Type a message and press Enter. "
              "Type '/quit' to close.\n")

        while True:
            # The Initiator transmits first each turn (simplex discipline).
            try:
                text = input("You -> ")
            except EOFError:
                text = "/quit"

            if text.strip().lower() == "/quit":
                _try_send(sock, lncp.make_bye(self.request_id,
                                              "Closed by initiator."))
                print("[INITIATOR] BYE sent. Closing.")
                break

            self.seq += 1
            try:
                lncp.send_frame(sock, lncp.make_text(self.request_id,
                                                     self.seq, text))
                reply = lncp.recv_frame(sock)
            except (lncp.ProtocolError, ConnectionError, OSError) as exc:
                print(f"[INITIATOR] Connection lost: {exc}")
                break

            if not self._handle_reply(reply):
                break

        _close(sock)
        print("[INITIATOR] Connection closed.")

    def _handle_reply(self, reply: dict) -> bool:
        """Return False when the session should end."""
        rtype = reply.get("type")
        if rtype == lncp.BYE:
            print(f"[INITIATOR] Recipient closed the session: "
                  f"{reply.get('reason', '')}")
            return False
        if rtype == lncp.ACK:
            print(f"  [ACK for seq={reply.get('seq')}]")
            return True
        if rtype == lncp.TEXT:
            print(f"Recipient -> {reply.get('body', '')}")
            return True
        print(f"[INITIATOR] Unexpected message type: {rtype}")
        return True

    def run(self) -> None:
        self.send_broadcast()
        conn = self.listen_for_connection()
        if conn is None:
            return
        try:
            if self.perform_handshake(conn):
                self.exchange_messages(conn)
            else:
                _close(conn)
        except KeyboardInterrupt:
            _try_send(conn, lncp.make_bye(self.request_id, "Interrupted."))
            _close(conn)
            print("\n[INITIATOR] Interrupted. Connection closed.")


def _try_send(sock: socket.socket, msg: dict) -> None:
    try:
        lncp.send_frame(sock, msg)
    except (OSError, lncp.ProtocolError):
        pass


def _close(sock: socket.socket) -> None:
    try:
        sock.close()
    except OSError:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LNCP Initiator")
    parser.add_argument("nickname", help="Nickname of the intended recipient")
    parser.add_argument("--port", type=int, default=55000,
                        help="TCP port to listen on (default: 55000)")
    parser.add_argument("--deadline", type=int, default=30,
                        help="Seconds to wait for a response (default: 30)")
    args = parser.parse_args()

    Initiator(args.nickname, args.port, args.deadline).run()
