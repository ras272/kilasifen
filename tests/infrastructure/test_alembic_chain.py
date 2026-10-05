"""The Alembic history stays one linear chain of AAAAMMDD_NN revisions.

Two branches that each add a revision on top of the same parent merge
cleanly as files but leave Alembic with two heads, and ``alembic upgrade
head`` then refuses to run. These checks name the problem directly.
"""

import re
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REVISION_ID = re.compile(r"[0-9]{8}_[0-9]{2}")


def _script() -> ScriptDirectory:
    config = Config(str(_REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


def test_migrations_have_a_single_head():
    heads = _script().get_heads()

    assert len(heads) == 1, (
        f"Alembic has several heads {sorted(heads)}: chain the newer revision "
        "after the other one (down_revision) instead of on their common parent"
    )


def test_migrations_form_one_linear_chain():
    revisions = list(_script().walk_revisions())

    bases = [rev.revision for rev in revisions if rev.down_revision is None]
    assert len(bases) == 1, bases
    for rev in revisions:
        # CLAUDE.md: every revision is chained to the previous one; no merge
        # revisions and no branch points.
        assert not isinstance(rev.down_revision, (tuple, list)), rev.revision
        assert len(rev.nextrev) <= 1, (rev.revision, sorted(rev.nextrev))


def test_revision_ids_follow_the_file_names():
    for rev in _script().walk_revisions():
        assert _REVISION_ID.fullmatch(rev.revision), rev.revision
        assert Path(rev.path).name.startswith(f"{rev.revision}_"), (
            rev.revision,
            rev.path,
        )
