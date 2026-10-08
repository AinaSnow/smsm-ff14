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

bool projectVisibility(float3 p, out float2 uv)
{
    float4 h=float4(dot(projectionRows[0],float4(p,1)),dot(projectionRows[1],float4(p,1)),
                    dot(projectionRows[2],float4(p,1)),dot(projectionRows[3],float4(p,1)));
    bool valid=abs(h.w)>1e-8 && all(abs(h)<1e20);
    float3 ndc=h.xyz/(valid?h.w:1);
    uv=ndc.xy*ndcToUV.xy+ndcToUV.zw;
    return valid && all(abs(ndc.xy)<1) && ndc.z>0 && ndc.z<1 && all(uv>0) && all(uv<1);
}
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
float materialVisibility(float3 p, out float supported)
{
    supported=1;
    uint count=(uint)clamp(visibilitySettings.w,1,128);
    float3 segment=lampPositionRange.xyz-p;
    [loop] for(uint i=1;i<=count;++i) {
        float3 q=p+segment*((float)i/((float)count+1));
        float2 uv;
        if(!projectVisibility(q,uv)) {supported=0;return 1;}
        bool sceneValid;float3 scene=visiblePosition(uv,sceneValid);
        // Invalid depth is missing information: explicitly flag the fallback.
        if(!sceneValid) {supported=0;return 1;}
        float gap=abs(q.z)-abs(scene.z);
        if(gap>max(visibilitySettings.y,0) && gap<max(visibilitySettings.z,0)) {
#if MATERIAL_PLANE_REFINE
            bool normalValid;float3 n=visibleNormal(uv,normalValid);
            float denom=dot(n,segment);
            float t=dot(n,scene-p)/(abs(denom)>1e-8?denom:1);
            float3 hit=p+t*segment;float2 hitUV;
            if(normalValid && abs(denom)>1e-8 && t>0 && t<1 &&
               length(hit-p)>max(visibilitySettings.y,.0001) && projectVisibility(hit,hitUV)) {
                bool verifyValid;float3 verify=visiblePosition(hitUV,verifyValid);
                if(verifyValid && abs(verify.z-hit.z)<=max(visibilitySettings.y,.0001)) return 0;
            }
#else
            return 0;
#endif
        }
    }
    return 1;
}
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
