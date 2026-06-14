#!/usr/bin/env python3
"""
LNCP (Local Network Chat Protocol) - Recipient Application.

The Recipient listens for UDP DISCOVER broadcasts naming its nickname, connects
to the Initiator over TCP, completes the handshake, exchanges turn-based text
messages, and closes the session. See PROTOCOL_SPECIFICATION.md for the full
design.

Usage:
    python recipient.py <my_nickname>
"""

from __future__ import annotations

import argparse
import json
import socket
import time

import lncp


class Recipient:
    def __init__(self, my_nickname: str):
        self.my_nickname = my_nickname
        self.request_id  = None
        self.seq         = 0

    def wait_for_discovery(self) -> dict | None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", lncp.UDP_PORT))
        print(f"[RECIPIENT] Listening for DISCOVER broadcasts as "
              f"'{self.my_nickname}' on UDP {lncp.UDP_PORT}...")

        try:
            while True:
                try:
                    data, addr = sock.recvfrom(lncp.BUFFER_SIZE)
                    payload = json.loads(data.decode(lncp.ENCODING))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

                if not isinstance(payload, dict) or payload.get("type") != lncp.DISCOVER:
                    continue
                if payload.get("recipient") != self.my_nickname:
                    continue

                deadline_ts = payload.get("deadline", 0)
                if time.time() > deadline_ts:
                    print("[RECIPIENT] Matching DISCOVER found but deadline already "
                          "passed - ignoring.")
                    continue

                payload["_initiator_ip"] = addr[0]
                print(f"[RECIPIENT] DISCOVER received from {addr[0]} "
                      f"(id={payload.get('id')}, "
                      f"deadline in {max(0.0, deadline_ts - time.time()):.1f}s)")
                return payload
        finally:
            sock.close()

    def connect_to_initiator(self, discovery: dict) -> socket.socket | None:
        ip   = discovery["_initiator_ip"]
        port = discovery.get("tcp_port")
        if not isinstance(port, int):
            print("[RECIPIENT] DISCOVER is missing a valid tcp_port. Aborting.")
            return None

        print(f"[RECIPIENT] Connecting to Initiator at {ip}:{port}...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        try:
            sock.connect((ip, port))
            sock.settimeout(None)
            print("[RECIPIENT] TCP connection established.")
            return sock
        except (ConnectionRefusedError, socket.timeout, OSError) as exc:
            print(f"[RECIPIENT] Failed to connect: {exc}")
            _close(sock)
            return None

    def perform_handshake(self, sock: socket.socket, discovery: dict) -> bool:
        self.request_id = discovery["id"]
        try:
            lncp.send_frame(sock, lncp.make_hello(self.request_id, self.my_nickname))
            print(f"[RECIPIENT] HELLO sent with id={self.request_id}")
            response = lncp.recv_frame(sock)
        except (lncp.ProtocolError, ConnectionError, OSError) as exc:
            print(f"[RECIPIENT] Handshake failed: {exc}")
            return False

        rtype = response.get("type")
        if rtype == lncp.ACCEPT:
            print(f"[RECIPIENT] Handshake ACCEPTED: {response.get('info', '')}")
            return True
        if rtype == lncp.REJECT:
            print(f"[RECIPIENT] Handshake REJECTED "
                  f"[{response.get('code', '?')}]: {response.get('reason', '')}")
            return False
        print(f"[RECIPIENT] Unexpected handshake response: {rtype}")
        return False

    def exchange_messages(self, sock: socket.socket) -> None:
        print("\n[RECIPIENT] Session open. Waiting for messages. "
              "Type '/quit' (when prompted) to close.\n")

        while True:
            # The Recipient receives first each turn (simplex discipline).
            try:
                msg = lncp.recv_frame(sock)
            except (lncp.ProtocolError, ConnectionError, OSError) as exc:
                print(f"[RECIPIENT] Connection lost: {exc}")
                break

            mtype = msg.get("type")

            if mtype == lncp.BYE:
                print(f"[RECIPIENT] Initiator closed the session: "
                      f"{msg.get('reason', '')}")
                break

            if mtype != lncp.TEXT:
                print(f"[RECIPIENT] Unexpected message type: {mtype}")
                continue

            print(f"Initiator -> {msg.get('body', '')}")

            try:
                text = input("You -> ")
            except EOFError:
                text = "/quit"

            if text.strip().lower() == "/quit":
                _try_send(sock, lncp.make_bye(self.request_id,
                                              "Closed by recipient."))
                print("[RECIPIENT] BYE sent. Closing.")
                break

            if text.strip() == "":
                # Empty line acknowledges the TEXT without sending a reply.
                _try_send(sock, lncp.make_ack(self.request_id, msg.get("seq", 0)))
            else:
                self.seq += 1
                if not _try_send(sock, lncp.make_text(self.request_id,
                                                      self.seq, text)):
                    print("[RECIPIENT] Connection lost while replying.")
                    break

        _close(sock)
        print("[RECIPIENT] Connection closed.")

    def run(self) -> None:
        discovery = self.wait_for_discovery()
        if not discovery:
            return
        sock = self.connect_to_initiator(discovery)
        if sock is None:
            return
        try:
            if self.perform_handshake(sock, discovery):
                self.exchange_messages(sock)
            else:
                _close(sock)
        except KeyboardInterrupt:
            _try_send(sock, lncp.make_bye(self.request_id or "", "Interrupted."))
            _close(sock)
            print("\n[RECIPIENT] Interrupted. Connection closed.")


def _try_send(sock: socket.socket, msg: dict) -> bool:
    try:
        lncp.send_frame(sock, msg)
        return True
    except (OSError, lncp.ProtocolError):
        return False


def _close(sock: socket.socket) -> None:
    try:
        sock.close()
    except OSError:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LNCP Recipient")
    parser.add_argument("nickname",
                        help="Your nickname (must match what the Initiator broadcasts)")
    args = parser.parse_args()

    Recipient(args.nickname).run()
