from tradingagents.rnd.data_auditor import _dedupe_issues, _review_issues


def test_review_issues_normalizes_llm_findings():
    issues = _review_issues(
        {
            "findings": [
                {
                    "severity": "medium",
                    "module": "display",
                    "message": "摘要表达容易误读",
                    "fix": "改成待确认线索",
                }
            ]
        }
    )

    assert issues == [
        {
            "severity": "medium",
            "module": "display",
            "message": "摘要表达容易误读",
            "fix": "改成待确认线索",
        }
    ]


def test_review_issues_keeps_low_findings_out_of_scored_issues():
    assert _review_issues(
        {
            "findings": [
                {
                    "severity": "low",
                    "module": "display",
                    "message": "仅展示建议",
                    "fix": "可后续优化",
                }
            ]
        }
    ) == []


def test_dedupe_issues_keeps_one_copy():
    issues = _dedupe_issues(
        [
            {"severity": "medium", "module": "call_auction", "message": "集合竞价生成时间偏晚"},
            {"severity": "medium", "module": "call_auction", "message": "集合竞价生成时间偏晚"},
        ]
    )

    assert len(issues) == 1
