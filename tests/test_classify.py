"""Unit tests for intent classification and rule extraction (no LLM path)."""

from cogos.classify import classify_intent, extract_rule, next_rule_id


def test_classify_rule_by_marker():
    intent = classify_intent("以后我的 SQL 不允许使用 SELECT *。")
    assert intent.type == "rule"
    assert intent.method == "keyword"


def test_classify_rule_by_my_pattern():
    intent = classify_intent("我的代码不要用 print 调试。")
    assert intent.type == "rule"


def test_classify_rule_forced_by_prefix():
    intent = classify_intent("规则:写 SQL 时用 CTE")
    assert intent.type == "rule"


def test_classify_task_default_without_llm():
    intent = classify_intent("帮我写一个查询销售数据的 SQL。")
    assert intent.type == "task"
    assert intent.method == "fallback"
    assert intent.confidence < 1.0


def test_classify_domain_hint():
    intent = classify_intent("以后我的 SQL 不允许使用 SELECT *。")
    assert intent.domain == "sql"


def test_extract_rule_forbidden_pattern():
    draft = extract_rule("以后我的 SQL 不允许使用 SELECT *。")
    assert "SELECT *" in draft.forbidden
    assert draft.method == "pattern"


def test_extract_rule_required_pattern():
    draft = extract_rule("以后我的代码必须用类型标注。")
    assert draft.required, "expected a required pattern"
    assert draft.method == "pattern"


def test_extract_rule_raw_when_no_pattern():
    draft = extract_rule("以后注意 SQL 风格。")
    assert draft.method == "raw"
    assert not draft.forbidden


def test_next_rule_id_per_domain(tmp_path):
    (tmp_path / "R-SQL-001.json").write_text("{}", encoding="utf-8")
    (tmp_path / "R-SQL-002.json").write_text("{}", encoding="utf-8")
    (tmp_path / "R-COD-001.json").write_text("{}", encoding="utf-8")
    assert next_rule_id(tmp_path, "sql") == "R-SQL-003"
    assert next_rule_id(tmp_path, "coding") == "R-COD-002"


def test_next_rule_id_empty_dir(tmp_path):
    assert next_rule_id(tmp_path, "general") == "R-GEN-001"
