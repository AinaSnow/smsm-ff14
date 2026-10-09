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
struct Input { std::string kind, path; unsigned slot=0, width=0, height=0, stride=0,layers=1; };
int wmain(int argc, wchar_t** argv) try {
    if (argc != 2) throw std::runtime_error("Usage: render_ps.exe <UTF-8 job.txt>");
    std::ifstream job{fs::path(argv[1])}; if (!job) throw std::runtime_error("Cannot open job");
    unsigned width=0,height=0,targets=1,frames=1,draws=1; std::string shader,vertex,output,key,source_shader,blend="overwrite",format="rgba32f";
    float vx=0,vy=0,vw=0,vh=0; std::vector<Input> inputs;
    while (job >> key) {
        if (key == "size") job >> width >> height >> targets;
        else if (key == "shader") job >> std::quoted(shader);
        else if (key == "vertex") job >> std::quoted(vertex);
        else if(key=="source_shader")job>>std::quoted(source_shader);
        else if (key == "output") job >> std::quoted(output);
        else if (key == "viewport") job >> vx >> vy >> vw >> vh;
        else if (key == "frames") job >> frames;
        else if (key == "draws") job >> draws;
        else if (key == "blend") job >> blend;
        else if (key == "format") job >> format;
        else {
            Input item; item.kind=key;
            if (key == "texture") job >> item.slot >> item.width >> item.height >> std::quoted(item.path);
            else if(key=="array")job>>item.slot>>item.layers>>item.width>>item.height>>std::quoted(item.path);
            else if (key == "cube") { job >> item.slot >> item.width >> std::quoted(item.path); item.height=item.width; }
            else if (key == "structured") job >> item.slot >> item.stride >> std::quoted(item.path);
            else if (key == "constant" || key == "animation" || key == "region_copy") job >> item.slot >> std::quoted(item.path);
            else throw std::runtime_error("Unknown job field: " + key);
            inputs.push_back(item);
        }
        if (!job) throw std::runtime_error("Malformed job field: " + key);
    }
    if (!width || !height || width>4096 || height>4096 || targets<1 || targets>8 || !frames || frames>256 || shader.empty() || output.empty())
        throw std::runtime_error("Invalid dimensions, shader or output");
    if (!draws || draws>64 || (blend!="overwrite" && blend!="add" && blend!="source-alpha"))
        throw std::runtime_error("Invalid draw count or blend mode");
    if (format!="rgba32f" && format!="r11g11b10" && format!="rgba16f") throw std::runtime_error("Invalid target format");
    unsigned pixelBytes=format=="rgba32f"?16:(format=="rgba16f"?8:4);
    std::string extension=format=="rgba32f"?".f32":(format=="rgba16f"?".f16":".r11");
    if (!vw) { vw=float(width); vh=float(height); }
    if (vx<0 || vy<0 || vw<=0 || vh<=0 || vx+vw>width || vy+vh>height) throw std::runtime_error("Invalid viewport");
#ifdef SMSM_RESHADE_PIXEL_TEST
    if(frames!=3)throw std::runtime_error("ReShade pixel test requires exactly off/on/off frames");
    wchar_t executable[32768];GetModuleFileNameW(nullptr,executable,32768);
    const auto hostRoot=fs::path(executable).parent_path();
    auto library=LoadLibraryW((hostRoot/L"d3d11.dll").c_str());
    if(!library)throw std::runtime_error("ReShade runtime missing");
    auto create=reinterpret_cast<decltype(&D3D11CreateDeviceAndSwapChain)>(GetProcAddress(library,"D3D11CreateDeviceAndSwapChain"));
    WNDCLASSW wc{};wc.lpfnWndProc=DefWindowProcW;wc.hInstance=GetModuleHandleW(nullptr);wc.lpszClassName=L"SMSMActualPixelHost";
    RegisterClassW(&wc);
    auto window=CreateWindowW(wc.lpszClassName,L"SMSM hidden pixel test",WS_POPUP,0,0,width,height,nullptr,nullptr,wc.hInstance,nullptr);
    if(!window || !create)throw std::runtime_error("Cannot initialize hidden hardware host");
    DXGI_SWAP_CHAIN_DESC swapDesc{};swapDesc.BufferDesc.Width=width;swapDesc.BufferDesc.Height=height;
    swapDesc.BufferDesc.Format=DXGI_FORMAT_R8G8B8A8_UNORM;swapDesc.SampleDesc.Count=1;
    swapDesc.BufferUsage=DXGI_USAGE_RENDER_TARGET_OUTPUT;swapDesc.BufferCount=2;swapDesc.OutputWindow=window;swapDesc.Windowed=TRUE;
    ComPtr<ID3D11Device> device;ComPtr<ID3D11DeviceContext> context;ComPtr<IDXGISwapChain> swap;D3D_FEATURE_LEVEL level;
    check(create(nullptr,D3D_DRIVER_TYPE_HARDWARE,nullptr,0,nullptr,0,D3D11_SDK_VERSION,&swapDesc,&swap,&device,&level,&context),"ReShade hardware device");
    fs::create_directories(hostRoot/"SMSM-native-captures");
    auto send=[&](const char *command){
        {std::ofstream f(hostRoot/"SMSM-native-captures"/"ambient-command.txt");f<<command<<'\n';}
        check(swap->Present(0,0),"command Present");
        if(fs::exists(hostRoot/"SMSM-native-captures"/"ambient-command.txt"))throw std::runtime_error("Command not consumed by addon");
    };
#else
    wchar_t system[MAX_PATH]; GetSystemDirectoryW(system, MAX_PATH);
    auto library = LoadLibraryExW((fs::path(system)/L"d3d11.dll").c_str(), nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!library) throw std::runtime_error("Cannot load system D3D11");
    auto create = reinterpret_cast<decltype(&D3D11CreateDevice)>(GetProcAddress(library, "D3D11CreateDevice"));
    if (!create) throw std::runtime_error("Missing D3D11CreateDevice");
    ComPtr<ID3D11Device> device; ComPtr<ID3D11DeviceContext> context; D3D_FEATURE_LEVEL level;
    check(create(nullptr, D3D_DRIVER_TYPE_WARP, nullptr, 0, nullptr, 0, D3D11_SDK_VERSION, &device, &level, &context), "WARP device");
#endif
    auto psBytes=read(shader); ComPtr<ID3D11PixelShader> ps;
    check(device->CreatePixelShader(psBytes.data(), psBytes.size(), nullptr, &ps), "pixel shader");
#ifdef SMSM_VISIBLE_AMBIENT
    auto sourceBytes=read(source_shader);ComPtr<ID3D11PixelShader> sourcePs;
    check(device->CreatePixelShader(sourceBytes.data(),sourceBytes.size(),nullptr,&sourcePs),"original region source shader");
#endif
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
    // Explicit synthetic states, NOT a claim about the game's OM state. Apply
    // identical blending to all MRTs; alpha always takes the latest source.
    D3D11_BLEND_DESC bd{}; auto& rt=bd.RenderTarget[0];
    rt.RenderTargetWriteMask=D3D11_COLOR_WRITE_ENABLE_ALL;
#ifdef SMSM_WRITE_MASK_ZERO
    rt.RenderTargetWriteMask=0;
#endif
    rt.BlendEnable=blend!="overwrite";
    rt.SrcBlend=blend=="source-alpha" ? D3D11_BLEND_SRC_ALPHA : D3D11_BLEND_ONE;
    rt.DestBlend=blend=="source-alpha" ? D3D11_BLEND_INV_SRC_ALPHA : D3D11_BLEND_ONE;
    rt.BlendOp=rt.BlendOpAlpha=D3D11_BLEND_OP_ADD;
    rt.SrcBlendAlpha=D3D11_BLEND_ONE; rt.DestBlendAlpha=D3D11_BLEND_ZERO;
    ComPtr<ID3D11BlendState> blendState; check(device->CreateBlendState(&bd,&blendState),"blend state");
    context->OMSetBlendState(blendState.Get(),nullptr,0xffffffff);
    D3D11_SAMPLER_DESC sd{}; sd.Filter=D3D11_FILTER_MIN_MAG_MIP_POINT; sd.AddressU=sd.AddressV=sd.AddressW=D3D11_TEXTURE_ADDRESS_CLAMP;
    sd.MaxLOD=D3D11_FLOAT32_MAX; sd.ComparisonFunc=D3D11_COMPARISON_NEVER;
    ComPtr<ID3D11SamplerState> sampler; check(device->CreateSamplerState(&sd,&sampler),"sampler");
    ID3D11SamplerState* samplers[16]; for (auto& s:samplers) s=sampler.Get(); context->PSSetSamplers(0,16,samplers);
    std::vector<ComPtr<ID3D11Resource>> resources; std::vector<ComPtr<ID3D11ShaderResourceView>> views;
    std::vector<ComPtr<ID3D11Buffer>> buffers; ComPtr<ID3D11Buffer> animation; std::vector<char> animationBytes; unsigned animationStride=0;
    ComPtr<ID3D11Buffer> regionSource,regionDestination;std::vector<char> regionBytes;unsigned regionStride=0;
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
        if (input.kind=="texture" || input.kind=="cube" || input.kind=="array") {
            unsigned faces=input.kind=="cube"?6:input.kind=="array"?input.layers:1;
            if(!faces || faces>64)throw std::runtime_error("Invalid array layer count");
            if (!input.width || !input.height || input.width>4096 || input.height>4096 || bytes.size()!=size_t(input.width)*input.height*16*faces) throw std::runtime_error("Invalid RGBA32F texture size");
            D3D11_TEXTURE2D_DESC td{}; td.Width=input.width; td.Height=input.height; td.MipLevels=1; td.ArraySize=faces; td.Format=DXGI_FORMAT_R32G32B32A32_FLOAT;
            td.SampleDesc.Count=1; td.Usage=D3D11_USAGE_IMMUTABLE; td.BindFlags=D3D11_BIND_SHADER_RESOURCE;
            if (input.kind=="cube") td.MiscFlags=D3D11_RESOURCE_MISC_TEXTURECUBE;
            D3D11_SUBRESOURCE_DATA data[64]{};
            for (unsigned face=0;face<faces;++face) { data[face].pSysMem=bytes.data()+size_t(face)*input.width*input.height*16; data[face].SysMemPitch=input.width*16; }
            ComPtr<ID3D11Texture2D> tex; check(device->CreateTexture2D(&td,data,&tex),"input texture");
            D3D11_SHADER_RESOURCE_VIEW_DESC sv{}; sv.Format=td.Format; sv.ViewDimension=D3D11_SRV_DIMENSION_TEXTURECUBEARRAY;
            sv.TextureCubeArray.MipLevels=1; sv.TextureCubeArray.NumCubes=1;
            if(input.kind=="array"){sv={};sv.Format=td.Format;sv.ViewDimension=D3D11_SRV_DIMENSION_TEXTURE2DARRAY;sv.Texture2DArray.MipLevels=1;sv.Texture2DArray.ArraySize=faces;}
            check(device->CreateShaderResourceView(tex.Get(),input.kind!="texture"?&sv:nullptr,&view),"texture SRV"); resources.push_back(tex);
        } else if (input.kind=="region_copy") {
            if(regionSource || bytes.size()%frames) throw std::runtime_error("Invalid region copy frames");
            size_t size=bytes.size()/frames;
            if(!size || size%16 || size>65536) throw std::runtime_error("Invalid native constant buffer size");
            D3D11_BUFFER_DESC bd{};bd.ByteWidth=UINT(size);bd.Usage=D3D11_USAGE_DEFAULT;bd.BindFlags=D3D11_BIND_CONSTANT_BUFFER;
            check(device->CreateBuffer(&bd,nullptr,&regionSource),"native region source CB");
            bd.BindFlags=D3D11_BIND_SHADER_RESOURCE;bd.MiscFlags=D3D11_RESOURCE_MISC_BUFFER_STRUCTURED;bd.StructureByteStride=16;
            check(device->CreateBuffer(&bd,nullptr,&regionDestination),"owned region buffer");
            D3D11_SHADER_RESOURCE_VIEW_DESC sv{};sv.Format=DXGI_FORMAT_UNKNOWN;sv.ViewDimension=D3D11_SRV_DIMENSION_BUFFER;sv.Buffer.NumElements=UINT(size/16);
            check(device->CreateShaderResourceView(regionDestination.Get(),&sv,&view),"owned region SRV");
            regionBytes=std::move(bytes);regionStride=UINT(size);
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
        D3D11_TEXTURE2D_DESC td{}; td.Width=width; td.Height=height; td.MipLevels=td.ArraySize=1;
        td.Format=format=="rgba32f"?DXGI_FORMAT_R32G32B32A32_FLOAT:(format=="rgba16f"?DXGI_FORMAT_R16G16B16A16_FLOAT:DXGI_FORMAT_R11G11B10_FLOAT); td.SampleDesc.Count=1;
        td.Usage=D3D11_USAGE_DEFAULT; td.BindFlags=D3D11_BIND_RENDER_TARGET;
        ComPtr<ID3D11Texture2D> tex,stage; ComPtr<ID3D11RenderTargetView> rtv;
        check(device->CreateTexture2D(&td,nullptr,&tex),"render target"); check(device->CreateRenderTargetView(tex.Get(),nullptr,&rtv),"RTV");
        td.Usage=D3D11_USAGE_STAGING; td.BindFlags=0; td.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
        check(device->CreateTexture2D(&td,nullptr,&stage),"readback texture"); rawRT[i]=rtv.Get(); renderTargets.push_back(tex); staging.push_back(stage); rtvs.push_back(rtv);
    }
    context->OMSetRenderTargets(targets,rawRT,nullptr);
#ifdef SMSM_PREDICATED
    ComPtr<ID3D11Predicate> testPredicate;D3D11_QUERY_DESC pd{D3D11_QUERY_OCCLUSION_PREDICATE,0};
    check(device->CreatePredicate(&pd,&testPredicate),"test predicate");
    context->Begin(testPredicate.Get());context->End(testPredicate.Get());context->Flush();
    BOOL predicateResult=TRUE;HRESULT predHr=S_FALSE;
    for(unsigned poll=0;poll<1000 && predHr==S_FALSE;++poll){predHr=context->GetData(testPredicate.Get(),&predicateResult,sizeof(predicateResult),0);if(predHr==S_FALSE)Sleep(1);}
    if(predHr!=S_OK || predicateResult)throw std::runtime_error("Expected completed false occlusion predicate");
#endif
    for (unsigned frame=0;frame<frames;++frame) {
#ifdef SMSM_RESHADE_PIXEL_TEST
#ifdef SMSM_VISIBLE_AMBIENT
        send(frame==1?"half":"off");
#elif defined(SMSM_MATERIAL_CENSUS)
        send(frame==1?"census":"off");
#elif defined(SMSM_MATERIAL_SAMPLE)
        send(frame==1?"sample 980154264a89fba1 0":"off");
#elif defined(SMSM_MATERIAL_PROBE)
        send(frame==1?"probe 980154264a89fba1 3 " SMSM_PROBE_VERTEX_SHA:"off");
#elif defined(SMSM_MATERIAL_SKIP)
        send(frame==1?"sample 980154264a89fba1 1":"off");
#else
#ifdef SMSM_RESHADE_OUTPUT_TEST
        send(frame==1?"audit":"off");
#else
        send(frame==1?"coverage":"off");
#endif
#endif
#endif
        if (animation) context->UpdateSubresource(animation.Get(),0,nullptr,animationBytes.data()+size_t(frame)*animationStride,0,0);
        if (regionSource) {
            context->UpdateSubresource(regionSource.Get(),0,nullptr,regionBytes.data()+size_t(frame)*regionStride,0,0);
            context->CopyResource(regionDestination.Get(),regionSource.Get());
        }
#ifdef SMSM_VISIBLE_AMBIENT
        if(frame==1){
            if(!regionSource)throw std::runtime_error("Missing synthetic native region source");
            ComPtr<ID3D11Buffer> common,pbr,camera;
            context->PSGetConstantBuffers(1,1,&common);context->PSGetConstantBuffers(2,1,&pbr);context->PSGetConstantBuffers(3,1,&camera);
            auto *p=camera.Get();context->PSSetConstantBuffers(1,1,&p);p=regionSource.Get();context->PSSetConstantBuffers(2,1,&p);
            context->PSSetShader(sourcePs.Get(),nullptr,0);context->Draw(0,0);
            p=common.Get();context->PSSetConstantBuffers(1,1,&p);p=pbr.Get();context->PSSetConstantBuffers(2,1,&p);
            context->PSSetShader(ps.Get(),nullptr,0);
        }
#endif
        float clear[4]={0,0,0,0}; for (auto& rtv:rtvs) context->ClearRenderTargetView(rtv.Get(),clear);
#ifdef SMSM_PREDICATED
        if(frame==1)context->SetPredication(testPredicate.Get(),FALSE);
#endif
        for (unsigned draw=0;draw<draws;++draw) context->Draw(3,0);
#ifdef SMSM_PREDICATED
        if(frame==1){
            ComPtr<ID3D11Predicate> restored;BOOL value;context->GetPredication(&restored,&value);
            if(restored.Get()!=testPredicate.Get() || value)throw std::runtime_error("Audit failed to restore predication");
            context->SetPredication(nullptr,FALSE);
        }
#endif
        for (unsigned i=0;i<targets;++i) {
            context->CopyResource(staging[i].Get(),renderTargets[i].Get()); D3D11_MAPPED_SUBRESOURCE mapped{};
            check(context->Map(staging[i].Get(),0,D3D11_MAP_READ,0,&mapped),"readback Map");
            auto path=fs::u8path(output+"-f"+std::to_string(frame)+"-rt"+std::to_string(i)+extension);
            if (fs::exists(path)) { context->Unmap(staging[i].Get(),0); throw std::runtime_error("Refusing to overwrite readback"); }
            std::ofstream out(path,std::ios::binary);
            for (unsigned y=0;y<height;++y) out.write(static_cast<char*>(mapped.pData)+size_t(y)*mapped.RowPitch,size_t(width)*pixelBytes);
            context->Unmap(staging[i].Get(),0); if (!out) throw std::runtime_error("Readback write failed");
        }
#ifdef SMSM_RESHADE_PIXEL_TEST
#ifdef SMSM_LATER_CLEAR
        if(frame==1){float later[4]={.125f,.125f,.125f,1};for(auto &rtv:rtvs)context->ClearRenderTargetView(rtv.Get(),later);}
#endif
        send("status");
#ifdef SMSM_RESHADE_OUTPUT_TEST
        if(frame==1)for(unsigned poll=0;poll<10;++poll){Sleep(5);send("status");}
#endif
        fs::copy_file(hostRoot/"SMSM-native-captures"/"ambient-status.json",hostRoot/("frame-"+std::to_string(frame)+"-status.json"));
#endif
    }
#ifdef SMSM_RESHADE_PIXEL_TEST
    check(device->GetDeviceRemovedReason(),"hardware device status");DestroyWindow(window);
    std::cout<<"Actual ReShade hardware Draw/CopyResource/Map complete: off/coverage/off, three vertices per frame\n";
#else
    std::cout << "WARP Draw/CopyResource/Map complete: " << frames << " frames, " << draws << " draws/frame, blend=" << blend << ", " << targets << " MRTs, " << width << "x" << height << "\n";
#endif
    return 0;
} catch (const std::exception& e) { std::cerr << e.what() << "\n"; return 1; }
