// 415a922293923fa4: use the host's view-position and encoded world-normal
// inputs; add diffuse light before native AO/material/ambient/output encoding.
cbuffer Common : register(b0) { float4 common[1]; }
cbuffer Camera : register(b1) { float4 camera[3]; }
Texture2D<float4> viewPositionTexture : register(t10);
Texture2D<float4> normalTexture : register(t5);
SamplerState positionSampler : register(s9);
SamplerState normalSampler : register(s4);
#ifdef SINGLE_LIGHT_BAKED
#include "single_light_parameters.h"
#else
// Offline only; game candidate bakes controls, never binds b13.
cbuffer SingleLight : register(b13) { float4 lampPositionRange; float4 lampColorIntensity; }
#endif

float4 main(float4 pixel : SV_POSITION) : SV_TARGET
{
    float2 uv=pixel.xy*common[0].xy+common[0].zw;
    float3 position=viewPositionTexture.SampleLevel(positionSampler,uv,0).xyz;
    float3 encoded=normalTexture.SampleLevel(normalSampler,uv,0).xyz-.5;
    float3 normal=float3(dot(camera[0].xyz,encoded),dot(camera[1].xyz,encoded),dot(camera[2].xyz,encoded));
    float lengthSquared=dot(normal,normal);
    normal*=rsqrt(max(lengthSquared,1e-8));
    float3 delta=lampPositionRange.xyz-position;
    float distanceSquared=dot(delta,delta);
    float3 direction=delta*rsqrt(max(distanceSquared,1e-8));
    float cutoff=saturate(1-distanceSquared/max(lampPositionRange.w*lampPositionRange.w,1e-8));
    float attenuation=cutoff*cutoff/(1+distanceSquared);
    float diffuse=saturate(dot(normal,direction))/3.141592653589793;
    float3 rgb=max(lampColorIntensity.xyz,0)*max(lampColorIntensity.w,0)*diffuse*attenuation;
    // Zero view position is treated as invalid background in this prototype;
    // actual host coverage/stencil still needs in-game evidence.
    bool valid=dot(position,position)>1e-8 && all(abs(position)<1e20) &&
               lengthSquared>1e-8 && lengthSquared<1e20 && all(abs(rgb)<1e20);
    return float4(valid?rgb:float3(0,0,0),0);
}
