// Helper compiled and inserted into reviewed directional-light shaders.
// Register layouts are from client 2026.09.15, not the pre-Dawntrail G-buffer.
cbuffer Common : register(b0) { float4 common[2]; }
cbuffer Camera : register(b1) { float4 camera[18]; }
cbuffer Light : register(b2) { float4 light[25]; }
Texture2D<float4> depthTexture : register(t0);
Texture2D<float4> normalTexture : register(t3);
SamplerState depthSampler : register(s0);
SamplerState normalSampler : register(s2);

float3 viewPosition(float2 pixel)
{
    float2 uv = pixel * common[0].xy + common[0].zw;
    float depth = max(depthTexture.SampleLevel(depthSampler, uv, 0).x, 0.000001);
    float4 clip = float4(pixel * common[1].xy + common[1].zw, depth, 1);
    return float3(dot(camera[14], clip), dot(camera[15], clip), dot(camera[16], clip)) / dot(camera[17], clip);
}

float3 viewNormal(float2 pixel)
{
    float2 uv = pixel * common[0].xy + common[0].zw;
    float3 n = normalTexture.SampleLevel(normalSampler, uv, 0).xyz - 0.5;
    float3 transformed = float3(dot(camera[0].xyz, n), dot(camera[1].xyz, n), dot(camera[2].xyz, n));
    return transformed * rsqrt(max(dot(transformed, transformed), 1e-8));
}

float4 main(float4 pixel : SV_POSITION) : SV_TARGET
{
    float3 lightDirection = light[1].xyz;
    float ndotl = dot(viewNormal(pixel.xy), lightDirection);
    float pixelDepth = length(viewPosition(pixel.xy));
    // Same projected 64-pixel trace extent as the legacy normal-shadow effect.
    float2 direction = float2(dot(lightDirection, float3(light[20].x, light[21].x, light[22].x)),
                              -dot(lightDirection, float3(light[20].y, light[21].y, light[22].y))) * 64;
    float noise = frac(52.9829189 * frac(dot(pixel.xy, float2(0.06711056, 0.00583715))));
    float slope = -ndotl, maxSlope = 0, shadow = 0;
    [loop] for (int i = 0; i < 24; ++i) {
        float distance = (i + 1 - noise) / 24;
        float2 samplePixel = pixel.xy + direction * distance;
        float2 ndc = samplePixel * common[1].xy + common[1].zw;
        // Discard samples outside the active viewport rather than clamp to edges.
        if (ndotl > 0 && all(abs(ndc) <= 1)) {
            float delta = pixelDepth - length(viewPosition(samplePixel));
            float2 depthWeight = saturate(1 - delta * float2(4, -6));
            slope -= dot(viewNormal(samplePixel), lightDirection) * depthWeight.x * depthWeight.y;
            if (slope > maxSlope) shadow += 64 * 0.4 * (1 - distance);
            maxSlope = max(maxSlope, slope);
        }
    }
    // The current shader squares its shadow mask later, so return sqrt visibility.
    return sqrt(saturate(1 - shadow / 24));
}
