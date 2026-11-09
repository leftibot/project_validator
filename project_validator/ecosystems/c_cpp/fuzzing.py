"""C and C++ fuzzing: libFuzzer and AFL++ fuzz targets, run as binaries (or by CTest, see the fuzz-testing question),
and RapidCheck property tests."""

import re

from project_validator.ecosystems.c_cpp import C_AND_CXX
from project_validator.facts import Command, Facts, resolved
from project_validator.facts.fuzzing import LIBFUZZER_OPTION, FuzzTargets, PropertyTests, dotnet_target, fuzzed, fuzzer
from project_validator.facts.tools import Run, all_of, known_tools, starts, when

C_FUZZ_TARGETS = FuzzTargets(
    name="libFuzzer or AFL++ fuzz targets (LLVMFuzzerTestOneInput, __AFL_LOOP)",
    languages=C_AND_CXX.languages,
    path=re.compile(r"\.(?:c|cc|cpp|cxx|C)$"),
    contains=re.compile(r"\bLLVMFuzzerTestOneInput\b|__AFL_LOOP|__AFL_FUZZ_TESTCASE_BUF"),
)
C_PROPERTY_TESTS = PropertyTests(
    name="RapidCheck tests",
    languages=C_AND_CXX.languages,
    path=re.compile(r"\.(?:c|cc|cpp|cxx|C|h|hpp)$"),
    contains=re.compile(r"\brc::check\b|\bRC_GTEST_PROP\b|\bRC_BOOST_PROP\b"),
)


def _libfuzzer_binary(command: Command, facts: Facts) -> Run | None:
    """A fuzz target binary run with a libFuzzer option (`./build/fuzz_tester -max_total_time=30`): a heuristic, for
    a program given as a path (a bare program is a launcher's, `npx jazzer`) that is not Swift's product (under
    `.build/`) and not a known tool (which claims its own commands)."""
    argv = resolved(command)
    if not argv or "/" not in argv[0] or argv[0].removeprefix("./").startswith(".build/"):
        return None
    if not any(LIBFUZZER_OPTION.fullmatch(word) for word in argv[1:]):
        return None
    if any(tool.name != "libFuzzer" and tool.claims(command, facts) for tool in known_tools()):
        return None
    return fuzzed(heuristic=True)


LIBFUZZER = fuzzer(
    name="libFuzzer",
    languages=C_AND_CXX.languages,
    how="a fuzz target binary with -max_total_time= (or ClusterFuzzLite)",
    runs=_libfuzzer_binary,
    targets=(C_FUZZ_TARGETS,),
)

AFL = fuzzer(
    name="AFL++",
    languages=C_AND_CXX.languages,
    how="afl-fuzz -i <corpus> -o <findings> -- <target>",
    runs=when(all_of(starts(("afl-fuzz",)), lambda command: not dotnet_target(command)), fuzzed),
    targets=(C_FUZZ_TARGETS,),
)
