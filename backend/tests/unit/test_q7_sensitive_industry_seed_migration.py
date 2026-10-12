"""Contract coverage for the Q350/Q351 sensitive-industry seed migration (0057).

The migration runs on real PG in the migration job (`alembic upgrade head`
-> `downgrade -1` -> upgrade; the fingerprinted downgrade was verified against
a one-shot PG16 container: ops-customized rows survive downgrade while pristine
seed rows are removed). This file pins the pure-logic halves so a silent edit
to the seed set/fingerprint — or a rebase that breaks the revision chain — is
caught without a PostgreSQL.

The two seed industries and their keyword arrays are the Q350 ruling
(docs/02 C1.293, docs/19 list-2 #13): changing them is a ruling, not a
refactor. Q351 narrowed the downgrade to delete only rows whose full column
fingerprint still matches the seed, so operations edits via Q7 CRUD survive.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "0057_q7_sensitive_industry_seeds.py"
)

APPROVED_SEED_KEYWORDS = {
    "food": ["食品"],
    "maternal_infant": ["母婴"],
}


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("q7_sensitive_industry_seeds_0057", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["q7_sensitive_industry_seeds_0057"] = module
    spec.loader.exec_module(module)
    return module


def test_revision_chain_is_linear_and_appended(mod):
    assert mod.revision == "0057_q7_sensitive_industry_seeds"
    assert mod.down_revision == "0056_video_segments_objects"


def test_seed_keywords_match_the_approved_two_industries(mod):
    assert mod._SEED_KEYWORDS == APPROVED_SEED_KEYWORDS


def test_downgrade_fingerprints_every_seed_column(mod):
    # Q351：downgrade 的 DELETE 必须带全部种子指纹列，只删原样种子行；
    # 若有人退回「按 industry 无条件删」，本测试当场判红。
    source = MIGRATION.read_text(encoding="utf-8")
    downgrade_body = source.split("def downgrade", 1)[1]
    for column in (
        "industries.c.industry",
        "industries.c.keywords",
        "industries.c.threshold",
        "industries.c.sensitive",
        "industries.c.enabled",
        "industries.c.is_default",
    ):
        assert column in downgrade_body, column
    assert "DELETE FROM c1_industry_thresholds WHERE industry IN" not in downgrade_body
