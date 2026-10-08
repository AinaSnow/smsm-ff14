#pragma once
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <Windows.h>
#include <d3d11_1.h>
#include <wrl/client.h>
#include <bcrypt.h>
#include <algorithm>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace smsm {
using Microsoft::WRL::ComPtr;
namespace fs = std::filesystem;
using Clock = std::chrono::steady_clock;
inline double milliseconds(Clock::time_point start) {
    return std::chrono::duration<double, std::milli>(Clock::now() - start).count();
}
inline void check(HRESULT hr) {
    if (FAILED(hr)) throw std::runtime_error("HRESULT " + std::to_string(static_cast<uint32_t>(hr)));
}
inline std::string quote(const std::string &s) {
    std::ostringstream out; out << '"';
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') out << '\\' << c;
        else if (c < 32) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << int(c);
        else out << c;
    }
    return out.str() + '"';
}
template<class T> std::string number(T x) { std::ostringstream s; s << std::setprecision(12) << x; return s.str(); }
inline std::string array(const std::vector<std::string> &items) {
    std::string s = "["; for (const auto &x : items) { if (s.size() > 1) s += ','; s += x; } return s + ']';
}
struct Json {
    std::map<std::string, std::string> fields;
    void text(const std::string &key, const std::string &value) { fields[key] = quote(value); }
    template<class T> void num(const std::string &key, T value) { fields[key] = number(value); }
    std::string str() const {
        std::string s = "{";
        for (const auto &[k,v] : fields) { if (s.size() > 1) s += ','; s += quote(k) + ':' + v; }
        return s + '}';
    }
};
inline std::string sha256(const void *data, size_t size) {
    if (size > ULONG_MAX) throw std::runtime_error("SHA input too large");
    BCRYPT_ALG_HANDLE alg = nullptr; BCRYPT_HASH_HANDLE hash = nullptr;
    auto ok = [](NTSTATUS s) { if (s < 0) throw std::runtime_error("BCrypt failure"); };
    ok(BCryptOpenAlgorithmProvider(&alg, BCRYPT_SHA256_ALGORITHM, nullptr, 0));
    unsigned char digest[32] = {};
    try {
        ok(BCryptCreateHash(alg, &hash, nullptr, 0, nullptr, 0, 0));
        ok(BCryptHashData(hash, (PUCHAR)data, (ULONG)size, 0));
        ok(BCryptFinishHash(hash, digest, sizeof(digest), 0));
    } catch (...) { if (hash) BCryptDestroyHash(hash); BCryptCloseAlgorithmProvider(alg, 0); throw; }
    BCryptDestroyHash(hash); BCryptCloseAlgorithmProvider(alg, 0);
    std::ostringstream out;
    for (auto b : digest) out << std::hex << std::setw(2) << std::setfill('0') << int(b);
    return out.str();
}
struct Target { std::string migoto, sha; };
inline const std::vector<Target> game_targets = {
    {"415a922293923fa4", "907ce4b6cc047a429a41c537a33a44c3fff04bd74ea66ad780e9b669d72dd740"},
    {"980154264a89fba1", "f8face0fb530f3b884c2a6b2af289fa1a8bb3ed0e4301b03efd34afadf7c76f7"}
};
// Exact byte sizes only. Unsupported formats are reported, never converted.
inline uint32_t texel_bytes(DXGI_FORMAT f) {
    switch (f) {
    case DXGI_FORMAT_R32G32B32A32_TYPELESS: case DXGI_FORMAT_R32G32B32A32_FLOAT: return 16;
    case DXGI_FORMAT_R16G16B16A16_TYPELESS: case DXGI_FORMAT_R16G16B16A16_FLOAT:
    case DXGI_FORMAT_R16G16B16A16_UNORM: case DXGI_FORMAT_R32G32_FLOAT: return 8;
    case DXGI_FORMAT_R32_TYPELESS: case DXGI_FORMAT_D32_FLOAT: case DXGI_FORMAT_R32_FLOAT:
    case DXGI_FORMAT_R24G8_TYPELESS: case DXGI_FORMAT_D24_UNORM_S8_UINT: case DXGI_FORMAT_R24_UNORM_X8_TYPELESS:
    case DXGI_FORMAT_R11G11B10_FLOAT: case DXGI_FORMAT_R10G10B10A2_UNORM:
    case DXGI_FORMAT_R8G8B8A8_TYPELESS: case DXGI_FORMAT_R8G8B8A8_UNORM: case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB:
    case DXGI_FORMAT_B8G8R8A8_UNORM: case DXGI_FORMAT_B8G8R8A8_TYPELESS: case DXGI_FORMAT_B8G8R8A8_UNORM_SRGB:
    case DXGI_FORMAT_R16G16_FLOAT: case DXGI_FORMAT_R16G16_UNORM: return 4;
    case DXGI_FORMAT_R16_TYPELESS: case DXGI_FORMAT_R16_FLOAT: case DXGI_FORMAT_D16_UNORM: case DXGI_FORMAT_R16_UNORM: return 2;
    default: return 0;
    }
}
struct History {
    uint64_t generation = 0, event = 0, frame = 0;
    std::string last = "unknown";
};
struct Snapshot {
    Json meta;
    ComPtr<ID3D11Resource> source, staging;
    uint32_t subresource = 0, width = 0, height = 1, row_bytes = 0;
    uint64_t bytes = 0;
    bool buffer = false;
};
struct Draw {
    Json meta;
    std::vector<Snapshot> resources;
};
class Diagnostic {
public:
    static constexpr uint64_t max_budget = 256ull * 1024 * 1024;
    bool enabled = false, internal = false;
    uint64_t budget = max_budget, frame = 0, draw = 0, event = 0, generation = 0;
    std::vector<Target> targets = game_targets;
    std::map<uint64_t, std::pair<std::string,std::string>> shaders;
    std::map<uint64_t, History> histories;
    std::vector<Draw> draws;
    fs::path root, capture_dir;
    bool recording = false, waiting = false;
    std::string status = "idle";
    uint64_t captured_frame = 0, bytes = 0, readback_presents = 0;
    uint64_t deferred_draws = 0;
    double copy_ms = 0, map_ms = 0;
    std::set<std::string> seen;

    explicit Diagnostic(fs::path path) : root(std::move(path)) {}
    void init_resource(uint64_t id, bool initial) {
        histories[id] = {++generation, ++event, frame, initial ? "initial_data" : "created_without_initial_data"};
    }
    void destroy_resource(uint64_t id) { ++event; histories.erase(id); }
    void write(uint64_t id, const std::string &kind) {
        if (internal || !enabled || !id) return;
        auto &h = histories[id]; h.event = ++event; h.frame = frame; h.last = kind;
    }
    void init_shader(uint64_t id, const void *code, size_t size) {
        std::string sha = sha256(code, size);
        // All VS/PS identities are retained for the selected draw; no Migoto hash recomputation.
        std::string target;
        for (const auto &t : targets) if (sha == t.sha) target = t.migoto;
        shaders[id] = {target, sha};
    }
    void stop() {
        if (recording || waiting) { status = "cancelled"; finish(); }
        enabled = false;
    }
    bool arm() {
        if (!enabled || recording || waiting) return false;
        fs::create_directories(root);
        for (uint32_t n = 0; ; ++n) {
            capture_dir = root / ("capture-" + number(GetCurrentProcessId()) + "-" + number(GetTickCount64()) + "-" + number(n));
            if (fs::create_directory(capture_dir)) break;
        }
        captured_frame = frame;
        recording = true; status = "armed"; bytes = 0; readback_presents = 0; deferred_draws = 0;
        copy_ms = map_ms = 0; seen.clear(); draws.clear();
        return true;
    }
    // Called once at Present, before optionally arming the following frame.
    void present(ID3D11DeviceContext *ctx) {
        if (recording) {
            recording = false; waiting = true;
            status = draws.empty() ? "missing_targets" : "readback_pending";
        }
        if (waiting) {
            ++readback_presents;
            bool ready = true;
            const auto start = Clock::now(); internal = true;
            try {
                for (auto &d : draws) for (auto &s : d.resources) {
                    if (!s.staging || s.meta.fields.count("file")) continue;
                    D3D11_MAPPED_SUBRESOURCE mapped = {};
                    HRESULT hr = ctx->Map(s.staging.Get(), 0, D3D11_MAP_READ, D3D11_MAP_FLAG_DO_NOT_WAIT, &mapped);
                    if (hr == DXGI_ERROR_WAS_STILL_DRAWING) { ready = false; continue; }
                    if (FAILED(hr)) { s.meta.text("status", "map_failed"); s.meta.num("hresult", uint32_t(hr)); s.staging.Reset(); continue; }
                    // Keep padding out of the file while retaining exact source format bits.
                    std::vector<unsigned char> raw;
                    try {
                        if (!s.buffer && mapped.RowPitch < s.row_bytes) throw std::runtime_error("invalid_row_pitch");
                        raw.resize(static_cast<size_t>(s.bytes));
                        for (uint32_t y = 0; y < s.height; ++y)
                            memcpy(raw.data() + size_t(y) * s.row_bytes, static_cast<unsigned char *>(mapped.pData) + size_t(y) * (s.buffer ? s.row_bytes : mapped.RowPitch), s.row_bytes);
                        s.meta.num("mapped_row_pitch", mapped.RowPitch);
                    } catch (...) { ctx->Unmap(s.staging.Get(), 0); throw; }
                    ctx->Unmap(s.staging.Get(), 0);
                    const std::string name = "draw-" + d.meta.fields.at("draw") + "-" + s.meta.fields.at("label").substr(1, s.meta.fields.at("label").size()-2) + ".bin";
                    std::ofstream out(capture_dir / name, std::ios::binary);
                    out.exceptions(std::ios::badbit | std::ios::failbit);
                    out.write(reinterpret_cast<char *>(raw.data()), raw.size()); out.close();
                    s.meta.text("file", name); s.meta.text("sha256", sha256(raw.data(), raw.size())); s.meta.text("status", "captured");
                    s.staging.Reset();
                }
            } catch (...) { internal = false; status = "readback_error"; map_ms += milliseconds(start); finish(); throw; }
            internal = false; map_ms += milliseconds(start);
            if (ready || readback_presents >= 8) {
                if (!ready) status = "readback_timeout";
                else if (!draws.empty()) status = seen.size() == targets.size() ? "snapshots_complete" : "partial_targets";
                finish();
            }
        }
        ++frame; draw = 0;
    }
    void finish() {
        std::vector<std::string> rows;
        for (auto &d : draws) {
            std::vector<std::string> resources;
            for (auto &s : d.resources) {
                if (s.staging || s.meta.fields["status"] == quote("planned")) { s.meta.text("status", status); s.staging.Reset(); }
                resources.push_back(s.meta.str()); s.source.Reset();
            }
            d.meta.fields["resources"] = array(resources); rows.push_back(d.meta.str());
        }
        Json report;
        report.num("schema", 1); report.text("source_kind", "d3d11_runtime_capture"); report.text("status", status);
        report.text("phase", "pre_draw"); report.num("source_frame", captured_frame); report.num("budget_bytes", budget);
        report.num("selected_raw_bytes", bytes); report.num("copy_enqueue_ms", copy_ms); report.num("readback_and_io_ms", map_ms);
        report.num("readback_presents", readback_presents); report.num("deferred_draws_skipped", deferred_draws);
        report.fields["game_semantics_verified"] = "false";
        report.text("history_coverage", "observed_callbacks_only; disabled-period writes, indirect/UAV/deferred producers are not complete");
        report.fields["draws"] = array(rows);
        std::vector<std::string> missing;
        for (const auto &t : targets) if (!seen.count(t.migoto)) missing.push_back(quote(t.migoto));
        report.fields["missing_targets"] = array(missing);
        std::ofstream out(capture_dir / "manifest.json"); out.exceptions(std::ios::badbit | std::ios::failbit); out << report.str() << '\n';
        recording = waiting = false; draws.clear();
    }
    Json resource_meta(ID3D11Resource *resource, const std::string &label, const std::string &semantic) {
        Json m; m.text("label", label); m.text("semantic", semantic); m.text("semantic_status", "candidate");
        const auto id = reinterpret_cast<uint64_t>(resource);
        m.num("native_resource", id); m.num("frame", captured_frame); m.num("draw", draw); m.text("phase", "pre_draw");
        const auto h = histories.find(id);
        if (h != histories.end()) {
            m.num("generation", h->second.generation); m.num("last_event_sequence", h->second.event);
            m.num("last_observed_event_frame", h->second.frame); m.text("last_observed_event", h->second.last);
        } else { m.num("generation", 0); m.text("last_observed_event", "unknown_initial_state"); }
        return m;
    }
    Snapshot buffer(ID3D11Buffer *source, const std::string &label, UINT first, UINT count) {
        Snapshot s; s.meta = resource_meta(source, label, "camera_or_lighting_constants");
        if (!source) { s.meta.text("status", "missing_binding"); return s; }
        D3D11_BUFFER_DESC desc; source->GetDesc(&desc);
        s.source = source; s.buffer = true; s.row_bytes = desc.ByteWidth; s.bytes = desc.ByteWidth;
        s.meta.num("byte_width", desc.ByteWidth); s.meta.num("bind_flags", desc.BindFlags); s.meta.num("usage", desc.Usage);
        s.meta.num("constant_first", first); s.meta.num("constant_count", count); s.meta.num("row_bytes", s.row_bytes);
        s.meta.num("structure_stride", desc.StructureByteStride); s.meta.text("status", "planned"); return s;
    }
    Snapshot texture(ID3D11ShaderResourceView *view, const std::string &label, const std::string &semantic) {
        Snapshot s;
        ComPtr<ID3D11Resource> resource;
        if (view) view->GetResource(&resource);
        s.meta = resource_meta(resource.Get(), label, semantic);
        if (!resource) { s.meta.text("status", "missing_binding"); return s; }
        D3D11_SHADER_RESOURCE_VIEW_DESC vd; view->GetDesc(&vd);
        s.meta.num("view_format", vd.Format); s.meta.num("view_dimension", vd.ViewDimension);
        UINT mip = 0, slice = 0;
        if (vd.ViewDimension == D3D11_SRV_DIMENSION_TEXTURE2D) mip = vd.Texture2D.MostDetailedMip;
        else if (vd.ViewDimension == D3D11_SRV_DIMENSION_TEXTURE2DARRAY) {
            mip = vd.Texture2DArray.MostDetailedMip; slice = vd.Texture2DArray.FirstArraySlice;
            s.meta.num("view_array_size", vd.Texture2DArray.ArraySize);
        } else {
            ComPtr<ID3D11Texture2D> tex;
            if (SUCCEEDED(resource.As(&tex))) {
                D3D11_TEXTURE2D_DESC d; tex->GetDesc(&d);
                s.meta.num("resource_width",d.Width); s.meta.num("resource_height",d.Height); s.meta.num("resource_format",d.Format);
                s.meta.num("array_size",d.ArraySize); s.meta.num("mip_levels",d.MipLevels); s.meta.num("sample_count",d.SampleDesc.Count);
            }
            s.meta.text("status", "unsupported_view_dimension"); return s;
        }
        return texture_resource(resource.Get(), std::move(s.meta), mip, slice);
    }
    Snapshot texture_resource(ID3D11Resource *resource, Json meta, UINT mip, UINT slice) {
        Snapshot s; s.meta = std::move(meta);
        if (!resource) { s.meta.text("status", "missing_binding"); return s; }
        ComPtr<ID3D11Texture2D> tex;
        if (FAILED(resource->QueryInterface(IID_PPV_ARGS(&tex)))) { s.meta.text("status", "unsupported_resource_dimension"); return s; }
        D3D11_TEXTURE2D_DESC d; tex->GetDesc(&d);
        s.meta.num("resource_width", d.Width); s.meta.num("resource_height", d.Height); s.meta.num("resource_format", d.Format);
        s.meta.num("mip_levels", d.MipLevels); s.meta.num("array_size", d.ArraySize); s.meta.num("sample_count", d.SampleDesc.Count);
        s.meta.num("sample_quality", d.SampleDesc.Quality); s.meta.num("bind_flags", d.BindFlags); s.meta.num("usage", d.Usage);
        if (d.SampleDesc.Count != 1 || mip >= d.MipLevels || slice >= d.ArraySize) { s.meta.text("status", "unsupported_msaa_or_subresource"); return s; }
        const uint32_t bpp = texel_bytes(d.Format);
        if (!bpp) { s.meta.text("status", "unsupported_format"); return s; }
        s.source = resource; s.width = std::max(1u, d.Width >> mip); s.height = std::max(1u, d.Height >> mip);
        s.row_bytes = s.width * bpp; s.bytes = uint64_t(s.row_bytes) * s.height;
        s.subresource = D3D11CalcSubresource(mip, slice, d.MipLevels);
        s.meta.num("subresource", s.subresource); s.meta.num("mip", mip); s.meta.num("array_slice", slice);
        s.meta.num("width", s.width); s.meta.num("height", s.height); s.meta.num("row_bytes", s.row_bytes);
        s.meta.text("selection", "one_selected_subresource; array views use first slice only"); s.meta.text("status", "planned"); return s;
    }
    void before_draw(ID3D11DeviceContext *ctx, const std::string &kind, UINT count, UINT instances) {
        if (internal || !enabled) return;
        ++draw; ++event;
        if (ctx->GetType() != D3D11_DEVICE_CONTEXT_IMMEDIATE) { if (recording) ++deferred_draws; return; }
        if (recording) {
            ComPtr<ID3D11PixelShader> ps; ctx->PSGetShader(&ps, nullptr, nullptr);
            auto identity = shaders.find(reinterpret_cast<uint64_t>(ps.Get()));
            if (identity != shaders.end() && !identity->second.first.empty() && !seen.count(identity->second.first))
                capture(ctx, identity->second, kind, count, instances);
        }
        // Pre-call evidence of intended writes; success/content/precise stencil coverage are not inferred.
        ID3D11RenderTargetView *rt[8] = {}; ComPtr<ID3D11DepthStencilView> depth;
        ctx->OMGetRenderTargets(8, rt, &depth);
        for (auto *v : rt) if (v) { ComPtr<ID3D11Resource> r; v->GetResource(&r); write(reinterpret_cast<uint64_t>(r.Get()), "draw_output_intent"); v->Release(); }
        if (depth) { ComPtr<ID3D11Resource> r; depth->GetResource(&r); write(reinterpret_cast<uint64_t>(r.Get()), "depth_draw_intent"); }
    }
    void capture(ID3D11DeviceContext *ctx, const std::pair<std::string,std::string> &identity, const std::string &kind, UINT count, UINT instances) {
        const auto start = Clock::now();
        Draw d; d.meta.num("draw", draw); d.meta.num("event_sequence", event); d.meta.num("frame", frame);
        d.meta.text("target", identity.first); d.meta.text("pixel_sha256", identity.second); d.meta.text("draw_kind", kind);
        d.meta.num("element_count", count); d.meta.num("instances", instances);
        ComPtr<ID3D11VertexShader> vs; ctx->VSGetShader(&vs, nullptr, nullptr);
        auto vid = shaders.find(reinterpret_cast<uint64_t>(vs.Get()));
        d.meta.text("vertex_sha256", vid == shaders.end() ? "unknown" : vid->second.second);
        UINT n = D3D11_VIEWPORT_AND_SCISSORRECT_OBJECT_COUNT_PER_PIPELINE;
        D3D11_VIEWPORT vp[D3D11_VIEWPORT_AND_SCISSORRECT_OBJECT_COUNT_PER_PIPELINE] = {}; ctx->RSGetViewports(&n, vp);
        std::vector<std::string> viewports;
        for (UINT i=0; i<n; ++i) viewports.push_back(array({number(vp[i].TopLeftX),number(vp[i].TopLeftY),number(vp[i].Width),number(vp[i].Height),number(vp[i].MinDepth),number(vp[i].MaxDepth)}));
        d.meta.fields["viewports"] = array(viewports); d.meta.text("viewport_source", "D3D11_RSGetViewports_at_pre_draw");
        ComPtr<ID3D11DeviceContext1> ctx1; ctx->QueryInterface(IID_PPV_ARGS(&ctx1));
        auto cb = [&](bool vertex, UINT slot) {
            ComPtr<ID3D11Buffer> b; UINT first=0, constants=4096;
            if (ctx1) { if (vertex) ctx1->VSGetConstantBuffers1(slot,1,&b,&first,&constants); else ctx1->PSGetConstantBuffers1(slot,1,&b,&first,&constants); }
            else { if (vertex) ctx->VSGetConstantBuffers(slot,1,&b); else ctx->PSGetConstantBuffers(slot,1,&b); }
            d.resources.push_back(buffer(b.Get(), (vertex ? "vs-b" : "ps-b") + number(slot), first, constants));
        };
        auto srv = [&](UINT slot, const std::string &semantic) {
            ComPtr<ID3D11ShaderResourceView> v; ctx->PSGetShaderResources(slot,1,&v);
            d.resources.push_back(texture(v.Get(), "ps-t" + number(slot), semantic));
        };
        if (identity.first == targets[0].migoto) {
            cb(false,0); cb(false,1); cb(false,2); cb(false,3);
            srv(10,"view_position_candidate"); srv(5,"normal_candidate");
            srv(3,"native_diffuse_candidate"); srv(4,"native_specular_candidate"); srv(0,"reflection_array_unknown_spatial_semantics");
        } else {
            cb(false,1); cb(false,2); cb(false,3); cb(false,4); cb(false,6); cb(true,0); cb(true,2);
            srv(2,"depth_candidate"); srv(4,"normal_candidate"); srv(0,"native_diffuse_candidate");
            srv(1,"native_specular_candidate"); srv(7,"reflection_array_unknown_spatial_semantics");
        }
        // Depth is an independent observation, never substituted for the shader's input depth.
        ComPtr<ID3D11DepthStencilView> depth; ctx->OMGetRenderTargets(0,nullptr,&depth);
        ComPtr<ID3D11Resource> dr; if (depth) depth->GetResource(&dr);
        Json dm = resource_meta(dr.Get(), "om-depth", "depth_attachment_unknown_correspondence");
        UINT mip=0, slice=0;
        bool depth_supported = true;
        if (depth) {
            D3D11_DEPTH_STENCIL_VIEW_DESC vd; depth->GetDesc(&vd); dm.num("view_format",vd.Format); dm.num("view_dimension",vd.ViewDimension);
            if (vd.ViewDimension == D3D11_DSV_DIMENSION_TEXTURE2D) mip=vd.Texture2D.MipSlice;
            else if (vd.ViewDimension == D3D11_DSV_DIMENSION_TEXTURE2DARRAY) { mip=vd.Texture2DArray.MipSlice; slice=vd.Texture2DArray.FirstArraySlice; dm.num("view_array_size",vd.Texture2DArray.ArraySize); }
            else depth_supported=false;
        }
        if (depth_supported) d.resources.push_back(texture_resource(dr.Get(),std::move(dm),mip,slice));
        else { Snapshot unsupported; unsupported.meta=std::move(dm); unsupported.meta.text("status","unsupported_depth_view"); d.resources.push_back(std::move(unsupported)); }
        uint64_t planned = 0;
        for (auto &s : d.resources) { planned += s.bytes; s.meta.num("selected_bytes",s.bytes); }
        seen.insert(identity.first);
        if (planned > budget - bytes) {
            status = "budget_exceeded"; d.meta.num("requested_raw_bytes",planned); draws.push_back(std::move(d));
            finish(); return;
        }
        bytes += planned; internal = true;
        try {
            ComPtr<ID3D11Device> device; ctx->GetDevice(&device);
            for (auto &s : d.resources) if (s.source) {
                if (s.buffer) {
                    D3D11_BUFFER_DESC bd = {}; bd.ByteWidth = s.row_bytes; bd.Usage = D3D11_USAGE_STAGING; bd.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
                    ComPtr<ID3D11Buffer> staging; check(device->CreateBuffer(&bd,nullptr,&staging)); s.staging = staging;
                    ctx->CopyResource(s.staging.Get(),s.source.Get());
                } else {
                    ComPtr<ID3D11Texture2D> tex; check(s.source.As(&tex)); D3D11_TEXTURE2D_DESC td; tex->GetDesc(&td);
                    td.Width=s.width; td.Height=s.height; td.MipLevels=td.ArraySize=1; td.Usage=D3D11_USAGE_STAGING;
                    td.BindFlags=td.MiscFlags=0; td.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
                    ComPtr<ID3D11Texture2D> staging; check(device->CreateTexture2D(&td,nullptr,&staging)); s.staging=staging;
                    ctx->CopySubresourceRegion(s.staging.Get(),0,0,0,0,s.source.Get(),s.subresource,nullptr);
                }
                s.source.Reset(); // frozen copy has independent lifetime; no stale source access during readback
            }
        } catch (...) { internal = false; copy_ms += milliseconds(start); status="copy_error"; draws.push_back(std::move(d)); finish(); throw; }
        internal = false; copy_ms += milliseconds(start); draws.push_back(std::move(d));
    }
};
}
