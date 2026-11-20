Class InterfaceMap.Exporter Extends %RegisteredObject
{

Parameter MAXBYTES = 16777216;

/// Raise a readable conversion or I/O error at the terminal and CLI.
ClassMethod Fail(message As %String) [ Private ]
{
    throw ##class(%Exception.General).%New(message)
}

/// Validate an HTTP(S) base URL and extract its host, optional port and path.
ClassMethod ParseURL(base As %String, Output host, Output port, Output path, Output https) As %String [ Private ]
{
    set regex=##class(%Regex.Matcher).%New("^(https?)://([A-Za-z0-9.-]+|\[[A-Fa-f0-9:]+\])(?::([0-9]+))?(/[^?#\s]*)?$",base)
    if 'regex.Match() { do ..Fail("Expected an HTTP(S) FHIR base URL without credentials, query or fragment.") }
    set https=(regex.Group(1)="https"),host=regex.Group(2),port=regex.Group(3),path=$zstrip(regex.Group(4),">","/")
    if (port'=""),((port<1)!(port>65535)) { do ..Fail("Invalid HTTP port.") }
    if port="" { set port=$select(https:443,1:80) }
    quit $zstrip(base,">","/")
}

/// Read decompressed bytes in bounded chunks, carrying partial UTF-8 across buffer boundaries.
ClassMethod ParseStream(stream As %Stream.Object) As %DynamicObject [ Private ]
{
    set chars=##class(%Stream.TmpCharacter).%New(),total=0,carry=""
    while 'stream.AtEnd {
        set n=32768,chunk=stream.Read(.n,.sc)
        $$$ThrowOnError(sc)
        set total=total+$length(chunk)
        if total>..#MAXBYTES { do ..Fail("CapabilityStatement exceeds 16 MiB.") }
        $$$ThrowOnError(chars.Write($zconvert(chunk,"I","UTF8",carry)))
    }
    if carry'="" { do ..Fail("Incomplete UTF-8 metadata.") }
    do chars.Rewind()
    quit ##class(%DynamicObject).%FromJSON(chars)
}

/// Return an optional collection; reject malformed declared collections.
ClassMethod Items(obj As %DynamicObject, key As %String) As %DynamicArray [ Private ]
{
    set array=obj.%Get(key,[])
    if '$isobject(array) { do ..Fail("Expected an array for "_key) }
    if 'array.%IsA("%Library.DynamicArray") { do ..Fail("Expected an array for "_key) }
    quit array
}

/// Reference a component schema in the FHIR JSON representation.
ClassMethod Content(resource As %String) As %DynamicObject [ Private ]
{
    return {"application/fhir+json":{"schema":{"$ref":("#/components/schemas/"_resource)}}}
}

/// Translate one declared FHIR interaction into its verb, suffix and result resource.
ClassMethod Route(code, name, Output method, Output suffix, Output result) As %Boolean [ Private ]
{
    set method="get",suffix="",result=name
    if code="read" { set suffix="/{id}" }
    elseif code="vread" { set suffix="/{id}/_history/{vid}" }
    elseif code="history-instance" { set suffix="/{id}/_history",result="Bundle" }
    elseif code="history-type" { set suffix="/_history",result="Bundle" }
    elseif code="search-type" { set result="Bundle" }
    elseif code="create" { set method="post" }
    elseif code="update" { set method="put",suffix="/{id}" }
    elseif code="delete" { set method="delete",suffix="/{id}",result="OperationOutcome" }
    else { quit 0 }
    quit 1
}

/// Merge parameters by name, allowing a resource declaration to override the common one.
ClassMethod Parameters(array As %DynamicArray, ByRef params) [ Private ]
{
    for i=0:1:array.%Size()-1 {
        set p=array.%Get(i),name=p.%Get("name")
        if name="" { do ..Fail("Missing search parameter name.") }
        set params(name)=p
    }
}

/// Build a single OpenAPI operation from its advertised FHIR interaction.
ClassMethod Operation(name, code, method, suffix, result, updateCreate, ByRef params) As %DynamicObject [ Private ]
{
    set responses={"default":{"description":"FHIR error","content":(..Content("OperationOutcome"))}}
    if (code="create")!((code="update")&&updateCreate) { do responses.%Set("201",{"description":"Resource created","content":(..Content(name))}) }
    if code'="create" { do responses.%Set("200",{"description":("Successful "_code),"content":(..Content(result))}) }
    if (code="update")!(code="delete") { do responses.%Set("204",{"description":"Success with an empty response body"}) }
    set op={"operationId":(name_"_"_$translate(code,"-","_")),"summary":(code_" "_name),"tags":[(name)],"responses":(responses)}
    set parameters=[]
    for key="id","vid" {
        if suffix[("{"_key_"}") { do parameters.%Push({"name":(key),"in":"path","required":true,"schema":{"type":"string"}}) }
    }
    if code="search-type" {
        set key=""
        for { set key=$order(params(key)) quit:key=""
            set p=params(key)
            do parameters.%Push({"name":(key),"in":"query","schema":{"type":"string"},"description":(p.%Get("documentation","FHIR search parameter")),"x-fhir-search-type":(p.%Get("type","unknown"))})
        }
    }
    if parameters.%Size() { set op.parameters=parameters }
    if (method="put")!(method="post") { set op.requestBody={"required":true,"content":(..Content(name))} }
    quit op
}

/// Add a component that constrains resourceType while allowing resource-specific fields.
ClassMethod AddSchema(schemas, name) [ Private ]
{
    do schemas.%Set(name,{"type":"object","required":["resourceType"],"properties":{"resourceType":{"type":"string","enum":[(name)]}}})
}

/// Report each declared custom operation, which requires more detail to expand.
ClassMethod ReportOperations(obj, scope, skipped) [ Private ]
{
    set array=..Items(obj,"operation")
    for i=0:1:array.%Size()-1 {
        set item=array.%Get(i)
        do skipped.%Push({"scope":(scope),"operation":(item.%Get("name"))})
    }
}

/// Add only advertised methods and preserve unsupported declarations in the report.
ClassMethod AddResource(r, paths, schemas, skipped, ByRef common) [ Private ]
{
    set name=r.%Get("type")
    if '$match(name,"^[A-Z][A-Za-z0-9]*$") { do ..Fail("Invalid FHIR resource type.") }
    do ..AddSchema(schemas,name)
    merge params=common
    do ..Parameters(..Items(r,"searchParam"),.params)
    set arr=..Items(r,"interaction")
    for i=0:1:arr.%Size()-1 {
        set code=arr.%Get(i).%Get("code")
        if '..Route(code,name,.method,.suffix,.result) {
            do skipped.%Push({"scope":(name),"interaction":(code)})
            continue
        }
        set route="/"_name_suffix,item=paths.%Get(route,{})
        set candidate=..Operation(name,code,method,suffix,result,r.%Get("updateCreate"),.params)
        if item.%IsDefined(method) {
            if item.%Get(method).%ToJSON()'=candidate.%ToJSON() { do ..Fail("Conflicting declarations for "_method_" "_route) }
        }
        do item.%Set(method,candidate),paths.%Set(route,item)
    }
    do ..ReportOperations(r,name,skipped)
    for key="conditionalCreate","conditionalRead","conditionalUpdate","conditionalDelete","searchInclude","searchRevInclude" {
        if 'r.%IsDefined(key) { continue }
        set value=r.%Get(key),kind=r.%GetTypeOf(key)
        if (kind="null")!((kind="boolean")&&('value))!((kind="string")&&(value="not-supported")) { continue }
        if $isobject(value) { if 'value.%Size() { continue } }
        set entry={"scope":(name),"declaration":(key)}
        if kind="boolean" { do entry.%Set("value",value,"boolean") } else { set entry.value=value }
        do skipped.%Push(entry)
    }
}

/// Map server-mode CapabilityStatement blocks to OpenAPI paths and component references.
ClassMethod Convert(statement As %DynamicObject, base As %String) As %DynamicObject
{
    set base=..ParseURL(base,.host,.port,.path,.https)
    if statement.%Get("resourceType")'="CapabilityStatement" { do ..Fail("Expected a FHIR CapabilityStatement.") }
    if '$match(statement.%Get("fhirVersion"),"^4\.0\.[0-9]+$") { do ..Fail("Expected FHIR R4 (4.0.x).") }
    set arr=..Items(statement,"format"),json=0
    for i=0:1:arr.%Size()-1 {
        set fmt=arr.%Get(i)
        if (fmt="json")!(fmt="application/json")!(fmt="application/fhir+json") { set json=1 }
    }
    if 'json { do ..Fail("The server does not advertise FHIR JSON.") }
    set paths={"/metadata":{"get":{"operationId":"server_capabilities","responses":{"200":{"description":"Server capabilities","content":(..Content("CapabilityStatement"))}}}}}
    set schemas={},skipped=[]
    for name="Bundle","CapabilityStatement","OperationOutcome" { do ..AddSchema(schemas,name) }
    set arr=..Items(statement,"imports")
    for i=0:1:arr.%Size()-1 { do skipped.%Push({"scope":"server","import":(arr.%Get(i))}) }
    set blocks=..Items(statement,"rest"),found=0
    for b=0:1:blocks.%Size()-1 {
        set block=blocks.%Get(b)
        if block.%Get("mode")'="server" { continue }
        set found=1
        kill common
        do ..Parameters(..Items(block,"searchParam"),.common)
        if block.%IsDefined("security") { do skipped.%Push({"scope":"server","declaration":"security","note":"Review the source security declaration before deploying to a gateway."}) }
        set arr=..Items(block,"interaction")
        for i=0:1:arr.%Size()-1 { do skipped.%Push({"scope":"server","interaction":(arr.%Get(i).%Get("code"))}) }
        do ..ReportOperations(block,"server",skipped)
        set resources=..Items(block,"resource")
        for i=0:1:resources.%Size()-1 { do ..AddResource(resources.%Get(i),paths,schemas,skipped,.common) }
    }
    if 'found { do ..Fail("A server REST declaration is required.") }
    set title=statement.%Get("title",statement.%Get("name","FHIR R4 server"))
    set version=statement.%Get("version",statement.%Get("fhirVersion"))
    return {"openapi":"3.0.3","info":{"title":(title),"version":(version)},"servers":[{"url":(base)}],"paths":(paths),"components":{"schemas":(schemas)},"x-interface-map-report":{"skipped":(skipped),"schemaScope":"FHIR JSON resource envelopes only"}}
}

/// Fetch metadata or read an offline file, then atomically publish a UTF-8 specification.
/// The directory argument remains available for callers of the previous terminal interface.
ClassMethod Generate(base As %String, outputFile As %String, directory As %String = "", source As %String = "", tls As %String = "FhirInterfaceTLS") As %Integer
{
    set base=..ParseURL(base,.host,.port,.path,.https)
    if source'="" {
        if ##class(%File).NormalizeFilename(source)=##class(%File).NormalizeFilename(outputFile) { do ..Fail("Source and output must differ.") }
        if '##class(%File).Exists(source) { do ..Fail("Metadata file does not exist.") }
        set raw=##class(%Stream.FileBinary).%New()
        $$$ThrowOnError(raw.LinkToFile(source))
    } else {
        set request=##class(%Net.HttpRequest).%New()
        set request.Server=host,request.Port=port,request.Https=https
        set request.Timeout=30,request.OpenTimeout=10,request.ReadRawMode=1,request.AcceptGzip=1
        if https { set request.SSLConfiguration=tls,request.SSLCheckServerIdentity=1,request.SSLUseSNI=1 }
        do request.SetHeader("Accept","application/fhir+json")
        $$$ThrowOnError(request.Get(path_"/metadata"))
        set resp=request.HttpResponse
        if (resp.StatusCode<200)!(resp.StatusCode>299) { do ..Fail("Metadata HTTP status "_resp.StatusCode) }
        set raw=resp.Data
    }
    set doc=..Convert(..ParseStream(raw),base)
    set temp=outputFile_"."_$system.Util.CreateGUID()_".tmp"
    try {
        set out=##class(%Stream.FileCharacter).%New()
        $$$ThrowOnError(out.LinkToFile(temp))
        set out.TranslateTable="UTF8"
        do doc.%ToJSON(out)
        $$$ThrowOnError(out.%Save())
        set out=""
        if '##class(%File).Rename(temp,outputFile,.err) { do ..Fail("Could not replace output file: "_err) }
    } catch ex {
        set out=""
        if ##class(%File).Exists(temp) { do ##class(%File).Delete(temp) }
        throw ex
    }
    quit doc.paths.%Size()
}

}
