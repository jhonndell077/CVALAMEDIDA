import unittest
import bank_sync_status as status


class BankSyncStatusTests(unittest.TestCase):
    def test_dates_and_notes_are_informational_and_never_become_failed_access(self):
        bank = {'pending':0,'warnings':[{'code':'bank_date_preserved','severity':'notice'},
                                      {'code':'bank_document_note','severity':'notice'}]}
        self.assertEqual(status.summarize(bank)['state'], 'ready')
        self.assertEqual(status.summarize(bank)['noticeCount'], 2)
        self.assertEqual(status.event(bank), ('success','bank_sync_notice'))

    def test_ownership_unreadable_and_unknown_warnings_require_review(self):
        for warning in ({'code':'bank_identity_conflict','severity':'blocking'},
                        {'code':'bank_identity_unverified','severity':'blocking'},
                        {'code':'bank_document_unreadable','severity':'blocking'},
                        {'message':'Legacy unknown reason'}, {'code':'unknown','severity':'notice'}):
            with self.subTest(warning=warning):
                bank={'pending':0,'warnings':[warning]}
                self.assertEqual(status.summarize(bank)['state'],'blocked')
                self.assertEqual(status.event(bank),('warning','bank_review_required'))

    def test_intermediate_batch_is_not_a_finished_warning_or_success(self):
        self.assertEqual(status.summarize({'pending':2})['state'],'pending')
        self.assertIsNone(status.event({'pending':2}))

    def test_revision_is_blocking_even_if_warnings_were_lost(self):
        self.assertEqual(status.summarize({'documents':[{'file_id':'x','status':'revision','active':True}]})['state'],'blocked')
        self.assertEqual(status.summarize({'documents':[{'file_id':'x','status':'revision','active':False}]})['state'],'ready')

    def test_summary_contains_only_allowlisted_codes_and_counters(self):
        summary=status.summarize({'warnings':[{'file_id':'private-id','name':'Private name','message':'Private text'}]})
        self.assertNotIn('Private',str(summary));self.assertNotIn('private-id',str(summary))
        self.assertEqual(summary['reasons'],['bank_review_required'])
