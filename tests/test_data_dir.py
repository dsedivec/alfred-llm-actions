"""Tests for data directory resolution and user data migration."""

import llm


class TestResolveDataDir:
    """Tests for resolve_data_dir()."""

    def test_returns_alfred_env_when_set(self, monkeypatch, tmp_path):
        target = str(tmp_path / "alfred_data")
        monkeypatch.setenv("alfred_workflow_data", target)
        assert llm.resolve_data_dir() == target

    def test_falls_back_to_workflow_data_subdir(self, monkeypatch):
        monkeypatch.delenv("alfred_workflow_data", raising=False)
        monkeypatch.setattr(llm, "WORKFLOW_DIR", "/fake/workflow")
        assert llm.resolve_data_dir() == "/fake/workflow/data"


class TestMigrateUserData:
    """Tests for migrate_user_data()."""

    def test_copies_models_yaml(self, tmp_path, monkeypatch):
        """models.yaml is copied from WORKFLOW_DIR to DATA_DIR."""
        wf = tmp_path / "workflow"
        wf.mkdir()
        data = tmp_path / "data"
        data.mkdir()
        state = data / "state"
        state.mkdir()

        (wf / "models.yaml").write_text("- label: test\n")

        monkeypatch.setattr(llm, "WORKFLOW_DIR", str(wf))
        monkeypatch.setattr(llm, "DATA_DIR", str(data))
        monkeypatch.setattr(llm, "STATE_DIR", str(state))
        monkeypatch.setattr(llm, "MODELS_USER_FILE", str(data / "models.yaml"))

        llm.migrate_user_data()
        assert (data / "models.yaml").read_text() == "- label: test\n"

    def test_copies_state_files(self, tmp_path, monkeypatch):
        """State files are copied from WORKFLOW_DIR/state to new STATE_DIR."""
        wf = tmp_path / "workflow"
        wf.mkdir()
        old_state = wf / "state"
        old_state.mkdir()
        (old_state / "active_model.json").write_text('{"model":"x"}')
        (old_state / "last_conversation.json").write_text("[]")

        data = tmp_path / "data"
        data.mkdir()
        state = data / "state"
        state.mkdir()

        monkeypatch.setattr(llm, "WORKFLOW_DIR", str(wf))
        monkeypatch.setattr(llm, "DATA_DIR", str(data))
        monkeypatch.setattr(llm, "STATE_DIR", str(state))
        monkeypatch.setattr(llm, "MODELS_USER_FILE", str(data / "models.yaml"))

        llm.migrate_user_data()
        assert (state / "active_model.json").read_text() == '{"model":"x"}'
        assert (state / "last_conversation.json").read_text() == "[]"

    def test_copies_cache_files(self, tmp_path, monkeypatch):
        """Cache files in old state dir are also copied."""
        wf = tmp_path / "workflow"
        wf.mkdir()
        old_state = wf / "state"
        old_state.mkdir()
        (old_state / "models_cache_openai.json").write_text("{}")

        data = tmp_path / "data"
        data.mkdir()
        state = data / "state"
        state.mkdir()

        monkeypatch.setattr(llm, "WORKFLOW_DIR", str(wf))
        monkeypatch.setattr(llm, "DATA_DIR", str(data))
        monkeypatch.setattr(llm, "STATE_DIR", str(state))
        monkeypatch.setattr(llm, "MODELS_USER_FILE", str(data / "models.yaml"))

        llm.migrate_user_data()
        assert (state / "models_cache_openai.json").read_text() == "{}"

    def test_does_not_overwrite_existing(self, tmp_path, monkeypatch):
        """Existing files in DATA_DIR are NOT overwritten."""
        wf = tmp_path / "workflow"
        wf.mkdir()
        (wf / "models.yaml").write_text("old content")

        data = tmp_path / "data"
        data.mkdir()
        state = data / "state"
        state.mkdir()
        (data / "models.yaml").write_text("user content")

        monkeypatch.setattr(llm, "WORKFLOW_DIR", str(wf))
        monkeypatch.setattr(llm, "DATA_DIR", str(data))
        monkeypatch.setattr(llm, "STATE_DIR", str(state))
        monkeypatch.setattr(llm, "MODELS_USER_FILE", str(data / "models.yaml"))

        llm.migrate_user_data()
        assert (data / "models.yaml").read_text() == "user content"

    def test_noop_when_data_inside_workflow(self, tmp_path, monkeypatch):
        """No migration when DATA_DIR is inside WORKFLOW_DIR (fallback mode)."""
        wf = tmp_path / "workflow"
        wf.mkdir()
        data = wf / "data"
        data.mkdir()
        state = data / "state"
        state.mkdir()
        (wf / "models.yaml").write_text("should not copy")

        monkeypatch.setattr(llm, "WORKFLOW_DIR", str(wf))
        monkeypatch.setattr(llm, "DATA_DIR", str(data))
        monkeypatch.setattr(llm, "STATE_DIR", str(state))
        monkeypatch.setattr(llm, "MODELS_USER_FILE", str(data / "models.yaml"))

        llm.migrate_user_data()
        assert not (data / "models.yaml").exists()
