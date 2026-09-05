from app.config import settings
from app.models import AppSetting
from app.services.settings_store import migrate_settings_defaults


def test_migrate_replaces_deprecated_deepseek_chat(db_session):
    db_session.add(AppSetting(key="summarize_model", value="deepseek-chat"))
    db_session.add(AppSetting(key="transcribe_model", value="whisper-1"))
    db_session.commit()
    migrate_settings_defaults(db_session)
    assert db_session.get(AppSetting, "summarize_model").value == settings.default_summarize_model
    assert db_session.get(AppSetting, "transcribe_model").value == settings.default_transcribe_model
    assert settings.default_summarize_model == "deepseek-v4-flash"


def test_flag_settings_roundtrip(db_session):
    from app.services.settings_store import load_settings, save_settings

    saved = save_settings(db_session, {"ai_proofread": False, "show_transcript": False})
    assert saved.ai_proofread is False
    assert saved.show_transcript is False
    loaded = load_settings(db_session)
    assert loaded.ai_proofread is False
    assert loaded.show_transcript is False
    restored = save_settings(db_session, {"ai_proofread": True, "show_transcript": True})
    assert restored.ai_proofread is True
    assert restored.show_transcript is True


def test_summarize_concurrency_roundtrip_and_clamp(db_session):
    from app.services.settings_store import load_settings, save_settings

    saved = save_settings(db_session, {"summarize_concurrency": 99})
    assert saved.summarize_concurrency == 8
    saved = save_settings(db_session, {"summarize_concurrency": 0})
    assert saved.summarize_concurrency == 1
    saved = save_settings(db_session, {"summarize_concurrency": 4})
    assert saved.summarize_concurrency == 4
    assert load_settings(db_session).summarize_concurrency == 4


def test_default_transcribe_threads_is_80_percent(monkeypatch):
    from app.services.settings_store import default_transcribe_threads, parse_transcribe_threads

    monkeypatch.setattr("app.services.settings_store.cpu_count", lambda: 10)
    assert default_transcribe_threads() == 8
    monkeypatch.setattr("app.services.settings_store.cpu_count", lambda: 8)
    assert default_transcribe_threads() == 6
    monkeypatch.setattr("app.services.settings_store.cpu_count", lambda: 1)
    assert default_transcribe_threads() == 1
    monkeypatch.setattr("app.services.settings_store.cpu_count", lambda: 10)
    assert parse_transcribe_threads("") == 8
    assert parse_transcribe_threads(0) == 8
    assert parse_transcribe_threads(99) == 10
    assert parse_transcribe_threads(3) == 3


def test_transcribe_threads_and_fast_roundtrip(db_session, monkeypatch):
    from app.services.settings_store import load_settings, save_settings

    monkeypatch.setattr("app.services.settings_store.cpu_count", lambda: 10)
    loaded = load_settings(db_session)
    assert loaded.transcribe_threads == 8
    assert loaded.transcribe_fast is False
    assert loaded.cpu_count == 10
    saved = save_settings(db_session, {"transcribe_threads": 4, "transcribe_fast": True})
    assert saved.transcribe_threads == 4
    assert saved.transcribe_fast is True
    again = load_settings(db_session)
    assert again.transcribe_threads == 4
    assert again.transcribe_fast is True


def test_migrate_small_whisper_back_to_sensevoice(db_session):
    db_session.add(AppSetting(key="transcribe_model", value="small"))
    db_session.commit()
    migrate_settings_defaults(db_session)
    assert db_session.get(AppSetting, "transcribe_model").value == "sensevoice-small-q8"


def test_migrate_keeps_sensevoice(db_session):
    db_session.add(AppSetting(key="transcribe_model", value="sensevoice-small-q8"))
    db_session.commit()
    migrate_settings_defaults(db_session)
    assert db_session.get(AppSetting, "transcribe_model").value == "sensevoice-small-q8"


def test_migrate_keeps_local_whisper_model(db_session):
    db_session.add(AppSetting(key="transcribe_model", value="medium"))
    db_session.commit()
    migrate_settings_defaults(db_session)
    assert db_session.get(AppSetting, "transcribe_model").value == "medium"


def test_migrate_keeps_ai_proofread_off(db_session):
    db_session.add(AppSetting(key="ai_proofread", value="0"))
    db_session.commit()
    migrate_settings_defaults(db_session)
    assert db_session.get(AppSetting, "ai_proofread").value == "0"


def test_migrate_keeps_explicit_custom_model(db_session):
    db_session.add(AppSetting(key="summarize_model", value="deepseek-v4-pro"))
    db_session.commit()
    migrate_settings_defaults(db_session)
    assert db_session.get(AppSetting, "summarize_model").value == "deepseek-v4-pro"
