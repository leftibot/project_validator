#include <cstddef>
#include <cstdint>

// A libFuzzer target: the fuzzer calls it with generated inputs.
extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data, std::size_t size)
{
  return (data != nullptr && size > 0) ? 0 : 0;
}
