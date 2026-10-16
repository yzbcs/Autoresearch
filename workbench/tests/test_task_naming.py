"""Real filesystem collisions and Unicode HTTP routing for task names."""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from workbench import task_naming
from workbench.server import search, writing
from workbench.tests.test_workbench import app as app  # noqa: PLC0414 - shared pytest fixture
from workbench.tests.test_workbench import json_request, new_writing, request, writing_examples


def test_identical_timestamps_do_not_overwrite(tmp_path, monkeypatch):
    class FixedClock:
        @staticmethod
        def now(tz):
            return datetime(2026, 9, 8, 12, 30, 0, tzinfo=tz)
    monkeypatch.setattr(task_naming, "datetime", FixedClock)
    with ThreadPoolExecutor(max_workers=8) as pool:
        dirs = list(pool.map(lambda _: task_naming.create_task_directory(tmp_path, "../中文任务", "search"), range(16)))
    assert len(set(dirs)) == 16
    assert all(p.parent == tmp_path and re.fullmatch(task_naming.name_pattern("search"), p.name) for p in dirs)


def test_chinese_names_and_legacy_http(app):
    project = new_writing(app)
    assert re.fullmatch(task_naming.name_pattern("writing"), project["id"])
    assert json_request(app, '/auto-writing/api/writings/' + project['id'])['title'] == project['title']
    run = writing.safe_project_dir(project['id'])
    publication = writing.publication_dir(run)
    publication.mkdir(parents=True, exist_ok=True)
    (publication / 'manuscript.pdf').write_bytes(b'%PDF-test')
    status, _, body = request(app, '/auto-writing/api/writings/' + project['id'] + '/publication/download/pdf')
    assert status == 200 and body == b'%PDF-test'
    # Existing identifiers remain readable without moving or rewriting their directory.
    legacy_id = 'writing-20260901-120000-abcdef'
    project = writing.load_project(project['id'])
    run.rename(run.parent / legacy_id)
    project['id'] = legacy_id
    writing.save_project(project)
    assert json_request(app, '/auto-writing/api/writings/' + legacy_id)['id'] == legacy_id

    table = json_request(app, '/auto-table/api/projects', {
        'title': '中文表格任务', 'mode': 'results',
        'files': [writing_examples.encoded_file('results.csv', b'method,score\na,1\n')],
    }, status=201)
    assert re.fullmatch(task_naming.name_pattern('table'), table['id'])
    assert json_request(app, '/auto-table/api/projects/' + table['id'])['title'] == '中文表格任务'
    assert any(p['id'] == table['id'] for p in json_request(app, '/auto-table/api/projects')['projects'])

    job = search.ResearchJob('research direction', 2, False, 1, title='中文调研标题')
    assert re.fullmatch(task_naming.name_pattern('search'), job.run_dir.name)
    assert any(r['run_name'] == job.run_dir.name for r in json_request(app, '/auto-search/api/runs')['runs'])
    (job.run_dir / 'web-data.json').write_text('{"ideas": []}')
    assert json_request(app, '/auto-search/api/runs/' + job.run_dir.name + '/ideas')['ideas'] == []
