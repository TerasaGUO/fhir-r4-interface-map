# FHIR R4 接口映射工具

[English](README.md)

从 FHIR R4 服务声明的路由生成 OpenAPI 3.0.3 JSON 文件。元数据获取、解析、交互映射及文件写入全部由 InterSystems IRIS 或 IRIS for Health 中的原生 ObjectScript 类执行。终端入口仅需 IRIS。可选的 Python 命令行封装调用同一个已安装的类。

配置 API 网关时，输入 FHIR 服务的基址，工具会从 `/metadata` 读取 JSON 格式的 CapabilityStatement，生成路径、HTTP 方法、FHIR 媒体类型、输入参数和响应的基本结构。输出文件还会列出需要人工核对的能力声明。

## 使用 IPM 部署

将仓库克隆或挂载到 IRIS 主机。安装 [IPM](https://github.com/intersystems/ipm) 后，在目标应用命名空间执行以下命令。请将示例路径换成 IRIS 主机上包含 `module.xml` 的仓库目录。

```objectscript
zpm "load /opt/fhir-interface-map"
write ##class(InterfaceMap.Exporter).Generate("https://example.org/fhir","/tmp/openapi.json","","/opt/fhir-interface-map/demo/r4/metadata")
```

仓库中的离线示例应返回 `2`。使用在线 HTTPS 端点时，请按下文配置 TLS。包发布到所用注册表后，可执行 `zpm "install fhir-r4-interface-map 1.0.0"` 安装。

## 安装到 IRIS

1. 将仓库复制到 IRIS 可读的位置，例如 `/opt/fhir-interface-map`。
2. 在应用命名空间编译该类，使用随仓库提供的 CapabilityStatement 生成示例规范。方法返回不同路径模板的数量。IRIS 服务账号需要能写入输出路径。

```objectscript
set app="/opt/fhir-interface-map"
set sc=$system.OBJ.Load(app_"/src/InterfaceMap/Exporter.cls","ck")
if $system.Status.IsError(sc) do $system.Status.DisplayError(sc)
write ##class(InterfaceMap.Exporter).Generate("https://example.org/fhir","/tmp/openapi.json","",app_"/demo/r4/metadata")
```

HTTPS 请求使用已启用的 IRIS 客户端 TLS 配置，需要打开服务端证书校验并指定受信的 CA 证书。默认配置名为 `FhirInterfaceTLS`。已有合适的配置时，可将名称作为第五个参数传入。在全新 Linux 社区版容器中，管理员可在 `%SYS` 命名空间执行以下语句，一次性创建默认配置。

```objectscript
set p("VerifyPeer")=1,p("CAFile")="/etc/ssl/certs/ca-certificates.crt",p("Enabled")=1
set sc=##class(Security.SSLConfigs).Create("FhirInterfaceTLS",.p)
if $system.Status.IsError(sc) do $system.Status.DisplayError(sc)
```

回到应用命名空间，输入 IRIS 主机可访问的 FHIR 基址即可在线导出。IRIS 校验 HTTPS 服务主机名。若服务需要身份认证，可以使用已授权的客户端获取元数据，再按前例传入本地文件。输出规范会采用调用者指定的服务基址。工具支持最多 16 MiB 的解压后元数据，成功转换后才替换输出文件。

```objectscript
write ##class(InterfaceMap.Exporter).Generate("https://hapi.fhir.org/baseR4","/tmp/openapi.json")
```

## 在全新的 IRIS 容器复现演示

启动 Docker，在仓库根目录执行下列命令。项目目录将以只读方式挂载。测试会在容器的回环地址启动一个提供合成数据的 FHIR HTTP 端点，在 USER 命名空间编译入口类，调用 IRIS 方法获取元数据，然后用生成的 OpenAPI 路由读取一条 Organization 资源。整个过程共发出两次 HTTP GET 请求。

```sh
docker run -d --rm --name r4-interface-demo \
  --mount "type=bind,source=$PWD,target=/app,readonly" \
  containers.intersystems.com/intersystems/irishealth-community:2026.2
# Wait for iris list to show status: running and state: ok.
docker exec r4-interface-demo iris list
docker exec r4-interface-demo python3 /app/tests/iris_smoke.py
docker stop r4-interface-demo
```

成功时，最后一行输出如下。

```text
PASS: IRIS compiled the class, fetched /metadata and generated a working Organization read.
```

示例会生成两条路径，分别为 `GET /metadata` 和 `GET /Organization/{id}`。访问 `/Organization/example` 会得到名称为 `Demo Registry` 的资源。

## 从命令行运行

先安装入口类，然后在 IRIS 主机运行可选的 Python 3.8+ 命令行封装。系统 PATH 需包含 `iris` 可执行文件。该封装通过 `iris session` 调用 ObjectScript 方法。通过 `IRIS_INSTANCE` 和 `IRIS_NAMESPACE` 可以更改默认实例名 `IRIS` 和默认命名空间 `USER`。回归测试使用同一个原生入口。

```sh
python3 interface_map.py http://localhost:8000/r4 /tmp/openapi.json --source demo/r4/metadata
python3 interface_map.py https://hapi.fhir.org/baseR4 /tmp/openapi.json
python3 -m unittest discover -s tests -v
```

如需校验生成的文件，可以在独立的 Python 环境中安装下面的校验器。公开服务声明的路径可能变化，服务也可能临时不可用。

```sh
python3 -m venv .venv
.venv/bin/pip install openapi-spec-validator==0.8.5
.venv/bin/python -c 'import json; from openapi_spec_validator import validate; validate(json.load(open("/tmp/openapi.json"))); print("OpenAPI document passed")'
```

## 实际验证结果

2026 年 11 月 20 日，在 IRIS for Health Community 2026.2 终端调用导出方法，从公开 HAPI R4 服务生成了 731 条路径、1,169 个操作。文档通过 openapi-spec-validator 0.8.5 校验。使用生成的 Organization 搜索路径并指定 `_count=0`，收到 HTTP 200 响应，资源为 `searchset` 类型的 FHIR Bundle。上面的本地示例可独立复现同一工作流程。

## 支持的交互

| 服务声明的交互 | 生成的操作 |
|---|---|
| read、vread | 按资源 ID 读取当前资源，或按资源 ID 和版本 ID 读取指定版本 |
| search-type | 使用服务声明的搜索参数，对该资源集合执行 GET |
| history-type、history-instance | 通过 GET 获取资源类型或单个资源实例的历史 |
| create | 将 FHIR JSON 资源 POST 到对应集合 |
| update、delete | 按资源 ID 执行 PUT 或 DELETE |

工具映射服务端模式的 REST 声明。搜索操作会合并服务通用参数和资源级参数。参数值保留为字符串，以便传递 FHIR 日期前缀、token 和引用等语法。资源体使用包含预期 `resourceType` 的基本 JSON 结构，具体 Profile 约束由 FHIR 服务验证。

系统级交互、自定义操作、PATCH、导入项、条件交互、关联资源搜索（include）及安全声明可在 `x-interface-map-report.skipped` 中核对。将文档用于网关配置前，请按部署环境补充认证和授权策略。本版的覆盖范围不包括 POST 搜索表单、异步响应和 Profile 展开。

[HL7 FHIR R4 能力声明](https://hl7.org/fhir/R4/capabilitystatement.html) · [FHIR RESTful API](https://hl7.org/fhir/R4/http.html) · [OpenAPI 3.0.3](https://spec.openapis.org/oas/v3.0.3.html)

项目采用 MIT 许可证，详见 [LICENSE](LICENSE)。

对应的社区悬赏题目为[从 FHIR CapabilityStatement 生成 OpenAPI 规范](https://ideas.intersystems.com/ideas/DPI-I-804)。
