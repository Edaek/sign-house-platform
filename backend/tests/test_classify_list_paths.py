"""Disambiguation lists use full NAS paths without 1/2 numbering."""
from app.services.loomy_wa_pick_store import match_loomy_wa_pick_option, nas_path_line_from_option
from app.services.project_ai_resolve_service import _build_classify_list_message
from app.services.project_number_match_service import wa_classify_nas_path_line


def test_build_classify_list_message_no_number_prefix():
    cands = [
        (
            {
                'code': 'PJ-1005',
                'nasFolderName': '1005',
                'nasParentBucket': 'T-1000-2002',
            },
            100,
        ),
        (
            {
                'code': 'PJ-1005',
                'nasFolderName': '1005',
                'nasParentBucket': 'S-1000-2000',
            },
            100,
        ),
    ]
    msg = _build_classify_list_message('1005', cands)
    assert '1.' not in msg
    assert '2.' not in msg
    assert 'T-1000-2002/1005' in msg
    assert 'S-1000-2000/1005' in msg
    assert '完整路徑' in msg or 'NAS 路徑' in msg


def test_wa_classify_nas_path_line():
    proj = {'nasParentBucket': 'S-1000-2000', 'nasFolderName': '1005', 'code': 'PJ-1005'}
    assert wa_classify_nas_path_line(proj) == 'S-1000-2000/1005'


def test_match_pick_by_full_path():
    opts = [
        {
            'project_id': 'a',
            'nas_parent_bucket': 'T-1000-2002',
            'nas_folder_name': '1005',
            'label': 'T-1000-2002/1005',
        },
        {
            'project_id': 'b',
            'nas_parent_bucket': 'S-1000-2000',
            'nas_folder_name': '1005',
            'label': 'S-1000-2000/1005',
        },
    ]
    hit = match_loomy_wa_pick_option(opts, 'S-1000-2000/1005')
    assert hit and hit['project_id'] == 'b'
    assert nas_path_line_from_option(hit) == 'S-1000-2000/1005'
