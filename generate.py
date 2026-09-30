#!/usr/bin/env python3
# This file is a part of ThetaGP.
#
# Generate the artifacts derived from ThetaGP.proto: the C codec the firmware
# compiles, and the Python bindings the host tools import. This repository holds
# the schema and this generator and nothing that consumes it: which consumer
# runs a side, and where its output goes, is the consumer's to say.
#
# Usage:
#   generate.py c      --nanopb <checkout> --out <dir> [--protobuf-path <dir>]
#   generate.py python --out <dir> [--protoc <path>] [--protobuf-path <dir>]
#
# Exit: 0 = the artifacts were written; 1 = a generator ran and wrote nothing;
#       2 = the inputs or the toolchain are not there.

from __future__ import annotations

import argparse
import os
import os.path
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
WIRE_SCHEMA = "protocol/ThetaGP.proto"
ENUMS_SCHEMA = "enums/enums.proto"

PROTOBUF_PYTHONPATH_ENV = "PROTOBUF_PYTHONPATH"


def fail(message: str, code: int):
    print("generate: " + message, file=sys.stderr)
    sys.exit(code)


def find_protobuf_runtime(explicit: str | None):
    """The directory to take python-protobuf from, None to use the interpreter's
    own, or False when neither is available."""
    try:
        import google.protobuf  # noqa: F401  (the probe is the point)
        return None
    except ImportError:
        pass

    for candidate in (explicit, os.environ.get(PROTOBUF_PYTHONPATH_ENV)):
        if not candidate:
            continue
        if os.path.isfile(os.path.join(candidate, "google", "protobuf",
                                       "__init__.py")):
            return candidate
    return False


def check_nonempty(path: str, who: str) -> bool:
    """True when the generator wrote a non-empty file at `path`."""
    if not os.path.isfile(path):
        print("ERROR: %s wrote no %s" % (who, path), file=sys.stderr)
        return False
    if os.path.getsize(path) == 0:
        print("ERROR: %s wrote an empty %s" % (who, path), file=sys.stderr)
        return False
    return True


def run_generation(argv):
    """Run one generator over the schema and report a non-zero exit on empty
    output. Returns the process result."""
    return subprocess.run(argv, cwd=REPO_ROOT, capture_output=True, text=True)


def generate_c(args) -> int:
    schema = os.path.join(REPO_ROOT, WIRE_SCHEMA)
    out_dir = os.path.abspath(args.out)
    generator = os.path.join(args.nanopb, "generator", "nanopb_generator.py")

    if not os.path.isfile(schema):
        fail("%s is not there" % schema, 2)
    if not os.path.isfile(generator):
        fail("no nanopb generator at %s: --nanopb names the nanopb checkout "
             "whose generator/ holds nanopb_generator.py" % generator, 2)
    if shutil.which("protoc") is None:
        fail("protoc is not on PATH (the nanopb generator calls it for the "
             "schema it is given)", 2)

    runtime = find_protobuf_runtime(args.protobuf_path)
    if runtime is False:
        fail("no python-protobuf runtime — the interpreter running this cannot "
             "import google.protobuf, and neither $%s nor --protobuf-path names "
             "a directory that holds it" % PROTOBUF_PYTHONPATH_ENV, 2)

    env = os.environ.copy()
    env["TEMPORARILY_DISABLE_PROTOBUF_VERSION_CHECK"] = "true"
    if runtime:
        env["PYTHONPATH"] = (runtime + os.pathsep + env["PYTHONPATH"]
                             if env.get("PYTHONPATH") else runtime)

    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(WIRE_SCHEMA))[0]
    outputs = [os.path.join(out_dir, stem + ".pb.c"),
               os.path.join(out_dir, stem + ".pb.h")]

    with tempfile.TemporaryDirectory(prefix="thetagp_pb_") as tmp:
        # The generator builds the python bindings of nanopb's own options file
        # beside its sources by default; the temp directory keeps that write.
        env["NANOPB_PB2_TEMP_DIR"] = tmp
        cmd = [sys.executable, generator, "-I", os.path.dirname(schema),
               "--output-dir=" + out_dir, schema]
        print("$ " + " ".join(cmd))
        result = subprocess.run(cmd, cwd=REPO_ROOT, env=env,
                                capture_output=True, text=True)
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        if result.returncode != 0:
            fail("the nanopb generator exited %d" % result.returncode, 1)

    if not all(check_nonempty(path, "the nanopb generator") for path in outputs):
        return 1
    print("wrote " + ", ".join(outputs))
    return 0


def generate_python(args) -> int:
    schema = os.path.join(REPO_ROOT, WIRE_SCHEMA)
    out_dir = os.path.abspath(args.out)

    if not os.path.isfile(schema):
        fail("%s is not there" % schema, 2)

    protoc = args.protoc or shutil.which("protoc")
    if not protoc:
        fail("protoc is not on PATH and --protoc was not given (the python "
             "plugin of protoc is what writes the bindings)", 2)

    os.makedirs(out_dir, exist_ok=True)
    name = os.path.basename(schema)
    cmd = [protoc, "--python_out=" + out_dir, "-I", os.path.dirname(schema),
           name]
    print("$ " + " ".join(cmd))
    result = run_generation(cmd)
    if result.stdout.strip():
        print(result.stdout.rstrip())
    if result.returncode != 0:
        fail("protoc exited %d" % result.returncode, 1)

    binding = os.path.join(out_dir, os.path.splitext(name)[0] + "_pb2.py")
    if not check_nonempty(binding, "protoc"):
        return 1
    print("wrote " + binding)
    return 0


def generate_cpp_enums(args) -> int:
    schema = os.path.join(REPO_ROOT, ENUMS_SCHEMA)
    if not os.path.isfile(schema):
        fail("%s is not there" % schema, 2)
    protoc = args.protoc or shutil.which("protoc")
    if not protoc:
        fail("protoc is not on PATH and --protoc was not given", 2)
    runtime = find_protobuf_runtime(args.protobuf_path)
    if runtime is False:
        fail("no python-protobuf runtime — the interpreter cannot import "
             "google.protobuf", 2)
    if runtime:
        sys.path.insert(0, runtime)

    import google.protobuf.descriptor_pb2 as descriptor_pb2

    with tempfile.TemporaryDirectory(prefix="thetagp_enum_") as tmp:
        desc = os.path.join(tmp, "enums.desc")
        result = run_generation([protoc, "--descriptor_set_out=" + desc,
                                 "--include_imports", "-I", REPO_ROOT, schema])
        if result.returncode != 0:
            fail("protoc exited %d" % result.returncode, 1)
        fds = descriptor_pb2.FileDescriptorSet()
        with open(desc, "rb") as handle:
            fds.ParseFromString(handle.read())

    wanted = os.path.basename(schema)
    file_proto = next((f for f in fds.file
                       if os.path.basename(f.name) == wanted), None)
    if file_proto is None:
        fail("the descriptor set carries no %s" % wanted, 1)

    lines = ["// Generated by generate.py — do not edit.", "#pragma once", ""]
    if args.namespace:
        lines += ["namespace %s {" % args.namespace, ""]
    for enum in file_proto.enum_type:
        prefix = enum.name + "_"
        strip = all(value.name.startswith(prefix) for value in enum.value)
        lines.append("enum class %s {" % enum.name)
        for value in enum.value:
            name = value.name[len(prefix):] if strip else value.name
            lines.append("    %s = %d," % (name, value.number))
        lines.append("    Count = %d,"
                     % (max(v.number for v in enum.value) + 1))
        lines.append("};")
        lines.append("")
    if args.namespace:
        lines += ["} // namespace %s" % args.namespace, ""]

    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as handle:
        handle.write("\n".join(lines))
    print("wrote " + out)
    return 0


def main(argv) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the artifacts of " + WIRE_SCHEMA + ": the C codec "
                    "(nanopb) and the Python bindings.")
    subparsers = parser.add_subparsers(dest="what", required=True)

    c = subparsers.add_parser("c", help="the C codec the firmware compiles")
    c.add_argument("--nanopb", required=True, metavar="DIR",
                   help="the nanopb checkout; its generator/ holds "
                        "nanopb_generator.py")
    c.add_argument("--out", required=True, metavar="DIR",
                   help="the directory the .pb.c/.pb.h pair is written to")
    c.add_argument("--protobuf-path", default=None, metavar="DIR",
                   help="a site-packages directory holding google/protobuf, "
                        "when the interpreter cannot import it")
    c.set_defaults(handler=generate_c)

    py = subparsers.add_parser("python", help="the Python bindings the host tools import")
    py.add_argument("--out", required=True, metavar="DIR",
                    help="the directory ThetaGP_pb2.py is written to")
    py.add_argument("--protoc", default=None, metavar="PATH",
                    help="the protoc to run (default: the one on PATH)")
    py.add_argument("--protobuf-path", default=None, metavar="DIR",
                    help="a site-packages directory holding google/protobuf, "
                         "when the interpreter cannot import it")
    py.set_defaults(handler=generate_python)

    enums = subparsers.add_parser(
        "cpp-enums", help="the C++ enums of enums/enums.proto")
    enums.add_argument("--out", required=True, metavar="FILE",
                       help="the header this writes")
    enums.add_argument("--namespace", default=None, metavar="NS",
                       help="wrap the enums in this namespace")
    enums.add_argument("--protoc", default=None, metavar="PATH",
                       help="the protoc to run (default: the one on PATH)")
    enums.add_argument("--protobuf-path", default=None, metavar="DIR",
                       help="a site-packages directory holding google/protobuf")
    enums.set_defaults(handler=generate_cpp_enums)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
