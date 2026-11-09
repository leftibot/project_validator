import unittest

from project_validator.text import JsonSyntaxError, check_json, matching_names, pattern


class MatchingNamesTests(unittest.TestCase):
    def test_reports_each_name_once_in_pattern_order(self) -> None:
        patterns = (pattern("b", "bee"), pattern("a", "ay"), pattern("b", "buzz"))
        self.assertEqual(matching_names(["ay bee", "buzz"], patterns), ["b", "a"])

    def test_is_case_insensitive(self) -> None:
        self.assertEqual(matching_names(["CLANG"], (pattern("clang", "clang"),)), ["clang"])


class CheckJsonTests(unittest.TestCase):
    def test_only_json_whitespace_is_whitespace(self) -> None:
        # The JSON grammar allows only space, tab, newline and carriage return between tokens; `\s` also accepts
        # \x0b, \x0c and \x1c-\x1f, which json.loads rejects.
        for separator in ("\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x1f"):
            with self.subTest(separator=separator), self.assertRaises(JsonSyntaxError):
                check_json(f"[1{separator}]")
            with self.subTest(trailing=separator), self.assertRaises(JsonSyntaxError):
                check_json(f"[1]{separator}")
        for text in ("[1]\xa0", "[1]\u3000", "[1\u0661]"):
            with self.subTest(text=text), self.assertRaises(JsonSyntaxError):
                check_json(text)
        check_json("[1 \t\r\n]")
        check_json("[1] \t\r\n")
