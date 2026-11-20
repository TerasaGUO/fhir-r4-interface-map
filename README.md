# FHIR R4 Interface Map

[简体中文](README.zh-CN.md)

Generate OpenAPI 3.0.3 JSON from the routes a FHIR R4 server advertises. A native ObjectScript class in InterSystems IRIS or IRIS for Health fetches and parses metadata, maps declared interactions and writes the output. The terminal entry point requires only IRIS. An optional Python shell wrapper invokes that same installed class.

An API gateway engineer supplies a FHIR base URL. The exporter reads its JSON CapabilityStatement at `/metadata` and creates paths, HTTP methods, FHIR media types, input parameters and response envelopes. The generated document includes a report of capabilities requiring manual review.

## Install on IRIS

1. Copy the repository to an IRIS-readable directory such as `/opt/fhir-interface-map`.
2. In the application namespace, compile the class and generate a sample from the included CapabilityStatement. The return value counts distinct path templates. Output paths must be writable by the IRIS service account.

```objectscript
set app="/opt/fhir-interface-map"
set sc=$system.OBJ.Load(app_"/src/InterfaceMap.Exporter.cls","ck")
if $system.Status.IsError(sc) do $system.Status.DisplayError(sc)
write ##class(InterfaceMap.Exporter).Generate("https://example.org/fhir","/tmp/openapi.json","",app_"/demo/r4/metadata")
```

For HTTPS, use an active IRIS client TLS configuration with server certificate verification enabled and trusted CA certificates. The default profile name is `FhirInterfaceTLS`. If a suitable profile already exists, pass its name as the fifth argument. To create the default profile once in a clean Linux community container, an administrator can run the following in the `%SYS` namespace.

```objectscript
set p("VerifyPeer")=1,p("CAFile")="/etc/ssl/certs/ca-certificates.crt",p("Enabled")=1
set sc=##class(Security.SSLConfigs).Create("FhirInterfaceTLS",.p)
if $system.Status.IsError(sc) do $system.Status.DisplayError(sc)
```

From the application namespace, generate a specification from a reachable base URL. IRIS verifies the HTTPS hostname. For a protected service, fetch metadata with your authorized client and use the offline file parameter shown above. The supplied base URL is recorded in the generated document. The exporter accepts up to 16 MiB of decoded metadata and replaces its output file after successful conversion.

```objectscript
write ##class(InterfaceMap.Exporter).Generate("https://hapi.fhir.org/baseR4","/tmp/openapi.json")
```

## Reproduce the demo in a fresh IRIS container

Run these commands from the repository root with Docker running. The repository is mounted read-only. The test starts a synthetic FHIR HTTP endpoint on the container loopback interface, compiles the class in the USER namespace, calls the IRIS method over a live HTTP source, and reads a synthetic Organization using the generated OpenAPI operation. The test makes two HTTP GET requests.

```sh
docker run -d --rm --name r4-interface-demo \
  --mount "type=bind,source=$PWD,target=/app,readonly" \
  containers.intersystems.com/intersystems/irishealth-community:2026.2
# Wait for iris list to show status: running and state: ok.
docker exec r4-interface-demo iris list
docker exec r4-interface-demo python3 /app/tests/iris_smoke.py
docker stop r4-interface-demo
```

Expected last line:

```text
PASS: IRIS compiled the class, fetched /metadata and generated a working Organization read.
```

The fixture's two generated paths are `GET /metadata` and `GET /Organization/{id}`. Reading `/Organization/example` returns a resource named `Demo Registry`.

## Run from the shell

With the class installed, run the optional Python 3.8+ wrapper on the IRIS host with the `iris` executable on PATH. It calls the ObjectScript method through `iris session`. Set `IRIS_INSTANCE` and `IRIS_NAMESPACE` to override the defaults `IRIS` and `USER`. The regression suite uses the same native entry point.

```sh
python3 interface_map.py http://localhost:8000/r4 /tmp/openapi.json --source demo/r4/metadata
python3 interface_map.py https://hapi.fhir.org/baseR4 /tmp/openapi.json
python3 -m unittest discover -s tests -v
```

To validate an output file, an optional validator can be installed in a separate environment. A public endpoint may change its declared paths or be temporarily unavailable.

```sh
python3 -m venv .venv
.venv/bin/pip install openapi-spec-validator==0.8.5
.venv/bin/python -c 'import json; from openapi_spec_validator import validate; validate(json.load(open("/tmp/openapi.json"))); print("OpenAPI document passed")'
```

## Verified example

On November 20, 2026, the terminal method in IRIS for Health Community 2026.2 generated 731 paths and 1,169 operations from the public HAPI R4 server. The generated document passed openapi-spec-validator 0.8.5. Using its Organization search route with `_count=0` returned HTTP 200 and a FHIR searchset Bundle. The local fixture above reproduces the workflow without depending on public data or endpoint availability.

## Coverage

| Declared interaction | Generated operation |
|---|---|
| read, vread | GET by resource ID or by resource ID and version |
| search-type | GET on the resource collection with the declared search parameters |
| history-type, history-instance | GET on the type or instance history |
| create | POST a FHIR JSON resource to the collection |
| update, delete | PUT or DELETE by resource ID |

Only server-mode REST declarations are mapped. The search operation combines common and resource-level search parameters. Search values stay strings to preserve FHIR date prefixes, tokens and references. Resource bodies use a minimal JSON envelope with the expected `resourceType`; profile-level validation remains the FHIR server's responsibility.

Review `x-interface-map-report.skipped` for server-wide interactions, custom operations, PATCH, imports, conditional interactions, includes and security declarations. Before using the file to configure a gateway, supply deployment-specific authentication and authorization. Forms for POST search, asynchronous responses and profile expansion are outside this release.

[HL7 FHIR R4 capability statements](https://hl7.org/fhir/R4/capabilitystatement.html) · [FHIR RESTful API](https://hl7.org/fhir/R4/http.html) · [OpenAPI 3.0.3](https://spec.openapis.org/oas/v3.0.3.html)

MIT license. See LICENSE.

Community Bounty idea: [Generate an OpenAPI specification from a FHIR CapabilityStatement](https://ideas.intersystems.com/ideas/DPI-I-804).
