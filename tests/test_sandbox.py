"""The code sandbox must run normal code and block dangerous actions."""
import pytest

from core.sandbox import run_python


@pytest.mark.parametrize("code,needle", [
    ("import subprocess; subprocess.run(['ls'])", "subprocess.Popen"),
    ("import os; os.system('echo hi')", "os.system"),
    ("open('/tmp/omnipilot_evil.txt', 'w').write('x')", "outside the workspace"),
])
def test_blocks_dangerous_code(tmp_path, code, needle):
    r = run_python(code, tmp_path, timeout=20)
    assert not r.ok and needle in r.stderr


def test_blocks_network(tmp_path):
    r = run_python("import socket; socket.create_connection(('1.1.1.1', 80), timeout=3)", tmp_path, timeout=20)
    assert not r.ok


def test_no_secrets_in_sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "super-secret")
    r = run_python("import os; print(os.environ.get('GROQ_API_KEY'))", tmp_path, timeout=20)
    assert r.stdout.strip() == "None"


def test_timeout(tmp_path):
    r = run_python("while True: pass", tmp_path, timeout=3)
    assert r.timed_out and not r.ok


def test_normal_code_and_new_files(tmp_path):
    r = run_python("open('a.txt','w').write('x'); print(6*7)", tmp_path, timeout=20)
    assert r.ok and r.stdout.strip() == "42" and r.new_files == ["a.txt"]


def test_single_math_thread(tmp_path):
    r = run_python("import os; print(os.environ['OPENBLAS_NUM_THREADS'], os.environ['OMP_NUM_THREADS'])", tmp_path)
    assert r.ok and r.stdout.split() == ["1", "1"]
