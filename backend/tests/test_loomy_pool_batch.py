from app.services.loomy_pool_batch import batch_key_for_doc, sender_bucket_key


def test_batch_key_prefers_batch_id():
    assert batch_key_for_doc({'batchId': 'b1', 'messageId': 'm1'}) == 'b1'
    assert batch_key_for_doc({'messageId': 'm1'}) == 'm1'


def test_sender_bucket_private():
    assert sender_bucket_key(phone='85296364202', chat_jid='') == 'p:85296364202'


def test_sender_bucket_group():
    jid = '120363409744113388@g.us'
    assert sender_bucket_key(phone='85296364202', chat_jid=jid) == f'g:{jid}:85296364202'
