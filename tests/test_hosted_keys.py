"""
A hosted instance never spends a key it finds in its own environment (R113).

The environment on a hosted instance is the operator's. Before R113,
`resolve_api_key` fell back to `GOOGLE_API_KEY` and `env_openai_key` read five
provider variables, in any mode. So one secret set on Fly would have paid for
every user's bullets, every embedding and every import. Today none is set
(`fly.toml`, decision 4), so nothing changes on the instance; this pins it.

Local mode is unchanged: a developer's `.env` key is theirs.
"""

import ast
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from tools.generation import llm_backends  # noqa: E402

KEYS = {"GOOGLE_API_KEY": "env-gemini", "OPENAI_API_KEY": "env-openai",
        "GROQ_API_KEY": "env-groq"}
KEY_NAMES = ("GOOGLE_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY",
             "OPENROUTER_API_KEY", "TOGETHER_API_KEY", "DEEPSEEK_API_KEY")


def mode(name):
    env = {**KEYS, "JOBSCOUT_MODE": name}
    if name == "hosted":
        from tests.signed_in import SECRET
        env["JOBSCOUT_SESSION_SECRET"] = SECRET
    return mock.patch.dict(os.environ, env)


class TestTheTwoReaders(unittest.TestCase):

    def test_local_reads_the_environment(self):
        with mode("local"):
            self.assertEqual(config.resolve_api_key(), "env-gemini")
            self.assertEqual(llm_backends.env_openai_key(), "env-openai")

    def test_hosted_ignores_it(self):
        with mode("hosted"):
            self.assertEqual(config.resolve_api_key(), "")
            self.assertEqual(config.resolve_api_key(None), "")
            self.assertEqual(llm_backends.env_openai_key(), "")

    def test_the_requests_key_is_used_in_both(self):
        for name in ("local", "hosted"):
            with self.subTest(mode=name), mode(name):
                self.assertEqual(config.resolve_api_key("from-request"), "from-request")

    def test_an_unknown_mode_is_refused_not_guessed(self):
        from tools.accounts import HostingMisconfigured
        with mode("hostd"):
            with self.assertRaises(HostingMisconfigured):
                config.resolve_api_key()


class TestWhatAHostedRunGets(unittest.TestCase):

    def test_no_request_key_means_no_model(self):
        from agents.orchestrator import backend_status
        with mode("hosted"), \
                mock.patch.object(llm_backends, "ollama_is_running", return_value=False):
            status = backend_status()
        self.assertEqual(status["backend"], "none", status)

    def test_embeddings_stay_local_whatever_the_environment_holds(self):
        from tools.resume import embedding_scorer as es
        with mode("hosted"), mock.patch.object(es, "_BACKEND", None), \
                mock.patch.object(es, "EMBEDDING_BACKEND", "auto"):
            self.assertEqual(es.active_backend()[0], "local")


class TestNothingElseReadsAKey(unittest.TestCase):
    """
    The count, not the pair (R80): walk the syntax tree for any environment
    read of a key's name. Prose that names a variable is not a read.
    """

    ALLOWED = {"config.py", "tools/generation/llm_backends.py"}

    def test_only_the_two_readers_touch_key_variables(self):
        readers = set()
        for path in list((ROOT / "agents").rglob("*.py")) + \
                list((ROOT / "tools").rglob("*.py")) + \
                list((ROOT / "scripts").rglob("*.py")) + \
                [ROOT / "config.py", ROOT / "app.py", ROOT / "api" / "main.py"]:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and node.value in KEY_NAMES:
                    parent_reads = self._is_env_read(tree, node)
                    if parent_reads:
                        readers.add(path.relative_to(ROOT).as_posix())
        # Equal, not a subset: finding none would mean the walk is blind, and
        # a blind walk passes a subset check.
        self.assertEqual(readers, self.ALLOWED)

    @staticmethod
    def _is_env_read(tree, constant) -> bool:
        """The constant is an argument to getenv/environ.get, or an environ key,
        or a member of a tuple that a loop feeds to one (llm_backends' shape)."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and constant in node.args:
                name = ast.unparse(node.func)
                if name.endswith(("getenv", "environ.get")):
                    return True
            if isinstance(node, ast.Subscript) and node.slice is constant:
                if ast.unparse(node.value).endswith("environ"):
                    return True
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                    and node.value is constant:
                return True   # `API_KEY_ENV_VAR = "GOOGLE_API_KEY"`: a name for a read
            if isinstance(node, ast.For) and isinstance(node.iter, ast.Tuple) \
                    and constant in node.iter.elts:
                return True
        return False


if __name__ == "__main__":
    unittest.main()
