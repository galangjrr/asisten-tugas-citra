import os
import time
import tempfile
import pytest
from tools.storage_cleaner import clean_storage_by_age


def test_clean_storage_removes_old_files():
    with tempfile.TemporaryDirectory() as tmp_dir:
        # 1. Berkas lama (48 jam lalu)
        old_file = os.path.join(tmp_dir, "old_paper.pdf")
        with open(old_file, "w") as f:
            f.write("dummy content")
        old_time = time.time() - (48 * 3600)
        os.utime(old_file, (old_time, old_time))

        # 2. Berkas baru (1 jam lalu)
        fresh_file = os.path.join(tmp_dir, "fresh_paper.pdf")
        with open(fresh_file, "w") as f:
            f.write("dummy content")

        # 3. Berkas gitkeep
        gitkeep = os.path.join(tmp_dir, ".gitkeep")
        with open(gitkeep, "w") as f:
            f.write("")
        os.utime(gitkeep, (old_time, old_time))

        # Eksekusi pembersihan dengan batas usia 24 jam
        deleted = clean_storage_by_age(max_age_hours=24, storage_dir=tmp_dir)

        assert deleted == 1
        assert not os.path.exists(old_file)
        assert os.path.exists(fresh_file)
        assert os.path.exists(gitkeep)


def test_clean_storage_nonexistent_dir():
    deleted = clean_storage_by_age(max_age_hours=24, storage_dir="/path/that/does/not/exist")
    assert deleted == 0


def test_clean_storage_ignores_subdirectories():
    with tempfile.TemporaryDirectory() as tmp_dir:
        sub_dir = os.path.join(tmp_dir, "subfolder")
        os.makedirs(sub_dir)
        old_time = time.time() - (48 * 3600)
        os.utime(sub_dir, (old_time, old_time))

        deleted = clean_storage_by_age(max_age_hours=24, storage_dir=tmp_dir)
        assert deleted == 0
        assert os.path.exists(sub_dir)
