"""Publication must never label old binaries with a new version."""
import base64
import json
import os
from pathlib import Path
import tempfile
import textwrap
import unittest
from unittest.mock import patch


def verification_script():
    content = (Path(__file__).parent / '.github/workflows/release.yml').read_text()
    return textwrap.dedent(content.split("python - <<'PY'\n", 1)[1].split('\n          PY', 1)[0])


class ReleaseChecks(unittest.TestCase):
    def build(self, **updates):
        result = {'conclusion': 'success', 'status': 'completed', 'path': '.github/workflows/desktop.yml',
                  'head_repository': {'full_name': 'test/apply'}, 'head_branch': 'main', 'head_sha': 'test-sha'}
        return dict(result, **updates)

    def test_release_rejects_old_installer_version(self):
        encoded = base64.b64encode(json.dumps({'version': '0.1.0'}).encode()).decode()
        responses = [json.dumps(self.build()).encode(), json.dumps({'content': encoded}).encode()]
        with patch.dict(os.environ, GH_REPO='test/apply', BUILD_RUN_ID='1', RELEASE_TAG='v0.2.0', ANDROID_BUILD_RUN_ID=''), \
             patch('subprocess.check_output', side_effect=responses):
            with self.assertRaisesRegex(AssertionError, 'does not match'):
                exec(verification_script(), {})

    def test_release_rejects_android_from_different_commit(self):
        encoded = base64.b64encode(json.dumps({'version': '0.2.0'}).encode()).decode()
        responses = [json.dumps(self.build()).encode(), json.dumps({'content': encoded}).encode(),
                     json.dumps(self.build(path='.github/workflows/android.yml', head_sha='other-sha')).encode()]
        with patch.dict(os.environ, GH_REPO='test/apply', BUILD_RUN_ID='1', RELEASE_TAG='v0.2.0', ANDROID_BUILD_RUN_ID='2'), \
             patch('subprocess.check_output', side_effect=responses):
            with self.assertRaisesRegex(AssertionError, 'same commit'):
                exec(verification_script(), {})


if __name__ == '__main__':
    unittest.main()
