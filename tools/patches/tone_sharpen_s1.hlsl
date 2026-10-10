  // S1 contrast-adaptive sharpening (after AMD FidelityFX CAS, 5-tap cross).
  // x6 = sharpness 0..1 (Ctrl+F4 cycles); 0 leaves the input untouched.
  // Works on the HDR input before both tone curves, in a compressed u = c/(1+c)
  // range so highlights cannot overshoot; the result is clamped to the cross's
  // min/max, so no new extremes (halos) are created. Alpha is not touched.
  float s1Sharpness = saturate(IniParams.Load(int2(6, 0)).x);
  if (s1Sharpness > 0)
  {
    float3 s1C = max(color.rgb, 0);
    float3 s1N = max(sInput.T.Sample(sInput.S_s, v1.xy, int2(0, -1)).rgb, 0);
    float3 s1S = max(sInput.T.Sample(sInput.S_s, v1.xy, int2(0, 1)).rgb, 0);
    float3 s1W = max(sInput.T.Sample(sInput.S_s, v1.xy, int2(-1, 0)).rgb, 0);
    float3 s1E = max(sInput.T.Sample(sInput.S_s, v1.xy, int2(1, 0)).rgb, 0);
    s1C /= 1 + s1C; s1N /= 1 + s1N; s1S /= 1 + s1S; s1W /= 1 + s1W; s1E /= 1 + s1E;
    float3 s1Min = min(s1C, min(min(s1N, s1S), min(s1W, s1E)));
    float3 s1Max = max(s1C, max(max(s1N, s1S), max(s1W, s1E)));
    // Less sharpening where local contrast is already high.
    float3 s1Amp = sqrt(saturate(min(s1Min, 1 - s1Max) / max(s1Max, 1e-5)));
    float3 s1Weight = s1Amp * (-1.0 / lerp(8.0, 5.0, s1Sharpness));
    float3 s1U = (s1C + s1Weight * (s1N + s1S + s1W + s1E)) / (1 + 4 * s1Weight);
    s1U = clamp(s1U, s1Min, s1Max);
    color.rgb = s1U / max(1 - s1U, 1e-4);
  }
