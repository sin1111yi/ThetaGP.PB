# ThetaGP Protocol

`ThetaGP.proto` is the protocol between the ThetaGP device (STM32H743 firmware)
and its host tools. It is the single source of the commands, their fields, their
arm numbers and their error and reason codes: the codec the firmware compiles
and the bindings the host tools import are both generated from it, and no other
file restates what it declares.

This repository is the schema and nothing else — two tracked source files
(`ThetaGP.proto`, `ThetaGP.options`), this README and a generator that turns
them into the artifacts a consumer compiles or imports. It does not know which
consumer runs a side, nor where that consumer's output goes (design principle 6).

## File structure

```
.
├── ThetaGP.proto     the schema (tracked)
├── ThetaGP.options   the field bounds nanopb reads beside it (tracked)
├── README.md         this file (tracked)
├── generate.py       the generator: `c` for the firmware's codec, `python` for the host bindings
└── LICENSE           GPL-3.0
```

## Generation

`generate.py` writes both kinds of artifact from the schema alone:

```
# The C codec the firmware compiles (nanopb).
generate.py c --nanopb <nanopb checkout> --out <dir>

# The Python bindings the host tools import.
generate.py python --out <dir>
```

The `c` side runs `protoc` and the nanopb generator at
`<nanopb checkout>/generator/nanopb_generator.py`, and writes
`<dir>/ThetaGP.pb.c` and `<dir>/ThetaGP.pb.h`. The nanopb checkout is the
consumer's to supply, because the generated header carries a
`PB_PROTO_HEADER_VERSION` that has to match the nanopb runtime the consumer
links: a header and a runtime from different checkouts are a compile error, not
a silent mismatch. The `python` side runs `protoc --python_out` and nothing
else, and writes `<dir>/ThetaGP_pb2.py`.

Both sides need `protoc` on PATH and a python-protobuf runtime. An interpreter
that cannot import `google.protobuf` itself is pointed at a site-packages
directory holding it through `$PROTOBUF_PYTHONPATH` (or the scripts'
`--protobuf-path`). A runtime older than the `protoc` that wrote the bindings
refuses to load them rather than guessing.

## The wire

One frame carries one message:

```
varint length | payload[length] | sum of the payload's bytes, low 16 bits, little endian
```

The length counts the payload and neither the prefix nor the sum; the sum covers
the payload and neither the prefix nor itself. A payload is at most 1,024 bytes,
so a frame is at most 1,028. The payload is a bare message — `pb_encode` and
`pb_decode`, not their delimited forms.

A host numbers the frames it writes: it puts its next number in the request's
`queued` field, the reply carries that number plus one, and the host's next frame
carries that reply's number plus one. A frame the device cannot read is answered
with a `TransportError`, which carries no number — there was nothing to pair it
with — and a host that receives one resends the command.

## Arm numbers

`Request` is one `oneof` whose arms are numbered 1..31, grouped by domain:

| Range | Domain |
| --- | --- |
| 1..6 | `sys` |
| 7..12 | `config` |
| 13..20 | `test` |
| 21..29 | the `profile` domain's commands |
| 30..31 | the two arms a stored body's write continues in |

`Reply` is one `oneof` numbered 1..33: 1 is `transport_error`, 2 is `error`, the
29 arms that answer a command follow (arm *k* of a request is answered by arm
*k+2*), and 32..33 are that body's read. `Reply` carries the numbering field
`queued = 34` outside the `oneof`.

Rules that hold for every change:

- A main arm is named `<domain>_<command>`; a continuation arm carries its own
  name; a message name appears in its `oneof` once.
- Within a `oneof`, numbers run 1..N with no gaps. A number is assigned once and
  never reused: a removed field leaves `reserved N;` behind.
- A field a device may not always send is `optional`, so its absence reads as
  declared rather than as missing.
- Anything a device does not answer is `ERR_UNKNOWN_CMD`, and anything it cannot
  do is an `Error` arm naming why.
- What the frame layer cannot hand on is neither of those: a payload whose sum
  does not hold, an illegal length prefix, a frame whose bytes stopped arriving,
  a payload that is not the message it claims and a receive side with no slot
  left all answer on the transport arm, each with a reason of its own. A reply to
  such a frame carries the device's own numbering, so a host tells a refusal from
  a transport failure by the arm it arrived on, never by a code.

## Adding a command

1. Declare its message and its reply message in `ThetaGP.proto`, and give the
   request arm the next free number of its domain — never one already used.
2. Add the reply arm it answers with, keeping the *k+2* relation.
3. Give every string, bytes and repeated field a bound in `ThetaGP.options`, so a
   decoded message is a fixed-size struct.
4. Regenerate with `generate.py`. When a build regenerates is the consumer's
   decision: the schema does not say it, and a consumer that compiles a stale
   codec is the consumer's to refuse.
5. Teach the consumer to answer the new arm. An arm the consumer carries no case
   for is refused as an unknown command rather than silently ignored; where that
   case lives is the consumer's, not the schema's.

## Design principles

1. **Single source of truth**: all protocol changes go into `ThetaGP.proto` and
   its `.options`. This repository tracks those two files and this README; every
   output derived from them is generated locally and ignored.
2. **No manual sync**: generated files are never hand-edited.
3. **Low dependency**: the schema is read by `protoc` and the nanopb generator
   and by nothing else. No hand-written parser of `.proto` lives here — a host
   tool reads the arms off the generated descriptors.
4. **Additive evolution**: the schema grows, and what has already shipped keeps
   working.
   - A field added to a reply is one an older host does not know. A host reads a
     message by field number and ignores the numbers it was not built with, so a
     device that sends more than it declared is read, not refused.
   - A command or a configuration key added later is one an older device does not
     have. Such a device answers `ERR_UNKNOWN_CMD` (1), `ERR_NOT_SUPPORTED` (6)
     or `ERR_INVALID_PARAM` (2) as the case fits, and what it did carry keeps
     answering exactly as before.
   - What has shipped keeps its meaning. An existing command, field, key or code
     does not change what it means, because the devices already in the field
     cannot be changed with it.
5. **A field has one name.** The firmware, the schema and the host tools spell a
   field the same way; where the name must be short, the protocol's name wins
   over a name the code would have preferred.
6. **The protocol does not know the codebase.** The dependency runs one way: a
   consumer depends on this file and on what is generated from it, never the
   other way round. A generator that reads the consumer's source tree, a
   declaration saying "this type already exists over there", and a sentence
   naming the consumer's files and lines are one defect at three weights — each
   one has the protocol describing the codebase instead of the interface. The
   weak form is not a milder version of the strong one: the citations rot,
   nothing notices, and the reader is handed a location instead of a rule. When a
   rule needs the codebase to hold, the codebase asserts it at its own compile
   time, beside the code that would break it (`#ifndef ... #error` at the write
   point); that is the direction that works, because the consumer knows what it
   must do and the protocol does not have to be told. An entry that breaks this
   is either removed or said in terms that stand on their own: quote what
   happens, not where it is written.
7. **A number is never reused.** Arm numbers within a `oneof` and field numbers
   within a message are assigned once. Removing one leaves `reserved` behind, so
   an old host and a new device cannot read the same bytes as two different
   things.
