import os
import shutil
import tempfile
import pytest
from tools.task_store import save_task_to_disk, load_task_from_disk, TASKS_DIR
from agents.generator import robust_json_dict_parse


def test_save_and_load_task_to_disk():
    test_id = "test_task_123"
    test_task = {
        "title": "Analisis Kasus Hukum Bisnis",
        "sections": [{"heading": "Bab I", "content": "Isi pembahasan..."}],
        "topic": "Hukum Bisnis",
        "language": "id"
    }

    filepath = save_task_to_disk(test_id, test_task)
    assert os.path.exists(filepath)

    loaded = load_task_from_disk(test_id)
    assert loaded is not None
    assert loaded["title"] == "Analisis Kasus Hukum Bisnis"
    assert len(loaded["sections"]) == 1

    # Cleanup test file
    if os.path.exists(filepath):
        os.remove(filepath)


def test_load_nonexistent_task():
    result = load_task_from_disk("non_existent_random_id")
    assert result is None


def test_robust_json_parse_clean():
    clean_json = '{"title": "Test Title", "sections": [{"heading": "1", "content": "Text"}]}'
    result = robust_json_dict_parse(clean_json)
    assert result is not None
    assert result["title"] == "Test Title"


def test_robust_json_parse_with_markdown_fences():
    fenced_json = '```json\n{"title": "Fenced Title", "sections": []}\n```'
    result = robust_json_dict_parse(fenced_json)
    assert result is not None
    assert result["title"] == "Fenced Title"


def test_robust_json_parse_with_surrounding_commentary():
    messy_text = 'Here is the requested output:\n{"title": "Surrounded Title", "sections": []}\nHope this helps!'
    result = robust_json_dict_parse(messy_text)
    assert result is not None
    assert result["title"] == "Surrounded Title"


def test_robust_json_parse_list_wrapper():
    list_json = '[{"title": "List Title", "sections": []}]'
    result = robust_json_dict_parse(list_json)
    assert result is not None
    assert result["title"] == "List Title"


def test_robust_json_parse_invalid():
    assert robust_json_dict_parse("") is None
    assert robust_json_dict_parse("Just random text without any brackets") is None


def test_robust_json_parse_trailing_commas():
    trailing_json = '{"title": "Trailing Title", "sections": [{"heading": "A", "content": "Text",},],}'
    result = robust_json_dict_parse(trailing_json)
    assert result is not None
    assert result["title"] == "Trailing Title"


def test_sanitize_task_id_prevents_traversal():
    from tools.task_store import sanitize_task_id
    assert sanitize_task_id("../../etc/passwd") == "etcpasswd"
    assert sanitize_task_id("task:123/evil\\path") == "task123evilpath"
    assert sanitize_task_id("valid-task_id-123") == "valid-task_id-123"
