// View-space point-light prototype. Resource layout audited against the two
// 2026.09.15 directional-light variants. Diffuse irradiance only, no albedo guess.
cbuffer Common : register(b0) { float4 common[2]; }
cbuffer Camera : register(b1) { float4 camera[18]; }
Texture2D<float4> depthTexture : register(t0);
Texture2D<float4> normalTexture : register(t3);
SamplerState depthSampler : register(s0);
SamplerState normalSampler : register(s2);

#ifdef SINGLE_LIGHT_BAKED
#include "single_light_parameters.h"
#else
// Offline per-frame control only. Game package bakes these into instructions;
// it does NOT bind a new runtime constant buffer or use r5's t120.y mechanism.
cbuffer SingleLight : register(b13) {
    float4 lampPositionRange; // view-space xyz, range in view-space units
    float4 lampColorIntensity; // linear RGB, scalar intensity
}
#endif

float3 reconstructPosition(float2 pixel, out float valid)
{
    float2 uv = pixel * common[0].xy + common[0].zw;
    float d = depthTexture.SampleLevel(depthSampler, uv, 0).x;
    float4 clip = float4(pixel * common[1].xy + common[1].zw, max(d, 0.000001), 1);
    float4 h = float4(dot(camera[14], clip), dot(camera[15], clip),
                      dot(camera[16], clip), dot(camera[17], clip));
    valid = (d > 0 && d < 1 && abs(h.w) > 1e-8 && all(abs(h) < 1e20)) ? 1 : 0;
    float w = abs(h.w) > 1e-8 ? h.w : 1;
    return h.xyz / w;
}

float3 reconstructNormal(float2 pixel, out float valid)
{
    float2 uv = pixel * common[0].xy + common[0].zw;
    float3 encoded = normalTexture.SampleLevel(normalSampler, uv, 0).xyz - 0.5;
    float3 n = float3(dot(camera[0].xyz, encoded), dot(camera[1].xyz, encoded), dot(camera[2].xyz, encoded));
    float square = dot(n, n);
    valid = (square > 1e-8 && square < 1e20) ? 1 : 0;
    return n * rsqrt(max(square, 1e-8));
}

float4 main(float4 pixel : SV_POSITION) : SV_TARGET
{
    float positionValid, normalValid;
    float3 position = reconstructPosition(pixel.xy, positionValid);
    float3 normal = reconstructNormal(pixel.xy, normalValid);
#if SINGLE_LIGHT_AUDIT_MODE == 1
    return float4(position, positionValid);
#elif SINGLE_LIGHT_AUDIT_MODE == 2
    return float4(normal, normalValid);
#else
    float3 toLight = lampPositionRange.xyz - position;
    float distanceSquared = dot(toLight, toLight);
    float3 direction = toLight * rsqrt(max(distanceSquared, 1e-8));
    float rangeSquared = max(lampPositionRange.w * lampPositionRange.w, 1e-8);
    float cutoff = saturate(1 - distanceSquared / rangeSquared);
    // Finite at the source; C1 cutoff at the range. This is an artistic bounded
    // attenuation model, not calibrated photometric units or a shadow solver.
    float attenuation = cutoff * cutoff / (1 + distanceSquared);
    float diffuse = saturate(dot(normal, direction)) * (1.0 / 3.141592653589793);
    float valid = positionValid * normalValid;
    float3 rgb = max(lampColorIntensity.xyz, 0) * max(lampColorIntensity.w, 0) * diffuse * attenuation;
    // Conditional selection prevents invalid G-buffer NaNs from entering output.
    return float4(valid > 0 && all(abs(rgb) < 1e20) ? rgb : float3(0, 0, 0), 0);
#endif
}
