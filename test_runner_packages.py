"""Exercise package recovery control flow without installing host packages."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class RunnerPackageTests(unittest.TestCase):
    def run_script(self,scenario):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);binary=root/'bin';binary.mkdir()
            wrappers={
                'sudo':'exec "$@"',
                'timeout':'shift; shift; exec "$@"',
                'find':'exit 0',
                'dpkg-query': 'if [ "$SCENARIO" = installed ]; then echo "install ok installed"; else exit 1; fi',
                'apt-get': '''echo "$*" >> "$CALLS"
case " $* " in
  *" update "*)
    if [ "$SCENARIO" = retry ] && [ ! -f "$FIRST_UPDATE" ]; then touch "$FIRST_UPDATE"; exit 124; fi
    [ "$SCENARIO" != failure ] ;;
  *" install "*)
    if [ "$SCENARIO" = retry ] && [ ! -f "$FIRST_UPDATE" ]; then exit 100; fi
    [ "$SCENARIO" != failure ] ;;
esac'''}
            for name,body in wrappers.items():
                p=binary/name;p.write_text('#!/bin/sh\n'+body+'\n');p.chmod(0o755)
            env=dict(os.environ,PATH=str(binary)+os.pathsep+os.environ['PATH'],SCENARIO=scenario,
                CALLS=str(root/'calls'),FIRST_UPDATE=str(root/'first-update'))
            result=subprocess.run(['bash','scripts/install-runner-packages.sh','ffmpeg'],env=env,capture_output=True,text=True,timeout=15)
            calls=(root/'calls').read_text().splitlines() if (root/'calls').exists() else []
            return result,calls

    def test_cached_indexes_avoid_unnecessary_update(self):
        result,calls=self.run_script('cached')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(len(calls),1);self.assertIn(' install ',calls[0])

    def test_timeout_is_retried_and_then_install_recovers(self):
        result,calls=self.run_script('retry')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(sum(x.endswith(' update') for x in calls),2)
        self.assertEqual(sum(' install ' in x for x in calls),2)

    def test_persistent_failure_is_bounded_and_already_installed_is_noop(self):
        result,calls=self.run_script('failure')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(sum(x.endswith(' update') for x in calls),2)
        result,calls=self.run_script('installed')
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(calls,[])
