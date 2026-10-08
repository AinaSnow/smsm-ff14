#include "ambient_bridge.hpp"
#include <d3dcompiler.h>
#include <iostream>
using namespace smsm;
void require(bool ok,const char *message){if(!ok)throw std::runtime_error(message);}
ComPtr<ID3DBlob> compile(const char *text,const char *profile){
    ComPtr<ID3DBlob> result,error;check(D3DCompile(text,strlen(text),nullptr,nullptr,nullptr,"main",profile,0,0,&result,&error));return result;
}
int main(){try{
    wchar_t sys[MAX_PATH];GetSystemDirectoryW(sys,MAX_PATH);auto library=LoadLibraryW((fs::path(sys)/"d3d11.dll").c_str());
    auto create=reinterpret_cast<decltype(&D3D11CreateDevice)>(GetProcAddress(library,"D3D11CreateDevice"));
    ComPtr<ID3D11Device> device;ComPtr<ID3D11DeviceContext> ctx;check(create(nullptr,D3D_DRIVER_TYPE_WARP,nullptr,0,nullptr,0,7,&device,nullptr,&ctx));
    ComPtr<ID3D11DeviceContext1> ctx1;check(ctx.As(&ctx1));
    auto vertex=compile("float4 main(uint id:SV_VertexID):SV_Position{float2 p=float2((id<<1)&2,id&2);return float4(p*float2(2,-2)+float2(-1,1),0,1);}","vs_5_0");
    auto original=compile("float4 main():SV_Target{return float4(.25,.5,.75,1);}","ps_5_0");
    auto candidate=compile("StructuredBuffer<uint4> r:register(t12);cbuffer C:register(b8){float4 c;}cbuffer Camera:register(b3){float4 cam;}float4 main():SV_Target{return float4(r[0].x/255.0,c.x,cam.x,1);}","ps_5_0");
    ComPtr<ID3D11VertexShader> vs;ComPtr<ID3D11PixelShader> ps;
    check(device->CreateVertexShader(vertex->GetBufferPointer(),vertex->GetBufferSize(),nullptr,&vs));
    check(device->CreatePixelShader(original->GetBufferPointer(),original->GetBufferSize(),nullptr,&ps));
    ctx->VSSetShader(vs.Get(),nullptr,0);ctx->PSSetShader(ps.Get(),nullptr,0);ctx->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    D3D11_VIEWPORT viewport={0,0,4,4,0,1};ctx->RSSetViewports(1,&viewport);
    D3D11_TEXTURE2D_DESC td={};td.Width=td.Height=4;td.ArraySize=td.MipLevels=1;td.Format=DXGI_FORMAT_R32G32B32A32_FLOAT;td.SampleDesc.Count=1;td.BindFlags=D3D11_BIND_RENDER_TARGET;
    ComPtr<ID3D11Texture2D> output,staging;ComPtr<ID3D11RenderTargetView> rtv;
    check(device->CreateTexture2D(&td,nullptr,&output));check(device->CreateRenderTargetView(output.Get(),nullptr,&rtv));
    auto *rt=rtv.Get();ctx->OMSetRenderTargets(1,&rt,nullptr);
    td.BindFlags=0;td.Usage=D3D11_USAGE_STAGING;td.CPUAccessFlags=D3D11_CPU_ACCESS_READ;check(device->CreateTexture2D(&td,nullptr,&staging));
    auto buffer=[&](const void *data,UINT size){D3D11_BUFFER_DESC d={};d.ByteWidth=size;d.Usage=D3D11_USAGE_DEFAULT;d.BindFlags=D3D11_BIND_CONSTANT_BUFFER;D3D11_SUBRESOURCE_DATA s={data,0,0};ComPtr<ID3D11Buffer>b;check(device->CreateBuffer(&d,&s,&b));return b;};
    uint32_t regions[128]={};regions[64]=2;auto region=buffer(regions,sizeof(regions));
    float camera_data[128]={};camera_data[0]=.7f;auto camera=buffer(camera_data,sizeof(camera_data));
    auto wrong_camera=buffer(camera_data,sizeof(camera_data));auto old_control=buffer(camera_data,sizeof(camera_data));
    auto *b=region.Get();UINT first=16,count=16;ctx1->PSSetConstantBuffers1(2,1,&b,&first,&count);
    b=camera.Get();ctx->PSSetConstantBuffers(1,1,&b);ctx->PSSetConstantBuffers(3,1,&b);
    b=old_control.Get();ctx1->PSSetConstantBuffers1(8,1,&b,&first,&count);
    AmbientBridge bridge;bridge.initialize(device.Get(),candidate->GetBufferPointer(),candidate->GetBufferSize());
    require(!bridge.capture_source(ctx.Get()) && !bridge.draw(ctx.Get(),[&]{ctx->Draw(3,0);}),"default-off modified a draw");
    bridge.set_strength(ctx.Get(),.5f);require(bridge.capture_source(ctx.Get()),"source capture failed");
    require(bridge.draw(ctx.Get(),[&]{ctx->Draw(3,0);}),"matching camera did not override");
    ctx->CopyResource(staging.Get(),output.Get());D3D11_MAPPED_SUBRESOURCE mapped;check(ctx->Map(staging.Get(),0,D3D11_MAP_READ,0,&mapped));
    auto *pixel=static_cast<float*>(mapped.pData);require(std::abs(pixel[0]-2.f/255)<1e-7f && pixel[1]==.5f && pixel[2]==.7f,"ranged CB GPU copy/control/camera incorrect");ctx->Unmap(staging.Get(),0);
    ComPtr<ID3D11PixelShader> restored;ctx->PSGetShader(&restored,nullptr,nullptr);require(restored.Get()==ps.Get(),"PS not restored");
    ComPtr<ID3D11Buffer> restored_cb;UINT restored_first,restored_count;ctx1->PSGetConstantBuffers1(8,1,&restored_cb,&restored_first,&restored_count);
    require(restored_cb.Get()==old_control.Get() && restored_first==first && restored_count==count,"ranged CB not restored");
    ComPtr<ID3D11ShaderResourceView> restored_view;ctx->PSGetShaderResources(12,1,&restored_view);require(!restored_view,"SRV not restored");
    b=wrong_camera.Get();ctx->PSSetConstantBuffers(3,1,&b);require(!bridge.draw(ctx.Get(),[&]{throw std::runtime_error("wrong camera callback");}),"wrong camera accepted");
    b=camera.Get();ctx->PSSetConstantBuffers(3,1,&b);bridge.note_write(reinterpret_cast<uint64_t>(camera.Get()));
    require(!bridge.draw(ctx.Get(),[&]{throw std::runtime_error("changed camera callback");}),"camera write not invalidated");
    require(!bridge.capture_source(ctx.Get()),"recaptured within invalidated frame");
    bridge.reset_frame();require(!bridge.draw(ctx.Get(),[]{}),"old frame reused");require(bridge.capture_source(ctx.Get()),"new frame did not capture");
    bool caught=false;try{bridge.draw(ctx.Get(),[]{throw std::runtime_error("simulated draw failure");});}catch(...){caught=true;}
    require(caught && !bridge.internal,"exception left override active");ctx->PSGetShader(&restored,nullptr,nullptr);require(restored.Get()==ps.Get(),"exception did not restore PS");
    bridge.note_write(reinterpret_cast<uint64_t>(region.Get()));require(!bridge.draw(ctx.Get(),[]{}),"source mutation ignored");
    bridge.set_strength(ctx.Get(),0);require(!bridge.enabled(),"disable failed");
    std::cout<<"WARP bridge copy, camera guards, frame invalidation and state restoration passed\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
