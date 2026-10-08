// Experimental angular styling, not area lighting, SSS or a shadow penumbra.
// Negative N.L stays black; RGB is scaled together to avoid introducing a hue.
// Bounded mode never exceeds Lambert. Balanced mode preserves the uniform-
// hemisphere response integral but can brighten intermediate angles and clip.
#ifndef SMSM_DIFFUSE_BOUNDED
#define SMSM_DIFFUSE_BOUNDED 1
#endif
float smsmDiffuseResponse(float cosine, float strength)
{
    float x=saturate(cosine);
#if SMSM_DIFFUSE_BOUNDED
    float rounded=x*x*(2-x);
#else
    float rounded=x*x*(3-2*x);
#endif
    return lerp(x,rounded,saturate(strength))/3.141592653589793;
}
