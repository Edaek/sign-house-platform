from app.services.loomy_wa_smart_classify import parse_assign_target


def test_parse_assign_phrase():
    hint, target = parse_assign_target('將 1006 啊数据打卡 歸類到 1005')
    assert target == '1005'
    assert hint and '1006' in hint


def test_parse_assign_to_only():
    hint, target = parse_assign_target('归类到 PJ-3000')
    assert hint is None
    assert '3000' in target


def test_parse_no_assign():
    assert parse_assign_target('我要分開進行歸類') == (None, None)
