  // T2 dithering, inside tone mapping: the r10 output-copy shader is not on the
  // displayed path with DLSS/FSR, but this pass is. Same centred noise as r10
  // (DitherMode 4): at most one 8-bit step, faded out at exact black/white and
  // above 1, alpha untouched. z7 switches it (Ctrl+F6).
  if (smsmControls.z > 0.5)
  {
    float3 t2Noise = ign3(v0.xy);
    t2Noise.y = ign3(v0.xy + 0.5).x;
    t2Noise = clamp(t2Noise * 2 - 1.0 / 255.0, -1.0 / 255.0, 1.0 / 255.0);
    float3 t2Fade = min(saturate(o0.rgb * 255), saturate((1 - o0.rgb) * 255));
    o0.rgb += t2Noise * t2Fade;
  }

