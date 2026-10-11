#pragma once

#include <cstdint>
#include <string>

namespace coopsync::runtime {

// Hash/version validation belongs to the calling sampler. This diagnostic uses
// only ReadProcessMemory on the current process. It never executes game code.
// Its rolling window is explicitly incomplete and local handles are not peer IDs.
std::string CaptureWorldRaw(std::uintptr_t base, std::uint32_t image_size,
                            std::uint64_t sequence);

} // namespace coopsync::runtime
