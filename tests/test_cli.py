import waaid_radar.__main__ as cli
from conftest import FIXTURES


def test_preview_from_file(capsys, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert cli.main(["preview", "--file", str(FIXTURES / "page.html")]) == 0
    out = capsys.readouterr()
    assert "ماجستير في الأمن السيبراني" in out.out and "#أمن_سيبراني" in out.out
    assert "المجموع 5 برامج" in out.err


def test_preview_json(capsys):
    assert cli.main(["preview", "--json", "--all", "--file", str(FIXTURES / "page.html")]) == 0
    assert '"institution": "جامعة موناش"' in capsys.readouterr().out


def test_dry_run_from_file_prints_messages_and_keeps_no_state(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@waaid_radar")
    monkeypatch.setenv("STATE_PATH", str(tmp_path / "state.json"))
    assert cli.main(["run", "--file", str(FIXTURES / "page.html")]) == 0
    out = capsys.readouterr().out
    assert "→ @waaid_radar" in out and "برنامج جديد — مسار واعد" in out
    assert not (tmp_path / "state.json").exists()


def test_run_without_token_is_a_config_error(monkeypatch):
    for name in ("TELEGRAM_BOT_TOKEN", "DRY_RUN"):
        monkeypatch.delenv(name, raising=False)
    assert cli.main(["run"]) == 2


def test_check_reports_a_bot_without_post_rights(capsys, monkeypatch):
    class FakeTelegram:
        def __init__(self, token):
            pass

        def get_me(self):
            return {"id": 9, "username": "waaid_radar_bot"}

        def get_chat(self, chat_id):
            return {"title": "رادار واعد"}

        def get_chat_member(self, chat_id, user_id):
            return {"status": "member"}

    monkeypatch.setattr(cli, "Telegram", FakeTelegram)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@waaid_radar")
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "111")
    assert cli.main(["check"]) == 1
    out = capsys.readouterr().out
    assert "✓ البوت: @waaid_radar_bot" in out and "✗ البوت ليس مشرفًا" in out
