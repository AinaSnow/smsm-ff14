#include "diagnostic.hpp"
#include <d3dcompiler.h>
#include <iostream>

using namespace smsm;
void require(bool value, const char *message) { if (!value) throw std::runtime_error(message); }
std::vector<unsigned char> compile(const char *code,const char *profile) {
    ComPtr<ID3DBlob> blob,error;
    HRESULT hr=D3DCompile(code,strlen(code),nullptr,nullptr,nullptr,"main",profile,0,0,&blob,&error);
    if (FAILED(hr)) throw std::runtime_error(error ? static_cast<const char *>(error->GetBufferPointer()) : "compile failed");
    auto *p=static_cast<unsigned char *>(blob->GetBufferPointer()); return {p,p+blob->GetBufferSize()};
}
using CreateDevice = decltype(&D3D11CreateDevice);
struct Fixture {
    ComPtr<ID3D11Device> device;
    ComPtr<ID3D11DeviceContext> ctx;
    ComPtr<ID3D11PixelShader> ps[2];
    ComPtr<ID3D11VertexShader> vs;
    ComPtr<ID3D11Texture2D> tex,out,depth;
    ComPtr<ID3D11ShaderResourceView> srv;
    ComPtr<ID3D11RenderTargetView> rtv;
    ComPtr<ID3D11DepthStencilView> dsv;
    ComPtr<ID3D11Buffer> cb;
    std::vector<unsigned char> code[2];
    Fixture() {
        wchar_t sys[MAX_PATH]; GetSystemDirectoryW(sys,MAX_PATH);
        auto module=LoadLibraryW((fs::path(sys)/"d3d11.dll").c_str());
        auto create=reinterpret_cast<CreateDevice>(GetProcAddress(module,"D3D11CreateDevice"));
        require(create!=nullptr,"system D3D11 missing");
        check(create(nullptr,D3D_DRIVER_TYPE_WARP,nullptr,0,nullptr,0,D3D11_SDK_VERSION,&device,nullptr,&ctx));
        code[0]=compile("Texture2D<float4> t:register(t10); float4 main(float4 p:SV_Position):SV_Target{return t.Load(int3(p.xy,0));}","ps_5_0");
        code[1]=compile("float4 main(float4 p:SV_Position):SV_Target{return float4(0.25,0.5,0.75,1);}","ps_5_0");
        for (int i=0;i<2;++i) check(device->CreatePixelShader(code[i].data(),code[i].size(),nullptr,&ps[i]));
        auto vc=compile("float4 main(uint id:SV_VertexID):SV_Position{float2 p=float2((id<<1)&2,id&2);return float4(p*float2(2,-2)+float2(-1,1),0,1);}","vs_5_0");
        check(device->CreateVertexShader(vc.data(),vc.size(),nullptr,&vs));
        D3D11_TEXTURE2D_DESC td={}; td.Width=17;td.Height=9;td.ArraySize=td.MipLevels=1;td.Format=DXGI_FORMAT_R32G32B32A32_FLOAT;
        td.SampleDesc.Count=1;td.BindFlags=D3D11_BIND_SHADER_RESOURCE;
        std::vector<float> pixels(17*9*4);for(size_t i=0;i<pixels.size();++i)pixels[i]=float(i)/1024;
        D3D11_SUBRESOURCE_DATA initial={pixels.data(),17*16,0};
        check(device->CreateTexture2D(&td,&initial,&tex)); check(device->CreateShaderResourceView(tex.Get(),nullptr,&srv));
        td.BindFlags=D3D11_BIND_RENDER_TARGET|D3D11_BIND_SHADER_RESOURCE;check(device->CreateTexture2D(&td,nullptr,&out));check(device->CreateRenderTargetView(out.Get(),nullptr,&rtv));
        td.Format=DXGI_FORMAT_R32_TYPELESS;td.BindFlags=D3D11_BIND_DEPTH_STENCIL;
        check(device->CreateTexture2D(&td,nullptr,&depth));
        D3D11_DEPTH_STENCIL_VIEW_DESC dd={};dd.Format=DXGI_FORMAT_D32_FLOAT;dd.ViewDimension=D3D11_DSV_DIMENSION_TEXTURE2D;
        check(device->CreateDepthStencilView(depth.Get(),&dd,&dsv));ctx->ClearDepthStencilView(dsv.Get(),D3D11_CLEAR_DEPTH,0.625f,0);
        D3D11_BUFFER_DESC bd={}; bd.ByteWidth=1024;bd.BindFlags=D3D11_BIND_CONSTANT_BUFFER;
        std::vector<float> constants(256);for(size_t i=0;i<constants.size();++i)constants[i]=float(i)+0.25f;
        D3D11_SUBRESOURCE_DATA bi={constants.data(),0,0};check(device->CreateBuffer(&bd,&bi,&cb));
        for(UINT i=0;i<7;++i){auto *b=cb.Get();ctx->PSSetConstantBuffers(i,1,&b);ctx->VSSetConstantBuffers(i,1,&b);}
        for(UINT i=0;i<11;++i){auto *v=srv.Get();ctx->PSSetShaderResources(i,1,&v);}
        auto *r=rtv.Get();ctx->OMSetRenderTargets(1,&r,dsv.Get());
        D3D11_DEPTH_STENCIL_DESC ds={};ds.DepthEnable=FALSE;ComPtr<ID3D11DepthStencilState> state;check(device->CreateDepthStencilState(&ds,&state));ctx->OMSetDepthStencilState(state.Get(),0);
        D3D11_VIEWPORT vp={2,1,13,7,0.2f,0.8f};ctx->RSSetViewports(1,&vp);ctx->VSSetShader(vs.Get(),nullptr,0);ctx->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    }
    void identify(Diagnostic &d) {
        d.targets={{"full",sha256(code[0].data(),code[0].size())},{"mesh",sha256(code[1].data(),code[1].size())}};
        for(int i=0;i<2;++i)d.init_shader(reinterpret_cast<uint64_t>(ps[i].Get()),code[i].data(),code[i].size());
        d.init_resource(reinterpret_cast<uint64_t>(tex.Get()),true);d.init_resource(reinterpret_cast<uint64_t>(cb.Get()),true);
        d.init_resource(reinterpret_cast<uint64_t>(depth.Get()),false);d.write(reinterpret_cast<uint64_t>(depth.Get()),"clear_depth_intent");
    }
    void draw(Diagnostic &d,int i) {ctx->PSSetShader(ps[i].Get(),nullptr,0);d.before_draw(ctx.Get(),"draw",3,1);ctx->Draw(3,0);}
    void finish(Diagnostic &d) {ctx->Flush();for(int i=0;i<8 && (d.recording||d.waiting);++i){d.present(ctx.Get());Sleep(2);}require(!d.waiting,"readback timeout");}
};
int wmain(int argc,wchar_t **argv) {
    try {
        require(argc==2,"output required");fs::path root=argv[1];require(!fs::exists(root),"immutable test output exists");fs::create_directories(root);
        Fixture f;
        Diagnostic d(root/"normal");f.identify(d);
        require(!d.arm(),"default should reject capture");f.draw(d,0);require(!fs::exists(d.root),"default-off wrote data");
        d.enabled=true;require(d.arm(),"arm failed");require(!d.arm(),"duplicate arm accepted");f.draw(d,0);f.draw(d,0);f.draw(d,1);
        require(d.draws.size()==2,"once-per-target failed");f.finish(d);
        require(d.status=="snapshots_complete","targets missing");
        std::vector<float> next(256,3.5f);f.ctx->UpdateSubresource(f.cb.Get(),0,nullptr,next.data(),0,0);
        d.write(reinterpret_cast<uint64_t>(f.cb.Get()),"update_buffer_intent");require(d.arm(),"second arm failed");f.draw(d,0);f.finish(d);
        require(d.status=="partial_targets","missing target was hidden");
        Diagnostic limited(root/"budget");f.identify(limited);limited.enabled=true;limited.budget=16;limited.arm();f.draw(limited,0);
        require(limited.status=="budget_exceeded" && !limited.recording,"budget did not stop");
        Diagnostic absent(root/"absent");f.identify(absent);absent.enabled=true;absent.arm();f.finish(absent);require(absent.status=="missing_targets","missing targets not reported");
        Diagnostic stop(root/"cancel");f.identify(stop);stop.enabled=true;stop.arm();f.draw(stop,0);stop.stop();require(stop.draws.empty()&&!stop.enabled,"stop kept staging");
        Diagnostic lost(root/"lost_shader");f.identify(lost);lost.enabled=true;lost.shaders.erase(reinterpret_cast<uint64_t>(f.ps[0].Get()));lost.arm();f.draw(lost,0);f.finish(lost);require(lost.status=="missing_targets","destroyed shader reused");
        Diagnostic deferred(root/"deferred");f.identify(deferred);deferred.enabled=true;ComPtr<ID3D11DeviceContext> dc;check(f.device->CreateDeferredContext(0,&dc));
        deferred.arm();deferred.before_draw(dc.Get(),"draw",3,1);f.finish(deferred);require(deferred.deferred_draws==1,"deferred not rejected");
        Diagnostic reborn(root/"recreated");f.identify(reborn);reborn.enabled=true;
        auto id=reinterpret_cast<uint64_t>(f.tex.Get());auto gen=reborn.histories.at(id).generation;reborn.destroy_resource(id);reborn.init_resource(id,false);
        require(reborn.histories.at(id).generation>gen,"resource generation reused");reborn.arm();f.draw(reborn,0);f.finish(reborn);
        // Preserve real draw output for an independent readback/no-modification check.
        D3D11_TEXTURE2D_DESC desc;f.out->GetDesc(&desc);desc.Usage=D3D11_USAGE_STAGING;desc.BindFlags=0;desc.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
        ComPtr<ID3D11Texture2D> read;check(f.device->CreateTexture2D(&desc,nullptr,&read));f.ctx->CopyResource(read.Get(),f.out.Get());
        D3D11_MAPPED_SUBRESOURCE m;check(f.ctx->Map(read.Get(),0,D3D11_MAP_READ,0,&m));
        const float *p=reinterpret_cast<const float *>(static_cast<unsigned char *>(m.pData)+m.RowPitch*2)+4*3;
        require(p[0]==float((2*17+3)*4)/1024,"capture changed application output");f.ctx->Unmap(read.Get(),0);
        Diagnostic producers(root/"producer");f.identify(producers);producers.init_resource(reinterpret_cast<uint64_t>(f.out.Get()),false);
        producers.set_enabled(true);f.draw(producers,0);
        D3D11_BLEND_DESC alpha_only_desc={};alpha_only_desc.RenderTarget[0].RenderTargetWriteMask=D3D11_COLOR_WRITE_ENABLE_ALPHA;
        ComPtr<ID3D11BlendState> alpha_only;check(f.device->CreateBlendState(&alpha_only_desc,&alpha_only));
        f.ctx->OMSetBlendState(alpha_only.Get(),nullptr,~0u);f.draw(producers,1);
        auto output_id=reinterpret_cast<uint64_t>(f.out.Get());
        require(producers.histories.at(output_id).pixel_writers.size()==2,"multiple draw writers lost");
        require(producers.histories.at(output_id).draw_writer.fields.at("color_write_mask")=="8","alpha-only mask not recorded");
        f.ctx->CopyResource(read.Get(),f.out.Get());check(f.ctx->Map(read.Get(),0,D3D11_MAP_READ,0,&m));
        p=reinterpret_cast<const float *>(static_cast<unsigned char *>(m.pData)+m.RowPitch*2)+4*3;
        require(p[0]==float((2*17+3)*4)/1024 && p[3]==1,"last draw incorrectly assumed to own RGB");f.ctx->Unmap(read.Get(),0);
        f.ctx->OMSetBlendState(nullptr,nullptr,~0u);
        producers.write(output_id,"copy_resource_intent");
        require(producers.histories.at(output_id).draw_writer.fields.empty(),"copy retained stale producer");
        f.draw(producers,0);
        producers.stop();producers.set_enabled(true);
        require(producers.resource_meta(f.out.Get(),"test","unknown").fields.at("writer_observation_scope")==quote("historical_observation_only"),"disabled epoch reused as current");
        f.draw(producers,0); // Fresh producer in the current enable epoch.
        ComPtr<ID3D11ShaderResourceView> produced_srv;check(f.device->CreateShaderResourceView(f.out.Get(),nullptr,&produced_srv));
        D3D11_TEXTURE2D_DESC alternate_desc;f.out->GetDesc(&alternate_desc);
        ComPtr<ID3D11Texture2D> alternate;ComPtr<ID3D11RenderTargetView> alternate_rtv;
        check(f.device->CreateTexture2D(&alternate_desc,nullptr,&alternate));check(f.device->CreateRenderTargetView(alternate.Get(),nullptr,&alternate_rtv));
        auto *alternate_view=alternate_rtv.Get();f.ctx->OMSetRenderTargets(1,&alternate_view,f.dsv.Get());
        auto *produced_view=produced_srv.Get();f.ctx->PSSetShaderResources(10,1,&produced_view);
        producers.arm();f.draw(producers,0);f.finish(producers);
        auto *original_source=f.srv.Get();f.ctx->PSSetShaderResources(10,1,&original_source);
        auto *original_target=f.rtv.Get();f.ctx->OMSetRenderTargets(1,&original_target,f.dsv.Get());
        // Actual game r1 reported DXGI 87 normals. Verify exact BGRA bytes, padded
        // staging rows, and the GPU's independent logical RGBA interpretation.
        std::vector<unsigned char> bgra(17*9*4);
        for(unsigned y=0;y<9;++y)for(unsigned x=0;x<17;++x){
            auto i=(y*17+x)*4;bgra[i]=static_cast<unsigned char>(x*3+y);bgra[i+1]=static_cast<unsigned char>(x+y*7);
            bgra[i+2]=static_cast<unsigned char>(x*11+y*17);bgra[i+3]=static_cast<unsigned char>((x^y)^128);
        }
        D3D11_TEXTURE2D_DESC bd={};bd.Width=17;bd.Height=9;bd.MipLevels=bd.ArraySize=1;
        bd.Format=DXGI_FORMAT_B8G8R8A8_UNORM;bd.SampleDesc.Count=1;bd.BindFlags=D3D11_BIND_SHADER_RESOURCE;
        D3D11_SUBRESOURCE_DATA bi={bgra.data(),17*4,0};ComPtr<ID3D11Texture2D> bt;ComPtr<ID3D11ShaderResourceView> bv;
        check(f.device->CreateTexture2D(&bd,&bi,&bt));check(f.device->CreateShaderResourceView(bt.Get(),nullptr,&bv));
        auto *bound=bv.Get();f.ctx->PSSetShaderResources(5,1,&bound);f.ctx->PSSetShaderResources(10,1,&bound);
        Diagnostic bg(root/"bgra8");f.identify(bg);bg.init_resource(reinterpret_cast<uint64_t>(bt.Get()),true);
        bg.enabled=true;bg.arm();f.draw(bg,0);f.finish(bg);require(bg.status=="partial_targets","BGRA target capture missing");
        f.ctx->CopyResource(read.Get(),f.out.Get());check(f.ctx->Map(read.Get(),0,D3D11_MAP_READ,0,&m));
        p=reinterpret_cast<const float *>(static_cast<unsigned char *>(m.pData)+m.RowPitch*2)+4*3;
        const unsigned i=(2*17+3)*4;const unsigned channel[]={2,1,0,3};
        for(unsigned c=0;c<4;++c)require(std::abs(p[c]-float(bgra[i+channel[c]])/255)<1e-7f,"BGRA logical channel order or output changed");
        f.ctx->Unmap(read.Get(),0);
        std::cout<<"Actual WARP draws, bounded staging readback and lifecycle checks passed\n";return 0;
    } catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
