using System.Globalization;
using System.Security.Cryptography;
using System.Text.Json;
using Lumina;
using Lumina.Data;

// Confirm a proposed package name against both the SqPack index and exact DXBC.
// Package identity is not evidence of a named object's visible pixel coverage.
internal static class ShaderIdentity
{
    public static int MaterialRoster(string client, string extraction, string report)
    {
        client=Path.GetFullPath(client);extraction=Path.GetFullPath(extraction);report=Path.GetFullPath(report);
        if(File.Exists(report) || report.StartsWith(client+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))
            throw new ArgumentException("Use a new report outside the client.");
        using var manifest=JsonDocument.Parse(File.ReadAllBytes(Path.Combine(extraction,"manifest.json")));
        var version=File.ReadAllText(Path.Combine(client,"game/ffxivgame.ver")).Trim();
        if(manifest.RootElement.GetProperty("ClientBuild").GetString()!=version)throw new InvalidDataException("Build mismatch");
        using var game=new GameData(Path.Combine(client,"game/sqpack"));
        var entries=manifest.RootElement.GetProperty("Shaders").EnumerateArray().ToArray();
        var identities=new Dictionary<string,(string Hash,SortedSet<string> Packages)>();
        var packages=new List<object>();
        foreach(var name in new[]{"hair","skin","character","characterlegacy","characterglass","characterstockings"})
        {
            var path="shader/sm5/shpk/"+name+".shpk";var key=IndexKey(path).ToString("x16");
            var selected=entries.Where(e=>e.GetProperty("ResourceHash").GetString()==key && e.GetProperty("Profile").GetString()=="ps_5_0").ToArray();
            var file=game.GetFile<FileResource>(path);
            if(file==null || selected.Length==0)throw new InvalidDataException("Missing expected material package or extracted PS: "+name);
            if(!file.Data.AsSpan(0,4).SequenceEqual("ShPk"u8))throw new InvalidDataException("Invalid ShPk: "+name);
            foreach(var entry in selected)
            {
                var bytes=file.Data.AsSpan(entry.GetProperty("Offset").GetInt32(),entry.GetProperty("Length").GetInt32());
                var sha=entry.GetProperty("Sha256").GetString()!;var hash=entry.GetProperty("Hash").GetString()!;
                var extracted=Path.GetFullPath(Path.Combine(extraction,entry.GetProperty("File").GetString()!));
                if(!extracted.StartsWith(extraction+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase) ||
                    !bytes.StartsWith("DXBC"u8) || Convert.ToHexStringLower(SHA256.HashData(bytes))!=sha || !bytes.SequenceEqual(File.ReadAllBytes(extracted)))
                    throw new InvalidDataException("Material package shader mismatch: "+name);
                if(!identities.TryGetValue(sha,out var identity))identity=(hash,new SortedSet<string>(StringComparer.Ordinal));
                if(identity.Hash!=hash)throw new InvalidDataException("Inconsistent shader hash");
                identity.Packages.Add(name);identities[sha]=identity;
            }
            packages.Add(new{name,resource_path=path,resource_hash=key,verified_pixel_shaders=selected.Select(e=>e.GetProperty("Sha256").GetString()).Distinct().Count()});
        }
        var rows=identities.OrderBy(e=>e.Key,StringComparer.Ordinal).Select(e=>new{sha256=e.Key,hash=e.Value.Hash,packages=e.Value.Packages.ToArray()}).ToArray();
        Directory.CreateDirectory(Path.GetDirectoryName(report)!);
        using var output=new FileStream(report,FileMode.CreateNew,FileAccess.Write);
        JsonSerializer.Serialize(output,new{schema=1,client_build=version,verified_package_reads=true,packages,shaders=rows},new JsonSerializerOptions{WriteIndented=true});
        Console.WriteLine($"Verified {packages.Count} material packages and {rows.Length} unique pixel shaders against client bytes.");
        return 0;
    }

    public static ulong IndexKey(string path)
    {
        var slash = path.LastIndexOf('/');
        return GameData.GetFileHash(path.AsSpan(0, slash), path.AsSpan(slash + 1));
    }

    public static int Verify(string client, string extraction, string target, string resourcePath, string report)
    {
        client = Path.GetFullPath(client);
        extraction = Path.GetFullPath(extraction);
        report = Path.GetFullPath(report);
        if (File.Exists(report)) throw new IOException("Use a new report path.");
        if (report.StartsWith(client + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
            throw new ArgumentException("Report must be outside the client.");
        if (target.Length != 16 || !ulong.TryParse(target, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out _))
            throw new ArgumentException("Expected 16-digit shader hash.");
        if (!resourcePath.StartsWith("shader/sm5/shpk/", StringComparison.Ordinal) ||
            !resourcePath.EndsWith(".shpk", StringComparison.Ordinal) || resourcePath.Contains("..") || resourcePath.Contains('\\'))
            throw new ArgumentException("Expected shader/sm5/shpk/<name>.shpk.");
        using var manifest = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(extraction, "manifest.json")));
        var version = File.ReadAllText(Path.Combine(client, "game/ffxivgame.ver")).Trim();
        if (manifest.RootElement.GetProperty("ClientBuild").GetString() != version)
            throw new InvalidDataException("Client build differs from extraction.");
        var entries = manifest.RootElement.GetProperty("Shaders").EnumerateArray().ToArray();
        var matches = entries.Where(e => e.GetProperty("Hash").GetString() == target.ToLowerInvariant()).ToArray();
        if (matches.Length == 0) throw new InvalidDataException("Shader absent from extraction.");
        var key = IndexKey(resourcePath).ToString("x16");
        using var game = new GameData(Path.Combine(client, "game/sqpack"));
        var file = game.GetFile<FileResource>(resourcePath) ?? throw new IOException("Named package not found in client.");
        if (!file.Data.AsSpan(0, 4).SequenceEqual("ShPk"u8)) throw new InvalidDataException("Expected ShPk header.");
        foreach (var entry in matches)
        {
            if (entry.GetProperty("ResourceHash").GetString() != key)
                throw new InvalidDataException($"Package hash {key} differs from manifest {entry.GetProperty("ResourceHash").GetString()}; do not infer exclusive identity.");
            var offset = entry.GetProperty("Offset").GetInt32();
            var length = entry.GetProperty("Length").GetInt32();
            var bytes = file.Data.AsSpan(offset, length);
            var relative = entry.GetProperty("File").GetString()!;
            var extracted = Path.GetFullPath(Path.Combine(extraction, relative));
            if (!extracted.StartsWith(extraction + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Manifest payload escapes extraction.");
            if (!bytes.StartsWith("DXBC"u8) || !bytes.SequenceEqual(File.ReadAllBytes(extracted)) ||
                Convert.ToHexStringLower(SHA256.HashData(bytes)) != entry.GetProperty("Sha256").GetString())
                throw new InvalidDataException("Named package bytes differ from verified extracted shader.");
        }
        var packageEntries = entries.Where(e => e.GetProperty("ResourceHash").GetString() == key).ToArray();
        var result = new
        {
            client_build = version, target, resource_path = resourcePath, resource_hash = key,
            named_package_read = true, exact_dxbc_match = true,
            shader_sha256 = matches[0].GetProperty("Sha256").GetString(),
            matching_manifest_entries = matches.Length,
            unique_package_pixel_shaders = packageEntries.Where(e => e.GetProperty("Profile").GetString() == "ps_5_0")
                .Select(e => e.GetProperty("Hash").GetString()).Distinct().Count(),
            visible_player_coverage_verified = false,
            limits = new[] { "Exact package membership does not identify a player or NPC draw.",
                "One shader variant does not establish coverage of all hair, skin or clothing.",
                "No new frame capture or game rendering modification was performed." }
        };
        Directory.CreateDirectory(Path.GetDirectoryName(report)!);
        using var output = new FileStream(report, FileMode.CreateNew, FileAccess.Write);
        JsonSerializer.Serialize(output, result, new JsonSerializerOptions { WriteIndented = true });
        Console.WriteLine(JsonSerializer.Serialize(result));
        return 0;
    }
}
