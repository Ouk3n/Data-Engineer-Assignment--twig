from pipeline.quality import score_labels


def test_quality_scores_nulls_numbers_and_unordered_skills(tmp_path):
    labels = tmp_path / "labels.csv"
    labels.write_text(
        "posting_id,source,company,title,seniority,city,country,remote_policy,salary_min,salary_max,currency,employment_type,skills,visa_sponsorship,posted_date,status\n"
        "job-1,greenhouse,Acme,Data Engineer,NULL,Austin,US,remote,100000,NULL,USD,full_time,\"SQL, Python\",false,NULL,open\n",
        encoding="utf-8",
    )
    records = [{
        "posting_id": "job-1", "company": "Acme", "title": "Data Engineer", "seniority": None,
        "city": "Austin", "country": "US", "remote_policy": "remote", "salary_min": 100000.0,
        "salary_max": None, "currency": "USD", "employment_type": "full_time", "skills": ["Python", "SQL"],
        "visa_sponsorship": False, "posted_date": None, "status": "open",
    }]
    report = score_labels(labels, records)
    assert report["labeled_rows"] == 1
    assert report["field_accuracy"]["skills"] == 1.0
    assert report["field_accuracy"]["salary_min"] == 1.0
    assert report["field_accuracy"]["seniority"] == 1.0
