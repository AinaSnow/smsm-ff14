#pragma once
#include "diagnostic.hpp"

namespace smsm {
// Opt-in experiment. The caller must identify the exact source/consumer PS.
class AmbientBridge {
    struct Binding {
        ComPtr<ID3D11Buffer> buffer;
        UINT first=0,count=4096;
    };
    ComPtr<ID3D11PixelShader> candidate;
    ComPtr<ID3D11Buffer> control,region_copy;
    ComPtr<ID3D11ShaderResourceView> region_view;
    Binding camera;
    uint64_t source_id=0;
    UINT region_bytes=0;
    bool ready=false,attempted=false;
    float strength=0;
    static Binding binding(ID3D11DeviceContext *ctx,UINT slot) {
        Binding b;ComPtr<ID3D11DeviceContext1> ctx1;ctx->QueryInterface(IID_PPV_ARGS(&ctx1));
        if(ctx1)ctx1->PSGetConstantBuffers1(slot,1,&b.buffer,&b.first,&b.count);
        else ctx->PSGetConstantBuffers(slot,1,&b.buffer);
        return b;
    }
public:
    bool internal=false;
    uint64_t copies=0,overrides=0,fallbacks=0;
    bool enabled() const {return strength>0 && candidate;}
    void disable() {strength=0;reset_frame();}
    void initialize(ID3D11Device *device,const void *bytes,size_t size) {
        ComPtr<ID3D11PixelShader> shader;ComPtr<ID3D11Buffer> controls;
        check(device->CreatePixelShader(bytes,size,nullptr,&shader));
        D3D11_BUFFER_DESC desc={};desc.ByteWidth=16;desc.BindFlags=D3D11_BIND_CONSTANT_BUFFER;desc.Usage=D3D11_USAGE_DEFAULT;
        float zero[4]={};D3D11_SUBRESOURCE_DATA data={zero,0,0};
        check(device->CreateBuffer(&desc,&data,&controls));candidate=shader;control=controls;
    }
    void set_strength(ID3D11DeviceContext *ctx,float value) {
        if(!(value>=0 && value<=1))throw std::runtime_error("Invalid ambient strength");
        if(!candidate || !control)throw std::runtime_error("Ambient experiment is not initialized");
        reset_frame();float values[4]={value,0,0,0};ctx->UpdateSubresource(control.Get(),0,nullptr,values,0,0);strength=value;
    }
    void reset_frame() {ready=false;attempted=false;source_id=0;camera={};}
    void invalidate() {ready=false;}
    void note_write(uint64_t resource) {
        if(resource && (resource==source_id || resource==reinterpret_cast<uint64_t>(camera.buffer.Get())))ready=false;
    }
    bool capture_source(ID3D11DeviceContext *ctx) {
        if(!enabled() || internal || ctx->GetType()!=D3D11_DEVICE_CONTEXT_IMMEDIATE)return false;
        if(attempted)return ready;
        attempted=true;ready=false;
        auto source=binding(ctx,2);camera=binding(ctx,1);
        if(!source.buffer || !camera.buffer)return false;
        D3D11_BUFFER_DESC desc;source.buffer->GetDesc(&desc);
        const uint64_t start=uint64_t(source.first)*16;
        const uint64_t length=start<desc.ByteWidth ? std::min<uint64_t>(desc.ByteWidth-start,uint64_t(source.count)*16) : 0;
        if(length<256 || length>65536 || length%16)return false;
        if(!region_copy || region_bytes!=length) {
            ComPtr<ID3D11Device> device;ctx->GetDevice(&device);
            region_view.Reset();region_copy.Reset();
            D3D11_BUFFER_DESC dest={};dest.ByteWidth=UINT(length);dest.Usage=D3D11_USAGE_DEFAULT;
            dest.BindFlags=D3D11_BIND_SHADER_RESOURCE;dest.MiscFlags=D3D11_RESOURCE_MISC_BUFFER_STRUCTURED;dest.StructureByteStride=16;
            check(device->CreateBuffer(&dest,nullptr,&region_copy));
            D3D11_SHADER_RESOURCE_VIEW_DESC view={};view.Format=DXGI_FORMAT_UNKNOWN;view.ViewDimension=D3D11_SRV_DIMENSION_BUFFER;view.Buffer.NumElements=UINT(length/16);
            check(device->CreateShaderResourceView(region_copy.Get(),&view,&region_view));region_bytes=UINT(length);
        }
        D3D11_BOX box={UINT(start),0,0,UINT(start+length),1,1};
        ctx->CopySubresourceRegion(region_copy.Get(),0,0,0,0,source.buffer.Get(),0,&box);
        source_id=reinterpret_cast<uint64_t>(source.buffer.Get());ready=true;++copies;return true;
    }
    template<class DrawCall> bool draw(ID3D11DeviceContext *ctx,DrawCall call) {
        if(!enabled() || internal || ctx->GetType()!=D3D11_DEVICE_CONTEXT_IMMEDIATE)return false;
        auto now=binding(ctx,3);
        if(!ready || !now.buffer || now.buffer.Get()!=camera.buffer.Get() || now.first!=camera.first || now.count!=camera.count) {++fallbacks;return false;}
        ComPtr<ID3D11PixelShader> old_shader;
        ID3D11ClassInstance *instances[256]={};UINT classes=256;
        ctx->PSGetShader(&old_shader,instances,&classes);
        for(UINT i=0;i<classes && i<256;++i)if(instances[i])instances[i]->Release();
        if(classes) {++fallbacks;return false;}
        ComPtr<ID3D11ShaderResourceView> old_view;ctx->PSGetShaderResources(12,1,&old_view);
        auto old_control=binding(ctx,8);
        ComPtr<ID3D11DeviceContext1> ctx1;ctx->QueryInterface(IID_PPV_ARGS(&ctx1));
        auto restore=[&]() {
            ctx->PSSetShader(old_shader.Get(),nullptr,0);
            auto *v=old_view.Get();ctx->PSSetShaderResources(12,1,&v);
            auto *b=old_control.buffer.Get();
            if(ctx1 && b)ctx1->PSSetConstantBuffers1(8,1,&b,&old_control.first,&old_control.count);
            else ctx->PSSetConstantBuffers(8,1,&b);
            internal=false;
        };
        internal=true;
        auto *v=region_view.Get();ctx->PSSetShaderResources(12,1,&v);
        auto *b=control.Get();ctx->PSSetConstantBuffers(8,1,&b);ctx->PSSetShader(candidate.Get(),nullptr,0);
        try {call();} catch(...) {restore();throw;}
        restore();++overrides;return true;
    }
};
}
