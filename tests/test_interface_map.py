import copy
import gzip
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import tempfile
import unittest
from pathlib import Path

from interface_map import export

BASE = "https://example.org/r4"
FIXTURE = Path(__file__).resolve().parents[1] / "demo" / "r4" / "metadata"


def convert(statement, base):
    """Pass an input fixture through the installed IRIS class and inspect its actual file."""
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / "input.json"
        target = Path(folder) / "output.json"
        source.write_text(json.dumps(statement, ensure_ascii=False), encoding="utf-8")
        export(base, target, source)
        return json.loads(target.read_text())


@contextmanager
def serve_response(payload, encoding="", truncate=False):
    """Serve a fixed body over loopback, optionally interrupting HTTP chunk framing."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/fhir+json")
            if encoding:
                self.send_header("Content-Encoding", encoding)
            if truncate:
                self.send_header("Transfer-Encoding", "chunked")
            else:
                self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/r4"
        finally:
            server.shutdown()
            thread.join()


class InterfaceMapTests(unittest.TestCase):
    def setUp(self):
        """Load a fresh synthetic CapabilityStatement for each test."""
        self.statement = json.loads(FIXTURE.read_text())
        self.rest = self.statement["rest"][0]

    def test_read_only_resource(self):
        """An advertised read must not generate a search or write operation."""
        document = convert(self.statement, BASE)
        self.assertEqual(set(document["paths"]), {"/metadata", "/Organization/{id}"})
        operation = document["paths"]["/Organization/{id}"]["get"]
        self.assertTrue(operation["parameters"][0]["required"])
        self.assertEqual(operation["parameters"][0]["in"], "path")
        self.assertEqual(document["servers"][0]["url"], BASE)

    def test_declared_write_verbs_and_status(self):
        """Check routes, request bodies and status codes for create, update and delete."""
        self.rest["resource"][0]["interaction"] = [{"code": x} for x in ("create", "update", "delete")]
        paths = convert(self.statement, BASE)["paths"]
        self.assertIn("201", paths["/Organization"]["post"]["responses"])
        self.assertTrue(paths["/Organization/{id}"]["put"]["requestBody"]["required"])
        self.assertIn("204", paths["/Organization/{id}"]["delete"]["responses"])
        self.assertNotIn("get", paths["/Organization/{id}"])

    def test_inherited_search_and_override(self):
        """Merge shared parameters while preserving local descriptions and FHIR string syntax."""
        self.rest["searchParam"] = [{"name": "_id", "type": "token"}, {"name": "name", "type": "string"}]
        resource = self.rest["resource"][0]
        resource["interaction"] = [{"code": "search-type"}]
        resource["searchParam"] = [{"name": "name", "type": "string", "documentation": "Current name"}]
        operation = convert(self.statement, BASE)["paths"]["/Organization"]["get"]
        params = {p["name"]: p for p in operation["parameters"]}
        self.assertEqual(len(operation["parameters"]), 2)
        self.assertEqual(params["name"]["description"], "Current name")
        self.assertEqual(params["_id"]["schema"]["type"], "string")
        self.assertIn("Bundle", str(operation["responses"]["200"]))

    def test_client_only_ignored_and_unsupported_reported(self):
        """Ignore client declarations and report unsupported server capabilities."""
        self.statement["rest"].append({"mode":"client", "resource":[{"type":"Patient", "interaction":[{"code":"read"}]}]})
        self.rest["resource"][0]["interaction"].append({"code": "patch"})
        self.rest["operation"] = [{"name": "lookup", "definition": "https://example.org/OperationDefinition/lookup"}]
        result = convert(self.statement, BASE)
        self.assertNotIn("/Patient/{id}", result["paths"])
        self.assertNotIn("patch", result["paths"]["/Organization/{id}"])
        self.assertIn("patch", str(result["x-interface-map-report"]))
        self.assertIn("lookup", str(result["x-interface-map-report"]))

    def test_update_create_and_security_declarations(self):
        """Advertise HTTP 201 on update only when updateCreate is enabled, and report security declarations."""
        resource = self.rest["resource"][0]
        resource["interaction"] = [{"code": "update"}]
        self.rest["security"] = {"description": "OAuth required"}
        result = convert(self.statement, BASE)
        self.assertNotIn("201", result["paths"]["/Organization/{id}"]["put"]["responses"])
        self.assertIn("security", str(result["x-interface-map-report"]))
        resource["updateCreate"] = True
        self.assertIn("201", convert(self.statement, BASE)["paths"]["/Organization/{id}"]["put"]["responses"])

    def test_version_and_history_paths(self):
        """History returns a Bundle, and a versioned read declares both the resource and version IDs."""
        self.rest["resource"][0]["interaction"] = [{"code": x} for x in ("vread","history-type","history-instance")]
        paths = convert(self.statement, BASE)["paths"]
        params = paths["/Organization/{id}/_history/{vid}"]["get"]["parameters"]
        self.assertEqual([p["name"] for p in params], ["id","vid"])
        self.assertIn("Bundle", str(paths["/Organization/_history"]["get"]["responses"]["200"]))
        self.assertIn("Bundle", str(paths["/Organization/{id}/_history"]["get"]["responses"]["200"]))

    def test_invalid_inputs(self):
        """Reject unsupported versions, resource types, server modes, formats and invalid base URLs."""
        for lookup, value in (("fhirVersion","4.3.0"),("resourceType","Patient"),("rest",[{"mode":"client"}]),("format",["xml"])):
            with self.subTest(lookup=lookup):
                bad = copy.deepcopy(self.statement)
                bad[lookup] = value
                with self.assertRaises(ValueError):
                    convert(bad, BASE)
        for source in ("file:///private/tmp/meta","https://secret@example.org/fhir","https://example.org/fhir?key=secret"):
            with self.assertRaises(ValueError):
                convert(self.statement, source)

    def test_gzip_metadata(self):
        """Decode gzip metadata and enforce the size limit on the uncompressed response."""
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "result.json"
            with serve_response(gzip.compress(FIXTURE.read_bytes()), "gzip") as base:
                self.assertEqual(export(base, output), 2)
            with serve_response(gzip.compress(b" " * (16 * 1024 * 1024 + 1)), "gzip") as base:
                with self.assertRaisesRegex(ValueError, "16 MiB"):
                    export(base, output)

    def test_truncated_metadata_leaves_existing_output_intact(self):
        """Report an interrupted chunked response and preserve the previous output."""
        with tempfile.TemporaryDirectory() as folder, serve_response(b"1000\r\npartial", truncate=True) as base:
            output = Path(folder) / "result.json"
            output.write_text("previous")
            with self.assertRaises(ValueError):
                export(base, output)
            self.assertEqual(output.read_text(), "previous")

    def test_unicode_and_large_response(self):
        """Decode UTF-8 metadata, and serialize valid JSON past the IRIS string limit."""
        self.statement["title"] = "München — \u6771\u4eac"
        self.rest["resource"][0]["interaction"] = [{"code":"search-type"}]
        self.rest["resource"][0]["searchParam"] = [
            {"name": f"search-{idx}", "type":"string", "documentation": "x" * 1200}
            for idx in range(3500)]
        result = convert(self.statement, BASE)
        self.assertEqual(result["info"]["title"], self.statement["title"])
        self.assertEqual(len(result["paths"]["/Organization"]["get"]["parameters"]), 3500)

    def test_export_preserves_existing_file_on_error(self):
        """A failed export must leave the previous successful output intact."""
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "result.json"
            export(BASE, output, FIXTURE)
            first = output.read_bytes()
            self.assertEqual(json.loads(first)["openapi"], "3.0.3")
            invalid = Path(folder) / "invalid.json"
            invalid.write_text('{"resourceType":"Patient"}')
            with self.assertRaises(ValueError):
                export(BASE, output, invalid)
            self.assertEqual(first, output.read_bytes())
            self.statement["title"] = "Updated target"
            replacement = Path(folder) / "replacement.json"
            replacement.write_text(json.dumps(self.statement))
            export(BASE, output, replacement)
            self.assertEqual(json.loads(output.read_text())["info"]["title"], "Updated target")
            with self.assertRaisesRegex(ValueError, "Source and output must differ"):
                export(BASE, replacement, replacement)
