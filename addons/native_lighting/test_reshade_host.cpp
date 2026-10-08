// Isolated hidden-window host: actual ReShade runtime, original game PS bytecode,
// synthetic resources. No game injection, no shader replacement and no visual claim.
#include "diagnostic.hpp"
#include <d3dcompiler.h>
#include <dxgi.h>
#include <iostream>

using namespace smsm;
std::vector<char> read(const fs::path &path) {
    std::ifstream in(path,std::ios::binary);if(!in)throw std::runtime_error("missing input file");
    return {std::istreambuf_iterator<char>(in),std::istreambuf_iterator<char>()};
}
void command(const fs::path &root,const char *text) {
    std::ofstream out(root/"SMSM-native-command.txt");out<<text<<'\n';
}
int wmain(int argc,wchar_t **argv) {
    try {
        if(argc!=3 && argc!=4)throw std::runtime_error("host directory and extraction directory required");
        fs::path root=fs::absolute(argv[1]),extraction=fs::absolute(argv[2]);
        WNDCLASSW wc={};wc.lpfnWndProc=DefWindowProcW;wc.hInstance=GetModuleHandleW(nullptr);wc.lpszClassName=L"SMSMHiddenDiagnosticTest";
        RegisterClassW(&wc);
        HWND window=CreateWindowW(wc.lpszClassName,L"SMSM isolated WARP verification",WS_POPUP,0,0,64,32,nullptr,nullptr,wc.hInstance,nullptr);
        if(!window)throw std::runtime_error("hidden window creation failed");
        auto runtime=LoadLibraryW((root/L"d3d11.dll").c_str());
        if(!runtime)throw std::runtime_error("ReShade proxy load failed");
        using Create = decltype(&D3D11CreateDeviceAndSwapChain);
        auto create=reinterpret_cast<Create>(GetProcAddress(runtime,"D3D11CreateDeviceAndSwapChain"));
        if(!create)throw std::runtime_error("ReShade export missing");
        DXGI_SWAP_CHAIN_DESC sd={};sd.BufferDesc.Width=64;sd.BufferDesc.Height=32;sd.BufferDesc.Format=DXGI_FORMAT_R8G8B8A8_UNORM;
        sd.SampleDesc.Count=1;sd.BufferUsage=DXGI_USAGE_RENDER_TARGET_OUTPUT;sd.BufferCount=2;sd.OutputWindow=window;sd.Windowed=TRUE;
        sd.SwapEffect=DXGI_SWAP_EFFECT_DISCARD;
        ComPtr<ID3D11Device> device;ComPtr<ID3D11DeviceContext> ctx;ComPtr<IDXGISwapChain> swap;
        // Official ReShade deliberately skips WARP. Test callback wiring on hardware,
        // with zero vertices to avoid executing game PS against synthetic bindings.
        check(create(nullptr,D3D_DRIVER_TYPE_HARDWARE,nullptr,0,nullptr,0,D3D11_SDK_VERSION,&sd,&swap,&device,nullptr,&ctx));
        ComPtr<ID3D11Texture2D> back;check(swap->GetBuffer(0,IID_PPV_ARGS(&back)));
        ComPtr<ID3D11RenderTargetView> rtv;check(device->CreateRenderTargetView(back.Get(),nullptr,&rtv));
        ComPtr<ID3D11PixelShader> ps[2];
        for(int i=0;i<2;++i){auto code=read(extraction/L"dxbc"/(game_targets[i].migoto+"-ps.bin"));check(device->CreatePixelShader(code.data(),code.size(),nullptr,&ps[i]));}
        const char *vs="float4 main(uint id:SV_VertexID):SV_Position{float2 p=float2((id<<1)&2,id&2);return float4(p*float2(2,-2)+float2(-1,1),0,1);}";
        ComPtr<ID3DBlob> code,errors;check(D3DCompile(vs,strlen(vs),nullptr,nullptr,nullptr,"main","vs_5_0",0,0,&code,&errors));
        ComPtr<ID3D11VertexShader> vertex;check(device->CreateVertexShader(code->GetBufferPointer(),code->GetBufferSize(),nullptr,&vertex));
        D3D11_BUFFER_DESC bd={};bd.ByteWidth=4096;bd.BindFlags=D3D11_BIND_CONSTANT_BUFFER;
        std::vector<float> constants(1024);for(size_t i=0;i<constants.size();++i)constants[i]=float(i)/128;
        D3D11_SUBRESOURCE_DATA bi={constants.data(),0,0};ComPtr<ID3D11Buffer> cb;check(device->CreateBuffer(&bd,&bi,&cb));
        D3D11_TEXTURE2D_DESC td={};td.Width=64;td.Height=32;td.MipLevels=td.ArraySize=1;td.Format=DXGI_FORMAT_R32G32B32A32_FLOAT;
        td.SampleDesc.Count=1;td.BindFlags=D3D11_BIND_SHADER_RESOURCE|D3D11_BIND_RENDER_TARGET;
        std::vector<float> pixels(64*32*4,0.25f);D3D11_SUBRESOURCE_DATA ti={pixels.data(),64*16,0};
        ComPtr<ID3D11Texture2D> tex;ComPtr<ID3D11ShaderResourceView> srv;check(device->CreateTexture2D(&td,&ti,&tex));check(device->CreateShaderResourceView(tex.Get(),nullptr,&srv));
        ComPtr<ID3D11Texture2D> depth_source,depth_copy;ComPtr<ID3D11ShaderResourceView> depth_view;ComPtr<ID3D11RenderTargetView> producer_target;
        check(device->CreateTexture2D(&td,&ti,&depth_source));check(device->CreateTexture2D(&td,nullptr,&depth_copy));
        check(device->CreateShaderResourceView(depth_copy.Get(),nullptr,&depth_view));check(device->CreateRenderTargetView(tex.Get(),nullptr,&producer_target));
        auto producer_code=read(extraction/L"dxbc"/"edf9243383ddcd52-ps.bin");ComPtr<ID3D11PixelShader> producer_ps;
        check(device->CreatePixelShader(producer_code.data(),producer_code.size(),nullptr,&producer_ps));
        D3D11_SAMPLER_DESC sampler_desc={};sampler_desc.Filter=D3D11_FILTER_MIN_MAG_MIP_POINT;
        sampler_desc.AddressU=sampler_desc.AddressV=sampler_desc.AddressW=D3D11_TEXTURE_ADDRESS_CLAMP;sampler_desc.MaxLOD=D3D11_FLOAT32_MAX;
        ComPtr<ID3D11SamplerState> sampler;check(device->CreateSamplerState(&sampler_desc,&sampler));
        auto produce=[&](){
            ctx->CopyResource(depth_copy.Get(),depth_source.Get());
            auto *r=producer_target.Get();ctx->OMSetRenderTargets(1,&r,nullptr);
            D3D11_VIEWPORT vp={3,2,57,27,0.1f,0.9f};ctx->RSSetViewports(1,&vp);
            ctx->PSSetShader(producer_ps.Get(),nullptr,0);auto *v=depth_view.Get();ctx->PSSetShaderResources(0,1,&v);
            auto *s=sampler.Get();ctx->PSSetSamplers(0,1,&s);ctx->Draw(0,1);
        };
        auto render=[&](int shader){
            auto *r=rtv.Get();ctx->OMSetRenderTargets(1,&r,nullptr);D3D11_VIEWPORT vp={3,2,57,27,0.1f,0.9f};ctx->RSSetViewports(1,&vp);
            ctx->VSSetShader(vertex.Get(),nullptr,0);ctx->PSSetShader(ps[shader].Get(),nullptr,0);ctx->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
            for(UINT i=0;i<7;++i){auto *b=cb.Get();ctx->PSSetConstantBuffers(i,1,&b);ctx->VSSetConstantBuffers(i,1,&b);}
            for(UINT i=0;i<11;++i){auto *v=srv.Get();ctx->PSSetShaderResources(i,1,&v);}
            ctx->Draw(0,1);
        };
        auto present=[&](){check(swap->Present(0,0));MSG m;while(PeekMessageW(&m,nullptr,0,0,PM_REMOVE)){TranslateMessage(&m);DispatchMessageW(&m);}Sleep(5);};
        for(int i=0;i<20;++i){render(0);present();}
        if(fs::exists(root/"SMSM-native-captures"))throw std::runtime_error("default-off host captured data");
        command(root,"enable");render(0);present();
        command(root,"capture");render(0);present();
        produce();render(0);render(0);render(1);present();
        for(int i=0;i<20;++i){render(0);present();}
        // Repeat with new bytes on the same CB. New capture must not reuse old readback.
        std::fill(constants.begin(),constants.end(),7.25f);ctx->UpdateSubresource(cb.Get(),0,nullptr,constants.data(),0,0);
        command(root,"capture");render(0);present();produce();render(0);render(1);present();
        for(int i=0;i<20;++i){render(0);present();}
        command(root,"stop");present();
        if(argc==4) {
            auto ambient_command=[&](const char *action){std::ofstream out(root/"SMSM-native-captures"/"ambient-command.txt");out<<action<<'\n';};
            ambient_command("half");present();
            for(int i=0;i<3;++i){render(0);render(1);present();}
            ambient_command("status");present();
            fs::copy_file(root/"SMSM-native-captures"/"ambient-status.json",root/"ambient-enabled-status.json");
            ambient_command("off");present();render(0);render(1);present();
            ambient_command("status");present();
            fs::copy_file(root/"SMSM-native-captures"/"ambient-status.json",root/"ambient-disabled-status.json");
            if(std::wstring(argv[3])==L"coverage") {
                ambient_command("coverage");present();
                // No source/fullscreen draw: coverage must work without ambient readiness.
                for(int i=0;i<3;++i){render(1);present();}
                ambient_command("status");present();
                fs::copy_file(root/"SMSM-native-captures"/"ambient-status.json",root/"coverage-enabled-status.json");
                Sleep(10100);render(1);present();
                // Expiry publishes status by itself; do not hide failure with a status command.
                fs::copy_file(root/"SMSM-native-captures"/"ambient-status.json",root/"coverage-expired-status.json");
                ambient_command("coverage");present();render(1);present();
                ambient_command("off");present();render(1);present();
                ambient_command("status");present();
                fs::copy_file(root/"SMSM-native-captures"/"ambient-status.json",root/"coverage-off-status.json");
            }
        }
        if(FAILED(device->GetDeviceRemovedReason()))throw std::runtime_error("device removed");
        ctx->ClearState();ctx->Flush();DestroyWindow(window);
        std::cout<<"Actual ReShade hardware callback host completed (zero vertices)\n";return 0;
    }catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
