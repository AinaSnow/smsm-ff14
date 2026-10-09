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
Status("old");var transport=new CaptureClient(root);transport.Prepare();
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
var wrong=new CaptureClient(root);wrong.Prepare();File.Delete(Path.Combine(folder,"ambient-command.txt"));wrong.PollPrepare();wrong.Begin();File.Delete(Path.Combine(folder,"ambient-command.txt"));
var wrongDir=Path.Combine(folder,"output-audit-1-3");Directory.CreateDirectory(wrongDir);
File.WriteAllText(Path.Combine(wrongDir,"report.json"),JsonSerializer.Serialize(new{status="complete",mode="sample",selected_shader="wrong",selected_bytes=100}));Status("output-audit-1-3");
try { wrong.Poll();throw new Exception("Wrong-target report accepted"); } catch(InvalidDataException){}finally{wrong.Cancel();}
checks.Add("wrong target rejected");
var pending=new CaptureClient(root);pending.Prepare();Require(File.Exists(Path.Combine(folder,"ambient-command.txt")),"No pending own command");pending.Cancel();
Require(!File.Exists(Path.Combine(folder,"ambient-command.txt")),"Own unconsumed command remained");checks.Add("own pending command cleanup");
var inFlight=new CaptureClient(root);inFlight.Prepare();File.Delete(Path.Combine(folder,"ambient-command.txt"));inFlight.PollPrepare();inFlight.Begin();File.Delete(Path.Combine(folder,"ambient-command.txt"));
Status("output-audit-1-4",true);inFlight.Cancel();
Require(File.ReadAllText(Path.Combine(folder,"ambient-command.txt"))=="off\n","Own active audit not stopped before Poll");checks.Add("abort after native consumption before first poll");
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
    public bool Throw;
    public void Prepare(){} public PollResult PollPrepare()=>new(true);
    public void Begin(){if(Throw)throw new IOException("failure");} public PollResult Poll()=>new(true,"synthetic-capture");public void Cancel(){}
}
sealed class FakeJournal : ISessionJournal
{
    public HashSet<string> Owned=[];
    public void Own(string id)=>Owned.Add(id);public void Released(string id)=>Owned.Remove(id);public void Event(string kind,object value){}
}
