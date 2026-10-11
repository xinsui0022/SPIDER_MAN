#pragma once

#include <cstdint>
#include <string>

namespace coopsync::runtime {

// Called only by the explicitly started diagnostic worker, outside DllMain.
// No engine calls, hooks, memory writes or world synchronization are performed.
bool SamplerInitialize(std::string& session_json);
bool SamplerCapture(std::uint64_t sequence, std::string& sample_json);
void SamplerShutdown() noexcept;

} // namespace coopsync::runtime
