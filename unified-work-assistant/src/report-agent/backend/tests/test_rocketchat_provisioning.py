import importlib.util
import json
from pathlib import Path


def load_setup():
    path = Path(__file__).resolve().parents[2] / "rocketchat" / "setup.py"
    spec = importlib.util.spec_from_file_location("rocketchat_setup_for_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_init_adds_four_employees_without_replacing_existing_credentials(tmp_path):
    setup = load_setup()
    setup.LOCAL = tmp_path
    original = {
        "admin": {"username": "poc-admin", "password": "admin-secret"},
        "employee": {"username": "poc-employee", "password": "existing-secret"},
        "bot": {"username": "report-bot", "password": "bot-secret"},
    }
    (tmp_path / "credentials.json").write_text(json.dumps(original), encoding="utf-8")

    setup.init()

    credentials = json.loads((tmp_path / "credentials.json").read_text(encoding="utf-8"))
    employees = setup.employee_accounts(credentials)
    assert [account["username"] for _, account, _ in employees] == [
        "poc-employee", "poc-employee-2", "poc-employee-3", "poc-employee-4",
    ]
    assert credentials["employee"]["password"] == "existing-secret"
    assert all(account["password"] for _, account, _ in employees)
