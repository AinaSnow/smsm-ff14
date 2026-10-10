  // H3: fix H1's excessive energy/contrast loss before judging visual benefit.
  // Preserve values <= 0.95. Smoothly attenuate brighter RGB by at most 6%.
  // No fixed output ceiling: emissive cores can retain values above 1.
  float smsmPeak = max(o0.r, max(o0.g, o0.b));
  const float smsmKnee = 0.95f;
  if (smsmPeak > smsmKnee)
  {
    float smsmExcess = (smsmPeak - smsmKnee) / 0.75f;
    float smsmWeight = (smsmExcess * smsmExcess) / (1.0f + smsmExcess * smsmExcess);
    o0.rgb *= 1.0f - 0.06f * smsmWeight;
  }
