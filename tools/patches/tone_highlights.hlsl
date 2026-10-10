  // Experimental SDR shoulder after the accepted static 50% blend.
  // Preserve dark/mid tones and RGB ratios; roll peaks above 0.85 towards 1.
  // Assumes a later SDR display clamp. Actual scene benefit remains unverified.
  float smsmPeak = max(o0.r, max(o0.g, o0.b));
  const float smsmKnee = 0.85f;
  if (smsmPeak > smsmKnee)
  {
    float smsmExcess = smsmPeak - smsmKnee;
    float smsmRolledPeak = smsmKnee + (1.0f - smsmKnee) *
        smsmExcess / ((1.0f - smsmKnee) + smsmExcess);
    o0.rgb *= smsmRolledPeak / smsmPeak;
  }
