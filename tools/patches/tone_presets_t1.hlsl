  // T1 tone presets. Mode 0 keeps the R10 output computed above unchanged.
  // Ctrl+F8 cycles IniParams[7].x = 0,1,2,3; Ctrl+F7 toggles the label (y).
  float4 smsmControls = IniParams.Load(int2(7,0));
  uint smsmMode = (uint)clamp(smsmControls.x + 0.5f, 0.0f, 3.0f);
  if (smsmMode != 0)
  {
    float3 t1Hdr = max(sourceColor, 0);
    float t1W = genericTonemap(whitePt, 1.6f, 1.0f, 0.18f, 0.227f, 64.0f);
    float3 t1Out;
    if (smsmMode == 1)
    {
      // A: same SMSM curve, applied to the brightest channel so hue and
      // saturation ratios are kept (per-channel curves push skin toward white).
      float t1Peak = max(max(t1Hdr.r, t1Hdr.g), t1Hdr.b);
      float t1Mapped = genericTonemap(t1Peak, 1.6f, 1.0f, 0.18f, 0.227f, 64.0f) / t1W;
      t1Out = t1Peak > 1e-6f ? t1Hdr * (t1Mapped / t1Peak) : float3(0,0,0);
    }
    else if (smsmMode == 2)
    {
      // B: colour from the game's own tone map (keeps the zone LUT grading),
      // brightness from the full SMSM curve (removes the grey haze).
      static const float3 t1Luma = float3(0.2126f, 0.7152f, 0.0722f);
      float3 t1Game = GameToneMap(sourceColor);
      float t1GameL = dot(t1Game, t1Luma);
      float t1SmsmL = dot(color.rgb, t1Luma);
      t1Out = t1Game * clamp(t1SmsmL / max(t1GameL, 1e-4f), 0.0f, 4.0f);
    }
    else
    {
      // C: as A, but near-white highlights roll toward neutral white
      // (lamps and sunlit cloth stop looking neon; mid-tone skin is untouched).
      float t1Peak = max(max(t1Hdr.r, t1Hdr.g), t1Hdr.b);
      float t1Mapped = genericTonemap(t1Peak, 1.6f, 1.0f, 0.18f, 0.227f, 64.0f) / t1W;
      float3 t1Hue = t1Peak > 1e-6f ? t1Hdr * (t1Mapped / t1Peak) : float3(0,0,0);
      float t1Roll = saturate((t1Mapped - 0.7f) / 0.3f);
      t1Out = lerp(t1Hue, t1Mapped.xxx, 0.5f * t1Roll * t1Roll);
    }
    // No output ceiling: like R10, values above 1 pass through to later passes.
    o0.rgb = max(t1Out, 0);
  }

  // Mode label: "R10" in blue for mode 0, a single letter A/B/C otherwise.
  uint2 smsmPixel = (uint2)v0.xy;
  if (smsmControls.y > 0.5f && all(smsmPixel >= uint2(24,24)) && all(smsmPixel < uint2(72,46)))
  {
    uint2 cell = (smsmPixel - uint2(28,28)) / 2;
    bool inText = all(smsmPixel >= uint2(28,28)) && cell.y < 7 && cell.x < 18;
    uint letter = cell.x / 6;
    uint column = cell.x % 6;
    // Glyph rows, five pixels wide: R, 1, 0, A, B, C.
    static const uint glyphs[42] = {
      30,17,17,30,20,18,17,  4,12,4,4,4,4,14,  14,17,19,21,25,17,14,
      14,17,17,31,17,17,17,  30,17,17,30,17,17,30,  14,17,16,16,16,17,14
    };
    uint glyph = smsmMode == 0 ? letter : 2 + smsmMode;
    bool ink = inText && column < 5 && (smsmMode == 0 || letter == 0);
    uint row = glyphs[min(glyph,5u)*7 + min(cell.y,6u)];
    ink = ink && ((row >> (4u-min(column,4u))) & 1u) != 0;
    static const float3 accents[4] = {
      float3(0.2,0.65,1.0), float3(0.3,0.9,0.35), float3(1.0,0.45,0.12), float3(0.75,0.4,1.0)
    };
    o0.rgb = ink ? accents[smsmMode] : float3(0.025,0.025,0.025);
  }
