#define wmain diagnostic_fixture_main
#include "test_diagnostic.cpp"
#undef wmain
#include "output_audit.hpp"

int wmain(int argc,wchar_t **argv) {
    try {
        require(argc==2,"output required");fs::path root=argv[1];require(!fs::exists(root),"immutable output exists");fs::create_directories(root);
        for(const char *name:{"normal","stale","capped","cancel"})fs::create_directories(root/name);
        Fixture f;Diagnostic history(root);f.identify(history);
        auto code=compile("cbuffer Light:register(b2){float4 p[64];};struct O{float3 a:SV_Target0;float3 b:SV_Target1;};O main(float4 pos:SV_Position){O o;o.a=p[2].xyz;o.b=p[3].xyz;return o;}","ps_5_0");
        ComPtr<ID3D11PixelShader> producer;check(f.device->CreatePixelShader(code.data(),code.size(),nullptr,&producer));history.init_shader(reinterpret_cast<uint64_t>(producer.Get()),code.data(),code.size());
        ComPtr<ID3D11Texture2D> light[2];ComPtr<ID3D11RenderTargetView> rt[2];ComPtr<ID3D11ShaderResourceView> srv[2];
        for(UINT i=0;i<2;++i){D3D11_TEXTURE2D_DESC td={};td.Width=17;td.Height=9;td.MipLevels=td.ArraySize=1;td.Format=DXGI_FORMAT_R11G11B10_FLOAT;td.SampleDesc.Count=1;td.BindFlags=D3D11_BIND_RENDER_TARGET|D3D11_BIND_SHADER_RESOURCE;
            check(f.device->CreateTexture2D(&td,nullptr,&light[i]));check(f.device->CreateRenderTargetView(light[i].Get(),nullptr,&rt[i]));check(f.device->CreateShaderResourceView(light[i].Get(),nullptr,&srv[i]));history.init_resource(reinterpret_cast<uint64_t>(light[i].Get()),false);}
        std::vector<float> constants(256,0);constants[8]=4;constants[9]=1.4f;constants[10]=.4f;constants[12]=2;constants[13]=.7f;constants[14]=.2f;
        D3D11_BUFFER_DESC bd={};bd.ByteWidth=1024;bd.BindFlags=D3D11_BIND_CONSTANT_BUFFER;D3D11_SUBRESOURCE_DATA data={constants.data(),0,0};ComPtr<ID3D11Buffer> cb;check(f.device->CreateBuffer(&bd,&data,&cb));history.init_resource(reinterpret_cast<uint64_t>(cb.Get()),true);
        auto *buffer=cb.Get();f.ctx->PSSetConstantBuffers(2,1,&buffer);
        const std::string vertex(64,'a');
        auto execute=[&](OutputAudit &audit){history.before_draw(f.ctx.Get(),"draw",3,1);audit.observe_producer(f.ctx.Get(),"draw",3,1);f.ctx->Draw(3,0);};
        auto consume=[&](OutputAudit &audit){auto *out=f.rtv.Get();f.ctx->OMSetRenderTargets(1,&out,nullptr);ID3D11ShaderResourceView *inputs[2]={srv[0].Get(),srv[1].Get()};f.ctx->PSSetShaderResources(0,2,inputs);f.ctx->PSSetShader(f.ps[0].Get(),nullptr,0);
            history.before_draw(f.ctx.Get(),"draw",3,1);audit.observe_producer(f.ctx.Get(),"draw",3,1);audit.draw(f.ctx.Get(),3,1,[&]{f.ctx->Draw(3,0);return true;},"full","synthetic",vertex);};
        auto finish=[&](OutputAudit &audit){audit.present(f.ctx.Get(),f.out.Get());require(!history.enabled,"tracking stayed enabled after capture frame");f.ctx->Flush();for(int i=0;i<100&&audit.active();++i){Sleep(2);audit.present(f.ctx.Get(),f.out.Get());}require(!audit.active(),"readback did not finish");++history.frame;history.draw=0;};
        OutputAudit audit;audit.arm(root/"normal",OutputAudit::Mode::probe,"full",0,vertex,3,&history);
        f.ctx->OMSetRenderTargets(0,nullptr,nullptr);for(UINT i=0;i<520;++i)execute(audit);
        ID3D11RenderTargetView *outputs[2]={rt[0].Get(),rt[1].Get()};f.ctx->OMSetRenderTargets(2,outputs,nullptr);f.ctx->PSSetShader(producer.Get(),nullptr,0);execute(audit);
        std::fill(constants.begin(),constants.end(),3.5f);f.ctx->UpdateSubresource(cb.Get(),0,nullptr,constants.data(),0,0);history.write(reinterpret_cast<uint64_t>(cb.Get()),"update_buffer_intent");consume(audit);finish(audit);
        OutputAudit stale;stale.arm(root/"stale",OutputAudit::Mode::probe,"full",0,vertex,3,&history);consume(stale);finish(stale);
        OutputAudit capped;capped.arm(root/"capped",OutputAudit::Mode::probe,"full",0,vertex,3,&history);f.ctx->OMSetRenderTargets(2,outputs,nullptr);f.ctx->PSSetShader(producer.Get(),nullptr,0);for(UINT i=0;i<129;++i)execute(capped);consume(capped);finish(capped);
        OutputAudit stop;stop.arm(root/"cancel",OutputAudit::Mode::probe,"full",0,vertex,3,&history);stop.cancel();require(!history.enabled,"cancel left tracking enabled");
        std::cout<<"Producer/consumer resource link, frozen CB, frame scoping, producer cap and tracking cleanup exercised\n";return 0;
    }catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
