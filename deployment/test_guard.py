import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

spec = importlib.util.spec_from_file_location("guard", Path(__file__).with_name("guard.py"))
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class StopLoop(Exception):
    pass


class GuardTests(unittest.TestCase):
    def run_guard(self, pids, child=None, sleeps=None, occupied=False):
        temporary_root = Path(__file__).parent.parent / "assets/tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        with (
            tempfile.TemporaryDirectory(dir=temporary_root) as directory,
            patch.object(guard, "DEPLOY", Path(directory)),
            patch.object(guard, "LOGS", Path(directory)),
            patch.object(guard, "RUNTIME", Path(directory)),
            patch.object(guard.signal, "signal"),
            patch.object(guard, "existing", side_effect=pids),
            patch.object(guard, "recover_worker") as recover,
            patch.object(guard, "port_open", return_value=occupied),
            patch.object(guard.subprocess, "Popen", return_value=child) as spawn,
            patch.object(guard.time, "sleep", side_effect=sleeps or StopLoop),
        ):
            with self.assertRaises(StopLoop):
                guard.supervise()
            return spawn.call_count, recover.call_count, spawn.call_args

    def test_adopts_without_restarting(self):
        count, recoveries, _ = self.run_guard([123])
        self.assertEqual((count, recoveries), (0, 1))

    def test_restarts_after_child_exit(self):
        child = Mock(pid=321)
        child.poll.return_value = -15
        child.returncode = -15
        count, _, args = self.run_guard([None, None], child, [None, None, StopLoop])
        self.assertEqual(count, 2)
        self.assertTrue(args.kwargs["start_new_session"])
        self.assertEqual(args.kwargs["stdin"], guard.subprocess.DEVNULL)

    def test_never_duplicates_live_launcher(self):
        child = Mock(pid=321)
        child.poll.return_value = None
        count, _, _ = self.run_guard([None, None], child, [None, StopLoop])
        self.assertEqual(count, 1)

    def test_does_not_replace_other_listener(self):
        count, _, _ = self.run_guard([None], occupied=True)
        self.assertEqual(count, 0)

    def test_account_gateway_is_ready_before_admin_setup(self):
        response = Mock()
        response.__enter__ = Mock(
            return_value=io.BytesIO(b'{"authenticated":false,"setup_required":true}')
        )
        response.__exit__ = Mock(return_value=False)
        with patch.object(guard, "urlopen", return_value=response) as request:
            self.assertEqual(guard.gateway_state(), {"connected": True, "account_mode": True})
            self.assertEqual(request.call_count, 1)

    def test_legacy_gateway_keeps_existing_recovery_probe(self):
        response = Mock()
        response.__enter__ = Mock(return_value=io.BytesIO(b'{"connected":true}'))
        response.__exit__ = Mock(return_value=False)
        missing = HTTPError("http://127.0.0.1:8760/api/auth/session", 404, "not found", {}, None)
        with patch.object(guard, "urlopen", side_effect=[missing, response]):
            self.assertEqual(guard.gateway_state(), {"connected": True})


if __name__ == "__main__":
    unittest.main()
