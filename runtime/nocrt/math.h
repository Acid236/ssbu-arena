/* Minimal <math.h> for the game libraries built without the MSVC / Windows SDK headers (RECOMP_NOCRT=1, see
 * tools/lifter/build.py). Same declarations as the Universal CRT's for x64, so the compiler makes the same code: the
 * functions are ordinary external functions, except fabsf, which the UCRT header defines inline as (float)fabs(x) on
 * x64 and is defined the same way here. The functions come from ucrtbase.dll (nocrt/ucrtbase_min.def); every one of
 * them is exactly rounded (IEEE 754), so any correct implementation gives the same results. */
#ifndef SSBU_NOCRT_MATH_H
#define SSBU_NOCRT_MATH_H
double __cdecl fabs(double _X);
double __cdecl sqrt(double _X);
double __cdecl ceil(double _X);
double __cdecl floor(double _X);
double __cdecl round(double _X);
double __cdecl trunc(double _X);
double __cdecl rint(double _X);
double __cdecl nearbyint(double _X);
double __cdecl fma(double _X, double _Y, double _Z);
double __cdecl fmax(double _X, double _Y);
double __cdecl fmin(double _X, double _Y);
double __cdecl copysign(double _Number, double _Sign);
float __cdecl sqrtf(float _X);
float __cdecl ceilf(float _X);
float __cdecl floorf(float _X);
float __cdecl roundf(float _X);
float __cdecl truncf(float _X);
float __cdecl rintf(float _X);
float __cdecl nearbyintf(float _X);
float __cdecl fmaf(float _X, float _Y, float _Z);
float __cdecl fmaxf(float _X, float _Y);
float __cdecl fminf(float _X, float _Y);
float __cdecl copysignf(float _Number, float _Sign);
__inline float __cdecl fabsf(float _X)
{
    return (float)fabs(_X);
}
#endif
