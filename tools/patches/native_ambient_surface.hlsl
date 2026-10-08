// Experimental diffuse-only surface sampling of the game's native ambient array.
// t12 is an owned GPU copy of the same-camera native buffer; b8 is opt-in control.
// Keep the host's attenuation, AO, reflected lighting, alpha and output encoding.
StructuredBuffer<uint4> regionRows : register(t12);
cbuffer NativeAmbientControl : register(b8) { float4 control; }
float4 row(uint index) {return asfloat(regionRows[index]);}

float spatialWeight(uint i, float3 position)
{
    uint b=4+12*i;
    uint type = regionRows[b+10].w;
    float4 p = float4(position,1);
    float3 q = float3(dot(row(b+6),p),dot(row(b+7),p),dot(row(b+8),p));
    float3 minusRange = row(b+9).xyz;
    float3 plusRange = float3(row(b+9).w,row(b+10).xy);
    float3 inverseRange = lerp(minusRange,plusRange,step(0,q));
    float result = -1;
    if (type == 0) result = 1;
    else if (type <= 3 && all(abs(q)<1e15) && all(inverseRange>0) && all(inverseRange<1e15)) {
        float3 face = inverseRange*(1-abs(q));
        result = saturate(min(face.x,min(face.y,face.z)));
        if (result > 0 && type == 1) {
            float radius = length(q);
            // Analytic limit at the center; never evaluate 0/0.
            result = radius < 1e-6 ? 1 : saturate((1-radius)/dot(rcp(inverseRange),abs(q)/radius));
        } else if (result > 0 && type == 3) {
            float radius = length(q.xz);
            float radial = radius < 1e-6 ? 1 : saturate((1-radius)/dot(rcp(inverseRange.xz),abs(q.xz)/radius));
            result = saturate(min(face.y,radial));
        }
    }
    return result;
}

float3 diffuseRegion(uint i,float3 normal)
{
    uint b=4+12*i;
    float4 n=float4(normal,1);
    // Exactly the native normal-dot-SH clamp and reciprocal scale.
    return saturate(float3(dot(row(b),n),dot(row(b+1),n),dot(row(b+2),n)))*row(b+3).w;
}

float4 main(float3 normal:COLOR0,float3 position:TEXCOORD0):SV_TARGET
{
    float4 output=0;
    uint rows,stride;regionRows.GetDimensions(rows,stride);
    uint count=regionRows[0].x;
    // A global-only scene has no spatial detail to add: retain the object's
    // original ambient even when its coefficients differ from the background.
    if (control.x>0 && control.x<=1 && count>1 && count<=64 && rows>=4+12*count && stride==16 &&
        all(abs(normal)<1e8) && all(abs(position)<1e15)) {
        uint global=count-1;
        if (regionRows[4+12*global+10].w==0) {
            uint a=global,b=global,c=global,picked=0;
            float wa=1,wb=1;
            bool valid=true;
            [loop] for(uint i=0;i<64 && i<global;++i) {
                float w=spatialWeight(i,position);
                if(w<0) {valid=false;break;}
                if(w>0) {
                    if(picked==0) {a=i;wa=w;}
                    else if(picked==1) {b=i;wb=w;}
                    else c=i;
                    ++picked;
                    if(picked==3 || w>=1) break;
                }
            }
            float3 value=lerp(lerp(diffuseRegion(c,normal),diffuseRegion(b,normal),wb),diffuseRegion(a,normal),wa);
            if(valid && all(value>=0) && all(value<1e10)) output=float4(value,control.x);
        }
    }
    return output;
}
