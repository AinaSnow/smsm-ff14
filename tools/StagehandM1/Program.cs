using System.Numerics;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Text.Json;
using Stagehand.Definitions;
using Stagehand.Definitions.Objects;

if(args.Length!=3)throw new ArgumentException("metadata <installed FFXIVClientStructs.dll> <new report.json> | fixtures <new directory> <label>");
if(args[0]=="metadata")
{
    using var input=File.OpenRead(args[1]);using var pe=new PEReader(input);var reader=pe.GetMetadataReader();
    var wanted=new[]{"FFXIVClientStructs.FFXIV.Client.Graphics.Scene.Light","FFXIVClientStructs.FFXIV.Client.Graphics.Render.Light"};
    var layouts=new Dictionary<string,object>();var fieldsByType=new Dictionary<string,Dictionary<string,int>>();var sizes=new Dictionary<string,int>();
    foreach(var handle in reader.TypeDefinitions)
    {
        var type=reader.GetTypeDefinition(handle);var name=reader.GetString(type.Namespace)+"."+reader.GetString(type.Name);
        if(!wanted.Contains(name))continue;
        var fields=new Dictionary<string,int>();
        foreach(var fieldHandle in type.GetFields())
        {
            var field=reader.GetFieldDefinition(fieldHandle);var offset=field.GetOffset();
            if(offset>=0)fields[reader.GetString(field.Name)]=offset;
        }
        var layout=type.GetLayout();sizes[name]=layout.Size;fieldsByType[name]=fields;
        layouts[name]=new{size=layout.Size,fields};
    }
    var scene=wanted[0];var render=wanted[1];
    var compatible=sizes.GetValueOrDefault(scene)==0xB0 && sizes.GetValueOrDefault(render)==0x130 &&
        fieldsByType[scene].GetValueOrDefault("RenderLight",-1)==0x90 && fieldsByType[render].GetValueOrDefault("LightFlags",-1)==0x18 &&
        fieldsByType[render].GetValueOrDefault("Transform",-1)==0x20 && fieldsByType[render].GetValueOrDefault("ColorIntensity",-1)==0x28 &&
        fieldsByType[render].GetValueOrDefault("Range",-1)==0x8C;
    var assembly=reader.GetAssemblyDefinition();
    var report=new{assembly=reader.GetString(assembly.Name),version=assembly.Version.ToString(),light_layout_matches_reviewed_source=compatible,layouts,
        inspected_without_loading_assembly=true,native_calls_executed=false};
    using var output=new FileStream(args[2],FileMode.CreateNew,FileAccess.Write);
    JsonSerializer.Serialize(output,report,new JsonSerializerOptions{WriteIndented=true});
    Console.WriteLine($"Installed light layouts compatible: {compatible}");return compatible?0:1;
}
if(args[0]!="fixtures")throw new ArgumentException("Unknown mode");
var directory=Path.GetFullPath(args[1]);if(Directory.Exists(directory))throw new IOException("Use a new fixture directory");Directory.CreateDirectory(directory);
var empty=new StageDefinition{Info=new StageInfo{Name="SMSM M1 Native Single Light",AuthorName="SMSM",VersionString="M1",Description="Manual single-light test; no automatic stage loading."}};
var parameters=new LightDefinition{DisplayName="SMSM M1 point",IsDisabled=true,Shape=LightShape.Point,Color=Vector3.One,Intensity=8,Range=10,
    FalloffFunction=LightFalloffFunction.Quadratic,FalloffFactor=1,Position=new Vector3(2,1.5f,1.5f),
    EnableSpecularHighlights=true,EnableDynamicShadows=false,EnableCharacterShadows=false,EnableObjectShadows=false,ProjectedTextureGamePath=""};
var preview=new StageDefinition{Info=empty.Info};preview.Objects["smsm_m1_point"]=parameters;
void Write(string name,StageDefinition stage)
{
    var bytes=JsonSerializer.SerializeToUtf8Bytes(stage,StageDefinition.StandardSerializerOptions);
    var roundtrip=JsonSerializer.Deserialize<StageDefinition>(bytes,StageDefinition.StandardSerializerOptions) ?? throw new InvalidDataException("Roundtrip failed");
    if(roundtrip.Objects.Count!=stage.Objects.Count)throw new InvalidDataException("Object count changed");
    if(roundtrip.Objects.Count!=0 && (roundtrip.Objects.Single().Value is not LightDefinition light || !light.IsDisabled || light.Shape!=LightShape.Point))
        throw new InvalidDataException("Unsafe light preset");
    File.WriteAllBytes(Path.Combine(directory,name),bytes);
}
Write("SMSM-M1-native-light.json",empty);Write("disabled-point-parameters.json",preview);
var result=new{official_definitions_version=typeof(StageDefinition).Assembly.GetName().Version!.ToString(),schema_roundtrip=true,
    automatic_show_conditions_added=false,initial_stage_objects=0,preset_disabled=true,ipc_used=false,gpu_association_used=false,label=args[2]};
File.WriteAllText(Path.Combine(directory,"validation.json"),JsonSerializer.Serialize(result,new JsonSerializerOptions{WriteIndented=true}));
Console.WriteLine("Official stage schema roundtrip passed; empty M1 stage and disabled point preset prepared.");
return 0;
