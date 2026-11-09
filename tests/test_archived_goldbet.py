import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from test_regressions import worker

class ArchivedSheetAuditTests(unittest.TestCase):
    def snapshot(self, records):
        store=worker.GoogleQueueStore.__new__(worker.GoogleQueueStore)
        store.queue=Mock()
        store.queue.get_all_values.return_value=[]
        store.client=Mock()
        book=store.client.open_by_key.return_value
        book.worksheet.return_value.get_all_values.return_value=[['Nome e Cognome','E-Mail']]
        with patch.object(worker,'audit_queue_records',return_value=(records,[])):
            result=store.consistency_snapshot()
        return result, [c.args[0] for c in book.worksheet.call_args_list]

    def test_archived_goldbet_is_not_scanned_as_active(self):
        request=SimpleNamespace(destination_spreadsheet='fixture-main',destination_sheet='PokerStars')
        result,calls=self.snapshot([(request,'','')])
        self.assertNotIn('GoldBet',calls)
        self.assertEqual(result['scan_keys'],{('fixture-main',n) for n in ('PokerStars','Sisal Sport','MyLotteriesPlay')})
        self.assertEqual(set(calls),{'PokerStars','Sisal Sport','MyLotteriesPlay'})

    def test_explicit_historical_destination_is_still_checked(self):
        request=SimpleNamespace(destination_spreadsheet='fixture-archive',destination_sheet='GoldBet Old')
        result,calls=self.snapshot([(request,'','')])
        self.assertEqual(calls,['GoldBet Old'])
        self.assertIn(('fixture-archive','GoldBet Old'),result['tables'])
        self.assertEqual(result['scan_keys'],set())
