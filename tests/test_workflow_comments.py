"""Execute the workflow's JavaScript with mocked GitHub APIs; never post test comments."""

import json
from pathlib import Path
import shutil
import subprocess
import unittest

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/verix-pr.yml"


@unittest.skipUnless(shutil.which("node"), "Node.js is required for workflow JavaScript tests")
class WorkflowCommentTests(unittest.TestCase):
    def execute(self, *, comments=None, head="head", report=None):
        workflow = yaml.safe_load(WORKFLOW.read_text())
        script = workflow["jobs"]["comment"]["steps"][-1]["with"]["script"]
        fixture = {
            "comments": comments or [],
            "head": head,
            "report": report if report is not None else '{"verdict":"verify","mode":"blocking"}',
        }
        program = """
const fixture = JSON.parse(process.argv[1]);
const script = process.argv[2];
const calls = [];
const github = {
  rest: {
    pulls: {get: async () => ({data: {head: {sha: fixture.head}, base: {sha: 'base'}}})},
    issues: {
      listComments: () => {},
      createComment: async args => calls.push({method: 'create', ...args}),
      updateComment: async args => calls.push({method: 'update', ...args})
    }
  },
  paginate: async () => fixture.comments
};
const context = {repo: {owner: 'owner', repo: 'repo'}, issue: {number: 1},
  payload: {pull_request: {head: {sha: 'head'}, base: {sha: 'base'}}},
  serverUrl: 'https://github.com', runId: 1};
const core = {info: () => {}};
const fakeRequire = name => {
  if (name !== 'fs') throw new Error('Unexpected module');
  return {readFileSync: () => fixture.report};
};
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
new AsyncFunction('github', 'context', 'core', 'require', script)(github, context, core, fakeRequire)
  .then(() => process.stdout.write(JSON.stringify(calls)))
  .catch(error => { console.error(error); process.exitCode = 1; });
"""
        result = subprocess.run(
            ["node", "-e", program, json.dumps(fixture), script],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)

    def test_creates_one_comment_then_updates_existing_bot_comment(self):
        calls = self.execute()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["method"], "create")
        self.assertIn("Verix: verify", calls[0]["body"])
        calls = self.execute(
            comments=[{"id": 7, "user": {"type": "Bot"}, "body": "<!-- verix-report --> previous"}]
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["method"], "update")
        self.assertEqual(calls[0]["comment_id"], 7)

    def test_stale_run_cannot_overwrite_a_newer_revision(self):
        self.assertEqual(self.execute(head="newer-head"), [])

    def test_invalid_or_untrusted_report_text_is_not_posted(self):
        for report in ("not JSON", '{"verdict":"<script>evil</script>","mode":"evil"}'):
            calls = self.execute(report=report)
            self.assertIn("Verix: unresolved", calls[0]["body"])
            self.assertNotIn("evil", calls[0]["body"])

    def test_forks_have_no_comment_job_and_analysis_has_read_only_permissions(self):
        data = yaml.safe_load(WORKFLOW.read_text())
        self.assertEqual(data["permissions"], {"contents": "read"})
        self.assertNotIn("permissions", data["jobs"]["analyze"])
        self.assertIn("head.repo.full_name == github.repository", data["jobs"]["comment"]["if"])
        self.assertNotIn("pull_request_target", WORKFLOW.read_text())
