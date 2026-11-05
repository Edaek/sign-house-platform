"""resolve_wa_move_target_project prefers long-name row over empty stub."""
import unittest
from unittest.mock import MagicMock, patch

from bson import ObjectId


class ResolveMoveTargetTests(unittest.TestCase):
    @patch('app.services.image_pool_service.mongo')
    def test_prefers_source_project_when_codes_collide(self, mock_mongo):
        from app.services.image_pool_service import resolve_wa_move_target_project

        stub_id = ObjectId()
        long_id = ObjectId()
        src_id = long_id
        stub = {
            '_id': stub_id,
            'code': 'PJ-2937',
            'nasFolderName': 'PJ-2937',
            'nasParentBucket': 'PJ-2900-2999',
            'status': 'active',
        }
        long_proj = {
            '_id': long_id,
            'code': 'PJ-2937',
            'nasFolderName': 'PJ-2937 粉嶺北(Yau Lee)_RN',
            'nasParentBucket': 'PJ-2900-2999',
            'status': 'active',
        }

        mock_mongo.db.wa_projects.find.return_value = [stub, long_proj]
        mock_mongo.db.wa_projects.find_one.return_value = long_proj
        mock_mongo.db.wa_records.count_documents.side_effect = lambda q: (
            3 if q.get('projectId') == long_id else 0
        )

        with patch(
            'app.services.project_number_match_service.is_wa_classify_target',
            return_value=True,
        ):
            hit = resolve_wa_move_target_project(
                target_code='PJ-2937',
                source_record={'projectId': src_id},
            )
        self.assertEqual(str(hit['_id']), str(long_id))


if __name__ == '__main__':
    unittest.main()
