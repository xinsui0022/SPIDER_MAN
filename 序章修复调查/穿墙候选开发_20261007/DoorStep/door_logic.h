#pragma once
#include <cmath>
#include <cstdint>
#include <initializer_list>

namespace doorstep {
struct alignas(16) Matrix { float v[16]; };
struct Context {
    uint32_t handle;
    uintptr_t entry, mover;
    uint64_t scene;
};
struct Anchor {
    bool valid = false;
    Matrix matrix{};
    Context context{};
    uint64_t time = 0;
};
inline bool ValidMatrix(const Matrix& m) {
    for (float x : m.v) if (!std::isfinite(x)) return false;
    if (std::fabs(m.v[15] - 1.0f) > 0.05f) return false;
    for (int a : {3, 7, 11}) if (std::fabs(m.v[a]) > 0.05f) return false;
    for (int a : {12, 13, 14}) if (std::fabs(m.v[a]) > 20000.0f) return false;
    for (int row = 0; row < 3; ++row) {
        float n = 0;
        for (int k = 0; k < 3; ++k) n += m.v[row*4+k] * m.v[row*4+k];
        if (n < 0.8f || n > 1.2f) return false;
    }
    for (int a = 0; a < 3; ++a) for (int b = a+1; b < 3; ++b) {
        float dot = 0;
        for (int k = 0; k < 3; ++k) dot += m.v[a*4+k] * m.v[b*4+k];
        if (std::fabs(dot) > 0.15f) return false;
    }
    return true;
}
inline bool Step(const Matrix& from, float distance, Matrix& to) {
    if (!ValidMatrix(from) || !std::isfinite(distance) || distance < 0.5f || distance > 5.0f) return false;
    const float x = from.v[8], z = from.v[10];
    const float length = std::sqrt(x*x + z*z);
    if (length < 0.25f) return false;
    to = from;
    to.v[12] += x / length * distance;
    to.v[14] += z / length * distance;
    return ValidMatrix(to);
}
inline float Separation(const Matrix& a, const Matrix& b) {
    float q = 0;
    for (int k = 12; k < 15; ++k) q += (a.v[k]-b.v[k]) * (a.v[k]-b.v[k]);
    return std::sqrt(q);
}
inline bool Vertical(const Matrix& from, float distance, Matrix& to) {
    if (!ValidMatrix(from) || !std::isfinite(distance) || std::fabs(distance)<0.5f || std::fabs(distance)>5.0f) return false;
    to=from; to.v[13]+=distance;
    return ValidMatrix(to);
}
inline bool SameContext(const Context& a, const Context& b) {
    return a.handle == b.handle && a.entry == b.entry && a.mover == b.mover && a.scene == b.scene;
}
inline bool CanReturn(const Anchor& a, const Context& current, const Matrix& now, uint64_t time) {
    return a.valid && ValidMatrix(a.matrix) && ValidMatrix(now) && SameContext(a.context, current)
        && time >= a.time && time - a.time <= 120000 && Separation(a.matrix, now) <= 12.0f;
}
}
