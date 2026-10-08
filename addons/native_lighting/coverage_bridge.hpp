#pragma once
#include "diagnostic.hpp"

namespace smsm {
// Diagnostic marker only. Does not require or change ambient resources/camera.
class CoverageBridge {
    ComPtr<ID3D11PixelShader> marker;
    uint64_t deadline=0;
public:
    bool internal=false;
    uint64_t draws=0,fallbacks=0;
    bool available() const {return marker!=nullptr;}
    bool enabled() const {return deadline!=0;}
    void disable() {deadline=0;}
    void initialize(ID3D11Device *device,const void *bytes,size_t size) {
        check(device->CreatePixelShader(bytes,size,nullptr,&marker));
    }
    void enable(uint64_t now) {
        if(!marker)throw std::runtime_error("Coverage marker not built into this package");
        deadline=now+10000;
    }
    bool expire(uint64_t now) {
        if(deadline && now>=deadline){disable();return true;}return false;
    }
    template<class F> bool draw(ID3D11DeviceContext *ctx,uint64_t now,F call) {
        if(!enabled() || now>=deadline || internal || ctx->GetType()!=D3D11_DEVICE_CONTEXT_IMMEDIATE)return false;
        ComPtr<ID3D11PixelShader> original;
        ID3D11ClassInstance *instances[256]={};UINT classes=256;
        ctx->PSGetShader(&original,instances,&classes);
        for(UINT i=0;i<classes && i<256;++i)if(instances[i])instances[i]->Release();
        if(classes){++fallbacks;return false;}
        internal=true;ctx->PSSetShader(marker.Get(),nullptr,0);
        auto restore=[&]{ctx->PSSetShader(original.Get(),nullptr,0);internal=false;};
        try{call();}catch(...){restore();throw;}
        restore();++draws;return true;
    }
};
}
