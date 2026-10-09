#pragma once
#include "diagnostic.hpp"

namespace smsm {
// One frame, exact target only. Queries do not imply color writes; raw before/
// after/end snapshots provide separate evidence. No forced render-state changes.
class OutputAudit {
public:
    enum class Mode {marker,census,sample,probe};
private:
    struct Image {
        Json meta;
        ComPtr<ID3D11Texture2D> source,stage;
        UINT sub=0,width=0,height=0,bpp=0;
    };
    struct Constant {Json meta;ComPtr<ID3D11Buffer> stage;UINT bytes=0;};
    struct Entry {Json meta;ComPtr<ID3D11Query> query;std::vector<Image> images,inputs;std::vector<Constant> constants;};
    std::vector<Entry> entries;
    std::vector<Entry> producers;
    Diagnostic *tracker=nullptr;
    uint64_t producer_bytes=0,producer_candidates=0;
    bool producer_truncated=false;
    std::map<uint64_t,uint64_t> resource_ids;
    std::vector<ComPtr<ID3D11Resource>> held_resources;
    ComPtr<ID3D11Query> done;
    fs::path directory;
    uint64_t bytes=0,observed=0,started=0;
    bool recording=false,waiting=false;
    Mode mode=Mode::marker;
    std::string selected_shader;
    std::string selected_vertex;
    UINT selected_elements=0;
    UINT skip_draws=0;
    Image final_image;
    uint64_t id(ID3D11Resource *r) {
        if(!r)return 0;
        auto key=reinterpret_cast<uint64_t>(r);
        auto [it,inserted]=resource_ids.emplace(key,resource_ids.size()+1);
        if(inserted)held_resources.emplace_back(r); // Prevent pointer reuse within this audit.
        return it->second;
    }
    Image prepare(ID3D11DeviceContext *ctx,ID3D11Texture2D *source,UINT sub,DXGI_FORMAT view,const std::string &label) {
        Image image;image.meta.text("label",label);
        if(!source){image.meta.text("status","missing");return image;}
        D3D11_TEXTURE2D_DESC desc;source->GetDesc(&desc);
        image.meta.num("resource",id(source));image.meta.num("format",desc.Format);image.meta.num("view_format",view);
        image.meta.num("subresource",sub);image.meta.num("sample_count",desc.SampleDesc.Count);
        const UINT mip=sub%desc.MipLevels;
        image.width=std::max(1u,desc.Width>>mip);image.height=std::max(1u,desc.Height>>mip);image.bpp=texel_bytes(desc.Format);
        const uint64_t size=uint64_t(image.width)*image.height*image.bpp;
        if(desc.SampleDesc.Count!=1 || !image.bpp || sub>=desc.MipLevels*desc.ArraySize || size>budget-bytes){image.meta.text("status","unsupported_or_budget");return image;}
        bytes+=size;image.source=source;image.sub=sub;
        desc.Width=image.width;desc.Height=image.height;desc.ArraySize=desc.MipLevels=1;
        desc.BindFlags=desc.MiscFlags=0;desc.Usage=D3D11_USAGE_STAGING;desc.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
        ComPtr<ID3D11Device> device;ctx->GetDevice(&device);check(device->CreateTexture2D(&desc,nullptr,&image.stage));
        image.meta.num("width",image.width);image.meta.num("height",image.height);image.meta.num("bytes",size);
        image.meta.text("status","queued");return image;
    }
    static void copy(ID3D11DeviceContext *ctx,Image &i) {
        if(!i.stage)return;
        ComPtr<ID3D11Predicate> predicate;BOOL value;ctx->GetPredication(&predicate,&value);
        // Audit copies must not be skipped by the game's predicate. Restore it
        // before the actual draw, whose original predication remains intact.
        if(predicate)ctx->SetPredication(nullptr,FALSE);
        ctx->CopySubresourceRegion(i.stage.Get(),0,0,0,0,i.source.Get(),i.sub,nullptr);
        if(predicate)ctx->SetPredication(predicate.Get(),value);
    }
    Json read(ID3D11DeviceContext *ctx,Image &i) {
        if(!i.stage)return i.meta;
        D3D11_MAPPED_SUBRESOURCE mapped;check(ctx->Map(i.stage.Get(),0,D3D11_MAP_READ,D3D11_MAP_FLAG_DO_NOT_WAIT,&mapped));
        std::vector<char> data;
        try {
            data.resize(size_t(i.width)*i.height*i.bpp);
            for(UINT y=0;y<i.height;++y)memcpy(data.data()+size_t(y)*i.width*i.bpp,static_cast<char*>(mapped.pData)+size_t(y)*mapped.RowPitch,size_t(i.width)*i.bpp);
        }catch(...){ctx->Unmap(i.stage.Get(),0);throw;}
        ctx->Unmap(i.stage.Get(),0);
        // Labels are generated internally and contain no caller-controlled path.
        const auto label=i.meta.fields.at("label");
        const std::string name=label.substr(1,label.size()-2)+".bin";
        std::ofstream file(directory/name,std::ios::binary);file.write(data.data(),data.size());
        if(!file)throw std::runtime_error("output audit payload write failed");
        i.meta.text("file",name);i.meta.text("sha256",sha256(data.data(),data.size()));i.meta.text("status","captured");return i.meta;
    }
    void capture_inputs(ID3D11DeviceContext *ctx,Entry &entry,bool constants_only=false,const std::string &prefix="") {
        // Called before the original draw. Copy commands share its immediate
        // context order; later binding/resource changes cannot alter snapshots.
        ComPtr<ID3D11Device> device;ctx->GetDevice(&device);
        ComPtr<ID3D11DeviceContext1> ctx1;ctx->QueryInterface(IID_PPV_ARGS(&ctx1));
        ComPtr<ID3D11Predicate> predicate;BOOL value;ctx->GetPredication(&predicate,&value);
        if(predicate)ctx->SetPredication(nullptr,FALSE);
        try {
            for(UINT slot=0;slot<7;++slot){
                Constant c;const std::string label=(prefix.empty()?"draw-"+number(observed):prefix)+"-ps-b"+number(slot);
                c.meta.text("label",label);c.meta.text("stage","ps");c.meta.text("phase","pre_draw");c.meta.num("slot",slot);
                ComPtr<ID3D11Buffer> source;UINT first=0,count=4096;
                if(ctx1)ctx1->PSGetConstantBuffers1(slot,1,&source,&first,&count);else ctx->PSGetConstantBuffers(slot,1,&source);
                c.meta.num("constant_first",first);c.meta.num("constant_count",count);c.meta.num("resource",id(source.Get()));
                if(!source)c.meta.text("status","missing_binding");
                else {
                    D3D11_BUFFER_DESC desc;source->GetDesc(&desc);c.meta.num("byte_width",desc.ByteWidth);
                    if(desc.ByteWidth>4*1024*1024 || desc.ByteWidth>budget-bytes || (constants_only && desc.ByteWidth>32ull*1024*1024-producer_bytes)){
                        c.meta.text("status","unsupported_or_budget");if(constants_only)producer_truncated=true;
                    }
                    else {
                        c.bytes=desc.ByteWidth;bytes+=c.bytes;c.meta.num("bytes",c.bytes);
                        if(constants_only)producer_bytes+=c.bytes;
                        D3D11_BUFFER_DESC staging={};staging.ByteWidth=c.bytes;staging.Usage=D3D11_USAGE_STAGING;staging.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
                        check(device->CreateBuffer(&staging,nullptr,&c.stage));ctx->CopyResource(c.stage.Get(),source.Get());c.meta.text("status","queued");
                    }
                }
                entry.constants.push_back(std::move(c));
            }
            for(UINT slot=0;!constants_only && slot<4;++slot){
                ComPtr<ID3D11ShaderResourceView> view;ctx->PSGetShaderResources(slot,1,&view);
                ComPtr<ID3D11Resource> resource;if(view)view->GetResource(&resource);
                D3D11_SHADER_RESOURCE_VIEW_DESC vd={};if(view)view->GetDesc(&vd);
                ComPtr<ID3D11Texture2D> tex;if(resource)resource.As(&tex);
                const bool supported=tex && vd.ViewDimension==D3D11_SRV_DIMENSION_TEXTURE2D;
                auto input=prepare(ctx,supported?tex.Get():nullptr,supported?vd.Texture2D.MostDetailedMip:0,vd.Format,"draw-"+number(observed)+"-ps-t"+number(slot));
                input.meta.text("stage","ps");input.meta.text("phase","pre_draw");input.meta.num("slot",slot);
                input.meta.num("resource",id(resource.Get()));input.meta.num("view_dimension",vd.ViewDimension);
                if(tracker && resource)input.meta.fields["producer_history"]=tracker->resource_meta(resource.Get(),"consumer-ps-t"+number(slot),"observed_pre_draw_resource_history").str();
                if(view && !supported)input.meta.text("status","unsupported_view_dimension");
                copy(ctx,input);entry.inputs.push_back(std::move(input));
            }
        }catch(...){if(predicate)ctx->SetPredication(predicate.Get(),value);throw;}
        if(predicate)ctx->SetPredication(predicate.Get(),value);
    }
    Json read_constant(ID3D11DeviceContext *ctx,Constant &c) {
        if(!c.stage)return c.meta;
        D3D11_MAPPED_SUBRESOURCE mapped;check(ctx->Map(c.stage.Get(),0,D3D11_MAP_READ,D3D11_MAP_FLAG_DO_NOT_WAIT,&mapped));
        std::vector<char> data;
        try {data.resize(c.bytes);memcpy(data.data(),mapped.pData,c.bytes);}catch(...){ctx->Unmap(c.stage.Get(),0);throw;}
        ctx->Unmap(c.stage.Get(),0);
        const auto label=c.meta.fields.at("label");const auto name=label.substr(1,label.size()-2)+".bin";
        std::ofstream file(directory/name,std::ios::binary);file.write(data.data(),data.size());if(!file)throw std::runtime_error("constant snapshot write failed");
        c.meta.text("file",name);c.meta.text("sha256",sha256(data.data(),data.size()));c.meta.text("status","captured");return c.meta;
    }
    void write_report(ID3D11DeviceContext *ctx,const std::string &status) {
        Json report;report.num("schema",1);report.text("status",status);report.num("observed_target_draws",observed);
        report.num("byte_budget",budget);report.num("selected_bytes",bytes);
        report.text("mode",mode==Mode::marker?"marker":mode==Mode::census?"census":mode==Mode::probe?"probe":"sample");
        if(mode==Mode::probe){report.text("selected_vertex_sha256",selected_vertex);report.num("selected_elements",selected_elements);}
        report.text("selected_shader",selected_shader);report.num("skip_draws",skip_draws);report.num("recorded_draws",entries.size());
        if(tracker){
            report.num("producer_candidates",producer_candidates);report.num("producer_bytes",producer_bytes);
            report.fields["producer_trace_truncated"]=producer_truncated?"true":"false";
            report.fields["complete_write_history_verified"]="false";
            report.text("producer_trace_scope","one capture frame; dual R11G11B10 RGB RTV draw candidates, at most 128 PS b0-b6 snapshots/32 MiB; binding is not pixel contribution; compute/UAV/indirect writes not complete");
            std::vector<std::string> records;
            for(auto &p:producers){
                if(status=="complete"){std::vector<std::string> inputs;for(auto &c:p.constants)inputs.push_back(read_constant(ctx,c).str());p.meta.fields["inputs"]=array(inputs);}
                records.push_back(p.meta.str());
            }
            report.fields["producer_records"]=array(records);
        }
        report.text("scope",mode==Mode::census?"verified material packages; at most 512 original-draw states/queries; no per-draw color snapshots":"one exact PS; at most 128 draw states/queries and first four selected RTV0 before/after/end snapshots; queries do not prove color writes");
        if(mode==Mode::probe)report.text("scope","exact PS/VS/element count with RGB output; at most two draws, PS b0-b6/t0-t3 pre-draw inputs and RTV snapshots; binding names are not proven light semantics");
        std::vector<std::string> rows;
        for(auto &e:entries){
            if(status=="complete") {
                UINT64 samples=0;const HRESULT hr=ctx->GetData(e.query.Get(),&samples,sizeof(samples),D3D11_ASYNC_GETDATA_DONOTFLUSH);
                if(hr==S_OK)e.meta.num("occlusion_samples",samples);else e.meta.text("query_status","unavailable");
                std::vector<std::string> images;for(auto &i:e.images)images.push_back(read(ctx,i).str());e.meta.fields["images"]=array(images);
                if(mode==Mode::probe){std::vector<std::string> resources;for(auto &c:e.constants)resources.push_back(read_constant(ctx,c).str());for(auto &i:e.inputs)resources.push_back(read(ctx,i).str());e.meta.fields["inputs"]=array(resources);}
            }
            rows.push_back(e.meta.str());
        }
        report.fields["draws"]=array(rows);
        if(status=="complete")report.fields["present_backbuffer"]=read(ctx,final_image).str();
        std::ofstream file(directory/"report.json");file<<report.str()<<'\n';if(!file)throw std::runtime_error("output audit report write failed");
    }
public:
    static constexpr uint64_t budget=256ull*1024*1024;
    bool internal=false;
    bool active() const {return recording || waiting;}
    bool collecting() const {return recording;}
    bool read_only() const {return mode!=Mode::marker;}
    bool accepts(const std::string &hash) const {return mode==Mode::census || (mode==Mode::sample || mode==Mode::probe) && hash==selected_shader;}
    const fs::path &path() const {return directory;}
    void cancel(){recording=waiting=internal=false;if(tracker)tracker->set_enabled(false);tracker=nullptr;entries.clear();producers.clear();resource_ids.clear();held_resources.clear();done.Reset();final_image={};}
    void arm(const fs::path &root,Mode requested=Mode::marker,const std::string &shader="",UINT skip=0,const std::string &vertex="",UINT elements=0,Diagnostic *history=nullptr) {
        if(active())throw std::runtime_error("output audit already active");
        cancel();bytes=observed=0;
        mode=requested;selected_shader=shader;skip_draws=skip;selected_vertex=vertex;selected_elements=elements;
        directory=root/("output-audit-"+number(GetCurrentProcessId())+"-"+number(GetTickCount64()));
        if(!fs::create_directory(directory))throw std::runtime_error("output audit directory exists");
        recording=true;producer_bytes=producer_candidates=0;producer_truncated=false;
        if(mode==Mode::probe && history){tracker=history;tracker->captured_frame=tracker->frame;tracker->set_enabled(true);}
    }
    void observe_producer(ID3D11DeviceContext *ctx,const char *kind,UINT count,UINT instances) {
        if(!recording || mode!=Mode::probe || !tracker || internal || ctx->GetType()!=D3D11_DEVICE_CONTEXT_IMMEDIATE || !instances || count==UINT_MAX)return;
        ID3D11RenderTargetView *raw[2]={};ctx->OMGetRenderTargets(2,raw,nullptr);ComPtr<ID3D11RenderTargetView> views[2];views[0].Attach(raw[0]);views[1].Attach(raw[1]);
        if(!views[0] || !views[1])return;
        D3D11_RENDER_TARGET_VIEW_DESC desc[2];views[0]->GetDesc(&desc[0]);views[1]->GetDesc(&desc[1]);
        if(desc[0].Format!=DXGI_FORMAT_R11G11B10_FLOAT || desc[1].Format!=DXGI_FORMAT_R11G11B10_FLOAT)return;
        ComPtr<ID3D11BlendState> blend;FLOAT factors[4];UINT sample_mask;ctx->OMGetBlendState(&blend,factors,&sample_mask);D3D11_BLEND_DESC bd={};if(blend)blend->GetDesc(&bd);
        for(UINT i=0;i<2;++i)if(blend && !(bd.RenderTarget[bd.IndependentBlendEnable?i:0].RenderTargetWriteMask&7))return;
        ++producer_candidates;if(producers.size()>=128){producer_truncated=true;return;}
        Entry entry;auto &j=entry.meta;j.num("frame",tracker->frame);j.num("draw",tracker->draw);j.text("call",kind);j.num("elements",count);j.num("instances",instances);
        ComPtr<ID3D11PixelShader> ps;ComPtr<ID3D11VertexShader> vs;ctx->PSGetShader(&ps,nullptr,nullptr);ctx->VSGetShader(&vs,nullptr,nullptr);
        auto shader=[&](uint64_t pointer){auto it=tracker->shaders.find(pointer);return it==tracker->shaders.end()?"unknown":it->second.second;};
        j.text("pixel_sha256",shader(reinterpret_cast<uint64_t>(ps.Get())));j.text("vertex_sha256",shader(reinterpret_cast<uint64_t>(vs.Get())));
        std::vector<std::string> outputs;
        for(UINT i=0;i<2;++i){ComPtr<ID3D11Resource> r;views[i]->GetResource(&r);auto m=tracker->resource_meta(r.Get(),"producer-o"+number(i),"RTV_write_intent_not_pixel_provenance");m.num("resource",id(r.Get()));m.num("slot",i);m.num("view_format",desc[i].Format);outputs.push_back(m.str());}
        j.fields["outputs"]=array(outputs);
        internal=true;try{capture_inputs(ctx,entry,true,"producer-"+number(tracker->draw));internal=false;}catch(...){internal=false;throw;}
        producers.push_back(std::move(entry));
    }
    template<class F> bool draw(ID3D11DeviceContext *ctx,UINT count,UINT instances,F call,
            const std::string &pixel_hash="",const std::string &packages="",const std::string &vertex_sha="") {
        if(!recording || internal || ctx->GetType()!=D3D11_DEVICE_CONTEXT_IMMEDIATE)return call();
        if(mode==Mode::probe){
            if(count!=selected_elements || vertex_sha!=selected_vertex)return call();
            ComPtr<ID3D11RenderTargetView> output;ctx->OMGetRenderTargets(1,&output,nullptr);if(!output)return call();
            ComPtr<ID3D11BlendState> blend;FLOAT factors[4];UINT mask;ctx->OMGetBlendState(&blend,factors,&mask);
            if(blend){D3D11_BLEND_DESC desc;blend->GetDesc(&desc);if(!(desc.RenderTarget[0].RenderTargetWriteMask&7))return call();}
        }
        ++observed;if(observed<=skip_draws || entries.size()>=(mode==Mode::census?512u:mode==Mode::probe?2u:128u))return call();
        Entry entry;auto &j=entry.meta;j.num("ordinal",observed);j.num("elements",count);j.num("instances",instances);
        if(tracker){j.num("frame",tracker->frame);j.num("draw",tracker->draw);}
        j.text("pixel_shader",pixel_hash);j.text("packages",packages);j.text("vertex_sha256",vertex_sha);
        j.fields["shader_replaced"]=mode==Mode::marker?"true":"false";
        ID3D11RenderTargetView *raw[8]={};ComPtr<ID3D11DepthStencilView> depth;ctx->OMGetRenderTargets(8,raw,&depth);
        ComPtr<ID3D11RenderTargetView> rt[8];for(UINT i=0;i<8;++i)rt[i].Attach(raw[i]);
        ComPtr<ID3D11BlendState> blend;FLOAT factors[4];UINT sampleMask;ctx->OMGetBlendState(&blend,factors,&sampleMask);
        D3D11_BLEND_DESC bd={};if(blend)blend->GetDesc(&bd);
        j.num("sample_mask",sampleMask);j.num("alpha_to_coverage",bd.AlphaToCoverageEnable);
        j.fields["blend_factor"]=array({number(factors[0]),number(factors[1]),number(factors[2]),number(factors[3])});
        std::vector<std::string> outputs;
        for(UINT slot=0;slot<8;++slot)if(rt[slot]){
            D3D11_RENDER_TARGET_VIEW_DESC vd;rt[slot]->GetDesc(&vd);ComPtr<ID3D11Resource> r;rt[slot]->GetResource(&r);
            Json o;o.num("slot",slot);o.num("resource",id(r.Get()));o.num("view_format",vd.Format);o.num("view_dimension",vd.ViewDimension);
            const auto &b=bd.RenderTarget[bd.IndependentBlendEnable?slot:0];
            o.num("write_mask",blend?b.RenderTargetWriteMask:15);o.num("blend_enabled",b.BlendEnable);
            o.num("src_blend",b.SrcBlend);o.num("dst_blend",b.DestBlend);o.num("blend_op",b.BlendOp);
            o.num("src_alpha",b.SrcBlendAlpha);o.num("dst_alpha",b.DestBlendAlpha);o.num("alpha_op",b.BlendOpAlpha);
            outputs.push_back(o.str());
            if(slot==0 && mode!=Mode::census && entries.size()<4){
                ComPtr<ID3D11Texture2D> tex;r.As(&tex);UINT sub=0;bool supported=false;
                if(vd.ViewDimension==D3D11_RTV_DIMENSION_TEXTURE2D){sub=vd.Texture2D.MipSlice;supported=true;}
                if(vd.ViewDimension==D3D11_RTV_DIMENSION_TEXTURE2DARRAY && vd.Texture2DArray.ArraySize==1 && tex){
                    D3D11_TEXTURE2D_DESC td;tex->GetDesc(&td);sub=D3D11CalcSubresource(vd.Texture2DArray.MipSlice,vd.Texture2DArray.FirstArraySlice,td.MipLevels);supported=true;
                }
                for(const char *phase:{"before","after","end"})entry.images.push_back(prepare(ctx,supported?tex.Get():nullptr,sub,vd.Format,"draw-"+number(observed)+"-"+phase));
            }
        }
        j.fields["outputs"]=array(outputs);
        ComPtr<ID3D11DepthStencilState> ds;UINT ref;ctx->OMGetDepthStencilState(&ds,&ref);
        D3D11_DEPTH_STENCIL_DESC dd={};if(ds)ds->GetDesc(&dd);else{dd.DepthEnable=TRUE;dd.DepthWriteMask=D3D11_DEPTH_WRITE_MASK_ALL;dd.DepthFunc=D3D11_COMPARISON_LESS;}
        j.num("depth_enabled",dd.DepthEnable);j.num("depth_write",dd.DepthWriteMask);j.num("depth_func",dd.DepthFunc);j.num("stencil_enabled",dd.StencilEnable);j.num("stencil_ref",ref);
        j.num("stencil_read_mask",UINT(dd.StencilReadMask));j.num("stencil_write_mask",UINT(dd.StencilWriteMask));
        j.num("front_stencil_func",dd.FrontFace.StencilFunc);j.num("back_stencil_func",dd.BackFace.StencilFunc);
        j.num("depth_attachment",depth?1:0);
        ComPtr<ID3D11RasterizerState> rs;ctx->RSGetState(&rs);D3D11_RASTERIZER_DESC rd={};if(rs)rs->GetDesc(&rd);else{rd.CullMode=D3D11_CULL_BACK;rd.FillMode=D3D11_FILL_SOLID;rd.DepthClipEnable=TRUE;}
        j.num("cull_mode",rd.CullMode);j.num("front_ccw",rd.FrontCounterClockwise);j.num("scissor_enabled",rd.ScissorEnable);j.num("depth_clip",rd.DepthClipEnable);
        UINT n=16;D3D11_RECT scissors[16];ctx->RSGetScissorRects(&n,scissors);std::vector<std::string> rects;
        for(UINT i=0;i<n;++i)rects.push_back(array({number(scissors[i].left),number(scissors[i].top),number(scissors[i].right),number(scissors[i].bottom)}));j.fields["scissors"]=array(rects);
        n=16;D3D11_VIEWPORT vp[16];ctx->RSGetViewports(&n,vp);rects.clear();for(UINT i=0;i<n;++i)rects.push_back(array({number(vp[i].TopLeftX),number(vp[i].TopLeftY),number(vp[i].Width),number(vp[i].Height),number(vp[i].MinDepth),number(vp[i].MaxDepth)}));j.fields["viewports"]=array(rects);
        ComPtr<ID3D11Predicate> predicate;BOOL predicateValue;ctx->GetPredication(&predicate,&predicateValue);j.num("predication_bound",predicate?1:0);j.num("predicate_value",predicateValue);
        if(mode==Mode::probe){
            ComPtr<ID3D11SamplerState> sampler;ctx->PSGetSamplers(0,1,&sampler);Json state;
            if(sampler){D3D11_SAMPLER_DESC sd;sampler->GetDesc(&sd);state.num("filter",sd.Filter);state.num("address_u",sd.AddressU);state.num("address_v",sd.AddressV);state.num("address_w",sd.AddressW);state.num("min_lod",sd.MinLOD);state.num("max_lod",sd.MaxLOD);state.num("mip_lod_bias",sd.MipLODBias);state.num("max_anisotropy",sd.MaxAnisotropy);state.num("comparison",sd.ComparisonFunc);}
            else state.text("status","null_default_sampler");j.fields["sampler0"]=state.str();
        }
        ComPtr<ID3D11Device> device;ctx->GetDevice(&device);D3D11_QUERY_DESC q={D3D11_QUERY_OCCLUSION,0};check(device->CreateQuery(&q,&entry.query));
        internal=true;
        bool replaced=false;
        try {
            if(mode==Mode::probe)capture_inputs(ctx,entry);
            if(!entry.images.empty())copy(ctx,entry.images[0]);
            ctx->Begin(entry.query.Get());
            try{replaced=call();}catch(...){ctx->End(entry.query.Get());throw;}
            ctx->End(entry.query.Get());
            if(entry.images.size()>1)copy(ctx,entry.images[1]);
            internal=false;
        }catch(...){internal=false;throw;}
        j.num("replacement_executed",replaced?1:0);entries.push_back(std::move(entry));return replaced;
    }
    void present(ID3D11DeviceContext *ctx,ID3D11Texture2D *backbuffer) {
        if(!active())return;
        if(recording){
            internal=true;
            try{
                for(auto &e:entries)if(e.images.size()>2)copy(ctx,e.images[2]);
                final_image=prepare(ctx,backbuffer,0,DXGI_FORMAT_UNKNOWN,"present-backbuffer");copy(ctx,final_image);
                ComPtr<ID3D11Device> device;ctx->GetDevice(&device);D3D11_QUERY_DESC q={D3D11_QUERY_EVENT,0};check(device->CreateQuery(&q,&done));ctx->End(done.Get());
                internal=false;
            }catch(...){internal=false;throw;}
            recording=false;if(tracker)tracker->set_enabled(false);waiting=true;started=GetTickCount64();return;
        }
        BOOL ready=FALSE;HRESULT hr=ctx->GetData(done.Get(),&ready,sizeof(ready),D3D11_ASYNC_GETDATA_DONOTFLUSH);check(hr);
        if(hr==S_OK && ready){write_report(ctx,"complete");cancel();}
        else if(GetTickCount64()-started>10000){write_report(ctx,"gpu_timeout");cancel();}
    }
};
}
