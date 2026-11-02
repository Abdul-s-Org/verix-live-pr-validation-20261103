"""Property checks run with the development dependency set installed."""

import unittest

try:
    from hypothesis import given, settings, strategies as st
except ImportError:
    st = None

from verix.engine.policy import evaluate


if st is not None:

    class PolicyProperties(unittest.TestCase):
        @given(
            st.lists(st.sampled_from(["valid", "suspect", "invalid", "unknown"]), max_size=30),
            st.sampled_from(["low", "medium", "high"]),
            st.booleans(),
        )
        def test_same_inputs_always_replay(self, states, level, incomplete):
            self.assertEqual(
                evaluate(states, level, incomplete), evaluate(list(states), level, incomplete)
            )

        @given(st.lists(st.sampled_from(["valid", "suspect", "unknown"]), max_size=30))
        def test_invalid_evidence_always_blocks(self, states):
            self.assertEqual(evaluate(states + ["invalid"], "high", False), "block")

        @settings(max_examples=25, deadline=None)
        @given(st.integers(min_value=1, max_value=15))
        def test_entire_dependency_chain_becomes_suspect(self, length):
            import subprocess
            import tempfile
            from pathlib import Path
            from verix.engine.service import Engine

            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)

                def git(*args):
                    subprocess.run(["git", "-C", directory, *args], check=True, capture_output=True)

                git("init", "-q")
                git("config", "user.name", "Property test")
                git("config", "user.email", "test@example.invalid")
                (root / "source").write_text("before")
                git("add", "source")
                git("commit", "-qm", "base")
                engine = Engine(root)
                try:
                    session = engine.start("property-test")
                    observation = engine.observe(session, "source")
                    parent = observation
                    chain = []
                    for _ in range(length):
                        parent = engine.claim(session, "Dependent claim", [], [parent])
                        chain.append(parent)
                    (root / "source").write_text("after")
                    states = engine.analyze(session)["states"]
                    self.assertTrue(all(states[node] == "suspect" for node in chain))
                finally:
                    engine.store.db.close()
else:

    class MissingHypothesis(unittest.TestCase):
        @unittest.skip("Install .[dev] to run Hypothesis property tests")
        def test_property_dependencies(self):
            pass
