add_executable(fuzz_tester fuzz_tester.cpp)
target_compile_options(fuzz_tester PRIVATE -fsanitize=fuzzer,undefined,address)
target_link_options(fuzz_tester PRIVATE -fsanitize=fuzzer,undefined,address)
add_test(NAME fuzz_tester_run COMMAND fuzz_tester -max_total_time=10)
