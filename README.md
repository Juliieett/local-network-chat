# Local Network Chat — LNCP/1.0

A custom application-layer protocol and reference implementation for a
**local-network, nickname-based, one-to-one text chat**. The Initiator discovers
a partner via a UDP broadcast, then the two exchange messages over a TCP
connection using a strict, turn-based handshake-and-chat protocol called
**LNCP (Local Network Chat Protocol)**.

> The full protocol design — message formats, encoding rules, state machines,
> and error handling — lives in **[`PROTOCOL_SPECIFICATION.md`](./PROTOCOL_SPECIFICATION.md)**.
> That document is the primary deliverable; this README covers how to run it.

---

## Files

| File | Purpose |
|------|---------|
| `lncp.py` | Shared protocol library: constants, message framing, message builders. Imported by both apps so they speak identical LNCP. |
| `initiator.py` | **Initiator** app — broadcasts discovery, listens on TCP, validates the handshake, talks. |
| `recipient.py` | **Recipient** app — listens for discovery, connects over TCP, completes the handshake, talks. |
| `PROTOCOL_SPECIFICATION.md` | The LNCP/1.0 specification document. |

---

## Requirements

* **Python 3.10+** (uses `X | None` type hints). No third-party packages — the
  standard library only.
* A local network (or a single machine via loopback) that allows UDP broadcast
  on port **54321** and TCP on the Initiator's chosen port (default **55000**).
* Host firewalls must permit those ports.

---

## How to run

LNCP does not buffer broadcasts, so **start the Recipient first** (it must be
listening when the broadcast goes out).

### Terminal 1 — Recipient
```bash
python recipient.py alice
```
`alice` is this peer's nickname. It now waits for a broadcast addressed to
`alice`.

### Terminal 2 — Initiator
```bash
python initiator.py alice
```
This broadcasts a request for the partner nicknamed `alice`, then listens for
the incoming TCP connection.

Optional flags for the Initiator:

| Flag | Default | Meaning |
|------|---------|---------|
| `--port PORT` | `55000` | TCP port to listen on |
| `--deadline SECS` | `30` | How many seconds to wait for a response |

```bash
python initiator.py alice --port 56000 --deadline 20
```

### Chatting
The chat is **turn-based** — the Initiator types first:

* **Initiator**: type a line, press Enter; it is sent and the app waits for the
  reply.
* **Recipient**: sees the message, then is prompted to reply. Press Enter on an
  empty line to send a bare acknowledgement instead of text.
* Either side types `/quit` to send `BYE` and close the session cleanly.

---

## Testing on two machines

1. Ensure both machines are on the same subnet and can reach each other.
2. Run `recipient.py <nick>` on machine A.
3. Run `initiator.py <nick>` on machine B, using the **same nickname**.
4. If discovery fails, check that broadcast UDP 54321 and the TCP port are not
   blocked by a firewall.

## Testing on one machine (loopback)
Open two terminals and follow the *How to run* steps above using the same
nickname. Broadcast traffic loops back locally on most systems.

---

## Demonstrating error conditions

| Scenario | How to trigger | Expected result |
|----------|----------------|-----------------|
| **No response before deadline** | Start only the Initiator with `--deadline 5`; never start a Recipient. | Initiator prints "Deadline expired" and exits. |
| **Wrong nickname** | `recipient.py bob` while `initiator.py alice`. | Recipient ignores the broadcast; Initiator eventually times out. |
| **Late connection** | Use `--deadline 1`, delay the Recipient. | Initiator replies `REJECT` with code `DEADLINE_EXPIRED`. |
| **Clean close** | Type `/quit` on either side. | Both sides report the close and exit. |
| **Abrupt disconnect** | Kill one process mid-chat. | The other side reports "connection lost" and exits. |

---

## Protocol at a glance

```
DISCOVER (UDP broadcast)  ─►  TCP connect  ─►  HELLO  ─►  ACCEPT/REJECT
                                            ─►  TEXT ⇄ TEXT/ACK  ─►  BYE
```

See [`PROTOCOL_SPECIFICATION.md`](./PROTOCOL_SPECIFICATION.md) for message
formats, field tables, the framing diagram, state machines, and the full error
table.
