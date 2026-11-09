"""C# and F# fuzzing: SharpFuzz fuzz targets, and FsCheck property tests."""

import re

from project_validator.ecosystems.dotnet import DOTNET_LANGUAGES
from project_validator.facts.fuzzing import FuzzTargets, PropertyTests, fuzzed, fuzzer
from project_validator.facts.tools import any_of, starts, when

DOTNET_FUZZ_TARGETS = FuzzTargets(
    name="SharpFuzz fuzz targets (Fuzzer.Run, Fuzzer.LibFuzzer.Run)",
    languages=DOTNET_LANGUAGES,
    path=re.compile(r"\.(?:cs|fs)$"),
    contains=re.compile(r"Fuzzer\.(?:OutOfProcess\.|LibFuzzer\.)?Run\("),
)
DOTNET_PROPERTY_TESTS = PropertyTests(
    name="FsCheck tests",
    languages=DOTNET_LANGUAGES,
    path=re.compile(r"\.(?:cs|fs)$"),
    contains=re.compile(r"Prop\.ForAll|\[<Property>\]|\[Property\]"),
)

SHARPFUZZ = fuzzer(
    name="SharpFuzz",
    languages=DOTNET_LANGUAGES,
    how="libfuzzer-dotnet --target_path=<fuzz project> (or sharpfuzz, afl-fuzz, dotnet fuzz)",
    runs=when(
        any_of(
            starts(("libfuzzer-dotnet",)), starts(("sharpfuzz",)), starts(("afl-fuzz",)), starts(("dotnet", "fuzz"))
        ),
        fuzzed,
    ),
    targets=(DOTNET_FUZZ_TARGETS,),
)
