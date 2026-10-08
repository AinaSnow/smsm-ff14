// OFFLINE ONLY. b12 supplies projection/viewport/inverse projection; b13 lamp.
// Existing mesh t2 depth, t4 encoded normal, s0 and b3 are explicitly supplied
// by synthetic fixtures. Their live values/projection are not yet verified.
#define main unshadowedMeshLight
#include "forward_material_light.hlsl"
#undef main
cbuffer Visibility : register(b12) {
    float4 visibilitySettings;
    float4 projectionRows[4];
    float4 ndcToUV;
    float4 inverseProjectionRows[4];
}
cbuffer Camera : register(b3) { float4 camera[3]; }
Texture2D<float4> sceneDepth : register(t2);
Texture2D<float4> sceneNormal : register(t4);
SamplerState sceneSampler : register(s0);
float3 visiblePosition(float2 uv, out bool valid)
{
    uint width,height;sceneDepth.GetDimensions(width,height);
    // Point depth belongs to the selected texel center, not the march ray UV.
    float2 size=float2(width,height);
    float2 center=(clamp(floor(uv*size),0,size-1)+.5)/size;
    float z=sceneDepth.SampleLevel(sceneSampler,center,0).x;
    float2 ndc=(center-ndcToUV.zw)/ndcToUV.xy;
    float4 p=float4(ndc,z,1);
    float4 h=float4(dot(inverseProjectionRows[0],p),dot(inverseProjectionRows[1],p),
                    dot(inverseProjectionRows[2],p),dot(inverseProjectionRows[3],p));
    valid=z>0 && z<1 && abs(h.w)>1e-8 && all(abs(h)<1e20);
    float3 result=h.xyz/(valid?h.w:1);
    valid=valid && dot(result,result)>1e-8 && all(abs(result)<1e20);
    return result;
}
float3 visibleNormal(float2 uv, out bool valid)
{
    float3 encoded=sceneNormal.SampleLevel(sceneSampler,uv,0).xyz-.5;
    float3 n=float3(dot(camera[0].xyz,encoded),dot(camera[1].xyz,encoded),dot(camera[2].xyz,encoded));
    float n2=dot(n,n);valid=n2>1e-8 && n2<1e20;
    return n*rsqrt(max(n2,1e-8));
}
#include "visibility_march.hlsl"
float4 main(float3 normal:COLOR0,float3 position:TEXCOORD0):SV_TARGET
{
    float4 lamp=unshadowedMeshLight(normal,position);
    bool valid=dot(position,position)>1e-8 && all(abs(position)<1e20);
    float supported=valid?1:0,visibility=1;
    if(visibilitySettings.x>0 && valid)visibility=materialVisibility(position,supported);
#if MATERIAL_VISIBILITY_AUDIT
    return float4(visibility,supported,valid?1:0,0);
#else
    return float4(lamp.xyz*visibility,0);
#endif
}
