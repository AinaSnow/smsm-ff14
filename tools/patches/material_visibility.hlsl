// OFFLINE ONLY: b12 supplies a synthetic projection/viewport, not a game binding.
// Produces an input texture for native material composition; not a game patch.
#define main unshadowedMaterialLight
#include "material_light.hlsl"
#undef main
cbuffer Visibility : register(b12) {
    float4 visibilitySettings; // enable, bias, assumed thickness, step count
    float4 projectionRows[4];
    float4 ndcToUV; // viewport-to-texture scale.xy / offset.zw
}
Texture2D<float4> diffuseInput : register(t3);
SamplerState diffuseSampler : register(s2);

float3 visiblePosition(float2 uv, out bool valid)
{
    float3 p=viewPositionTexture.SampleLevel(positionSampler,uv,0).xyz;
    valid=dot(p,p)>1e-8 && all(abs(p)<1e20);
    return p;
}
float3 visibleNormal(float2 uv, out bool valid)
{
    float3 encoded=normalTexture.SampleLevel(normalSampler,uv,0).xyz-.5;
    float3 n=float3(dot(camera[0].xyz,encoded),dot(camera[1].xyz,encoded),dot(camera[2].xyz,encoded));
    float n2=dot(n,n);valid=n2>1e-8 && n2<1e20;
    return n*rsqrt(max(n2,1e-8));
}
#include "visibility_march.hlsl"
float4 main(float4 pixel:SV_POSITION):SV_TARGET
{
    float2 uv=pixel.xy*common[0].xy+common[0].zw;
    float4 lamp=unshadowedMaterialLight(pixel);
    bool valid;float3 p=visiblePosition(uv,valid);
    float supported=valid?1:0, visibility=1;
    if(visibilitySettings.x>0 && valid) visibility=materialVisibility(p,supported);
#if MATERIAL_VISIBILITY_AUDIT
    return float4(visibility,supported,valid?1:0,0);
#elif MATERIAL_VISIBILITY_ADD_ONLY
    // Offline fused harness inserts this contribution at the native t3 read.
    return float4(lamp.xyz*visibility,0);
#else
    float4 base=diffuseInput.SampleLevel(diffuseSampler,uv,0);
    return float4(base.xyz+lamp.xyz*visibility,base.w);
#endif
}
