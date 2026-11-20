"""Run inside the IRIS community container with python3."""

import functools
import json
import subprocess
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def objectscript_string(value):
    """Escape a local path for an ObjectScript string literal."""
    return '"' + str(value).replace('"', '""') + '"'


def run():
    """Serve a synthetic FHIR endpoint, export its routes inside IRIS, and read the advertised resource."""
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(ROOT / "demo"))
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server, tempfile.TemporaryDirectory() as folder:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}/r4"
            output = Path(folder) / "generated.json"
            scripts = [
                f'set sc=$system.OBJ.Load({objectscript_string(ROOT / "src/InterfaceMap.Exporter.cls")},"ck")',
                'if $system.Status.IsError(sc) zhalt 2',
                'write ##class(InterfaceMap.Exporter).Generate(' + ",".join(
                    objectscript_string(arg) for arg in (base, output, ROOT)) + '),!',
                'halt',
            ]
            subprocess.run(["iris", "session", "IRIS", "-U", "USER"], input="\n".join(scripts)+"\n",
                           text=True, check=True)
            spec = json.loads(output.read_text())
            assert set(spec["paths"]) == {"/metadata", "/Organization/{id}"}
            route = next(path for path, methods in spec["paths"].items()
                         if methods.get("get", {}).get("operationId") == "Organization_read")
            url = spec["servers"][0]["url"] + route.replace("{id}", "example")
            with urlopen(url, timeout=5) as response:
                record = json.load(response)
            assert record["resourceType"] == "Organization" and record["name"] == "Demo Registry"
            print("PASS: IRIS compiled the class, fetched /metadata and generated a working Organization read.")
        finally:
            server.shutdown()
            thread.join()


if __name__ == "__main__":
    run()
