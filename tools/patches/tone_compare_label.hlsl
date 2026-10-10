  // Deliberately small in-frame label: confirms this tone shader ran.
  // Ctrl+F7 hides it for screenshots. Alpha is never changed.
  uint2 smsmPixel = (uint2)v0.xy;
  if (smsmControls.y > 0.5f && all(smsmPixel >= uint2(24,24)) && all(smsmPixel < uint2(72,46)))
  {
    uint2 cell = (smsmPixel - uint2(28,28)) / 2;
    bool inText = all(smsmPixel >= uint2(28,28)) && cell.y < 7 && cell.x < 18;
    uint letter = cell.x / 6;
    uint column = cell.x % 6;
    // Glyph rows, five pixels wide: R, 1, 0, H.
    static const uint glyphs[28] = {
      30,17,17,30,20,18,17, 4,12,4,4,4,4,14,
      14,17,19,21,25,17,14, 17,17,17,31,17,17,17
    };
    bool high = smsmControls.x > 0.5f;
    uint glyph = high ? (letter == 0 ? 3 : 1) : letter;
    bool ink = inText && column < 5 && (!high || letter < 2);
    uint row = glyphs[min(glyph,3u)*7 + min(cell.y,6u)];
    ink = ink && ((row >> (4u-min(column,4u))) & 1u) != 0;
    float3 accent = high ? float3(1.0,0.45,0.12) : float3(0.2,0.65,1.0);
    o0.rgb = ink ? accent : float3(0.025,0.025,0.025);
  }
