// /gpose near/far aperture blur 00f2b6068017c6c6 (client 2026.09.15 / 2026.10.06), D0 + D1.
// The game's pass: 16 taps whose UVs come from the vertex shader, each weighted only by
// its own CoC (alpha) for its ring; it runs several times per frame, so lights end up as
// dim Gaussian-like blobs.
//   y6 (Ctrl+F2) D1 highlight bokeh: 0 off, 1 normal, 2 strong. Bright samples get more
//      weight in the colour average only; alpha (CoC / layer data) keeps the game weights,
//      so near/far separation and edges are unchanged.
//   z6 (Ctrl+F3) D0 diagnostic: tints this pass purple to prove it runs.
// With y6 = z6 = 0 the arithmetic follows the game's instruction order.
cbuffer Viewport : register(b0) { float4 viewport[2]; }
SamplerState inputSampler : register(s0);
Texture2D<float4> inputTexture : register(t0);
Texture1D<float4> IniParams : register(t120);

static const float4 rings[4] = {
    float4(3.771236, 3.000000, 4.000000, 0.250000),
    float4(10.000000, 2.000000, 4.500000, 0.222222),
    float4(10.917875, 2.500000, 5.500000, 0.181818),
    float4(10.917875, 2.500000, 5.500000, 0.181818)
};

float RingWeight(float alpha, float4 ring)
{
    return saturate((rcp(1.000100 - alpha) + ring.z - ring.x) * ring.w);
}

// 1 for ordinary values; up to 1 + k for bright lights. u = c/(1+c) keeps it scale-tolerant.
float Highlight(float3 rgb, float k)
{
    float peak = max(max(rgb.r, rgb.g), rgb.b);
    float u = max(peak, 0) / (1 + max(peak, 0));
    float h = saturate((u - 0.45) / 0.4);
    return 1 + k * h * h;
}

float4 main(float4 position : SV_POSITION0,
    float4 uv0 : TEXCOORD0, float4 uv1 : TEXCOORD1,
    float4 uv2 : TEXCOORD2, float4 uv3 : TEXCOORD3,
    float4 uv4 : TEXCOORD4, float4 uv5 : TEXCOORD5,
    float4 uv6 : TEXCOORD6, float4 uv7 : TEXCOORD7) : SV_TARGET0
{
    float4 taps[8] = {uv0, uv1, uv2, uv3, uv4, uv5, uv6, uv7};
    float4 controls = IniParams.Load(int2(6, 0));
    float4 result;
    if (controls.y > 0.5)
    {
        float k = controls.y > 1.5 ? 16.0 : 6.0;
        float3 colour = 0;
        float colourWeight = 0.001;
        float alphaTotal = 0;
        float alphaWeight = 0.001;
        [loop] for (uint i = 0; i < 8; ++i)
        {
            float4 ring = rings[i >> 1];
            float4 uv = min(saturate(taps[i]) * viewport[0].xyxy, viewport[0].zwzw);
            float4 a = inputTexture.Sample(inputSampler, uv.xy);
            float4 b = inputTexture.Sample(inputSampler, uv.zw);
            float wa = RingWeight(a.w, ring) * ring.y;
            float wb = RingWeight(b.w, ring) * ring.y;
            float ca = wa * Highlight(a.rgb, k), cb = wb * Highlight(b.rgb, k);
            colour += a.rgb * ca + b.rgb * cb;
            colourWeight += ca + cb;
            alphaTotal += a.w * wa + b.w * wb;
            alphaWeight += wa + wb;
        }
        result = float4(colour / colourWeight, alphaTotal / alphaWeight);
    }
    else
    {
        // Game order: mad(sample, w*y, total) per tap, weight sum starts at 0.001.
        float4 total = 0;
        float weightSum = 0.001;
        [loop] for (uint i = 0; i < 8; ++i)
        {
            float4 ring = rings[i >> 1];
            float4 uv = min(saturate(taps[i]) * viewport[0].xyxy, viewport[0].zwzw);
            float4 a = inputTexture.Sample(inputSampler, uv.xy);
            float wa = RingWeight(a.w, ring);
            float4 partial = a * (wa * ring.y) + total;
            float partialWeight = wa * ring.y + weightSum;
            float4 b = inputTexture.Sample(inputSampler, uv.zw);
            float wb = RingWeight(b.w, ring);
            total = b * (wb * ring.y) + partial;
            weightSum = wb * ring.y + partialWeight;
        }
        result = total / weightSum;
    }
    if (controls.z > 0.5)
        result.rgb = result.rgb * float3(1.0, 0.25, 1.0) + float3(0.08, 0.0, 0.08);
    return result;
}
