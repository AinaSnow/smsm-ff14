using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Lumina;
using Lumina.Data;

if (args.Length == 6 && args[0] == "--identify")
{
    try { return ShaderIdentity.Verify(args[1], args[2], args[3], args[4], args[5]); }
    catch (Exception e) when (e is IOException or InvalidDataException or ArgumentException or JsonException)
    {
        Console.Error.WriteLine(e.Message);
        return 1;
    }
}

if (args.Length != 2)
{
    Console.Error.WriteLine("Usage: ShaderAudit <client root> <new output directory>");
    Console.Error.WriteLine("   or: ShaderAudit --identify <client root> <extraction> <shader hash> <resource path> <new report.json>");
    return 2;
}
var client = Path.GetFullPath(args[0]);
var output = Path.GetFullPath(args[1]);
var gamePath = Path.Combine(client, "game");
if (!File.Exists(Path.Combine(gamePath, "ffxivgame.ver"))) throw new ArgumentException("Missing game/ffxivgame.ver");
if (Directory.Exists(output)) throw new IOException("Output already exists; use a new directory to preserve prior evidence.");
if (output.StartsWith(client + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase) || output.Equals(client, StringComparison.OrdinalIgnoreCase))
    throw new ArgumentException("Output must be outside the game installation.");
Directory.CreateDirectory(Path.Combine(output, "dxbc"));
var version = File.ReadAllText(Path.Combine(gamePath, "ffxivgame.ver")).Trim();
using var game = new GameData(Path.Combine(gamePath, "sqpack"));
var entries = new List<object>();
var resources = 0;
var unique = new HashSet<string>();
// Names are hints only. Enumerate the complete shader category even when names are unknown.
var names = new Dictionary<ulong, string>();
foreach (var name in new[] { "tonemapping", "brightpassfilter", "mergetextures2", "fxaa", "colorgrading", "radialblur", "vignette" })
foreach (var folder in new[] { "shader/sm5/", "shader/sm5/shcd/" })
{
    var path = folder + name + ".shcd";
    names[ShaderIdentity.IndexKey(path)] = path;
}
foreach (var name in new[] { "character", "characterlegacy", "characterglass", "characterstockings", "skin", "hair", "iris", "bg", "bgcolorchange", "bguvscroll", "bguvscrollb", "bgcrestchange" })
{
    var path = "shader/sm5/shpk/" + name + ".shpk";
    names[ShaderIdentity.IndexKey(path)] = path;
}
foreach (var repo in game.Repositories.OrderBy(r => r.Key))
{
    if (!repo.Value.Categories.TryGetValue(5, out var categories)) continue;
    foreach (var category in categories)
    foreach (var key in (category.IndexHashTableEntries ?? throw new InvalidDataException("Missing index hash table")).Keys.Order())
    {
        var file = category.GetFile<FileResource>(key);
        if (file == null) throw new IOException($"Cannot read shader resource {key:x16}");
        resources++;
        var data = file.Data;
        for (var offset = 0; offset <= data.Length - 32; offset++)
        {
            if (!data.AsSpan(offset, 4).SequenceEqual("DXBC"u8)) continue;
            var length = Read(data, offset + 24);
            var count = Read(data, offset + 28);
            if (length < 32 || length > data.Length - offset || count > (length - 32) / 4) continue;
            string? profile = null;
            var valid = true;
            for (var i = 0; i < count; i++)
            {
                var chunk = Read(data, offset + 32 + (int)i * 4);
                if (chunk > length - 8) { valid = false; break; }
                var start = offset + (int)chunk;
                var size = Read(data, start + 4);
                if (size > length - chunk - 8) { valid = false; break; }
                var tag = Encoding.ASCII.GetString(data, start, 4);
                if (tag is not ("SHDR" or "SHEX") || size < 8) continue;
                var token = Read(data, start + 8);
                var stage = (token >> 16) switch { 0 => "ps", 1 => "vs", 2 => "gs", 3 => "hs", 4 => "ds", 5 => "cs", _ => "unknown" };
                profile = $"{stage}_{(token >> 4) & 15}_{token & 15}";
            }
            if (!valid || profile == null) continue;
            var blob = data.AsSpan(offset, (int)length).ToArray();
            // Traditional 3DMigoto hash: unseeded 64-bit FNV-1 (multiply, then XOR).
            ulong hash = 0;
            foreach (var b in blob) hash = unchecked(hash * 0x100000001b3UL) ^ b;
            var sha256 = Convert.ToHexStringLower(SHA256.HashData(blob));
            var filename = $"{hash:x16}-{profile[..2]}.bin";
            var destination = Path.Combine(output, "dxbc", filename);
            if (File.Exists(destination) && !File.ReadAllBytes(destination).AsSpan().SequenceEqual(blob))
                throw new InvalidDataException($"Shader hash collision: {filename}");
            if (unique.Add(filename)) File.WriteAllBytes(destination, blob);
            entries.Add(new { Repository = repo.Key, category.Chunk, ResourceHash = $"{key:x16}",
                ResourceMagic = Encoding.ASCII.GetString(data, 0, Math.Min(4, data.Length)),
                ResourcePath = names.GetValueOrDefault(key), Offset = offset, Length = length,
                Profile = profile, Hash = $"{hash:x16}", Sha256 = sha256, File = "dxbc/" + filename });
            offset += (int)length - 1;
        }
    }
}
File.WriteAllText(Path.Combine(output, "manifest.json"), JsonSerializer.Serialize(new
{
    ClientBuild = version, HashAlgorithm = "3dmigoto-unseeded-fnv1-64", ResourceCount = resources,
    ShaderCount = entries.Count, UniqueShaderCount = unique.Count, Shaders = entries
}, new JsonSerializerOptions { WriteIndented = true }));
Console.WriteLine($"Build {version}: {resources} resources, {entries.Count} shaders, {unique.Count} unique -> {output}");
return 0;

static uint Read(byte[] data, int offset) => BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(offset, 4));
