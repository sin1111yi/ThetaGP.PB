# ThetaGP.PB

<p align="center">
  <img src="asset/thetagp-logo.png" alt="ThetaGP Logo" width="400">
</p>

The ThetaGP protocol: one schema (`ThetaGP.proto`) from which the firmware's
codec and the host bindings are both generated. This repository is the schema,
its field bounds, this README and a generator; it knows no consumer.

## Layout

```
ThetaGP.proto     the schema
ThetaGP.options   nanopb field bounds
generate.py       the generator
README.md
LICENSE           GPL-3.0
```

## Generate

```
generate.py c --nanopb <checkout> --out <dir>   # the C codec
generate.py python --out <dir>                   # the Python bindings
```

`c` runs `protoc` and the nanopb generator at
`<checkout>/generator/nanopb_generator.py`; the checkout is the consumer's,
because the generated header and the runtime must match. `python` runs
`protoc --python_out`. Both need `protoc` and a python-protobuf runtime
(`$PROTOBUF_PYTHONPATH` points an interpreter that cannot import it).

## The wire

```
varint length | payload | payload checksum (low 16 bits, little endian)
```

The length covers the payload only; the checksum covers the payload only. A
payload is at most 1,024 B, so a frame is at most 1,028 B. A host numbers its
frames through `queued`: the reply carries request+1 and the host's next frame
carries reply+1.

## Rules

- Arm numbers run dense from 1 within each `oneof`, assigned once, never reused;
  a removed field leaves `reserved N;`.
- A main arm is `<domain>_<command>`; a name appears in its `oneof` once.
- A field a device may not always send is `optional`.
- An arm a device does not answer is `ERR_UNKNOWN_CMD`; one it cannot do is an
  `Error` naming why.
- Additive only: what has shipped keeps its meaning.
- The protocol does not know the codebase: no consumer paths, no citations.

## Adding a command

Declare the request and reply messages; give the request arm the next free
number of its domain and the reply arm the k+2 relation; bound every string,
bytes and repeated field in `ThetaGP.options`; regenerate.
