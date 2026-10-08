// Offline input signatures are remapped by the audited ASM inserter to the
// host's final tangent-space-normal result r1 and view-position varying v6.
#ifdef SINGLE_LIGHT_BAKED
#include "single_light_parameters.h"
#else
cbuffer SingleLight : register(b13) { float4 lampPositionRange; float4 lampColorIntensity; }
#endif
float4 main(float3 normal : COLOR0, float3 position : TEXCOORD0) : SV_TARGET
{
    float n2=dot(normal,normal);
    normal*=rsqrt(max(n2,1e-8));
    float3 delta=lampPositionRange.xyz-position;
    float d2=dot(delta,delta);
    float cutoff=saturate(1-d2/max(lampPositionRange.w*lampPositionRange.w,1e-8));
    float diffuse=saturate(dot(normal,delta*rsqrt(max(d2,1e-8))))/3.141592653589793;
    float3 rgb=max(lampColorIntensity.xyz,0)*max(lampColorIntensity.w,0)*diffuse*cutoff*cutoff/(1+d2);
    bool valid=n2>1e-8 && n2<1e20 && dot(position,position)>1e-8 && all(abs(position)<1e20) && all(abs(rgb)<1e20);
    return float4(valid?rgb:float3(0,0,0),0);
}
