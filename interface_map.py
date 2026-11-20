"""Invoke the installed ObjectScript exporter through the local IRIS terminal."""

import argparse
import os
from pathlib import Path
import re
import subprocess


def literal(value):
    """Quote one value for an ObjectScript string literal on a single terminal line."""
    text = str(value)
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ValueError("Control characters are not valid terminal arguments.")
    return '"' + text.replace('"', '""') + '"'


def export(base, output, source=None, tls="FhirInterfaceTLS"):
    """Call the native class and return its count; file locations belong to the IRIS host."""
    args = [base, Path(output).absolute(), "", Path(source).absolute() if source else "", tls]
    call = "##class(InterfaceMap.Exporter).Generate(" + ",".join(map(literal, args)) + ")"
    script = ('try {set n=' + call + ' write "MAP-PATHS=",n,!} '
              'catch ex {write ex.DisplayString(),! zhalt 1}\nhalt\n')
    result = subprocess.run(
        ["iris", "session", os.getenv("IRIS_INSTANCE", "IRIS"), "-U", os.getenv("IRIS_NAMESPACE", "USER")],
        input=script, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    match = re.search(r"^MAP-PATHS=(\d+)\s*$", result.stdout, re.MULTILINE)
    if result.returncode or not match:
        raise ValueError("IRIS export failed. " + result.stdout.strip())
    return int(match.group(1))


def main():
    """Pass shell arguments to the installed IRIS class."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", help="FHIR R4 base URL")
    parser.add_argument("output", help="Destination OpenAPI JSON file")
    parser.add_argument("--source", help="Read a saved CapabilityStatement instead of fetching /metadata")
    parser.add_argument("--tls", default="FhirInterfaceTLS", help="IRIS TLS client configuration")
    args = parser.parse_args()
    try:
        count = export(args.base, args.output, args.source, args.tls)
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + "\n")
    print(f"Wrote {count} paths to {args.output}")


if __name__ == "__main__":
    main()
