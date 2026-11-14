"""Expected failures for CMake and Meson reading bugs the corpus audit found (upstream #203 to #206). Each test asserts
the correct behaviour; it starts passing (an "unexpected success") when the bug is fixed, and its decorator goes."""

from __future__ import annotations

import unittest
from collections.abc import Mapping

from project_validator.build_systems.meson import syntax
from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.checks.cxx_extensions import cxx_extensions
from project_validator.checks.out_of_source_build import out_of_source_build
from project_validator.checks.sanitizers import sanitizers
from project_validator.checks.static_analysis import static_analysis
from project_validator.checks.tests_run import tests_run
from project_validator.checks.top_level_guard import top_level_guard
from project_validator.core import Check, Result, Status
from tests.support import CMAKE_PROJECT, github_job, make_context, temp_project

C_PROJECT = "cmake_minimum_required(VERSION 3.21)\nproject(x LANGUAGES C)\n"
CXX_SOURCE = {"src/a.cpp": ""}
TESTS_GUARDED = "if(X_BUILD_TESTS)\n  include(CTest)\n  add_subdirectory(tests)\nendif()\n"
# The pre-3.21 idioms of fmt, Catch2, h3, glfw, simdjson and llama.cpp: a flag computed once, then guarded on.
STANDALONE_FLAGS = (
    "if(NOT DEFINED PROJECT_NAME)\n  set(X_MASTER ON)\nendif()\n"
    + CMAKE_PROJECT
    + 'option(X_BUILD_TESTS "" ${X_MASTER})\n',
    CMAKE_PROJECT
    + "if(NOT DEFINED PROJECT_NAME)\n  set(X_BUILD_TESTS ON)\nelse()\n  set(X_BUILD_TESTS OFF)\nendif()\n",
    CMAKE_PROJECT + "if(CMAKE_PROJECT_NAME STREQUAL PROJECT_NAME)\n  set(X_BUILD_TESTS ON)\nendif()\n",
    CMAKE_PROJECT + 'string(COMPARE EQUAL "${CMAKE_CURRENT_SOURCE_DIR}" "${CMAKE_SOURCE_DIR}" X_BUILD_TESTS)\n',
    CMAKE_PROJECT
    + 'string(\n  COMPARE EQUAL\n  "${CMAKE_SOURCE_DIR}" "${CMAKE_CURRENT_SOURCE_DIR}"\n  X_BUILD_TESTS\n)\n',
    CMAKE_PROJECT + "if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)\n  set(X_BUILD_TESTS ON)\nendif()\n",
)
# cmake_template's PreventInSourceBuilds.cmake, and its older form: the directories compared after resolving symlinks.
RESOLVED_IN_SOURCE = (
    "function(x_assure_out_of_source_builds)\n"
    '  file(REAL_PATH "${CMAKE_SOURCE_DIR}" srcdir)\n'
    '  file(REAL_PATH "${CMAKE_BINARY_DIR}" bindir)\n'
    '  if("${srcdir}" STREQUAL "${bindir}")\n'
    '    message(FATAL_ERROR "Quitting configuration")\n'
    "  endif()\n"
    "endfunction()\n"
    "x_assure_out_of_source_builds()\n",
    'get_filename_component(srcdir "${CMAKE_SOURCE_DIR}" REALPATH)\n'
    'get_filename_component(bindir "${CMAKE_BINARY_DIR}" REALPATH)\n'
    'if("${srcdir}" STREQUAL "${bindir}")\n  message(FATAL_ERROR "no")\nendif()\n',
)
# neovim's add_glob_target(): the command is an add_custom_command's, and the target depends on its output.
GLOB_TARGET = (
    "function(add_glob_target)\n"
    '  cmake_parse_arguments(ARG "" "TARGET;COMMAND" "FLAGS;FILES" ${ARGN})\n'
    "  set(touch_file ${PROJECT_BINARY_DIR}/${ARG_TARGET}.touch)\n"
    "  add_custom_command(OUTPUT ${touch_file}\n"
    "    COMMAND ${ARG_COMMAND} ${ARG_FLAGS} ${ARG_FILES}\n"
    "    COMMAND ${CMAKE_COMMAND} -E touch ${touch_file})\n"
    "  add_custom_target(${ARG_TARGET} DEPENDS ${touch_file})\n"
    "endfunction()\n"
    "find_program(SHELLCHECK_PRG shellcheck)\n"
    "add_glob_target(TARGET lintsh COMMAND ${SHELLCHECK_PRG} FLAGS -x -a FILES scripts/x.sh)\n"
)
# neovim's unittest target: busted runs from a CMake script, `cmake -P`.
RUN_TESTS_SCRIPT = (
    "find_program(BUSTED_PRG busted)\n"
    "execute_process(COMMAND ${BUSTED_PRG} -o test/busted/outputHandler.lua test/${TEST_TYPE})\n"
)
LUA_SPEC = {"test/unit/a_spec.lua": 'describe("a", function() end)\n'}
# cmake_template's myproject_supports_sanitizers(): the default of the ASAN option comes from a compile check.
SUPPORTS_ASAN = (
    "include(CheckCXXSourceCompiles)\n"
    "macro(x_supports_sanitizers)\n"
    '  if((CMAKE_CXX_COMPILER_ID MATCHES ".*Clang.*" OR CMAKE_CXX_COMPILER_ID MATCHES ".*GNU.*") AND WIN32)\n'
    "    set(SUPPORTS_ASAN OFF)\n"
    "  else()\n"
    "    if(NOT WIN32)\n"
    '      set(CMAKE_REQUIRED_FLAGS "-fsanitize=address")\n'
    '      check_cxx_source_compiles("int main() { return 0; }" HAS_ASAN_LINK_SUPPORT)\n'
    "      if(HAS_ASAN_LINK_SUPPORT)\n"
    "        set(SUPPORTS_ASAN ON)\n"
    "      else()\n"
    "        set(SUPPORTS_ASAN OFF)\n"
    "      endif()\n"
    "    else()\n"
    "      set(SUPPORTS_ASAN ON)\n"
    "    endif()\n"
    "  endif()\n"
    "endmacro()\n"
    "x_supports_sanitizers()\n"
    'option(x_ENABLE_SANITIZER_ADDRESS "Enable address sanitizer" ${SUPPORTS_ASAN})\n'
    'option(x_ENABLE_SANITIZER_UNDEFINED "Enable undefined sanitizer" ON)\n'
)


def _run(check: Check, files: Mapping[str, str]) -> Result:
    """The result of `check` in a throw-away project of `files`, judged strictly (unknown is an error)."""
    with temp_project(files) as root:
        return check.run(make_context(root))


def _built_target(target: str) -> dict[str, str]:
    """A GitHub workflow that configures the project and builds its custom target `target`."""
    return github_job("ubuntu-latest", "cmake -S . -B build", f"cmake --build build --target {target}")


class TopLevelGuardIdiomTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #203: a guard on a flag computed from the pre-3.21 idioms is not seen
    def test_a_flag_computed_from_a_pre_3_21_idiom_guards(self) -> None:
        """A variable computed from NOT DEFINED PROJECT_NAME, CMAKE_PROJECT_NAME STREQUAL PROJECT_NAME, a source
        directory comparison or string(COMPARE EQUAL ...) guards the tests (fmt, Catch2, h3, glfw, simdjson,
        llama.cpp)."""
        for flag in STANDALONE_FLAGS:
            with self.subTest(flag=flag):
                result = _run(top_level_guard, {"CMakeLists.txt": flag + TESTS_GUARDED, **CXX_SOURCE})
                self.assertEqual(result.status, Status.PASS, result)

    @unittest.expectedFailure  # upstream #203: directories compared after REAL_PATH are not an in-source guard
    def test_the_directories_compared_after_resolving_symlinks_prevent_in_source_builds(self) -> None:
        """cmake_template's own PreventInSourceBuilds.cmake, the file the hint names, compares the source and binary
        directories through file(REAL_PATH) copies (older: get_filename_component REALPATH) and stops the build."""
        for prevent in RESOLVED_IN_SOURCE:
            with self.subTest(prevent=prevent.splitlines()[0]):
                files = {"CMakeLists.txt": CMAKE_PROJECT + "include(cmake/PreventInSourceBuilds.cmake)\n"}
                result = _run(
                    out_of_source_build, {**files, "cmake/PreventInSourceBuilds.cmake": prevent, **CXX_SOURCE}
                )
                self.assertEqual(result.status, Status.PASS, result)


class SkippedConstructTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #204: the legacy COMPILE_FLAGS target property is not an option source
    def test_the_compile_flags_property_holds_compiler_options(self) -> None:
        """googletest sets -Wall -Wshadow -Wconversion through COMPILE_FLAGS: the check lists only the missing flags
        (a warning), not "no compiler warning flags found"."""
        build = 'add_library(x src/a.cpp)\nset_target_properties(x PROPERTIES COMPILE_FLAGS "-Wall -Wshadow")\n'
        result = _run(compiler_warnings, {"CMakeLists.txt": CMAKE_PROJECT + build, **CXX_SOURCE})
        self.assertEqual(result.status, Status.WARN, result)
        self.assertIn("-Wpedantic", result.message)

    @unittest.expectedFailure  # upstream #204: a property value with two possible values loses the properties after
    def test_c_extensions_off_counts_after_a_property_set_from_a_branched_variable(self) -> None:
        """glfw's set_target_properties(glfw PROPERTIES OUTPUT_NAME ${GLFW_LIB_NAME} ... C_EXTENSIONS OFF), where the
        name is set in both branches of an if(), disables C extensions on the target. The issue's plain repro passes:
        the trigger is the branched value before the property."""
        build = (
            "add_library(glfw a.c)\n"
            "if(UNIX AND BUILD_SHARED_LIBS)\n  set(GLFW_LIB_NAME glfw)\nelse()\n  set(GLFW_LIB_NAME glfw3)\nendif()\n"
            "set_target_properties(glfw PROPERTIES OUTPUT_NAME ${GLFW_LIB_NAME} C_STANDARD 99 C_EXTENSIONS OFF)\n"
        )
        result = _run(cxx_extensions, {"CMakeLists.txt": C_PROJECT + build, "a.c": ""})
        self.assertEqual(result.status, Status.PASS, result)

    @unittest.expectedFailure  # upstream #204: a target depending on an add_custom_command output runs nothing
    def test_a_wrapper_around_add_custom_command_runs_its_linter(self) -> None:
        """neovim's lintsh target, made by add_glob_target() (cmake_parse_arguments, add_custom_command OUTPUT, a
        target DEPENDS on it), runs shellcheck when CI builds it; a plain add_custom_target with the command is
        credited."""
        files = {"CMakeLists.txt": C_PROJECT + GLOB_TARGET, "scripts/x.sh": "#!/bin/sh\n", **_built_target("lintsh")}
        result = _run(static_analysis, files)
        self.assertIn("Shell: shellcheck runs", result.message)

    @unittest.expectedFailure  # upstream #204: a custom target running `cmake -P script` is not followed into it
    def test_a_cmake_script_test_runner_runs_the_tests_it_executes(self) -> None:
        """neovim's unittest target runs busted through `cmake -D TEST_TYPE=unit -P cmake/RunTests.cmake`: the Lua
        tests count as run, exactly as when the target runs busted itself."""
        script = "${CMAKE_COMMAND} -D TEST_TYPE=unit -P ${PROJECT_SOURCE_DIR}/cmake/RunTests.cmake"
        runner = f"add_custom_target(unittest COMMAND {script})\n"
        direct = "add_custom_target(unittest COMMAND busted test/unit)\n"
        ci = _built_target("unittest")
        expected = _run(tests_run, {"CMakeLists.txt": C_PROJECT + direct, **LUA_SPEC, **ci})
        self.assertNotIn("no CI configuration runs busted", expected.message)
        files = {"CMakeLists.txt": C_PROJECT + runner, "cmake/RunTests.cmake": RUN_TESTS_SCRIPT, **LUA_SPEC, **ci}
        self.assertEqual(_run(tests_run, files).message, expected.message)

    @unittest.expectedFailure  # upstream #204: a configure_package_config_file template is parsed as a build file
    def test_a_package_config_template_is_not_a_build_file(self) -> None:
        """fortran-lang/stdlib's config/template.cmake starts with @PACKAGE_INIT@: a template rendered before it is
        read, skipped like YAML templates, so a project without warning flags fails instead of erroring "not read"."""
        template = (
            '@PACKAGE_INIT@\n\nif(NOT TARGET "@PROJECT_NAME@::@PROJECT_NAME@")\n  include("x-targets.cmake")\nendif()\n'
        )
        files = {"CMakeLists.txt": CMAKE_PROJECT, "config/template.cmake": template, **CXX_SOURCE}
        result = _run(compiler_warnings, files)
        self.assertEqual(result.status, Status.FAIL, result)
        self.assertIn("no compiler warning flags found", result.message)


class MesonMultiLineConditionTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #205: a newline inside parentheses is not whitespace to the Meson parser
    def test_a_parenthesised_condition_continued_over_lines_parses(self) -> None:
        """GNOME/glib's gnulib meson.build: an if() whose parenthesised boolean expression runs over four lines is
        valid Meson (newlines inside parentheses are whitespace) and parses to one If statement."""
        text = "if (a == '1' and\n    b) or\n   (c and\n    d)\n  x = true\nendif\n"
        nodes = syntax.parse(text)
        self.assertEqual([type(node).__name__ for node in nodes], ["If"])


class SanitizerOptionDefaultTests(unittest.TestCase):
    @unittest.expectedFailure  # upstream #206: an option default from a compile check is "off", not unknown
    def test_an_option_defaulting_to_a_compile_check_result_is_unknown(self) -> None:
        """cmake_template's ENABLE_SANITIZER_ADDRESS defaults to ${SUPPORTS_ASAN}, set from check_cxx_source_compiles,
        which the validator cannot run: the answer is unknown (an error without --allow-unknown), not "missing"."""
        result = _run(sanitizers, {"CMakeLists.txt": CMAKE_PROJECT + SUPPORTS_ASAN, **CXX_SOURCE})
        self.assertEqual(result.status, Status.ERROR, result)
