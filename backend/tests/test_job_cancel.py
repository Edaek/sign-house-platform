"""Tests for cooperative job cancellation."""

import unittest
from unittest.mock import patch, MagicMock

from app.services import job_cancel


class JobCancelFlagTests(unittest.TestCase):
    @patch('app.services.job_cancel.mongo')
    def test_request_cancel_sets_flag(self, mock_mongo):
        mock_mongo.db.processing_jobs.update_one.return_value.modified_count = 1
        self.assertTrue(job_cancel.request_cancel('job-1'))
        mock_mongo.db.processing_jobs.update_one.assert_called_once()

    @patch('app.services.job_cancel.mongo')
    def test_is_cancel_requested_reads_db(self, mock_mongo):
        mock_mongo.db.processing_jobs.find_one.return_value = {'cancel_requested': True}
        self.assertTrue(job_cancel.is_cancel_requested('job-1'))


class BatchCancelCheckpointTests(unittest.TestCase):
    """Verify cancel is checked at enough points that a single-page job can stop."""

    def test_single_page_pdf_checks_cancel_after_page_work(self):
        """Regression: cancel during the only page must not mark job completed."""
        import inspect
        from app.services import batch_processor

        source = inspect.getsource(batch_processor.process_single_pdf)
        # Must check cancel inside the page loop AND before marking file completed
        self.assertIn("return 'cancelled'", source)
        # After page loop, should not blindly complete when cancel was requested
        loop_pos = source.find('for page_idx, page_info in enumerate(pages)')
        after_loop = source[loop_pos:]
        completed_pos = after_loop.find("'status': 'completed'")
        self.assertGreater(completed_pos, 0, 'expected file-completed block')
        cancel_after_loop = 'is_cancel_requested' in after_loop[:completed_pos] or \
            'is_cancel_requested(job_id)' in source[source.find('# File completed'):]
        self.assertTrue(
            cancel_after_loop,
            'batch_processor must check cancel after page work / before file-completed',
        )


class DetectCancelCheckpointTests(unittest.TestCase):
    def test_detect_checks_after_cv_and_before_finalize(self):
        import inspect
        from app.services import detect_job_service

        source = inspect.getsource(detect_job_service.run_detect_job)
        cv_pos = source.find('detect_circles_by_template')
        self.assertGreater(cv_pos, 0)
        after_cv = source[cv_pos:]
        self.assertIn('_check_cancel()', after_cv[:800])

        assign_pos = source.find('assign_quantities')
        after_assign = source[assign_pos:]
        self.assertIn('_check_cancel()', after_assign[:600],
                      'must check cancel after assign_quantities')


if __name__ == '__main__':
    unittest.main()
