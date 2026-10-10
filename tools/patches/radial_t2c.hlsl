// Radial blur / light shafts, client build 2026.09.15.0000.0000.
// T2c: w7 (Ctrl+F5) switches between the SMSM 8-tap jittered blur (r10 port of
// 0fed9c59a976fd24) and the game's own 4-tap loop, reproduced from 91f970e6bbe57d99.
cbuffer cDynamicViewportResolutionParam : register(b0)
{
    float4 cDynamicViewportResolutionParam[2] : packoffset(c0);
}
cbuffer cRadialBlurParam : register(b1)
{
    float4 cRadialBlurParam : packoffset(c0);
}
SamplerState sInputSampler : register(s0);
Texture2D<float4> sInputTex : register(t0);
Texture1D<float4> IniParams : register(t120);

#include "Common.h"

float2 ViewportUv(float2 uv)
{
    return min(saturate(uv) * cDynamicViewportResolutionParam[0].xy, cDynamicViewportResolutionParam[0].zw);
}

void main(float4 position : SV_POSITION0, float2 uv : TEXCOORD0,
          out float4 output : SV_TARGET0)
{
    float2 delta = cRadialBlurParam.xy - uv;
    float4 sum = 0;
    float weightSum = 0;
    if (IniParams.Load(int2(7, 0)).w > 0.5)
    {
        // SMSM: 8 taps; the legacy scalar jitter keeps its x component explicitly.
        const int sampleCount = 8;
        float jitter = clamp(interleaved_gradient(position.yx) * delta.x, -1.0, 1.0);
        [unroll]
        for (int i = 0; i < sampleCount; ++i)
        {
            float spread = cRadialBlurParam.w * (i + jitter) / (sampleCount - 1);
            float weight = 1.0 - cRadialBlurParam.z * i / sampleCount;
            sum += sInputTex.Sample(sInputSampler, ViewportUv(uv + delta * spread)) * weight;
            weightSum += weight;
        }
    }
    else
    {
        // Game: 4 taps, spread w*i/3, weight 1 - z*i/4.
        [loop]
        for (int i = 0; i < 4; ++i)
        {
            float spread = cRadialBlurParam.w * i * 0.333333;
            float weight = 1.0 - cRadialBlurParam.z * i * 0.25;
            sum += sInputTex.Sample(sInputSampler, ViewportUv(uv + delta * spread)) * weight;
            weightSum += weight;
        }
    }
    output = sum / weightSum;
}
