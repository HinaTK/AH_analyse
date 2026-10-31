import unittest
from confirmed_589720 import build

class ETFTests(unittest.TestCase):
    def test_code_and_labels_are_derived(self):
        rows=[('buy',4600,'1.28'),('buy',4700,'1.273'),('buy',4800,'1.197'),('buy',5100,'1.169'),('sell',5100,'1.193'),('buy',5100,'1.156'),('sell',5100,'1.180'),('buy',5100,'1.157'),('buy',5200,'1.142'),('buy',4600,'1.120'),('buy',5400,'1.093'),('sell',5400,'1.115'),('buy',5400,'1.103')]
        r=build(rows,code='sz159363',name='创业板人工智能ETF华宝')
        self.assertEqual(len(r['trades']),13)
        self.assertEqual([t['lot'] for t in r['trades']],list('ABCDDD DDEFGGG'.replace(' ','')))
        self.assertEqual(r['max_grid'],'G')
        self.assertEqual(len(r['t_records']),3)
        self.assertTrue(all(t['id'].startswith('159363-') for t in r['trades']))
        self.assertTrue(all(t['date'] is None for t in r['trades']))

if __name__=='__main__': unittest.main()
