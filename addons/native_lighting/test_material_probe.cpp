#define wmain diagnostic_fixture_main
#include "test_diagnostic.cpp"
#undef wmain
#include "output_audit.hpp"

int wmain(int argc,wchar_t **argv) {
    try {
        require(argc==2,"output required");fs::path root=argv[1];require(!fs::exists(root),"immutable output exists");fs::create_directories(root);
        Fixture f;OutputAudit audit;const std::string vertex(64,'a');
        audit.arm(root,OutputAudit::Mode::probe,"full",0,vertex,3);
        f.ctx->PSSetShader(f.ps[0].Get(),nullptr,0);
        unsigned executed=0;
        auto draw=[&](UINT count,const std::string &vs){audit.draw(f.ctx.Get(),count,1,[&]{f.ctx->Draw(3,0);++executed;return true;},"full","synthetic",vs);};
        f.ctx->OMSetRenderTargets(0,nullptr,nullptr);
        for(unsigned i=0;i<520;++i)draw(3,vertex); // Depth-only passes cannot consume quota.
        auto *rt=f.rtv.Get();f.ctx->OMSetRenderTargets(1,&rt,nullptr);
        draw(6,vertex);draw(3,"wrong vertex");
        D3D11_BLEND_DESC desc={};ComPtr<ID3D11BlendState> zeroMask;check(f.device->CreateBlendState(&desc,&zeroMask));
        f.ctx->OMSetBlendState(zeroMask.Get(),nullptr,UINT_MAX);draw(3,vertex);f.ctx->OMSetBlendState(nullptr,nullptr,UINT_MAX);
        ComPtr<ID3D11DeviceContext1> ctx1;f.ctx.As(&ctx1);UINT first=16,constants=16;auto *cb=f.cb.Get();
        if(ctx1)ctx1->PSSetConstantBuffers1(3,1,&cb,&first,&constants);
        draw(3,vertex);
        std::vector<float> changed(256,3.5f);f.ctx->UpdateSubresource(f.cb.Get(),0,nullptr,changed.data(),0,0);
        draw(3,vertex);draw(3,vertex); // Two recorded draws, third still executes normally.
        audit.present(f.ctx.Get(),f.out.Get());f.ctx->Flush();
        for(int i=0;i<100 && audit.active();++i){Sleep(2);audit.present(f.ctx.Get(),f.out.Get());}
        require(!audit.active() && !audit.internal,"probe did not release staged objects");
        require(executed==526,"original draw callback count changed");
        ComPtr<ID3D11Buffer> bound;UINT gotFirst=0,gotCount=0;if(ctx1){ctx1->PSGetConstantBuffers1(3,1,&bound,&gotFirst,&gotCount);require(bound.Get()==cb && gotFirst==first && gotCount==constants,"constant binding modified");}
        OutputAudit cancelled;cancelled.arm(root,OutputAudit::Mode::probe,"full",0,vertex,3);cancelled.cancel();require(!cancelled.active(),"cancel left active probe");
        std::cout<<"Filtered depth-only/zero-write/geometry draws; two immutable input snapshots; original draw callbacks and CB range preserved\n";return 0;
    }catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
