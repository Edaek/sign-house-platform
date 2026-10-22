"""Assignment confirmation copy must reflect fuzzy folder choice, not Mongo default."""
from app.services.assignment_notify_service import assignment_confirmation_text


def test_confirmation_shows_chosen_physical_folder_not_mongo_enrich():
    project = {
        '_id': '507f1f77bcf86cd799439011',
        'code': 'PJ-3051',
        'name': '3051',
        'nasFolderName': 'PJ-3051',
    }
    text = assignment_confirmation_text(project, 1)
    assert 'PJ-3051 唐人新村' not in text
    assert 'PJ-3051' in text
    assert '檔案已歸類' in text
