// Headless D3D11 WARP draw/readback harness. Never load the game's proxy DLL.
#include <windows.h>
#include <d3d11.h>
#include <d3dcompiler.h>
#include <wrl/client.h>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <vector>
#include <stdexcept>
#include <cstring>
using Microsoft::WRL::ComPtr;
namespace fs = std::filesystem;
void check(HRESULT hr, const char* what) {
    if (FAILED(hr)) { std::ostringstream s; s << what << " HRESULT=0x" << std::hex << hr; throw std::runtime_error(s.str()); }
}
std::vector<char> read(const std::string& path) {
    std::ifstream f(fs::u8path(path), std::ios::binary | std::ios::ate);
    if (!f) throw std::runtime_error("Cannot read " + path);
    auto n = f.tellg(); if (n <= 0) throw std::runtime_error("Empty input " + path);
    std::vector<char> bytes(static_cast<size_t>(n)); f.seekg(0); f.read(bytes.data(), bytes.size());
    if (!f) throw std::runtime_error("Short read " + path); return bytes;
}
struct Input { std::string kind, path; unsigned slot=0, width=0, height=0, stride=0; };
int wmain(int argc, wchar_t** argv) try {
    if (argc != 2) throw std::runtime_error("Usage: render_ps.exe <UTF-8 job.txt>");
    std::ifstream job{fs::path(argv[1])}; if (!job) throw std::runtime_error("Cannot open job");
    unsigned width=0,height=0,targets=1,frames=1; std::string shader,vertex,output,key;
    float vx=0,vy=0,vw=0,vh=0; std::vector<Input> inputs;
    while (job >> key) {
        if (key == "size") job >> width >> height >> targets;
        else if (key == "shader") job >> std::quoted(shader);
        else if (key == "vertex") job >> std::quoted(vertex);
        else if (key == "output") job >> std::quoted(output);
        else if (key == "viewport") job >> vx >> vy >> vw >> vh;
        else if (key == "frames") job >> frames;
        else {
            Input item; item.kind=key;
            if (key == "texture") job >> item.slot >> item.width >> item.height >> std::quoted(item.path);
            else if (key == "structured") job >> item.slot >> item.stride >> std::quoted(item.path);
            else if (key == "constant" || key == "animation") job >> item.slot >> std::quoted(item.path);
            else throw std::runtime_error("Unknown job field: " + key);
            inputs.push_back(item);
        }
        if (!job) throw std::runtime_error("Malformed job field: " + key);
    }
    if (!width || !height || width>4096 || height>4096 || targets<1 || targets>8 || !frames || frames>256 || shader.empty() || output.empty())
        throw std::runtime_error("Invalid dimensions, shader or output");
    if (!vw) { vw=float(width); vh=float(height); }
    if (vx<0 || vy<0 || vw<=0 || vh<=0 || vx+vw>width || vy+vh>height) throw std::runtime_error("Invalid viewport");
    wchar_t system[MAX_PATH]; GetSystemDirectoryW(system, MAX_PATH);
    auto library = LoadLibraryExW((fs::path(system)/L"d3d11.dll").c_str(), nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!library) throw std::runtime_error("Cannot load system D3D11");
    auto create = reinterpret_cast<decltype(&D3D11CreateDevice)>(GetProcAddress(library, "D3D11CreateDevice"));
    if (!create) throw std::runtime_error("Missing D3D11CreateDevice");
    ComPtr<ID3D11Device> device; ComPtr<ID3D11DeviceContext> context; D3D_FEATURE_LEVEL level;
    check(create(nullptr, D3D_DRIVER_TYPE_WARP, nullptr, 0, nullptr, 0, D3D11_SDK_VERSION, &device, &level, &context), "WARP device");
    auto psBytes=read(shader); ComPtr<ID3D11PixelShader> ps;
    check(device->CreatePixelShader(psBytes.data(), psBytes.size(), nullptr, &ps), "pixel shader");
    ComPtr<ID3DBlob> vsCode, errors; std::vector<char> vsBytes;
    if (vertex.empty()) {
        const char* source="struct O{float4 p:SV_POSITION;float2 uv:TEXCOORD0;}; O main(uint id:SV_VertexID){O o;float2 uv=float2((id<<1)&2,id&2);o.uv=uv;o.p=float4(uv*float2(2,-2)+float2(-1,1),0,1);return o;}";
        HRESULT hr=D3DCompile(source,strlen(source),"fullscreen",nullptr,nullptr,"main","vs_5_0",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&vsCode,&errors);
        if (FAILED(hr) && errors) std::cerr << static_cast<char*>(errors->GetBufferPointer());
        check(hr,"vertex compilation");
    } else vsBytes=read(vertex);
    ComPtr<ID3D11VertexShader> vs;
    check(device->CreateVertexShader(vertex.empty()?vsCode->GetBufferPointer():vsBytes.data(), vertex.empty()?vsCode->GetBufferSize():vsBytes.size(), nullptr, &vs), "vertex shader");
    context->VSSetShader(vs.Get(),nullptr,0); context->PSSetShader(ps.Get(),nullptr,0);
    context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    D3D11_RASTERIZER_DESC rd{}; rd.FillMode=D3D11_FILL_SOLID; rd.CullMode=D3D11_CULL_NONE; rd.DepthClipEnable=TRUE;
    ComPtr<ID3D11RasterizerState> raster; check(device->CreateRasterizerState(&rd,&raster),"raster state"); context->RSSetState(raster.Get());
    D3D11_VIEWPORT viewport{vx,vy,vw,vh,0,1}; context->RSSetViewports(1,&viewport);
    D3D11_DEPTH_STENCIL_DESC dd{}; dd.DepthEnable=FALSE; dd.DepthFunc=D3D11_COMPARISON_ALWAYS;
    ComPtr<ID3D11DepthStencilState> depthState; check(device->CreateDepthStencilState(&dd,&depthState),"depth state"); context->OMSetDepthStencilState(depthState.Get(),0);
    D3D11_SAMPLER_DESC sd{}; sd.Filter=D3D11_FILTER_MIN_MAG_MIP_POINT; sd.AddressU=sd.AddressV=sd.AddressW=D3D11_TEXTURE_ADDRESS_CLAMP;
    sd.MaxLOD=D3D11_FLOAT32_MAX; sd.ComparisonFunc=D3D11_COMPARISON_NEVER;
    ComPtr<ID3D11SamplerState> sampler; check(device->CreateSamplerState(&sd,&sampler),"sampler");
    ID3D11SamplerState* samplers[16]; for (auto& s:samplers) s=sampler.Get(); context->PSSetSamplers(0,16,samplers);
    std::vector<ComPtr<ID3D11Resource>> resources; std::vector<ComPtr<ID3D11ShaderResourceView>> views;
    std::vector<ComPtr<ID3D11Buffer>> buffers; ComPtr<ID3D11Buffer> animation; std::vector<char> animationBytes; unsigned animationStride=0;
    for (const auto& input:inputs) {
        auto bytes=read(input.path);
        if (input.kind=="constant" || input.kind=="animation") {
            if (input.slot>=14) throw std::runtime_error("Invalid constant slot");
            size_t size=bytes.size(); if (input.kind=="animation") { if (animation || size%frames) throw std::runtime_error("Invalid animation"); size/=frames; }
            if (!size || size%16 || size>65536) throw std::runtime_error("Invalid constant buffer size");
            D3D11_BUFFER_DESC bd{}; bd.ByteWidth=UINT(size); bd.Usage=D3D11_USAGE_DEFAULT; bd.BindFlags=D3D11_BIND_CONSTANT_BUFFER;
            D3D11_SUBRESOURCE_DATA data{bytes.data(),0,0}; ComPtr<ID3D11Buffer> b;
            check(device->CreateBuffer(&bd,&data,&b),"constant buffer"); ID3D11Buffer* ptr=b.Get(); context->PSSetConstantBuffers(input.slot,1,&ptr);
            if (input.kind=="animation") { animation=b; animationBytes=std::move(bytes); animationStride=UINT(size); }
            buffers.push_back(b); continue;
        }
        if (input.slot>=128) throw std::runtime_error("Invalid SRV slot");
        ComPtr<ID3D11ShaderResourceView> view;
        if (input.kind=="texture") {
            if (!input.width || !input.height || input.width>4096 || input.height>4096 || bytes.size()!=size_t(input.width)*input.height*16) throw std::runtime_error("Invalid RGBA32F texture size");
            D3D11_TEXTURE2D_DESC td{}; td.Width=input.width; td.Height=input.height; td.MipLevels=td.ArraySize=1; td.Format=DXGI_FORMAT_R32G32B32A32_FLOAT;
            td.SampleDesc.Count=1; td.Usage=D3D11_USAGE_IMMUTABLE; td.BindFlags=D3D11_BIND_SHADER_RESOURCE;
            D3D11_SUBRESOURCE_DATA data{bytes.data(),input.width*16,0}; ComPtr<ID3D11Texture2D> tex;
            check(device->CreateTexture2D(&td,&data,&tex),"input texture"); check(device->CreateShaderResourceView(tex.Get(),nullptr,&view),"texture SRV"); resources.push_back(tex);
        } else {
            if (!input.stride || bytes.size()%input.stride || bytes.size()>16*1024*1024) throw std::runtime_error("Invalid structured buffer");
            D3D11_BUFFER_DESC bd{}; bd.ByteWidth=UINT(bytes.size()); bd.Usage=D3D11_USAGE_IMMUTABLE; bd.BindFlags=D3D11_BIND_SHADER_RESOURCE; bd.MiscFlags=D3D11_RESOURCE_MISC_BUFFER_STRUCTURED; bd.StructureByteStride=input.stride;
            D3D11_SUBRESOURCE_DATA data{bytes.data(),0,0}; ComPtr<ID3D11Buffer> buffer; check(device->CreateBuffer(&bd,&data,&buffer),"structured buffer");
            D3D11_SHADER_RESOURCE_VIEW_DESC sv{}; sv.Format=DXGI_FORMAT_UNKNOWN; sv.ViewDimension=D3D11_SRV_DIMENSION_BUFFER; sv.Buffer.NumElements=UINT(bytes.size()/input.stride);
            check(device->CreateShaderResourceView(buffer.Get(),&sv,&view),"buffer SRV"); resources.push_back(buffer);
        }
        ID3D11ShaderResourceView* ptr=view.Get(); context->PSSetShaderResources(input.slot,1,&ptr); views.push_back(view);
    }
    std::vector<ComPtr<ID3D11Texture2D>> renderTargets,staging; std::vector<ComPtr<ID3D11RenderTargetView>> rtvs; ID3D11RenderTargetView* rawRT[8]{};
    for (unsigned i=0;i<targets;++i) {
        D3D11_TEXTURE2D_DESC td{}; td.Width=width; td.Height=height; td.MipLevels=td.ArraySize=1; td.Format=DXGI_FORMAT_R32G32B32A32_FLOAT; td.SampleDesc.Count=1;
        td.Usage=D3D11_USAGE_DEFAULT; td.BindFlags=D3D11_BIND_RENDER_TARGET;
        ComPtr<ID3D11Texture2D> tex,stage; ComPtr<ID3D11RenderTargetView> rtv;
        check(device->CreateTexture2D(&td,nullptr,&tex),"render target"); check(device->CreateRenderTargetView(tex.Get(),nullptr,&rtv),"RTV");
        td.Usage=D3D11_USAGE_STAGING; td.BindFlags=0; td.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
        check(device->CreateTexture2D(&td,nullptr,&stage),"readback texture"); rawRT[i]=rtv.Get(); renderTargets.push_back(tex); staging.push_back(stage); rtvs.push_back(rtv);
    }
    context->OMSetRenderTargets(targets,rawRT,nullptr);
    for (unsigned frame=0;frame<frames;++frame) {
        if (animation) context->UpdateSubresource(animation.Get(),0,nullptr,animationBytes.data()+size_t(frame)*animationStride,0,0);
        float clear[4]={0,0,0,0}; for (auto& rtv:rtvs) context->ClearRenderTargetView(rtv.Get(),clear);
        context->Draw(3,0);
        for (unsigned i=0;i<targets;++i) {
            context->CopyResource(staging[i].Get(),renderTargets[i].Get()); D3D11_MAPPED_SUBRESOURCE mapped{};
            check(context->Map(staging[i].Get(),0,D3D11_MAP_READ,0,&mapped),"readback Map");
            auto path=fs::u8path(output+"-f"+std::to_string(frame)+"-rt"+std::to_string(i)+".f32");
            if (fs::exists(path)) { context->Unmap(staging[i].Get(),0); throw std::runtime_error("Refusing to overwrite readback"); }
            std::ofstream out(path,std::ios::binary);
            for (unsigned y=0;y<height;++y) out.write(static_cast<char*>(mapped.pData)+size_t(y)*mapped.RowPitch,size_t(width)*16);
            context->Unmap(staging[i].Get(),0); if (!out) throw std::runtime_error("Readback write failed");
        }
    }
    std::cout << "WARP Draw/CopyResource/Map complete: " << frames << " frames, " << targets << " MRTs, " << width << "x" << height << "\n";
    return 0;
} catch (const std::exception& e) { std::cerr << e.what() << "\n"; return 1; }
