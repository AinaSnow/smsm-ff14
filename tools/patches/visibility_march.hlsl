// Shared marcher; the caller supplies projection settings and visiblePosition/visibleNormal.
bool projectVisibility(float3 p, out float2 uv)
{
    float4 h=float4(dot(projectionRows[0],float4(p,1)),dot(projectionRows[1],float4(p,1)),
                    dot(projectionRows[2],float4(p,1)),dot(projectionRows[3],float4(p,1)));
    bool valid=abs(h.w)>1e-8 && all(abs(h)<1e20);
    float3 ndc=h.xyz/(valid?h.w:1);
    uv=ndc.xy*ndcToUV.xy+ndcToUV.zw;
    return valid && all(abs(ndc.xy)<1) && ndc.z>0 && ndc.z<1 && all(uv>0) && all(uv<1);
}
float materialVisibility(float3 p, out float supported)
{
    supported=1;
    uint count=(uint)clamp(visibilitySettings.w,1,128);
    float3 segment=lampPositionRange.xyz-p;
    [loop] for(uint i=1;i<=count;++i) {
        float3 q=p+segment*((float)i/((float)count+1));
        float2 uv;
        if(!projectVisibility(q,uv)) {supported=0;return 1;}
        bool sceneValid;float3 scene=visiblePosition(uv,sceneValid);
        // Invalid depth is missing information: explicitly flag the fallback.
        if(!sceneValid) {supported=0;return 1;}
        float gap=abs(q.z)-abs(scene.z);
        if(gap>max(visibilitySettings.y,0) && gap<max(visibilitySettings.z,0)) {
#if MATERIAL_PLANE_REFINE
            bool normalValid;float3 n=visibleNormal(uv,normalValid);
            float denom=dot(n,segment);
            float t=dot(n,scene-p)/(abs(denom)>1e-8?denom:1);
            float3 hit=p+t*segment;float2 hitUV;
            if(normalValid && abs(denom)>1e-8 && t>0 && t<1 &&
               length(hit-p)>max(visibilitySettings.y,.0001) && projectVisibility(hit,hitUV)) {
                bool verifyValid;float3 verify=visiblePosition(hitUV,verifyValid);
#if VISIBILITY_PLANE_DISTANCE
                // A nearest texel center can differ in depth along the same
                // slanted plane. Compare distance normal to that local plane.
                if(verifyValid && abs(dot(verify-hit,n))<=max(visibilitySettings.y,.0001)) return 0;
#else
                if(verifyValid && abs(verify.z-hit.z)<=max(visibilitySettings.y,.0001)) return 0;
#endif
            }
#else
            return 0;
#endif
        }
    }
    return 1;
}
