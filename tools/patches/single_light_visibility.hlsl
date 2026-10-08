// OFFLINE RESEARCH ONLY. Not included in the game package builder.
// b12 is a controlled test buffer, not an audited FF14 runtime binding.
#define main unshadowedLightMain
#include "single_light.hlsl"
#undef main
cbuffer Visibility : register(b12) {
    // enable, view-space depth bias, assumed surface thickness, sample count
    float4 visibilitySettings;
}

float minor3(float3 a, float3 b, float3 c) { return dot(a, cross(b, c)); }
float4 cofactorRow(float4 a, float4 b, float4 c) {
    return float4(minor3(a.yzw,b.yzw,c.yzw), -minor3(a.xzw,b.xzw,c.xzw),
                  minor3(a.xyw,b.xyw,c.xyw), -minor3(a.xyz,b.xyz,c.xyz));
}

float screenVisibility(float3 position, out float supported)
{
    // Invert the audited inverse-projection rows. No guessed camera matrix
    // slots; determinant validity is explicit for malformed projection input.
    float4 a=camera[14], b=camera[15], c=camera[16], d=camera[17];
    float4 ca=cofactorRow(b,c,d), cb=-cofactorRow(a,c,d);
    float4 cc=cofactorRow(a,b,d), cd=-cofactorRow(a,b,c);
    float determinant=dot(a,ca);
    supported=abs(determinant)>1e-12 && abs(determinant)<1e20;
    float visibility=1;
    uint count=(uint)clamp(visibilitySettings.w,1,128);
    // Fixed sampling has known thin-occluder and discontinuity failure modes.
    // No temporal filtering, edge extrapolation or offscreen reconstruction.
    [loop] for (uint i=1; i<=count && supported>0 && visibility>0; ++i) {
        float t=(float)i/((float)count+1);
        float3 q=lerp(position,lampPositionRange.xyz,t);
        float4 h=(ca*q.x+cb*q.y+cc*q.z+cd)/determinant;
        bool valid=abs(h.w)>1e-8 && all(abs(h)<1e20);
        float3 ndc=h.xyz/(valid?h.w:1);
        float2 pixel=(ndc.xy-common[1].zw)/common[1].xy;
        float2 uv=pixel*common[0].xy+common[0].zw;
        valid=valid && all(abs(ndc.xy)<1) && ndc.z>0 && ndc.z<1 && all(uv>0) && all(uv<1);
        if (!valid) { supported=0; }
        else {
            float sceneValid;
            float3 scene=reconstructPosition(pixel,sceneValid);
            // The depth buffer describes the closest surface only. Thickness
            // is a tunable assumption, not recovered back-face geometry.
            float gap=abs(q.z)-abs(scene.z);
            if (sceneValid>0 && gap>max(visibilitySettings.y,0) && gap<max(visibilitySettings.z,0)) {
#if VISIBILITY_PLANE_REFINE
                // Candidate thickness only finds a neighborhood. Re-test the
                // ray against its local tangent plane instead of shadowing an
                // entire artificial slab. Then verify depth at the hit itself.
                float nValid;
                float3 n=reconstructNormal(pixel,nValid);
                float3 segment=lampPositionRange.xyz-position;
                float denom=dot(n,segment);
                float hitT=dot(n,scene-position)/(abs(denom)>1e-8?denom:1);
                float3 hit=position+hitT*segment;
                float4 hitH=(ca*hit.x+cb*hit.y+cc*hit.z+cd)/determinant;
                bool hitValid=abs(hitH.w)>1e-8 && all(abs(hitH)<1e20);
                float3 hitNdc=hitH.xyz/(hitValid?hitH.w:1);
                float2 hitPixel=(hitNdc.xy-common[1].zw)/common[1].xy;
                float2 hitUV=hitPixel*common[0].xy+common[0].zw;
                hitValid=hitValid && all(abs(hitNdc.xy)<1) && hitNdc.z>0 && hitNdc.z<1 && all(hitUV>0) && all(hitUV<1);
                if (nValid>0 && abs(denom)>1e-8 && hitT>0 && hitT<1 &&
                    length(hit-position)>max(visibilitySettings.y,0.0001) && hitValid) {
                    float verifyValid;
                    float3 verify=reconstructPosition(hitPixel,verifyValid);
                    if (verifyValid>0 && abs(verify.z-hit.z)<=max(visibilitySettings.y,0.0001))
                        visibility=0;
                }
#else
                visibility=0;
#endif
            }
        }
    }
    // A confirmed hit terminates the ray before any offscreen fallback.
    // Unknown rays fall back to unshadowed lighting. This deliberately exposes
    // offscreen leaks instead of inventing dark borders; diagnostics flag them.
    return supported>0?visibility:1;
}

float4 main(float4 pixel : SV_POSITION) : SV_TARGET
{
    float4 light=unshadowedLightMain(pixel);
    float valid, supported=1;
    float3 position=reconstructPosition(pixel.xy,valid);
    float visibility=1;
    if (visibilitySettings.x>0 && valid>0)
        visibility=screenVisibility(position,supported);
#if VISIBILITY_AUDIT
    return float4(visibility,supported,valid,0);
#else
    return float4(light.xyz*visibility,light.w);
#endif
}
