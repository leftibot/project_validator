import unittest
from unittest import mock

from project_validator import yaml_support


class YamlSupportTests(unittest.TestCase):
    def test_a_missing_install_is_detected(self) -> None:
        with mock.patch("importlib.import_module", side_effect=ImportError):
            self.assertIsNone(yaml_support._import_yaml())

    def test_loading_without_pyyaml_explains_how_to_install_it(self) -> None:
        with mock.patch.object(yaml_support, "_yaml", None), self.assertRaises(yaml_support.YamlError) as raised:
            yaml_support.load("a: 1")
        self.assertEqual(str(raised.exception), yaml_support.MISSING_MESSAGE)

    def test_checking_without_pyyaml_explains_how_to_install_it(self) -> None:
        with mock.patch.object(yaml_support, "_yaml", None), self.assertRaises(yaml_support.YamlError) as raised:
            yaml_support.check_documents("a: 1")
        self.assertEqual(str(raised.exception), yaml_support.MISSING_MESSAGE)

    def test_invalid_yaml_is_reported_on_one_line(self) -> None:
        with self.assertRaises(yaml_support.YamlError) as raised:
            yaml_support.load("a: [unclosed\n")
        self.assertNotIn("\n", str(raised.exception))

    def test_deep_nesting_is_a_yaml_error_not_a_crash(self) -> None:
        deep = (
            "[" * 5000 + "]" * 5000,
            "{a: " * 5000 + "1" + "}" * 5000,
            "".join("  " * i + "- \n" for i in range(5000)),
        )
        for text in deep:
            with self.subTest(text=text[:12]):
                with self.assertRaisesRegex(yaml_support.YamlError, "nested too deeply to read"):
                    yaml_support.load(text)
                with self.assertRaisesRegex(yaml_support.YamlError, "nested too deeply to read"):
                    yaml_support.check_documents(text)


class TaggedTests(unittest.TestCase):
    def test_local_tags_are_kept_as_tagged_values(self) -> None:
        document = yaml_support.load("a: !reference [.x, script]\nb: !Ref Name\nc: !Sub {x: 1}\n")
        self.assertEqual(
            document,
            {
                "a": yaml_support.Tagged(tag="!reference", value=[".x", "script"]),
                "b": yaml_support.Tagged(tag="!Ref", value="Name"),
                "c": yaml_support.Tagged(tag="!Sub", value={"x": 1}),
            },
        )
