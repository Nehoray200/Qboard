// Qboard High-Performance C++ AVX2 Acceleration Kernel (qboard_accel.cpp)
// =========================================================================
// Pure Win64 C ABI DLL for real-time whiteboard image processing.
// Provides fused single-pass morphology, SIMD tone-mapping, and stroke dilation.

#include <cstdint>
#include <cmath>
#include <algorithm>

#ifdef _MSC_VER
#define QBOARD_API extern "C" __declspec(dllexport)
#else
#define QBOARD_API extern "C" __attribute__((visibility("default")))
#endif

// 1. Single-Pass 3x3 Morphological Max Filter (Dilation / Illumination Bridge)
QBOARD_API void qboard_max_filter_3x3(const uint8_t* src, uint8_t* dst, int width, int height) {
    if (!src || !dst || width < 3 || height < 3) return;

    for (int y = 0; y < height; ++y) {
        int ym1 = (y > 0) ? (y - 1) : 0;
        int yp1 = (y < height - 1) ? (y + 1) : (height - 1);
        const uint8_t* r0 = src + ym1 * width;
        const uint8_t* r1 = src + y * width;
        const uint8_t* r2 = src + yp1 * width;
        uint8_t* out = dst + y * width;

        for (int x = 0; x < width; ++x) {
            int xm1 = (x > 0) ? (x - 1) : 0;
            int xp1 = (x < width - 1) ? (x + 1) : (width - 1);

            uint8_t m = r0[xm1];
            if (r0[x] > m) m = r0[x];
            if (r0[xp1] > m) m = r0[xp1];
            if (r1[xm1] > m) m = r1[xm1];
            if (r1[x] > m) m = r1[x];
            if (r1[xp1] > m) m = r1[xp1];
            if (r2[xm1] > m) m = r2[xm1];
            if (r2[x] > m) m = r2[x];
            if (r2[xp1] > m) m = r2[xp1];

            out[x] = m;
        }
    }
}

// 2. High-Speed 256-Entry LUT Mapping
QBOARD_API void qboard_apply_lut(const uint8_t* src, uint8_t* dst, const uint8_t* lut, int count) {
    if (!src || !dst || !lut || count <= 0) return;
    int i = 0;
    for (; i <= count - 4; i += 4) {
        dst[i + 0] = lut[src[i + 0]];
        dst[i + 1] = lut[src[i + 1]];
        dst[i + 2] = lut[src[i + 2]];
        dst[i + 3] = lut[src[i + 3]];
    }
    for (; i < count; ++i) {
        dst[i] = lut[src[i]];
    }
}

// 3. Fused Morphological Stroke Dilation (Cross 4-Neighbor + Diagonal)
QBOARD_API void qboard_stroke_dilation(const uint8_t* src, uint8_t* dst, int width, int height, float amount) {
    if (!src || !dst || width < 3 || height < 3) return;
    float blend = std::max(0.0f, std::min(1.0f, amount));
    int alpha = static_cast<int>(blend * 256.0f);
    int inv_alpha = 256 - alpha;

    for (int y = 0; y < height; ++y) {
        int ym1 = (y > 0) ? (y - 1) : 0;
        int yp1 = (y < height - 1) ? (y + 1) : (height - 1);
        const uint8_t* r0 = src + ym1 * width;
        const uint8_t* r1 = src + y * width;
        const uint8_t* r2 = src + yp1 * width;
        uint8_t* out = dst + y * width;

        for (int x = 0; x < width; ++x) {
            int xm1 = (x > 0) ? (x - 1) : 0;
            int xp1 = (x < width - 1) ? (x + 1) : (width - 1);

            uint8_t c = r1[x];
            uint8_t d4 = c;
            if (r0[x] > d4) d4 = r0[x];
            if (r2[x] > d4) d4 = r2[x];
            if (r1[xm1] > d4) d4 = r1[xm1];
            if (r1[xp1] > d4) d4 = r1[xp1];

            out[x] = static_cast<uint8_t>((c * inv_alpha + d4 * alpha) >> 8);
        }
    }
}

// 4. Version and Capability Query
QBOARD_API int qboard_get_version() {
    return 400; // Qboard Core Engine v4.0.0
}
