using System.Numerics;
using System.Text.Json;
using System.Security.Cryptography;
using Smsm.StagehandBridge;
using Smsm.StagehandBridge.Core;
using Stagehand.Definitions;
using Stagehand.Definitions.Objects;

static void Require(bool condition, string message) { if (!condition) throw new Exception(message); }
var checks = new List<string>();
foreach(var preset in Enum.GetValues<LightPreset>())
{
    var definition=StageRecipe.Create(new(1,2,3),preset);
    Require(StageDefinition.TryParseDefinitionString(definition.ToDefinitionString(),out var parsed),"Official IPC definition rejected");
    Require(parsed!.Objects.Count==1 && parsed.Objects["point"] is LightDefinition,"Wrong native light scope");
    var light=(LightDefinition)parsed.Objects["point"];
    Require(light.Shape==LightShape.Point && light.Intensity==8 && light.Range==10 && light.Position==new Vector3(1,2,3),"Parameter roundtrip changed");
    Require(light.IsDisabled==(preset==LightPreset.Off) && !light.EnableDynamicShadows && !light.EnableCharacterShadows && !light.EnableObjectShadows,"Light defaults unsafe");
}
checks.Add("official IPC definition roundtrip: three presets");
EnvironmentState env = new(true, new(1, 2, 3), new(1, 2, -1, -1, -1, -1));
foreach (var scenario in new[] { "success", "move", "scene", "provider", "capture-failure", "timeout", "apply-failure", "manual-stop" })
{
    var stage = new FakeStage(); var capture = new FakeCapture(); var journal = new FakeJournal();
    var session = new Session(stage, capture, journal); session.Start(0, env); session.Tick(1, env);
    var id = session.OwnedStage!; Require(id.StartsWith("smsm.m2."), "Unowned namespace");
    // Fail/cancel while WARM is actually active, not just during the disabled baseline.
    if (scenario is not ("success" or "apply-failure")) { session.Tick(2101, env); session.Tick(2102, env); }
    switch (scenario)
    {
        case "success":
            long now = 2101;
            for (int i = 0; i < 3; i++) { session.Tick(now, env); session.Tick(now + 1, env); now += 2100; }
            Require(!session.Running && session.CompletedCaptures == 3, "Finite sequence did not stop");
            Require(stage.Applied.SequenceEqual(new[] { LightPreset.Off, LightPreset.Warm, LightPreset.Cool }), "Wrong preset order");
            break;
        case "move": session.Tick(2103, env with { Player = new(4, 2, 3) }); break;
        case "scene": session.Tick(2103, env with { Place = env.Place with { Room = 1 } }); break;
        case "provider":
            stage.Available = false; session.Tick(2103, env); Require(journal.Owned.Contains(id), "Ownership forgotten while provider unavailable");
            stage.Available = true; session.Tick(2104, env); break;
        case "capture-failure": capture.Throw = true; session.Tick(4203, env); break;
        case "timeout": session.Tick(20000, env); break;
        case "apply-failure": stage.Fail = true; session.Tick(2101, env); session.Tick(2102, env); break;
        case "manual-stop": session.Stop("manual"); break;
    }
    Require(!session.Running && !journal.Owned.Contains(id), scenario + " left owned Stage");
    Require(stage.Removed.All(x => x == id), "Removed another caller's Stage");
    Require(stage.UserStagePresent, "Changed user Stage");
    Require(!stage.LiveOwnedLight,"Left simulated owned light active");
    checks.Add(scenario);
}
{
    var stage = new FakeStage();var journal = new FakeJournal();var session = new Session(stage,new FakeCapture(),journal);
    session.Recover(["foreign.stage", "smsm.m2.old"]);
    Require(stage.Removed.SequenceEqual(new[]{"smsm.m2.old"}),"Recovery touched foreign ID");checks.Add("restart recovery ownership filter");
}
// Real local transport: no original shader/DLL execution; exercise queue, fresh
// acknowledgment and report identity separately from the IPC state machine.
var root = Path.Combine(Environment.CurrentDirectory, "artifacts", "stagehand-m2", "transport-test-" + Guid.NewGuid().ToString("N"));Directory.CreateDirectory(root);
var folder = Path.Combine(root,"SMSM-native-captures");Directory.CreateDirectory(folder);
var ownedFiles = new Dictionary<string,string>();
foreach(var name in new[]{"d3d11.dll","SMSM.NativeLighting.addon64"}) { File.WriteAllText(Path.Combine(root,name),"test only");ownedFiles[name]=Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(Path.Combine(root,name)))); }
File.WriteAllText(Path.Combine(root,"SMSM-native-install.json"),JsonSerializer.Serialize(new{client_build="2026.09.15.0000.0000",output_audit=true,material_roster_sha256="test",files=ownedFiles}));
void Status(string directory, bool active=false) => File.WriteAllText(Path.Combine(folder,"ambient-status.json"),JsonSerializer.Serialize(new{enabled=false,coverage_enabled=false,output_audit_active=active,output_audit_directory=directory}));
void WaitForOff(CaptureClient client)
{
    var deadline=DateTime.UtcNow.AddSeconds(5);
    while(!File.Exists(Path.Combine(folder,"ambient-command.txt")))
    {
        Require(!client.PollPrepare().Done,"Prepared without acknowledged OFF");
        if(DateTime.UtcNow>deadline)throw new Exception("Validation did not publish bounded OFF");
        Thread.Sleep(1);
    }
}
Status("old");var transport=new CaptureClient(root);transport.Prepare();WaitForOff(transport);
Require(!transport.PollPrepare().Done,"Prepared before command consumed");File.Delete(Path.Combine(folder,"ambient-command.txt"));Require(transport.PollPrepare().Done,"OFF acknowledgment failed");
transport.Begin();Require(File.ReadAllText(Path.Combine(folder,"ambient-command.txt"))=="sample e86f0d4916054deb 0\n","Wrong target transport");
File.Delete(Path.Combine(folder,"ambient-command.txt"));Require(!transport.Poll().Done,"Old capture accepted");
Status("output-audit-1-2",true);Require(!transport.Poll().Done,"In-progress report accepted");
var audit=Path.Combine(folder,"output-audit-1-2");Directory.CreateDirectory(audit);
File.WriteAllText(Path.Combine(audit,"report.json"),JsonSerializer.Serialize(new{status="complete",mode="sample",selected_shader=CaptureClient.Target,selected_bytes=100}));
Status("output-audit-1-2");Require(transport.Poll().Done,"Fresh complete sample rejected");
File.WriteAllText(Path.Combine(folder,"ambient-command.txt"),"foreign\n");transport.Cancel();
Require(File.ReadAllText(Path.Combine(folder,"ambient-command.txt"))=="foreign\n","Cancelled foreign command");
checks.Add("transport fresh report and foreign queue preservation");
File.Delete(Path.Combine(folder,"ambient-command.txt"));
var wrong=new CaptureClient(root);wrong.Prepare();WaitForOff(wrong);File.Delete(Path.Combine(folder,"ambient-command.txt"));wrong.PollPrepare();wrong.Begin();File.Delete(Path.Combine(folder,"ambient-command.txt"));
var wrongDir=Path.Combine(folder,"output-audit-1-3");Directory.CreateDirectory(wrongDir);
File.WriteAllText(Path.Combine(wrongDir,"report.json"),JsonSerializer.Serialize(new{status="complete",mode="sample",selected_shader="wrong",selected_bytes=100}));Status("output-audit-1-3");
try { wrong.Poll();throw new Exception("Wrong-target report accepted"); } catch(InvalidDataException){}finally{wrong.Cancel();}
checks.Add("wrong target rejected");
var pending=new CaptureClient(root);pending.Prepare();WaitForOff(pending);Require(File.Exists(Path.Combine(folder,"ambient-command.txt")),"No pending own command");pending.Cancel();
Require(!File.Exists(Path.Combine(folder,"ambient-command.txt")),"Own unconsumed command remained");checks.Add("own pending command cleanup");
var inFlight=new CaptureClient(root);inFlight.Prepare();WaitForOff(inFlight);File.Delete(Path.Combine(folder,"ambient-command.txt"));inFlight.PollPrepare();inFlight.Begin();File.Delete(Path.Combine(folder,"ambient-command.txt"));
Status("output-audit-1-4",true);inFlight.Cancel();
Require(File.ReadAllText(Path.Combine(folder,"ambient-command.txt"))=="off\n","Own active audit not stopped before Poll");checks.Add("abort after native consumption before first poll");
File.Delete(Path.Combine(folder,"ambient-command.txt"));
var cancelled = new CaptureClient(root);cancelled.Prepare();cancelled.Cancel();
try { cancelled.PollPrepare(); throw new Exception("Cancelled preparation resumed"); } catch(InvalidOperationException){}
Require(!File.Exists(Path.Combine(folder,"ambient-command.txt")) && !File.Exists(Path.Combine(folder,".smsm-m2-session.lock")),"Cancelled read-only preparation mutated queue");
checks.Add("cancel before asynchronous validation completion cannot publish");
File.WriteAllText(Path.Combine(root,"d3d11.dll"),"changed");
var invalid=new CaptureClient(root);invalid.Prepare();
try { WaitForOff(invalid); throw new Exception("Changed DLL accepted"); } catch(InvalidDataException){} finally{invalid.Cancel();}
Require(!File.Exists(Path.Combine(folder,"ambient-command.txt")) && !File.Exists(Path.Combine(folder,".smsm-m2-session.lock")),"Invalid package published or leased");
checks.Add("background integrity failure reaches framework before mutation");
foreach(var scenario in new[]{"scene","logout","provider","stop","timeout"})
{
    var stage=new FakeStage();var capture=new FakeCapture();var journal=new FakeJournal();
    var session=new Session(stage,capture,journal);session.Start(0,env,lifecycleOnly:true);session.Tick(1,env);
    Require(stage.LiveOwnedLight && stage.Applied.SequenceEqual(new[]{LightPreset.Warm}),"Lifecycle lamp not warm");
    session.Tick(500,env with { Player=new(50,2,3) });
    Require(session.Running,"Lifecycle movement should allow reaching a zone exit");
    switch(scenario)
    {
        case "scene":session.Tick(501,env with { Place=env.Place with { Territory=3 } });break;
        case "logout":session.Tick(501,env with { Ready=false });break;
        case "provider":stage.Available=false;session.Tick(501,env);stage.Available=true;session.Tick(502,env);break;
        case "stop":session.Stop("plugin disabled");break;
        case "timeout":session.Tick(60002,env);break;
    }
    Require(!session.Running && !stage.LiveOwnedLight && journal.Owned.Count==0,"Lifecycle cleanup failed: "+scenario);
    Require(capture.BeginCount==0 && session.CompletedCaptures==0,"Lifecycle accidentally captured");
    checks.Add("bounded lifecycle without capture: "+scenario);
}
{
    var stage=new FakeStage();var capture=new FakeCapture();var journal=new FakeJournal();var session=new Session(stage,capture,journal);
    session.Start(0,env,materialProbe:true);session.Tick(1,env);
    long now=2101;for(int i=0;i<4;++i){session.Tick(now,env);session.Tick(now+1,env);now+=2100;}
    Require(!session.Running && session.CompletedCaptures==4 && journal.Owned.Count==0,"Probe did not complete finite cleanup");
    Require(stage.Applied.SequenceEqual(new[]{LightPreset.Off,LightPreset.Warm,LightPreset.Cool,LightPreset.Off}),"Probe recovery baseline missing");
    checks.Add("four material probes with returning OFF baseline and cleanup");
}
File.WriteAllText(Path.Combine(root,"d3d11.dll"),"test only");Status("old-probe");
var unsupported=new CaptureClient(root);unsupported.Prepare(true);
try{WaitForOff(unsupported);throw new Exception("Old add-on accepted probe");}catch(InvalidOperationException){}finally{unsupported.Cancel();}
checks.Add("probe capability required before publishing");
File.WriteAllText(Path.Combine(root,"SMSM-native-install.json"),JsonSerializer.Serialize(new{client_build="2026.09.15.0000.0000",output_audit=true,material_input_probe=true,material_roster_sha256="test",files=ownedFiles}));
foreach(var scenario in new[]{"complete","missing-input","wrong-geometry","cancel"})
{
    Status("old-probe");var probe=new CaptureClient(root);probe.Prepare(true);WaitForOff(probe);
    File.Delete(Path.Combine(folder,"ambient-command.txt"));probe.PollPrepare();probe.Begin();
    Require(File.ReadAllText(Path.Combine(folder,"ambient-command.txt"))==$"probe {CaptureClient.Target} {CaptureClient.Elements} {CaptureClient.Vertex}\n","Wrong probe filter");
    File.Delete(Path.Combine(folder,"ambient-command.txt"));
    if(scenario=="cancel")
    {
        Status("output-audit-2-5",true);probe.Cancel();Require(File.ReadAllText(Path.Combine(folder,"ambient-command.txt"))=="off\n","In-flight probe not stopped");File.Delete(Path.Combine(folder,"ambient-command.txt"));
    }
    else
    {
        var name="output-audit-2-"+(scenario=="complete"?"1":scenario=="missing-input"?"2":"3");var dir=Path.Combine(folder,name);Directory.CreateDirectory(dir);
        var inputs=new[]{"-ps-b3","-ps-b6","-ps-t0","-ps-t1"}.Select(slot=>new{label="draw-1"+slot,status=scenario=="missing-input" && slot=="-ps-t1"?"unsupported":"captured",phase="pre_draw"}).ToArray();
        var draw=new{vertex_sha256=CaptureClient.Vertex,elements=CaptureClient.Elements,shader_replaced=false,inputs,images=new[]{new{status="captured"},new{status="captured"},new{status="captured"}}};
        File.WriteAllText(Path.Combine(dir,"report.json"),JsonSerializer.Serialize(new{status="complete",mode="probe",selected_shader=CaptureClient.Target,selected_vertex_sha256=scenario=="wrong-geometry"?"wrong":CaptureClient.Vertex,selected_elements=CaptureClient.Elements,selected_bytes=100,draws=new[]{draw}}));Status(name);
        if(scenario=="complete")Require(probe.Poll().Done,"Complete probe rejected");
        else{try{probe.Poll();throw new Exception("Bad probe accepted");}catch(InvalidDataException){}}
        probe.Cancel();
    }
    checks.Add("material probe transport: "+scenario);
}
var statusFolder=Path.Combine(root,"status-publisher");Directory.CreateDirectory(statusFolder);
var publisher=new StatusPublisher(statusFolder);
using(var legacyLock=new FileStream(Path.Combine(statusFolder,"status.json.tmp"),FileMode.Create,FileAccess.ReadWrite,FileShare.None))
    Require(publisher.TryPublish("{\"state\":1}"),"Legacy temporary lock prevented startup status");
checks.Add("locked legacy status temp cannot fail startup");
Parallel.For(0,100,i=>Require(publisher.TryPublish(JsonSerializer.Serialize(new{state=i})),"Concurrent instance write failed"));
using(var parsed=JsonDocument.Parse(File.ReadAllText(Path.Combine(statusFolder,"status.json"))))Require(parsed.RootElement.TryGetProperty("state",out _),"Partial concurrent JSON");
checks.Add("concurrent constructor and callback status publication serialized");
using(var locked=new FileStream(Path.Combine(statusFolder,"status.json"),FileMode.Open,FileAccess.Read,FileShare.None))
    Require(!publisher.TryPublish("{\"state\":1001}"),"Locked destination was not reported as retryable");
Require(publisher.TryPublish("{\"state\":1001}") && File.ReadAllText(Path.Combine(statusFolder,"status.json"))=="{\"state\":1001}","Failed status update lost instead of retried");
Require(!Directory.EnumerateFiles(statusFolder,".status-*.tmp").Any(),"Status write left temporary files");
checks.Add("locked destination is nonfatal and retries without orphan temp files");
var publisher2=new StatusPublisher(statusFolder);
Parallel.Invoke(()=>{for(int i=0;i<50;++i)publisher.TryPublish(JsonSerializer.Serialize(new{source=1,state=i}));},()=>{for(int i=0;i<50;++i)publisher2.TryPublish(JsonSerializer.Serialize(new{source=2,state=i}));});
using(var parsed=JsonDocument.Parse(File.ReadAllText(Path.Combine(statusFolder,"status.json"))))Require(parsed.RootElement.TryGetProperty("source",out _),"Instance temp files collided");
Require(!Directory.EnumerateFiles(statusFolder,".status-*.tmp").Any(),"Concurrent instance temp files remained");
checks.Add("different instances use distinct temporary files");
Console.WriteLine(JsonSerializer.Serialize(new{passed=true,checks}));

sealed class FakeStage : IStageClient
{
    public bool Available {get;set;}=true; public bool Fail; public bool UserStagePresent=true;public bool LiveOwnedLight;
    public List<LightPreset> Applied=[];public List<string> Removed=[];
    public bool Apply(string id,Vector3 position,LightPreset preset){Applied.Add(preset);LiveOwnedLight=preset!=LightPreset.Off;return !Fail;}
    public bool Remove(string id){Removed.Add(id);LiveOwnedLight=false;return true;}
}
sealed class FakeCapture : ICaptureClient
{
    public bool Throw; public int BeginCount;
    public void Prepare(bool materialProbe=false){} public PollResult PollPrepare()=>new(true);
    public void Begin(){++BeginCount;if(Throw)throw new IOException("failure");} public PollResult Poll()=>new(true,"synthetic-capture");public void Cancel(){}
}
sealed class FakeJournal : ISessionJournal
{
    public HashSet<string> Owned=[];
    public void Own(string id)=>Owned.Add(id);public void Released(string id)=>Owned.Remove(id);public void Event(string kind,object value){}
}
