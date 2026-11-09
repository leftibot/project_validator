"""Reading CMake projects: evaluation, what commands set, presets, and custom targets."""

import json
import unittest
from unittest import mock

from project_validator.build_systems import cmake
from project_validator.build_systems.cmake import evaluation
from project_validator.build_systems.cmake.presets import preset_facts
from project_validator.facts import Command, Fact, Origin, Setting, Unknown
from project_validator.facts.build import Applies, BuildSetting, CompilerOption
from project_validator.facts.conditions import DIMENSIONS
from project_validator.facts.dependencies import Declared
from tests.support import github_job, make_context, temp_project

# Every value of a dimension, as the profiles have extended it.
COMPILERS, PLATFORMS = DIMENSIONS["compilers"], DIMENSIONS["platforms"]
ANY = Applies()
MSVC = Applies(compilers=frozenset({"msvc"}))
NOT_MSVC = Applies(compilers=frozenset(COMPILERS) - {"msvc"})
GCC = Applies(compilers=frozenset({"gcc"}))
HOST = "${hostSystemName}"


def _lines(*lines: str) -> str:
    return "".join(f"{line}\n" for line in lines)


def _facts(files: dict[str, str]) -> tuple[Fact, ...]:
    return cmake._evaluated(files).facts


def _listed(*lines: str) -> tuple[Fact, ...]:
    return _facts({"CMakeLists.txt": _lines(*lines)})


def _options(found: tuple[Fact, ...]) -> list[tuple[str, str | None, Applies]]:
    return [(fact.option, fact.target, fact.applies) for fact in found if isinstance(fact, CompilerOption)]


def _settings(found: tuple[Fact, ...], name: str) -> list[tuple[str, Applies, bool]]:
    settings = (fact for fact in found if isinstance(fact, BuildSetting) and fact.name == name)
    return [(fact.value, fact.applies, fact.default) for fact in settings]


def _requiring(*requirements: str, compilers: frozenset[str] | None = None) -> Applies:
    return Applies(compilers=compilers, requires=frozenset(requirements))


class BranchTests(unittest.TestCase):
    def test_each_branch_sets_options_in_its_builds(self) -> None:
        found = _listed(
            "if(MSVC)",
            "  add_compile_options(/W4)",
            'elseif(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")',
            "  add_compile_options(-Wall)",
            "else()",
            "  add_compile_options(-Wextra [[-Wshadow]])",
            "endif()",
        )
        others = Applies(compilers=frozenset(COMPILERS) - {"msvc", "gcc"})
        expected = [("/W4", None, MSVC), ("-Wall", None, GCC), ("-Wextra", None, others), ("-Wshadow", None, others)]
        self.assertEqual(_options(found), expected)

    def test_an_option_the_build_cannot_decide_is_required(self) -> None:
        found = _listed('option(STRICT "" ON)', "if(STRICT)", "  add_compile_options(-Werror)", "endif()", "option()")
        self.assertEqual(_options(found), [("-Werror", None, _requiring("STRICT"))])
        self.assertEqual(_settings(found, "STRICT"), [("ON", ANY, True)])

    def test_loops_run_for_each_item(self) -> None:
        found = _listed(
            "set(FLAGS -Wall -Wextra)",
            "foreach(FLAG ${FLAGS})",
            "  add_compile_options(${FLAG})",
            "endforeach()",
            "foreach(FLAG IN LISTS FLAGS ITEMS -Wshadow)",
            "  target_compile_options(app PRIVATE ${FLAG})",
            "endforeach()",
            "foreach(I RANGE 3)",
            "  add_compile_options(-O${I})",
            "endforeach()",
            "foreach()",
            "endforeach()",
        )
        self.assertEqual(
            _options(found),
            [
                ("-Wall", None, ANY),
                ("-Wextra", None, ANY),
                ("-Wall", "app", ANY),
                ("-Wextra", "app", ANY),
                ("-Wshadow", "app", ANY),
                ("-O${I}", None, ANY),
            ],
        )

    def test_a_loop_runs_only_for_the_items_of_its_builds(self) -> None:
        found = _listed(
            "if(MSVC)",
            "  set(FLAGS /W4)",
            "else()",
            "  foreach(FLAG IN LISTS FLAGS)",
            "    add_compile_options(${FLAG})",
            "  endforeach()",
            "endif()",
        )
        self.assertEqual(_options(found), [])

    def test_while_and_block(self) -> None:
        found = _listed(
            "while(KEEP_GOING)",
            "  add_compile_options(-g)",
            "endwhile()",
            "block()",
            "  add_compile_options(-fPIC)",
            "endblock()",
        )
        self.assertEqual(_options(found), [("-g", None, _requiring("KEEP_GOING")), ("-fPIC", None, ANY)])

    def test_deep_nesting_is_unknown_not_a_crash(self) -> None:
        for text in (
            "if(A)\n" * 5000 + "endif()\n" * 5000,
            "foreach(i 1)\n" * 5000 + "endforeach()\n" * 5000,
            "if(" + "(" * 5000 + "A" + ")" * 5000 + ")\nendif()\n",
        ):
            with self.subTest(text=text[:20]):
                found = _facts({"CMakeLists.txt": "project(x)\n" + text})
                self.assertTrue(any(isinstance(fact, Unknown) for fact in found))

    def test_a_deeply_nested_generator_expression_is_kept_as_written(self) -> None:
        expression = "$<$<BOOL:1>:" * 2000 + "-W" + ">" * 2000
        found = _listed("add_executable(a a.c)", f"target_compile_options(a PRIVATE {expression})")
        self.assertEqual([option for option, _, _ in _options(found)], [expression])


class VariableTests(unittest.TestCase):
    def test_a_variable_holds_each_value_in_the_builds_it_is_set_in(self) -> None:
        found = _listed(
            "set(WARNINGS -Wall)",
            "if(MSVC)",
            "  set(WARNINGS /W4)",
            "endif()",
            "list(APPEND WARNINGS -Wextra)",
            "list(PREPEND WARNINGS -Wshadow)",
            "list(INSERT WARNINGS 0 -Wundef)",
            "list(REMOVE_ITEM WARNINGS -Wundef)",
            "list(LENGTH WARNINGS COUNT)",
            "list(APPEND)",
            "add_compile_options(${WARNINGS})",
        )
        self.assertEqual(
            _options(found),
            [("-Wall", None, NOT_MSVC), ("/W4", None, MSVC), ("-Wextra", None, ANY), ("-Wshadow", None, ANY)],
        )

    def test_flags_variables_are_options(self) -> None:
        found = _listed(
            'set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -Wall")',
            "if(MSVC)",
            '  string(APPEND CMAKE_CXX_FLAGS " /W4")',
            "endif()",
            'set(CMAKE_C_FLAGS_DEBUG "-O0")',
            'set(CMAKE_EXE_LINKER_FLAGS "-pie")',
            "string(TOLOWER X Y)",
        )
        cxx, c = frozenset({"C++"}), frozenset({"C"})
        expected = [
            ("-Wall", None, Applies(languages=cxx)),
            ("/W4", None, Applies(compilers=frozenset({"msvc"}), languages=cxx)),
            ("-O0", None, Applies(configurations=frozenset({"debug"}), languages=c)),
            ("-pie", None, ANY),
        ]
        self.assertEqual(sorted(_options(found), key=str), sorted(expected, key=str))
        linker = next(fact for fact in found if isinstance(fact, CompilerOption) and fact.option == "-pie")
        self.assertTrue(linker.linking)

    def test_unset_and_cache(self) -> None:
        found = _listed(
            "set(CMAKE_CXX_STANDARD 20)",
            "unset(CMAKE_CXX_STANDARD)",
            "set(CMAKE_CXX_COMPILER_LAUNCHER ccache)",
            "set(CMAKE_CXX_COMPILER_LAUNCHER)",
            "set(CMAKE_CXX_EXTENSIONS OFF)",
            "if(MSVC)",
            "  unset(CMAKE_CXX_EXTENSIONS)",
            "endif()",
            'set(CMAKE_BUILD_TYPE Release CACHE STRING "")',
            "set(CMAKE_BUILD_TYPE Debug)",
            'set(LEVEL 2 CACHE STRING "level")',
            "set(ENV{CC} gcc)",
            "set()",
            "unset()",
        )
        self.assertEqual(_settings(found, "CMAKE_CXX_STANDARD"), [])
        self.assertEqual(_settings(found, "CMAKE_CXX_COMPILER_LAUNCHER"), [])
        self.assertEqual(_settings(found, "CMAKE_CXX_EXTENSIONS"), [("OFF", NOT_MSVC, False)])
        self.assertEqual(_settings(found, "CMAKE_BUILD_TYPE"), [("Release", ANY, True)])
        self.assertEqual(_settings(found, "LEVEL"), [("2", ANY, True)])

    def test_a_function_sets_its_callers_variables_in_the_parent_scope(self) -> None:
        found = _listed(
            "set(CMAKE_CXX_STANDARD 20)",
            "function(choose)",
            "  set(CMAKE_CXX_EXTENSIONS OFF PARENT_SCOPE)",
            "  set(CMAKE_CXX_STANDARD 17)",
            "  unset(CMAKE_CXX_STANDARD PARENT_SCOPE)",
            "endfunction()",
            "choose()",
        )
        self.assertEqual(_settings(found, "CMAKE_CXX_EXTENSIONS"), [("OFF", ANY, False)])
        self.assertEqual(_settings(found, "CMAKE_CXX_STANDARD"), [])

    def test_a_value_unset_in_some_builds_may_be_set_when_configuring(self) -> None:
        found = _listed("if(MSVC)", "  set(LEVEL /W4)", "endif()", "add_compile_options(${LEVEL})")
        self.assertEqual(_options(found), [("/W4", None, MSVC), ("${LEVEL}", None, NOT_MSVC)])

    def test_compiler_checks_are_described(self) -> None:
        found = _listed(
            "check_cxx_compiler_flag(-fstack-protector-strong HAS_SSP)",
            "check_linker_flag(CXX -pie HAS_PIE)",
            "check_cxx_compiler_flag(-x)",
            "if(HAS_SSP AND HAS_PIE)",
            "  add_compile_options(-fstack-protector-strong)",
            "endif()",
        )
        requirements = ("the compiler accepts -fstack-protector-strong", "the linker accepts -pie")
        self.assertEqual(_options(found), [("-fstack-protector-strong", None, _requiring(*requirements))])

    def test_separated_arguments(self) -> None:
        found = _listed(
            'separate_arguments(FLAGS UNIX_COMMAND "-Wall -Wextra")',
            'set(MORE "-Wshadow -Wconversion")',
            "separate_arguments(MORE)",
            "separate_arguments()",
            "add_compile_options(${FLAGS} ${MORE})",
        )
        self.assertEqual([option for option, _, _ in _options(found)], ["-Wall", "-Wextra", "-Wshadow", "-Wconversion"])

    def test_find_program_finds_the_first_name(self) -> None:
        found = _listed(
            "find_program(TIDY NAMES clang-tidy clang-tidy-18)",
            "find_program(TIDY other)",
            "find_program(CPPCHECK cppcheck)",
            'set(CMAKE_CXX_CLANG_TIDY ${TIDY} "--quiet")',
            "set(CMAKE_CXX_CPPCHECK ${CPPCHECK})",
        )
        self.assertEqual(_settings(found, "CMAKE_CXX_CLANG_TIDY"), [("clang-tidy;--quiet", ANY, False)])
        self.assertEqual(_settings(found, "CMAKE_CXX_CPPCHECK"), [("cppcheck", ANY, False)])


class FunctionTests(unittest.TestCase):
    def test_a_function_runs_where_it_is_called(self) -> None:
        found = _listed(
            "function(warn target strict)",
            "  target_compile_options(${target} PRIVATE -Wall)",
            "  if(strict)",
            "    target_compile_options(${target} PRIVATE -Werror)",
            "  endif()",
            "  target_compile_options(${target} PRIVATE ${ARGN} ${ARGV0} ${ARGC})",
            "endfunction()",
            "function()",
            "endfunction()",
            "if(MSVC)",
            "else()",
            "  warn(app ${STRICT} -Wextra)",
            "endif()",
        )
        self.assertEqual(
            _options(found),
            [
                ("-Wall", "app", NOT_MSVC),
                ("-Werror", "app", _requiring("STRICT", compilers=NOT_MSVC.compilers)),
                ("-Wextra", "app", NOT_MSVC),
                ("app", "app", NOT_MSVC),
                ("3", "app", NOT_MSVC),
            ],
        )

    def test_a_macro_replaces_its_arguments(self) -> None:
        found = _listed(
            "macro(harden target global)",
            "  if(${global})",
            "    add_compile_options(-fcf-protection)",
            "  else()",
            "    target_compile_options(${target} PRIVATE -fcf-protection)",
            "  endif()",
            "endmacro()",
            "harden(lib ON)",
        )
        self.assertEqual(_options(found), [("-fcf-protection", None, ANY)])

    def test_a_function_nothing_calls_runs_as_if_called(self) -> None:
        files = {
            "cmake/Warnings.cmake": _lines("function(warnings target)", "  add_compile_options(-Wall)", "endfunction()")
        }
        expected = _requiring("cmake/Warnings.cmake is included", "warnings() is called")
        self.assertEqual(_options(_facts(files)), [("-Wall", None, expected)])

    def test_recursion_and_repeated_calls_are_cut_short(self) -> None:
        lines = (
            "function(again)",
            "  add_compile_options(-Wall)",
            "  again()",
            "endfunction()",
            "again()",
            "function(once target flag)",
            "  target_compile_options(${target} PRIVATE ${flag})",
            "endfunction()",
            # A call with the same arguments sets the same again: not followed.
            "once(t1 -g)",
            "once(t1 -g)",
            "once(t2 -O2)",
            "once(t3 -O3)",
        )
        expected = [("-Wall", None, ANY), ("-g", "t1", ANY), ("-O2", "t2", ANY)]
        with mock.patch.object(evaluation, "MOST_CALLS", 2):
            self.assertEqual(_options(_listed(*lines)), expected)

    def test_a_quoted_argument_is_one_whatever_value_it_takes(self) -> None:
        found = _listed(
            "if(MSVC)",
            "  set(FLAGS /O2)",
            "else()",
            "  set(FLAGS -O2)",
            "endif()",
            "function(build target flags extra)",
            "  target_compile_options(${target} PRIVATE ${extra})",
            "endfunction()",
            'build(app "${FLAGS}" -g)',
        )
        self.assertEqual(_options(found), [("-g", "app", ANY)])

    def test_parsed_arguments(self) -> None:
        found = _listed(
            "function(configure)",
            '  cmake_parse_arguments(ARG "GLOBAL" "TARGET" "OPTIONS" ${ARGN})',
            "  if(ARG_GLOBAL)",
            "    add_compile_options(${ARG_OPTIONS})",
            "  endif()",
            "  target_compile_options(${ARG_TARGET} PRIVATE ${ARG_UNPARSED_ARGUMENTS})",
            "endfunction()",
            "function(by_argv)",
            '  cmake_parse_arguments(PARSE_ARGV 0 ARG "" "TARGET" "")',
            "  target_compile_options(${ARG_TARGET} PRIVATE -g)",
            "endfunction()",
            "configure(GLOBAL stray TARGET app OPTIONS -Wall -Wextra)",
            "configure(TARGET lib)",
            "by_argv(TARGET tool)",
            "cmake_parse_arguments(X)",
        )
        self.assertEqual(
            _options(found),
            [
                ("-Wall", None, ANY),
                ("-Wextra", None, ANY),
                ("stray", "app", ANY),
                ("${ARG_UNPARSED_ARGUMENTS}", "lib", ANY),
                ("-g", "tool", ANY),
            ],
        )


class FileTests(unittest.TestCase):
    def test_includes_and_subdirectories_are_followed(self) -> None:
        files = {
            "CMakeLists.txt": _lines(
                "project(app)",
                "list(APPEND CMAKE_MODULE_PATH ${PROJECT_SOURCE_DIR}/cmake)",
                "include(Warnings)",
                "include(Warnings)",
                "include(cmake/Other.cmake)",
                "include(Missing)",
                "include()",
                "set(CMAKE_CXX_STANDARD 20)",
                "add_subdirectory(src)",
                "add_subdirectory(missing)",
                "add_subdirectory()",
                "project()",
            ),
            "cmake/Warnings.cmake": _lines("include_guard()", "add_compile_options(-Wall)"),
            "cmake/Other.cmake": _lines("add_compile_options(-Wextra ${CMAKE_CURRENT_LIST_DIR})"),
            "src/CMakeLists.txt": _lines(
                "project(sub)",
                "if(PROJECT_IS_TOP_LEVEL)",
                "  add_compile_options(-top)",
                "endif()",
                "set(CMAKE_CXX_STANDARD 17)",
            ),
        }
        found = _facts(files)
        self.assertEqual(_options(found), [("-Wall", None, ANY), ("-Wextra", None, ANY), ("cmake", None, ANY)])
        self.assertEqual(_settings(found, "CMAKE_CXX_STANDARD"), [("17", ANY, False), ("20", ANY, False)])

    def test_files_nothing_reaches(self) -> None:
        files = {
            "CMakeLists.txt": _lines(
                "project(top)", "if(PROJECT_IS_TOP_LEVEL)", "  add_compile_options(-top)", "endif()"
            ),
            "examples/CMakeLists.txt": _lines("add_compile_options(-example)"),
            "cmake/Unused.cmake": _lines("add_compile_options(-unused)"),
        }
        unused = _requiring("cmake/Unused.cmake is included")
        self.assertEqual(
            _options(_facts(files)), [("-top", None, ANY), ("-example", None, ANY), ("-unused", None, unused)]
        )

    def test_includes_that_would_never_end(self) -> None:
        files = {
            "CMakeLists.txt": _lines("include(a.cmake)"),
            "a.cmake": _lines("add_compile_options(-a)", "include(a.cmake)"),
        }
        self.assertEqual(_options(_facts(files)), [("-a", None, ANY)])

    def test_what_cannot_be_evaluated_is_unknown(self) -> None:
        unknowns = [(fact.subject, fact.reason) for fact in _listed("if(A)") if isinstance(fact, Unknown)]
        self.assertEqual(unknowns, [("the CMake file CMakeLists.txt", "line 1: if() is never closed with endif()")])
        with mock.patch.object(evaluation, "MOST_COMMANDS", 3):
            [unknown] = (fact for fact in _listed(*["set(A 1)"] * 5) if isinstance(fact, Unknown))
        self.assertEqual(unknown.reason, "evaluation stopped after 3 commands")


PROPERTIES = (
    'set_target_properties(app lib PROPERTIES CXX_EXTENSIONS OFF COMPILE_OPTIONS "-Wall;-Wextra")',
    "set_target_properties(app)",
    "set_property(TARGET app APPEND PROPERTY COMPILE_WARNING_AS_ERROR ON)",
    "set_property(DIRECTORY PROPERTY COMPILE_OPTIONS -Wshadow)",
    "set_property(GLOBAL PROPERTY CUSTOM x)",
    "set_property(TARGET app PROPERTY)",
    "set_property(SOURCE a.cpp PROPERTY COMPILE_OPTIONS -O0)",
)
PROPERTY_OPTIONS = [
    ("-Wall", "app", ANY),
    ("-Wextra", "app", ANY),
    ("-Wall", "lib", ANY),
    ("-Wextra", "lib", ANY),
    # COMPILE_WARNING_AS_ERROR passes each compiler its flag.
    ("-Werror", "app", Applies(compilers=frozenset({"gcc", "clang", "appleclang", "intel", "flang"}))),
    ("/WX", "app", MSVC),
    ("-Wshadow", None, ANY),
]


class CommandTests(unittest.TestCase):
    def test_options_definitions_and_link_options(self) -> None:
        found = _listed(
            "add_compile_definitions(_FORTIFY_SOURCE=2 -DNDEBUG)",
            'add_definitions("-DA -DB")',
            "target_compile_definitions(app PUBLIC X)",
            "target_link_options(app PRIVATE -pie)",
            "add_link_options(-z)",
            "target_link_libraries(app PRIVATE fmt -fsanitize=address)",
            "target_compile_options()",
            "target_link_libraries()",
            "target_compile_options(app BEFORE INTERFACE $<$<CXX_COMPILER_ID:MSVC>:/W4;/WX>)",
        )
        self.assertEqual(
            _options(found),
            [
                ("-D_FORTIFY_SOURCE=2", None, ANY),
                ("-DNDEBUG", None, ANY),
                ("-DA", None, ANY),
                ("-DB", None, ANY),
                ("-DX", "app", ANY),
                ("-pie", "app", ANY),
                ("-z", None, ANY),
                ("-fsanitize=address", "app", ANY),
                ("/W4", "app", MSVC),
                ("/WX", "app", MSVC),
            ],
        )

    def test_properties(self) -> None:
        found = _listed(*PROPERTIES)
        self.assertEqual(_options(found), PROPERTY_OPTIONS)
        settings = [(fact.name, fact.target, fact.value) for fact in found if isinstance(fact, BuildSetting)]
        self.assertEqual(
            settings,
            [
                ("CXX_EXTENSIONS", "app", "OFF"),
                ("CXX_EXTENSIONS", "lib", "OFF"),
                ("COMPILE_WARNING_AS_ERROR", "app", "ON"),
            ],
        )

    def test_tests_and_dependencies(self) -> None:
        files = {
            "CMakeLists.txt": _lines(
                "enable_testing()", "add_test(NAME a COMMAND a)", "include(cmake/CPM.cmake)", "CPMAddPackage(x)"
            ),
            "test/CMakeLists.txt": _lines(
                "include(CTest)", "gtest_discover_tests(t)", "FetchContent_Declare(x)", "option(A)"
            ),
        }
        found = [
            (type(fact).__name__, fact.origin.path, fact.value if isinstance(fact, Setting) else fact.manager)
            for fact in _facts(files)
            if isinstance(fact, (Setting, Declared))
        ]
        self.assertEqual(
            found,
            [
                ("Setting", "CMakeLists.txt", True),
                ("Setting", "CMakeLists.txt", "add_test"),
                ("Setting", "CMakeLists.txt", ("a", "a")),
                ("Declared", "CMakeLists.txt", "CPM"),
                ("Setting", "test/CMakeLists.txt", True),
                ("Setting", "test/CMakeLists.txt", "gtest_discover_tests"),
                ("Declared", "test/CMakeLists.txt", "FetchContent"),
            ],
        )

    def test_add_test_records_name_and_command(self) -> None:
        found = _listed(
            "add_test(NAME fuzz_tester_run COMMAND fuzz_tester -max_total_time=10)",
            "add_test(old_style old_tool --flag)",
            "gtest_discover_tests(t)",
        )
        tests = [fact.value for fact in found if isinstance(fact, Setting) and fact.key == "test"]
        self.assertEqual(
            tests, [("fuzz_tester_run", "fuzz_tester", "-max_total_time=10"), ("old_style", "old_tool", "--flag")]
        )


def _preset_settings(*files: tuple[str, object]) -> list[tuple[object, str, str, frozenset[str] | None]]:
    facts = preset_facts({path: json.dumps(content) for path, content in files})
    found = (fact for fact in facts if isinstance(fact, BuildSetting))
    return [(fact.origin.at[1], fact.name, fact.value, fact.applies.platforms) for fact in found]


def _preset_condition(condition: object) -> list[Applies]:
    presets = {"configurePresets": [{"name": "p", "condition": condition, "cacheVariables": {"A": "1"}}]}
    facts = preset_facts({"CMakePresets.json": json.dumps(presets)})
    return [fact.applies for fact in facts if isinstance(fact, BuildSetting)]


def _preset(*requirements: str, platforms: frozenset[str] | None = None) -> Applies:
    return Applies(platforms=platforms, requires=frozenset({"configured with the p preset", *requirements}))


PRESETS = {
    "configurePresets": [
        {"name": "base", "hidden": True, "cacheVariables": {"CMAKE_CXX_FLAGS": "-Wall", "A": True, "B": "x"}},
        {"name": "ci", "inherits": "base", "cacheVariables": {"B": None, "C": {"type": "BOOL", "value": False}}},
        {"name": "win", "inherits": ["ci", "missing"], "condition": {"type": "equals", "lhs": HOST, "rhs": "Windows"}},
        {"name": "loop", "inherits": "loop", "cacheVariables": "not a table"},
        {"name": "odd", "inherits": 3},
        {"name": 3},
    ]
}


class PresetTests(unittest.TestCase):
    def test_visible_presets_set_their_cache_variables_and_those_they_inherit(self) -> None:
        windows = frozenset({"windows"})
        self.assertEqual(
            _preset_settings(("CMakePresets.json", PRESETS)),
            [
                ("ci", "CMAKE_CXX_FLAGS", "-Wall", None),
                ("ci", "A", "TRUE", None),
                ("ci", "C", "FALSE", None),
                ("win", "CMAKE_CXX_FLAGS", "-Wall", windows),
                ("win", "A", "TRUE", windows),
                ("win", "C", "FALSE", windows),
            ],
        )

    def test_user_presets_inherit_the_projects(self) -> None:
        user = {"configurePresets": [{"name": "mine", "inherits": "ci", "cacheVariables": {"D": "1"}}]}
        found = _preset_settings(("CMakePresets.json", PRESETS), ("CMakeUserPresets.json", user))
        self.assertEqual([setting for setting in found if setting[0] == "mine"][-1], ("mine", "D", "1", None))
        facts = preset_facts({"CMakePresets.json": json.dumps(PRESETS)})
        self.assertIn("-Wall", [fact.option for fact in facts if isinstance(fact, CompilerOption)])

    def test_host_conditions(self) -> None:
        not_windows = frozenset(PLATFORMS) - {"windows"}
        linux_or_mac = frozenset({"linux", "macos"})
        for condition, expected in (
            ({"type": "notEquals", "lhs": HOST, "rhs": "Windows"}, [_preset(platforms=not_windows)]),
            ({"type": "inList", "string": HOST, "list": ["Linux", "Darwin"]}, [_preset(platforms=linux_or_mac)]),
            ({"type": "notInList", "string": HOST, "list": "Linux"}, [_preset()]),
            (
                {"type": "not", "condition": {"type": "equals", "lhs": HOST, "rhs": "Windows"}},
                [_preset(platforms=not_windows)],
            ),
        ):
            with self.subTest(condition=condition):
                self.assertEqual(_preset_condition(condition), expected)

    def test_other_conditions(self) -> None:
        unknown = [_preset("the preset's condition")]
        for condition, expected in (
            ({"type": "anyOf", "conditions": [{"type": "const", "value": True}]}, [_preset()]),
            ({"type": "allOf", "conditions": [{"type": "const", "value": False}]}, []),
            ({"type": "matches", "string": "x", "regex": "x"}, unknown),
            (False, []),
            ("odd", unknown),
        ):
            with self.subTest(condition=condition):
                self.assertEqual(_preset_condition(condition), expected)

    def test_presets_that_do_not_parse_are_unknown(self) -> None:
        self.assertEqual([type(fact).__name__ for fact in preset_facts({"CMakePresets.json": "{"})], ["Unknown"])
        self.assertEqual(list(preset_facts({"CMakePresets.json": "[]"})), [])


CUSTOM_TARGETS = {
    "CMakeLists.txt": _lines(
        "project(app)",
        "find_program(TIDY clang-tidy)",
        "add_custom_target(lint COMMAND ${TIDY} -p build src/a.cpp COMMAND echo done DEPENDS format VERBATIM)",
        "add_custom_target(format clang-format -i src/a.cpp)",
        "add_custom_target(always ALL COMMAND echo built)",
        "add_custom_target(docs)",
        "add_dependencies(docs lint)",
        "add_custom_target()",
        "add_dependencies()",
    ),
    "tools/CMakeLists.txt": _lines("add_custom_target(check COMMAND ./run.sh WORKING_DIRECTORY x)"),
}


def _expanded(line: str) -> list[tuple[tuple[str, ...], str | None, str]]:
    with temp_project({**CUSTOM_TARGETS, **github_job("lint", line)}) as root:
        facts = make_context(root).facts
    return [(fact.argv, fact.directory, str(fact.origin)) for fact in facts.of(Command) if fact.via]


class CustomTargetTests(unittest.TestCase):
    def test_building_a_custom_target_runs_its_commands_after_its_dependencies(self) -> None:
        self.assertEqual(
            _expanded("cmake --build build --target docs lint check -j 4"),
            [
                (("clang-format", "-i", "src/a.cpp"), None, "CMakeLists.txt:add_custom_target[4]"),
                (("clang-tidy", "-p", "build", "src/a.cpp"), None, "CMakeLists.txt:add_custom_target[3]"),
                (("echo", "done"), None, "CMakeLists.txt:add_custom_target[3]"),
                (("./run.sh",), "tools", "tools/CMakeLists.txt:add_custom_target[1]"),
            ],
        )

    def test_a_build_without_targets_builds_every_all_target(self) -> None:
        expected = [(("echo", "built"), None, "CMakeLists.txt:add_custom_target[5]")]
        self.assertEqual(_expanded("cmake --build build"), expected)

    def test_other_commands_are_not_expanded(self) -> None:
        for line in ("cmake -S . -B build", "make lint", "cmake --build build --target missing"):
            with self.subTest(line=line):
                self.assertEqual(_expanded(line), [])

    def test_a_project_is_evaluated_once(self) -> None:
        with temp_project({"CMakeLists.txt": "add_compile_options(-Wall)\n"}) as root:
            context = make_context(root)
            self.assertIs(cmake.cmake_project(context), cmake.cmake_project(context))
            [option] = context.facts.of(CompilerOption)
        self.assertEqual(option.origin, Origin(path="CMakeLists.txt", at=("add_compile_options", 1)))
