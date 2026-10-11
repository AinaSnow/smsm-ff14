  // S2b = S2 with highlight protection: sharpening fades out where the brightest of the
  // 13 taps approaches display white, so lamps keep soft glow and no dark rim.
  // S2 unsharp mask, radius 2 (13 taps), for the 2-3 px soft edges left by DLAA/TAA.
  // x6 = level: 0 off, 1 medium, 2 strong (Ctrl+F4 cycles); 0 leaves the input untouched.
  // The detail term is computed in u = c/(1+c) so bright areas do not dominate.
  // Overshoot past the 13-tap min/max is limited to k * (max - min) in linear HDR:
  // S1's hard clamp kept thin hair strands (local maxima) from gaining contrast, and
  // a bound taken in u near 1 would expand to very large linear values at highlights.
  float s2Level = IniParams.Load(int2(6, 0)).x;
  if (s2Level > 0.5)
  {
    float s2Amount = s2Level > 1.5 ? 4.0 : 2.0;
    float s2Overshoot = s2Level > 1.5 ? 0.4 : 0.2;
    float3 s2L = max(color.rgb, 0);
    float3 s2C = s2L / (1 + s2L);
    float3 s2Sum = s2C * 4;
    float3 s2Min = s2L, s2Max = s2L;
    // Cross (weight 2), diagonals and radius-2 cross (weight 1): total weight 20.
    #define S2_TAP(dx, dy, w) { float3 t = max(sInput.T.Sample(sInput.S_s, v1.xy, int2(dx, dy)).rgb, 0); \
        s2Min = min(s2Min, t); s2Max = max(s2Max, t); s2Sum += t / (1 + t) * w; }
    S2_TAP( 1, 0, 2) S2_TAP(-1, 0, 2) S2_TAP( 0, 1, 2) S2_TAP( 0,-1, 2)
    S2_TAP( 1, 1, 1) S2_TAP( 1,-1, 1) S2_TAP(-1, 1, 1) S2_TAP(-1,-1, 1)
    S2_TAP( 2, 0, 1) S2_TAP(-2, 0, 1) S2_TAP( 0, 2, 1) S2_TAP( 0,-2, 1)
    #undef S2_TAP
    // Display brightness of the neighbourhood peak through the SMSM curve and white point
    // (same constants as TONEMAP_EVILS below). Full strength below 0.9 of white,
    // none from 1.05: hair and cloth at night (0.65-0.8) keep full sharpening; lamp glow stays soft.
    // Brightness alone cannot separate glow curvature from detail, so some glow steepening remains.
    float s2White = (cToneMapParam[1].x + cToneMapParam[1].y) / cCommonTexParam.y + 32.0 / 256.0;
    float s2Peak = max(max(s2Max.r, s2Max.g), s2Max.b);
    float s2Display = genericTonemap(s2Peak, 1.6f, 1.0f, 0.18f, 0.227f, 64.0f)
                    / genericTonemap(s2White, 1.6f, 1.0f, 0.18f, 0.227f, 64.0f);
    s2Amount *= 1 - smoothstep(0.9, 1.05, s2Display);
    float3 s2U = saturate(s2C + s2Amount * (s2C - s2Sum / 20));
    float3 s2Range = s2Max - s2Min;
    float3 s2Low = max(s2Min - s2Overshoot * s2Range, 0);
    float3 s2High = s2Max + s2Overshoot * s2Range;
    // Back to linear (u = 1 maps to the upper bound), then limit.
    color.rgb = clamp(s2U / max(1 - s2U, 1e-6), s2Low, s2High);
  }
